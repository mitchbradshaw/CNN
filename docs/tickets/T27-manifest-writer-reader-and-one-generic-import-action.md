---
id: 27
title: "Manifest writer, reader, and one generic import action"
model: sonnet
size: M
blocked_by: [24, 25]
mutex: [18, 45, 46]
files: ["Pipelines/import_mp_artifacts/import_mp_artifacts.py", "Pipelines/import_wm_artifacts/import_wm_artifacts.py", "Pipelines/run_recipe/run_recipe.py", "UI/admin.py", "Working/manifest.py", "tests/test_manifest.py"]
flags: []
level: 7
unblocks: 6
budget_minutes: 60
---
# 27 — Manifest writer, reader, and one generic import action

**Model:** [S] · **Size:** [M]

**What to build:** every headless run writes a manifest beside its artifacts, and one import action
reads any manifest back into the local database — replacing the two bespoke artifact importers.

**Blocked by:** 24, 25

**Files/modules touched:** new `Working/manifest.py`; `Pipelines/run_recipe/run_recipe.py` (always
write one); deletion of `Pipelines/import_mp_artifacts/import_mp_artifacts.py` and
`Pipelines/import_wm_artifacts/import_wm_artifacts.py`; `UI/admin.py` (import action); new
`tests/test_manifest.py`.

**Merge risk:** **HIGHEST SEMANTIC RISK IN THE BACKLOG — vs tickets 45 and 46.** All three serialise
runs and results, and the PRD is explicit that one writer and one reader serve import, export and
reproducibility. Three agents working in parallel will produce three schemas. **This ticket owns the
manifest schema outright; 45 and 46 are blocked by it and must import it.** Also **MEDIUM vs 18**
(the Admin mount point).

**Acceptance criteria:**
- [ ] The manifest carries: recipe, config hash, run status, step timings, detections, artifact paths,
      code version, and timestamps.
- [ ] `run_recipe.py` writes one beside its artifacts on every invocation, including failed runs.
- [ ] One import action reads any manifest at a matching relative path and writes the corresponding
      local rows.
- [ ] **Round-trip test:** write a manifest, import it into an empty database, and assert the
      reconstructed run rows match the original — including step timings and detection sample ranges.
- [ ] The two bespoke importers are deleted, not left beside the generic one.
- [ ] Importing the same manifest twice does not duplicate runs or detections.
- [ ] The manifest schema is defined in exactly one module, which tickets 45 and 46 import.
