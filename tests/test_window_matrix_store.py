"""
test_window_matrix_store.py
=============================
Tests for `Working/database/window_matrix_store.py` (the v1 artifact format
and the registry/coverage query layer) and for the grid geometry in
`Working/Preprocessing/window_matrix/matrix_calc.py`, against synthetic
artifacts — no dependency on real multi-hour recordings, aeon, or torch.

Same shape as `test_matrix_profile_store.py`, deliberately.

Run from the project root:
    python tests/test_window_matrix_store.py
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

from Working.config import (
    WM_GRAMIAN_MAX_SAMPLES, WM_MIN_WINDOW_SAMPLES, WM_SLOW_ENTROPY_MAX_SAMPLES,
)
from Working.database.schema import init_db
from Working.database import queries as q
from Working.database.runs import get_or_create_config, insert_artifact, insert_run, update_run
from Working.database import window_matrix_store as store
from Working.Preprocessing.window_matrix.matrix_calc import create_matrix_at_timescale
from Working.recipes import make_recipe


# ── Fixture ──────────────────────────────────────────────────────────────────

class _Fixture:
    """A fresh temp DB + a fake channel `.npy` on disk + a `recordings` row.

    Default size is 40 x 10-minute windows at fs=1, which is deliberately
    large enough for the 1/10/60-minute ladder entries and deliberately too
    small for the 600-minute one — the "invalid because the span yields too
    few windows" branch needs to be exercised by the default fixture, not by
    a special case somebody might forget to write.
    """

    def __init__(self, n_samples=600 * 40, fs=1.0):
        self.tmpdir = tempfile.mkdtemp(prefix="wm_store_test_")
        self.db_path = os.path.join(self.tmpdir, "test.sqlite")
        self.npy_path = os.path.join(self.tmpdir, "CH2.npy")
        self.results_dir = os.path.join(self.tmpdir, "wm_results")
        self.n_samples = n_samples
        self.fs = fs
        np.save(self.npy_path, np.random.default_rng(0).standard_normal(n_samples))
        self.conn = init_db(self.db_path)
        self.recording_id = q.insert_recording(
            self.conn, "fake_rec.mat", 2, fs, n_samples, 0, self.npy_path
        )

    def register_wm(self, window_min, *, span=None, step_frac=1.0, complete=True,
                    sha1=None, columns=("shannon entropy", "catch22_CO_f1ecac"),
                    out_dir=None):
        """Build + register + save one synthetic window matrix, through the
        same `configs`/`runs`/`artifacts` path a live run's `persist` hook
        would use."""
        span = span or (0, self.n_samples)
        m = store.window_samples(window_min, self.fs)
        step = store.step_samples(m, step_frac)
        n_win = store.n_windows_for(span[1] - span[0], m, step)

        rng = np.random.default_rng(abs(hash((window_min, span))) % (2 ** 32))
        values = rng.standard_normal((n_win, len(columns))).astype(np.float32)
        computed = np.ones(values.shape, dtype=bool)
        if not complete:
            computed[-1, -1] = False
        start_idx = span[0] + np.arange(n_win) * step

        recipe = make_recipe(self.recording_id, [
            {"stage": "preprocessing", "algorithm": "window_matrix",
             "params": {"window_min": float(window_min), "step_frac": float(step_frac)}},
        ], span=list(span))
        config_id, config_hash = get_or_create_config(self.conn, recipe)
        run_id = insert_run(self.conn, config_id, self.recording_id, span[0], span[1],
                            status="running")
        update_run(self.conn, run_id, status="completed",
                   finished_at="2026-01-01T00:00:00Z", duration_s=0.1)

        path = store.save_wm(
            values, computed, columns, start_idx,
            m=m, step=step, fs=self.fs, window_min=window_min, step_frac=step_frac,
            span_start=span[0], span_end=span[1], n_samples=self.n_samples,
            source_file="fake_rec.mat", channel=2, recording_id=self.recording_id,
            data_sha1=sha1 if sha1 is not None else store.compute_data_sha1(self.npy_path),
            config_hash=config_hash,
            out_dir=out_dir or os.path.join(self.results_dir, f"s{span[0]}_{window_min:g}"),
        )
        insert_artifact(self.conn, run_id, kind="encoding", path=path)
        return run_id, path

    def ladder(self, **kwargs):
        return {r["window_min"]: r
                for r in store.ladder_status(self.conn, self.recording_id, self.fs,
                                             self.n_samples, **kwargs)}

    def close(self):
        self.conn.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ── Grid geometry — the tail bug ─────────────────────────────────────────────

def test_no_window_extends_past_the_signal():
    """The bug this replaces: `np.arange(0, len(x), step)` emitted starts
    right up to len(x), so the last few windows were computed on TRUNCATED
    slices. Catch22 and the entropy measures never checked length, so those
    values landed in the column looking comparable to the rest."""
    for n in (599, 600, 601, 1199, 1200, 1201, 2500):
        for step_frac in (1.0, 0.5, 0.25):
            wm = create_matrix_at_timescale(step_frac, np.zeros(n), 10, 1.0)
            for idx in wm.df.index:
                assert idx + wm.window_samples <= n, (
                    f"n={n} step_frac={step_frac}: window at {idx} runs past the signal"
                )
                assert wm.is_full_window(idx)


def test_exact_multiple_keeps_its_final_window():
    """Off-by-one guard: a signal exactly one window long must yield exactly
    one window, not zero."""
    assert list(create_matrix_at_timescale(1.0, np.zeros(600), 10, 1.0).df.index) == [0]
    assert list(create_matrix_at_timescale(1.0, np.zeros(1200), 10, 1.0).df.index) == [0, 600]
    assert list(create_matrix_at_timescale(1.0, np.zeros(1199), 10, 1.0).df.index) == [0]


def test_signal_shorter_than_one_window_yields_no_windows():
    wm = create_matrix_at_timescale(1.0, np.zeros(599), 10, 1.0)
    assert len(wm) == 0


def test_partial_tail_opt_in_restores_the_overhang():
    wm = create_matrix_at_timescale(1.0, np.zeros(1500), 10, 1.0, partial_tail=True)
    last = wm.df.index[-1]
    assert last + wm.window_samples > 1500
    assert wm.partial_tail is True
    assert wm.is_full_window(last) is False


def test_invalid_step_fraction_is_refused():
    for bad in (0, -0.5, 1.5):
        try:
            create_matrix_at_timescale(bad, np.zeros(1000), 10, 1.0)
        except ValueError:
            continue
        raise AssertionError(f"stepfrac={bad} should have raised")


def test_window_count_matches_the_store_helper():
    """`n_windows_for` is what `ladder_status` shows the user BEFORE
    anything runs. If it disagrees with what the builder actually produces,
    every cost estimate is wrong."""
    for n in (2500, 24_000, 27_118 * 600):
        for step_frac in (1.0, 0.5):
            m = store.window_samples(10, 1.0)
            step = store.step_samples(m, step_frac)
            wm = create_matrix_at_timescale(step_frac, np.zeros(n), 10, 1.0)
            assert len(wm) == store.n_windows_for(n, m, step)


# ── Per-scale stage availability ─────────────────────────────────────────────

def test_all_stages_available_at_short_windows():
    available, unavailable = store.stages_available_at(600)
    assert unavailable == ()
    assert set(available) == set(store.ALL_STAGES)


def test_slow_entropy_and_cnn_unavailable_at_long_windows():
    """A 600-minute window at fs=1 is 36,000 samples: sample entropy is
    O(m^2) per window and a GASF image is m x m. Neither is 'slow' — both
    are impossible, and the ladder must say so rather than offering a
    Compute button."""
    _available, unavailable = store.stages_available_at(36_000)
    assert set(unavailable) == {"slow_entropy", "cnn"}
    for stage in unavailable:
        assert store.unavailable_reason(stage, 36_000)
    assert store.unavailable_reason("catch22", 36_000) is None


def test_gramian_limit_matches_the_gramian_adapters():
    """`WM_GRAMIAN_MAX_SAMPLES` is duplicated as a literal in
    `Working/config.py` because config must not import `Adapters/`. This is
    the guard that stops the duplicate drifting: it is the same physical
    O(m^2)-memory limit, and a window matrix that accepted a window the
    Gramian adapters refuse would simply fail inside them."""
    from Adapters.catalogue_gramian_gasf import MAX_SPAN_SAMPLES
    assert WM_GRAMIAN_MAX_SAMPLES == MAX_SPAN_SAMPLES


def test_stage_limits_are_exact():
    assert store.stages_available_at(WM_SLOW_ENTROPY_MAX_SAMPLES)[1] == ()
    assert "slow_entropy" in store.stages_available_at(WM_SLOW_ENTROPY_MAX_SAMPLES + 1)[1]
    assert "cnn" not in store.stages_available_at(WM_GRAMIAN_MAX_SAMPLES)[1]
    assert "cnn" in store.stages_available_at(WM_GRAMIAN_MAX_SAMPLES + 1)[1]


# ── ladder_status ────────────────────────────────────────────────────────────

def test_ladder_states_before_anything_is_computed():
    fx = _Fixture()
    try:
        rows = fx.ladder()
        assert rows[1]["state"] == "missing"
        assert rows[10]["state"] == "missing"
        assert rows[10]["n_windows"] == 40
        # 600 min = 36,000 samples over a 24,000-sample span: no windows at all.
        assert rows[600]["state"] == "invalid"
        assert rows[600]["run_id"] is None
        assert rows[600]["reason"]
    finally:
        fx.close()


def test_ladder_is_shorter_at_a_lower_sample_rate():
    """`WM_SCALE_LADDER_MIN` is in MINUTES so the same ladder means the same
    thing at every fs — which means `m` is genuinely different, and the
    1-minute entry falls below the measures' floor at fs=0.25."""
    fx = _Fixture(fs=0.25)
    try:
        rows = fx.ladder()
        assert rows[1]["m"] == 15
        assert rows[1]["m"] < WM_MIN_WINDOW_SAMPLES
        assert rows[1]["state"] == "invalid"
        assert str(WM_MIN_WINDOW_SAMPLES) in rows[1]["reason"]
        assert rows[10]["state"] == "missing"
    finally:
        fx.close()


