---
id: 66
title: "Run a single algorithm as a one-block chain"
model: opus
size: M
blocked_by: [59, 62]
mutex: [64, 65]
files: ["UI/analyse/controls.py", "UI/analyse/layout.py", "tests/test_run_panel.py"]
flags: ['human-verify', 'done']
level: 2
unblocks: 0
budget_minutes: 60
---
# 66 — Run a single algorithm as a one-block chain

**Model:** [O] · **Size:** [M]

**What to build:** Running one algorithm becomes composing a chain with one block in it. The
standalone stage and algorithm dropdowns on the Run algorithm surface retire.

Today there are two ways to do the same thing: pick a stage and an algorithm from
dropdowns on the run surface, or add one block in the builder. Two routes to one
outcome is precisely the ambiguity that makes neither surface read as the real one,
and it is why the chain builder gets bypassed.

The stage and algorithm selection moves onto the block card. What stays on the Run
algorithm surface is what is genuinely **chain-wide** rather than per-block: the
staged-span basket, the span selector, and the run controls.

**The simplest case must not get harder.** Running one algorithm on one span should
take no more steps than it does today — one block, its parameters, run. If it does,
this ticket has failed even if every test passes.

**Read this before starting:** this is the ticket that removes the old workflow. If
the filmstrip is weak, this makes the tool worse before it makes it better. It is
flagged for human verification for that reason, and it is the fourth item on the
PRD's cut list. If the surface it depends on did not land cleanly, stop and say so
rather than proceeding.

**Blocked by:** 59, 62

**Files/modules touched:** `UI/analyse/controls.py`, `UI/analyse/layout.py`, `tests/test_run_panel.py`.

**Merge risk:** **HIGH.** Removes a working path. Mutually exclusive with T64 and T65.
Requires a person to use it, not just tests to pass — a suite can confirm the
one-block chain runs and cannot confirm that doing so still feels direct.

**Acceptance criteria:**
- [ ] Stage and algorithm are chosen on the block card, not on the Run algorithm surface.
- [ ] The standalone stage and algorithm selectors are removed from the run surface.
- [ ] The staged-span basket, span selector and run controls remain on the run surface.
- [ ] A one-block chain runs and produces the same result the old single-algorithm path did.
- [ ] Running one algorithm takes no more interactions than before.
- [ ] A headless construction test asserts the run surface still returns non-`None` panes after the selectors are removed.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
