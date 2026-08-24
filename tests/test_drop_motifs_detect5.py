"""
test_drop_motifs_detect5.py
============================
Engineered-signal tests for the FIVE-STAGE spike-drop detector
(`Working.Detection.drop_motifs.detect5`) and its parameter derivation
(`Working.Detection.drop_motifs.autoparams`).

Same discipline as `tests/test_drop_motifs_detect.py`: every signal is
built so the correct answer is known before the detector runs.

What this module exists to pin, in the order the design settled:

  Q1/Q8/Q14 - THE WINDOW. The shipped three-stage detector sizes a
     snippet as multiples of the fall duration (2x before, 4x after),
     which on a periodic train is mathematically guaranteed to swallow
     neighbouring cycles: at a 236 s fall and a 510 s period the window
     is 1416 s wide and holds three spikes. The five-stage detector
     brackets the window on the SURROUNDING UP RUNS instead, mirrored
     for the two morphologies:

                          sharkfin (rise->fall)     trough (fall->rise)
         anchor           initial drop onset        initial drop onset
         left edge        start of preceding UP     END of previous UP
         right edge       start of NEXT UP          END of first UP after

     Both readings of one rule, so the trough case is a reflection and
     not a special case. `test_sharkfin_train_window_holds_exactly_one_fall`
     is the direct regression against the observed failure.

  Q2/Q9 - THE ALPHABET. dSAX already ships a five-symbol alphabet
     (d D S U u, outer bins lower case). Under `quantile` threshold mode
     its cutlines are OCCUPANCY quantiles and carry no information about
     how steep "steep" is, so the outer bands here are re-pinned to the
     MAD noise floor - `d` means "at least slope_sigma sigmas of noise
     steeper than nothing", a physical claim.
     `test_fast_band_survives_padding_with_quiescent_data` is what
     separates that from a plain quantile encoding: padding a signal with
     flat data moves every quantile and must NOT move a noise-pinned band.

  Q3 - THE GATES. Two per-event rejections, both local and both
     physical: a rise-triggered event needs a real rise before its fall
     (`min_rise_frac`), and any event's fall must dominate its own window
     (`min_fall_dominance`). These are what keep a slow non-event out of a
     cluster that then averages it with real spikes.

  Q4/Q10/Q13 - THE TRIGGERS. Rise->fall and bare fast-down both fire; the
     rise trigger wins where both do; the morphology is decided ONCE per
     span so every window in a span shares its geometry.

  Q11 - THE GRADE. `window_purity` re-runs the drop gate inside each
     stored window and counts qualifying falls. A clean extraction scores
     exactly 1 everywhere; the failure this whole ticket is about scores 3.

  Q7/Q12 - THE PARAMETERS. Derived from the span's own dominant period,
     seeded by autocorrelation and then refined from the detected
     inter-onset intervals, because a frequency-modulated train (M2_aug
     336-346 h, "fm decreasing") has no single period for any estimator
     to find and its ACF lands on 12.2 cycles against an annotated 16.

Pure numpy/scipy, no matplotlib: `Working/` may not import a plotting
library (CLAUDE.md rule 1), and the last test here is that check.
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
import pytest

from Working.Detection.drop_motifs.autoparams import (
    autotune,
    derive_params,
    dominant_period,
)
from Working.Detection.drop_motifs.detect5 import (
    MORPHOLOGY_SHARKFIN,
    MORPHOLOGY_TROUGH,
    Detect5Params,
    choose_morphology,
    detect_drops5,
    stage_letters,
    window_purity,
)

FS = 1.0


# -- signal builders -------------------------------------------------------
#
# Everything is built from linear segments so that "the fall" has an exact
# start sample, an exact end sample and an exact slope. Noise is added only
# where a test needs a defined noise floor for the MAD estimator, and then
# with a fixed seed.

def sharkfin_cycle(rise_s=300, fall_s=60, amplitude=10.0, flat_s=40):
    """One rise-then-fall cycle: slow linear rise, fast linear fall, flat.

    Rise and fall differ 5x in duration, so the fall is unambiguously the
    steep part and a 5-symbol alphabet has something to separate.
    """
    return np.concatenate([
        np.linspace(0.0, amplitude, int(rise_s), endpoint=False),
        np.linspace(amplitude, 0.0, int(fall_s), endpoint=False),
        np.zeros(int(flat_s)),
    ])


def sharkfin_train(n_cycles=4, lead_s=200, **kw):
    """`n_cycles` identical sharkfins with a quiet lead-in.

    Returns `(x, onsets)` where each onset is the exact index of the first
    sample of that cycle's fall - the sample the detector must anchor on.
    """
    cyc = sharkfin_cycle(**kw)
    rise_s = int(kw.get("rise_s", 300))
    x = [np.zeros(int(lead_s))]
    onsets = []
    at = int(lead_s)
    for _ in range(n_cycles):
        onsets.append(at + rise_s)
        x.append(cyc)
        at += len(cyc)
    return np.concatenate(x), onsets


def trough_cycle(flat_s=200, fall_s=40, bottom_s=60, rise_s=120,
                 amplitude=10.0):
    """One fall-then-rise cycle: flat, fast fall, flat bottom, slow recovery.

    The mirror of `sharkfin_cycle`. The motif's right half is the RECOVERY,
    which is an UP run - so a window rule that stops at "the next UP run"
    would cut this event in half.
    """
    return np.concatenate([
        np.zeros(int(flat_s)),
        np.linspace(0.0, -amplitude, int(fall_s), endpoint=False),
        np.full(int(bottom_s), -amplitude),
        np.linspace(-amplitude, 0.0, int(rise_s), endpoint=False),
    ])


def trough_train(n_cycles=4, lead_s=200, **kw):
    """`n_cycles` trough spikes. Returns `(x, onsets)`; the onset is the
    first sample of the fall INTO the trough, i.e. the initial drop, which
    is the anchor for both morphologies."""
    cyc = trough_cycle(**kw)
    flat_s = int(kw.get("flat_s", 200))
    x = [np.zeros(int(lead_s))]
    onsets = []
    at = int(lead_s)
    for _ in range(n_cycles):
        onsets.append(at + flat_s)
        x.append(cyc)
        at += len(cyc)
    return np.concatenate(x), onsets


def fm_sharkfin_train(periods_s, fall_frac=0.2, amplitude=10.0, lead_s=200):
    """A frequency-modulated sharkfin train - the M2_aug am16 morphology.

    `periods_s` gives each cycle its own period, so the train has no single
    period and its autocorrelation cannot be right. Returns
    `(x, onsets, true_median_period)`.
    """
    x = [np.zeros(int(lead_s))]
    onsets = []
    at = int(lead_s)
    for p in periods_s:
        fall = max(4, int(p * fall_frac))
        rise = int(p) - fall
        x.append(np.linspace(0.0, amplitude, rise, endpoint=False))
        onsets.append(at + rise)
        x.append(np.linspace(amplitude, 0.0, fall, endpoint=False))
        at += rise + fall
    return np.concatenate(x), onsets, float(np.median(periods_s))


def noisy(x, sigma=0.02, seed=11):
    return x + np.random.default_rng(seed).normal(0.0, sigma, len(x))


def params5(**kw):
    """`Detect5Params` sized for the engineered signals above.

    `detrend_window_s` is deliberately long relative to the event SPACING,
    not merely to one event: a window shorter than the spacing turns the
    rolling mean's own recovery into a fall and the detector correctly
    reports it (pinned for the three-stage detector already).
    """
    base = dict(
        detrend_window_s=4000.0,
        segment_seconds=20.0,
        same_fraction=0.5,
        slope_sigma=4.0,
        merge_gap_segments=0,
        min_depth_frac=0.10,
        min_separation_s=0.0,
        lookahead_mult=3.0,
        trough_knee_frac=0.05,
        min_rise_frac=0.5,
        min_fall_dominance=0.5,
        window_cap_mult=6.0,
        window_pad_frac=0.25,
        morphology="auto",
    )
    base.update(kw)
    return Detect5Params(**base)


# ===========================================================================
# Q2/Q9 - the five-stage alphabet
# ===========================================================================

def test_five_stage_alphabet_uses_all_five_symbols_on_a_signal_that_has_them():
    """A signal built with a gentle rise, a steep rise, a gentle fall and a
    steep fall must produce all four non-SAME symbols.

    This is the minimum claim of the whole extension: three symbols cannot
    tell "up" from "fast up", and if the encoder never emits `u` or `d` on
    a signal that plainly contains both, the extra bands are decoration.
    """
    x = np.concatenate([
        np.zeros(400),
        np.linspace(0.0, 2.0, 400),      # gentle rise   -> U
        np.linspace(2.0, 12.0, 60),      # steep rise    -> u
        np.full(200, 12.0),              # flat          -> S
        np.linspace(12.0, 10.0, 400),    # gentle fall   -> D
        np.linspace(10.0, 0.0, 60),      # steep fall    -> d
        np.zeros(400),
    ])
    letters, _ = stage_letters(noisy(x), FS, params5())
    for sym in "dDSUu":
        assert sym in letters, (
            f"symbol {sym!r} never emitted; got {sorted(set(letters))} "
            f"from {letters}")


def test_fast_band_membership_follows_the_noise_floor_not_the_quantile():
    """`d` must mean "steeper than slope_sigma sigmas of noise".

    Under dSAX's `quantile` mode the outer cutlines are occupancy
    quantiles, which say how RARE a segment is and nothing about how steep
    it is. Decision 2.7 of the shipped detector already found that such a
    cutline lands three orders of magnitude below a real drop's slope and
    cannot serve as a threshold. So the five-stage encoder re-pins its
    outer bands to the MAD noise floor, and this asserts that directly.
    """
    x, _ = sharkfin_train(n_cycles=4)
    p = params5()
    letters, details = stage_letters(noisy(x), FS, p)

    sigma = details["sigma_slope"]
    cut = -p.slope_sigma * sigma
    seg_slopes = np.asarray(details["segment_slopes"], dtype=float)
    assert len(seg_slopes) == len(letters)

    is_fast_down = np.array([c == "d" for c in letters])
    assert np.all(seg_slopes[is_fast_down] <= cut), (
        "a segment labelled `d` is shallower than the noise-pinned cutline")
    assert np.all(seg_slopes[~is_fast_down] > cut), (
        "a segment steeper than the cutline was not labelled `d`")


def test_fast_band_survives_padding_with_quiescent_data():
    """Appending flat data moves every occupancy quantile and must not
    move a noise-pinned band.

    This is the test that distinguishes the shipped `dsax(alphabet_size=5)`
    under quantile mode from what this module does. Pad a four-cycle train
    with an equal length of quiet baseline: the fraction of segments that
    are SAME roughly doubles, so a quantile cutline moves a long way, while
    a MAD estimate of the noise is unchanged because the noise is.
    """
    x, _ = sharkfin_train(n_cycles=4)
    short = noisy(x, seed=3)
    pad = np.random.default_rng(4).normal(0.0, 0.02, len(x))
    long = np.concatenate([short, pad])

    p = params5()
    letters_short, _ = stage_letters(short, FS, p)
    letters_long, _ = stage_letters(long, FS, p)

    n = len(letters_short)
    d_short = letters_short.count("d")
    d_long = letters_long[:n].count("d")
    assert abs(d_short - d_long) <= 1, (
        f"the fast-down band moved when quiescent data was appended: "
        f"{d_short} -> {d_long} over the same {n} segments; the band is "
        f"tracking occupancy, not the noise floor")


# ===========================================================================
# Q1/Q8/Q14 - the window
# ===========================================================================

def test_sharkfin_train_window_holds_exactly_one_fall():
    """THE regression. Four identical sharkfins, period 400 s, fall 60 s.

    Under the shipped fall-multiple rule the window would be
    2*60 + 60 + 4*60 = 420 s wide against a 400 s period and would
    therefore contain a neighbour. Bracketing on the surrounding UP runs
    cannot, because the next cycle's rise IS the boundary.
    """
    x, onsets = sharkfin_train(n_cycles=4)
    res = detect_drops5(noisy(x), FS, params5())

    assert len(res.events) == 4, (
        f"expected 4 sharkfins, got {len(res.events)}")
    assert res.morphology == MORPHOLOGY_SHARKFIN

    purity = window_purity(noisy(x), FS, res)
    assert purity == [1, 1, 1, 1], (
        f"every window must hold exactly one fall, got {purity}")


def test_sharkfin_window_stops_before_the_next_rise():
    """Right edge = start of the next UP run, so the window is strictly
    inside the gap between this fall and the next cycle's rise."""
    x, onsets = sharkfin_train(n_cycles=3)
    res = detect_drops5(noisy(x), FS, params5())
    assert len(res.events) == 3

    for ev, nxt in zip(res.events, res.events[1:]):
        assert ev.window_end_idx <= nxt.up_region_start_idx, (
            f"window ends at {ev.window_end_idx}, past the next rise at "
            f"{nxt.up_region_start_idx}")
        assert ev.window_end_idx > ev.trough_idx, (
            "the window must extend past the trough")


