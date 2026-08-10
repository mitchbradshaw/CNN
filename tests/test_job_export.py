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
