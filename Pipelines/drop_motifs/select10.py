"""
select10.py
============
Selecting motifs out of a store. One rule, and it replaces the one that
was wrong.

`window_index` is not a selector
--------------------------------
Under `passes9.detect_sliding` a drop lying in two overlapping windows is
stored ONCE, tagged with whichever window won the best-framed rule - and
that is frequently the NEIGHBOUR's index rather than the index of the
window whose time range the drop sits in. Filtering `window_index == N`
therefore silently hides drops inside window N. It undercounted every
case-study window in `example_case_studies_v2` (CH1 6 against 11, CH2 1
against 2, CH4 11 against 21) and the undercount looked like refinement
being destructive.

The question a figure or a panel is actually asking is "which motifs are
in these seconds", so that is the question this module answers. The
window index stays on the row as provenance - it says which framing the
stored measurement came from, which is worth knowing - but it is never
the thing selected on.

Everything here takes and returns plain row dicts, so it works on a store
loaded by `motifs5.load_store` and on rows still in memory.
"""

import numpy as np

from Pipelines.drop_motifs import passes9


def in_sample_range(rows, start_idx, end_idx, *, key="onset_idx"):
    """Rows whose `key` sample lies in `[start_idx, end_idx)`.

    `onset_idx` is ABSOLUTE in the recording (`span_offset` is already
    added by `motifs5.rows_and_arrays`), so no window arithmetic is needed
    and none is done here.
    """
    lo, hi = int(start_idx), int(end_idx)
    return [r for r in rows if lo <= int(r[key]) < hi]


def in_time_range(rows, start_s, end_s, fs, *, key="onset_idx"):
    """Rows whose onset lies in `[start_s, end_s)` seconds."""
    return in_sample_range(rows, round(float(start_s) * float(fs)),
                           round(float(end_s) * float(fs)), key=key)


def in_window(rows, n_samples, fs, *, window_index,
              window_s=passes9.DEFAULT_WINDOW_S,
              overlap=passes9.DEFAULT_OVERLAP, key="onset_idx"):
    """The motifs inside one sliding window's TIME RANGE.

    The bounds are recomputed from the same `passes9.window_bounds` the
    detection used, so "window 36" means the same 900-950 s here as it did
    there - but membership is decided by the range, not by the label the
    dedup happened to leave on the row.
    """
    start, end = passes9.window_bounds(
        int(n_samples), float(fs), float(window_s), float(overlap)
    )[int(window_index)]
    return in_sample_range(rows, start, end, key=key)


def overlapping_span(rows, start_idx, end_idx):
    """Rows whose onset-to-trough span intersects `[start_idx, end_idx)`.

    The stricter question `in_sample_range` does not answer: an event that
    began before the range and is still falling inside it. Used for the
    truncation accounting, not for counting events in a window - a drop
    belongs to the window its ONSET is in, so that one window's count plus
    another's is not more than the two together.
    """
    lo, hi = int(start_idx), int(end_idx)
    return [r for r in rows
            if int(r["onset_idx"]) < hi and int(r["trough_idx"]) >= lo]


def group_by(rows, field):
    """`{value: [rows]}`, insertion-ordered, for corpus/species splits."""
    out = {}
    for row in rows:
        out.setdefault(row.get(field), []).append(row)
    return out


def durations_in_samples(rows):
    """`n_samples_in_fall` as an array, the confound control's variable."""
    return np.asarray([int(r["n_samples_in_fall"]) for r in rows], dtype=int)
