---
id: 68
title: "Headless recipe diff"
model: sonnet
size: S
blocked_by: []
mutex: []
files: ["Working/compare.py", "tests/test_compare.py"]
flags: ['done']
level: 0
unblocks: 1
budget_minutes: 30
---
# 68 — Headless recipe diff

**Model:** [S] · **Size:** [S]

**What to build:** A function that takes two recipes and returns how they differ, step by step:
steps present in one and not the other, and parameters whose values differ.

Most comparisons on this project are one-parameter sweeps. "These two chains are
identical except `low_hz` is 0.01 in one and 0.05 in the other" is the answer the
researcher wants, and today nothing computes it — the Compare view reports detection
overlap, which answers what *changed* but never what was *different*.

Pure and headless: two recipe dicts in, a structured difference out. No database, no
UI. It goes beside the existing run-set comparison so the Compare surface has one
module to talk to rather than two.

Handle the awkward cases explicitly rather than by accident: chains of different
lengths, the same algorithm appearing twice in one chain, and a parameter present in
one step and absent in the other.

**Blocked by:** nothing — can start immediately

**Files/modules touched:** `Working/compare.py`, `tests/test_compare.py`.

**Merge risk:** **LOW.** An addition to a small module. The existing run-set comparison in the
same file is a different question — detection overlap, not recipe difference — and
they should not be merged.

**Acceptance criteria:**
- [ ] A function returns the per-step difference between two recipes.
- [ ] Steps present in one recipe and not the other are reported as added or removed.
- [ ] Parameters whose values differ are reported with both values.
- [ ] Chains of different lengths are handled without raising.
- [ ] A repeated algorithm within one chain is not mistaken for the same step.
- [ ] Two identical recipes report no difference.
- [ ] The function is pure — no database, no UI.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
