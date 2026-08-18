---
id: 4
title: "Verdict-constraint rebuild: add `seed`"
model: opus
size: M
blocked_by: [2]
mutex: [2, 19]
files: ["Working/database/queries.py", "Working/database/schema.py", "tests/test_database.py"]
flags: ['human-gate', 'done']
level: 1
unblocks: 21
budget_minutes: 60
---
# 04 — Verdict-constraint rebuild: add `seed`

**Model:** [O] · **Size:** [M]

**What to build:** the annotation verdict vocabulary gains `seed`, so a shape recognised by eye can be
marked exemplar-worthy in the viewer using the same five terms adjudication uses.

**Blocked by:** 02

**Files/modules touched:** `Working/database/schema.py` (the `annotations` CREATE TABLE and a new
rebuild migration function called from `init_db`); `Working/database/queries.py`
(`insert_annotation`'s verdict validation); `tests/test_database.py`.

**Merge risk:** **HIGH vs ticket 02** — same file, and this rewrites a table 02 has extended with new
columns. Must merge strictly after 02. **MEDIUM vs ticket 19**, which shares the verdict vocabulary;
both must read one shared constant, not two literals.

**Why [O] and why a human looks:** SQLite cannot alter a `CHECK` constraint in place. This requires the
full rebuild procedure — create the new table, copy roughly eleven thousand rows, preserve the
`annotation_tags` join, drop, rename — against a table that has accumulated seven added columns
(`event_count`, `parent_annotation_id`, `status`, `relation_kind`, `deleted_at`, and the originals) and
is referenced by foreign keys. Getting the column list wrong loses data silently.

**Acceptance criteria:**
- [ ] The database file is backed up before the rebuild runs, to a path recorded in the migration's
      output.
- [ ] The `annotations` verdict constraint accepts exactly `seed`, `interesting`, `not_interesting`,
      `artifact`, `unsure`.
- [ ] Every annotation row survives: a test asserts identical row count and identical
      `(id, start_idx, end_idx, verdict)` tuples before and after.
- [ ] Every `annotation_tags` link survives: identical link count and identical
      `(annotation_id, tag_id)` pairs before and after.
- [ ] Every column added by the previous column migrations is present on the rebuilt table with its
      values intact, including soft-deleted rows (`deleted_at` non-null).
- [ ] The rebuild is idempotent — running `init_db()` twice does not rebuild twice and does not
      duplicate rows.
- [ ] The five verdict terms are defined as one shared constant that both the annotation path and the
      adjudication path import.
- [ ] **Fallback recorded in the ticket, not invented at merge time:** if the rebuild proves unsafe,
      record `seed` in the existing free-text `status` column instead, which needs no rebuild. Taking
      the fallback is a decision to surface, not to make silently.
