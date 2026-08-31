---
id: 63
title: "Headless suffix recomputation from a changed step"
model: sonnet
size: S
blocked_by: []
mutex: []
files: ["Working/execution.py", "tests/test_step_cache.py"]
flags: ['done']
level: 0
unblocks: 1
budget_minutes: 30
---
# 63 — Headless suffix recomputation from a changed step

**Model:** [S] · **Size:** [S]

**What to build:** A function that answers: when step N's parameters change, which steps must be
re-run?

The answer is **the suffix and only the suffix** — step N and everything after it.
Steps before N are untouched, and their cached results stay valid, because the step
cache is keyed on a recipe-*prefix* hash: changing step 4 cannot alter the hash of
the prefix ending at step 3.

This is small and it is worth its own ticket because getting it wrong is expensive
and invisible. The naive implementation re-runs the whole chain, which is correct
and, on any chain containing a matrix profile, the difference between instant and
several hours. Nobody notices a correctness bug here; they notice that tuning a
filter takes all afternoon and conclude the tool is slow.

Pure function: recipe in, step index in, the indices to recompute out. No database,
no execution, no UI.

**Blocked by:** nothing — can start immediately

**Files/modules touched:** `Working/execution.py`, `tests/test_step_cache.py`.

**Merge risk:** **LOW.** `Working/execution.py` is a shared and central module, but this is an
addition beside the existing prefix-hash helper rather than a change to the runner.
Do not alter the hashing itself — every cached artifact on disk depends on it.

**Acceptance criteria:**
- [ ] A function returns the step indices invalidated by a change at a given index.
- [ ] The returned set is exactly the changed step and every step after it.
- [ ] Steps before the changed index are never returned.
- [ ] Changing the first step returns every step; changing the last returns only itself.
- [ ] An index outside the recipe raises rather than returning silently.
- [ ] The function is pure — no database, no execution, no UI.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
