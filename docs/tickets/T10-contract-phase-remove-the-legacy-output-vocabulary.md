---
id: 10
title: "Contract phase: remove the legacy output vocabulary"
model: haiku
size: S
blocked_by: [6, 7, 8, 9, 11, 12]
mutex: []
files: ["Adapters/base.py", "Adapters/*.py", "Working/execution.py", "Working/side_inputs.py", "UI/analyse/controls.py", "UI/analyse/execution.py", "UI/workspaces/analyse/run_surface.py"]
flags: ['done']
level: 5
unblocks: 0
budget_minutes: 30
---
# 10 — Contract phase: remove the legacy output vocabulary

**Model:** [H] · **Size:** [S]

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
- [x] `OUTPUT_KINDS` contains only the seven type names. (Already true on arrival — ticket 48
      removed the legacy names; pinned by a test rather than built.)
- [x] `AdapterResult`'s `x`, `t`, `intervals` and `encoding` fields are removed; every adapter populates
      `value` only. The eight encoding blocks had no typed value at all and gained a real `Encoding`.
      The SAX blocks' `x`/`t` were load-bearing (the encoding view's panel 1 draws the exact
      preprocessed array) and moved to `meta`, alongside matrix_profile's existing arrays.
- [x] A test enumerates every registered adapter and asserts its `output_kind` is one of the seven
      (`input_kind` and every side input's `type_kind` too — a join is only safe if both ends agree).
- [x] A test asserts `discover_adapters()` registers every shipped module, so a silently skipped
      import fails the suite rather than disappearing from a dropdown. Asserted as membership rather
      than as a count: the registry is global and other test modules register probes into it.
- [x] The full suite passes with no regressions against the run baseline, including everything
      added in milestone 1.
