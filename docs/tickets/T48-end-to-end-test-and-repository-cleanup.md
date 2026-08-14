---
id: 48
title: "End-to-end test and repository cleanup"
model: sonnet
size: M
blocked_by: [23, 27, 36, 44, 45]
mutex: []
files: ["README.md", "UI/README.md", "Working/README.md", "tests/test_end_to_end.py"]
flags: []
level: 11
unblocks: 1
budget_minutes: 60
---
# 48 — End-to-end test and repository cleanup

**Model:** [S] · **Size:** [M]

**What to build:** one test that walks the whole claim — synthetic signal to exported manifest — plus
the cleanup that makes the repository submittable.

**Blocked by:** 23, 27, 36, 44, 45

**Files/modules touched:** new `tests/test_end_to_end.py`; `README.md`; `UI/README.md`;
`Working/README.md`; dead-code removal across the tree.

**Merge risk:** **LOW, but run it last against a fully merged `main`** — its entire purpose is to catch
what the per-ticket merges did not.

**Acceptance criteria:**
- [ ] A synthetic signal runs through a three-step chain, a detection is adjudicated, the candidate is
      promoted to the library, and the run group is exported — in one test.
- [ ] The exported manifest's recipe hash equals the run's recipe hash.
- [ ] All 195 existing tests pass, plus everything added across milestones 1–5.
- [ ] `discover_adapters()` registers the expected count — no adapter is silently skipped by a broken
      optional dependency.
- [ ] The READMEs describe the four workspaces, the seven types and the manifest format.
- [ ] The two bespoke importers, the legacy output-kind vocabulary and any superseded motif path are
      gone from the tree, not merely unused.
