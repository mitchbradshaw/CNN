"""
detection_threshold.py
========================
Generic `Scores` -> `SpanSet` block: thresholds a time-aligned `Scores`
(e.g. `detection.matrix_profile`'s output) into the spans where it exceeds
a cutoff. `Working.execution.execute_recipe` writes an `output_kind='spanset'`
result to `detections` directly, so any adapter that declares a `Scores`
output can chain into this one block rather than each detector inventing
its own interval-extraction step (CODING_STANDARDS 3.2's Scores/WindowSet
split is what makes this one generic block possible instead of one per
detector).

Not part of T08's declared file list -- no existing adapter or ticket owns
a generic threshold block (checked `docs/tickets/README.md`'s single-owner
rules), and the ticket's acceptance criteria explicitly require one exists
and is chained end to end from `matrix_profile`. Flagged here for the
reviewer per CLAUDE.md's out-of-scope-file rule.
"""

import numpy as np

from Adapters.base import AdapterResult, AdapterSpec, ParamSpec
from Adapters.registry import register
from Working.types import SpanSet


def _spans_from_mask(mask):
    """Contiguous runs of True in `mask` as (starts, ends) index arrays,
    half-open [start, end) -- SpanSet's convention, so no +/-1 adjustment
    is needed at either edge."""
    padded = np.concatenate(([False], mask, [False]))
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)
    return starts, ends


def _run(x, t, fs, threshold=0.0, value=None):
    if value is None:
        raise ValueError(
            "detection.threshold requires a Scores input from a prior step "
            "(input_kind='scores')."
        )

    scores = value.values
    mask = scores > threshold  # NaN > threshold is False -- a NaN-padded tail is excluded
    starts, ends = _spans_from_mask(mask)
    span_scores = tuple(float(np.max(scores[s:e])) for s, e in zip(starts, ends))

    return AdapterResult(
        output_kind="spanset",
        value=SpanSet(
            starts=tuple(int(s) for s in starts),
            ends=tuple(int(e) for e in ends),
            scores=span_scores,
        ),
    )


SPEC = register(AdapterSpec(
    name="detection.threshold",
    display_name="Threshold (Scores -> SpanSet)",
    stage="detection",
    params=[
        ParamSpec("threshold", float, 0.0,
                  "Spans are the contiguous runs where the score exceeds this value"),
    ],
    run=_run,
    input_kind="scores",
    output_kind="spanset",
    plot=None,
    description=(
        "Generic block: thresholds any Scores (e.g. a matrix profile) into "
        "spans above a cutoff, written to `detections`. Any adapter that "
        "outputs Scores can chain into this one."
    ),
))
