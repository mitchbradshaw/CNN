"""
test_job_export.py
====================
Tests for Working/hpc/job_export.py: the generated recipe JSON is
loadable by Pipelines/run_recipe/run_recipe.py's own loader (the actual
contract), the sbatch script carries the resolved --chdir/--time/
--job-name, re-exporting an identical job overwrites rather than
accumulating, and a different job gets a different (non-colliding) file
pair.

Run from the project root:
    python tests/test_job_export.py
"""

import inspect
import json
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.config import HPC_REMOTE_REPO_ROOT
from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import window_matrix_store as wm_store
from Working.hpc.job_export import export_mp_job, export_wm_job
from Pipelines.run_recipe.run_recipe import load_recipe_from_file


def _fresh_conn_with_recording():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    recording_id = q.insert_recording(conn, "fake_hpc.mat", 0, 1.0, 100_000, 0, "fake/CH0.npy")
    return conn, tf.name, recording_id


def test_recipe_json_is_loadable_by_run_recipe():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            result = export_mp_job(conn, recording_id, 10.0, out_dir=out_dir)
            recipe = load_recipe_from_file(result["recipe_path"])
            assert recipe["recording_id"] == recording_id
            assert recipe["span"] is None
            assert recipe["steps"] == [{
                "stage": "detection", "algorithm": "matrix_profile",
                "params": {"window_min": 10.0, "backend": "auto"},
                "side_inputs": {},
            }]
    finally:
        conn.close()
        os.unlink(db_path)


def test_script_contains_resolved_chdir_and_job_name():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            result = export_mp_job(conn, recording_id, 34.0, out_dir=out_dir)
            with open(result["script_path"]) as f:
                script = f.read()
            assert f"--chdir={HPC_REMOTE_REPO_ROOT}" in script
            assert f"--job-name={result['job_name']}" in script
            assert result["job_name"] == "mp_CH0_WIN34min"
            assert "run_recipe.py --config" in script
            # Path baked into the script is forward-slashed and repo-relative.
            assert "\\" not in script.split("run_recipe.py --config", 1)[1].splitlines()[0]
    finally:
        conn.close()
        os.unlink(db_path)


def test_time_floors_at_30_minutes_when_uncalibrated():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            result = export_mp_job(conn, recording_id, 1.0, out_dir=out_dir, est_seconds=None)
            with open(result["script_path"]) as f:
                script = f.read()
            assert "--time=00:30:00" in script
    finally:
        conn.close()
        os.unlink(db_path)


def test_time_is_3x_estimate_rounded_up_to_15min():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            # 1000s * 3 = 3000s = 50 min -> rounded up to 60 min.
            result = export_mp_job(conn, recording_id, 1.0, out_dir=out_dir, est_seconds=1000)
            with open(result["script_path"]) as f:
                script = f.read()
            assert "--time=01:00:00" in script
    finally:
        conn.close()
        os.unlink(db_path)


def test_reexporting_identical_job_overwrites_not_accumulates():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            r1 = export_mp_job(conn, recording_id, 10.0, out_dir=out_dir)
            r2 = export_mp_job(conn, recording_id, 10.0, out_dir=out_dir)
            assert r1["recipe_path"] == r2["recipe_path"]
            assert r1["script_path"] == r2["script_path"]
            files = os.listdir(out_dir)
            assert len([f for f in files if f.endswith(".json")]) == 1
            assert len([f for f in files if f.endswith(".sh")]) == 1
    finally:
        conn.close()
        os.unlink(db_path)


def test_different_window_min_produces_different_files():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            r1 = export_mp_job(conn, recording_id, 10.0, out_dir=out_dir)
            r2 = export_mp_job(conn, recording_id, 60.0, out_dir=out_dir)
            assert r1["recipe_path"] != r2["recipe_path"]
            assert r1["script_path"] != r2["script_path"]
            assert os.path.isfile(r1["recipe_path"]) and os.path.isfile(r2["recipe_path"])
    finally:
        conn.close()
        os.unlink(db_path)


