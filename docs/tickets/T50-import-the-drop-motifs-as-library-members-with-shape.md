---
id: 50
title: "Import the drop motifs as library members with shape families"
model: sonnet
size: M
blocked_by: []
mutex: []
files: ["Pipelines/import_drop_motifs/", "tests/test_import_drop_motifs.py"]
flags: ['done']
level: 0
unblocks: 5
budget_minutes: 60
---
# 50 — Import the drop motifs as library members with shape families

**Model:** [S] · **Size:** [M]

**What to build:** A headless importer that reads the tracked motif seed bundle and populates the
motif library, so the Library grid stops being empty. Today `motif_entry`,
`motif_member` and `motif_edge` hold **zero rows**; the grid, its detail view and
its grouping selectors were all built against nothing.

The bundle lives at `DATA/library_seed/drop_motifs5/motifs/` — tracked on purpose,
see its `PROVENANCE.md`. It holds 410 individual drop motifs (rise-then-fall
depolarisation events) drawn from 16 catalogued spans across 7 channels.

**The reading and clustering already exist — do not write either.** A prototype
confirmed this end to end against the real bundle:

    store.load_run(bundle_dir)      -> {"events": 410, "snippets": 410, "manifest": ...}
    cluster.cluster_events(ev, sn)  -> 12 families, cophenetic r = 0.63
                                       sizes 80 59 37 35 34 34 25 23 23 22 19 19

`Working.Detection.drop_motifs.store` reads the bundle unchanged (its filenames
were already aligned to that reader's contract). `Working.Detection.drop_motifs.cluster`
does the shape clustering — Ward linkage on resampled, z-normalised vectors under
the scale-invariant distance. Your job is the third step only: turn a clustering
into library rows through the existing writers in `Working.database.runs`
(`insert_motif_entry`, `get_or_create_motif_member`, `insert_motif_edge`).

One shape family becomes one `motif_entry` (the exemplar is the member closest to
the family's mean waveform); every motif in it becomes a `motif_member` carrying
its recording, start and end sample; the within-family distances become
`motif_edge` rows recording the distance function, the threshold and the recipe
hash, exactly as the edge table already expects.

**Provenance must survive onto every member** — the spike train it came from, its
recording and channel, its morphology and purity. A card that cannot be traced
back to the signal is not evidence.

**Blocked by:** nothing — can start immediately

**Files/modules touched:** `Pipelines/import_drop_motifs/`, `tests/test_import_drop_motifs.py`.

**Merge risk:** **MEDIUM.** You own a new package. The risk is writing a second reader or a
second clustering rather than importing the two that exist — grep
`Working/Detection/drop_motifs/` before writing anything that parses a CSV or
computes a distance. `Working.database.runs` is shared with T52 and T67; you only
call its existing writers, you do not change them.

**Acceptance criteria:**
- [ ] The importer runs headlessly against the tracked seed bundle and exits 0.
- [ ] After a run, `motif_entry` holds one row per shape family and `motif_member` holds one row per imported motif.
- [ ] Every member carries the recording, channel and sample range it came from, resolvable back to a `recordings` row.
- [ ] `motif_edge` rows record the distance function, threshold and recipe hash that produced them.
- [ ] The existing Library grid renders the imported entries without modification.
- [ ] A test asserts the imported member count and that provenance survives onto a member row.
- [ ] No new reader and no new distance function is added — `store` and `cluster` are imported, not reimplemented.

**Notes:** The number of families is a parameter, not a constant. Twelve is what the
prototype produced with the module's own default; T51 makes re-clustering cheap,
so do not agonise over the value here.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
