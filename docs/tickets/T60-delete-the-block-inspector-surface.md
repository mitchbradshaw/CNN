---
id: 60
title: "Delete the Block inspector surface"
model: sonnet
size: S
blocked_by: [59]
mutex: []
files: ["UI/workspaces/analyse/inspector.py", "UI/workspaces/__init__.py", "tests/test_block_inspector.py"]
flags: []
level: 2
unblocks: 0
budget_minutes: 30
---
# 60 — Delete the Block inspector surface

**Model:** [S] · **Size:** [S]

**What to build:** Remove the Block inspector. Everything it did now happens on the block card.

This is the *contract* half of the expand-contract T59 began. The inspector was a
third surface editing the same chain model as the builder and the run panel, which
is why none of the three read as authoritative — the researcher could never tell
which one was the real one.

Delete the surface, its registration into the Analyse workspace, and its tests. Do
**not** delete the parameter-widget generation or the derived-readout mixin: those
are shared modules the inspector merely used, and the card and the run panel both
still need them.

Nothing else may regress. The Analyse workspace loses a sub-tab and gains nothing;
that is the whole visible change.

**Blocked by:** 59

**Files/modules touched:** `UI/workspaces/analyse/inspector.py`, `UI/workspaces/__init__.py`, `tests/test_block_inspector.py`.

**Merge risk:** **LOW-MEDIUM.** A deletion, so the risk is deleting one thing too many. The
shared parameter/derive modules are used by two other surfaces — check who imports
what before removing a file. The workspace registry raises on a duplicate label but
not on a missing one, so a half-removed registration fails quietly.

**Acceptance criteria:**
- [ ] The Block inspector surface and its registration are removed.
- [ ] The Analyse workspace builds without it and its remaining sections are unaffected.
- [ ] The shared parameter-widget and derived-readout modules remain, still used by the block card and the run panel.
- [ ] The inspector's own test module is removed; no other test is weakened to accommodate the deletion.
- [ ] The full suite passes with no regressions.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
