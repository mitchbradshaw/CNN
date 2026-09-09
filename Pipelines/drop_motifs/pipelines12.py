"""
pipelines12.py
===============
Task 3. The `*_01_pipeline.png` figure - raw trace to detected events, every
stage - for each oyster span and for a seeded selection of Reishi and Lion's
mane sequences. These exist so the operator can confirm by eye that the
detector is doing what it claims.

Nothing is drawn here. `casestudy9.plot_pipeline` draws; this module decides
WHICH windows get drawn and hands them the right rows.

Selection is by rule and by seed
--------------------------------
The oyster set needs no selection: the work order states that the fifteen
catalogue IDs already in `drop_motifs10/motifs/` are the complete oyster set.

The Reishi and Lion's mane sets are three sequences each, drawn from the
qualifying runs `sequences11` writes, under seed `SEED`. Two rules on top of
the draw, and both exist so the figure set is reproducible AND joined up:

  PREFER WHAT IS ALREADY DRAWN. A sequence that appears in drop_motifs11's
  S3_1 or S3_2 figures is taken first, so the pipeline plot and the morph
  figure show the same events and a reader can put them side by side.
  `PREFERRED` is the list read off those figures' own JSON.

  THEN DRAW AT RANDOM, without replacement, from the rest.

The chosen keys go in the manifest, so the same six come back on a re-run
even if `sequences.csv` is regenerated.

Selection is by SAMPLE RANGE, never by `window_index`
------------------------------------------------------
`select10`'s rule, and the reason is in its docstring: a drop lying in two
overlapping windows is stored once under whichever window won the
best-framed rule, which is frequently the neighbour's index. Filtering on
the index undercounted every case-study window in an earlier run - CH4 11
against 21. Every selection below goes through `select10.in_sample_range`.

The frame the rows are in
-------------------------
`casestudy9.plot_pipeline` shades `store_rows` against the replay's own time
axis, so the two must share a coordinate frame. Store rows carry ABSOLUTE
sample indices (`motifs5.rows_and_arrays` has already added `span_offset`),
so every replay here is set up with the window's ABSOLUTE bounds against the
whole channel rather than from zero against a copied span. That is the one
thing that has to be got right and it is why `replay_for` exists rather than
each caller assembling its own call.
"""

import csv
import os

import numpy as np

from Pipelines.drop_motifs import casestudy9, select10

SEED = 20260904

# Read off `Plots/drop_motifs11/S3_1_*.json` and `S3_2_morph_across_scales
# .json`. Preferring these is what makes the two figure sets show the same
# events; see the module docstring.
PREFERRED = (
    "reishi_id901_ch1_461s",       # S3_1
    "reishi_id903_ch3_606s",       # S3_1 and S3_2
    "oyster_id10_ch3_1362824s",    # S3_1 and S3_2
    "sp385_id385_ch0_6140s",       # S3_2 - retired by this run, kept for the
                                   #        record of what was preferred
)

# How much context either side of a sequence the pipeline window carries, as
# a fraction of the sequence's own duration. A sequence drawn exactly onset
# to onset starts and ends on an event, and the detrend baseline at a window
# edge is computed from one side only - the very effect `passes9`'s
# best-framed rule exists to avoid. A quarter either side puts the first and
# last event of the run well inside the window.
CONTEXT_FRACTION = 0.25

# A sequence shorter than this many seconds is padded out to it, so a dense
# Reishi run of five events 2 s apart still gets a window the base pass can
# derive a scale from.
MIN_WINDOW_S = 60.0


def read_sequences(path):
    """`sequences.csv` as a list of dicts, numbers coerced."""
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("start_onset_s", "end_onset_s", "duration_s",
                    "median_fall_s", "median_depth_mv", "cv_interval"):
            row[key] = float(row[key]) if row.get(key) not in (None, "") else float("nan")
        for key in ("n", "catalogue_id"):
            row[key] = int(float(row[key]))
    return rows


def choose_sequences(sequences, species, n=3, seed=SEED,
                     preferred=PREFERRED):
    """`n` sequences for one species: preferred first, then a seeded draw.

    The draw is `numpy.random.default_rng(seed).permutation` over the
    remaining keys SORTED, so it does not depend on the order
    `sequences.csv` happens to be in - which changes whenever the store is
    rebuilt, and would otherwise make "seeded" mean nothing.
    """
    own = [s for s in sequences if s.get("species") == species]
    by_key = {s["sequence_key"]: s for s in own}

    chosen = [by_key[key] for key in preferred if key in by_key][:n]
    remaining = sorted(key for key in by_key if key not in
                       {s["sequence_key"] for s in chosen})
    rng = np.random.default_rng(seed)
    for key in rng.permutation(np.array(remaining, dtype=object)):
        if len(chosen) >= n:
            break
        chosen.append(by_key[str(key)])
    return chosen[:n]


# How much longer than the DETECTION window a pipeline figure's replay
# window may be. See `window_for`.
MAX_WINDOW_MULTIPLE = 4.0


