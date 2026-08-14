---
id: 25
title: "Scope selection and run-group fan-out"
model: sonnet
size: M
blocked_by: [2, 24]
mutex: [2, 43, 44]
files: ["Working/database/runs.py", "Working/recipes.py", "Working/run_groups.py", "tests/test_run_groups.py"]
flags: []
level: 6
unblocks: 10
budget_minutes: 60
---
# 25 — Scope selection and run-group fan-out

**Model:** [S] · **Size:** [M]

**What to build:** a sixteen-channel sweep or a five-band decomposition is one action, using one
mechanism rather than two.

**Blocked by:** 02, 24

**Files/modules touched:** new `Working/run_groups.py`; `Working/database/runs.py` (run-group
accessors); `Working/recipes.py` (fan-out target list in the recipe); new `tests/test_run_groups.py`.

**Merge risk:** **HIGH vs ticket 43's band path** — a band list and a channel list are deliberately the
same mechanism. If the surrogate or banded work implements a second fan-out, the PRD's
"band decomposition is the same mechanism as channel fan-out" stops being true. This ticket owns
fan-out; everything else parameterises it. **MEDIUM vs `Working/database/bands.py`**, which already
exists — read it before defining a band list format.

**Acceptance criteria:**
- [ ] A run over N channels or N bands creates one `run_groups` row and N `runs` rows referencing it.
- [ ] Locally the N runs execute sequentially with per-item progress.
- [ ] The fan-out target list is baked into the recipe, so a cluster task index can select its own
      target from it.
- [ ] A channel fan-out and a band fan-out go through the same code path — a test asserts this by
      running both and comparing the run-group structure.
- [ ] Existing band definitions in `Working/database/bands.py` are reused, not redefined.
