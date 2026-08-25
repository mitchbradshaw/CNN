"""
test_drop_motifs_detect.py
===========================
Engineered-signal tests for spike-drop detection
(`Working.Detection.drop_motifs.detect`).

Same discipline as `tests/test_dsax_engineered.py`: every signal here is
built so that the correct answer is known before the detector runs, and
the assertions are on exact sample indices wherever the signal makes an
exact answer meaningful. A detector that finds "about the right number of
roughly plausible events" on real data can be wrong in ways nobody
notices; a detector that puts the onset one sample late on a signal with
one perfectly sharp corner cannot hide.

The four cases the work order names, and what each one is guarding:

  1. clean ramp-then-cliff  - the happy path. The onset must land on the
     FIRST sample of the fall, not somewhere down it, because the whole
     point of the "one drop per UP region" rule is to identify the top of
     the fall rather than a point part-way along it.
  2. ramp with no drop      - a rise that never falls must yield zero
     events, and must be COUNTED as a rejected candidate rather than
     vanishing (work order 3.4/4.4: an empty result must not look like a
     result that was never computed).
  3. back-to-back rises     - two separated rise-then-drop events must
     come back as two events, not one merged event and not four.
  4. flat signal            - zero events and no exception. dSAX's own
     degenerate-cutline path is exercised here, so this also pins the
     "constant channel does not raise" behaviour end to end.

Pure numpy/scipy, no matplotlib: `Working/` may not import a plotting
library (CLAUDE.md rule 1), and these tests are the check that the
detection core stayed on the right side of that line.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.Detection.drop_motifs.detect import (
    DetectionParams,
    detect_drops,
    find_trough,
    merge_up_runs,
    robust_sigma,
    up_regions,
)

FS = 1.0


# -- signal builders -------------------------------------------------------
#
# Amplitudes are deliberately large relative to the noise added, because
# these tests assert on WHERE the detector fires, not on how close to the
# noise floor it can be pushed. Sensitivity is a property of the real
# recordings and is reported in the manifest, not asserted here.

def ramp_then_cliff(n=1200, rise_start=300, rise_len=400, fall_len=4,
                    amplitude=10.0, noise=0.0, seed=7):
    """Flat, then a linear rise, then a near-vertical fall, then flat.

    Returns `(x, peak_idx)` where `peak_idx` is the last sample of the
    rise - i.e. the sample the drop onset should be found at or one after.
    """
    x = np.zeros(n, dtype=float)
    peak = rise_start + rise_len
    x[rise_start:peak] = np.linspace(0.0, amplitude, rise_len)
    x[peak:peak + fall_len] = np.linspace(amplitude, 0.0, fall_len)
    x[peak + fall_len:] = 0.0
    if noise:
        x = x + np.random.default_rng(seed).normal(0.0, noise, n)
    return x, peak


def two_events(n=2400, gap=1200, **kwargs):
    """Two identical ramp-then-cliff events, `gap` samples apart."""
    a, peak_a = ramp_then_cliff(n=gap, **kwargs)
    b, peak_b = ramp_then_cliff(n=n - gap, **kwargs)
    return np.concatenate([a, b]), (peak_a, gap + peak_b)


def params(**kwargs):
    """DetectionParams tuned to these engineered signals.

    `detrend_window_s` must be long relative to the EVENT SPACING, not
    merely long relative to one event. At 600 s on the two-event signal
    below - a window half the 1200-sample gap - the rolling mean's own
    recovery after the first cliff becomes a 287-second, 1.9-unit fall in
    the detrended trace, and the detector correctly reports it as a drop.
    That is a real preprocessing failure rather than a detector bug, and
    `test_a_short_detrend_window_manufactures_a_spurious_slow_fall` pins
    it deliberately; the fixture uses a window wider than the spacing so
    the other tests measure what they mean to.
    """
    base = dict(
        detrend_window_s=2400.0,
        segment_seconds=20.0,
        same_fraction=0.5,
        slope_sigma=4.0,
        min_depth_frac=0.10,
        lookahead_mult=3.0,
        merge_gap_segments=0,
        min_separation_s=0.0,
        pre_context_mult=2.0,
        post_context_mult=4.0,
        trough_knee_frac=0.05,
    )
    base.update(kwargs)
    return DetectionParams(**base)


# -- 1. clean ramp-then-cliff ----------------------------------------------

def test_clean_ramp_then_cliff_finds_exactly_one_drop_at_the_cliff():
    x, peak = ramp_then_cliff()
    result = detect_drops(x, FS, params())

    assert len(result.events) == 1, (
        f"one engineered cliff should give one event, got {len(result.events)}")
    event = result.events[0]

    # The onset is the first sample at or past the cliff top. dSAX's
    # segmentation quantises the rise to whole segments, so the UP region
    # ends on a segment boundary at or before the peak; the derivative
    # scan then walks forward to the fall. It must land INSIDE the fall,
    # not before it and not past its foot.
    assert peak <= event.onset_idx <= peak + 2, (
        f"onset {event.onset_idx} is not at the cliff top {peak}")
    assert event.onset_slope_raw < 0.0


def test_onset_is_the_top_of_the_fall_not_a_point_along_it():
    """A LONG fall must still be reported at its start.

    This is the "prevents a string of identifications on a large downward
    slope" requirement: one UP region yields at most one drop, and that
    drop is the first qualifying sample, not the steepest one and not the
    last one.
    """
    x, peak = ramp_then_cliff(fall_len=120)
    result = detect_drops(x, FS, params())

    assert len(result.events) == 1
    assert peak <= result.events[0].onset_idx <= peak + 2, (
        "the onset drifted down the fall instead of marking its top")


# -- 2. a rise with no drop ------------------------------------------------

def test_ramp_with_no_drop_yields_no_events_and_is_counted_as_rejected():
    """A monotonic rise that never falls. Zero events - and the rejection
    must be VISIBLE in the counters, because 'nothing found' and 'never
    run' have to be distinguishable downstream (work order 1.8)."""
    x = np.concatenate([np.zeros(300), np.linspace(0.0, 10.0, 700)])
    result = detect_drops(x, FS, params())

    assert result.events == []
    assert result.counts["up_regions"] >= 1, (
        "the rise itself should still have been classified as an UP region")
    assert result.counts["rejected_no_slope"] >= 1, (
        "an UP region with no qualifying fall must be counted, not dropped "
        "silently")