def test_ladder_reports_available_after_a_complete_run():
    fx = _Fixture()
    try:
        run_id, path = fx.register_wm(10.0)
        rows = fx.ladder()
        assert rows[10]["state"] == "available"
        assert rows[10]["run_id"] == run_id
        assert rows[10]["artifact_path"] == path
        assert rows[1]["state"] == "missing"      # one scale does not imply another
    finally:
        fx.close()


def test_partial_and_stale_are_distinct_states():
    fx = _Fixture()
    try:
        fx.register_wm(10.0, complete=False)
        fx.register_wm(60.0, sha1="0" * 40)
        rows = fx.ladder()
        assert rows[10]["state"] == "partial"
        assert rows[60]["state"] == "stale"
        assert rows[60]["reason"]
    finally:
        fx.close()


# ── find_wm ──────────────────────────────────────────────────────────────────

def test_find_wm_hits_and_misses():
    fx = _Fixture()
    try:
        fx.register_wm(10.0)
        assert store.find_wm(fx.conn, fx.recording_id, 10.0) is not None
        assert store.find_wm(fx.conn, fx.recording_id, 60.0) is None
        # step_frac is part of the identity, not a detail
        assert store.find_wm(fx.conn, fx.recording_id, 10.0, step_frac=0.5) is None
        assert store.find_wm(fx.conn, fx.recording_id, 10.0, span=(0, fx.n_samples)) is not None
        assert store.find_wm(fx.conn, fx.recording_id, 10.0, span=(0, 600)) is None
    finally:
        fx.close()


