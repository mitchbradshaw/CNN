"""
test_window_matrix_resume.py
==============================
The guard for WINDOW_MATRIX_UI_PROMPT.md §0.2 — the bug that made
`HPC/Preprocessing/wm_job.sh` resubmit its chain indefinitely.

The old builder decided what still needed computing by looking for NaN, and
also WROTE NaN whenever a feature function raised. So "not yet computed" and
"computed, and the answer is NaN" were the same value: a window that
reliably raised was retried on every resumed job forever, `--status` could
never report DONE, and the shell chain resubmitted itself until someone
noticed.

These tests exist so that stays fixed. If someone later "simplifies"
`build.py` by deriving the mask from `np.isnan(values)`, they break here
rather than on the cluster.

The stage functions are swapped out for deterministic fakes, so nothing here
needs aeon, torch, or a real recording.

Run from the project root:
    python tests/test_window_matrix_resume.py
"""

import inspect
import os
import shutil
import sys
import tempfile

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.database import window_matrix_store as store
from Working.Preprocessing.window_matrix import build as build_mod
from Working.Preprocessing.window_matrix.build import build_window_matrix

FS = 1.0
WINDOW_MIN = 1.0          # m = 60 samples — above WM_MIN_WINDOW_SAMPLES (32)
N_SAMPLES = 60 * 20       # 20 non-overlapping windows

# `fast_entropy` produces 4 columns; the fakes below must return 4 values.
STAGE = "fast_entropy"
N_COLS = len(store.FAST_ENTROPY_COLUMNS)


class _FakeStages:
    """Swap `_STAGE_FN_FACTORIES[STAGE]` for a deterministic fake and count
    how many times it is called, so "did the resume retry this window?" is
    directly observable rather than inferred."""

    def __init__(self, fn):
        self.fn = fn
        self.calls = 0
        self._saved = None

    def _wrapped(self, window):
        self.calls += 1
        return self.fn(window)

    def __enter__(self):
        self._saved = build_mod._STAGE_FN_FACTORIES[STAGE]
        build_mod._STAGE_FN_FACTORIES[STAGE] = lambda: self._wrapped
        return self

    def __exit__(self, *exc):
        build_mod._STAGE_FN_FACTORIES[STAGE] = self._saved
        return False


def _signal():
    return np.random.default_rng(0).standard_normal(N_SAMPLES).astype(np.float64)


def _ok(window):
    return np.full(N_COLS, float(len(window)))


def _raises_on_the_third_window(counter):
    """A feature function that always fails for one particular window — the
    exact shape that used to make the chain immortal."""
    def fn(window):
        counter["seen"] += 1
        if counter["seen"] == 3:
            raise RuntimeError("no matching template in this window")
        return np.full(N_COLS, 1.0)
    return fn


# ── The failing window ───────────────────────────────────────────────────────

def test_a_failing_window_is_recorded_as_attempted_not_pending():
    counter = {"seen": 0}
    with _FakeStages(_raises_on_the_third_window(counter)):
        built = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,))

    values, computed = built["values"], built["computed"]
    assert computed.all(), "every cell was attempted, so every cell must be marked computed"
    assert built["complete"] is True, (
        "a matrix whose only NaNs are genuine results is COMPLETE — reporting it "
        "as partial is what made the HPC chain resubmit forever"
    )
    assert np.isnan(values[2]).all(), "the failing window's values should be NaN"
    assert not np.isnan(values[0]).any()


def test_resuming_does_not_retry_a_window_that_legitimately_returned_nan():
    """The infinite-resubmit bug, expressed as a test. The old `_pending`
    would hand this window back on every single resumed job."""
    tmpdir = tempfile.mkdtemp(prefix="wm_resume_test_")
    try:
        counter = {"seen": 0}
        with _FakeStages(_raises_on_the_third_window(counter)):
            first = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,))

        path = store.save_wm(
            first["values"], first["computed"], first["columns"], first["start_idx"],
            m=first["m"], step=first["step"], fs=FS, window_min=WINDOW_MIN,
            step_frac=1.0, span_start=0, span_end=N_SAMPLES, n_samples=N_SAMPLES,
            source_file="fake.mat", channel=0, recording_id=1,
            data_sha1="", config_hash="", out_dir=tmpdir,
        )

        with _FakeStages(_ok) as fake:
            second = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,),
                                         resume_path=path)
        assert fake.calls == 0, (
            f"resume recomputed {fake.calls} window(s); every cell was already "
            "attempted, so nothing should have run"
        )
        assert np.isnan(second["values"][2]).all(), (
            "the genuinely-NaN window must survive the resume as NaN, not be "
            "recomputed into a different value"
        )
        assert second["complete"] is True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Timeout and resume ───────────────────────────────────────────────────────

