---
id: 23
title: "Promote an adjudicated candidate into the library"
model: sonnet
size: S
blocked_by: [16, 19, 22]
mutex: [16, 37]
files: ["UI/workspaces/review/surface.py"]
flags: ['human-verify']
level: 6
unblocks: 2
budget_minutes: 30
---
# 23 — Promote an adjudicated candidate into the library

**Model:** [S] · **Size:** [S]

**What to build:** scoring and cataloguing become one continuous motion — an adjudicated candidate
becomes a library exemplar by an explicit action, and only by an explicit action.

**Blocked by:** 16, 19, 22

**Files/modules touched:** `UI/workspaces/review/surface.py`; calls ticket 16's entry-creation helper.

**Merge risk:** **HIGH vs 16 and 37** — three tickets create entries. 16 owns the helper; this ticket
and 37 call it. If this ticket writes its own insert, the library gains two creation paths with
different provenance handling.

**Acceptance criteria:**
- [ ] Promotion creates a `motif_entry` from the adjudicated candidate, retaining a provenance pointer
      to the detection.
- [ ] Promotion is an explicit action — no verdict implicitly creates an entry. A test asserts that
      adjudicating every candidate in a queue creates zero entries.
- [ ] Promotion writes no annotation row.
- [ ] The entry appears in the library immediately without a restart.
