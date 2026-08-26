---
id: 57
title: "Draw the chain as a horizontal block canvas"
model: opus
size: L
blocked_by: []
mutex: []
files: ["UI/workspaces/analyse/builder.py", "tests/test_chain_builder.py"]
flags: ['human-verify']
level: 0
unblocks: 4
budget_minutes: 120
---
# 57 — Draw the chain as a horizontal block canvas

**Model:** [O] · **Size:** [L]

**What to build:** The chain builder draws the chain as a chain: block cards left to right, in
execution order, each showing what type it takes in and what type it hands on.

Today it renders a vertical list of step labels above a taller vertical list of
twenty "Add ..." buttons. Nothing about that says "these steps happen in order and
data flows through them", so chains do not get composed — the researcher falls back
to running single algorithms, which is the workflow the whole build exists to
replace.

Each card carries the step's position, its algorithm name, its input type on the
edge it receives from and its output type on the edge it hands to, and controls to
reorder and delete it. Cards sit in a horizontally scrolling row with a connector
between them.

**Scroll horizontally; do not wrap.** Wrapping to a second row destroys the
left-to-right reading that is the entire reason for the change.

**Do not modify the chain model.** `UI.analyse.chain_state.ChainState` already
carries steps, ordering, parameters, side-input bindings and the compatibility
query. It already supports insertion at an index. This ticket is a *renderer* of
that model — nothing about drawing a canvas requires the model to change, and a
ticket that finds itself editing it has misread the seam. Type compatibility keeps
coming from the one chain-validation function; do not compute it here.

An invalid chain names the junction that is wrong, so the researcher fixes a
connection rather than guessing which step to remove.

Parameters stay where they are for now — T59 moves them onto the card. Ship the
canvas without them.

**Blocked by:** nothing — can start immediately

**Files/modules touched:** `UI/workspaces/analyse/builder.py`, `tests/test_chain_builder.py`.

**Merge risk:** **HIGH.** The primary Analyse surface, and T58/T59 own this file after you —
they are mutually exclusive with each other but both blocked on you, so land a
clean shape. This is linked-view Panel work: a broken dynamic map renders as a
silently blank pane, not an error, which is why a headless construction test is an
acceptance criterion rather than a nicety.

**Acceptance criteria:**
- [ ] The chain renders as horizontally arranged cards in execution order, one per step.
- [ ] Each card shows its algorithm name, its input type and its output type.
- [ ] Cards can be reordered and deleted, and the model updates accordingly.
- [ ] The row scrolls horizontally rather than wrapping.
- [ ] An invalid chain reports which junction is incompatible and why.
- [ ] A headless construction test asserts the builder returns the expected panes with non-`None` objects, for an empty chain and a multi-step chain.
- [ ] `UI/analyse/chain_state.py` is unchanged.

**Notes:** See `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**, "Chain shape, revised". Part 1's description of a vertical staged list is superseded and marked as such.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
