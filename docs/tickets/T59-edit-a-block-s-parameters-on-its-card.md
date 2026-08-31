---
id: 59
title: "Edit a block's parameters on its card"
model: sonnet
size: L
blocked_by: [57]
mutex: [58]
files: ["UI/workspaces/analyse/builder.py", "tests/test_chain_builder.py"]
flags: ['human-verify', 'done']
level: 1
unblocks: 2
budget_minutes: 120
---
# 59 — Edit a block's parameters on its card

**Model:** [S] · **Size:** [L]

**What to build:** A block's parameters are edited on its own card — no navigating to a separate
surface and re-selecting the step already being looked at.

The card gains the generated parameter controls, the recommended-default values,
the live derived readouts, and a picker for each declared side input. The derived
readouts update as the researcher types, without running anything: they are what
makes a parameter like "seconds per symbol" picturable, by saying "symbols
produced: 256" beside it.

**All of this already exists and is already shared.** The parameter-widget
generation and the derived-readout mixin are used by both the run panel and the
block inspector today, precisely so an adapter's controls cannot drift between two
surfaces. Import them onto the card. Writing a third copy is the failure this
ticket is most likely to produce.

This is the *expand* half of removing the block inspector: after this ticket the
card and the inspector both work, and T60 deletes the inspector once nothing needs
it. Do not delete anything here.

**Blocked by:** 57

**Files/modules touched:** `UI/workspaces/analyse/builder.py`, `tests/test_chain_builder.py`.

**Merge risk:** **HIGH.** Shares `builder.py` with T58 (mutually exclusive). The controls you
are relocating are shared with the run panel — import them, do not fork them, or the
two surfaces will drift and the drift will be invisible until an adapter changes.

**Acceptance criteria:**
- [ ] Each card shows the generated parameter controls for its algorithm.
- [ ] Recommended defaults are offered and a modified value is marked as modified.
- [ ] Derived readouts recompute live as a parameter changes, without executing the step.
- [ ] A block declaring a side input shows a picker for it on the card.
- [ ] The parameter widgets and derived-readout logic are imported from the existing shared modules, not reimplemented.
- [ ] A headless construction test asserts a card with parameters returns non-`None` panes.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
