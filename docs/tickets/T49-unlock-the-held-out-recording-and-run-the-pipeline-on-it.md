---
id: 49
title: "Unlock the held-out recording and run the pipeline on it"
model: opus
size: S
blocked_by: [3, 48]
mutex: []
files: ["Working/config.py"]
flags: ['human-gate']
level: 12
unblocks: 0
budget_minutes: 30
---
# 49 — Unlock the held-out recording and run the pipeline on it

**Model:** [O] · **Size:** [S] — **human-gated, not an autonomous ticket**

**What to build:** the generalisation test, run once, after the freeze.

**Blocked by:** 03, 48

**Files/modules touched:** `Working/config.py` (unlock flag only). **No code changes.**

**Merge risk:** none.

**Acceptance criteria:**
- [ ] Performed only after the 28 August feature freeze, and only after ticket 48 is green.
- [ ] `M4_aug_concat_fs1.mat` channels are already materialised, so the run is a single action.
- [ ] The full pipeline runs over it once; the run group is exported.
- [ ] The unlock is recorded with a date, so the methods chapter can state when the holdout was opened.
- [ ] `M2_aug_concat_fs1.mat` and `M2_aug_concat_fs2.mat` are confirmed to be on the same side of every
      train/test split — they are the same recording at two sample rates, and splitting them leaks.

---

# Reading the backlog

**Startable on day one with no blockers:** 01, 02, 03, 17.

**Run ticket 17 first and alone.** It is the file split, it conflicts with every UI ticket, and it is
what converts the Analyse and Library work from a queue into a fan-out. Everything else in the UI half
of this backlog assumes it has landed.

**Three sequencing rules that the blocking graph does not express:**

1. `Working/execution.py` is edited by tickets 08, 15 and 24. Sequence 08 → 15 → 24. Never overlap.
2. `Working/database/schema.py` is edited by tickets 02 and 04. Sequence 02 → 04. Never overlap.
3. `Adapters/base.py` is frozen after ticket 05 and unfrozen only for ticket 10.

**Three single-owner rules:**

- The manifest schema is owned by ticket 27. Tickets 45 and 46 import it.
- The set-overlap computation is owned by ticket 33. Ticket 44 imports it.
- Library entry creation is owned by ticket 16. Tickets 23 and 37 call its helper.

**Tallies.** 49 tickets: 18 `[O]`, 31 `[S]`. One `[L]` (ticket 30, kept large deliberately), the rest
`[S]` or `[M]`. The `[O]` set is the four Panel surfaces with linked views, the constraint rebuild, the
executor cache, the two new adapters, the entropy decision, the type correction, the file split, the
cross-channel bins, the paired surrogates, the compare view and the templates.

**Cut-list tickets, in the order the PRD says to drop them:** 15 (step cache), 47 (templates — keep
JSON import/export), 42 (grouping selectors), and the UI half of 41 (run cross-channel as a script;
ticket 41's core is deliberately UI-free so this cut costs nothing). **Never cut:** 19 (adjudications),
44 (surrogate-by-default), 45 and 46 (the exporters).