def test_trough_window_includes_the_recovery():
    """The mirror. A trough spike's recovery is an UP run and is PART of
    the motif, so the window must contain it - a naive "stop at the next
    UP run" rule would end the window at the bottom of the trough and
    throw away the right half of every event.
    """
    x, onsets = trough_train(n_cycles=3)
    res = detect_drops5(noisy(x), FS, params5(morphology=MORPHOLOGY_TROUGH))

    assert len(res.events) == 3, f"expected 3 troughs, got {len(res.events)}"
    assert res.morphology == MORPHOLOGY_TROUGH

    fall_s, bottom_s, rise_s = 40, 60, 120
    for ev in res.events:
        recovery_top = ev.onset_idx + fall_s + bottom_s + rise_s
        assert ev.window_end_idx >= recovery_top - 20, (
            f"window ends at {ev.window_end_idx}, before the recovery "
            f"completes near {recovery_top}; the trough was cut in half")


def test_window_is_capped_when_there_is_no_bounding_up_run():
    """An isolated event has no next UP run to stop at, so the fall
    multiple survives as a CAP. Without it the window runs to the end of
    the span."""
    x = np.concatenate([np.zeros(300),
                        np.linspace(0.0, 10.0, 300),
                        np.linspace(10.0, 0.0, 60),
                        np.zeros(4000)])
    p = params5(window_cap_mult=6.0)
    res = detect_drops5(noisy(x), FS, p)
    assert len(res.events) == 1
    ev = res.events[0]
    fall = ev.trough_idx - ev.onset_idx
    assert ev.window_end_idx - ev.trough_idx <= p.window_cap_mult * fall + 2, (
        "an unbounded window ran past its cap")
    assert ev.window_end_idx < len(x) - 1000, (
        "the window ran to the end of the span")


