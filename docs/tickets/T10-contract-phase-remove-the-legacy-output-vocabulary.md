---
id: 10
title: "Contract phase: remove the legacy output vocabulary"
model: sonnet
size: S
blocked_by: [6, 7, 8, 9, 11, 12]
mutex: []
files: ["Adapters/base.py"]
flags: []
level: 5
unblocks: 0
budget_minutes: 30
---
# 10 — Contract phase: remove the legacy output vocabulary

**Model:** [S] · **Size:** [S]

**What to build:** the dual-form support added in ticket 05 is deleted, leaving the seven type names as
the only vocabulary in the codebase.

**Blocked by:** 06, 07, 08, 09, 11, 12

**Files/modules touched:** `Adapters/base.py` (`OUTPUT_KINDS`, `AdapterResult` legacy fields,
`__post_init__`); any residual call site found by search.

**Merge risk:** none by construction — it runs after every migrate batch and every new adapter. It must
be the last adapter-layer ticket to merge. If it merges early, every unmigrated adapter breaks at
import and the registry silently skips it (`discover_adapters` catches import errors and continues),
which fails as a *missing block in a dropdown* rather than as an error.

**Acceptance criteria:**
- [ ] `OUTPUT_KINDS` contains only the seven type names.
- [ ] `AdapterResult`'s `x`, `t`, `intervals` and `encoding` fields are removed; every adapter populates
      `value` only.
- [ ] A test enumerates every registered adapter and asserts its `output_kind` is one of the seven.
- [ ] A test asserts `discover_adapters()` registers the expected adapter count, so a silently skipped
      import fails the suite rather than disappearing from a dropdown.
- [ ] All 195 existing tests plus everything added in milestone 1 pass.
