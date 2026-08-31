---
id: 70
title: "Collapse the run-history sidebar to a ribbon"
model: sonnet
size: M
blocked_by: [57]
mutex: []
files: ["UI/workspaces/analyse/history.py", "UI/workspaces/__init__.py", "tests/test_workspaces.py"]
flags: ['human-verify', 'done']
level: 1
unblocks: 0
budget_minutes: 60
---
# 70 — Collapse the run-history sidebar to a ribbon

**Model:** [S] · **Size:** [M]

**What to build:** The run-history sidebar toggles between a narrow ribbon on the edge of the page
and a width that actually fits its table.

Today it is fixed at a width narrower than its own content: the status filter is cut
off mid-widget, and the recipe and parameter columns — the two that make history
worth having — are truncated. Meanwhile the chain canvas next to it wants every
pixel it can get.

Collapsed, it is a thin strip with a control to reopen it. Expanded, it is wide
enough to read, with explicit column widths so the columns that get truncated are
not the informative ones, and a status filter wide enough to show what has been
selected.

**Collapsed is the default while the chain builder is the active section**, because
a horizontally scrolling canvas and a wide sidebar otherwise fight over the same
space. That interaction is the reason this ticket is blocked on the canvas: it is
discoverable only once both exist, and finding it after both have merged is worse
than designing for it now.

The expanded width is fixed rather than fitted to content. Column widths are decided
in the browser and are not knowable when the layout is built, so "expands to fit the
table" is achievable only as "expands to a width the table fits in".

**This is first on the PRD's cut list.** If the wave runs short, this ticket is not
started — it is never half-done.

**Blocked by:** 57

**Files/modules touched:** `UI/workspaces/analyse/history.py`, `UI/workspaces/__init__.py`, `tests/test_workspaces.py`.

**Merge risk:** **LOW-MEDIUM.** Touches the workspace shell, which is deliberately frozen and
which several surfaces mount into. Add the section-aware default through the
existing sidebar registration rather than by editing the shell's assembly.

**Acceptance criteria:**
- [ ] The sidebar toggles between a collapsed ribbon and an expanded width.
- [ ] Expanded, the recipe and parameter columns are readable and the status filter shows its selections.
- [ ] Collapsed, a control to reopen it remains visible.
- [ ] The sidebar defaults to collapsed while the chain builder is the active Analyse section.
- [ ] A headless construction test asserts the workspace builds with the sidebar in each state.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