# -- 3. back-to-back rises -------------------------------------------------

def test_two_separated_events_are_reported_as_two():
    x, (peak_a, peak_b) = two_events()
    result = detect_drops(x, FS, params())

    assert len(result.events) == 2, (
        f"two engineered cliffs should give two events, got {len(result.events)}")
    onsets = sorted(e.onset_idx for e in result.events)
    assert peak_a <= onsets[0] <= peak_a + 2
    assert peak_b <= onsets[1] <= peak_b + 2


def test_a_short_detrend_window_manufactures_a_spurious_slow_fall():
    """The detrend window has to be long relative to the EVENT SPACING.

    Set it to half the gap between two events and the rolling mean's own
    recovery after the first cliff appears in the detrended trace as a
    slow fall of its own - here about 19% of a real event's depth, spread
    over 287 seconds against the real cliff's 4. The detector reports it,
    correctly: by then it IS a fall in the signal it was handed.

    This is pinned rather than papered over because it is the failure a
    reader is most likely to reproduce on their own data, and because the
    giveaway is visible in the output - a fall duration two orders of
    magnitude longer than its neighbours, at a fraction of their depth.
    """
    x, (peak_a, peak_b) = two_events()

    wide = detect_drops(x, FS, params(detrend_window_s=2400.0))
    assert len(wide.events) == 2

    narrow = detect_drops(x, FS, params(detrend_window_s=600.0))
    assert len(narrow.events) == 3, (
        "expected the detrend artefact to show up as a third event")

    spurious = [e for e in narrow.events
                if e.onset_idx not in (peak_a, peak_b)
                and not (peak_a <= e.onset_idx <= peak_a + 2)
                and not (peak_b <= e.onset_idx <= peak_b + 2)]
    assert len(spurious) == 1
    # ... and it is identifiable as an artefact from the table alone.
    assert spurious[0].fall_duration_s > 100.0
    assert spurious[0].drop_depth_mv < 0.3 * max(
        e.drop_depth_mv for e in wide.events)


