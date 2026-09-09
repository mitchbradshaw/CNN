"""drop_motifs10 Task 1 - the seven carried-forward defects, one test each.

Numbered as `Pipelines/drop_motifs/DETECTION_AND_FIGURES.md` sec 6 and the
drop_motifs10 brief number them. Every fix in Task 1 has a test here so
that a fix which regresses is a red suite rather than a quiet change in a
count nobody re-derives.

Defect 2 is covered by `tests/test_drop_motifs_round2_store.py` (the key
collision that produced it) and by `test_no_feature_vector_is_all_zeros`
below (the consequence it produced in the tree).
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import passes6, passes8, passes9, select10
from Working.Detection.drop_motifs import cluster, detect5

FIG2A = "DATA/derived/channels/Fig2A_dt0p1/CH{}.npy"
FS = 10.0


def _channel(n):
    return np.asarray(np.load(FIG2A.format(n)), dtype=float)


def _base_events(channel, window_index):
    """The base pass over one Fig2A sliding window, in ABSOLUTE samples."""
    x = _channel(channel)
    start, end = passes9.window_bounds(len(x), FS, 50.0, 0.5)[window_index]
    tuned = passes6.run_base(x[start:end], FS, max_passes=3)
    return start, tuned.result


# ---------------------------------------------------------------------------
# 1. the tolerance was a duration compared against a difference of indices
# ---------------------------------------------------------------------------

def _pair(fs, onset_a, onset_b, fall_s):
    """Two same-direction candidates, `passes6.deduplicate`'s input shape."""
    def entry(pass_key, onset):
        row = {"fs": fs, "onset_idx": onset}
        return (pass_key, +1, onset, onset + int(fall_s * fs), fall_s,
                onset - 10, onset + 20, (row, {}, +1))
    return [entry("base", onset_a), entry("fine", onset_b)]


def test_two_detections_one_sample_apart_at_10hz_merge():
    """`tolerance = onset_frac * fall_s` is SECONDS; the onsets it is
    compared against are SAMPLE INDICES. At 10 Hz that makes the tolerance
    ten times too small, which is how the drop_motifs9 store came to hold
    61 pairs sharing a channel and a trough sample.

    The worked case from DETECTION_AND_FIGURES.md sec 4.1: CH1 window 36,
    `base` 9063 and `fine` 9064, fall 0.6 s. Tolerance as computed is
    0.5 x 0.6 = 0.3 "samples"; multiplied by fs it is 3, and they merge.
    """
    kept = passes6.deduplicate(_pair(10.0, 9063, 9064, 0.6))
    assert len(kept) == 1
    assert kept[0][0] == "base"


def test_the_same_pair_at_1hz_behaves_as_drop_motifs5_did():
    """The re-baseline must not move any 1 Hz count. At fs = 1 the two
    quantities are numerically equal, so multiplying by fs is the identity
    and every catalogue span reproduces.
    """
    # 0.3 samples of tolerance: one sample apart is NOT a duplicate.
    assert len(passes6.deduplicate(_pair(1.0, 9063, 9064, 0.6))) == 2
    # 5 samples of tolerance at a 10 s fall: two apart IS a duplicate.
    assert len(passes6.deduplicate(_pair(1.0, 9063, 9065, 10.0))) == 1


def test_passes8_deduplicate_and_passes6_deduplicate_now_agree_on_scale():
    """passes8 fixed this in its own copy. Two copies of one rule that
    disagree is how the bug survived; they must now give the same answer.
    """
    candidates = _pair(10.0, 9063, 9064, 0.6)
    assert (len(passes6.deduplicate(candidates))
            == len(passes8.deduplicate(candidates)) == 1)


# ---------------------------------------------------------------------------
# 2. the store must not disagree with itself, and no motif may be a constant
# ---------------------------------------------------------------------------

def test_no_feature_vector_is_all_zeros():
    """`cluster.feature_matrix` z-normalises, so a constant waveform
    becomes an all-zero vector and every such motif lands on top of every
    other at distance zero. 22 of the 1058 shipped refined motifs did
    exactly that and took the cophenetic r from 0.408 to a reported 0.681.
    A zero-variance feature row is now a fault, not a data point.
    """
    waveforms = [np.linspace(0.0, -1.0, 9), np.array([0.4, 0.1, -0.3, -0.9])]
    features = cluster.feature_matrix(waveforms)
    assert np.all(features.std(axis=1) > 0)

    with pytest.raises(ValueError):
        cluster.feature_matrix(waveforms + [np.full(6, -0.2)])


# ---------------------------------------------------------------------------
# 3 & 4. the trough search runs past the NEXT FALL, and eats it
# ---------------------------------------------------------------------------
#
# Both named regression cases are the same defect. `_fall_limit` bounds
# `find_trough` on the next RISE and on nothing else, so a drop whose
# recovery is not encoded as a rise lets the search reach the following
# drop. `find_trough` then takes the NEIGHBOUR's steepest sample as its
# reference and `refine_onset` walks the onset forward onto it; the
# min_separation dedup then deletes the neighbour's own detection as a
# duplicate of the relocated one. Two visible drops become one.

