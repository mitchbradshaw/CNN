---
id: 51
title: "Make the library import idempotent and re-clusterable"
model: sonnet
size: S
blocked_by: [50]
mutex: [52]
files: ["Pipelines/import_drop_motifs/", "tests/test_import_drop_motifs.py"]
flags: []
level: 1
unblocks: 0
budget_minutes: 30
---
# 51 — Make the library import idempotent and re-clusterable

**Model:** [S] · **Size:** [S]

**What to build:** Running the importer twice must change nothing, and re-running it at a different
clustering threshold must regroup the library without re-ingesting the motifs and
without destroying anything set by hand.

This matters because the threshold is a research parameter, not a constant. A
threshold giving 40 families of ten is a different instrument from one giving 3
families of a hundred, and the researcher will want to try several. If each
attempt duplicates 410 members, or silently deletes the tags applied to the last
attempt, that exploration is not affordable.

Two different behaviours, deliberately not the same:

- **Members are content-keyed and never duplicated.** A motif is identified by its
  recording, start sample and end sample. A second import of the same bundle finds
  the member already there and reuses it. The writer for this already exists and is
  already named for the behaviour.
- **Entries and edges for one `(distance_function, threshold)` pair are replaced
  wholesale.** Re-clustering at that same pair replaces its grouping; re-clustering
  at a different one adds a grouping beside the existing ones rather than
  overwriting them.

Anything a human added — a manual tag, a hand-set exemplar — survives both.

**Blocked by:** 50

**Files/modules touched:** `Pipelines/import_drop_motifs/`, `tests/test_import_drop_motifs.py`.

**Merge risk:** **LOW-MEDIUM.** Same package as T50 and T52, which is why all three are
mutually exclusive. The subtle failure is replacing edges by entry rather than by
`(distance_function, threshold)`, which silently destroys a second clustering the
researcher wanted to keep beside the first.

**Acceptance criteria:**
- [ ] Running the importer twice against the same bundle leaves the member count unchanged.
- [ ] Re-running at the same distance function and threshold replaces that grouping's entries and edges rather than adding duplicates.
- [ ] Re-running at a different threshold leaves the previous grouping's rows intact.
- [ ] A manually applied tag on an entry survives a re-cluster at the same threshold.
- [ ] A test covers each of the four behaviours above.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
