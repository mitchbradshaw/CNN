---
id: 19
title: "Adjudication store and divergence queries"
model: sonnet
size: M
blocked_by: [2, 4]
mutex: [2, 4]
files: ["Working/database/adjudications.py", "Working/database/queries.py", "tests/test_adjudications.py"]
flags: ['done']
level: 2
unblocks: 7
budget_minutes: 60
---
# 19 — Adjudication store and divergence queries

**Model:** [S] · **Size:** [M]

**What to build:** a human verdict against a machine detection is storable and queryable, in a table
that physically cannot hold a human annotation.

**Blocked by:** 02, 04

**Files/modules touched:** new `Working/database/adjudications.py`; `Working/database/queries.py`
(divergence queries over `v_spans`); new `tests/test_adjudications.py`.

**Merge risk:** **MEDIUM vs 02** (`runs.py` / schema accessors) and **MEDIUM vs 04** (shared verdict
vocabulary constant — import it, do not restate the five terms).

**The invariant to state in the ticket and assert in a test:** adjudicating writes an adjudication row
against a detection and **never** an annotation row.

**Acceptance criteria:**
- [ ] One adjudication per detection, with verdict from the shared five-term vocabulary, a note, and
      tags through a join table.
- [ ] Re-adjudicating a detection updates the existing row rather than inserting a second.
- [ ] A test asserts that no code path in this module inserts into `annotations`.
- [ ] A divergence query returns detections a human rejected — machine says yes, human says no.
- [ ] A divergence query returns annotations with no overlapping detection — human says yes, machine
      said nothing. This direction reads through `v_spans`.
- [ ] Both directions are queryable with equal standing over one read path.
- [ ] A queue query filters candidates by run, run group, method, score range, channel and adjudication
      status, and is fast enough on the existing detection volume to page without a visible pause.