def test_require_complete_never_substitutes_a_partial_matrix():
    fx = _Fixture()
    try:
        fx.register_wm(10.0, complete=False)
        loose = store.find_wm(fx.conn, fx.recording_id, 10.0)
        assert loose is not None and loose["complete"] is False
        assert store.find_wm(fx.conn, fx.recording_id, 10.0, require_complete=True) is None
    finally:
        fx.close()


def test_stale_is_returned_flagged_not_hidden():
    fx = _Fixture()
    try:
        fx.register_wm(10.0, sha1="0" * 40)
        hit = store.find_wm(fx.conn, fx.recording_id, 10.0)
        assert hit is not None
        assert hit["stale"] is True
    finally:
        fx.close()


def test_stale_detected_after_the_source_npy_changes():
    fx = _Fixture()
    try:
        fx.register_wm(10.0)
        assert store.find_wm(fx.conn, fx.recording_id, 10.0)["stale"] is False
        np.save(fx.npy_path, np.random.default_rng(99).standard_normal(fx.n_samples))
        assert store.find_wm(fx.conn, fx.recording_id, 10.0)["stale"] is True
    finally:
        fx.close()


# ── The registry must not over-match ─────────────────────────────────────────

def test_a_matrix_profile_run_is_not_listed_as_a_window_matrix():
    fx = _Fixture()
    try:
        _run_id, path = fx.register_wm(10.0)
        recipe = make_recipe(fx.recording_id, [
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": 10.0}},
        ], span=None)
        config_id, _h = get_or_create_config(fx.conn, recipe)
        mp_run = insert_run(fx.conn, config_id, fx.recording_id, 0, fx.n_samples,
                            status="completed")
        insert_artifact(fx.conn, mp_run, kind="encoding", path=path)
        assert all(r["run_id"] != mp_run for r in store.list_wm_runs(fx.conn, fx.recording_id))
    finally:
        fx.close()


