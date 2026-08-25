"""
test_matrix_profile_store.py
==============================
Tests for Working/database/matrix_profile_store.py (the reuse/registry
query layer), against synthetic small artifacts — no dependency on real
multi-MB matrix-profile data or a GPU.

Run from the project root:
    python tests/test_matrix_profile_store.py
"""

import inspect
import os
import sys
import tempfile
import time

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database.runs import get_or_create_config, insert_artifact, insert_run, update_run
from Working.database import matrix_profile_store as store
from Working.recipes import make_recipe
from Pipelines.matrix_profile.run_matrix_profile import save_matrix_profile


# ── Fixtures ─────────────────────────────────────────────────────────────────

class _Fixture:
    """A fresh temp DB + a fake channel .npy on disk + a `recordings` row,
    cleaned up on `close()`."""

    def __init__(self, n_samples=10_000, fs=1.0):
        self.tmpdir = tempfile.mkdtemp(prefix="mp_store_test_")
        self.db_path = os.path.join(self.tmpdir, "test.sqlite")
        self.npy_path = os.path.join(self.tmpdir, "CH0.npy")
        self.n_samples = n_samples
        self.fs = fs
        np.save(self.npy_path, np.random.default_rng(0).standard_normal(n_samples))
        self.conn = init_db(self.db_path)
        self.recording_id = q.insert_recording(
            self.conn, "fake_rec.mat", 0, fs, n_samples, 0, self.npy_path
        )

    def register_mp(self, window_min, *, approx=False, m=None, backend="stump",
                     source_file="fake_rec.mat", channel=0, sha1=None):
        """Compute+register+save one synthetic MP artifact, exactly the
        shape a live run would produce, via the same `configs`/`runs`/
        `artifacts` path `execute_recipe` + the adapter's `persist` hook
        use."""
        if m is None:
            m = max(4, int(round(window_min * 60 * self.fs)))
        mp_len = max(1, self.n_samples - m + 1)
        rng = np.random.default_rng(hash((window_min, approx)) % (2**32))
        mp = rng.random(mp_len).astype(np.float32)
        mpi = np.zeros(mp_len, dtype=np.int32)

        recipe = make_recipe(self.recording_id, [
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": float(window_min)}},
        ], span=None)
        config_id, config_hash = get_or_create_config(self.conn, recipe)
        run_id = insert_run(self.conn, config_id, self.recording_id, 0, self.n_samples,
                             status="running")
        update_run(self.conn, run_id, status="completed", finished_at="2026-01-01T00:00:00Z",
                   duration_s=0.1)

        path = save_matrix_profile(
            mp, mpi, -np.ones(mp_len, dtype=np.int32), -np.ones(mp_len, dtype=np.int32),
            m, self.fs, window_min,
            source_file=source_file, channel=channel, n_samples=self.n_samples,
            data_sha1=sha1 if sha1 is not None else store.compute_data_sha1(self.npy_path),
            backend=backend, recording_id=self.recording_id, config_hash=config_hash,
            approx=approx, approx_percentage=(0.5 if approx else 1.0),
            out_dir=os.path.join(self.tmpdir, "mp_results"),
        )
        insert_artifact(self.conn, run_id, kind="encoding", path=path)
        return run_id, path

    def close(self):
        self.conn.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ── list_mp_runs / find_mp ──────────────────────────────────────────────────

def test_list_mp_runs_returns_registered_artifact():
    fx = _Fixture()
    try:
        run_id, path = fx.register_mp(10.0)
        rows = store.list_mp_runs(fx.conn, fx.recording_id)
        assert len(rows) == 1
        assert rows[0]["run_id"] == run_id
        assert rows[0]["artifact_path"] == path
        assert rows[0]["window_min"] == 10.0
        assert rows[0]["approx"] is False
        assert rows[0]["stale"] is False
    finally:
        fx.close()


def test_find_mp_hits_and_misses():
    fx = _Fixture()
    try:
        fx.register_mp(10.0)
        hit = store.find_mp(fx.conn, fx.recording_id, 10.0)
        assert hit is not None
        miss = store.find_mp(fx.conn, fx.recording_id, 60.0)
        assert miss is None
    finally:
        fx.close()


