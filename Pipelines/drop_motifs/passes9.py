"""
passes9.py
===========
drop_motifs9. The detector is run over a SLIDING WINDOW instead of once
over the whole channel, and only drops are kept.

Why a sliding window
--------------------
Every pass in `passes6`/`passes7` derives its scale from the signal it is
handed - an autocorrelation over the whole input. Handed a 20-minute
channel, that produces ONE scale for the whole channel, and a spike train
that occupies 50-100 s of it competes for that scale with 1100 s of
everything else. Handed 50 s at a time, the derived scale is the scale of
whatever is in those 50 s, so a train that is locally dominant is detected
on its own terms.

This is the same idea as the `fine` pass - look at a scale the whole-span
autocorrelation talks you out of - but applied to WHERE rather than to how
wide.

What is kept
------------
Drops only. `inverted=False`, so the rise pass never runs. drop_motifs8
established that the inverted pass on this kind of data is mostly recovery
edges of drops already recorded (rule 3 of `passes8.deduplicate`); until
there is a reason to trust an isolated rise, this run does not collect
them. `sensitive`, `fine` and `micro` are all drop passes and all still
run - "drops only" is about DIRECTION, not about dropping the multi-scale
stack.

Not saving the same drop twice
------------------------------
With 50% overlap every event that is not within half a window of a channel
edge is inside TWO windows, so the naive union double-counts almost
everything. Two things fix it.

  THE SAME EVENT IS ONE EVENT. Two detections whose absolute onsets sit
  within `DEDUP_ONSET_FRAC` of the longer one's fall are the same drop,
  which is `passes6`'s own rule applied across windows rather than across
  passes. Note that the onset used is ABSOLUTE - `span_offset` is the
  window's start - so the comparison is in channel coordinates and not in
  each window's own.

  THE BEST-FRAMED DETECTION WINS. Which of the two duplicates to keep is
  not arbitrary. An event near a window's edge is measured against a
  detrend baseline computed mostly from one side of it, and if it is very
  near, its snippet is truncated by the window bound. So candidates are
  ranked by how CENTRED they are in the window that found them, and the
  most centred survives. This is the one place this module makes a
  judgement the earlier passes did not, and it is why the store's
  `window_centre_frac` column exists: it is the tie-break, recorded so it
  can be second-guessed.

The edge that cannot be fixed
-----------------------------
An event whose fall is longer than the window cannot be seen whole by any
window and will be detected as a truncated fragment or not at all. At 50 s
and 10 Hz that is a 500-sample ceiling on what a single window can frame;
the longest fall in the drop_motifs8 Fig2A run was 158 samples, so nothing
in that population is near it. `window_truncated` flags any event whose
snippet touches its window's bound, so the count is visible rather than
assumed to be zero.
"""

import numpy as np

from Pipelines.drop_motifs import passes7
from Pipelines.drop_motifs.passes6 import DEDUP_ONSET_FRAC, scale_bands
from Pipelines.drop_motifs.passes7 import PASS_ORDER
from Pipelines.drop_motifs.passes8 import size_split

# The window, and how far it moves. 50 s is the operator's figure, chosen
# off spike trains seen at the 50-100 s scale in the drop_motifs8 Fig2A
# overlays. A hop of half a window is the usual compromise: every interior
# sample is in exactly two windows, so an event framed badly by one has
# one other chance, without paying for a third.
DEFAULT_WINDOW_S = 50.0
DEFAULT_OVERLAP = 0.5

# A window with fewer than this many samples is not worth running: the
# autocorrelation the base pass derives its scale from needs a few cycles
# of something, and the detrend needs a baseline.
#
# LOWERED FROM 64 TO 32 IN drop_motifs10, and the reason is the rate
# control rather than anything about Fig2A at 10 Hz. `reishi_1hz` is the
# same five channels decimated, run through this same chain with the
# window length in SECONDS held fixed - which is the entire point of the
# control - so its windows are 50 samples where the 10 Hz ones are 500.
# At 64 every one of them was rejected and the control could not be run
# at all.
#
# This is a guard on whether a window is ATTEMPTED, not a threshold the
# detector uses to decide what a drop is, so lowering it retunes nothing:
# the catalogue corpora use span framing and have no windows, and Fig2A at
# 10 Hz is an order of magnitude above either value. It binds on exactly
# one corpus and it is stated here rather than passed in as a per-corpus
# parameter, because a per-corpus parameter is the thing this run is not
# allowed to have.
MIN_WINDOW_SAMPLES = 32


