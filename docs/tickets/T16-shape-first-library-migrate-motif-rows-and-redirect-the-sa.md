---
id: 16
title: "Shape-first library: migrate motif rows and redirect the save paths"
model: opus
size: M
blocked_by: [2]
mutex: [2, 17, 23, 37]
files: ["UI/motif_browser.py", "UI/run_panel.py", "Working/database/runs.py", "Working/database/schema.py", "tests/test_motif_browser.py", "tests/test_motif_migration.py"]
flags: []
level: 1
unblocks: 8
budget_minutes: 60
---
# 16 — Shape-first library: migrate motif rows and redirect the save paths

**Model:** [O] · **Size:** [M]

**What to build:** the library stops being keyed to detections. Existing motifs become entries, and
every path that saves a motif writes an entry instead.

**Blocked by:** 02

**Files/modules touched:** `Working/database/schema.py` (backfill in `init_db`);
`Working/database/runs.py` (`insert_motif`, `get_motif`, `list_motifs`, `motif_provenance` →
entry-based equivalents); `UI/run_panel.py` (`_save_motif`, `_on_save_detection_as_motif`,
`_on_save_viewport_as_motif`, `_on_save_encoding_as_motif`); `UI/motif_browser.py` (read path);
`tests/test_motif_browser.py`, new `tests/test_motif_migration.py`.

**Merge risk:** **HIGH vs ticket 17** — this edits four methods inside `RunPanel`, which 17 is
splitting into separate modules. Sequence 17 → 16, or accept a manual re-application of this diff
across the split files. **HIGH vs tickets 23 and 37**, which both create entries; this ticket owns the
single entry-creation helper both must call. **MEDIUM vs 02** on `runs.py`.

**Why [O]:** there are already three separate motif-save paths in `RunPanel` writing to the
detection-keyed `motifs` table, plus a `motif_tags` join and a legacy free-text `motifs.tags` column
alongside the vocabulary join. Consolidating those onto one entry-creation helper without losing a tag
link or a `sax_string` is judgement work, and getting it wrong is invisible until the library is queried.

**Acceptance criteria:**
- [ ] Every existing `motifs` row becomes a `motif_entry` row identified by recording and sample range,
      retaining its detection pointer as provenance.
- [ ] Every `motif_tags` link is carried across to `motif_entry_tags`; a test asserts identical link
      counts and identical tag values per entry.
- [ ] The legacy free-text `motifs.tags` column and `motifs.sax_string` are preserved on the entry or
      explicitly dropped with the reason stated — not silently lost.
- [ ] All three `RunPanel` save paths and any viewer path call **one** entry-creation helper.
- [ ] An entry can be created with no detection pointer at all — the eye-flagged exemplar case the old
      schema could not express. A test asserts this.
- [ ] The motif browser reads entries and renders unchanged; `tests/test_motif_browser.py` passes.
- [ ] The migration is idempotent — running `init_db()` twice does not double the entries.
