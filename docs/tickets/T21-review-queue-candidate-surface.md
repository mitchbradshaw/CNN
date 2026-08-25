---
id: 21
title: "Review queue: candidate surface"
model: opus
size: M
blocked_by: [20]
mutex: [20, 39]
files: ["UI/plots.py", "UI/workspaces/review/surface.py"]
flags: ['human-verify', 'done']
level: 4
unblocks: 4
budget_minutes: 60
---
# 21 — Review queue: candidate surface

**Model:** [O] · **Size:** [M]

**What to build:** one candidate at a time, in context, with enough padding and overlay to judge it in
under a second.

**Blocked by:** 20

**Files/modules touched:** new `UI/workspaces/review/surface.py`; reads `UI/plots.py`
(`build_motif_waveform_overlay`, `build_detection_overlay`) — **not modified**.

**Merge risk:** **LOW, and lower than expected** — `plots.build_motif_waveform_overlay(normalize=True)`
already implements the z-normalised overlay, so this ticket and ticket 39 both call it rather than each
writing one. **Do not add a new overlay builder to `UI/plots.py`.**

**Why [O] and why a person looks:** this is one of the linked-view surfaces the PRD singles out. A
broken dynamic map renders as a blank pane, not an error.

**Acceptance criteria:**
- [ ] One candidate renders in signal context with configurable padding on each side.
- [ ] Its analytical score is displayed alongside.
- [ ] The z-normalised overlay uses the existing plot builder, called not copied.
- [ ] Changing filters or advancing re-renders without the pane going blank — confirmed by a person
      stepping through at least twenty candidates.
- [ ] Adjudication throughput is a session, not a project: a person can judge a candidate without
      scrolling or clicking into a second view.
