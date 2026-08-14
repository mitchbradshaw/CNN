---
id: 47
title: "Templates: save, apply, carry and rebind"
model: opus
size: M
blocked_by: [14, 30]
mutex: [14, 30]
files: ["Working/database/runs.py", "Working/templates.py", "tests/test_templates.py"]
flags: []
level: 6
unblocks: 0
budget_minutes: 60
---
# 47 — Templates: save, apply, carry and rebind

**Model:** [O] · **Size:** [M]

**What to build:** "reapply this exact search" and "reapply this method" become two different saved
things, and a workflow can be tested against a recording it has never seen.

**Blocked by:** 14, 30

**Files/modules touched:** new `Working/templates.py`; `Working/database/runs.py` (template accessors);
`UI/workspaces/analyse/` (save and apply actions); new `tests/test_templates.py`.

**Merge risk:** **MEDIUM vs 30** — reuses the side-input picker for rebind prompts; call it, do not
duplicate it. **MEDIUM vs 14** — a template's stored bindings must be ticket 14's structure.

**Why [O]:** the carry-versus-rebind distinction is the design judgement in this ticket. Get it wrong
and "does this workflow generalise" and "does this exact search generalise" become the same button.

**Acceptance criteria:**
- [ ] A template stores a chain's steps with recording and span stripped.
- [ ] Each side-input binding declares either *carry* — the exemplar travels with the template — or
      *rebind* — prompt on apply.
- [ ] Applying a template asks for recording, span and any rebinds, then constructs an ordinary recipe
      that validates.
- [ ] A template exports as JSON and imports on a machine whose local ids differ, resolving its carried
      exemplar by content. A test asserts this by rewriting the ids and reapplying.
- [ ] Applying a template to a recording it has never seen produces a run.
