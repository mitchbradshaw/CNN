"""
test_types.py
===============
Tests for Working/types/: the seven interchange types (Signal, SpanSet,
WindowSet, Encoding, Grouping, Model, Scores) and their disk round-trip.

Run from the project root:
    python tests/test_types.py
"""

import dataclasses
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

import numpy as np
import pandas as pd

from Working.types import (
    Encoding,
    Grouping,
    Model,
    Scores,
    Signal,
    SpanSet,
    WindowSet,
)


def _scratch_dir():
    """A fresh temp directory for one round-trip test; caller cleans it up."""
    return tempfile.mkdtemp(prefix="types_test_")


# ── Signal ───────────────────────────────────────────────────────────────────

def test_signal_round_trips_through_disk():
    sig = Signal(x=np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64), fs=1.0)
    d = _scratch_dir()
    try:
        sig.to_path(d)
        loaded = Signal.from_path(d)
        assert loaded == sig
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_signal_is_frozen():
    sig = Signal(x=np.array([1.0]), fs=1.0)
    try:
        sig.fs = 2.0
        assert False, "expected FrozenInstanceError"
    except dataclasses.FrozenInstanceError:
        pass


# ── SpanSet ──────────────────────────────────────────────────────────────────

def test_spanset_round_trips_through_disk():
    spans = SpanSet(starts=(0, 100, 250), ends=(50, 150, 300),
                     labels=("burst", None, "quiet"), scores=(0.9, None, 0.2))
    d = _scratch_dir()
    try:
        spans.to_path(d)
        loaded = SpanSet.from_path(d)
        assert loaded == spans
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_spanset_round_trips_without_labels_or_scores():
    spans = SpanSet(starts=(0, 100), ends=(50, 150))
    d = _scratch_dir()
    try:
        spans.to_path(d)
        loaded = SpanSet.from_path(d)
        assert loaded == spans
        assert loaded.labels is None
        assert loaded.scores is None
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_spanset_rejects_mismatched_lengths():
    try:
        SpanSet(starts=(0, 100), ends=(50,))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_spanset_rejects_end_before_start():
    try:
        SpanSet(starts=(100,), ends=(50,))
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── WindowSet ────────────────────────────────────────────────────────────────

def test_windowset_round_trips_without_features():
    ws = WindowSet(starts=np.array([0, 100, 200], dtype=np.int64), length=100, fs=1.0)
    d = _scratch_dir()
    try:
        ws.to_path(d)
        loaded = WindowSet.from_path(d)
        assert loaded == ws
        assert loaded.features is None
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_windowset_round_trips_with_attached_feature_table():
    starts = np.array([0, 100, 200], dtype=np.int64)
    features = pd.DataFrame({"mean": [1.0, 2.0, 3.0], "std": [0.1, 0.2, 0.3]})
    ws = WindowSet(starts=starts, length=100, fs=1.0, features=features)
    d = _scratch_dir()
    try:
        ws.to_path(d)
        loaded = WindowSet.from_path(d)
        assert loaded == ws
        assert loaded.features is not None
        assert list(loaded.features.columns) == ["mean", "std"]
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_windowset_exposes_one_row_per_window():
    starts = np.array([0, 100, 200], dtype=np.int64)
    ws = WindowSet(starts=starts, length=100, fs=1.0)
    assert ws.n_windows == 3


def test_windowset_rejects_feature_table_row_count_mismatch():
    starts = np.array([0, 100, 200], dtype=np.int64)
    features = pd.DataFrame({"mean": [1.0, 2.0]})  # 2 rows, 3 windows
    try:
        WindowSet(starts=starts, length=100, fs=1.0, features=features)
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── Encoding ─────────────────────────────────────────────────────────────────

def test_encoding_round_trips_image_kind():
    values = np.random.default_rng(0).random((3, 8, 8)).astype(np.float32)
    enc = Encoding(values=values, kind="image")
    d = _scratch_dir()
    try:
        enc.to_path(d)
        loaded = Encoding.from_path(d)
        assert loaded == enc
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_encoding_round_trips_symbolic_kind():
    values = np.array(["aab", "abc", "bba"], dtype="<U8")
    enc = Encoding(values=values, kind="symbolic")
    d = _scratch_dir()
    try:
        enc.to_path(d)
        loaded = Encoding.from_path(d)
        assert loaded == enc
        assert loaded.kind == "symbolic"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


# ── Grouping ─────────────────────────────────────────────────────────────────

def test_grouping_round_trips_through_disk():
    grp = Grouping(labels=np.array([0, 0, 1, 2, 1], dtype=np.int64))
    d = _scratch_dir()
    try:
        grp.to_path(d)
        loaded = Grouping.from_path(d)
        assert loaded == grp
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


# ── Model ────────────────────────────────────────────────────────────────────

def test_model_round_trips_by_path_reference_only():
    model = Model(path=os.path.join("MODELS", "cnn_fusion_v1.joblib"))
    d = _scratch_dir()
    try:
        model.to_path(d)
        loaded = Model.from_path(d)
        assert loaded == model
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


# ── Scores ───────────────────────────────────────────────────────────────────

def test_scores_round_trips_through_disk():
    scores = Scores(values=np.array([0.1, 0.2, 0.3, 0.4]), fs=1.0)
    d = _scratch_dir()
    try:
        scores.to_path(d)
        loaded = Scores.from_path(d)
        assert loaded == scores
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_scores_exposes_one_value_per_timepoint():
    scores = Scores(values=np.array([0.1, 0.2, 0.3]), fs=1.0)
    assert scores.n_timepoints == 3


def test_scores_from_signal_asserts_length_matches_source_signal():
    sig = Signal(x=np.array([1.0, 2.0, 3.0, 4.0]), fs=1.0)
    scores = Scores.from_signal(sig, np.array([0.1, 0.2, 0.3, 0.4]))
    assert scores.n_timepoints == len(sig.x)


def test_scores_from_signal_rejects_length_mismatch():
    sig = Signal(x=np.array([1.0, 2.0, 3.0, 4.0]), fs=1.0)
    try:
        Scores.from_signal(sig, np.array([0.1, 0.2, 0.3]))
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── boundary rule ────────────────────────────────────────────────────────────

def test_types_package_imports_no_ui_library():
    import Working.types.encoding
    import Working.types.grouping
    import Working.types.model
    import Working.types.scores
    import Working.types.signal
    import Working.types.spanset
    import Working.types.windowset

    forbidden = ("panel", "holoviews", "bokeh", "matplotlib")
    for name, mod in list(sys.modules.items()):
        if name.startswith("Working.types"):
            src = inspect.getsource(mod)
            for lib in forbidden:
                assert lib not in src, f"{name} mentions forbidden import {lib!r}"


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