def window_bounds(n_samples, fs, window_s=DEFAULT_WINDOW_S,
                  overlap=DEFAULT_OVERLAP):
    """`[(start, end), ...]` covering `n_samples`, in samples.

    The last window is pulled back to end exactly at `n_samples` rather
    than being allowed to run short, so the tail of the channel is framed
    as well as the middle is. That makes its overlap with its predecessor
    larger than `overlap`, which the dedup handles like any other.
    """
    n_samples = int(n_samples)
    width = int(round(float(window_s) * float(fs)))
    if width <= 0:
        raise ValueError(f"window_s={window_s} at fs={fs} is zero samples")
    width = min(width, n_samples)
    if not 0.0 <= float(overlap) < 1.0:
        raise ValueError(f"overlap must be in [0, 1), got {overlap}")

    hop = max(1, int(round(width * (1.0 - float(overlap)))))
    starts = list(range(0, max(1, n_samples - width + 1), hop))
    # Pull a final window back to the channel's end, but only if it moves
    # far enough to frame anything new. Without the second test a channel
    # whose length misses a whole hop by one sample gets a window one
    # sample along from its neighbour: 500 samples re-detected to reach 1.
    tail = n_samples - width
    if tail > starts[-1] + hop // 4:
        starts.append(tail)

    bounds = []
    for start in starts:
        end = min(start + width, n_samples)
        if end - start >= min(MIN_WINDOW_SAMPLES, n_samples):
            bounds.append((int(start), int(end)))
    return bounds


def _centre_fraction(onset, start, end):
    """0 at a window's edge, 1 at its centre.

    The framing quality of one detection in one window, and the tie-break
    when two windows both found the same event.
    """
    width = float(end - start)
    if width <= 0:
        return 0.0
    position = (float(onset) - float(start)) / width      # 0..1 across
    return float(max(0.0, 1.0 - abs(position - 0.5) * 2.0))


def deduplicate_across_windows(rows, fs, *, onset_frac=DEDUP_ONSET_FRAC):
    """One row per real drop, keeping the best-framed detection of each.

    `rows` carry ABSOLUTE `onset_idx` and the `window_centre_frac` this
    module put on them. Returns `(kept_rows_in_time_order, n_dropped)`.

    Ranking is by framing first and pass priority second, so a base-pass
    detection at a window edge loses to a base-pass detection of the same
    event in the middle of the next window - which is the entire point -
    but a `micro` detection never displaces a `base` one at equal framing.
    """
    order = {key: i for i, key in enumerate(PASS_ORDER)}
    ranked = sorted(
        rows,
        key=lambda r: (-float(r.get("window_centre_frac", 0.0)),
                       order.get(r.get("pass_key"), 99),
                       int(r["onset_idx"])))

    kept = []
    for row in ranked:
        onset = float(row["onset_idx"])
        fall = float(row.get("fall_duration_s", 0.0))
        duplicate = False
        for other in kept:
            tolerance = onset_frac * max(
                fall, float(other.get("fall_duration_s", 0.0))) * float(fs)
            # A zero-length fall would make the tolerance zero and let two
            # detections of one flat event both through; one sample is the
            # floor.
            tolerance = max(tolerance, 1.0)
            if abs(onset - float(other["onset_idx"])) <= tolerance:
                duplicate = True
                break
        if not duplicate:
            kept.append(row)

    kept.sort(key=lambda r: int(r["onset_idx"]))
    return kept, len(rows) - len(kept)


