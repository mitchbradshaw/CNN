---
id: 1
title: "Seven interchange types with disk serialisation"
model: sonnet
size: M
blocked_by: []
mutex: []
files: ["__init__.py", "encoding.py", "grouping.py", "model.py", "scores.py", "signal.py", "spanset.py", "tests/test_types.py", "windowset.py"]
flags: []
level: 0
unblocks: 36
budget_minutes: 60
---
# 01 — Seven interchange types with disk serialisation

**Model:** [S] · **Size:** [M]

**What to build:** the seven typed values every block passes to the next, each able to round-trip to
disk so the step cache and the cluster round trip get a serialiser for free.

**Blocked by:** None — can start immediately.

**Files/modules touched:** new `Working/types/` package (`signal.py`, `spanset.py`, `windowset.py`,
`encoding.py`, `grouping.py`, `model.py`, `scores.py`, `__init__.py`); new `tests/test_types.py`.

**Merge risk:** none — greenfield package, no existing file edited. It is the root of the dependency
tree, so land it before 5, 11, 12 and 35 start.

**Acceptance criteria:**
- [ ] `Signal`, `SpanSet`, `WindowSet`, `Encoding`, `Grouping`, `Model`, `Scores` each exist as a frozen
      dataclass with a `to_path()` / `from_path()` pair.
- [ ] Arrays serialise to compressed `.npz`, feature tables to `.parquet`, span sets to `.json`, models
      by path reference only.
- [ ] Each of the seven round-trips through disk and compares equal to the original, including a
      `WindowSet` carrying an attached per-window feature table.
- [ ] `Scores` exposes one value per timepoint and asserts its length matches the signal it was
      derived from; `WindowSet` exposes one row per window and carries no timepoint alignment.
- [ ] No module in `Working/types/` imports Panel, HoloViews, Bokeh or matplotlib.
