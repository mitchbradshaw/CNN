"""
test_materialize_channels.py
==============================
Tests for Pipelines/materialize_channels/materialize_channels.py: fs
derivation from filename, uniform-length verification (and rejection when
it fails), dtype preservation, correct global_offset bookkeeping, and
resumability.

Writes a synthetic recording under a temp `raw_dir`, but the extracted
channel .npy files land under the real DATA/derived/channels/<stem>/ (that
path is a module-level constant in materialize_channels.py, matching how
the rest of the codebase hardcodes DATA/ locations) — so every test uses a
distinctive stem and cleans its output directory up in `finally`. Nothing
under DATA/raw/ is touched.

Run from the project root:
    python tests/test_materialize_channels.py
"""

import inspect
import os
import shutil
import sys
import tempfile
import time

import numpy as np
import scipy.io

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.Preprocessing.manage_data.load_data import CHANNEL_DIR
from Working.Preprocessing.database.queries import list_recordings
from Pipelines.materialize_channels.materialize_channels import (
    N_CHANNELS,
    _derive_fs,
    materialize_all,
)

STEM_GOOD = "UNITTEST_materialize_good_fs1"
STEM_BAD_DIVISION = "UNITTEST_materialize_baddivision_fs1"


def _cleanup(stem):
    # This repo lives inside a synced Google Drive folder, which can hold a
    # transient lock on just-written/-deleted files — retry briefly rather
    # than fail the test on a sync race.
    out_dir = os.path.join(CHANNEL_DIR, stem)
    if not os.path.isdir(out_dir):
        return
    for attempt in range(5):
        try:
            shutil.rmtree(out_dir)
            return
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.3)


# ── fs derivation ────────────────────────────────────────────────────────────

def test_derive_fs_integer():
    assert _derive_fs("M2_aug_concat_fs2") == 2.0


def test_derive_fs_from_good_stem():
    assert _derive_fs(STEM_GOOD) == 1.0


def test_derive_fs_missing_suffix_raises():
    try:
        _derive_fs("no_fs_suffix_here")
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── end-to-end extraction ───────────────────────────────────────────────────

def test_materialize_splits_channels_correctly_and_preserves_dtype():
    _cleanup(STEM_GOOD)
    try:
        with tempfile.TemporaryDirectory() as raw_dir:
            total, n_ch = 32, N_CHANNELS  # L = 2
            vector = np.arange(total, dtype=np.float32).reshape(-1, 1)
            mat_path = os.path.join(raw_dir, f"{STEM_GOOD}.mat")
            scipy.io.savemat(mat_path, {"x": vector})

            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                db_path = tf.name
            try:
                conn = materialize_all(raw_dir=raw_dir, db_path=db_path)

                L = total // n_ch
                out_dir = os.path.join(CHANNEL_DIR, STEM_GOOD)
                for ch in range(n_ch):
                    arr = np.load(os.path.join(out_dir, f"CH{ch}.npy"))
                    expected = np.arange(ch * L, (ch + 1) * L, dtype=np.float32)
                    assert np.array_equal(arr, expected), (ch, arr, expected)
                    assert arr.dtype == np.float32

                rows = list_recordings(conn, source_file=f"{STEM_GOOD}.mat")
                assert len(rows) == n_ch
                by_channel = {r["channel"]: r for r in rows}
                for ch in range(n_ch):
                    r = by_channel[ch]
                    assert r["n_samples"] == L
                    assert r["global_offset"] == ch * L
                    assert r["fs"] == 1.0
                conn.close()
            finally:
                os.unlink(db_path)
    finally:
        _cleanup(STEM_GOOD)


def test_materialize_is_resumable_no_duplicate_rows():
    _cleanup(STEM_GOOD)
    try:
        with tempfile.TemporaryDirectory() as raw_dir:
            total = 32
            vector = np.arange(total, dtype=np.float64).reshape(-1, 1)
            mat_path = os.path.join(raw_dir, f"{STEM_GOOD}.mat")
            scipy.io.savemat(mat_path, {"x": vector})

            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                db_path = tf.name
            try:
                materialize_all(raw_dir=raw_dir, db_path=db_path).close()
                conn = materialize_all(raw_dir=raw_dir, db_path=db_path)  # re-run
                rows = list_recordings(conn, source_file=f"{STEM_GOOD}.mat")
                assert len(rows) == N_CHANNELS
                conn.close()
            finally:
                os.unlink(db_path)
    finally:
        _cleanup(STEM_GOOD)


def test_materialize_rejects_non_uniform_division():
    _cleanup(STEM_BAD_DIVISION)
    try:
        with tempfile.TemporaryDirectory() as raw_dir:
            total = 30  # not divisible by 16
            vector = np.arange(total, dtype=np.float64).reshape(-1, 1)
            mat_path = os.path.join(raw_dir, f"{STEM_BAD_DIVISION}.mat")
            scipy.io.savemat(mat_path, {"x": vector})

            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                db_path = tf.name
            try:
                conn = materialize_all(raw_dir=raw_dir, db_path=db_path)
                rows = list_recordings(conn, source_file=f"{STEM_BAD_DIVISION}.mat")
                assert len(rows) == 0
                assert not os.path.isdir(os.path.join(CHANNEL_DIR, STEM_BAD_DIVISION))
                conn.close()
            finally:
                os.unlink(db_path)
    finally:
        _cleanup(STEM_BAD_DIVISION)


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