def test_a_preprocessed_recipe_is_not_listed_under_the_raw_timescale():
    """A window matrix over a detrended signal is a different quantity from
    one over the raw trace. Listing it under the same timescale would be the
    same category error as substituting an approximate matrix profile."""
    fx = _Fixture()
    try:
        _run_id, path = fx.register_wm(10.0)
        recipe = make_recipe(fx.recording_id, [
            {"stage": "preprocessing", "algorithm": "detrend",
             "params": {"mode": "linear", "window_s": 600.0}},
            {"stage": "preprocessing", "algorithm": "window_matrix",
             "params": {"window_min": 10.0, "step_frac": 1.0}},
        ], span=None)
        config_id, _h = get_or_create_config(fx.conn, recipe)
        run = insert_run(fx.conn, config_id, fx.recording_id, 0, fx.n_samples,
                         status="completed")
        insert_artifact(fx.conn, run, kind="encoding", path=path)
        assert all(r["run_id"] != run for r in store.list_wm_runs(fx.conn, fx.recording_id))
    finally:
        fx.close()


def test_incomplete_runs_and_missing_files_are_skipped_not_fatal():
    fx = _Fixture()
    try:
        _run_id, path = fx.register_wm(10.0)
        recipe = make_recipe(fx.recording_id, [
            {"stage": "preprocessing", "algorithm": "window_matrix",
             "params": {"window_min": 60.0, "step_frac": 1.0}},
        ], span=None)
        config_id, _h = get_or_create_config(fx.conn, recipe)

        running = insert_run(fx.conn, config_id, fx.recording_id, 0, fx.n_samples,
                             status="running")
        insert_artifact(fx.conn, running, kind="encoding", path=path)

        gone = insert_run(fx.conn, config_id, fx.recording_id, 0, 600, status="completed")
        insert_artifact(fx.conn, gone, kind="encoding",
                        path=os.path.join(fx.tmpdir, "not-here.npz"))

        run_ids = {r["run_id"] for r in store.list_wm_runs(fx.conn, fx.recording_id)}
        assert running not in run_ids
        assert gone not in run_ids
    finally:
        fx.close()