def test_min_separation_collapses_two_events_into_the_deeper_one():
    """`min_separation_s` is the knob that stops one real event being
    counted several times through several UP regions. Set wider than the
    engineered spacing it must collapse the pair, and the survivor must be
    the DEEPER of the two - depth is the quality score here, the same role
    distance plays in a nearest-neighbour dedupe."""
    x, (peak_a, peak_b) = two_events()
    x[peak_b:peak_b + 4] = np.linspace(20.0, 0.0, 4)      # make the 2nd deeper
    x[peak_b - 400:peak_b] = np.linspace(0.0, 20.0, 400)
    result = detect_drops(x, FS, params(min_separation_s=2000.0))

    assert len(result.events) == 1
    assert result.events[0].onset_idx > peak_a, (
        "dedup kept the shallower of the two events")
    assert result.counts["rejected_duplicate"] >= 1


# -- 4. flat signal --------------------------------------------------------

def test_flat_signal_gives_zero_events_without_raising():
    result = detect_drops(np.zeros(1000), FS, params())
    assert result.events == []
    assert result.counts["up_regions"] == 0


def test_constant_nonzero_signal_gives_zero_events_without_raising():
    result = detect_drops(np.full(1000, -0.42), FS, params())
    assert result.events == []


# -- the trough --------------------------------------------------------------
#
# `find_trough` takes the DERIVATIVE, not the signal: the fall ends where
# its slope flattens, not where the signal is lowest. See the function's
# own docstring for the two rules this replaced and why each failed.

def test_trough_ends_the_steep_fall_and_ignores_a_slow_tail_after_it():
    """The M2_aug failure, in miniature.

    A steep fall, then a long slow decay that goes lower. `argmin` returns
    the far end of the slow decay - which on the real recording turned one
    sharkfin's reported fall from ~450 s into ~1763 s and made its stored
    snippet swallow the next cycle. The knee rule stops at the foot of the
    steep part, which is what "the most vertical drop" means.
    """
    x = np.concatenate([
        np.linspace(0.0, -40.0, 20),      # steep: -2.0 per sample
        np.linspace(-40.0, -60.0, 400),   # slow tail: -0.05 per sample
    ])
    derivative = np.gradient(x)
    trough = find_trough(derivative, 0, len(x), knee_frac=0.05)

    assert 18 <= trough <= 26, (
        f"the fall should end at the knee near sample 20, got {trough}")
    assert int(np.argmin(x)) > 400, "the signal's minimum is far past the knee"


def test_trough_does_not_end_on_a_single_noisy_sample_mid_fall():
    """`hysteresis` consecutive samples must clear the knee, so one flat
    sample part-way down a long fall cannot terminate it."""
    x = np.linspace(0.0, -100.0, 80)
    x[30] = x[29]                          # one sample of zero slope
    derivative = np.gradient(x)
    trough = find_trough(derivative, 0, len(x), knee_frac=0.05)
    assert trough > 40, f"one flat sample ended the fall at {trough}"


def test_trough_is_scale_free_in_the_fall_it_measures():
    """The same shape at two scales must give proportional fall durations -
    this is what lets one `knee_frac` serve a 4-second icicle and a
    3-minute sharkfin."""
    def fall_length(steps):
        x = np.concatenate([np.linspace(0.0, -50.0, steps),
                            np.full(steps * 4, -50.0)])
        return find_trough(np.gradient(x), 0, len(x), knee_frac=0.05)

    short, long = fall_length(20), fall_length(200)
    assert 8.0 <= long / short <= 12.0, (
        f"a 10x longer fall measured {long / short:.1f}x longer, not ~10x")


def test_trough_at_the_very_end_of_the_window_does_not_run_off():
    derivative = np.gradient(np.linspace(0.0, -10.0, 30))
    assert find_trough(derivative, 25, 30) <= 29
    assert find_trough(derivative, 29, 30) <= 29


# -- helpers ---------------------------------------------------------------

