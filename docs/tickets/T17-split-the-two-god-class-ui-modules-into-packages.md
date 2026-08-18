---
id: 17
title: "Split the two god-class UI modules into packages"
model: opus
size: M
blocked_by: []
mutex: [3, 16, 29]
files: ["UI/__init__.py", "UI/app.py", "UI/run_panel.py"]
flags: ['solo', 'human-verify', 'done']
level: 0
unblocks: 26
budget_minutes: 60
---
# 17 — Split the two god-class UI modules into packages

**Model:** [O] · **Size:** [M]

**What to build:** `UI/app.py` and `UI/run_panel.py` become packages of focused modules, so the seven
UI tickets that follow can run in parallel instead of queueing on two files.

**Blocked by:** None — can start immediately.

**Files/modules touched:** `UI/app.py` (2282 lines, one `ViewerApp` class) → `UI/viewer/` package;
`UI/run_panel.py` (2248 lines, one `RunPanel` class, ~70 methods) → `UI/analyse/` package;
`UI/__init__.py`; every test importing from either.

**Merge risk:** **THIS IS THE HIGHEST-BLAST-RADIUS TICKET IN THE BACKLOG, and it is also the one that
removes the most risk from everything after it.** It conflicts with any ticket editing either file, so
it must land before 16, 18, 29, 30, 31, 32, 34, 37 and 38 start, and nothing else may touch those two
files while it is in flight. Run it alone, first, on day one.

**Why [O] and why a human looks:** a pure mechanical split still has to preserve the widget wiring and
the cross-references between the ~70 `RunPanel` methods and the `ViewerApp` instance each holds. The
failure mode this codebase has already hit twice — a dynamic map rendering as a silently blank pane
rather than raising — applies directly: a broken import path or a lost `param` watcher does not throw,
it just stops updating.

**Acceptance criteria:**
- [ ] `ViewerApp` is split along its existing seams — signal view, overlays and ribbons, selection and
      drag modes, annotation forms, filters, session persistence, layout — into modules under
      `UI/viewer/`, with the class assembled from mixins or composed collaborators.
- [ ] `RunPanel` is split into at least: staged-chain state, parameter/derive controls, run execution
      and progress, result display, encoding display, and motif-save actions, under `UI/analyse/`.
- [ ] **No behaviour changes.** Every existing UI test passes unmodified except for its import line.
- [ ] The seven-tab layout still renders and every tab still works — verified by a person opening the
      app, not by a test.
- [ ] No module under `UI/` is imported by anything in `Working/` or `Adapters/`; a test asserts this
      by walking imports.
- [ ] Each resulting module is under 600 lines.
