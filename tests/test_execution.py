"""
test_execution.py
====================
Tests for Working/execution.py (execute_recipe) against real materialized
channel data: run idempotency (a second identical run is reused, not
recomputed), crash-safety (a failing step leaves the run marked 'failed'
with a traceback, never half-written), and the O(n^2) encoding guard
(a span over an adapter's declared max_span_samples is refused before any
computation is attempted).

Run from the project root:
    python tests/test_execution.py
"""

import inspect
import os
import shutil
import sys
import tempfile

import numpy as np
import pytest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.execution import RecipeCancelled, RecipeExecutionError, execute_recipe
from Working.recipes import make_recipe

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_db_with_recording():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    q.insert_recording(conn, "M2_aug_concat_fs1.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    conn.close()
    return tf.name


def _fresh_db_with_synthetic_recording(n_samples, fs=1.0):
    """A tiny synthetic channel + fresh db, for tests that need `execute_recipe`
    to actually run an adapter but don't want to depend on the real channel
    data (`_channel_available()`). Returns (db_path, tmpdir); caller cleans up
    tmpdir (which also holds the .sqlite file)."""
    tmpdir = tempfile.mkdtemp(prefix="t08_test_")
    npy_path = os.path.join(tmpdir, "CH0.npy")
    np.save(npy_path, np.random.default_rng(0).standard_normal(n_samples))
    db_path = os.path.join(tmpdir, "test.sqlite")
    conn = init_db(db_path)
    q.insert_recording(conn, "fake.mat", 0, fs, n_samples, 0, npy_path)
    conn.close()
    return db_path, tmpdir


# ── idempotency ──────────────────────────────────────────────────────────────

def test_identical_recipe_reuses_prior_run():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    db_path = _fresh_db_with_recording()
    try:
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
        ], span=(100000, 100600))

        first = execute_recipe(recipe, db_path=db_path)
        second = execute_recipe(recipe, db_path=db_path)

        assert first["reused"] is False
        assert second["reused"] is True
        assert second["run_id"] == first["run_id"]
        assert second["config_hash"] == first["config_hash"]

        conn = init_db(db_path)
        assert len(R.list_runs(conn)) == 1  # no duplicate run row
        conn.close()
    finally:
        os.unlink(db_path)


def test_force_recomputes_even_when_identical():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    db_path = _fresh_db_with_recording()
    try:
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
        ], span=(100000, 100600))
        execute_recipe(recipe, db_path=db_path)
        forced = execute_recipe(recipe, db_path=db_path, force=True)
        assert forced["reused"] is False

        conn = init_db(db_path)
        # force=True still creates a second run row (not a silent overwrite)
        assert len(R.list_runs(conn)) == 2
        conn.close()
    finally:
        os.unlink(db_path)


def test_different_params_are_independent_runs():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    db_path = _fresh_db_with_recording()
    try:
        r1 = make_recipe(1, [{"stage": "preprocessing", "algorithm": "lowpass",
                               "params": {"cutoff_hz": 0.05}}], span=(100000, 100600))
        r2 = make_recipe(1, [{"stage": "preprocessing", "algorithm": "lowpass",
                               "params": {"cutoff_hz": 0.06}}], span=(100000, 100600))
        out1 = execute_recipe(r1, db_path=db_path)
        out2 = execute_recipe(r2, db_path=db_path)
        assert out1["run_id"] != out2["run_id"]
        assert out1["config_hash"] != out2["config_hash"]
    finally:
        os.unlink(db_path)


# ── crash-safety ─────────────────────────────────────────────────────────────

def test_failing_step_marks_run_failed_with_traceback():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    db_path = _fresh_db_with_recording()
    try:
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "bandpass",
             "params": {"low_hz": 0.5, "high_hz": 0.1}},  # low >= high -> adapter raises
        ], span=(100000, 100600))

        try:
            execute_recipe(recipe, db_path=db_path)
            assert False, "expected RecipeExecutionError"
        except RecipeExecutionError:
            pass

        conn = init_db(db_path)
        runs = R.list_runs(conn)
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        assert runs[0]["error_text"] is not None
        assert "ValueError" in runs[0]["error_text"]
        conn.close()
    finally:
        os.unlink(db_path)


def test_unknown_recording_raises_before_any_run_row():
    db_path_tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    db_path_tf.close()
    db_path = db_path_tf.name
    try:
        init_db(db_path).close()  # no recordings inserted
        recipe = make_recipe(999, [
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {}},
        ], span=(0, 100))
        try:
            execute_recipe(recipe, db_path=db_path)
            assert False, "expected ValueError"
        except ValueError:
            pass
        conn = init_db(db_path)
        assert len(R.list_runs(conn)) == 0
        conn.close()
    finally:
        os.unlink(db_path)


# ── O(n^2) guard ─────────────────────────────────────────────────────────────

