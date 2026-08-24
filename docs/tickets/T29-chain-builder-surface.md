---
id: 29
title: "Chain builder surface"
model: opus
size: M
blocked_by: [18, 28]
mutex: [13, 17, 28, 30, 31, 32, 34]
files: ["UI/analyse/chain_state.py", "UI/workspaces/analyse/builder.py"]
flags: ['human-verify', 'done']
level: 4
unblocks: 8
budget_minutes: 60
---
# 29 — Chain builder surface

**Model:** [O] · **Size:** [M]

**What to build:** the staged list a researcher composes a chain in, where an incompatible block is
visibly disabled with its reason stated inline rather than absent.

**Blocked by:** 18, 28

**Files/modules touched:** new `UI/workspaces/analyse/builder.py`; reads
`UI/analyse/chain_state.py`.

**Merge risk:** **MEDIUM vs 30, 31, 32, 34** — all mount into the Analyse workspace. Ticket 17's split
is what makes these separate files; keep them separate. **Note:** `RunPanel` already has
`refresh_staged_list`, `_on_remove_staged`, `_on_clear_staged`, `_on_stage_changed` and
`_on_algorithm_changed` — this ticket relocates and extends that behaviour, it does not invent it.

**Why [O] and why a person looks:** linked-view surface; a blank pane is the failure mode.

**Acceptance criteria:**
- [ ] The chain renders as an ordered staged list — no node canvas, no fan-out within a chain.
- [ ] The add-step control lists every block; incompatible ones are disabled with the reason from
      ticket 13 shown inline, not filtered out of the list.
- [ ] Reorder and delete work and revalidate immediately.
- [ ] The existing staged-list behaviour from `RunPanel` is preserved; its tests pass.
- [ ] A person composes the three worked chains without the pane blanking.
