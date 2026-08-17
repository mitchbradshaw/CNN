---
id: 5
title: "Adapter spec expansion (expand phase)"
model: sonnet
size: M
blocked_by: [1]
mutex: [6, 7, 8, 9, 11, 12, 43]
files: ["Adapters/base.py", "Adapters/registry.py", "tests/test_adapter_spec.py"]
flags: [done]
level: 1
unblocks: 28
budget_minutes: 60
---
# 05 — Adapter spec expansion (expand phase)

> **Done.** Merged by run-20260817-2050 as `49dbdfb`, both review rounds clean (0 findings). The `done`
> flag keeps the file loadable — every `blocked_by: [5]` still resolves — while dropping it out of
> scheduling. Do not re-dispatch; the work is in the base.

**Model:** [S] · **Size:** [M]

**What to build:** the adapter contract gains typed inputs, typed side-inputs and a runtime estimator,
accepting both the old and new output vocabularies at once so no adapter breaks on the day it lands.

**Blocked by:** 01

**Files/modules touched:** `Adapters/base.py` (`AdapterSpec`, `AdapterResult`, `OUTPUT_KINDS`);
`Adapters/registry.py` (validation only); new `tests/test_adapter_spec.py`.

**Merge risk:** **`Adapters/base.py` and `Adapters/registry.py` are frozen after this ticket.**
Tickets 06, 07, 08, 09, 11, 12 and 43 all add or edit adapters against this contract; if any of them
also edits `base.py`, the result is a five-way merge on a dataclass every adapter constructs. State
that constraint in each of those tickets.

**Acceptance criteria:**
- [ ] `AdapterSpec` gains `input_kind` (one of the seven type names, or `None` meaning "root signal").
- [ ] `AdapterSpec` gains `side_inputs`: a list, each entry naming its type and the source kinds it may
      bind to (`root_signal`, `earlier_step`, `library_exemplar`).
- [ ] `AdapterSpec` gains `estimate`: an optional callable returning predicted runtime in seconds, or
      `None` meaning "counts as free".
- [ ] `output_kind` accepts the seven type names **in addition to** `signal` / `intervals` / `encoding`;
      `__post_init__` rejects anything outside the union with a message naming the valid set.
- [ ] `AdapterResult` gains a `value` field carrying a typed object from ticket 01, alongside the
      existing `x` / `t` / `intervals` / `encoding` fields, which are untouched.
- [ ] `recommend`, `derive`, `persist`, `max_span_samples`, `plot` and `validate_params` are unchanged
      — this ticket adds fields and removes none.
- [ ] All nineteen existing adapters import and register without modification, and the full suite
      passes with no regressions against the run baseline.
