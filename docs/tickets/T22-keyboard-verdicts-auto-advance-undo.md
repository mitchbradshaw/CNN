---
id: 22
title: "Keyboard verdicts, auto-advance, undo"
model: opus
size: M
blocked_by: [21]
mutex: []
files: ["UI/workspaces/review/queue_state.py", "UI/workspaces/review/surface.py"]
flags: ['human-verify']
level: 5
unblocks: 3
budget_minutes: 60
---
# 22 — Keyboard verdicts, auto-advance, undo

**Model:** [O] · **Size:** [M]

**What to build:** single-key verdicts that advance automatically, with an undo, so hundreds of
candidates are an afternoon rather than a fortnight.

**Blocked by:** 21

**Files/modules touched:** `UI/workspaces/review/surface.py` (same file as 21 — sequential),
`UI/workspaces/review/queue_state.py`.

**Merge risk:** **HIGH if run in parallel with 21** — same file. Sequence strictly. **MEDIUM vs
`tests/test_shortcuts_and_view_controls.py`**, since the viewer already binds keyboard shortcuts; the
Review bindings must not collide with Explore's.

**Acceptance criteria:**
- [ ] Five keys map to the five verdicts; the mapping is displayed on screen, not memorised.
- [ ] A verdict writes an adjudication row and advances in one keystroke.
- [ ] Undo reverses the last verdict and returns to that candidate.
- [ ] Keys are inert while a text field has focus, so typing a note does not fire a verdict.
- [ ] No binding collides with an existing Explore shortcut; the existing shortcut tests pass.
- [ ] A person adjudicates fifty real candidates end to end without the pane blanking or the index
      desynchronising from the displayed candidate.
