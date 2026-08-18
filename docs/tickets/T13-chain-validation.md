---
id: 13
title: "Chain validation"
model: sonnet
size: M
blocked_by: [5]
mutex: [8, 14, 15, 24, 29]
files: ["Working/chain_validation.py", "Working/execution.py", "Working/recipes.py", "tests/test_chain_validation.py", "tests/test_recipes.py"]
flags: [done]
level: 2
unblocks: 19
budget_minutes: 60
---
# 13 — Chain validation

> **Done.** Built by run-20260818-0554, which held it on an overlap false positive: its test file's
> `_run_all()` collided with T35's, the convention 41 of 42 test files follow. The gate now ignores
> `tests/`. The branch passed red-proof, suite and review (0 findings) and was merged as `f0b77e4`.
> Do not re-dispatch; the work is in the base.

**Model:** [S] · **Size:** [M]

**What to build:** one function that answers "can this output type feed this block, and if not, why
not" — consumed at composition to disable a block with its reason shown, and at execution to hard-fail
before any computation.

**Blocked by:** 05

**Files/modules touched:** new `Working/chain_validation.py`; `Working/recipes.py` (`make_recipe` calls
it); `Working/execution.py` (called before the step loop); new `tests/test_chain_validation.py`.

**Merge risk:** **MEDIUM vs 14** (both edit `recipes.py`) and **MEDIUM vs 08/15/24** (all edit
`execution.py`). The rule to state in the ticket: **no caller may inline its own compatibility check.**
Ticket 29's add-step control and ticket 24's runner both call this function; if either writes its own,
the two layers drift, which is the exact failure the single-function design exists to prevent.

**Acceptance criteria:**
- [ ] One function takes a producing type and a consuming block and returns a boolean plus a
      human-readable reason string.
- [ ] The reason names both types and states what would be needed — a message a researcher can learn
      the type system from, not "incompatible".
- [ ] A test walks the full compatibility matrix of seven types against every registered block and
      asserts both the boolean and the reason for each incompatible pair.
- [ ] The three worked chains validate end to end: the CNN chain (signal → window set → grouping →
      model), the seeded search chain (signal → scores with an exemplar side-input → span set), and
      the banded search chain (signal → bandpass → scores → span set).
- [ ] `make_recipe` rejects an invalid chain at construction with the reason string.
- [ ] `execute_recipe` rejects an invalid chain before the first step runs — a test hand-writes an
      invalid recipe dict, bypassing `make_recipe`, and asserts it fails before any adapter is called.
