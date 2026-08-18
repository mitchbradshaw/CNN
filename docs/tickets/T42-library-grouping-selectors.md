---
id: 42
title: "Library grouping selectors"
model: haiku
size: S
blocked_by: [38]
mutex: []
files: ["UI/workspaces/library/grid.py"]
flags: ['human-verify']
level: 4
unblocks: 0
budget_minutes: 30
---
# 42 — Library grouping selectors

**Model:** [H] · **Size:** [S]

**What to build:** compare what each grouping basis produces over the same entries — shape, cluster
membership, or manual tag.

**Blocked by:** 38

**Files/modules touched:** `UI/workspaces/library/grid.py`.

**Merge risk:** **LOW.** *This is deliberately its own ticket because it is third on the cut list —
cutting it should mean not starting a ticket, not unpicking one.*

**Acceptance criteria:**
- [ ] A selector groups the grid by shape, by cluster membership, or by manual tag.
- [ ] The same entries appear under every basis; only the grouping changes.
- [ ] Tags are never treated as a primary key.
