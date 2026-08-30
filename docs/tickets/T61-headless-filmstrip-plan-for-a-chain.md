---
id: 61
title: "Headless filmstrip plan for a chain"
model: sonnet
size: M
blocked_by: []
mutex: []
files: ["UI/analyse/chain_state.py", "tests/test_chain_state.py"]
flags: ['done']
level: 0
unblocks: 1
budget_minutes: 60
---
# 61 — Headless filmstrip plan for a chain

**Model:** [S] · **Size:** [M]

**What to build:** A function that answers "what should the filmstrip show", with no Panel and no
browser involved.

Given a chain, it returns the ordered list of what to render: for each step, its
position, its label, the interchange type coming in, the interchange type going
out, and whether that step's cached result is current or stale.

**This function is the reason the plot-centric feature is testable at all.** The
alternative — deciding the filmstrip's contents inside Panel callbacks — makes the
whole feature verifiable only by a human looking at it, and the specific failure
mode here is that a broken pane renders *blank* rather than raising. A blank
filmstrip and a filmstrip that was never wired up are indistinguishable by eye
until someone notices a plot they expected is missing.

So the decision lives in the model, headless, and one test asserts "this chain
shows six entries in this order with these types". T62 then renders whatever this
returns.

Staleness comes from the existing content-addressed step cache, which is keyed on a
recipe-prefix hash — a step is current if its prefix hash has a cached artifact.
Read that; do not invent a second notion of freshness.

**Blocked by:** nothing — can start immediately

**Files/modules touched:** `UI/analyse/chain_state.py`, `tests/test_chain_state.py`.

**Merge risk:** **MEDIUM.** Touches the chain model, which T57 is told not to touch — so this
is the one ticket that may. Adding a query is safe; changing the step shape is not,
because the builder, the run surface and the recipe serialiser all read it.

**Acceptance criteria:**
- [ ] A function returns an ordered per-step plan for a chain: position, label, input type, output type, cache state.
- [ ] The plan's order matches the chain's execution order.
- [ ] A step with a current cached result is reported as current; one without is reported as stale.
- [ ] An empty chain returns an empty plan rather than raising.
- [ ] The function imports no UI library and touches no Panel object.
- [ ] Tests run headlessly with no browser.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
