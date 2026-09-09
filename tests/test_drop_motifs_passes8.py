"""
drop_motifs8: a rise is only a rise if no drop already accounts for it,
and the largest drops get a family of their own.

Both rules were derived from measurement on the stored 7.3 library rather
than proposed and then checked.
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import passes8


def _entry(pass_key, sign, onset, trough, fall_s, fs=1.0):
    """One `deduplicate` candidate. The payload is never inspected."""
    return (pass_key, sign, onset, trough, fall_s,
            onset - 50, trough + 50, {"fs": fs})


# ---------------------------------------------------------------------------
# rises are what the drops left over
# ---------------------------------------------------------------------------

def test_a_rise_that_begins_where_a_drop_bottoms_out_is_that_drops_recovery():
    """Catalogue ID 10, measured from the 7.3 store: every one of its 30
    surviving inverted detections starts within a sample or two of a kept
    drop's trough. They are the recovery edge of the same excursion, not
    30 separate events - which is why the figure alternated drop, rise,
    drop, rise down the whole train."""
    kept = passes8.deduplicate([
        _entry("base", +1, 1362676, 1362707, 31.0),
        _entry("inv", -1, 1362708, 1362773, 65.0),
    ])

    assert [e[0] for e in kept] == ["base"]


def test_the_leading_edge_rule_still_holds():
    """Rule 2 from drop_motifs6: a rise that PEAKS where a drop begins is
    that drop's leading edge. ID 1 without it reported 17 drops plus 16
    rises describing the same 17 events."""
    kept = passes8.deduplicate([
        _entry("base", +1, 1000, 1030, 30.0),
        _entry("inv", -1, 940, 1001, 60.0),
    ])

    assert [e[0] for e in kept] == ["base"]


def test_an_isolated_rise_is_kept():
    """The rule must not cost ID 385 the opposite-direction population the
    supervisor asked for. A rise in a quiet stretch touches no drop."""
    kept = passes8.deduplicate([
        _entry("base", +1, 1000, 1030, 30.0),
        _entry("inv", -1, 8000, 8040, 40.0),
    ])

    assert [e[0] for e in kept] == ["base", "inv"]


def test_a_rise_is_measured_against_every_kept_drop_not_only_the_last():
    kept = passes8.deduplicate([
        _entry("base", +1, 1000, 1030, 30.0),
        _entry("base", +1, 5000, 5030, 30.0),
        _entry("inv", -1, 1031, 1090, 59.0),
    ])
    assert len(kept) == 2


def test_the_tolerance_is_in_samples_not_seconds():
    """`fall_duration_s` is seconds and the onsets are sample indices. At
    fs = 1 Hz - every recording in this catalogue - the two coincide and
    the confusion is invisible; at any other rate it scales the tolerance
    by fs and silently merges or splits everything."""
    at_1hz = passes8.deduplicate(
        [_entry("base", +1, 1000, 1030, 30.0, fs=1.0),
         _entry("inv", -1, 1044, 1100, 56.0, fs=1.0)])
    at_10hz = passes8.deduplicate(
        [_entry("base", +1, 1000, 1300, 30.0, fs=10.0),
         _entry("inv", -1, 1440, 2000, 56.0, fs=10.0)])

    # The same event geometry in seconds must give the same verdict.
    assert len(at_1hz) == len(at_10hz)


# ---------------------------------------------------------------------------
# the largest drops get their own family
# ---------------------------------------------------------------------------

def _id010_depths():
    """Catalogue ID 10's 86 drop depths, from the 7.3 store. Two stand
    clear of the rest: 7.30 and 5.38 mV against a median of 2.41."""
    band0 = [1.9, 1.86, 1.85, 1.85, 1.68, 1.66, 1.65, 1.6, 1.56, 1.38,
             1.38, 1.35, 1.33, 1.31, 1.3, 1.3, 1.29, 1.22]
    band1 = [7.3, 2.81, 2.51, 2.49, 2.47, 2.45, 2.44, 2.4, 2.34, 2.31,
             2.28, 2.25, 2.21, 2.19, 2.15, 2.15, 2.14, 2.12, 2.09, 2.09,
             2.01, 1.98, 1.97, 1.9, 1.87, 1.84, 1.8, 1.75, 1.7, 1.63,
             0.98, 0.07]
    band2 = [3.64, 3.52, 3.43, 3.42, 3.34, 3.31, 3.3, 3.18, 3.18, 3.06,
             3.04, 3.0, 2.97, 2.92, 2.89, 2.88, 2.88, 2.85, 2.8, 2.78,
             2.73, 2.73, 2.72, 2.69, 2.6, 2.57, 2.53, 2.47, 2.44, 2.42]
    band3 = [5.38, 3.71, 3.27, 3.25, 3.02, 2.89]
    depths = band0 + band1 + band2 + band3
    bands = ([0] * len(band0) + [1] * len(band1)
             + [2] * len(band2) + [3] * len(band3))
    return np.array(depths), np.array(bands)


def test_the_two_largest_drops_are_pulled_into_a_band_of_their_own():
    """The operator's report: the large spikes were grouped with smaller
    ones. Split by fall duration alone they cannot separate - 7.30 mV sits
    in the 4-7 s band with thirty-one others and 5.38 mV in the 16-31 s
    band with five."""
    depths, bands = _id010_depths()
    labels = ["2-3 s", "4-7 s", "8-14 s", "16-31 s"]

    new_bands, new_labels = passes8.size_split(depths, bands, labels)

    large = int(new_bands.max())
    assert large == len(labels)                 # a new band, appended
    members = depths[new_bands == large]
    assert sorted(members.tolist()) == [5.38, 7.3]
    assert "mV" in new_labels[large]


def test_a_span_whose_drops_are_all_one_size_is_left_alone():
    """ID 3: seventeen motifs within a factor of two of each other. There
    is no 'largest' worth a panel, and inventing one costs a colour."""
    depths = np.array([7.1, 6.8, 7.4, 6.2, 7.9, 6.6, 7.2, 8.0, 6.9])
    bands = np.zeros(depths.size, dtype=int)

    new_bands, new_labels = passes8.size_split(depths, bands, ["86-236 s"])

    assert new_bands.tolist() == bands.tolist()
    assert new_labels == ["86-236 s"]


def test_one_lone_giant_is_not_given_a_panel_to_itself():
    """A single outlier is already drawn and de-emphasised by the outlier
    screen. A family of one shows no family."""
    depths = np.array([20.0, 2.1, 2.0, 1.9, 2.2, 2.05, 1.95])
    bands = np.zeros(depths.size, dtype=int)

    new_bands, _ = passes8.size_split(depths, bands, ["4-7 s"])

    assert new_bands.tolist() == bands.tolist()


def test_the_split_needs_a_real_gap_not_just_a_ranking():
    """Ranked, there is always a biggest two. The rule fires on distance
    from the span's median, so a smooth spread does not get carved up."""
    depths = np.linspace(2.0, 3.4, 24)
    bands = np.zeros(depths.size, dtype=int)

    new_bands, _ = passes8.size_split(depths, bands, ["4-7 s"])

    assert new_bands.tolist() == bands.tolist()


def test_the_large_band_is_reported_with_its_own_depth_range():
    depths, bands = _id010_depths()
    _, labels = passes8.size_split(depths, bands,
                                   ["2-3 s", "4-7 s", "8-14 s", "16-31 s"])
    assert "5.38" in labels[-1] or "5.4" in labels[-1]
    assert "7.3" in labels[-1]


def test_nothing_at_all_is_handled():
    new_bands, new_labels = passes8.size_split(np.array([]), np.array([]), [])
    assert new_bands.size == 0
    assert new_labels == []
