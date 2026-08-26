---
id: 52
title: "Spike trains as train-scale library entries"
model: sonnet
size: M
blocked_by: [50]
mutex: [51, 67]
files: ["Working/database/schema.py", "Pipelines/import_drop_motifs/", "tests/test_database.py", "tests/test_import_drop_motifs.py"]
flags: []
level: 1
unblocks: 1
budget_minutes: 60
---
# 52 — Spike trains as train-scale library entries

**Model:** [S] · **Size:** [M]

**What to build:** A spike train becomes a library entry in its own right, not just a string
repeated on 84 member rows.

Right now the only thing a spike train is, is the `span_key` column on each motif
that came out of it. That is enough to *group* by it and not enough to *link* it:
an edge attaches to a row, and a train has no row. The stated end-goal — asking
which spike trains resemble each other, by symbolic or spectral similarity — is
blocked until it does.

`motif_entry` gains a **scale** column with two values: one meaning "this entry is
a single event" and one meaning "this entry is a whole spike train". The column is
nullable and added through the existing additive column migration, which checks
`PRAGMA table_info` first and adds only what is missing. `init_db()` stays
idempotent.

The importer then writes, alongside the event-scale entries T50 produces, one
train-scale entry per spike train in the bundle — 16 of them — whose members are
the motifs that came out of that train.

**Scale is stored, never inferred.** Deriving it from duration would work today on
this bundle and break the first time a long single event or a short train arrives,
and the failure would be silent misclassification rather than an error.

**Blocked by:** 50

**Files/modules touched:** `Working/database/schema.py`, `Pipelines/import_drop_motifs/`, `tests/test_database.py`, `tests/test_import_drop_motifs.py`.

**Merge risk:** **MEDIUM.** `Working/database/schema.py` is the shared file — T67 also adds a
column to it, which is why the two are mutually exclusive. Follow the existing
additive-migration pattern exactly; do not rebuild a table. The importer half
overlaps T50/T51, hence those mutexes too.

**Acceptance criteria:**
- [ ] `motif_entry` carries a scale column distinguishing an event-scale entry from a train-scale one.
- [ ] `init_db()` remains idempotent — calling it twice adds the column once.
- [ ] A database created before this change gains the column when `init_db()` next runs.
- [ ] The importer writes one train-scale entry per spike train in the bundle, with that train's motifs as its members.
- [ ] Event-scale entries from T50 are unaffected and still resolve.
- [ ] Scale is read from the bundle's provenance, never derived from a span's duration.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