def test_both_morphologies_anchor_on_the_initial_drop():
    """Explicit operator requirement: up-same-down and down-same-up both
    align on the FIRST downward drop, so the two morphologies are
    comparable on one axis."""
    xs, sharkfin_onsets = sharkfin_train(n_cycles=3)
    xt, trough_onsets = trough_train(n_cycles=3)

    rs = detect_drops5(noisy(xs), FS, params5(morphology=MORPHOLOGY_SHARKFIN))
    rt = detect_drops5(noisy(xt), FS, params5(morphology=MORPHOLOGY_TROUGH))

    for ev, want in zip(rs.events, sharkfin_onsets):
        assert abs(ev.onset_idx - want) <= 25, (
            f"sharkfin anchored at {ev.onset_idx}, drop starts at {want}")
    for ev, want in zip(rt.events, trough_onsets):
        assert abs(ev.onset_idx - want) <= 25, (
            f"trough anchored at {ev.onset_idx}, drop starts at {want}")


# ===========================================================================
# Q3 - the gates
# ===========================================================================

def test_fall_with_no_preceding_rise_is_rejected_under_sharkfin_morphology():
    """Gate A. A fall that arrives out of nowhere is not a sharkfin, and
    under sharkfin morphology it must be counted out rather than silently
    kept - this is the "slow thing with no rise" that landed in cluster 3
    with four events spanning a 35x duration ratio.
    """
    x = np.concatenate([
        np.zeros(400),
        np.linspace(0.0, 10.0, 300),     # a real rise ...
        np.linspace(10.0, 0.0, 60),      # ... then a real fall  -> KEEP
        np.zeros(600),
        np.linspace(0.0, -10.0, 60),     # a fall with no rise   -> REJECT
        np.zeros(600),
    ])
    res = detect_drops5(noisy(x), FS,
                        params5(morphology=MORPHOLOGY_SHARKFIN,
                                min_rise_frac=0.5))
    assert len(res.events) == 1, (
        f"expected the riseless fall to be rejected, got {len(res.events)} "
        f"events")
    assert res.counts["rejected_no_rise"] >= 1, (
        "the rejection must be counted, not silent")