def densest_placement(onsets_s, width_s):
    """Where to put a window of `width_s` to hold the most of `onsets_s`.

    Used only when the cap below binds. Centring a capped window on the
    sequence's MIDPOINT is arbitrary and, on a sparse corpus, expensive:
    Lion's mane region B averages one event per 400 s, so a 480 s window
    dropped on the midpoint of a multi-hour run holds one event, and a
    pipeline figure with one event in it cannot show anyone that the
    detector is doing what it claims.

    Every candidate placement starts at some onset (a window that starts
    between two events can always be slid forward to the next one without
    losing any), so this is a sweep over `onsets_s`, not a search.
    """
    onsets = np.sort(np.asarray(onsets_s, dtype=float))
    if onsets.size == 0 or width_s <= 0:
        return None
    best_start, best_n = float(onsets[0]), 0
    for start in onsets:
        n = int(np.count_nonzero((onsets >= start)
                                 & (onsets <= start + width_s)))
        if n > best_n:
            best_start, best_n = float(start), n
    # A small margin so the first and last event are not on the frame edge.
    return best_start - 0.05 * width_s


def window_for(sequence, fs, *, context=CONTEXT_FRACTION,
               min_window_s=MIN_WINDOW_S, n_samples=None,
               max_window_s=None, onsets_s=None):
    """`(start_idx, stop_idx)` - the pipeline window one sequence gets.

    The sequence's own extent plus `context` either side, widened to
    `min_window_s`, capped at `max_window_s`, clipped to the channel.

    THE CAP IS NOT COSMETIC. `casestudy9.replay_window` re-derives the
    detector's parameters from whatever window it is handed, so a replay
    window much longer than the one the DETECTION used is not illustrating
    the detection - it is illustrating a different parameterisation that
    never ran. On a 3000-second Lion's mane sequence it does not even get
    that far: the base pass derives a 0.2 s segment, which at 10 Hz is two
    samples, and dSAX raises `dim_ratio=0.5 yields 1 sample(s) per segment`.

    So the cap is `MAX_WINDOW_MULTIPLE` times the corpus's own detection
    window - a measured quantity, not a per-corpus constant - and where a
    sequence is longer than that the window is centred on it and the figure
    says what fraction of the run it shows.
    """
    start_s = float(sequence["start_onset_s"])
    end_s = float(sequence["end_onset_s"])
    duration = max(end_s - start_s, 0.0)
    pad = max(context * duration, (min_window_s - duration) / 2.0, 0.0)
    lo_s, hi_s = start_s - pad, end_s + pad

    if max_window_s and (hi_s - lo_s) > float(max_window_s):
        width = float(max_window_s)
        placed = densest_placement(onsets_s, width) if onsets_s is not None \
            else None
        if placed is None:
            placed = 0.5 * (start_s + end_s) - 0.5 * width
        lo_s, hi_s = placed, placed + width

    lo = max(0, int(round(lo_s * fs)))
    hi = int(round(hi_s * fs))
    if n_samples is not None:
        hi = min(int(n_samples), hi)
    return lo, hi


def rows_in(rows, start_idx, stop_idx, **match):
    """Store rows in a sample range, filtered on whatever `match` names.

    By RANGE. See the module docstring - `window_index` is never a selector.
    """
    subset = [r for r in rows
              if all(str(r.get(field)) == str(value)
                     for field, value in match.items())]
    return sorted(select10.in_sample_range(subset, start_idx, stop_idx),
                  key=lambda r: int(r["onset_idx"]))


def replay_for(x_channel, fs, start_idx, stop_idx, *, catalogue_id,
               recording_id, source_file, channel, span_key, span_label,
               max_passes=3):
    """`casestudy9.replay_window` over ABSOLUTE bounds of the whole channel.

    Absolute, so the rows the replay produces and the rows the store holds
    are in one frame and `store_rows` shades where it should. Replaying a
    copied span from zero puts the two a span-offset apart, which draws
    every event in the wrong place or - worse, because it looks fine - in
    no place at all.
    """
    return casestudy9.replay_window(
        x_channel, fs, int(start_idx), int(stop_idx),
        catalogue_id=catalogue_id, recording_id=recording_id,
        source_file=source_file, channel=channel, span_key=span_key,
        span_label=span_label, max_passes=max_passes)


def draw(replay, x_channel, out_path, *, title, store_rows, family_of=None):
    """One `_01_pipeline.png`, shading the store's own events."""
    return casestudy9.plot_pipeline(
        replay, x_channel, out_path, title=title, family_of=family_of,
        store_rows=list(store_rows))


def sequence_stem(sequence):
    return str(sequence["sequence_key"])


def manifest_entry(sequence, start_idx, stop_idx, fs, rows):
    """Everything about one pipeline plot's selection, for the manifest."""
    return {
        "sequence_key": sequence["sequence_key"],
        "species": sequence.get("species"),
        "catalogue_id": sequence.get("catalogue_id"),
        "channel": sequence.get("channel"),
        "n_events_in_sequence": sequence.get("n"),
        "start_onset_s": sequence.get("start_onset_s"),
        "end_onset_s": sequence.get("end_onset_s"),
        "window_start_idx": int(start_idx),
        "window_stop_idx": int(stop_idx),
        "window_s": (int(stop_idx) - int(start_idx)) / float(fs),
        "fs": float(fs),
        "n_store_rows_in_window": len(rows),
        "preferred": sequence["sequence_key"] in PREFERRED,
        "selected_by": "sample range (never window_index)",
    }
