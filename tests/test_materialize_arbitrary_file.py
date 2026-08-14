"""
test_materialize_arbitrary_file.py
=====================================
Tests for materialize_arbitrary_file (Part 4's backend): correct .mat/.csv
channel splitting with a *confirmed* (not assumed) channel count and fs, and
the atomicity guarantee -- a failure partway through must leave no orphaned
`.npy` files and no dangling `recordings` rows.

Run from the project root:
    python tests/test_materialize_arbitrary_file.py
"""

import inspect
import os
import shutil
import sys
import tempfile
import time

import numpy as np
import scipy.io

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.Preprocessing.manage_data.load_data import CHANNEL_DIR
from Working.database.queries import list_recordings
import Pipelines.materialize_channels.materialize_channels as mc

STEM_MAT = "UNITTEST_arbitrary_mat"
STEM_CSV = "UNITTEST_arbitrary_csv"
STEM_CRASH = "UNITTEST_arbitrary_crash"


def _cleanup(stem):
    out_dir = os.path.join(CHANNEL_DIR, stem)
    for attempt in range(5):
        try:
            if os.path.isdir(out_dir):
                shutil.rmtree(out_dir)
            return
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.3)


def test_detect_channel_count_mat_defaults_to_convention():
    with tempfile.TemporaryDirectory() as raw_dir:
        path = os.path.join(raw_dir, "x.mat")
        scipy.io.savemat(path, {"x": np.arange(16).reshape(-1, 1)})
        assert mc.detect_channel_count(path) == mc.N_CHANNELS


def test_detect_channel_count_csv_uses_column_count():
    with tempfile.TemporaryDirectory() as raw_dir:
        path = os.path.join(raw_dir, "x.csv")
        arr = np.arange(20).reshape(5, 4)
        np.savetxt(path, arr, delimiter=",")
        assert mc.detect_channel_count(path) == 4


def test_materialize_arbitrary_mat_respects_confirmed_overrides():
    _cleanup(STEM_MAT)
    try:
        with tempfile.TemporaryDirectory() as raw_dir:
            mat_path = os.path.join(raw_dir, f"{STEM_MAT}.mat")
            vector = np.arange(40, dtype=np.float32).reshape(-1, 1)
            scipy.io.savemat(mat_path, {"x": vector})

            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                db_path = tf.name
            try:
                conn = mc.init_db(db_path)
                # User confirms 4 channels (not the suggested default 16) and fs=3.0.
                summary = mc.materialize_arbitrary_file(conn, mat_path, n_channels=4, fs=3.0)
                assert summary == {
                    "stem": STEM_MAT, "n_channels": 4, "fs": 3.0,
                    "n_samples": 10, "dtype": "float32",
                }
                rows = list_recordings(conn, source_file=f"{STEM_MAT}.mat")
                assert len(rows) == 4
                assert all(r["fs"] == 3.0 for r in rows)
                ch2 = np.load(os.path.join(CHANNEL_DIR, STEM_MAT, "CH2.npy"))
                assert np.array_equal(ch2, np.arange(20, 30, dtype=np.float32))
                assert os.path.isfile(os.path.join(CHANNEL_DIR, STEM_MAT, "manifest.json"))
                conn.close()
            finally:
                os.unlink(db_path)
    finally:
        _cleanup(STEM_MAT)


def test_materialize_arbitrary_csv_one_column_per_channel():
    _cleanup(STEM_CSV)
    try:
        with tempfile.TemporaryDirectory() as raw_dir:
            csv_path = os.path.join(raw_dir, f"{STEM_CSV}.csv")
            arr = np.arange(12, dtype=np.float64).reshape(3, 4)  # 3 samples, 4 channels
            np.savetxt(csv_path, arr, delimiter=",")

            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                db_path = tf.name
            try:
                conn = mc.init_db(db_path)
                summary = mc.materialize_arbitrary_file(conn, csv_path, n_channels=4, fs=1.0)
                assert summary["n_samples"] == 3
                ch0 = np.load(os.path.join(CHANNEL_DIR, STEM_CSV, "CH0.npy"))
                assert np.array_equal(ch0, arr[:, 0])
                conn.close()
            finally:
                os.unlink(db_path)
    finally:
        _cleanup(STEM_CSV)


def test_materialize_arbitrary_file_rejects_bad_channel_count():
    with tempfile.TemporaryDirectory() as raw_dir:
        mat_path = os.path.join(raw_dir, "bad.mat")
        scipy.io.savemat(mat_path, {"x": np.arange(10).reshape(-1, 1)})
        try:
            mc._load_mat_channels(mat_path, n_channels=3)  # 10 % 3 != 0
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_materialize_arbitrary_file_atomic_on_failure():
    _cleanup(STEM_CRASH)
    try:
        with tempfile.TemporaryDirectory() as raw_dir:
            mat_path = os.path.join(raw_dir, f"{STEM_CRASH}.mat")
            scipy.io.savemat(mat_path, {"x": np.arange(40, dtype=np.float64).reshape(-1, 1)})

            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                db_path = tf.name
            try:
                conn = mc.init_db(db_path)

                def flaky(done, total):
                    if done == 3:
                        raise RuntimeError("simulated crash")

                try:
                    mc.materialize_arbitrary_file(conn, mat_path, n_channels=4, fs=1.0,
                                                   progress_callback=flaky)
                    assert False, "expected the simulated crash to propagate"
                except RuntimeError:
                    pass

                assert not os.path.isdir(os.path.join(CHANNEL_DIR, STEM_CRASH))
                leftover = [d for d in os.listdir(CHANNEL_DIR)
                            if d.startswith(f".staging_{STEM_CRASH}")]
                assert leftover == []
                assert list_recordings(conn, source_file=f"{STEM_CRASH}.mat") == []
                conn.close()
            finally:
                os.unlink(db_path)
    finally:
        _cleanup(STEM_CRASH)


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
