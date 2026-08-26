---
id: 69
title: "Compare two chains as canvases with the difference highlighted"
model: opus
size: M
blocked_by: [57, 67, 68]
mutex: []
files: ["UI/workspaces/analyse/compare.py", "tests/test_compare.py"]
flags: ['human-verify']
level: 1
unblocks: 0
budget_minutes: 60
---
# 69 — Compare two chains as canvases with the difference highlighted

**Model:** [O] · **Size:** [M]

**What to build:** The Compare view shows the two runs' **chains**, stacked one above the other as
block canvases, with what differs between them highlighted — and keeps the existing
detection overlap below.

Today it shows two dropdowns of run ids and a list of interval pairs. That answers
"do these two detection sets overlap" and never "what was different about the two
chains", which for a one-parameter sweep is the only question.

Three things on the surface, in this order:

1. Both chains drawn as canvases, upper and lower, using the same card rendering the
   builder uses — not a second, independently drifting drawing of a chain.
2. The difference highlighted: a step added, a step removed, a parameter changed.
   Two six-block chains differing in one parameter is exactly where "obvious how
   they differ" fails without help.
3. A one-line summary of the difference, so it can be pasted into notes without
   transcribing a diagram.

The existing overlap output stays, below. The researcher gets both "what was
different" and "what did it change".

Runs are identified by their name (T67) alongside their id, so the two selectors
stop being a pair of integers.

**Blocked by:** 57, 67, 68

**Files/modules touched:** `UI/workspaces/analyse/compare.py`, `tests/test_compare.py`.

**Merge risk:** **MEDIUM.** Reuses the builder's card rendering (T57) and the diff function
(T68) — importing both is the point; a second chain drawing here would drift from
the builder's and nobody would notice until they disagreed.

**Acceptance criteria:**
- [ ] Both runs' chains render as stacked block canvases using the builder's card rendering.
- [ ] Steps added, removed, or whose parameters differ are visually highlighted.
- [ ] A one-line summary states the difference in words.
- [ ] The existing detection-set overlap output remains, below the chain comparison.
- [ ] Run selectors show each run's name alongside its id.
- [ ] A headless construction test asserts the surface returns non-`None` panes for two chains that differ and for two that are identical.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