def test_timeout_produces_a_partial_matrix_that_resumes_to_completion():
    import time

    tmpdir = tempfile.mkdtemp(prefix="wm_timeout_test_")
    try:
        def slow(window):
            time.sleep(0.02)
            return np.full(N_COLS, float(len(window)))

        with _FakeStages(slow):
            first = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,),
                                        timeout_s=0.08)
        assert first["timed_out"] is True
        assert first["complete"] is False
        n_done_first = int(first["computed"].all(axis=1).sum())
        assert 0 < n_done_first < len(first["start_idx"]), n_done_first

        path = store.save_wm(
            first["values"], first["computed"], first["columns"], first["start_idx"],
            m=first["m"], step=first["step"], fs=FS, window_min=WINDOW_MIN,
            step_frac=1.0, span_start=0, span_end=N_SAMPLES, n_samples=N_SAMPLES,
            source_file="fake.mat", channel=0, recording_id=1,
            data_sha1="", config_hash="", out_dir=tmpdir,
        )
        assert bool(store.load_wm(path)["complete"]) is False

        with _FakeStages(_ok) as fake:
            second = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,),
                                         resume_path=path)
        assert second["complete"] is True
        assert second["computed"].all()
        assert fake.calls == len(second["start_idx"]) - n_done_first, (
            "resume should compute exactly the windows the timeout left behind"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_resume_matches_an_uninterrupted_build_value_for_value():
    tmpdir = tempfile.mkdtemp(prefix="wm_equiv_test_")
    try:
        def deterministic(window):
            return np.arange(N_COLS, dtype=float) + float(window[0])

        with _FakeStages(deterministic):
            whole = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,))

        # Build a partial matrix by hand: the first half only.
        half = len(whole["start_idx"]) // 2
        values = np.full(whole["values"].shape, np.nan, dtype=np.float32)
        computed = np.zeros(whole["computed"].shape, dtype=bool)
        values[:half] = whole["values"][:half]
        computed[:half] = True

        path = store.save_wm(
            values, computed, whole["columns"], whole["start_idx"],
            m=whole["m"], step=whole["step"], fs=FS, window_min=WINDOW_MIN,
            step_frac=1.0, span_start=0, span_end=N_SAMPLES, n_samples=N_SAMPLES,
            source_file="fake.mat", channel=0, recording_id=1,
            data_sha1="", config_hash="", out_dir=tmpdir,
        )

        with _FakeStages(deterministic):
            resumed = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,),
                                          resume_path=path)
        assert np.array_equal(resumed["values"], whole["values"])
        assert resumed["complete"] is True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Resume safety ────────────────────────────────────────────────────────────