def test_fall_that_does_not_dominate_its_window_is_rejected():
    """Gate B. If the biggest thing in the window is not this fall, the
    window is not a picture of this event."""
    x = np.concatenate([
        np.zeros(300),
        np.linspace(0.0, 40.0, 200),     # a huge rise
        np.linspace(40.0, 39.0, 30),     # a tiny fall on top of it
        np.linspace(39.0, 40.0, 30),
        np.linspace(40.0, 0.0, 100),     # the real event
        np.zeros(600),
    ])
    res = detect_drops5(noisy(x), FS,
                        params5(min_fall_dominance=0.5, min_depth_frac=0.0))
    depths = [ev.drop_depth_mv for ev in res.events]
    assert all(d > 5_000.0 for d in depths), (
        f"a fall that does not dominate its window was kept: depths={depths}")
    assert res.counts["rejected_not_dominant"] >= 1


# ===========================================================================
# Q4/Q10/Q13 - triggers and morphology
# ===========================================================================

def test_trough_morphology_detects_falls_with_no_preceding_rise():
    """The bare fast-down trigger. Catalogue ID 25 and Mushroom's icicles
    have no UP run before the drop, so a rise-anchored detector finds
    nothing there; the five-stage detector must fire on `d` alone."""
    x, onsets = trough_train(n_cycles=4)
    res = detect_drops5(noisy(x), FS, params5(morphology=MORPHOLOGY_TROUGH))
    assert len(res.events) == 4, (
        f"the fall trigger found {len(res.events)} of 4 trough spikes")
    assert all(ev.trigger == "fall" for ev in res.events)


