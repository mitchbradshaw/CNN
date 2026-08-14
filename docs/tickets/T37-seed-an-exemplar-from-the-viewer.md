---
id: 37
title: "Seed an exemplar from the viewer"
model: sonnet
size: S
blocked_by: [16, 18]
mutex: [16, 23]
files: []
flags: ['human-verify']
level: 3
unblocks: 0
budget_minutes: 30
---
# 37 — Seed an exemplar from the viewer

**Model:** [S] · **Size:** [S]

**What to build:** a shape recognised by eye anchors a library entry without any algorithm having
proposed it — the case the detection-keyed schema could not express.

**Blocked by:** 16, 18

**Files/modules touched:** `UI/workspaces/explore/` (annotation action); calls ticket 16's
entry-creation helper.

**Merge risk:** **HIGH vs 16 and 23** — three entry-creation paths. Call the shared helper; do not
insert directly.

**Acceptance criteria:**
- [ ] Marking a span as `seed` in Explore creates a `motif_entry` with no detection pointer.
- [ ] The annotation row and the entry are separate objects — a test asserts both exist and that the
      entry is not an annotation.
- [ ] The entry appears in the library immediately.
- [ ] The `seed` verdict uses ticket 04's shared vocabulary constant.
