---
id: 33
title: "Compare view: two-run set overlap"
model: opus
size: M
blocked_by: [25, 27]
mutex: [44]
files: ["UI/workspaces/analyse/compare.py", "Working/compare.py", "tests/test_compare.py"]
flags: ['human-verify']
level: 8
unblocks: 3
budget_minutes: 60
---
# 33 — Compare view: two-run set overlap

**Model:** [O] · **Size:** [M]

**What to build:** "does the banded chain find things the direct chain misses" becomes a question the
tool answers, using the one comparison mechanism the surrogate control will also use.

**Blocked by:** 25, 27

**Files/modules touched:** new `Working/compare.py` (the overlap computation, headless); new
`UI/workspaces/analyse/compare.py`; new `tests/test_compare.py`.

**Merge risk:** **HIGH vs ticket 44.** The PRD states that comparing two chains and comparing a run
against its surrogate are the same mechanism — "one implementation serves two research questions."
**This ticket owns the overlap and counts computation in `Working/compare.py`; ticket 44 consumes it.**
If these run in parallel, you will get two implementations and the claim stops holding.

**Acceptance criteria:**
- [ ] Overlap between two completed runs' span sets is computed headlessly, with no UI import.
- [ ] The result reports intersection, each run's exclusive remainder, and counts for each.
- [ ] Span matching uses an explicit, named overlap criterion — reuse `similarity.interval_iou` rather
      than writing a second overlap notion.
- [ ] The exclusive remainder is routable into the Review queue for hand adjudication.
- [ ] A person picks two runs and sees the comparison without the pane blanking.
