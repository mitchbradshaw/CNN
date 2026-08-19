# Ticket runner — status and handover

**Updated:** Wednesday 19 August 2026. **Feature freeze: 28 August — 9 days, with a couple of days'
slack accepted deliberately to make the runner reliable first.**

Written so a fresh session can pick up without re-reading the design conversation. If you are
debugging the runner, read this, then `docs/ORCHESTRATOR_SPEC.md`. Do not read the ticket backlog.

---

## What exists

An autonomous ticket runner that dispatches the 49-ticket Pipeline GUI backlog to `claude -p`
subprocesses, one git worktree each, gates their work, and merges it into a disposable integration
branch. `main` is never written by the runner.

- **`orchestrator/`** — ~6,900 lines, 316 tests passing. Stdlib only, deterministic. No LLM makes a
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

**Eight tickets done of 49** — T01, T02, T04, T05, T13, T17, T28, T35. T04 and T17 were worked by
hand; the rest landed through the runner. **41 remain, one of them (T49) human-gated.** T04 landing
released 20 downstream tickets, so the DAG is now wide rather than bottlenecked.

**Seven runs so far, five of them with working gates. 17 dispatched, 5 merged.** That headline 29% is
misleading: sorted by cause, only **2 of the 17 were genuine ticket failures**. Ten were harness bugs,
and every run has fixed a different one.

| Run | Dispatched | Merged | Losses |
|---|---|---|---|
| 1157 | 3 | 1 | judgement→blocker *(fixed)*, one genuine |
| 2050 | 3 | 1 | judgement→blocker *(fixed)*, stall handling *(fixed)* |
| 0554 | 3 | 2 | overlap boilerplate *(fixed)* |
| 1114 | 4 | 1 | dirty red-proof ×2 *(fixed)*, one genuine |
| 2244 | 4 | 0 | usage exhaustion ×4 *(fixed 2026-08-19)* |

**The 2026-08-19 work (`fix/runner-usage-resilience`) closed the class of failure that made unattended
running impossible.** Full detail in `FOLLOWUPS.md`; the short version:

- An infrastructure failure no longer quarantines. It defers — no breaker weight, no blocked
  dependents, empty branch cleaned up — and `--resume` re-queues it.
- The runner reads `resets 3:30am` out of the transcript and pauses the fleet until then.
- Token and cost accounting exists at last: `REPORT.md` has `tokens` and `cost` columns and a run
  total that separates spend that landed from spend that did not.
- `ceilings.concurrent` 3 → 2, because concurrency concentrates token spend rather than reducing it.
- The Opus sub-ceiling now counts effective tiers, not declared ones — worth 1.5h of drain on its own.
- `UI/app.py` no longer builds the application at import; `panel serve UI/serve.py` is the command.

**Projected drain is 19h at ceiling 2** against a ~20h dispatch window, so the remaining 40
autonomous tickets fit one full night *if nothing fails*. Plan for two.

## How to run a night

```powershell
python -m orchestrator.run --plan                 # schedule only, dispatches nothing
python -m orchestrator.run --run                  # start
python -m orchestrator.run --status runs/run-<stamp>
python -m orchestrator.run --resume runs/run-<stamp>   # after a usage window reopens
```

Before starting, every time:

1. **`git worktree prune`** and delete any leftover `ticket/T*` branches. `provision()` uses
   `git worktree add -b`, which fails outright against an existing branch. A deferred ticket now
   cleans up its own empty branch, but a *quarantined* one deliberately keeps its branch as evidence.
2. **`python -m orchestrator.make_fixture`** if any ticket since the last run touched `schema.py`.
   Standing obligation — T16 is the remaining schema ticket.
3. **Check you are on `main`**, not on a leftover integration branch.
4. **`--plan` first** and read the wave list before committing a night to it.

In the morning: read `REPORT.md`. `DEFERRED` rows mean rerun; `FAILED` rows mean read the transcript.
Then triage the post-mortem stub the runner appended to `FOLLOWUPS.md` — it names every ticket that
cost tokens and did not land, and the diagnosis line is deliberately left empty for you.

## Known open items

- **The 88 `_channel_available()` guards `print` and `return` rather than skip.** A test that returns
  early reports as *passed*. This is now the single highest-value open item: it is the only thing
  standing between this repo and dropping `paths.recordings` entirely, which would close the
  writable-recordings isolation tradeoff. **Fix the guards first, then drop the junction** — the other
  order makes a large part of the suite vacuously green.
- **`UI/window_matrix_panel.py` leaks background `_worker` threads** that outlive their test and touch
  SQLite from the wrong thread. Passes 20/20 in isolation, fails inside the full suite. Needs a ticket.
- **`agent.output_format = "stream-json"` has not met the real CLI.** The parsers degrade safely — an
  unrecognised schema costs the cost column and nothing else — but check `REPORT.md` has a populated
  `tokens` column after the first real run before trusting the numbers.
- **T14 and T08 were both innocent losses** in run-20260818-1114 and are still open. T14's red-proof
  failure was the dirty-worktree bug; T08's suite failure looks genuine but it was also running into a
  closing usage window. Re-dispatch both before concluding anything.
- **`docs/RUNNER_FIX_PROMPT.md` carries a superseded root cause.** Still true. Add a correction header
  or delete it.

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
- **Fixing the label is not fixing the bug.** `out of extra usage` was added to
  `INFRASTRUCTURE_MARKERS` on 2026-08-19, which made the classification correct and changed the
  outcome not at all: the run loop still quarantined on an `infrastructure` verdict. A test asserted
  the classifier and nothing asserted what the caller did with it. When a defect is diagnosed, test
  the *consequence*, not the diagnosis.
- **Concurrency does not save a token budget, it concentrates it.** Three agents for an hour cost the
  same as one for three hours; only the first shape overruns a rolling usage window, and when it does
  it takes every in-flight ticket down together.
- **An untuned knob is not a safe knob.** The Opus sub-ceiling had been throttling 19 tickets against
  a cost nobody was paying since `model_cap` was introduced, because it counted the tier the ticket
  *declared* rather than the one it would run on. Nothing failed; the night was just quietly 1.5 hours
  longer.
- **A duplicated dataclass is a silent divergence.** `Ceilings` existed in both `config.py` and
  `scheduler.py`; the runtime used one and the tests exercised the other, so a new field was invisible
  through the half nobody looked at.
- **Stale tests fail the wrong way.** Four planner assertions pinned T04 as the bottleneck and broke
  with a `KeyError` the day T04 landed. A test that hardcodes a snapshot of the backlog stops testing
  the planner and starts testing the calendar — derive from the backlog instead.
