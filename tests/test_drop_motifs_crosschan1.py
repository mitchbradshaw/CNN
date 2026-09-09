"""
Task 3's classifier, tested against injected lags.

WHY THIS TEST EXISTS AND WHY IT IS NOT OPTIONAL. The finding Task 3
reports is "the channel mixing in the family table is not one disturbance
recorded five times". A bug in the lag or the correlation would fake
exactly that finding, and it would fake it silently - a wrong sign on the
lag, an off-by-one in the overlap, a correlation computed against the
unshifted copy, all produce a plausible-looking scatter with a plausible
spike somewhere. So the classifier is measured against three signals whose
answer is known by construction, one per bin:

    0.0 s  ->  common_mode     one disturbance on a shared ground
    0.8 s  ->  propagation     candidate network event
    4.0 s  ->  independent     coincidence

Run: pytest tests/test_drop_motifs_crosschan1.py
"""

import numpy as np
import pytest

from Pipelines.drop_motifs import crosschan1 as cc

FS = 10.0
EVENT_S = 3.0
SNIPPET_PAD_S = 6.0
ONSET_S = 100.0


def _event(fs=FS, duration_s=EVENT_S):
    """A drop: flat, a fall, a slower recovery. Asymmetric on purpose - a
    symmetric bump would correlate with its own time reverse and hide a
    sign error in the lag."""
    n = int(round(duration_s * fs))
    t = np.linspace(0.0, 1.0, n)
    return -np.exp(-((t - 0.25) ** 2) / 0.01) - 0.4 * np.exp(
        -((t - 0.55) ** 2) / 0.08)


def _pair(lag_s, *, noise=0.02, seed=7, fs=FS):
    """Two snippets holding the same event, offset by `lag_s`, each with
    its own independent noise.

    Returned in the shape the store uses: a row carrying absolute sample
    indices and a `{field: array}` snippet whose `t_s` is absolute
    seconds, because that is the representation the classifier has to
    handle and a test on bare arrays would not exercise the alignment.
    """
    rng = np.random.default_rng(seed)
    event = _event(fs=fs)
    pad = int(round(SNIPPET_PAD_S * fs))

    rows, snippets = [], {}
    for index, (channel, offset_s) in enumerate(((0, 0.0), (1, lag_s))):
        onset_idx = int(round((ONSET_S + offset_s) * fs))
        start = onset_idx - pad
        end = onset_idx + len(event) + pad
        values = np.zeros(end - start, dtype=float)
        values[pad:pad + len(event)] = event
        values = values + rng.normal(0.0, noise, size=values.shape)
        event_id = "synth_ch%d" % channel
        rows.append({
            "event_id": event_id,
            "channel": channel,
            "fs": fs,
            "onset_idx": onset_idx,
            "trough_idx": onset_idx + len(event) // 3,
            "snippet_start_idx": start,
            "snippet_end_idx": end,
            "drop_depth_mv": 1.0,
            "fall_duration_s": 0.5,
        })
        snippets[event_id] = {
            "detrended_mv": values,
            "raw_mv": values.copy(),
            "t_s": np.arange(start, end) / fs,
        }
    return rows, snippets


@pytest.mark.parametrize("lag_s, expected", [
    (0.0, "common_mode"),
    (0.8, "propagation"),
    (4.0, "independent"),
])
def test_injected_lag_lands_in_the_right_bin(lag_s, expected):
    rows, snippets = _pair(lag_s)
    pairs = cc.cross_channel_pairs(rows, snippets)
    assert len(pairs) == 1, (
        "two events %.1f s apart on different channels are one pair "
        "inside the +-%.1f s window" % (lag_s, cc.PAIR_WINDOW_S))
    pair = pairs[0]
    assert pair["bin"] == expected, (
        "lag %.1f s -> %s (measured lag %.2f s, r %.3f)"
        % (lag_s, pair["bin"], pair["peak_lag_s"], pair["peak_r"]))


