---
id: 36
title: "Edge computation and persistence"
model: sonnet
size: M
blocked_by: [2, 35]
mutex: [2, 41, 46]
files: ["Working/database/runs.py", "Working/library.py", "tests/test_library_edges.py"]
flags: ['done']
level: 2
unblocks: 8
budget_minutes: 60
---
# 36 — Edge computation and persistence

**Model:** [S] · **Size:** [M]

**What to build:** matching a span to an exemplar produces a stored edge that carries everything needed
to reproduce the match — so a motif family is an object, not a screenshot.

**Blocked by:** 02, 35

**Files/modules touched:** new `Working/library.py`; `Working/database/runs.py` (edge accessors);
new `tests/test_library_edges.py`.

**Merge risk:** **MEDIUM vs 41 and 46**, both of which write to `motif_edge`. This ticket defines the
edge-writer signature; the others call it and do not write raw SQL against that table.

**Acceptance criteria:**
- [ ] Matching a candidate span to an exemplar writes a `motif_member` and a `motif_edge`.
- [ ] Every edge carries distance function name, threshold, distance value and recipe hash.
- [ ] A member may reference any recording and any channel, including one the exemplar did not come from.
- [ ] Re-running the same match with the same recipe does not duplicate the edge.
- [ ] A test asserts an edge written today can be recomputed from its recorded fields to the same
      distance value.
