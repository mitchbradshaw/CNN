---
id: 40
title: "Search at other scales"
model: sonnet
size: M
blocked_by: [35, 36, 39]
mutex: []
files: ["UI/workspaces/library/detail.py", "Working/library.py", "tests/test_library_edges.py"]
flags: []
level: 5
unblocks: 0
budget_minutes: 60
---
# 40 — Search at other scales

**Model:** [S] · **Size:** [M]

**What to build:** search for instances of a motif at durations it was never defined at — turning
scale-invariance from an assumption into a query.

**Blocked by:** 35, 36, 39

**Files/modules touched:** `Working/library.py`; `UI/workspaces/library/detail.py` (the action);
`tests/test_library_edges.py`.

**Merge risk:** **LOW.**

**Acceptance criteria:**
- [ ] An action searches for members of an exemplar across a configurable range of durations.
- [ ] Results are written as members and edges recording the distance function used.
- [ ] The same search runs under the scale-invariant distance and under the native-length control, and
      their recall is comparable side by side.
- [ ] A test with a synthetic motif planted at three durations recovers all three under the
      scale-invariant distance and fewer under the control.
