---
id: 38
title: "Library grid"
model: opus
size: M
blocked_by: [16, 18, 36]
mutex: [34, 39]
files: ["UI/motif_browser.py", "UI/workspaces/library/grid.py", "tests/test_motif_browser.py"]
flags: ['human-verify', 'done']
level: 3
unblocks: 3
budget_minutes: 60
---
# 38 — Library grid

**Model:** [O] · **Size:** [M]

**What to build:** the shape vocabulary at a glance — a thumbnail grid of exemplars with a scope
summary, absorbing the existing motif browser.

**Blocked by:** 16, 18, 36

**Files/modules touched:** new `UI/workspaces/library/grid.py`; `UI/motif_browser.py` (absorbed);
`tests/test_motif_browser.py`.

**Merge risk:** **MEDIUM vs 39** (same package) and **MEDIUM vs 34**, if both absorb legacy panels in
the same window. `UI/motif_browser.py` is a 480-line single class — absorb it rather than rewriting it.

**Why [O] and why a person looks:** linked-view surface.

**Acceptance criteria:**
- [ ] Exemplars render as a thumbnail grid.
- [ ] Each shows its scope: which recordings and which channels its members appear in.
- [ ] The existing motif browser's behaviour is preserved or explicitly superseded, with
      `tests/test_motif_browser.py` updated rather than deleted.
- [ ] A person browses the real library without the grid blanking.