def test_oversized_span_refused_for_bounded_adapter():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    db_path = _fresh_db_with_recording()
    try:
        recipe = make_recipe(1, [
            {"stage": "catalogue", "algorithm": "gramian_gasf", "params": {}},
        ], span=(0, REAL_L))  # whole channel: 2.6M samples, way over the 5000 cap

        try:
            execute_recipe(recipe, db_path=db_path)
            assert False, "expected RecipeExecutionError from the O(n^2) guard"
        except RecipeExecutionError as e:
            assert "max_span_samples" in str(e)

        conn = init_db(db_path)
        runs = R.list_runs(conn)
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        conn.close()
    finally:
        os.unlink(db_path)


def test_bounded_span_allowed_for_same_adapter():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    db_path = _fresh_db_with_recording()
    try:
        recipe = make_recipe(1, [
            {"stage": "catalogue", "algorithm": "gramian_gasf", "params": {}},
        ], span=(100000, 100600))  # 600 samples, well under the cap
        out = execute_recipe(recipe, db_path=db_path)
        assert out["reused"] is False
        assert out["result"].value.values.shape == (600, 600)
    finally:
        os.unlink(db_path)


def test_unbounded_adapter_accepts_large_span():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    db_path = _fresh_db_with_recording()
    try:
        # lowpass has no max_span_samples -- a large span must not be refused.
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
        ], span=(0, 200_000))
        out = execute_recipe(recipe, db_path=db_path)
        assert out["reused"] is False
    finally:
        os.unlink(db_path)


# ── typed dispatch (Scores / WindowSet / SpanSet), persist decoupled from
#    output_kind ──────────────────────────────────────────────────────────────

def test_matrix_profile_declares_scores_and_persists_artifact():
    import Adapters.detection_matrix_profile as mp_adapter

    db_path, tmpdir = _fresh_db_with_synthetic_recording(200)
    results_dir = os.path.join(tmpdir, "results")
    prior_results_dir = mp_adapter.RESULTS_DIR
    mp_adapter.RESULTS_DIR = results_dir
    try:
        recipe = make_recipe(1, [
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": 0.1, "backend": "stump"}},
        ], span=(0, 200))
        out = execute_recipe(recipe, db_path=db_path)

        assert out["result"].output_kind == "scores"
        assert len(out["result"].value.values) == 200  # matches the analysed span

        conn = init_db(db_path)
        artifacts = R.list_artifacts(conn, out["run_id"])
        conn.close()
        assert len(artifacts) == 1
        assert artifacts[0]["kind"] == "encoding"
    finally:
        mp_adapter.RESULTS_DIR = prior_results_dir
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_window_matrix_declares_windowset_and_persists_artifact():
    import Adapters.preprocessing_window_matrix as wm_adapter

    db_path, tmpdir = _fresh_db_with_synthetic_recording(400)
    results_dir = os.path.join(tmpdir, "results")
    prior_results_dir = wm_adapter.RESULTS_DIR
    wm_adapter.RESULTS_DIR = results_dir
    try:
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "window_matrix",
             "params": {"window_min": 1.0, "step_frac": 1.0, "catch22": True,
                        "fast_entropy": False, "slow_entropy": False,
                        "cnn": False, "rf": False}},
        ], span=(0, 400))
        out = execute_recipe(recipe, db_path=db_path)

        assert out["result"].output_kind == "windowset"
        window_set = out["result"].value
        assert len(window_set.starts) >= 3  # WM_MIN_WINDOWS
        assert window_set.features is not None
        assert len(window_set.features) == len(window_set.starts)  # no timepoint alignment

        conn = init_db(db_path)
        artifacts = R.list_artifacts(conn, out["run_id"])
        conn.close()
        assert len(artifacts) == 1
        assert artifacts[0]["kind"] == "encoding"
    finally:
        wm_adapter.RESULTS_DIR = prior_results_dir
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_matrix_profile_to_threshold_chain_writes_detections():
    import Adapters.detection_matrix_profile as mp_adapter

    db_path, tmpdir = _fresh_db_with_synthetic_recording(200)
    prior_results_dir = mp_adapter.RESULTS_DIR
    mp_adapter.RESULTS_DIR = os.path.join(tmpdir, "results")
    try:
        # mp distances are always >= 0, so threshold=-1.0 makes every
        # non-NaN mp value pass -> one deterministic contiguous span.
        recipe = make_recipe(1, [
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": 0.1, "backend": "stump"}},
            {"stage": "detection", "algorithm": "threshold",
             "params": {"threshold": -1.0}},
        ], span=(0, 200))
        out = execute_recipe(recipe, db_path=db_path)

        assert out["detections_written"] == 1
        conn = init_db(db_path)
        dets = R.list_detections(conn, out["run_id"])
        conn.close()
        assert len(dets) == 1
        assert dets[0]["start_idx"] == 0
        assert dets[0]["end_idx"] == 200 - 6 + 1  # m=6 for window_min=0.1 at fs=1.0
    finally:
        mp_adapter.RESULTS_DIR = prior_results_dir
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── T24: run-row status/current-step, per-stage emission, cancellation ───────

