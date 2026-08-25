---
id: 9
title: "Decide the type of `detection.entropy`"
model: opus
size: S
blocked_by: [5, 8]
mutex: [5, 7]
files: ["Adapters/detection_entropy.py", "Working/types/windowset.py", "tests/test_analysis_modules.py"]
flags: ['done']
level: 3
unblocks: 1
budget_minutes: 30
---
# 09 — Decide the type of `detection.entropy`

**Model:** [O] · **Size:** [S]

**What to build:** a resolution for the one adapter that fits none of the seven types, recorded as a
decision rather than left as an inconsistency an examiner can find.

**Blocked by:** 05, 08

**Files/modules touched:** `Adapters/detection_entropy.py`; possibly `Working/types/windowset.py`
(read only); `tests/test_analysis_modules.py`; a short decision note in `docs/`.

**Merge risk:** **MEDIUM vs ticket 07** if the resolution makes entropy a per-window feature, since
that changes its `input_kind` to `WindowSet` and puts it in batch B's territory.

**Why [O]:** `detection.entropy` returns `AdapterResult(output_kind="encoding", encoding=float(value))`
— a single scalar for the whole span. That is neither an `Encoding` nor a `Scores` nor a `WindowSet`.
The PRD's rule is that a method not fitting the seven types is out of scope rather than a reason to add
an eighth, so the options are: attach it as a per-window feature column on a `WindowSet` (changing its
input type), or remove it from the chain system and keep it as a `Working/` function only. The thesis
plan already carries "entropy variants retain-or-drop justification needed" as an open item, so this
ticket closes both at once.

**Acceptance criteria:**
- [ ] One of the two resolutions is implemented, not both.
- [ ] If kept: `detection.entropy` declares `input_kind="WindowSet"`, `output_kind="WindowSet"`, and
      appends one named feature column per selected measure; a test asserts the column appears with one
      value per window.
- [ ] If dropped: the adapter file is removed from the registry, the underlying
      `Working/Detection/analysis/entropy_analysis.py` functions are untouched, and any test that
      registered it is updated rather than deleted.
- [ ] Either way, a short note in `docs/` states which was chosen and why, in terms an examiner reading
      the methods chapter would accept.
- [ ] No eighth interchange type is introduced.
