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
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.execution import RecipeExecutionError, execute_recipe
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


# ── idempotency ──────────────────────────────────────────────────────────────

def test_identical_recipe_reuses_prior_run():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
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
        print("  (skipped: real channel data not present)")
        return
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
        print("  (skipped: real channel data not present)")
        return
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
        print("  (skipped: real channel data not present)")
        return
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
        print("  (skipped: real channel data not present)")
        return
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
        print("  (skipped: real channel data not present)")
        return
    db_path = _fresh_db_with_recording()
    try:
        recipe = make_recipe(1, [
            {"stage": "catalogue", "algorithm": "gramian_gasf", "params": {}},
        ], span=(100000, 100600))  # 600 samples, well under the cap
        out = execute_recipe(recipe, db_path=db_path)
        assert out["reused"] is False
        assert out["result"].encoding.shape == (600, 600)
    finally:
        os.unlink(db_path)


def test_unbounded_adapter_accepts_large_span():
    if not _channel_available():
        print("  (skipped: real channel data not present)")
        return
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
