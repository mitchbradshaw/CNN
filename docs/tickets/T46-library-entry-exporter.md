---
id: 46
title: "Library-entry exporter"
model: sonnet
size: M
blocked_by: [27, 36, 41]
mutex: [27, 36, 45]
files: ["UI/workspaces/library/detail.py", "Working/export.py", "tests/test_export.py"]
flags: ['done']
level: 8
unblocks: 0
budget_minutes: 60
---
# 46 — Library-entry exporter

**Model:** [S] · **Size:** [M]

**What to build:** a motif family leaves the tool as a table, so recurrence can be reported rather than
described.

**Blocked by:** 27, 36, 41

**Files/modules touched:** `Working/export.py` (same module as 45 — sequential);
`UI/workspaces/library/detail.py` (export action); `tests/test_export.py`.

**Merge risk:** **HIGH vs 45** (same module) and **HIGH vs 27** (manifest schema). Sequence after both.

**Acceptance criteria:**
- [ ] Exports a folder containing a manifest, a CSV, and copied plots.
- [ ] Covers exemplar, members with their edges and distances, scope by recording and channel,
      cross-channel bins, tags, and the recipe behind each edge.
- [ ] Members classified as `artifact` are present in the export and marked, not silently dropped.
- [ ] The manifest schema is ticket 27's.
- [ ] The code version that produced the export is recorded, so a result traces to a repository state.
