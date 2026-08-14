---
id: 24
title: "Background run execution: status, cancellation, per-stage results"
model: sonnet
size: M
blocked_by: [13, 15, 17]
mutex: [8, 13, 15]
files: ["UI/analyse/execution.py", "Working/database/runs.py", "Working/execution.py", "tests/test_execution.py"]
flags: []
level: 5
unblocks: 11
budget_minutes: 60
---
# 24 — Background run execution: status, cancellation, per-stage results

**Model:** [S] · **Size:** [M]

**What to build:** a run executes on a background thread with its state on the run row, cancellable
between steps, with each stage's result landing as it completes rather than at the end.

**Blocked by:** 13, 15, 17

**Files/modules touched:** `Working/execution.py` (per-step result callback);
`Working/database/runs.py` (current-step field on the run row); `UI/analyse/execution.py` (the
extracted `_on_run` worker); `tests/test_execution.py`.

**Merge risk:** **HIGH vs 08 and 15** — all three edit the step loop. Sequence 08 → 15 → 24.
**Note this is extension, not new work:** `RunPanel._on_run` already runs a `_worker()` thread with a
step-level `on_progress` and a cancel handler. Do not build a second execution path beside it.

**Acceptance criteria:**
- [ ] Status, current step index and error text live on the run row and are readable by a poller.
- [ ] Cancellation is cooperative, checked between steps, and marks the run failed with a note rather
      than leaving it half-written — the existing `RecipeCancelled` behaviour is preserved.
- [ ] Each stage's typed result is written and emitted as it lands, not accumulated to the end.
- [ ] Chain validation hard-fails before the first step, so an invalid recipe never starts computing.
- [ ] The existing step-level `on_progress` and the finer intra-step `run_kwargs["on_progress"]` remain
      two distinct callbacks with distinct signatures — a test asserts both still fire.
- [ ] `tests/test_execution.py` and `tests/test_run_panel.py` pass.
