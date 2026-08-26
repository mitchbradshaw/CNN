---
id: 62
title: "Plot every step of the chain as a filmstrip"
model: opus
size: L
blocked_by: [56, 61]
mutex: []
files: ["UI/analyse/results.py", "UI/analyse/layout.py", "tests/test_run_panel.py"]
flags: ['human-verify']
level: 1
unblocks: 3
budget_minutes: 120
---
# 62 — Plot every step of the chain as a filmstrip

**Model:** [O] · **Size:** [L]

**What to build:** The Run algorithm surface shows every stage of the analysis, not just the last
one.

Today it shows exactly one plot: the staged span before the run, replaced by the
result after. A six-step chain therefore produces one picture, and there is no way
to see what the detrend did before the SAX ran, or what the SAX produced before the
matrix profile consumed it. For a tool whose purpose is understanding what a
technique does to a signal, the intermediate states — where the understanding
actually lives — are not rendered at all.

The surface becomes a **filmstrip**: the chain's input plotted at the top, then one
plot per step in order below it, so the whole transformation reads as a single
scroll. Each plot is labelled with the block that produced it and the interchange
type it is, so six stacked plots are navigable rather than a wall of curves.

Two things are handed to you and neither should be rebuilt: the **plan** (T61) says
what to show and in what order, and the **type renderer** (T56) turns each value
into an element. This ticket is the surface that walks one and calls the other.

Every step gets a plot, including the ones whose output is not a signal. If a
Grouping or a Model renders as a summary rather than a curve, that is correct — a
blank pane is not.

**Blocked by:** 56, 61

**Files/modules touched:** `UI/analyse/results.py`, `UI/analyse/layout.py`, `tests/test_run_panel.py`.

**Merge risk:** **HIGH.** The most visible surface in the wave, and T64, T65 and T66 all build
on it and own overlapping files, which is why the three are mutually exclusive with
each other. Linked HoloViews panes in a stack are exactly where this codebase has
had silently blank panes twice; the headless construction test is not optional.

**Acceptance criteria:**
- [ ] The surface renders the chain's input at the top and one plot per step below, in execution order.
- [ ] Each plot is labelled with the block that produced it and its interchange type.
- [ ] A step whose output is not a signal still renders something, via the type renderer.
- [ ] The rendered order matches the plan returned by the headless plan function.
- [ ] A headless construction test asserts the filmstrip returns the expected number of panes, each with a non-`None` object, for a multi-step chain.
- [ ] No type switching happens in this surface — every value goes through the single render function.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