def remeasure_merged_depth(kept, all_rows, arrays, fs, *,
                           onset_frac=DEDUP_ONSET_FRAC):
    """Re-measure depth on the MERGED event, once the winner is chosen.

    drop_motifs10 defect 5. `deduplicate_across_windows` ranks candidates
    by `window_centre_frac`, which optimises FRAMING and says nothing
    about depth fidelity. The winner is the copy nearest its window's
    centre, and its trough is wherever that window's detrend and knee rule
    put it - which on the drop_motifs9 store was measurably early: CH2's
    second drop measured 0.125 mV in the winning window's framing against
    0.387 mV when window 33's own detection was refined directly.

    THE FRAMING RULE IS KEPT and the depth is re-measured, rather than the
    ranking being changed to include depth. Ranking on depth would make
    the dedup prefer whichever window measured DEEPEST, which is a
    maximum over noisy estimates and therefore biased upward by
    construction; re-measuring changes one number on an event whose
    identity, snippet and framing are already decided, and cannot change
    which events exist. It is the smaller change and the safer one.

    The merged event's extent is the union of its group's `[onset,
    trough]` marks - every window that saw this drop contributes its
    opinion about where the fall starts and ends. The measurement is then
    taken on the WINNER's own detrended snippet over that union, clipped
    to what the winner actually stored, so no sample is invented and the
    depth still comes from one window's baseline rather than from a mix.

    Both numbers are kept: `drop_depth_mv` is the re-measured one and
    `depth_winner_framing_mv` is what the winner's own framing said, so
    the effect on the depth distribution is auditable per event rather
    than only in aggregate.
    """
    groups = _duplicate_groups(kept, all_rows, fs, onset_frac=onset_frac)
    out, n_changed, deltas = [], 0, []

    for row in kept:
        row = dict(row)
        row["depth_winner_framing_mv"] = float(row["drop_depth_mv"])
        row["n_merged_copies"] = len(groups.get(row["event_id"], [row]))
        # Always present, so the store's rows stay homogeneous.
        row["remeasured_onset_idx"] = int(row["onset_idx"])
        row["remeasured_trough_idx"] = int(row["trough_idx"])

        values = arrays.get(f"{row['event_id']}__detrended_mv")
        members = groups.get(row["event_id"], [row])
        if values is not None and len(members) > 1:
            values = np.asarray(values, dtype=float)
            start = int(row["snippet_start_idx"])
            lo = min(int(m["onset_idx"]) for m in members) - start
            hi = max(int(m["trough_idx"]) for m in members) - start
            lo = int(np.clip(lo, 0, max(0, values.size - 1)))
            hi = int(np.clip(hi + 1, lo + 1, values.size))
            segment = values[lo:hi]
            if segment.size >= 2:
                peak = lo + int(np.argmax(segment))
                foot = peak + int(np.argmin(values[peak:hi]))
                depth = float(values[peak] - values[foot])
                if depth > 0:
                    row["drop_depth_mv"] = depth
                    row["remeasured_onset_idx"] = int(peak + start)
                    row["remeasured_trough_idx"] = int(foot + start)

        delta = row["drop_depth_mv"] - row["depth_winner_framing_mv"]
        if abs(delta) > 1e-9:
            n_changed += 1
            deltas.append(delta)
        out.append(row)

    info = {
        "n_remeasured": int(n_changed),
        "n_rows": len(out),
        "median_abs_delta_mv": (float(np.median(np.abs(deltas)))
                                if deltas else 0.0),
        "max_abs_delta_mv": (float(np.max(np.abs(deltas)))
                             if deltas else 0.0),
        "rule": "framing rule kept; depth re-measured on the merged event",
    }
    return out, info


def _duplicate_groups(kept, all_rows, fs, *, onset_frac=DEDUP_ONSET_FRAC):
    """`{winner_event_id: [every row that merged into it]}`.

    Re-derived with the same tolerance the dedup used, so the grouping
    cannot disagree with the decision it is explaining.
    """
    groups = {r["event_id"]: [r] for r in kept}
    kept_ids = set(groups)
    for row in all_rows:
        if row["event_id"] in kept_ids:
            continue
        onset = float(row["onset_idx"])
        fall = float(row.get("fall_duration_s", 0.0))
        best, best_gap = None, None
        for winner in kept:
            tolerance = max(onset_frac * max(
                fall, float(winner.get("fall_duration_s", 0.0))) * float(fs), 1.0)
            gap = abs(onset - float(winner["onset_idx"]))
            if gap <= tolerance and (best_gap is None or gap < best_gap):
                best, best_gap = winner, gap
        if best is not None:
            groups[best["event_id"]].append(row)
    return groups


