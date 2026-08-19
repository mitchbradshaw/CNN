# Autonomous ticket runner

Dispatches the tickets in `docs/tickets/` to `claude -p` subprocesses — one git worktree each —
gates them, merges them into an integration branch, and leaves a trail you can audit over coffee.

The design, and the reasoning behind every decision in it, is `docs/ORCHESTRATOR_SPEC.md`. This file
is how to run the thing.

Python standard library only. No venv, no install step, no third-party dependency.

---

## The four commands

```powershell
python -m orchestrator.run --plan                     # print the schedule, dispatch nothing
python -m orchestrator.run --run                      # start a run
python -m orchestrator.run --resume runs/run-<stamp>  # reconcile against git and continue
python -m orchestrator.run --status runs/run-<stamp>  # print REPORT.md, change nothing
```

Useful flags: `--ceiling N` / `--opus-ceiling N` override the configured concurrency for one
invocation; `--label NAME` names the run directory; `--config PATH` points at a different
`config.toml`.

### Start with `--plan`

`--plan` runs the real scheduler over the real backlog and prints the wave-by-wave schedule without
touching git. It is the same code path the run uses, so it is evidence about the run rather than a
second implementation of it.

```
RUN PLAN — integration/run-20260815-2130  (ceiling 2, opus 1, stop 07:00)

wave 1     t+0h00   T01 sonnet M  60m  Seven interchange types with disk serialisat
                    T02 sonnet M  60m  Schema extension: new tables, new columns, u
                    T03 sonnet S  30m  Held-out recording lock
                    held: T17 (solo)
wave 3     t+2h00   T17 opus   M  60m  Split the two god-class UI modules into pack  [SOLO — runs alone]
                    held: T06 (solo), T07 (solo), T08 (solo), T13 (solo), T36 (solo)
...
projected drain 10.0 h · 27 tickets autonomous · 22 held
```

The first real run is a decision you make after reading that output. Nothing else triggers one.

---

## Before the first run

Four things, in order.

1. **Commit everything.** `git worktree add` materialises only *committed* files. Anything untracked
   — a skill, `pytest.ini`, a ticket edit — is invisible inside every agent's worktree, and the gates
   that depend on it fail open rather than closed. `--run` refuses to start on a dirty tree for
   exactly this reason.
2. **Check the reviewer resolves inside a worktree.** `.claude/skills/` is tracked in this repo
   specifically so it survives into worktrees. Verify with
   `git ls-files .claude/skills/code-review`.
3. **Rebuild the fixture database** with `python -m orchestrator.make_fixture`. It is written to
   `config.toml`'s `paths.fixture_db` (default `DATA/fixture/annotations.sqlite`) and copied — never
   linked — into every worktree. Provisioning refuses to continue without it rather than let an agent
   find the real database, and the builder now refuses to emit a row whose `.npy` is not on disk.

   That last check is not hypothetical. In run-20260817-1157 the channel directory named in
   `paths.recordings` was empty, so all 16 fixture rows pointed at files that did not exist. `UI/app.py`
   built a `ViewerApp` at import time, the load raised `FileNotFoundError`, and the ten test files
   that import the app package failed at *collection* — which aborts the whole pytest session. Every
   worktree ran zero tests all night while the suite gate reported green. Rebuild the fixture after
   any change to `paths.recordings`, after a schema migration, and any time `DATA/derived/channels/`
   has been cleared.

   **The import-time construction was removed on 2026-08-19** — the servable call moved to
   `UI/serve.py`, and `import UI.app` now defines the factory without calling it. That closes the
   *collection-failure* half of this story but not the fixture obligation: tests still read the
   database, and a fixture that has drifted from `schema.py` still fails them honestly.

   It also removed an alarm. A junction that was present but pointing at an *empty* directory used to
   be caught because `import UI.app` crashed at collection; now the import succeeds. The replacement
   is two-part: the 88 `_channel_available()` guards became real `pytest.skip` calls, so absent data
   shows up as skips rather than silent passes, and `capture_baseline` refuses to start when
   `paths.recordings` is configured but the baseline skipped more than 5% of the suite. The junction
   itself is kept — see `FOLLOWUPS.md` for the measurement that settled it.
4. **Measure the suite.** `pytest -q --durations=15`, twice — the first run pays the import cost for
   torch/kymatio/aeon. Under ~2 min the design holds as written; 2–8 min holds with a lower ceiling;
   over ~15 min the merge gate becomes the bottleneck and the policy needs revisiting.

The run captures its own baseline before dispatching anything, so a suite that is *already* red does
not quarantine innocent tickets. The failing set is written to `runs/<run>/baseline.txt`.

---

## What a run does

```
cut integration/run-<stamp> from main
capture the baseline failing set
loop until nothing is dispatchable:
    schedule()  →  worktree  →  claude -p  →  five gates  →  merge
```

`main` is never written. In the morning you review the integration branch as one diff and
fast-forward `main` yourself, or throw the night away with one `git branch -D`.

**Solo tickets drain the field.** Once a `solo` ticket is the top candidate, nothing new dispatches
until the in-flight tickets finish. Without this, T17 could only start on a tick where the field
happened to be empty *and* it happened to sort first — under jitter that lands it around t+7 h
instead of t+2 h, and it gates 26 tickets. `--plan` prints a drain wave so an idle stretch reads as
deliberate rather than hung.

### The five gates