def test_morphology_is_chosen_once_per_span_and_reported():
    """Q13. One geometry per span, so an overlay compares like with like.
    `choose_morphology` is the decision and it is recorded on the result."""
    xs, _ = sharkfin_train(n_cycles=4)
    xt, _ = trough_train(n_cycles=4)
    p = params5(morphology="auto")

    assert choose_morphology(noisy(xs), FS, p) == MORPHOLOGY_SHARKFIN
    assert choose_morphology(noisy(xt), FS, p) == MORPHOLOGY_TROUGH

    res = detect_drops5(noisy(xt), FS, p)
    assert res.morphology == MORPHOLOGY_TROUGH
    assert len({ev.trigger for ev in res.events}) == 1, (
        "a span must not mix triggers once its morphology is decided")


def test_rise_trigger_wins_where_both_triggers_fire():
    """Q10. A sharkfin's fall satisfies the bare fast-down trigger too;
    the event must be typed by the stronger evidence and the suppression
    must be counted so the fall trigger's value is measurable."""
    x, _ = sharkfin_train(n_cycles=3)
    res = detect_drops5(noisy(x), FS, params5(morphology=MORPHOLOGY_SHARKFIN))
    assert all(ev.trigger == "rise" for ev in res.events)
    assert res.counts["fall_trigger_suppressed"] >= 3, (
        "on a sharkfin train the fall trigger should be suppressed on "
        "essentially every event")


# ===========================================================================
# Q11 - the grade
# ===========================================================================

def test_window_purity_counts_the_falls_a_window_actually_holds():
    """The headline number of the report. A window that swallowed three
    cycles must score 3, or the metric cannot detect the bug it exists to
    detect."""
    x, _ = sharkfin_train(n_cycles=4)
    xn = noisy(x)
    res = detect_drops5(xn, FS, params5())
    assert window_purity(xn, FS, res) == [1, 1, 1, 1]

    widened = detect_drops5(xn, FS, params5(window_cap_mult=6.0,
                                            window_pad_frac=0.25,
                                            bracket_on_up_runs=False))
    assert max(window_purity(xn, FS, widened)) >= 2, (
        "with the UP bracket disabled the fall-multiple window must "
        "demonstrably swallow a neighbour - otherwise this test is not "
        "measuring the failure it claims to")


# ===========================================================================
# Q7/Q12 - parameter derivation
# ===========================================================================

