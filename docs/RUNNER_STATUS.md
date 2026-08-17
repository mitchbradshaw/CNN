# Ticket runner — status and handover

**Updated:** Monday 17 August 2026, ~09:30 Brisbane. **Feature freeze: 28 August — 11 days.**

Written so a fresh session can pick up without re-reading the design conversation. If you are
debugging the runner, read this, then `docs/ORCHESTRATOR_SPEC.md`. Do not read the ticket backlog.

---

## What exists

An autonomous ticket runner that dispatches the 49-ticket Pipeline GUI backlog to `claude -p`
subprocesses, one git worktree each, gates their work, and merges it into a disposable integration
branch. `main` is never written by the runner.

- **`orchestrator/`** — ~6,300 lines, 239 tests passing. Stdlib only, deterministic. No LLM makes a
  scheduling, merge, or conflict decision.
- **`docs/ORCHESTRATOR_SPEC.md`** — the settled architecture and failure policy. Appendix A is the
  `state.json` schema, Appendix B the pre-flight checks. Decisions in it are settled; implement,
  don't re-litigate.
- **`docs/tickets/`** — 49 ticket files with YAML front-matter (`blocked_by`, `mutex`, `files`,
  `flags`, `level`, `unblocks`, `budget_minutes`) plus `README.md` carrying the DAG, the 18 live
  mutex pairs, and the dispatch order.
- **`docs/CODING_STANDARDS.md`** — the Standards-axis authority for the review gate, with per-rule
  severities (`blocker` / `major` / `minor`).
- **`CLAUDE.md`** — repo context loaded for every ticket agent.

Run it from the repo root in PowerShell, conda env active — it is a terminal command, not a chat:

```powershell
python -m orchestrator.run --plan     # print the schedule, dispatch nothing
python -m orchestrator.run --run      # start a run
python -m orchestrator.run --resume runs/run-<stamp>
python -m orchestrator.run --status runs/run-<stamp>
```

## Where things stand

**Run 1 (`runs/run-20260816-1943`) failed for harness reasons and was stopped.** T01 was quarantined
after passing its red-proof gate, which cascaded 36 tickets to `BLOCKED_UPSTREAM`. The ticket was
innocent: `UI/app.py:2279` executes `create_app().servable(...)` at module import, so importing
`UI.app` constructs the whole application, reads the default database, and mmaps a real channel
`.npy`. In a worktree without that data, the ten test files that import `UI.app` fail at *collection*
— before their `_channel_available()` skip guards can run. The baseline had been measured in the main
repo, which has the data, so every collection error read as a regression.

**Five defects were found and fixed** (239 tests, was 228):

| | |
|---|---|
| Baseline measured in the main repo | `capture_baseline` now provisions a throwaway worktree, runs there, tears it down. Raises `BaselineError` and refuses the run if it can't provision. |
| Junction placed at `<wt>/<basename>` | Now preserves the source's path relative to the repo root. |
| `recordings = []` | Now `["DATA/derived/channels/M2_aug_concat_fs1"]` — 317 MB, verified the minimum that makes `import UI.app` succeed. |
| Fixture DB was a byte-identical copy of the real 11,266-row database | Now 126,976 bytes: 16 recording rows, 0 annotations. Built reproducibly by `orchestrator/make_fixture.py`. |
| `teardown()` only scanned immediate children | A repo-root-relative junction sits four levels down, so teardown deleted the sentinel in testing — it would have destroyed 317 MB of real derived data on the first teardown. Now recurses manually, checking for a reparse point *before* descending (`os.walk` traverses Windows junctions even with `followlinks=False`). |

**Baseline now passes green in 348 s, measured inside a provisioned worktree.** Negative control
confirmed the acceptance test has teeth: `rc=1` without the junction, `rc=0` with it.

## Immediate next steps

1. **Get off the integration branch.** The main working tree is checked out on
   `integration/run-20260816-1943`, not `main` (both at `7d90a42`). Commit now and the fixes land on
   a branch that is about to be deleted.
2. **Commit and merge.** Branch `fix/runner-provisioning` off `main`, commit the eleven changed and
   untracked files, merge back with `--no-ff`, push (local `main` is ahead of `origin/main`).
3. **Delete the stale branches — this is a hard prerequisite, not tidying.** `ticket/T01`,
   `ticket/T02`, `ticket/T03` still exist. `provision()` calls `git worktree add -b ticket/T01`,
   which fails when the branch exists, so run 2 dies on its first three dispatches. Also
   `git worktree prune` (T02 and T03 are registered `prunable`) and delete
   `integration/run-20260816-1943`.
4. **`--plan`**, confirm it still renders eight waves with a drain wave before T17 and T04/T49 in the
   not-dispatched list, then **`--run`**.

## Known open items

- **`UI/app.py:2279` module-level `create_app()`** — recorded in `FOLLOWUPS.md`, not yet a ticket.
  This is the root cause of run 1 and it is application code, out of scope for harness work. Fixing
  it would let the `recordings` junction be dropped entirely, closing the isolation tradeoff rather
  than merely recording it. Promote to a ticket at triage — deliberately *not* in `docs/tickets/`,
  because the backlog loader would dispatch it unreviewed on the next run.
- **`UI/window_matrix_panel.py` leaks a background `_worker` thread** that outlives its test and
  touches SQLite from the wrong thread. Signature: passes 20/20 in isolation, fails inside the full
  suite. This is the flake the gate-2 flake amendment absorbs. Needs its own ticket.
- **Ticket 04 is the backlog's bottleneck.** `human-gate`, never dispatched, and 20 tickets sit
  downstream of it including T18, which gates the whole UI half. Run 2 will drain to ~27 of 49 and
  stall there. `docs/T04_MANUAL_PROMPT.md` is the supervised prompt; it must be done by hand, after
  T02 has merged, and it is the single highest-leverage manual action available.
- **`docs/RUNNER_FIX_PROMPT.md` carries a superseded root cause.** Add a two-line correction header
  before committing, or delete it.
- **Isolation tradeoff accepted:** agents can now reach and write to real derived channel data
  through the junction. The annotation database is still protected. Recorded in
  `ORCHESTRATOR_SPEC.md` §Isolation and inline in `config.toml`; widening `recordings` re-opens it.

## Operating lessons, dearly bought

- **Worktrees materialise only committed files.** Anything untracked — skills, `pytest.ini`, ticket
  edits — is invisible to every agent, and the gates that depend on it fail *open*.
- **Measure the baseline where the agents live.** A baseline from the main repo describes a world no
  agent inhabits.
- **A safety test that passes first try is suspect.** The teardown test failed red, which is why it
  was worth having; the acceptance test passed first try and needed a negative control before it
  could be believed.
- **Don't run `git` through the Cowork device bridge** — it cannot delete files, so every invocation
  leaves a `.git/index.lock` behind. Use `git --no-optional-locks status` for read-only inspection.
