---
id: 55
title: "Filter and distance-sort the library grid"
model: sonnet
size: M
blocked_by: [54]
mutex: []
files: ["UI/workspaces/library/grid.py", "tests/test_library_grid.py"]
flags: ['human-verify']
level: 3
unblocks: 0
budget_minutes: 60
---
# 55 — Filter and distance-sort the library grid

**Model:** [S] · **Size:** [M]

**What to build:** 410 cards is too many to read. Filters narrow them, and sorting a family by
distance from its exemplar puts the cleanest and the most marginal members where
they can be seen.

Filters, all from data the import already carries: morphology, purity, spike train,
source recording and channel, and range filters on drop depth and fall duration.
Depth range is the one that isolates an amplitude regime, which is a question this
project asks repeatedly.

Sorting within a family is by the edge distance to that family's exemplar — the
distance is already persisted on the edge, so this is a read, not a computation.

Filters compose. A filter that matches nothing says so in a sentence rather than
rendering an empty grid, because an empty grid and a broken grid look identical.

**Blocked by:** 54

**Files/modules touched:** `UI/workspaces/library/grid.py`, `tests/test_library_grid.py`.

**Merge risk:** **LOW-MEDIUM.** Last in the chain of three that own the grid file, so nothing
follows you there. Read the distances off the persisted edges; do not recompute
them.

**Acceptance criteria:**
- [ ] The grid filters by morphology, purity, spike train, recording and channel.
- [ ] The grid filters by drop-depth and fall-duration range.
- [ ] Filters compose, and a filter matching nothing renders a sentence rather than an empty grid.
- [ ] Members within a family can be sorted by their persisted edge distance to the exemplar.
- [ ] A headless construction test asserts the grid still returns non-`None` panes with filters applied.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