def test_dominant_period_recovers_a_known_period():
    x, _ = sharkfin_train(n_cycles=8)
    period, confidence = dominant_period(noisy(x), FS)
    assert abs(period - 400.0) < 40.0, f"got {period}, expected ~400 s"
    assert confidence > 0.5


def test_dominant_period_reports_low_confidence_on_noise():
    """The ACF peak height is the confidence gate: on the real spans it
    reads >=0.58 wherever the period is right and <=0.36 wherever it is
    wrong, so it must not read high on something aperiodic."""
    x = np.random.default_rng(5).normal(0.0, 1.0, 8000)
    _, confidence = dominant_period(x, FS)
    assert confidence < 0.4, f"noise reported confidence {confidence}"


def test_derive_params_scales_with_the_period():
    """`segment_seconds` ~ period/8 so a rise spans several segments;
    `detrend_window_s` a small multiple of the period so the drift goes
    and the event stays. Both must move WITH the period rather than being
    constants wearing a derivation."""
    a = derive_params(period_s=400.0, fs=FS, n_samples=8000)
    b = derive_params(period_s=4000.0, fs=FS, n_samples=80000)
    assert b["segment_seconds"] > 5 * a["segment_seconds"]
    assert b["detrend_window_s"] > 5 * a["detrend_window_s"]
    assert a["segment_seconds"] < 400.0 / 4


def test_autotune_converges_and_reports_every_pass():
    """The iteration must be inspectable: a fixed point reached silently
    is indistinguishable from one that was never sought."""
    x, onsets = sharkfin_train(n_cycles=8)
    result = autotune(noisy(x), FS, max_passes=3)
    assert result.converged
    assert 1 <= len(result.trace) <= 3
    for pass_info in result.trace:
        assert "period_s" in pass_info and "n_events" in pass_info
    assert abs(result.period_s - 400.0) < 60.0


def test_autotune_beats_its_own_acf_seed_on_a_frequency_modulated_train():
    """The M2_aug am16 case, synthesised. Its annotation says "frequency
    modulation fm decreasing" and its autocorrelation lands on 12.2 cycles
    against an annotated 16, because a non-stationary train has no single
    period. Refining from the DETECTED inter-onset intervals does not
    assume stationarity and must therefore do better.
    """
    periods = list(range(700, 300, -50))          # 8 cycles, 700 s -> 350 s
    x, onsets, true_median = fm_sharkfin_train(periods)
    xn = noisy(x)

    seed_period, _ = dominant_period(xn, FS)
    result = autotune(xn, FS, max_passes=3)

    assert abs(result.period_s - true_median) < abs(seed_period - true_median), (
        f"refinement did not improve on the seed: seed={seed_period:.0f}, "
        f"refined={result.period_s:.0f}, true median={true_median:.0f}")

    # All but the FIRST cycle. The first sits inside the leading half of
    # the detrend window, where the rolling mean is computed against
    # edge-padded data and flattens the event along with the drift - a
    # property of any high pass at a boundary, not of this detector. The
    # real spans are annotated with quiet margins for exactly this reason
    # and the report records the first onset so an edge loss is visible.
    assert len(result.events) >= len(periods) - 1, (
        f"found {len(result.events)} of {len(periods)} modulated cycles")


# ===========================================================================
# hygiene
# ===========================================================================

def test_detection_is_deterministic():
    x, _ = sharkfin_train(n_cycles=5)
    xn = noisy(x)
    a = detect_drops5(xn, FS, params5())
    b = detect_drops5(xn, FS, params5())
    assert [e.onset_idx for e in a.events] == [e.onset_idx for e in b.events]
    assert [e.window_end_idx for e in a.events] == \
           [e.window_end_idx for e in b.events]


def test_five_stage_core_imports_no_plotting_library():
    """CLAUDE.md rule 1, checked on this module's own import graph rather
    than trusted."""
    import Working.Detection.drop_motifs.autoparams as _a
    import Working.Detection.drop_motifs.detect5 as _d

    forbidden = {"panel", "holoviews", "bokeh", "matplotlib"}
    for mod in (_a, _d):
        names = {getattr(v, "__name__", "").split(".")[0]
                 for v in vars(mod).values()}
        assert not (forbidden & names), (
            f"{mod.__name__} imports a plotting library: {forbidden & names}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
