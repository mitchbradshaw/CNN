---
id: 53
title: "Library thumbnails in millivolts with a shared family y-scale"
model: sonnet
size: S
blocked_by: [50]
mutex: []
files: ["UI/workspaces/library/grid.py", "tests/test_library_grid.py"]
flags: ['human-verify']
level: 1
unblocks: 1
budget_minutes: 30
---
# 53 — Library thumbnails in millivolts with a shared family y-scale

**Model:** [S] · **Size:** [S]

**What to build:** Library thumbnails draw real amplitude, in millivolts, unnormalised — and every
card within one family shares a y-scale so that relative depth between members is
visible rather than flattened by per-card autoscaling.

**This is not a style preference and it must not be "improved" later.** The
clustering z-normalises so that "same shape" has a definition; the figures must not,
because the project's own submission language is that *normalisation of amplitude
destroys the evidence of scaling laws for depolarisation events*. A grid of tidy,
identically-scaled cards is a grid that has deleted the finding. The reasoning is
written out at the top of `Working/Detection/drop_motifs/cluster.py`, which does
both things correctly and explains why they differ.

The seed bundle carries both a raw and a detrended trace per motif. Draw the
detrended one — it is what detection ran on and what "the same shape" was defined
against.

Shared y-scale is **within** a family, not across the whole grid: two families whose
amplitudes differ by an order of magnitude should each be readable.

**Blocked by:** 50

**Files/modules touched:** `UI/workspaces/library/grid.py`, `tests/test_library_grid.py`.

**Merge risk:** **LOW.** One file, and a chain with T54 and T55 which own it after you. The
trap is reaching for the existing z-normalised overlay builder because it is right
there — it normalises, which is exactly what this ticket forbids.

**Acceptance criteria:**
- [ ] Thumbnails render the detrended trace in millivolts with no amplitude normalisation.
- [ ] All cards within one family share a y-range; families do not share one with each other.
- [ ] A test asserts the rendered y-range of two cards in the same family is identical and reflects real millivolt values.
- [ ] The grid still constructs headlessly with non-`None` panes.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
