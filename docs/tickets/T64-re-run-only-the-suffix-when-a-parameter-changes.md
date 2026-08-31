---
id: 64
title: "Re-run only the suffix when a parameter changes"
model: sonnet
size: M
blocked_by: [62, 63]
mutex: [65, 66]
files: ["UI/analyse/execution.py", "UI/analyse/results.py", "tests/test_run_panel.py"]
flags: ['human-verify', 'done']
level: 2
unblocks: 0
budget_minutes: 60
---
# 64 — Re-run only the suffix when a parameter changes

**Model:** [S] · **Size:** [M]

**What to build:** Editing a parameter updates the filmstrip by re-running that step and the ones
after it — never the whole chain.

Three behaviours, and the third is the one that protects the researcher:

- **Cheap suffix runs automatically.** Tuning a filter should feel immediate.
- **Expensive suffix asks first, with the estimate.** Above the interactive budget,
  the control says what it will cost and waits. Losing an afternoon to a keystroke
  is the thing being prevented.
- **Stale plots are marked stale while a re-run is in flight.** An old picture read
  as a new result is worse than no picture.

The estimate and the budget threshold **already exist** — they are the same
estimator and the same interactive-budget constant the run routing uses to decide
between local and cluster execution. Use them. A second cost model would drift from
the first, and the drift would surface as the two surfaces disagreeing about
whether the same chain is expensive.

Which steps to re-run comes from T63's function. Do not recompute that here.

**Blocked by:** 62, 63

**Files/modules touched:** `UI/analyse/execution.py`, `UI/analyse/results.py`, `tests/test_run_panel.py`.

**Merge risk:** **MEDIUM.** Mutually exclusive with T65 and T66 — all three build on the
filmstrip and touch overlapping files. The temptation is a fresh threshold constant
because the existing one is named for routing; resist it.

**Acceptance criteria:**
- [ ] Changing a parameter re-runs that step and its successors, and no earlier step.
- [ ] A suffix whose estimate is below the interactive budget runs without asking.
- [ ] A suffix above the budget shows its estimate and waits for confirmation.
- [ ] Plots for steps being recomputed are visibly marked stale until they land.
- [ ] The existing estimator and interactive-budget constant are used; no new threshold is introduced.
- [ ] A headless test asserts the recomputed set for a parameter change on a middle step.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
