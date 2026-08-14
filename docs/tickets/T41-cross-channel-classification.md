---
id: 41
title: "Cross-channel classification"
model: opus
size: M
blocked_by: [36]
mutex: [35, 36]
files: ["UI/workspaces/library/detail.py", "Working/cross_channel.py", "Working/library.py", "tests/test_cross_channel.py"]
flags: []
level: 3
unblocks: 1
budget_minutes: 60
---
# 41 — Cross-channel classification

**Model:** [O] · **Size:** [M]

**What to build:** separating a shared-ground recording artifact from a real network event, before
anything is counted — the control the recurrence claim rests on.

**Blocked by:** 36

**Files/modules touched:** new `Working/cross_channel.py`; `Working/library.py` (edge update);
`UI/workspaces/library/detail.py` (the action); new `tests/test_cross_channel.py`.

**Merge risk:** **MEDIUM vs 35** (correlation and z-normalisation helpers — import, do not rewrite) and
**MEDIUM vs 36** (edge writes — call the writer). **This is a library-level action, not a block** — it
must not grow an adapter, because the univariate `Signal` type deliberately cannot express
multi-channel input and because the classification is a statement about a family, not about a signal.

**Why [O]:** the bin boundaries — "near-zero lag", "near-identical waveform", "small consistent lag",
"scattered across long intervals" — are judgement calls a spec cannot fully pin down, and they are
load-bearing for a research claim.

**Acceptance criteria:**
- [ ] For each member pair on different channels of one recording, inter-channel lag comes from the
      cross-correlation peak and waveform identity from the correlation at that lag.
- [ ] Each pair classifies into exactly one of `artifact`, `propagation`, `independent_recurrence`,
      persisted on the edge.
- [ ] The thresholds separating the bins are named configuration values, not literals in the function.
- [ ] The `artifact` bin is excluded from recurrence counts wherever counts are reported.
- [ ] **The test to insist on:** a synthetic pair with a known injected lag and a known waveform
      relationship classifies into the expected bin — one case per bin. Without this, a bug here is
      indistinguishable from a research finding, and it is precisely the finding an examiner will attack.
- [ ] The module imports no UI library, so it can also be run as a script if the UI action is cut.
