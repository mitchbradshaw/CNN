---
id: 67
title: "Name a run"
model: sonnet
size: M
blocked_by: []
mutex: [52]
files: ["Working/database/schema.py", "Working/database/runs.py", "UI/workspaces/analyse/history.py", "tests/test_database.py", "tests/test_run_groups.py"]
flags: ['done']
level: 0
unblocks: 1
budget_minutes: 60
---
# 67 — Name a run

**Model:** [S] · **Size:** [M]

**What to build:** A run carries a name the researcher chooses, so runs can be told apart without
memorising integers.

Right now every run is an autoincrementing id. The Compare view offers "#12 —
recording 49" against "#31 — recording 385", with nowhere to record that one was
the tuned lowpass and the other the raw comparison.

The runs table gains a nullable name column through the existing additive column
migration — `PRAGMA table_info` first, add only what is missing, `init_db()` stays
idempotent. The name is editable in the run history table, and shown wherever a run
id is shown.

**A surrogate run inherits its parent's name**, marked as the surrogate. Surrogate
pairing is on by default, so every launch already produces two runs; naming one and
leaving the other anonymous would read as a defect rather than a design.

**The name is a label, never an identifier.** Nothing keys on it, nothing enforces
uniqueness, and the recipe hash remains the identity of a run's content. Two runs
may share a name; that is the researcher's business.

**Blocked by:** nothing — can start immediately

**Files/modules touched:** `Working/database/schema.py`, `Working/database/runs.py`, `UI/workspaces/analyse/history.py`, `tests/test_database.py`, `tests/test_run_groups.py`.

**Merge risk:** **MEDIUM.** `Working/database/schema.py` is shared with T52, which adds a
column to a different table — mutually exclusive, either order. Follow the additive
migration pattern; nothing here justifies a table rebuild.

**Acceptance criteria:**
- [ ] The runs table carries a nullable name column, added by the existing additive migration.
- [ ] `init_db()` stays idempotent and an older database gains the column on next init.
- [ ] A run's name is editable from the run history table and persists.
- [ ] A surrogate run inherits its parent's name, marked as the surrogate.
- [ ] The name is displayed wherever the run id is displayed.
- [ ] Nothing keys on the name and no uniqueness constraint is added.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