def test_fall_limit_stops_at_the_next_fall_not_only_the_next_rise():
    """The unit statement of the defect, with no recording involved.

    Two falls, no rise encoded between them. The limit must land on the
    second fall's start, not run past it.
    """
    rises = [(40, 42)]                    # a rise, far past both falls
    falls = [(2, 4), (20, 22)]            # segments
    sps = 2
    limit = detect5._fall_limit(4, rises, sps, 200, falls=falls,
                                min_separation_samples=5.0)
    assert limit == 40                    # 20 * sps, the second fall's start
    # Without the falls the old behaviour is unchanged.
    assert detect5._fall_limit(4, rises, sps, 200) == 80


def test_fall_limit_does_not_split_one_fall_that_the_encoding_broke():
    """`ddSdd` is one fall the encoding split, not two events. A fall run
    that starts within `min_separation` of the onset is the same event and
    must not bound the search - which is why the bound is gated on the
    detector's own statement of how far apart two events must be.
    """
    limit = detect5._fall_limit(4, [(40, 42)], 2, 200,
                                falls=[(2, 4), (5, 7)],
                                min_separation_samples=9.0)
    assert limit == 80                    # the rise; the near fall is ignored


def test_ch4_window05_second_visible_drop_is_detected():
    """Defect 3, by sample index. CH4 window 05 (samples 1250-1750) holds
    23 d-runs; the second, at samples 1296-1300, reaches the d threshold
    and produced no detection. Measured cause: `_fall_limit` returned
    sample 1340 (the next RISE, 4.4 s away, past the next drop), the
    trough came back at 1339 and `refine_onset` moved the onset 36 samples
    forward to 1332 - the next drop, which the min_separation dedup then
    deleted as a duplicate of the relocated one.

    Four of that window's 23 d-runs were lost this way (129.6, 135.4,
    140.8, 156.2 s). Fixed, all 23 d-runs yield exactly one detection each
    and no candidate is rejected by any gate.
    """
    start, result = _base_events(4, 5)
    onsets = sorted(start + ev.onset_idx for ev in result.events)
    assert any(1282 <= o <= 1300 for o in onsets), (
        f"no detection for the d-run at samples 1296-1300; got {onsets}")
    # and it must not have cost the drop that used to swallow it
    assert any(1325 <= o <= 1340 for o in onsets)
    # one detection per d-run, nothing rejected
    assert result.counts["drops_confirmed"] == result.counts["candidates"] == 23


def test_ch1_the_0p172_mv_drop_at_904_6s_is_detected():
    """Defect 4, by sample index. CH1 window 36 (samples 9000-9500). The
    operator's miss between M2 and M3 measures 0.172 mV - above the 0.1 mV
    instrument floor, so the depth gate does not excuse it. Measured
    cause: a CHAIN, and only its first link is defect 3's.

      1. `refine_onset` only ever searches [onset, trough], so it cannot
         move an onset BACK. The proposal lands at 9055, part-way down,
         and the depth the gates read is 0.086 mV rather than 0.166 mV -
         `min_depth_frac` then rejects it as shallow.
         Fixed by `detect5.walk_back_to_shoulder`.
      2. With the depth right, Gate B rejects it instead: no rise is
         encoded between this drop and the 0.34 mV drop at 9063, so no
         value of `min_rise_frac` gives `tighten_window` a boundary and
         the window [9050, 9076) holds both. Dominance 0.202.
         Fixed by bounding `window_bounds` on the next FALL as well.

    Detected onset 9052, depth 0.127 mV, dominance 0.944.
    """
    start, result = _base_events(1, 36)
    found = [(start + ev.onset_idx, ev.drop_depth_mv) for ev in result.events]
    hits = [d for o, d in found if 9045 <= o <= 9062]
    assert hits, f"no detection in samples 9045-9062; got {sorted(found)}"
    # above the 0.1 mV instrument floor, which is the whole point of the case
    assert max(hits) >= 0.10, f"detected but below the floor: {hits}"


# ---------------------------------------------------------------------------
# 7. window_index is not a safe selector
# ---------------------------------------------------------------------------

def test_selecting_a_sample_range_ignores_which_window_won():
    """A drop inside two overlapping windows is stored ONCE, tagged with
    whichever window the best-framed rule picked - often the neighbour.
    `window_index == N` therefore hides drops inside window N's own range.
    This undercounted every case-study window in v2 (CH4: 11 against 21).
    """
    rows = [
        {"event_id": "a", "onset_idx": 1260, "window_index": 4},
        {"event_id": "b", "onset_idx": 1400, "window_index": 5},
        {"event_id": "c", "onset_idx": 1700, "window_index": 6},
        {"event_id": "d", "onset_idx": 1800, "window_index": 6},
    ]
    got = select10.in_sample_range(rows, 1250, 1750)
    assert [r["event_id"] for r in got] == ["a", "b", "c"]
    # the selector this replaces would have returned only "b"
    assert [r["event_id"] for r in rows if r["window_index"] == 5] == ["b"]


def test_selecting_a_window_selects_its_range_not_its_label():
    got = select10.in_window(
        [{"event_id": "a", "onset_idx": 1260, "window_index": 4}],
        3000, FS, window_index=5, window_s=50.0, overlap=0.5)
    assert [r["event_id"] for r in got] == ["a"]
