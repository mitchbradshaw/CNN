---
id: 54
title: "Group the library grid by provenance or by shape"
model: opus
size: M
blocked_by: [52, 53]
mutex: []
files: ["UI/workspaces/library/grid.py", "tests/test_library_grid.py"]
flags: ['human-verify']
level: 2
unblocks: 1
budget_minutes: 60
---
# 54 — Group the library grid by provenance or by shape

**Model:** [O] · **Size:** [M]

**What to build:** The Library grid groups its cards along **two independent axes**, and the
researcher chooses which.

- **Provenance** — the spike train an entry came from. Exact, already in the data,
  no computation. Answers "what came out of this recording".
- **Shape** — the computed family, which pools motifs from every spike train.
  Answers "what recurs across recordings".

These are different questions and the interesting result is that they **disagree**.
Measured on the seed data: of twelve shape families, eleven draw members from more
than one spike train — up to eight — and two of them mix morphologies that the
per-span labels call distinct. That cross-recording recurrence is the claim the
thesis makes, and it is invisible unless both axes exist and can be seen not to
line up.

So a family drawing members from more than one recording is **marked as such on
the card**. It is the result, not a detail.

Switching axis never adds or drops an entry — it only changes how cards are
sectioned. That rule already governs the existing grouping selector; extend it
rather than replacing it.

Train-scale and event-scale entries (T52) are visually distinguishable, so the two
scales do not intermix into one undifferentiated grid.

**Blocked by:** 52, 53

**Files/modules touched:** `UI/workspaces/library/grid.py`, `tests/test_library_grid.py`.

**Merge risk:** **MEDIUM.** Linked-view Panel work on a file T53 has just changed and T55 will
change next. The failure mode this codebase has hit twice is a silently blank pane
— your acceptance includes a headless construction test for that reason.

**Acceptance criteria:**
- [ ] A selector groups the grid by provenance (spike train) or by computed shape family.
- [ ] The same entries appear under both axes; only the sectioning changes.
- [ ] An entry whose family spans more than one recording is marked on its card.
- [ ] Train-scale and event-scale entries are visually distinguishable.
- [ ] A headless construction test asserts the grid returns the expected panes with non-`None` objects under each axis.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
