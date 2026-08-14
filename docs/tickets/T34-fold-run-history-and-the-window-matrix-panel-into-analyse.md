---
id: 34
title: "Fold run history and the window-matrix panel into Analyse"
model: sonnet
size: M
blocked_by: [18, 29]
mutex: [29, 30, 31, 32, 38]
files: ["UI/run_history.py", "UI/window_matrix_panel.py", "UI/workspaces/analyse/__init__.py", "UI/workspaces/analyse/history.py", "UI/workspaces/analyse/window_matrix.py", "tests/test_run_panel_matrix_profile.py", "tests/test_window_matrix_panel.py"]
flags: ['human-verify']
level: 5
unblocks: 0
budget_minutes: 60
---
# 34 — Fold run history and the window-matrix panel into Analyse

**Model:** [S] · **Size:** [M]

**What to build:** the old standalone panels move inside the Analyse workspace, and the tabs they used
to occupy disappear.

**Blocked by:** 18, 29

**Files/modules touched:** `UI/run_history.py` → `UI/workspaces/analyse/history.py`;
`UI/window_matrix_panel.py` → `UI/workspaces/analyse/window_matrix.py`;
`UI/workspaces/analyse/__init__.py`; `tests/test_window_matrix_panel.py`,
`tests/test_run_panel_matrix_profile.py`.

**Merge risk:** **MEDIUM vs 29, 30, 31, 32** — same workspace package. Blocked by 29 even though not
logically gated, so it lands after the builder rather than beside it.

**Acceptance criteria:**
- [ ] Run history appears as a sidebar within Analyse and can reload a past chain into the builder.
- [ ] The window-matrix panel is reachable within Analyse with its existing behaviour, including its
      coverage ribbon.
- [ ] The standalone tabs are removed, not merely hidden.
- [ ] `tests/test_window_matrix_panel.py`, `test_window_matrix_coverage_ribbon.py` and
      `test_run_panel_matrix_profile.py` pass.
