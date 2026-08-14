---
id: 15
title: "Step cache in the executor"
model: opus
size: M
blocked_by: [2, 8, 14]
mutex: [3, 8, 13, 14, 24]
files: ["Working/config.py", "Working/database/runs.py", "Working/execution.py", "tests/test_step_cache.py"]
flags: []
level: 4
unblocks: 12
budget_minutes: 60
---
# 15 — Step cache in the executor

**Model:** [O] · **Size:** [M]

**What to build:** retuning one stage of a chain reuses the expensive stages before it, so parameter
exploration stops being gated on recomputing a matrix profile every time.

**Blocked by:** 02, 08, 14

**Files/modules touched:** `Working/execution.py` (prefix hashing and the resume walk);
`Working/database/runs.py` (`step_artifacts` accessors); `Working/config.py` (the write threshold);
new `tests/test_step_cache.py`.

**Merge risk:** **HIGH vs 08 and 24** — three tickets edit `execute_recipe`'s step loop. Sequence
08 → 15 → 24. **HIGH vs 14** on hash construction. **MEDIUM vs `Working/encoding_cache.py`**, which
already caches encodings by recipe hash: this ticket must not duplicate it. Decide explicitly whether
the step cache subsumes the encoding cache or sits above it, and record the answer in the ticket.

**Why [O]:** a wrong prefix hash does not raise — it returns a plausible cached artifact from a
different parameterisation, and the result looks like a finding. This is the ticket where the
reproducibility claim quietly dies if it is done carelessly.

**Acceptance criteria:**
- [ ] Each step's cache key is the hash of the recipe prefix up to and including that step, with the
      step's side-input bindings included in the hashed content.
- [ ] On run, the executor walks the chain and resumes at the first step with no cached artifact.
- [ ] An artifact is written only when the step's measured runtime exceeds the configured threshold, so
      trivial filters cost no disk.
- [ ] **The test that matters:** in an *n*-step chain, changing the parameters of step *k* recomputes
      steps *k* through *n* and reuses steps 0 through *k*−1, asserted by artifact identity on disk —
      not by timing.
- [ ] Changing a step's side-input binding invalidates that step's cache and everything after it.
- [ ] Cached artifacts round-trip through the ticket 01 serialisers, so no type needs a bespoke
      cache path.
- [ ] Interaction with `encoding_cache.py` is stated in the module docstring: either it is now unused
      by the executor, or it remains the storage layer beneath the step cache. Not both.
- [ ] No cache eviction is implemented — out of scope before the freeze.
