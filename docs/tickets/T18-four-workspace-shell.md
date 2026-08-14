---
id: 18
title: "Four-workspace shell"
model: opus
size: M
blocked_by: [4, 17]
mutex: [27]
files: ["UI/admin.py", "UI/viewer/layout.py", "UI/workspaces/__init__.py", "tests/test_session_persistence.py", "tests/test_shortcuts_and_view_controls.py"]
flags: ['human-verify']
level: 2
unblocks: 18
budget_minutes: 60
---
# 18 — Four-workspace shell

**Model:** [O] · **Size:** [M]

**What to build:** the seven tabs become Explore, Analyse, Review, Library plus an Admin group — the
research loop rather than a filing cabinet.

**Blocked by:** 04, 17

**Files/modules touched:** `UI/viewer/layout.py` (the `pn.Tabs` assembly); new
`UI/workspaces/__init__.py` with a registration point per workspace; `UI/admin.py`;
`tests/test_session_persistence.py`, `tests/test_shortcuts_and_view_controls.py`.

**Merge risk:** **HIGH — eight tickets mount into this shell** (20, 29, 31, 34, 37, 38, 42, and the
Admin import action in 27). Land it, then **freeze the shell module**: workspace tickets register into
it and never edit it. If a workspace ticket needs a shell change, it declares this ticket as a blocker
and the change is made here.

**Acceptance criteria:**
- [ ] Four workspaces plus an Admin group replace the seven tabs.
- [ ] Explore is the existing viewer, behaviourally unchanged: rasterized zoom on visible range,
      vectorised annotation overlays, coverage and density ribbons, drag modes, filters, keyboard
      shortcuts, cross-channel peek, session persistence.
- [ ] Explore gains `seed` as a fifth verdict in the annotation form, reading the shared vocabulary
      constant from ticket 04.
- [ ] Analyse, Review and Library exist as empty mount points that register content without editing
      the shell.
- [ ] Admin holds vocabulary administration and recording import, both working as they do today.
- [ ] The "Reopen" action in run history still switches to the correct workspace — the existing
      `self.tabs.active = 1` behaviour has an equivalent.
- [ ] Session persistence tests pass; a person confirms every workspace renders and none is blank.
