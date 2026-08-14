---
id: 28
title: "Chain state model"
model: sonnet
size: M
blocked_by: [13]
mutex: [29]
files: ["UI/analyse/chain_state.py", "tests/test_chain_state.py"]
flags: []
level: 3
unblocks: 9
budget_minutes: 60
---
# 28 — Chain state model

**Model:** [S] · **Size:** [M]

**What to build:** the headless representation of a chain under construction — steps, ordering,
parameters, bindings, and which blocks may be added next. Testable without a browser.

**Blocked by:** 13

**Files/modules touched:** new `UI/analyse/chain_state.py` (no Panel import); new
`tests/test_chain_state.py`.

**Merge risk:** **MEDIUM vs 29** (29 renders this). Splitting the state out is what makes 29 a
renderable-only ticket and keeps the composition logic headlessly testable.

**Acceptance criteria:**
- [ ] Add, remove and reorder steps; each operation revalidates the chain.
- [ ] For the current chain tail, the model returns every registered block with a boolean and a reason
      from ticket 13's function — it does not compute compatibility itself.
- [ ] The model converts to a well-formed recipe via `make_recipe` and back.
- [ ] Removing a step whose output a later step's side-input is bound to either rebinds or reports the
      break — it does not silently produce an invalid chain.
- [ ] The module imports no UI library.
