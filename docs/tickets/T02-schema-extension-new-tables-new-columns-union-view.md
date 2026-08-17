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
- [ ] ~~`v_spans` exists as a view unioning `annotations` and `detections` with an `origin` column
      whose only values are `'human'` and `'machine'`.~~ **Withdrawn — see below.**
- [ ] Calling `init_db()` twice against a populated database leaves every row count and every
      annotation-tag link identical.
- [ ] No `INSERT` in this ticket writes an annotation row from a machine source.

**Adjudicated 2026-08-17 — `v_spans` is withdrawn from this ticket.**

The run-20260817-1157 review blocked on it and was right to. Standards rule 2.5 forbids the `origin`
column *by name* — "no `origin` column is introduced to paper over it" — and CLAUDE.md gives this file
precedence over the ticket on standards. The first attempt's in-code defence, that the view is a
read-only derivation and so creates no write path, is a reasonable argument but it is an argument for
amending rule 2.5, and that is not this ticket's to make.

So: **do not build `v_spans`.** Build the seven tables and columns above and nothing else. Whatever
needs to read across both sources can join them at the call site until a ticket that owns the
question decides how the two are presented together.

**Two further review findings, folded in so they are not re-litigated:**

- The `adjudications` CHECK constraint must **not** hard-code the verdict literals. `queries.VERDICTS`
  is the source of truth and ticket 04 extends it with `seed`; a third hard-coded copy makes 04's
  rebuild wider and the two silently diverge in the meantime. Derive the constraint, or omit it and
  validate in the accessor.
- Accessors are **creation and read for the tables this ticket adds, nothing more.** Library entry
  creation belongs to 16, edges to 36, run groups to 25, step artifacts to 15, adjudication policy to
  19. Do not add query-policy helpers (orderings, filtered lists) that no acceptance criterion here
  asks for — the previous attempt added eight and every one was a finding.
