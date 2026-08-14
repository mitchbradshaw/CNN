---
id: 43
title: "Surrogate generation block"
model: sonnet
size: M
blocked_by: [5, 6]
mutex: [5, 6, 25]
files: ["Adapters/preprocessing_surrogate.py", "tests/test_surrogate.py"]
flags: []
level: 3
unblocks: 3
budget_minutes: 60
---
# 43 — Surrogate generation block

**Model:** [S] · **Size:** [M]

**What to build:** a signal-to-signal block that produces a null, reproducibly, from its recipe.

**Blocked by:** 05, 06

**Files/modules touched:** new `Adapters/preprocessing_surrogate.py`; new
`tests/test_surrogate.py`.

**Merge risk:** **MEDIUM vs 06** — shares the signal-transform helper if one was written; import it.
**Do not edit `Adapters/base.py`.**

**Acceptance criteria:**
- [ ] Declares `input_kind="Signal"`, `output_kind="Signal"`.
- [ ] Offers phase randomisation and block shuffling as a choice parameter.
- [ ] Exposes an explicit RNG seed among its `ParamSpec` parameters, so the recipe hash reproduces the
      surrogate exactly.
- [ ] **A fixed seed reproduces a bit-identical surrogate**, asserted by array equality.
- [ ] Phase randomisation preserves the power spectrum to within a stated tolerance, asserted directly.