def test_unknown_recording_raises():
    conn, db_path, _recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            try:
                export_mp_job(conn, 9999, 10.0, out_dir=out_dir)
                assert False, "expected ValueError"
            except ValueError:
                pass
    finally:
        conn.close()
        os.unlink(db_path)


# ── export_wm_job (WINDOW_MATRIX_UI_PROMPT.md §7) ────────────────────────────

def test_wm_recipe_json_is_loadable_and_resume_path_matches_the_store():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            result = export_wm_job(conn, recording_id, 10.0, out_dir=out_dir,
                                   stages=("catch22", "fast_entropy"))
            recipe = load_recipe_from_file(result["recipe_path"])
            assert recipe["recording_id"] == recording_id
            params = recipe["steps"][0]["params"]
            # The resume path baked into the recipe is exactly what save_wm
            # would write for this (recording, geometry) -- WINDOW_MATRIX_UI_PROMPT.md
            # §7: the recipe must never change across a resubmit chain, and
            # this is the value that has to stay stable.
            expected_stem = wm_store.artifact_name("fake_hpc", 0, 10.0, 1.0)
            assert params["resume_path"].endswith(f"{expected_stem}.npz")
            assert params["resume_path"] == result["artifact_path"].replace(os.sep, "/")
    finally:
        conn.close()
        os.unlink(db_path)


def test_wm_gpu_line_present_only_with_cnn_stage():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            no_cnn = export_wm_job(conn, recording_id, 10.0, out_dir=out_dir,
                                   stages=("catch22", "fast_entropy"))
            with open(no_cnn["script_path"]) as f:
                script_no_cnn = f.read()
            assert "--gres=gpu:a100" not in script_no_cnn

            with_cnn = export_wm_job(conn, recording_id, 60.0, out_dir=out_dir,
                                     stages=("catch22", "cnn"))
            with open(with_cnn["script_path"]) as f:
                script_with_cnn = f.read()
            assert "--gres=gpu:a100" in script_with_cnn
    finally:
        conn.close()
        os.unlink(db_path)


def test_wm_chain_cap_and_force_are_present():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            result = export_wm_job(conn, recording_id, 10.0, out_dir=out_dir, max_chain=7)
            with open(result["script_path"]) as f:
                script = f.read()
            assert "MAX_CHAIN=7" in script
            assert "run_recipe.py --config" in script and "--force" in script
            # Resubmits itself, passing the incremented chain position.
            assert 'sbatch "$(pwd)/HPC/Preprocessing/generated/' in script or "sbatch " in script
            assert "NEXT=$((CHAIN_INDEX + 1))" in script
            assert "wm_status.py --artifact" in script
    finally:
        conn.close()
        os.unlink(db_path)


def test_wm_reexporting_identical_job_overwrites_not_accumulates():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            r1 = export_wm_job(conn, recording_id, 10.0, out_dir=out_dir)
            r2 = export_wm_job(conn, recording_id, 10.0, out_dir=out_dir)
            assert r1["recipe_path"] == r2["recipe_path"]
            assert r1["script_path"] == r2["script_path"]
            files = os.listdir(out_dir)
            assert len([f for f in files if f.endswith(".json")]) == 1
            assert len([f for f in files if f.endswith(".sh")]) == 1
    finally:
        conn.close()
        os.unlink(db_path)


def test_wm_timeout_is_slurm_wall_clock_minus_cleanup_margin():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            # 30-minute floor (uncalibrated) -> 1800s - 300s margin = 1500s.
            result = export_wm_job(conn, recording_id, 10.0, out_dir=out_dir, est_seconds=None)
            assert result["slurm_time"] == "00:30:00"
            assert result["timeout_s"] == 1500.0
            recipe = load_recipe_from_file(result["recipe_path"])
            assert recipe["steps"][0]["params"]["timeout_s"] == 1500.0
    finally:
        conn.close()
        os.unlink(db_path)


def test_wm_unknown_recording_raises():
    conn, db_path, _recording_id = _fresh_conn_with_recording()
    try:
        with tempfile.TemporaryDirectory() as out_dir:
            try:
                export_wm_job(conn, 9999, 10.0, out_dir=out_dir)
                assert False, "expected ValueError"
            except ValueError:
                pass
    finally:
        conn.close()
        os.unlink(db_path)


