---
id: 45
title: "Run-group exporter"
model: sonnet
size: M
blocked_by: [19, 27]
mutex: [27, 46]
files: ["Working/export.py", "tests/test_export.py"]
flags: ['done']
level: 8
unblocks: 2
budget_minutes: 60
---
# 45 — Run-group exporter

**Model:** [S] · **Size:** [M]

**What to build:** a completed run group leaves the tool as a folder a thesis chapter can be written
from, without re-running anything.

**Blocked by:** 19, 27

**Files/modules touched:** new `Working/export.py`; `UI/workspaces/analyse/` (export action);
new `tests/test_export.py`.

**Merge risk:** **HIGH vs 27 and 46.** Import ticket 27's manifest writer; do not define a second
schema. 46 shares this module — sequence them.

**Acceptance criteria:**
- [ ] Exports a folder containing a manifest, a spans table as CSV, and copied plots.
- [ ] The manifest schema is ticket 27's, imported not restated.
- [ ] Covers recipe, config hash, per-run status and timings, detections with their adjudications,
      surrogate counts, artifact paths, code version and timestamps.
- [ ] **A null surrogate is stated explicitly rather than omitted**, so a missing control is visible in
      the export. A test asserts the field is present and explicitly null for an unpaired run.
- [ ] The CSV opens in a spreadsheet with one row per span and named columns — thesis tables come out
      of a spreadsheet, not a JSON blob.