def test_up_regions_reads_maximal_runs_of_U():
    assert up_regions("SSUUUDDSSUS") == [(2, 5), (9, 10)]
    assert up_regions("SSSDDD") == []
    assert up_regions("UUU") == [(0, 3)]


def test_merge_up_runs_bridges_short_same_gaps_only():
    # One S between two U runs becomes one region at max_gap=1 ...
    assert merge_up_runs("UUSUU", 1) == "UUUUU"
    # ... but two S do not, at the same setting.
    assert merge_up_runs("UUSSUU", 1) == "UUSSUU"
    assert merge_up_runs("UUSSUU", 2) == "UUUUUU"
    # max_gap=0 is the identity, which is the documented default.
    assert merge_up_runs("UUSUU", 0) == "UUSUU"
    # A D is never bridged - a fall between two rises is two rises.
    assert merge_up_runs("UUDUU", 2) == "UUDUU"


def test_robust_sigma_is_insensitive_to_a_few_huge_outliers():
    """The whole reason the slope threshold is built on a MAD estimate
    rather than a standard deviation: on a spiking recording the rare
    enormous drops ARE the outliers, and letting them set the noise scale
    is how a detector ends up unable to see anything but the largest
    event."""
    rng = np.random.default_rng(3)
    clean = rng.normal(0.0, 1.0, 5000)
    spiked = clean.copy()
    spiked[:50] = 500.0

    assert abs(robust_sigma(clean) - 1.0) < 0.1
    assert abs(robust_sigma(spiked) - robust_sigma(clean)) < 0.05
    assert spiked.std() > 10.0        # ... which sd emphatically is not


def test_detection_is_deterministic_across_repeated_runs():
    """Quantile-mode dSAX touches no RNG (see `dsax()`'s Determinism note),
    which is the reason this pipeline uses it rather than `learned`. Two
    runs with no reseeding in between must be identical."""
    x, _ = ramp_then_cliff(noise=0.05)
    a = detect_drops(x, FS, params())
    b = detect_drops(x, FS, params())
    assert [e.onset_idx for e in a.events] == [e.onset_idx for e in b.events]
    assert a.counts == b.counts


def test_snippet_indices_bracket_the_onset_and_stay_in_range():
    x, peak = ramp_then_cliff()
    event = detect_drops(x, FS, params()).events[0]

    assert 0 <= event.snippet_start_idx < event.onset_idx
    assert event.onset_idx < event.snippet_end_idx <= len(x)
    assert event.up_region_start_idx < event.up_region_end_idx <= event.onset_idx


def test_events_carry_the_parameters_that_produced_them():
    """Every event has to be self-describing, because the event table is
    the data-card's raw material and a row whose provenance lives only in
    a separate file is a row that will be quoted without it."""
    x, _ = ramp_then_cliff()
    event = detect_drops(x, FS, params()).events[0]
    assert event.segment_seconds == 20.0
    assert event.detrend_window_s == 2400.0
    assert event.dsax_threshold_mode == "quantile"
    assert event.dsax_trend_estimator == "ols_slope"


def test_working_core_imports_no_plotting_library():
    """CLAUDE.md rule 1, checked directly on this module's own import
    graph rather than trusted."""
    import Working.Detection.drop_motifs.cluster  # noqa: F401
    import Working.Detection.drop_motifs.detect   # noqa: F401
    import Working.Detection.drop_motifs.store    # noqa: F401

    forbidden = {"panel", "holoviews", "bokeh", "matplotlib"}
    loaded = {name.split(".")[0] for name in sys.modules}
    offenders = forbidden & loaded
    # Another test module may legitimately have imported matplotlib into
    # this interpreter already, so the check is on what OUR modules pull:
    # re-import them in a clean subprocess-like namespace is overkill here,
    # so assert on the module objects' own declared imports instead.
    import Working.Detection.drop_motifs.detect as _d
    import Working.Detection.drop_motifs.cluster as _c
    import Working.Detection.drop_motifs.store as _s
    for mod in (_d, _c, _s):
        names = {getattr(v, "__name__", "").split(".")[0]
                 for v in vars(mod).values()}
        assert not (forbidden & names), (
            f"{mod.__name__} imports a plotting library: {forbidden & names}")
    del offenders


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