def test_a_backfilled_artifact_is_refused_as_a_resume_source():
    """A backfilled artifact's mask was INFERRED as `~isnan(values)`, so it
    cannot distinguish the two NaN meanings. Trusting it would reintroduce
    exactly the conflation the mask exists to remove."""
    tmpdir = tempfile.mkdtemp(prefix="wm_backfill_resume_test_")
    try:
        with _FakeStages(_ok):
            whole = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,))

        path = store.save_wm(
            whole["values"], whole["computed"], whole["columns"], whole["start_idx"],
            m=whole["m"], step=whole["step"], fs=FS, window_min=WINDOW_MIN,
            step_frac=1.0, span_start=0, span_end=N_SAMPLES, n_samples=N_SAMPLES,
            source_file="fake.mat", channel=0, recording_id=1,
            data_sha1="", config_hash="", backfilled=True, out_dir=tmpdir,
        )

        with _FakeStages(_ok) as fake:
            build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,),
                                resume_path=path)
        assert fake.calls > 0, "a backfilled artifact must not be used as a resume source"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_resume_matches_by_name_and_index_not_by_position():
    """A resume whose stage set differs produces a different column list.
    Lining those up positionally would write one measure's values into
    another measure's column — silently, and only detectable much later."""
    tmpdir = tempfile.mkdtemp(prefix="wm_align_test_")
    try:
        with _FakeStages(_ok):
            first = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,))
        path = store.save_wm(
            first["values"], first["computed"], first["columns"], first["start_idx"],
            m=first["m"], step=first["step"], fs=FS, window_min=WINDOW_MIN,
            step_frac=1.0, span_start=0, span_end=N_SAMPLES, n_samples=N_SAMPLES,
            source_file="fake.mat", channel=0, recording_id=1,
            data_sha1="", config_hash="", out_dir=tmpdir,
        )

        # Now build a WIDER matrix (slow entropy first in column order) and
        # resume from the narrower one.
        slow_marker = 999.0

        def slow_fn(window):
            return np.full(len(store.SLOW_ENTROPY_COLUMNS), slow_marker)

        saved = build_mod._STAGE_FN_FACTORIES["slow_entropy"]
        build_mod._STAGE_FN_FACTORIES["slow_entropy"] = lambda: slow_fn
        try:
            with _FakeStages(_ok):
                wide = build_window_matrix(
                    _signal(), FS, WINDOW_MIN,
                    stages=(STAGE, "slow_entropy"), resume_path=path,
                )
        finally:
            build_mod._STAGE_FN_FACTORIES["slow_entropy"] = saved

        cols = list(wide["columns"])
        for name in store.FAST_ENTROPY_COLUMNS:
            j = cols.index(name)
            assert np.allclose(wide["values"][:, j], 60.0), (
                f"{name} should carry the resumed value (60.0), not a slow-entropy one"
            )
        for name in store.SLOW_ENTROPY_COLUMNS:
            j = cols.index(name)
            assert np.allclose(wide["values"][:, j], slow_marker)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── Skipped stages ───────────────────────────────────────────────────────────

def test_a_stage_impossible_at_this_scale_does_not_make_the_matrix_immortal():
    """A 600-minute window cannot carry sample entropy or CNN scores. Those
    columns stay uncomputed forever — so `complete` must ignore them, or the
    HPC chain would resubmit indefinitely chasing work that can never be
    done. That is the same failure as §0.2, arriving by a different route."""
    n = 36_000 * 4
    with _FakeStages(_ok):
        built = build_window_matrix(np.zeros(n), FS, 600.0,
                                    stages=(STAGE, "slow_entropy", "cnn"))

    assert set(built["stages_skipped"]) == {"slow_entropy", "cnn"}
    assert built["stages_run"] == (STAGE,)
    assert not built["computed"].all(), "the skipped stages' columns stay uncomputed"
    assert built["complete"] is True, (
        "every cell that CAN be computed at this scale was — the matrix is finished"
    )

    cols = list(built["columns"])
    for name in store.SLOW_ENTROPY_COLUMNS + store.CNN_COLUMNS:
        assert name in cols, (
            "an unavailable stage's columns must still be PRESENT — omitting them "
            "would make matrices at different timescales structurally incomparable"
        )
        assert not built["computed"][:, cols.index(name)].any()


# ── Grid ─────────────────────────────────────────────────────────────────────

def test_start_idx_is_absolute_for_an_offset_span():
    with _FakeStages(_ok):
        built = build_window_matrix(_signal(), FS, WINDOW_MIN, stages=(STAGE,),
                                    span_start=12_345)
    assert built["start_idx"][0] == 12_345
    assert built["start_idx"][1] == 12_345 + 60


def test_no_window_is_computed_on_a_truncated_slice():
    """`_ok` returns the window LENGTH, so a truncated tail window would be
    directly visible as a smaller value in the column."""
    with _FakeStages(_ok):
        built = build_window_matrix(np.zeros(60 * 20 + 37), FS, WINDOW_MIN, stages=(STAGE,))
    assert np.allclose(built["values"], 60.0), (
        "every window must be a full 60 samples; a shorter value here means the "
        "ragged tail came back"
    )


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
