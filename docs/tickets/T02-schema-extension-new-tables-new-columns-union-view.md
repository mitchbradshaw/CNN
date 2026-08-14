---
id: 2
title: "Schema extension: new tables, new columns, union view"
model: sonnet
size: M
blocked_by: []
mutex: [4, 16, 19, 25, 36]
files: ["Working/database/runs.py", "Working/database/schema.py", "tests/test_database.py"]
flags: []
level: 0
unblocks: 32
budget_minutes: 60
---
# 02 — Schema extension: new tables, new columns, union view

**Model:** [S] · **Size:** [M]

**What to build:** every additive schema change the pipeline needs, applied in one place, so that
`init_db()` on an existing database produces the new shape without touching a single existing row.

**Blocked by:** None — can start immediately.

**Files/modules touched:** `Working/database/schema.py` (`_SCHEMA`, new `_*_NEW_COLUMNS` lists,
`init_db`); `Working/database/runs.py` (accessors for the new tables); `tests/test_database.py`.

**Merge risk:** **HIGH vs ticket 04.** Both edit `schema.py`, and 04 rewrites a table that 02 has just
extended. They are sequenced by a blocking edge — do not attempt to overlap them. Also **MEDIUM vs
16, 19, 25, 36**, all of which add accessors to `runs.py`; each should add its own functions and touch
no existing ones.

**Acceptance criteria:**
- [ ] `adjudications` exists: one row per detection, with verdict, note, created_at, and an
      `adjudication_tags` join table against `tag_vocabulary`.
- [ ] `motif_entry`, `motif_member`, `motif_edge` exist. An entry is identified by recording and sample
      range with optional nullable provenance pointers to a detection or an annotation. A member may
      reference any recording and any channel. An edge carries distance function, threshold, distance
      value, recipe hash, and nullable inter-channel lag, waveform correlation and classification bin.
- [ ] `motif_entry_tags` attaches tags many-to-many; no tag is part of any primary key.
- [ ] `run_groups` exists; `runs` gains a nullable `run_group_id` and a nullable `surrogate_of_run_id`.
- [ ] `step_artifacts` exists, keyed on a recipe-prefix hash plus step index, storing an artifact path.
- [ ] `templates` exists, storing a name and a steps JSON blob with no recording or span.
- [ ] `v_spans` exists as a view unioning `annotations` and `detections` with an `origin` column whose
      only values are `'human'` and `'machine'`.
- [ ] Calling `init_db()` twice against a populated database leaves every row count and every
      annotation-tag link identical.
- [ ] No `INSERT` in this ticket writes an annotation row from a machine source.
