# Manual build prompt — ticket 04, verdict-constraint rebuild

Ticket 04 is `human-gate`: the runner will never dispatch it, and **20 further tickets sit downstream
of it**, including ticket 18, which gates the entire UI half of the backlog. It is the single
highest-leverage manual action in the project.

Run this in an interactive Claude Code session at `C:\Users\mmebr\Documents\CNN`, watching it. Not
overnight, not with `--dangerously-skip-permissions`, not in a runner worktree.

**Before you start:** confirm the `annotations.sqlite` backup you took actually opens. A backup you
have not read is a hypothesis.

---

```
Work ticket 04 — the verdict-constraint rebuild. Read docs/tickets/T04-verdict-constraint-rebuild-add-seed.md
in full; it is the specification and its acceptance criteria are the definition of done. Read CLAUDE.md
and docs/CODING_STANDARDS.md for the rules that apply to every ticket here.

This ticket is human-gated and I am watching it. Ask me before anything irreversible. Do not treat my
silence as approval.

WHY THIS ONE IS DIFFERENT

SQLite cannot alter a CHECK constraint in place, so adding `seed` to the annotations verdict
vocabulary needs the full twelve-step table-rebuild procedure against roughly eleven thousand rows of
manual labelling that CANNOT BE REGENERATED from raw data plus code. Getting the column list wrong
does not raise — it silently drops a column's values. That is the failure mode to design against.

Ticket 02 must already be merged; this rewrites a table 02 has just extended.

METHOD

1. Read the live schema first, never a remembered one. Derive the column list from
   `PRAGMA table_info(annotations)` against the REAL database, plus every `_*_NEW_COLUMNS` list in
   Working/database/schema.py. Print what you found and let me check it before you write a migration
   that copies it. The ticket names five added columns; the schema is the authority on whether that
   list is complete, and a column that exists in the file but not in your INSERT is exactly how this
   goes wrong quietly.

2. Also enumerate, from the live database, before writing anything:
     - every index, trigger and view that references `annotations`
     - every foreign key pointing AT `annotations` (annotation_tags, and anything else)
     - the current `foreign_keys` and `legacy_alter_table` pragma settings
   The standard rebuild drops and recreates the table; anything in that list that you do not
   recreate afterwards is silently gone. SQLite drops dependent indexes and triggers with the table
   and does not warn you.

3. Test-first, against a synthetic fixture database, per the tdd skill. Build the fixture to look
   like the real thing in the ways that matter: rows carrying every added column, at least one
   soft-deleted row with `deleted_at` non-null, tag links across several annotations, and at least
   one row per existing verdict value. The acceptance criteria name the assertions — identical row
   count, identical `(id, start_idx, end_idx, verdict)` tuples, identical `(annotation_id, tag_id)`
   pairs, idempotence under a second `init_db()`.

4. THEN prove it on a COPY of the real database before it ever touches the real one. Copy
   DATA/db/annotations.sqlite to a scratch path, run `init_db()` against the copy, and diff the
   before/after for yourself: row counts, tag-link counts, per-column NULL counts, and the four-tuple
   set. A synthetic fixture cannot tell you whether the real file's seven accumulated columns and
   eleven thousand rows survive. Show me that diff. This is the step that makes the difference
   between a tested migration and a proven one.

5. Only after I have seen that diff do we consider running against the real database, and that is my
   decision to make, not yours.

CONSTRAINTS

- The five verdict terms become ONE shared constant that both the annotation path and the
  adjudication path import. Ticket 19 depends on there being exactly one. Do not leave two literals.
- The migration backs up the database file itself before rebuilding, to a path it prints. That is an
  acceptance criterion, not a nicety — and it is separate from the backup I already took.
- The rebuild must be idempotent: `init_db()` twice must not rebuild twice, must not duplicate rows,
  and must not re-backup on every startup.
- Wrap the rebuild in a single transaction, and verify counts INSIDE the transaction before
  committing, so a mismatch rolls back rather than lands.
- Stay inside the ticket's declared files: Working/database/schema.py, Working/database/queries.py,
  tests/test_database.py.
- The full suite must pass with no regressions. Note that tests/test_window_matrix_panel.py has a
  known background-thread flake unrelated to this work; if that is the only failure, say so rather
  than chasing it.

THE FALLBACK

The ticket records a fallback: if the rebuild proves unsafe, record `seed` in the existing free-text
`status` column instead, which needs no rebuild at all. Taking the fallback is a decision to surface
to me, with your reasoning — never one to make silently because the rebuild got difficult.

Start by reading the ticket and the live schema, then show me the column list and the dependent-object
inventory from step 2 before you write any code.
```

---

## After it lands

Commit on a branch off `main`, merge it yourself, and push. The runner reads ticket status from git,
not from a file — once ticket 04's work is on the branch the run cuts from, its 20 dependents become
dispatchable on the next run.

Ticket 04 keeps its `human-gate` flag afterwards. The flag means "the runner must never dispatch
this", not "this is unfinished", and re-running it would rebuild a table that no longer needs it.
