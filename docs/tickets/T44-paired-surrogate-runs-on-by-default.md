---
id: 44
title: "Paired surrogate runs, on by default"
model: opus
size: M
blocked_by: [24, 32, 33, 43]
mutex: [25, 31, 32, 33]
files: ["UI/workspaces/analyse/run_surface.py", "Working/compare.py", "Working/run_groups.py"]
flags: ['human-verify', 'done']
level: 10
unblocks: 2
budget_minutes: 60
---
# 44 — Paired surrogate runs, on by default

**Model:** [O] · **Size:** [M]

**What to build:** every result carries a null, because the control runs unless someone turns it off —
not because someone remembered to turn it on.

**Blocked by:** 24, 32, 33, 43

**Files/modules touched:** `Working/run_groups.py` (surrogate pairing);
`UI/workspaces/analyse/run_surface.py` (the toggle and the paired display); consumes
`Working/compare.py`.

**Merge risk:** **HIGH vs 33** — must consume ticket 33's overlap and counts computation, not write its
own side-by-side. **HIGH vs 31/32** (same file; sequence after both). **MEDIUM vs 25** — pairing must
use the existing fan-out mechanism.

**Why [O]:** default-on is the whole design, and the transience of the surrogate signal is what stops
surrogate-derived spans reaching the library. Both are easy to implement in a way that looks right and
is not.

**Acceptance criteria:**
- [ ] Every run carries a surrogate toggle that defaults to **on**.
- [ ] When on, a paired run executes the identical chain with the surrogate step prepended, linked to
      the original by `surrogate_of_run_id`.
- [ ] Results always display as detected-versus-surrogate counts — never as a bare detection count.
- [ ] The surrogate signal is transient and gets **no** `recordings` row. A test asserts that no
      `motif_entry` can be created from a surrogate run, because there is no recording to attach a span to.
- [ ] Turning the toggle off is recorded on the run, so a missing null is visible rather than absent.
- [ ] The comparison uses `Working/compare.py`; a test asserts there is exactly one overlap
      implementation in the repository.
