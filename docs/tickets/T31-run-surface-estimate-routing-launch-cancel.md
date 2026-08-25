---
id: 31
title: "Run surface: estimate, routing, launch, cancel"
model: sonnet
size: M
blocked_by: [26, 29]
mutex: [29, 32, 34, 44]
files: ["UI/workspaces/analyse/run_surface.py"]
flags: ['human-verify', 'done']
level: 8
unblocks: 4
budget_minutes: 60
---
# 31 — Run surface: estimate, routing, launch, cancel

**Model:** [S] · **Size:** [M]

**What to build:** the decision surface before a run — what it will cost, where it should execute, and
the ability to stop it.

**Blocked by:** 26, 29

**Files/modules touched:** new `UI/workspaces/analyse/run_surface.py`; reads ticket 26's routing value.

**Merge risk:** **HIGH vs 32** (same file — sequence them) and **MEDIUM vs 44**: the surrogate toggle
belongs to ticket 44. **Do not stub a toggle here** or two will need merging.

**Acceptance criteria:**
- [ ] The chain estimate is displayed before launch, including the fan-out multiplier.
- [ ] Above the configured ceiling, "export cluster job" becomes the primary action and local execution
      is visibly demoted — it is not removed.
- [ ] Launch starts the ticket 24 background run; cancel stops it between steps.
- [ ] The scope selector — recordings, channels, span, bands — feeds ticket 25's fan-out.
- [ ] No surrogate control appears on this surface.
