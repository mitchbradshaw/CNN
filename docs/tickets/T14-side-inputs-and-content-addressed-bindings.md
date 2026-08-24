---
id: 14
title: "Side-inputs and content-addressed bindings"
model: sonnet
size: M
blocked_by: [5, 13]
mutex: [12, 13, 15, 30, 47]
files: ["Working/execution.py", "Working/recipes.py", "Working/side_inputs.py", "tests/test_recipes.py", "tests/test_side_inputs.py"]
flags: ['done']
level: 3
unblocks: 15
budget_minutes: 60
---
# 14 — Side-inputs and content-addressed bindings

**Model:** [S] · **Size:** [M]

**What to build:** a step can draw an extra typed input from the root signal, an earlier step, or a
library exemplar, and that binding hashes by what it *is* rather than by what its local row id happens
to be.

**Blocked by:** 05, 13

**Files/modules touched:** `Working/recipes.py` (`make_recipe`, step shape, `_normalize`); new
`Working/side_inputs.py` (resolution); `Working/execution.py` (resolve before calling `run`);
`tests/test_recipes.py`, new `tests/test_side_inputs.py`.

**Merge risk:** **HIGH vs ticket 15** — both change what enters a recipe hash. 14 must land first and
15 must build its prefix hash on top of 14's step shape, not fork it. **MEDIUM vs 13** (both edit
`recipes.py`) and **MEDIUM vs 30** — the block inspector's side-input picker must emit exactly this
binding structure.

**Acceptance criteria:**
- [ ] A step may carry a `side_inputs` map of name to binding; each binding names its source kind and
      the content that identifies it.
- [ ] A `library_exemplar` binding hashes on source file, channel and sample range. The entry id is
      stored alongside as a convenience pointer and is **excluded** from the canonical JSON.
- [ ] A test changes an exemplar's local entry id and asserts the recipe hash is unchanged.
- [ ] A test changes an exemplar's sample range and asserts the recipe hash changes.
- [ ] `execute_recipe` resolves each binding to a typed value before calling the adapter's `run`, and
      raises a clear error naming the binding if it cannot be resolved.
- [ ] `canonical_json` still produces identical output for semantically identical recipes regardless of
      key order or numpy-versus-native scalar types — the existing hashing tests pass unmodified.