# ── Round trip and the computed mask ─────────────────────────────────────────

def test_round_trip_preserves_geometry_and_columns():
    fx = _Fixture()
    try:
        _run_id, path = fx.register_wm(10.0)
        loaded = store.load_wm(path)
        df = store.to_dataframe(loaded)
        assert df.shape == (40, 2)
        assert list(df.columns) == ["shannon entropy", "catch22_CO_f1ecac"]
        # start_idx is ABSOLUTE in the channel, not relative to the span
        assert df.index[0] == 0 and df.index[-1] == 39 * 600
        assert not df.isna().any().any()
        assert bool(loaded["complete"]) is True
        assert int(loaded["m"]) == 600
        assert float(loaded["fs"]) == 1.0
    finally:
        fx.close()


def test_start_idx_is_absolute_for_an_offset_span():
    fx = _Fixture()
    try:
        _run_id, path = fx.register_wm(10.0, span=(6000, 18_000))
        df = store.to_dataframe(store.load_wm(path))
        assert df.index[0] == 6000
        assert df.index[-1] + 600 <= 18_000
    finally:
        fx.close()


def test_uncomputed_cells_are_nan_in_the_dataframe_but_distinguishable():
    """The whole point of the mask (WINDOW_MATRIX_UI_PROMPT.md §0.2): a
    reader that wants analysis gets NaN, a reader that wants resume state
    gets the truth. `np.isnan(values)` must never be the resume signal."""
    fx = _Fixture()
    try:
        _run_id, path = fx.register_wm(10.0, complete=False)
        loaded = store.load_wm(path)
        assert bool(loaded["complete"]) is False
        assert bool(loaded["computed"][-1, -1]) is False
        assert bool(loaded["computed"][0, 0]) is True

        masked = store.to_dataframe(loaded)
        assert np.isnan(masked.iloc[-1, -1])

        raw = store.to_dataframe(loaded, include_uncomputed=True)
        assert not np.isnan(raw.iloc[-1, -1])
    finally:
        fx.close()


def test_a_genuinely_nan_value_is_still_marked_computed():
    """The infinite-resubmit bug, directly. A window whose feature function
    raises is recorded as attempted-and-NaN; a resume must not retry it, and
    the matrix must still report itself complete."""
    fx = _Fixture()
    try:
        values = np.array([[1.0, 2.0], [np.nan, 4.0]], dtype=np.float32)
        computed = np.ones((2, 2), dtype=bool)      # both attempted
        path = store.save_wm(
            values, computed, ("a", "b"), [0, 600],
            m=600, step=600, fs=1.0, window_min=10.0, step_frac=1.0,
            span_start=0, span_end=1200, n_samples=fx.n_samples,
            source_file="fake_rec.mat", channel=2, recording_id=fx.recording_id,
            data_sha1="", config_hash="", out_dir=fx.results_dir,
        )
        loaded = store.load_wm(path)
        assert bool(loaded["complete"]) is True
        assert loaded["computed"].all()
        assert np.isnan(store.to_dataframe(loaded).iloc[1, 0])
    finally:
        fx.close()