# ── T26: runtime estimators, cluster routing, SLURM array export ────────────

def test_both_expensive_adapters_declare_estimate_delegating_to_cost():
    """detection.matrix_profile and preprocessing.window_matrix both declare
    `estimate`, delegating to their existing cost module (PRD "Cluster
    routing"). Uncalibrated -> None, the same 'counts as free' semantics the
    cost modules already use."""
    from Adapters import detection_matrix_profile as mp_adapter
    from Adapters import preprocessing_window_matrix as wm_adapter
    from Working.Detection.matrix_profiling import cost as mp_cost
    from Working.Preprocessing.window_matrix import cost as wm_cost
    from tests._calibration_isolation import scratch_calibration

    assert mp_adapter.SPEC.estimate is not None
    assert wm_adapter.SPEC.estimate is not None

    span = [0.0] * 100_000
    with scratch_calibration(mp_cost, wm_cost):
        assert mp_adapter.SPEC.estimate(span, None, 1.0) is None
        assert wm_adapter.SPEC.estimate(span, None, 1.0) is None

    with scratch_calibration(mp_cost):
        mp_cost.calibrate("stump", n0=2000)
        est = mp_adapter.SPEC.estimate(span, None, 1.0)
        assert est == mp_cost.estimate_seconds(100_000, "auto")

    with scratch_calibration(wm_cost):
        wm_cost.calibrate(stages=("catch22",))
        # The adapter's estimate delegates to the cost module, so only the
        # calibrated stage is selected -- fast_entropy/slow_entropy would
        # return None (uncalibrated) and the whole estimate is None.
        est_wm = wm_adapter.SPEC.estimate(
            span, None, 1.0, window_min=1.0,
            fast_entropy=False, slow_entropy=False,
        )
        assert est_wm is not None and est_wm > 0


def test_chain_estimate_sums_per_step_and_multiplies_by_fanout_width():
    """The chain estimate is the sum of per-step estimates (a block with no
    estimator contributes zero), multiplied by fan-out width."""
    from Working.hpc.job_export import estimate_recipe_seconds
    from Working.recipes import make_recipe
    from Working.Detection.matrix_profiling import cost as mp_cost
    from tests._calibration_isolation import scratch_calibration

    with scratch_calibration(mp_cost):
        mp_cost.calibrate("stump", n0=2000)
        # detrend has no estimator -> contributes zero; matrix_profile
        # contributes its calibrated estimate.
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "detrend",
             "params": {"mode": "linear", "window_s": 0.01}},
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": 10.0, "backend": "stump"}},
        ], span=[0, 4000])
        single = estimate_recipe_seconds(recipe, 4000, 1.0)
        assert single == mp_cost.estimate_seconds(4000, "stump")

        fan = make_recipe(1, [
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": 10.0, "backend": "stump"}},
        ], span=[0, 4000], fan_out={"kind": "channels", "targets": [1, 2, 3]})
        assert estimate_recipe_seconds(fan, 4000, 1.0) == 3 * single


def test_routing_decision_returns_cluster_above_the_configured_ceiling():
    """Above the configured ceiling the routing decision is the value
    'cluster' -- a headless value a run surface reads, not UI logic."""
    from Working.hpc.job_export import route_recipe
    from Working.recipes import make_recipe
    from Working.Detection.matrix_profiling import cost as mp_cost
    from tests._calibration_isolation import scratch_calibration

    with scratch_calibration(mp_cost):
        mp_cost.calibrate("stump", n0=2000)
        recipe = make_recipe(1, [
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": 10.0, "backend": "stump"}},
        ], span=[0, 100_000])
        est = mp_cost.estimate_seconds(100_000, "stump")
        assert est is not None
        assert route_recipe(recipe, 100_000, 1.0, ceiling_s=est / 2) == "cluster"
        assert route_recipe(recipe, 100_000, 1.0, ceiling_s=est * 2) == "local"