def test_require_exact_skips_approx_artifact():
    fx = _Fixture()
    try:
        fx.register_mp(10.0, approx=True)
        # An approx-only artifact is findable normally...
        loose = store.find_mp(fx.conn, fx.recording_id, 10.0, require_exact=False)
        assert loose is not None
        assert loose["approx"] is True
        # ...but never substituted when an exact profile was requested.
        strict = store.find_mp(fx.conn, fx.recording_id, 10.0, require_exact=True)
        assert strict is None
    finally:
        fx.close()


def test_find_mp_prefers_exact_over_approx():
    fx = _Fixture()
    try:
        fx.register_mp(10.0, approx=True)
        time.sleep(0.01)
        exact_run_id, _ = fx.register_mp(10.0, approx=False)
        best = store.find_mp(fx.conn, fx.recording_id, 10.0)
        assert best["run_id"] == exact_run_id
        assert best["approx"] is False
    finally:
        fx.close()


# ── staleness ────────────────────────────────────────────────────────────────

def test_stale_detection_after_touching_source_npy():
    fx = _Fixture()
    try:
        run_id, path = fx.register_mp(10.0)
        fresh = store.find_mp(fx.conn, fx.recording_id, 10.0)
        assert fresh["stale"] is False

        # Overwrite the source .npy with different content -> data_sha1 no
        # longer matches what's baked into the artifact.
        np.save(fx.npy_path, np.random.default_rng(999).standard_normal(fx.n_samples))

        stale = store.find_mp(fx.conn, fx.recording_id, 10.0)
        assert stale is not None
        assert stale["stale"] is True
        assert stale["run_id"] == run_id  # still returned, never silently dropped
    finally:
        fx.close()


# ── ladder_status ────────────────────────────────────────────────────────────

def test_ladder_status_reports_available_missing_and_invalid():
    fx = _Fixture(n_samples=10_000, fs=1.0)  # 1 min = 60 samples valid; 600 min invalid here
    try:
        fx.register_mp(1.0)  # the 1-minute rung: m=60 samples
        rows = store.ladder_status(fx.conn, fx.recording_id, fx.fs, fx.n_samples)
        by_window = {r["window_min"]: r for r in rows}

        assert by_window[1.0]["state"] == "available"
        assert by_window[10.0]["state"] == "missing"
        # 600 min at fs=1 -> m=36000 samples > n_samples(10000)//2 -> invalid
        assert by_window[600.0]["state"] == "invalid"
        assert "reason" in by_window[600.0] and by_window[600.0]["reason"]
        assert by_window[600.0]["run_id"] is None
    finally:
        fx.close()


def test_ladder_status_too_short_channel_marks_everything_invalid_or_missing():
    fx = _Fixture(n_samples=100, fs=1.0)  # even 1 min (m=60) barely fits; 10/60/600 min don't
    try:
        rows = store.ladder_status(fx.conn, fx.recording_id, fx.fs, fx.n_samples)
        by_window = {r["window_min"]: r for r in rows}
        for window_min in (10.0, 60.0, 600.0):
            assert by_window[window_min]["state"] == "invalid", window_min
    finally:
        fx.close()


def test_ladder_status_approx_state():
    fx = _Fixture()
    try:
        fx.register_mp(10.0, approx=True)
        rows = store.ladder_status(fx.conn, fx.recording_id, fx.fs, fx.n_samples)
        by_window = {r["window_min"]: r for r in rows}
        assert by_window[10.0]["state"] == "approx"
    finally:
        fx.close()


# ── load_mp ──────────────────────────────────────────────────────────────────

def test_load_mp_roundtrips_arrays():
    fx = _Fixture()
    try:
        _, path = fx.register_mp(10.0)
        data = store.load_mp(path)
        assert "mp" in data and "mpi" in data and "left_i" in data and "right_i" in data
        assert len(data["mp"]) == len(data["mpi"])
    finally:
        fx.close()


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
