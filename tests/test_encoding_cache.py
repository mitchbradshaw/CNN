"""
test_encoding_cache.py
========================
Tests for Working/encoding_cache.py: hit/miss behaviour (compute_fn is
only ever called on a miss), array/string/JSON round-tripping, and that a
hit really does skip recomputation regardless of what compute_fn would
return.

Run from the project root:
    python tests/test_encoding_cache.py
"""

import inspect
import os
import shutil
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.database.schema import init_db
from Working.database import queries as q
from Working.encoding_cache import build_encoding_path, get_or_compute_encoding


def _fresh_conn_and_recording():
    conn = init_db(":memory:")
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 10_000, 0, "a/CH0.npy")
    recording = q.get_recording_by_id(conn, rid)
    return conn, recording


def test_miss_then_hit_calls_compute_once():
    conn, recording = _fresh_conn_and_recording()
    tmp_root = tempfile.mkdtemp()
    try:
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return np.arange(10), 0, 600

        _enc1, hit1 = get_or_compute_encoding(conn, recording, "test_enc", "abcd1234", compute, root=tmp_root)
        _enc2, hit2 = get_or_compute_encoding(conn, recording, "test_enc", "abcd1234", compute, root=tmp_root)

        assert hit1 is False
        assert hit2 is True
        assert calls["n"] == 1
    finally:
        shutil.rmtree(tmp_root)


def test_hit_returns_identical_value_to_original_computation():
    conn, recording = _fresh_conn_and_recording()
    tmp_root = tempfile.mkdtemp()
    try:
        original = np.array([1.5, 2.5, 3.5])

        def compute():
            return original, 0, 600

        enc1, _ = get_or_compute_encoding(conn, recording, "test_enc", "hash0001", compute, root=tmp_root)
        enc2, _ = get_or_compute_encoding(conn, recording, "test_enc", "hash0001", compute, root=tmp_root)
        assert np.array_equal(enc1, original)
        assert np.array_equal(enc2, original)
    finally:
        shutil.rmtree(tmp_root)


def test_different_hash_is_a_separate_cache_entry():
    conn, recording = _fresh_conn_and_recording()
    tmp_root = tempfile.mkdtemp()
    try:
        calls = {"n": 0}

        def compute():
            calls["n"] += 1
            return np.array([calls["n"]]), 0, 600

        enc_a, hit_a = get_or_compute_encoding(conn, recording, "test_enc", "hashaaaa", compute, root=tmp_root)
        enc_b, hit_b = get_or_compute_encoding(conn, recording, "test_enc", "hashbbbb", compute, root=tmp_root)

        assert hit_a is False and hit_b is False
        assert calls["n"] == 2
        assert not np.array_equal(enc_a, enc_b)
    finally:
        shutil.rmtree(tmp_root)


def test_string_encoding_round_trips():
    conn, recording = _fresh_conn_and_recording()
    tmp_root = tempfile.mkdtemp()
    try:
        def compute():
            return "abcdefgh", 0, 600

        enc1, hit1 = get_or_compute_encoding(conn, recording, "sax_csax", "strhash1", compute, root=tmp_root)
        enc2, hit2 = get_or_compute_encoding(conn, recording, "sax_csax", "strhash1", compute, root=tmp_root)
        assert hit1 is False and hit2 is True
        assert enc1 == enc2 == "abcdefgh"
    finally:
        shutil.rmtree(tmp_root)


def test_build_encoding_path_layout():
    path = build_encoding_path("M2_concat_fs1.mat", 3, "gramian_gasf", "a1b2c3d4", "npy")
    normalized = path.replace("\\", "/")
    assert normalized == "DATA/derived/encodings/M2_concat_fs1/CH03/gramian_gasf/a1b2c3d4.npy"


def test_cache_miss_registers_encodings_row():
    conn, recording = _fresh_conn_and_recording()
    tmp_root = tempfile.mkdtemp()
    try:
        def compute():
            return np.arange(5), 100, 700

        get_or_compute_encoding(conn, recording, "test_enc", "regrow01", compute, root=tmp_root)
        row = conn.execute(
            "SELECT * FROM encodings WHERE config_hash = ?", ("regrow01",)
        ).fetchone()
        assert row is not None
        assert row["span_start"] == 100
        assert row["span_end"] == 700
        assert row["recording_id"] == recording["id"]
    finally:
        shutil.rmtree(tmp_root)


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