def test_fanout_exports_as_a_single_slurm_array_job():
    """A fan-out over N targets exports as ONE SLURM array job whose task
    index selects its target from the recipe's baked-in list."""
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        other_id = q.insert_recording(conn, "other_hpc.mat", 1, 1.0, 100_000, 0, "fake/CH1.npy")
        with tempfile.TemporaryDirectory() as out_dir:
            result = export_mp_job(conn, recording_id, 10.0, out_dir=out_dir,
                                   fan_out={"kind": "channels", "targets": [recording_id, other_id]})
            with open(result["script_path"]) as f:
                script = f.read()
            assert "#SBATCH --array=0-1" in script
            assert "$SLURM_ARRAY_TASK_ID" in script
            assert "materialize_target" in script
            assert "run_recipe.py --config" in script
            with open(result["recipe_path"]) as f:
                data = json.load(f)
            assert data["fan_out"] == {"kind": "channels", "targets": [recording_id, other_id]}
    finally:
        conn.close()
        os.unlink(db_path)


def test_array_job_task_index_selects_its_target_from_the_recipe():
    from Working.run_groups import materialize_target

    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        other_id = q.insert_recording(conn, "other_hpc.mat", 1, 1.0, 100_000, 0, "fake/CH1.npy")
        with tempfile.TemporaryDirectory() as out_dir:
            result = export_mp_job(conn, recording_id, 10.0, out_dir=out_dir,
                                   fan_out={"kind": "channels", "targets": [recording_id, other_id]})
            with open(result["recipe_path"]) as f:
                data = json.load(f)
            assert materialize_target(data, 0)["recording_id"] == recording_id
            assert materialize_target(data, 1)["recording_id"] == other_id
            assert "fan_out" not in materialize_target(data, 0)
    finally:
        conn.close()
        os.unlink(db_path)


def test_generic_export_job_writes_an_array_job_for_a_fanout_recipe():
    """The generic `export_job` (the backend both bespoke exporters now wrap)
    handles the fan-out array case directly, preserving the 3x wall-time
    safety factor (30-minute uncalibrated floor)."""
    from Working.hpc.job_export import export_job
    from Working.database.runs import get_or_create_config
    from Working.recipes import make_recipe

    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        other_id = q.insert_recording(conn, "other_hpc.mat", 1, 1.0, 100_000, 0, "fake/CH1.npy")
        with tempfile.TemporaryDirectory() as out_dir:
            recipe = make_recipe(recording_id, [
                {"stage": "detection", "algorithm": "matrix_profile",
                 "params": {"window_min": 10.0, "backend": "auto"}},
            ], fan_out={"kind": "channels", "targets": [recording_id, other_id]})
            _config_id, hash8 = get_or_create_config(conn, recipe)
            result = export_job(recipe, out_dir=out_dir, base_name=f"arr_{hash8}",
                                job_name="arr", est_seconds=None)
            with open(result["script_path"]) as f:
                script = f.read()
            assert "#SBATCH --array=0-1" in script
            assert "$SLURM_ARRAY_TASK_ID" in script
            assert "materialize_target" in script
            assert "--time=00:30:00" in script  # 3x safety, 30-min floor
    finally:
        conn.close()
        os.unlink(db_path)


def test_wm_array_export_uses_the_chain_template_with_array_directive():
    conn, db_path, recording_id = _fresh_conn_with_recording()
    try:
        other_id = q.insert_recording(conn, "other_hpc.mat", 1, 1.0, 100_000, 0, "fake/CH1.npy")
        with tempfile.TemporaryDirectory() as out_dir:
            result = export_wm_job(conn, recording_id, 10.0, out_dir=out_dir,
                                   fan_out={"kind": "channels", "targets": [recording_id, other_id]})
            with open(result["script_path"]) as f:
                script = f.read()
            assert "#SBATCH --array=0-1" in script
            assert "wm_status.py --artifact" in script
            assert "sbatch --array=$SLURM_ARRAY_TASK_ID" in script
    finally:
        conn.close()
        os.unlink(db_path)


# ── runner ───────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