def detect_sliding(x, fs, *, catalogue_id, recording_id, source_file,
                   channel, window_s=DEFAULT_WINDOW_S,
                   overlap=DEFAULT_OVERLAP, span_label=None, span_key=None,
                   max_passes=3, fine=True, sensitive=True, micro=True,
                   progress=None, remeasure_depth=True, base_offset=0,
                   **pass_kwargs):
    """Run the drop passes over a sliding window and merge the survivors.

    Returns `(rows, arrays, info)` in the same shape every earlier
    `detect_*` returns, so the store writer and the figure set need no
    special case for this run.

    `base_offset` is where `x` STARTS IN ITS CHANNEL, and it exists because
    drop_motifs12a detects over a REGION rather than a whole channel.

    Every index this function puts on a row is offset by the window's start
    within `x`. On Fig2A `x` is the whole channel, so that offset is already
    absolute and the distinction has never had to be made. A Lion's mane
    region begins 13.76 million samples into its channel; without
    `base_offset` every `onset_idx` in the store would be short by exactly
    that, and the store would be internally consistent, well-formed, and
    pointing at the wrong part of the recording.

    It is added to the window start rather than to the finished rows, so
    the event ids - which embed the onset - and `window_centre_frac`, which
    compares an onset against its window's bounds, are computed once in one
    frame. Adding it afterwards would leave the ids naming the old indices.

    Defaults to 0, so every existing caller is unchanged.
    """
    base_offset = int(base_offset)
    x = np.asarray(x, dtype=float).ravel()
    fs = float(fs)
    bounds = window_bounds(len(x), fs, window_s, overlap)

    all_rows, all_arrays = [], {}
    per_window, n_failed = [], 0

    for index, (start, end) in enumerate(bounds):
        segment = x[start:end]
        try:
            rows, arrays, info = passes7.detect_multiscale(
                segment, fs,
                catalogue_id=catalogue_id, recording_id=recording_id,
                source_file=source_file, channel=channel,
                span_offset=start + base_offset,
                span_label=span_label, span_key=span_key,
                max_passes=max_passes, fine=fine, sensitive=sensitive,
                micro=micro,
                inverted=False,          # drops only - see the docstring
                # The window is part of the key. Two overlapping windows
                # detrend the same drop against different baselines and
                # frame it with different bounds, so their snippets are
                # two different arrays; without this they are one key and
                # `all_arrays.update` below silently keeps whichever came
                # last. See `passes6.motif_key`.
                window_index=index,
                **pass_kwargs)
        except Exception as exc:                      # noqa: BLE001
            # One unusable window must not lose the other forty-five. The
            # count is reported, not swallowed.
            n_failed += 1
            per_window.append({"start": int(start + base_offset),
                               "end": int(end + base_offset),
                               "n": 0, "error": repr(exc)})
            continue

        # The window's own bounds, in the same frame the rows are now in.
        lo, hi = start + base_offset, end + base_offset
        for row in rows:
            row["window_start_idx"] = int(lo)
            row["window_end_idx"] = int(hi)
            row["window_index"] = int(index)
            row["window_centre_frac"] = _centre_fraction(
                int(row["onset_idx"]), lo, hi)
            row["window_truncated"] = int(
                int(row["snippet_start_idx"]) <= lo
                or int(row["snippet_end_idx"]) >= hi)

        all_rows.extend(rows)
        all_arrays.update(arrays)
        # Absolute, like the rows: a per-window diagnostic in a different
        # frame from the store it explains is worse than no diagnostic.
        per_window.append({"start": int(lo), "end": int(hi),
                           "n": len(rows)})
        if progress:
            progress(index + 1, len(bounds))

    n_raw = len(all_rows)
    kept, n_dropped = deduplicate_across_windows(all_rows, fs)

    # Arrays are keyed `{event_id}__{field}`; keep only the survivors'.
    keep_ids = {r["event_id"] for r in kept}
    arrays = {key: value for key, value in all_arrays.items()
              if key.split("__")[0] in keep_ids}

    # The framing rule chose the row; it did not measure the depth. See
    # `remeasure_merged_depth` - drop_motifs10 defect 5.
    if remeasure_depth:
        kept, remeasure_info = remeasure_merged_depth(
            kept, all_rows, arrays, fs)
    else:
        remeasure_info = {"n_remeasured": 0, "n_rows": len(kept),
                          "rule": "off (re-baseline isolation only)"}

    bands, labels = scale_bands([r["fall_duration_s"] for r in kept])
    bands, labels = size_split(
        [abs(float(r["drop_depth_mv"])) for r in kept], bands, labels)
    for row, band in zip(kept, bands):
        row["scale_band"] = int(band)

    info = {
        "window_s": float(window_s),
        "window_samples": int(round(float(window_s) * fs)),
        "overlap": float(overlap),
        "n_windows": len(bounds),
        "n_windows_failed": int(n_failed),
        "n_before_dedup": int(n_raw),
        "n_duplicates_dropped": int(n_dropped),
        "n_after_dedup": len(kept),
        "n_truncated": int(sum(int(r.get("window_truncated", 0))
                               for r in kept)),
        "per_window": per_window,
        "scale_band_labels": labels,
        "n_scale_bands": len(labels),
        "per_pass_kept": {key: sum(1 for r in kept if r["pass_key"] == key)
                          for key in PASS_ORDER},
        "directions": "drops only (inverted pass not run)",
        "depth_remeasure": remeasure_info,
    }
    return kept, arrays, info