| # | Gate | Failing it means |
|---|---|---|
| 1 | **Red proof** | The first commit must touch only `tests/`, and that test must actually fail when checked out. A test that never failed asserts nothing. |
| 2 | **Suite** | No regressions against the baseline. On red, the failing node ids are re-run **once** — pass means `FLAKY`, fail means quarantine. |
| 3 | **Scope** | Soft. Undeclared files are reported and appended to the review prompt, never blocked. |
| 4 | **Review** | Two-axis `code-review`, with the fixed point and the spec both passed explicitly. Blockers get one auto-fix round, then quarantine. Majors and minors merge and land in `FOLLOWUPS.md`. |
| 5 | **Overlap** | Two branches adding the same top-level symbol. The second is **held**, never auto-resolved. Private (`_`-prefixed) names count by default — see `overlap.include_private`. |

Severity is graded by the runner from the rule numbers in `docs/CODING_STANDARDS.md`, not by the
reviewer. A finding that cites no rule gets `minor` — a reviewer that will not cite a rule does not
get to stop a merge at 3am.

### When something goes wrong

**Quarantine** preserves the branch, marks the ticket `FAILED`, holds everything downstream as
`BLOCKED_UPSTREAM`, and continues with the rest of the DAG. It is a verdict on the ticket's *work*,
and only the gates produce it.

**Defer** is what happens when the environment, not the ticket, is the problem — a usage cap, a rate
limit, an API error. The ticket is marked `DEFERRED`: no circuit-breaker weight, no dependents held,
and its branch deleted if it carries no commits so the next dispatch can provision. Nothing was
judged, so nothing may be concluded. Deferred tickets are terminal for the night and re-queued at the
top of the next pass, which is what `--resume` is for.

The distinction is load-bearing. Until 2026-08-19 an infrastructure failure quarantined: in
`run-20260818-2244` four agents hit a plan usage cap, all four were quarantined, the breaker tripped
on the third, and a twenty-hour night ended at 23:00 having merged nothing.

**The circuit breaker** halts the run after three consecutive quarantines, or when more than 40% of
dispatched tickets are quarantined. That is the difference between "one ticket was wrong" and "the
base is broken and every agent is failing for the same reason". `FLAKY` marks count at half weight,
on their *own* streak — a flaky ticket merges, and a merge clears the quarantine streak, so sharing
one counter would let every flake erase its own contribution.

**Rate limiting is handled fleet-wide.** When the signature — fast exit, non-zero code, no commits —
appears on two or more agents, *all* dispatch pauses. Three agents each backing off independently is
three agents discovering the same closed door.

How long it pauses depends on whether anything told it. A plan usage cap prints its own reset time
(`You're out of extra usage · resets 3:30am`); the runner reads that and waits for it, bounded by
`rate_limit.max_usage_wait_seconds` (6h). Where nothing names a time, it falls back to blind
exponential backoff bounded by `max_backoff_seconds` (15m) — small on purpose, because a guess should
not cost hours.

---

## Reading the results

```
runs/<label>-<timestamp>/
  REPORT.md          one table row per ticket — read this first
  plan.md            the plan as printed at launch
  state.json         the DAG state, rewritten atomically on every transition
  baseline.txt       tests already failing before any ticket ran
  T17/
    transcript-1.log  the agent session (one per attempt)
    red-proof.txt     test output at the test-only commit
    suite.txt         the suite on the branch, plus any re-run
    post-merge.txt    the suite after merging
    review.json       structured findings, graded
    review-1.md       the reviewer's prose
    scope.txt         files touched vs files declared
    overlap.txt       symbols added, and any collision
    diff.patch
```

You open a ticket directory only for the rows that are red.

Git is the ledger. `git log --merges --oneline <integration branch>` is the landing order;
`git revert -m 1 <sha>` removes exactly one ticket's work, which is why every merge is `--no-ff`.

---

## Resuming

Kill it and restart it. `--resume` reconciles **against git, not against `state.json`** — every
ticket that was mid-flight is stale by definition, so each is re-derived:

| Git says | Action |
|---|---|
| A merge commit names the branch tip | `MERGED` — or `MERGING` again if the post-merge suite never ran |
| Branch has unmerged commits | Resume at the gates; the agent is **not** re-dispatched |
| Branch exists with no commits | Delete it, back to `READY` |
| No branch | Back to `READY` |

Nothing is ever re-dispatched on the strength of a `state.json` field alone.

---

## Configuration

Everything tuneable is in `config.toml` — ceilings, budgets, the wall-clock stop, model ids, paths,
retry counts, circuit-breaker thresholds, rate-limit backoff. Nothing is hardcoded, and a missing
section is an error rather than a default.

The file's hash is recorded in `state.json`, so a resumed run tells you if the configuration moved
under it.

Two settings are load-bearing and should not be changed casually:

- `suite.command` must never include `-n`. `tests/_session_isolation.py` documents exactly why
  parallel collection breaks this suite.
- `review.blocking_severities` is what makes the merge gate asymmetric. A style finding that blocks a
  merge overnight also blocks every dependent ticket, and that cost is measured in milestones.

---

## The runner's own tests

```powershell
pytest orchestrator/tests
```

228 tests, a little over three minutes. They live outside `tests/` deliberately: the ticket suite is
the baseline every gate compares against, and the runner's tests must not enter it.

Every test that touches git builds a disposable repository under `tmp_path`, and every test that
needs an agent drives a fake CLI. Nothing in the suite launches a real agent, and nothing writes to
this repository.
