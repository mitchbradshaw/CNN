---
id: 3
title: "Held-out recording lock"
model: haiku
size: S
blocked_by: []
mutex: [8, 15, 17]
files: ["UI/app.py", "Working/config.py", "Working/execution.py", "tests/test_heldout_lock.py"]
flags: ['done']
level: 0
unblocks: 1
budget_minutes: 30
---
# 03 — Held-out recording lock

**Model:** [H] · **Size:** [S]

**What to build:** the evaluation recording is refused by both the viewer and the runner unless
explicitly unlocked, so "untouched until the freeze" is true by construction rather than by memory.

**Blocked by:** None — can start immediately.

**Files/modules touched:** `Working/config.py` (held-out name and unlock flag); `Working/execution.py`
(guard at the top of `execute_recipe`); `UI/app.py` (guard in recording selection); new
`tests/test_heldout_lock.py`.

**Merge risk:** **LOW but touches two hot files.** Its `execution.py` edit sits beside ticket 08's
dispatch rewrite and ticket 15's cache insertion; its `app.py` edit sits beside ticket 17's file split.
Small diff — land it in the first day so it is already in `main` when those start.

**Acceptance criteria:**
- [ ] `M4_aug_concat_fs1.mat` is named in `Working/config.py`, not hardcoded at a call site.
- [ ] `execute_recipe` raises a named exception with a clear message when the recipe's recording
      resolves to the held-out source file and the unlock flag is not set.
- [ ] The viewer refuses to load the held-out recording under the same condition.
- [ ] Both permit it when the unlock flag is set.
- [ ] A test asserts refusal, asserts the unlock path works, and asserts the guard reads the config
      value rather than a literal.
- [ ] The lock keys on source file, so every materialised channel of the held-out recording is covered
      by one config entry.