@pytest.mark.parametrize("lag_s", [0.0, 0.8, -1.3, 4.0])
def test_measured_lag_recovers_the_injected_one(lag_s):
    """The bin test would still pass if the lag were systematically wrong
    by less than a bin width. This one pins the number itself, including
    its SIGN - a reversed sign is the classic cross-correlation bug and it
    would turn "CH0 leads CH1" into the opposite claim.
    """
    rows, snippets = _pair(lag_s)
    pair = cc.cross_channel_pairs(rows, snippets)[0]
    assert pair["peak_lag_s"] == pytest.approx(lag_s, abs=1.0 / FS), (
        "injected %.2f s, measured %.2f s" % (lag_s, pair["peak_lag_s"]))


def test_zero_lag_copy_correlates_near_one():
    """The common_mode rule needs r >= 0.90 to be reachable at all. A copy
    of one waveform plus 2% noise must clear it, or the bin is empty by
    construction and its emptiness would be reported as a finding."""
    rows, snippets = _pair(0.0)
    pair = cc.cross_channel_pairs(rows, snippets)[0]
    assert pair["peak_r"] > 0.90


def test_independent_noise_does_not_reach_the_common_mode_corner():
    """The other half of the same guard: two unrelated noise snippets must
    NOT land in common_mode. Without this, a classifier that returned
    r = 1.0 for everything would pass every test above."""
    rng = np.random.default_rng(11)
    rows, snippets = [], {}
    for channel in (0, 1):
        onset_idx = int(round(ONSET_S * FS))
        start, end = onset_idx - 60, onset_idx + 60
        event_id = "noise_ch%d" % channel
        rows.append({
            "event_id": event_id, "channel": channel, "fs": FS,
            "onset_idx": onset_idx, "trough_idx": onset_idx + 5,
            "snippet_start_idx": start, "snippet_end_idx": end,
            "drop_depth_mv": 0.2, "fall_duration_s": 0.5,
        })
        snippets[event_id] = {
            "detrended_mv": rng.normal(0.0, 1.0, size=end - start),
            "raw_mv": rng.normal(0.0, 1.0, size=end - start),
            "t_s": np.arange(start, end) / FS,
        }
    pair = cc.cross_channel_pairs(rows, snippets)[0]
    assert pair["bin"] != "common_mode", (
        "independent noise reached the common-mode corner at r = %.3f"
        % pair["peak_r"])


def test_pairs_are_only_built_across_channels():
    """Two events on the SAME channel are never a cross-channel pair, however
    close in time. The co-occurrence count is the headline number of Task 3
    and same-channel pairs would inflate it."""
    rows, snippets = _pair(0.2)
    for row in rows:
        row["channel"] = 3
    assert cc.cross_channel_pairs(rows, snippets) == []


def test_events_further_apart_than_the_window_are_not_paired():
    rows, snippets = _pair(0.0)
    rows[1]["onset_idx"] += int(round((cc.PAIR_WINDOW_S + 2.0) * FS))
    rows[1]["snippet_start_idx"] += int(round((cc.PAIR_WINDOW_S + 2.0) * FS))
    rows[1]["snippet_end_idx"] += int(round((cc.PAIR_WINDOW_S + 2.0) * FS))
    snippets[rows[1]["event_id"]]["t_s"] = (
        snippets[rows[1]["event_id"]]["t_s"] + cc.PAIR_WINDOW_S + 2.0)
    assert cc.cross_channel_pairs(rows, snippets) == []


def test_thresholds_are_parameters_not_constants():
    """The sensitivity table in CROSS_CHANNEL.json is only meaningful if the
    thresholds can actually be varied. This asserts they are plumbed, not
    hard-coded at the comparison site."""
    rows, snippets = _pair(0.8)
    strict = cc.Thresholds(common_lag_s=0.2, common_r=0.90,
                           propagation_lag_s=0.5, propagation_r=0.70)
    pair = cc.cross_channel_pairs(rows, snippets, thresholds=strict)[0]
    assert pair["bin"] == "independent", (
        "0.8 s exceeds a 0.5 s propagation window and must fall out of "
        "the propagation bin")