def test_save_wm_refuses_a_mismatched_mask_or_column_list():
    fx = _Fixture()
    try:
        base = dict(m=600, step=600, fs=1.0, window_min=10.0, step_frac=1.0,
                    span_start=0, span_end=1800, n_samples=fx.n_samples,
                    source_file="fake_rec.mat", channel=2,
                    recording_id=fx.recording_id, data_sha1="", config_hash="",
                    out_dir=fx.results_dir)
        for label, args in [
            ("mask shape", (np.zeros((3, 2), np.float32), np.ones((2, 2), bool),
                            ("a", "b"), [0, 600, 1200])),
            ("column count", (np.zeros((3, 2), np.float32), np.ones((3, 2), bool),
                              ("a",), [0, 600, 1200])),
            ("row count", (np.zeros((3, 2), np.float32), np.ones((3, 2), bool),
                           ("a", "b"), [0, 600])),
        ]:
            try:
                store.save_wm(*args, **base)
            except ValueError:
                continue
            raise AssertionError(f"{label} mismatch should have raised")
    finally:
        fx.close()


# ── coverage_for_span ────────────────────────────────────────────────────────

def test_coverage_reports_the_covered_region_per_scale():
    fx = _Fixture()
    try:
        fx.register_wm(10.0)
        cov = store.coverage_for_span(fx.conn, fx.recording_id)
        assert cov[10] == [(0, fx.n_samples)]
        assert 60 not in cov
    finally:
        fx.close()


def test_overlapping_runs_merge_into_one_interval():
    """Merged through the SAME `queries.merge_intervals` the reviewed-coverage
    ribbon uses, so the ribbon can never disagree with a coverage percentage
    computed elsewhere."""
    fx = _Fixture()
    try:
        for span in ((0, 12_000), (6_000, 18_000), (15_000, 24_000)):
            fx.register_wm(10.0, span=span)
        assert store.coverage_for_span(fx.conn, fx.recording_id)[10] == [(0, 24_000)]
    finally:
        fx.close()


def test_disjoint_runs_stay_disjoint():
    """The failure that would matter visually: scattered coverage islands
    must not be reported as one continuous span."""
    fx = _Fixture()
    try:
        fx.register_wm(10.0, span=(0, 6_000))
        fx.register_wm(10.0, span=(12_000, 18_000))
        assert store.coverage_for_span(fx.conn, fx.recording_id)[10] == [
            (0, 6_000), (12_000, 18_000)
        ]
    finally:
        fx.close()


def test_coverage_is_clipped_to_the_requested_span():
    fx = _Fixture()
    try:
        fx.register_wm(10.0)
        cov = store.coverage_for_span(fx.conn, fx.recording_id, span=(3_000, 9_000))
        assert cov[10] == [(3_000, 9_000)]
    finally:
        fx.close()


def test_stale_coverage_is_excluded_by_default():
    """A region whose source data has changed is not covered in any useful
    sense, and showing it as covered misleads in the worst direction."""
    fx = _Fixture()
    try:
        fx.register_wm(10.0, sha1="0" * 40)
        assert 10 not in store.coverage_for_span(fx.conn, fx.recording_id)
        assert 10 in store.coverage_for_span(fx.conn, fx.recording_id, include_stale=True)
    finally:
        fx.close()


# ── Measure set ──────────────────────────────────────────────────────────────

def test_measure_set_has_no_redundant_probability_twins():
    """WINDOW_MATRIX_UI_PROMPT.md §2.1 — a `1 - p` twin sits at r = -1.0 and
    double-weights the CNN direction in every Euclidean distance."""
    cols = store.measure_columns()
    assert not any(c.endswith("_notinteresting") for c in cols)
    assert len(cols) == 33, f"expected 33 measures, got {len(cols)}: {cols}"
    assert len(set(cols)) == len(cols)


def test_measure_columns_respects_the_stage_subset():
    entropy_only = store.measure_columns(("fast_entropy", "slow_entropy"))
    assert len(entropy_only) == 6
    assert "shannon entropy" in entropy_only
    assert not any(c.startswith("catch22_") for c in entropy_only)
    try:
        store.measure_columns(("nonexistent",))
    except ValueError:
        return
    raise AssertionError("an unknown stage name should raise")


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
