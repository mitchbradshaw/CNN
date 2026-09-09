"""round2: the store defect that put 22 all-zero vectors into the shipped tree.

Two seams, both found by recomputation on `Plots/drop_motifs9_fig2a/motifs`:
208 of 1736 raw rows carry a `detrended_mv` whose length disagrees with
`snippet_end_idx - snippet_start_idx`, and `clusterfigs7._waveform_of`
answers that disagreement with a one-sample "fall" instead of an error.

The cause is a KEY COLLISION, not a truncation. `passes6.motif_key` builds
an event id out of (catalogue, recording, pass, absolute onset) and nothing
else, so the same drop found by the same pass in two overlapping sliding
windows gets ONE id. `passes9.detect_sliding` then does
`all_arrays.update(arrays)`, which keeps the LAST window's snippet, while
`deduplicate_across_windows` keeps the BEST-CENTRED row - usually the other
window's. The surviving row's bounds and the surviving array come from
different windows, and nothing downstream notices.
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import clusterfigs7, passes9


def _ramp_channel(n=3000, fs=10.0):
    """A channel with periodic drops, so overlapping windows re-find them."""
    rng = np.random.default_rng(20260903)
    x = rng.normal(0.0, 0.02, n)
    for onset in range(120, n - 120, 137):
        x[onset:onset + 8] -= np.linspace(0.0, 1.2, 8)
        x[onset + 8:onset + 30] += np.linspace(-1.2, 0.0, 22)
    return np.cumsum(np.zeros(n)) + x


# ---------------------------------------------------------------------------
# 1. the store must not disagree with itself
# ---------------------------------------------------------------------------

def test_every_stored_snippet_is_as_long_as_its_row_says_it_is():
    """The invariant the whole pipeline indexes by: an event's array runs
    from `snippet_start_idx` to `snippet_end_idx`. `_waveform_of`,
    `_aligned` and `refine9.refine_row` all subtract `snippet_start_idx`
    from an absolute index and use the result to index the array, so a
    length disagreement is not cosmetic - it reads the wrong samples."""
    x = _ramp_channel()
    rows, arrays, _ = passes9.detect_sliding(
        x, 10.0, catalogue_id=900, recording_id=1,
        source_file="synthetic", channel=0, window_s=50.0, overlap=0.5)

    assert rows, "the fixture must produce detections for this to test anything"
    mismatched = [
        r["event_id"] for r in rows
        if len(arrays[f"{r['event_id']}__detrended_mv"])
        != int(r["snippet_end_idx"]) - int(r["snippet_start_idx"])
    ]
    assert mismatched == []


def test_two_windows_that_find_one_drop_do_not_share_an_event_id():
    """The collision itself, isolated from whether it happens to bite.
    With 50% overlap every interior event is inside two windows; if the id
    carries no window, one of the two snippets is silently overwritten."""
    x = _ramp_channel()
    fs = 10.0
    bounds = passes9.window_bounds(len(x), fs, 50.0, 0.5)
    assert len(bounds) > 2

    from Pipelines.drop_motifs import passes7
    seen = {}
    for index, (start, end) in enumerate(bounds):
        rows, arrays, _ = passes7.detect_multiscale(
            x[start:end], fs, catalogue_id=900, recording_id=1,
            source_file="synthetic", channel=0, span_offset=start,
            max_passes=3, fine=True, sensitive=True, micro=True,
            inverted=False, window_index=index)
        for row in rows:
            seen.setdefault(row["event_id"], []).append(index)

    collided = {k: v for k, v in seen.items() if len(v) > 1}
    assert collided == {}


# ---------------------------------------------------------------------------
# 2. a length disagreement must be an error, not a one-sample fall
# ---------------------------------------------------------------------------

def test_waveform_of_raises_when_the_array_is_not_the_length_the_row_claims():
    """A silent one-sample "fall" z-normalises to an all-zero feature
    vector, and 22 of those sat on top of each other at distance zero in
    the shipped tree. The store is allowed to be wrong; it is not allowed
    to be wrong quietly."""
    row = {"event_id": "e0", "snippet_start_idx": 100, "snippet_end_idx": 140,
           "onset_idx": 118, "trough_idx": 126, "fs": 10.0, "signal_sign": 1}
    snippets = {"e0": {"detrended_mv": np.linspace(0.0, -1.0, 12)}}

    with pytest.raises(ValueError, match="snippet"):
        clusterfigs7._waveform_of(row, snippets)


def test_waveform_of_still_returns_the_fall_when_the_lengths_agree():
    row = {"event_id": "e0", "snippet_start_idx": 100, "snippet_end_idx": 140,
           "onset_idx": 118, "trough_idx": 126, "fs": 10.0, "signal_sign": 1}
    snippets = {"e0": {"detrended_mv": np.linspace(0.0, -1.0, 40)}}

    wave = clusterfigs7._waveform_of(row, snippets)

    assert wave.size == 8
