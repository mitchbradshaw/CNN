---
id: 20
title: "Review queue: filters and queue state"
model: sonnet
size: M
blocked_by: [18, 19]
mutex: [21]
files: ["UI/workspaces/review/queue_state.py", "tests/test_review_queue.py"]
flags: ['human-verify']
level: 3
unblocks: 5
budget_minutes: 60
---
# 20 — Review queue: filters and queue state

**Model:** [S] · **Size:** [M]

**What to build:** the headless half of the candidate queue — which candidates are in it, in what
order, and what advancing means. Testable without a browser.

**Blocked by:** 18, 19

**Files/modules touched:** new `UI/workspaces/review/queue_state.py`; new `tests/test_review_queue.py`.

**Merge risk:** **MEDIUM vs 21** (same package; 21 renders what this holds). Keep the state object free
of any Panel import so it stays headlessly testable — that separation is what makes 20 a `[S]` ticket
and lets 21 be the only part needing a person.

**Acceptance criteria:**
- [ ] A queue object holds the filtered candidate list, the current index, and the verdict history.
- [ ] Filters for run, run group, method, score range, channel and adjudication status compose.
- [ ] Advancing moves to the next unadjudicated candidate under the current filter.
- [ ] Undo restores the previous index and reverses the last adjudication write.
- [ ] The module imports no UI library; every criterion above is asserted headlessly.
