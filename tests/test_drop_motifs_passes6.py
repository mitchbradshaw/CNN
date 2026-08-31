"""
Multi-scale detection: identity, deduplication and scale banding.

These are the parts of `passes6` that decide what ends up in the motif
library. A fault in any of them is silent - the figures still draw, they
just describe a set that double-counts, mis-groups, or overwrites itself.
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import passes6


# -- identity -----------------------------------------------------------

def test_the_same_onset_from_two_passes_gets_two_distinct_keys():
    """The double-counting trap the pass tag exists to close.

    drop_motifs5 keyed on `id{cat}_r{rec}_{onset}`. With more than one
    pass over a span, a fine-pass detection at the same onset as a base
    one would collide with it and silently replace it on write.
    """
    base = passes6.motif_key(24, 2, passes6.PASS_BASE, 145_000)
    fine = passes6.motif_key(24, 2, passes6.PASS_FINE, 145_000)

    assert base != fine
    assert base == "id024_r2_base_145000"
    assert fine == "id024_r2_fine_145000"


def test_the_key_is_stable_so_re_running_a_pass_is_idempotent():
    """Re-importing must not populate the library with duplicates."""
    first = passes6.motif_key(385, 385, passes6.PASS_INV, 9_412)
    second = passes6.motif_key(385, 385, passes6.PASS_INV, 9_412)
    assert first == second


def test_two_spans_on_one_recording_do_not_collide():
    """ID 20 is a sub-span of ID 1 and ID 21 of ID 3, on recording 1."""
    assert (passes6.motif_key(1, 1, passes6.PASS_BASE, 1_212_000)
            != passes6.motif_key(20, 1, passes6.PASS_BASE, 1_212_000))


# -- deduplication ------------------------------------------------------

def _candidate(pass_key, onset, fall_s, sign=1, trough=None,
               start=None, end=None):
    """A dedup candidate.

    `sign` defaults to +1 (a drop) and `trough` to just after the onset,
    so a test about same-direction onset proximity is not accidentally
    also exercising the opposite-direction rule.
    """
    if trough is None:
        trough = onset + 1
    if start is None:
        start = onset - 1
    if end is None:
        end = onset + 1
    return (pass_key, sign, onset, trough, fall_s, start, end,
            {"onset": onset})


def test_a_fine_pass_rediscovery_of_a_base_event_is_dropped():
    """The fine pass re-finds most of the base pass at a tighter window.

    Keeping both would double every event, and the pooled dendrogram would
    then report the same motif twice as a two-member "family".
    """
    kept = passes6.deduplicate([
        _candidate(passes6.PASS_BASE, 1000, 100.0),
        _candidate(passes6.PASS_FINE, 1012, 60.0),     # same event
        _candidate(passes6.PASS_FINE, 4000, 20.0),     # genuinely new
    ])

    assert [entry[0] for entry in kept] == [passes6.PASS_BASE,
                                            passes6.PASS_FINE]
    assert [entry[2] for entry in kept] == [1000, 4000]


def test_the_base_pass_wins_because_it_is_offered_first():
    kept = passes6.deduplicate([
        _candidate(passes6.PASS_BASE, 500, 80.0),
        _candidate(passes6.PASS_FINE, 505, 30.0),
    ])
    assert len(kept) == 1
    assert kept[0][0] == passes6.PASS_BASE


def test_tolerance_scales_with_duration_not_with_samples():
    """The spans run 0.2 h to 90 h; no fixed sample tolerance serves both.

    Two events 40 samples apart are the same detection when the fall is
    200 s long, and two different ones when it is 10 s long.
    """
    long_fall = passes6.deduplicate([
        _candidate(passes6.PASS_BASE, 1000, 200.0),
        _candidate(passes6.PASS_FINE, 1040, 200.0),
    ])
    short_fall = passes6.deduplicate([
        _candidate(passes6.PASS_BASE, 1000, 10.0),
        _candidate(passes6.PASS_FINE, 1040, 10.0),
    ])

    assert len(long_fall) == 1
    assert len(short_fall) == 2


def test_deduplicate_preserves_order_and_keeps_everything_distinct():
    candidates = [_candidate(passes6.PASS_BASE, i * 1000, 50.0)
                  for i in range(5)]
    assert passes6.deduplicate(candidates) == candidates


def test_a_sharkfins_own_rising_edge_is_not_a_second_motif():
    """The catalogue ID 1 defect.

    On a sharkfin the rise and the fall are ONE physical excursion: the
    rise tops out exactly where the fall begins. The inverted pass finds
    that rise, and its onset sits a few hundred seconds before the fall -
    outside the same-direction tolerance - so ID 1 reported 17 drops plus
    16 "rises" that were the leading edges of those same 17 drops.
    """
    kept = passes6.deduplicate([
        # the sharkfin: its fall begins at 1000
        _candidate(passes6.PASS_BASE, 1000, 400.0, sign=1, trough=1400),
        # its own rising edge: begins at 850 and PEAKS at 1000
        _candidate(passes6.PASS_INV, 850, 120.0, sign=-1, trough=1000),
    ])

    assert len(kept) == 1
    assert kept[0][0] == passes6.PASS_BASE


def test_a_genuine_opposite_direction_spike_survives():
    """The rule must not throw away what the inverted pass is for.

    ID 385's upward spikes are their own excursions: they peak in a quiet
    stretch, not at the onset of any drop. A window-containment rule was
    tried here first and deleted 15 of the 17 of them, because a wide
    quiet window happens to contain them.
    """
    kept = passes6.deduplicate([
        _candidate(passes6.PASS_BASE, 1000, 20.0, sign=1, trough=1020,
                   start=900, end=6000),
        _candidate(passes6.PASS_INV, 5000, 15.0, sign=-1, trough=5015),
    ])

    assert len(kept) == 2
    assert kept[1][0] == passes6.PASS_INV


# -- scale bands --------------------------------------------------------

def test_a_coherent_span_is_not_split():
    """ID 21 is a clean sharkfin train; splitting it costs the comparison."""
    bands, labels = passes6.scale_bands([100.0, 120.0, 140.0, 110.0, 135.0])

    assert set(bands.tolist()) == {0}
    assert len(labels) == 1


def test_a_two_scale_span_is_split_into_two_bands():
    """The ID 24 / ID 34 problem: two scales overlaid on one axis."""
    durations = [8.0, 9.0, 7.5, 8.5, 210.0, 190.0, 230.0, 205.0]
    bands, labels = passes6.scale_bands(durations)

    assert len(labels) == 2
    assert bands[:4].tolist() == [0, 0, 0, 0]
    assert set(bands[4:].tolist()) == {1}


def test_a_lone_outlying_duration_does_not_get_its_own_panel():
    """A band with one trace in it is not an overlay."""
    durations = [10.0, 11.0, 9.5, 10.5, 12.0, 11.5, 900.0]
    _, labels = passes6.scale_bands(durations)

    assert len(labels) == 1


def test_band_labels_state_the_durations_they_hold():
    durations = [8.0, 9.0, 7.5, 8.5, 210.0, 190.0, 230.0, 205.0]
    _, labels = passes6.scale_bands(durations)

    assert labels[0] == "8-9 s"
    assert labels[1] == "190-230 s"


def test_scale_bands_of_an_empty_set_returns_empty():
    bands, labels = passes6.scale_bands([])
    assert bands.size == 0
    assert labels == []


def test_bands_are_ordered_fine_to_coarse():
    """Band 0 must be the fastest events, so panels read top-down by scale."""
    durations = [400.0, 380.0, 420.0, 12.0, 11.0, 13.0, 14.0]
    bands, _ = passes6.scale_bands(durations)

    fast = np.array(durations)[bands == 0]
    slow = np.array(durations)[bands == 1]
    assert fast.max() < slow.min()


# -- the inverted pass stores the signal as recorded --------------------

def test_inverted_pass_is_documented_as_sign_flagged_not_sign_stored():
    """A library holding a negated waveform and calling it the recording
    is a trap for every later consumer; the row carries the sign instead."""
    assert passes6.PASS_INV in passes6.PASS_ORDER
    assert "rising" in passes6.PASS_LABELS[passes6.PASS_INV]