def test_run_row_tracks_current_step_and_emits_stage_results():
    """AC1 + AC3: the run row carries `current_step` as a run progresses so a
    poller can read it, and each stage's typed result is emitted via
    `on_step_result` as it lands rather than accumulated to the end."""
    db_path, tmpdir = _fresh_db_with_synthetic_recording(200)
    try:
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
        ], span=(0, 200))

        observed_current_steps = []
        emitted = []

        def on_progress(i, n, s, a):
            conn = init_db(db_path)
            try:
                run = R.list_runs(conn)[0]  # the only run row
                observed_current_steps.append(run["current_step"])
            finally:
                conn.close()

        def on_step_result(i, result):
            emitted.append((i, result.output_kind))

        out = execute_recipe(
            recipe, db_path=db_path,
            on_progress=on_progress, on_step_result=on_step_result,
        )

        assert observed_current_steps == [0, 1], (
            f"a poller should see current_step advance 0 then 1, got {observed_current_steps}"
        )
        assert emitted == [(0, "signal"), (1, "signal")], (
            f"each stage result should be emitted as it lands, got {emitted}"
        )

        conn = init_db(db_path)
        try:
            run = R.get_run(conn, out["run_id"])
            assert run["status"] == "completed"
            assert run["current_step"] == 1
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cancellation_marks_run_failed_with_note_and_current_step():
    """AC2: cooperative cancellation between steps marks the run failed with
    a note rather than leaving it half-written, and the run row still shows
    the last step that actually started."""
    db_path, tmpdir = _fresh_db_with_synthetic_recording(200)
    try:
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
        ], span=(0, 200))

        calls = {"n": 0}

        def should_cancel():
            calls["n"] += 1
            return calls["n"] >= 2  # cancel before the second step

        try:
            execute_recipe(recipe, db_path=db_path, should_cancel=should_cancel)
            assert False, "expected RecipeCancelled"
        except RecipeCancelled:
            pass

        conn = init_db(db_path)
        try:
            run = R.list_runs(conn)[0]
            assert run["status"] == "failed"
            assert "Cancelled" in run["error_text"]
            assert run["current_step"] == 0  # step 0 started; step 1 never did
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_invalid_chain_raises_before_any_run_row():
    """AC4: chain validation hard-fails before the first step, so an invalid
    recipe (here: a hand-edited dict that bypasses make_recipe's own check)
    never starts computing and never creates a run row."""
    db_path, tmpdir = _fresh_db_with_synthetic_recording(200)
    try:
        # lowpass produces a signal; threshold expects Scores. Validated only
        # at execution because this recipe was built by hand, not make_recipe.
        recipe = {
            "recording_id": 1,
            "span": [0, 200],
            "steps": [
                {"stage": "preprocessing", "algorithm": "lowpass",
                 "params": {"cutoff_hz": 0.05}},
                {"stage": "detection", "algorithm": "threshold",
                 "params": {"threshold": -1.0}},
            ],
        }

        try:
            execute_recipe(recipe, db_path=db_path)
            assert False, "expected ValueError from chain validation"
        except ValueError as e:
            assert "Invalid chain" in str(e)

        conn = init_db(db_path)
        try:
            assert len(R.list_runs(conn)) == 0, "an invalid chain must never create a run row"
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_step_and_intra_step_progress_both_fire():
    """AC5: the step-level on_progress and the finer intra-step
    run_kwargs['on_progress'] are two distinct callbacks with distinct
    signatures, and both fire."""
    import Adapters.preprocessing_window_matrix as wm_adapter

    db_path, tmpdir = _fresh_db_with_synthetic_recording(400)
    results_dir = os.path.join(tmpdir, "results")
    prior_results_dir = wm_adapter.RESULTS_DIR
    wm_adapter.RESULTS_DIR = results_dir
    try:
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "window_matrix",
             "params": {"window_min": 1.0, "step_frac": 1.0, "catch22": True,
                        "fast_entropy": False, "slow_entropy": False,
                        "cnn": False, "rf": False}},
        ], span=(0, 400))

        step_progress = []
        intra_progress = []

        def on_progress(i, n, s, a):
            step_progress.append((i, n, s, a))

        def intra(done, total, stage):
            intra_progress.append((done, total, stage))

        out = execute_recipe(
            recipe, db_path=db_path,
            on_progress=on_progress,
            run_kwargs={"on_progress": intra},
        )

        assert out["reused"] is False
        assert step_progress, "step-level on_progress must fire once per step"
        assert len(step_progress[0]) == 4, "step-level signature: (i, n, stage, algorithm)"
        assert intra_progress, "intra-step run_kwargs['on_progress'] must fire"
        assert len(intra_progress[0]) == 3, "intra-step signature: (done, total, stage)"
    finally:
        wm_adapter.RESULTS_DIR = prior_results_dir
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── runner ───────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, skipped, failed = 0, 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except pytest.skip.Exception as e:
            # `Skipped` derives from BaseException, not Exception, so it would
            # sail past the handler below and abort the whole standalone run on
            # the first guarded test. Absent data is a skip here too, not a pass.
            print(f"[SKIP] {fn.__name__}: {e}")
            skipped += 1
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    tally = f"{passed}/{len(fns)} passed"
    if skipped:
        # Never fold skips into the pass count: "all green" and "the data
        # was not there" are the two readings this file exists to keep
        # apart.
        tally += f", {skipped} skipped (real channel data absent)"
    print(f"\n{tally}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
