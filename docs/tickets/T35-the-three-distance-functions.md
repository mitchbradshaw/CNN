---
id: 35
title: "The three distance functions"
model: sonnet
size: M
blocked_by: [1]
mutex: [41]
files: ["Working/distances.py", "tests/test_distances.py"]
flags: []
level: 1
unblocks: 9
budget_minutes: 60
---
# 35 — The three distance functions

**Model:** [S] · **Size:** [M]

**What to build:** three named ways to say two spans are the same shape, each recordable on the edge it
produces, so scale-invariance becomes testable rather than assumed.

**Blocked by:** 01

**Files/modules touched:** new `Working/distances.py`; new `tests/test_distances.py`.

**Merge risk:** **NAMING — do not put these in `Working/database/similarity.py`.** That module computes
interval IoU for duplicate-annotation warnings and is a different concept entirely. **MEDIUM vs ticket
41**, which needs correlation and z-normalisation helpers: this ticket owns them, 41 imports them.

**Acceptance criteria:**
- [ ] A scale-invariant distance: resample both spans to a common length, z-normalise, Euclidean.
- [ ] A symbolic distance: SAX minimum-distance at a fixed word length, reusing the existing SAX ports
      rather than reimplementing PAA.
- [ ] A native-length z-normalised distance as the unnormalised control.
- [ ] Each is a named constant recorded on the edge, not an anonymous callable.
- [ ] **The test that matters:** a pair identical in shape but differing in duration is near-zero under
      the scale-invariant distance and large under the control.
- [ ] Each distance is asserted against at least one hand-computed case.
- [ ] Elastic distances are not implemented — explicitly out of scope.
