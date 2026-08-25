---
id: 39
title: "Entry detail: members overlay and edge list"
model: opus
size: M
blocked_by: [38]
mutex: [21, 38]
files: ["UI/workspaces/library/detail.py"]
flags: ['human-verify', 'done']
level: 4
unblocks: 1
budget_minutes: 60
---
# 39 — Entry detail: members overlay and edge list

**Model:** [O] · **Size:** [M]

**What to build:** a motif family inspectable as a set — the exemplar, every span matched to it, all of
them overlaid on a shared relative-time axis, and the edges that put them there.

**Blocked by:** 38

**Files/modules touched:** new `UI/workspaces/library/detail.py`; reads
`UI/plots.build_motif_waveform_overlay` — **not modified**.

**Merge risk:** **LOW** — the overlay builder already exists and is shared with ticket 21. **Do not add
a second overlay builder to `UI/plots.py`.**

**Acceptance criteria:**
- [ ] Clicking an exemplar shows it, its member list, and the all-members overlay on a shared
      relative-time axis.
- [ ] The edge list shows distance function, threshold and distance value per member.
- [ ] The overlay uses the existing plot builder, called not copied.
- [ ] A person opens a family with at least twenty members without the pane blanking.
