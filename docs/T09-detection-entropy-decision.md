# T09 — Decision: `detection.entropy` is dropped from the adapter registry

## Resolution

`detection.entropy` is removed from the chain system. The underlying functions in
`Working/Detection/analysis/entropy_analysis.py` are unchanged and remain available as plain
analysis functions.

## Why

The adapter returned a single scalar for the whole span (`AdapterResult(output_kind="encoding",
encoding=float(value))`). That value is not an `Encoding` (a per-window image or symbolic
representation), not a `Scores` (a time-aligned profile with one value per timepoint), and not a
`WindowSet` (fixed-length segments with an attached per-window feature table).

The PRD type-system rule is explicit: a method that fits none of the seven interchange types is out
of scope, rather than a reason to add an eighth. Keeping the adapter as a per-window feature column
would have changed both its input and output types to `WindowSet` and rewritten it into a different
method — per-window feature extraction — which is outside this ticket's scope and overlaps the
per-window feature work already owned by other tickets.

Dropping the adapter closes the inconsistency without introducing an eighth interchange type, and the
entropy computations themselves are not lost: they stay in `Working/` where they can be called
directly by analysis code.
