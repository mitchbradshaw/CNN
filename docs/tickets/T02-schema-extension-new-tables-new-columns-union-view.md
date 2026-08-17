---
id: 2
title: "Schema extension: new tables, new columns, union view"
model: sonnet
size: M
blocked_by: []
mutex: [4, 16, 19, 25, 36]
files: ["Working/database/schema.py", "tests/test_database.py"]
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
`init_db`); `tests/test_database.py`. **`Working/database/runs.py` is deliberately not on this list —
see the adjudication at the end.**

**Merge risk:** **HIGH vs ticket 04.** Both edit `schema.py`, and 04 rewrites a table that 02 has just
extended. They are sequenced by a blocking edge — do not attempt to overlap them. Risk against 16, 19,
25 and 36 was MEDIUM while this ticket wrote accessors; with `runs.py` off the list it is now low, and
those tickets each add their own functions to it.

**Acceptance criteria:**
- [ ] `adjudications` exists: one row per detection, with verdict, note, created_at, and an
      `adjudication_tags` join table against `tag_vocabulary`. `verdict` is `TEXT NOT NULL` with **no
      `CHECK` constraint** — see the adjudication at the end.
- [ ] `motif_entry`, `motif_member`, `motif_edge` exist. An entry is identified by recording and sample
      range with optional nullable provenance pointers to a detection or an annotation. A member may
      reference any recording and any channel. An edge carries distance function, threshold, distance
      value, recipe hash, and nullable inter-channel lag, waveform correlation and classification bin.
- [ ] `motif_entry_tags` attaches tags many-to-many; no tag is part of any primary key.
      `motif_entry` gets the columns named above and no others — `label` and `notes` are presentation
      fields nothing here asks for, and ticket 16 owns what a library entry displays.
- [ ] `run_groups` exists; `runs` gains a nullable `run_group_id` and a nullable `surrogate_of_run_id`.
      `run_groups` carries an id and a created_at and nothing further that is `NOT NULL` — fan-out and
      scope semantics are ticket 25's. The previous attempt made `config_id` mandatory, which decides
      on 25's behalf that a group cannot exist before its config does.
- [ ] `step_artifacts` exists, keyed on a recipe-prefix hash plus step index, storing an artifact path.
- [ ] `templates` exists, storing a name and a steps JSON blob with no recording or span.
- [ ] ~~`v_spans` exists as a view unioning `annotations` and `detections` with an `origin` column
      whose only values are `'human'` and `'machine'`.~~ **Withdrawn — see below.**
- [ ] Calling `init_db()` twice against a populated database leaves every row count and every
      annotation-tag link identical — `annotations` and `annotation_tags` included, not only the new
      tables.
- [ ] No `INSERT` in this ticket writes an annotation row from a machine source.
- [ ] No function is added to `Working/database/runs.py`, or to any module outside the file list. The
      schema is asserted by introspection (`PRAGMA table_info`, `PRAGMA index_list`, `sqlite_master`),
      not through accessors this ticket does not own.

**Adjudicated 2026-08-17 — `v_spans` is withdrawn from this ticket.**

The run-20260817-1157 review blocked on it and was right to. Standards rule 2.5 forbids the `origin`
column *by name* — "no `origin` column is introduced to paper over it" — and CLAUDE.md gives this file
precedence over the ticket on standards. The first attempt's in-code defence, that the view is a
read-only derivation and so creates no write path, is a reasonable argument but it is an argument for
amending rule 2.5, and that is not this ticket's to make.

So: **do not build `v_spans`.** Build the seven tables and columns above and nothing else. Whatever
needs to read across both sources can join them at the call site until a ticket that owns the
question decides how the two are presented together.

**Adjudicated 2026-08-17 — `adjudications` carries no `CHECK` on `verdict`.**

Not a preference. Rule 2.2 says schema changes are additive and names **ticket 04's rebuild as the one
exception in this backlog**. SQLite cannot alter a `CHECK` in place, so a four-verdict `CHECK` written
here makes adding `seed` a *second* non-additive rebuild — one that rule 2.2 does not permit and no
ticket owns. Ticket 04's own acceptance criteria already claim the resolution: "the five verdict terms
are defined as one shared constant that both the annotation path and the adjudication path import."

So the verdict column is a plain `TEXT NOT NULL` with no `CHECK`, and the vocabulary is enforced in
Python by whichever ticket writes the adjudication path — 19, using 04's shared constant. Adding
`seed` then touches one constant and no table. Do not hard-code the four literals anywhere in this
ticket; `queries.VERDICTS` already holds them twice and rule 6.4 counts a third copy as duplication.

**Adjudicated 2026-08-17 — this ticket adds no accessors at all.**

`Working/database/runs.py` is removed from the file list. Ticket 02 is schema and nothing else.

The previous attempt wrote `insert_motif_entry`, `insert_motif_edge`, `insert_run_group`,
`insert_step_artifact`, a verdict-validating `insert_adjudication`, and eight read accessors. Rule 1.4
makes declared ownership real, and `docs/tickets/README.md` says in as many words that **library entry
creation is owned by 16**. Edges are 36's, run groups 25's, step artifacts 15's, adjudication policy
19's. This ticket's own `mutex: [4, 16, 19, 25, 36]` is exactly that set — the mutex was the design
already saying these tickets own these functions; writing them here made the mutex meaningless.

Every acceptance criterion above is about the *shape* of the schema, and shape is testable without an
accessor: `PRAGMA table_info`, `PRAGMA index_list`, and `sqlite_master` answer all of them, and raw
`INSERT` statements in the test cover the idempotency criterion. If a criterion seems to need a
helper, it does not — introspect instead.

This also disposes of the rest of the round-two findings without further argument: the eight
unrequested read accessors (rule 7.1), the speculative orderings (6.2), `insert_step_artifact`'s
get-or-create that silently discarded a differing `path` (6.1), and `insert_motif_edge`'s eleven-
parameter data clump all cease to exist along with the file.

**One criterion tightened.** The idempotency test must assert what rule 2.1 actually requires — *every*
row count and *every* tag link, including `annotations` and `annotation_tags`, not just the new
tables. The previous attempt checked only the new ones, which cannot catch the regression the rule
exists to catch.

**Keep the module docstring current.** `schema.py`'s header lists the tables and the migration steps;
a new table that is not in it is a stale doc on the file most likely to be read first.
