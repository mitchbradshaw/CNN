# Autonomous ticket runner — architecture and failure policy

**Status:** settled by grilling, 14–15 Aug 2026. No implementation written yet.
**Scope:** the system that dispatches the 49 tickets in `docs/tickets/` to autonomous coding agents,
merges their work, and leaves a trail auditable the next morning.

---

## Problem

49 tickets, 13 levels deep, 14 days to feature freeze. The work is parallelisable but only under
constraints the blocking graph alone does not express. Runs happen overnight and unattended, so every
decision the system makes at 3am must be either deterministic or deferred to the morning — never
improvised.

The failure to design against is not "a ticket failed". It is waking up to twelve broken branches and
no way to tell which one broke first.

---

## Architecture

### The orchestrator is not an LLM

A deterministic Python script owns the DAG, scheduling, git, and the merge. Agents are subprocesses
(`claude -p`, bypass permissions) that see one worktree and one ticket. Every non-deterministic
decision is either inside a sandboxed agent or in the morning queue.

An LLM orchestrator can decide at 3am to resolve a conflict, rewrite a ticket, or skip a blocker, and
the next morning its judgement is indistinguishable from a bug. A deterministic scheduler fails one
way: it stopped, and the log says where. It is also trivially resumable — kill it, restart it, it
reads `state.json` and continues.

### Where the work happens

**One persistent local clone for the whole ticketing period**, at `C:\Users\mmebr\Documents\CNN`.
`DATA/` and `MODELS/` are copied across once by file copy (they are gitignored). Every worktree, every
merge and every integration branch lives there for the duration.

The Google Drive copy is retired, not synchronised. It is renamed `CNN_ARCHIVE_pre_ticketing` so it
cannot be opened by muscle memory. `origin` on GitHub is and always was the backup; Drive was
providing nothing the remote does not, while putting a sync daemon in the path of every `.git/index`
write. Two live copies of one repo, one of them stale, is a worse failure than the one being avoided.

### Isolation

One `git worktree` per in-flight ticket, cut from the run's integration branch. Worktrees share the
object store and cost nothing to create.

Provisioning per worktree, before the agent starts:

- A copy of a **small purpose-built fixture database** — never the real one. An agent that cannot
  reach the 11,000-row database also cannot damage it. The only ticket that genuinely needs the real
  database is 04, which is human-gated anyway.
- Directory **junctions** (`mklink /J`) to the shared read-only recording directories for tickets that
  declare they need real data. `.git/config` has `symlinks = false`; junctions are unaffected.
- The **conda environment is shared**. Dependency changes are not an autonomous action.

`SESSION_STATE_PATH` resolves relative to cwd, so per-worktree UI session state isolates correctly
provided each agent's cwd is its own worktree.

### Branching and merge authority

The run cuts an integration branch from `main`. Tickets branch from the integration branch and
**auto-merge back into it**. `main` is never written by the runner.

This is what makes auto-merge safe. Deferring merges to a human queue would be safer per-merge and
catastrophic overall: every ticket with a blocker would idle overnight and the DAG would collapse to
its root layer. Auto-merging into a branch you can delete costs nothing to be wrong about.

A ticket has **landed** — and its dependents become dispatchable — when its branch has merged into the
integration branch *and the full suite is green after the merge*. Dependents therefore always cut from
a base containing their blockers' work.

**All merges are `--no-ff`.** This is not a preference. A merge commit per ticket is what makes
`git revert -m 1 <sha>` remove exactly one ticket's work, and what makes `git log --merges` the
landing order. A fast-forward merge would destroy the per-ticket auditability that is the entire point.

In the morning you review the integration branch as one diff and fast-forward `main` yourself, or
throw the night away with one `git branch -D`.

---

## Scheduling

### Constraints, in priority order

1. **Blocking edges.** A ticket dispatches only when every blocker has landed.
2. **Mutexes.** Every declared merge-risk pair is a mutual exclusion — never both in flight at once.
   Not an ordering constraint; just not simultaneous. 18 of the 64 declared pairs are not already
   ordered by a blocking edge and would otherwise be dispatched concurrently, including `16 ↔ 17` (the
   file split against four edits to the class it is dismantling) and `45 ↔ 46` (two exporters, same
   module, same level). The full list is in `docs/tickets/README.md`.
3. **Solo.** Ticket 17 runs alone; nothing else is in flight while it does.
4. **Ceilings.** Global 3 concurrent agents; Opus sub-ceiling 2.
5. **Human gates.** Tickets flagged `human-gate` are never dispatched.

The ceilings are configuration, not constants. The real limits are token throughput, the superlinear
growth of conflict probability with in-flight branches, and morning review bandwidth — not CPU.

### Ordering when more tickets are ready than the ceiling allows

**Most-unblocking first** — descending count of transitive dependents — tie-broken by critical-path
length, then by ticket id for determinism. On this backlog that opens with 01, 02, 03, then 05, 35, 16,
which is what the backlog's own reading section advises, arrived at mechanically.

### Run scoping

Run the **whole DAG** under a wall-clock stop, not milestone by milestone. The milestone labels do not
match the dependency structure — ticket 35 (Milestone 4) is runnable at level 1 and ticket 43
(Milestone 5) at level 3, long before Milestone 2 finishes. Batching by label would idle the machine
waiting on nothing.

After the wall-clock deadline the orchestrator starts no new tickets and lets in-flight ones finish.

### Run-plan preview

`orchestrator/run.py --plan` prints the schedule **without dispatching anything**, and the same
preview is written to the run directory and printed at launch. It exists so that the plan is
inspectable before you go to bed rather than reconstructable afterwards.

It reports, per wave: which tickets start concurrently, on which model, at what size and budget, what
each is blocked on, which mutex held a ready ticket back, and the projected wall-clock. It ends with
the tickets that will **not** run and why — `human-gate`, or held downstream of one.

```
RUN PLAN — integration/run-20260815  (ceiling 3, opus 2, stop 07:00)

wave 1   t+0h00   T01 sonnet M 60m  seven interchange types
                  T02 sonnet M 60m  schema extension
                  T03 sonnet S 30m  held-out lock
wave 2   t+1h00   T05 sonnet M 60m  adapter spec expansion      (was blocked by T01)
                  T35 sonnet M 60m  three distance functions    (was blocked by T01)
                  T16 opus   M 60m  shape-first library
wave 3   t+2h00   T17 opus   M 60m  split god-class UI modules  [SOLO — runs alone]
                                    held: T13, T36, T06 (ceiling), T04 (human-gate)
...
projected drain 10.2 h · 27 tickets autonomous · 22 held

NOT DISPATCHED
  T04  human-gate   verdict-constraint rebuild — 11k-row table rebuild
  T49  human-gate   unlock held-out recording
  20 further tickets held downstream of T04 (see below)
```

---

## Failure policy

Four classes. They are handled differently because they are different events.

| Class | Signature | Policy |
|---|---|---|
| **Infrastructure** | API error, rate limit, worktree creation failed, env broken | Exponential backoff, up to 3 retries. Does not count against the ticket. |
| **Stall** | No tool call or no commit for N minutes, or the wall-clock budget exceeded | Kill. One retry from a clean worktree with the previous transcript tail injected. Then quarantine. |
| **Red at exit** | Agent finished; suite is failing, or an existing test regressed | **No retry.** Quarantine immediately. A second blind attempt at a ticket the agent already believes it finished produces a second wrong answer and burns an hour. |
| **Review-rejected** | Tests green, review returned blockers | See below. |

**Quarantine** means: branch preserved, not merged, ticket marked `FAILED`, everything blocked by it
marked `BLOCKED-UPSTREAM` and never dispatched, run continues with the rest of the DAG.

**Post-merge red** is distinct: the branch was green alone and red merged. Auto-revert the merge,
quarantine the ticket, continue. The integration branch is never left red, because every subsequent
ticket cuts from it.

**Global circuit breaker.** Three consecutive quarantines, or more than 40% of dispatched tickets
quarantined, halts the run. This is the difference between "one ticket was wrong" and "the base is
broken and every agent is now failing for the same reason".

**Rate limiting is handled fleet-wide, not per-agent.** When the signature (fast exit, non-zero code,
no commits) appears on two or more concurrent agents, the orchestrator pauses *all* dispatch and backs
off exponentially to a 15-minute cap. `claude-retry.log` in this repo records the naive version: one
agent retrying every 3 seconds into a limit it had already hit. Three agents doing that independently
is 60 requests a minute into a closed door.

**Budgets** come from the ticket's size flag: S = 30 min, M = 60 min, L = 120 min. Exceeding the budget
is a stall.

---

## Gates

A ticket passes through five gates between dispatch and landing. Each is mechanical.

### 1. Red proof — TDD is verified, not trusted

The agent's first commit must touch only `tests/`. The orchestrator checks out that commit and runs
the new test file: it **must fail**. A ticket that cannot produce a failing test first is quarantined
before any implementation happens, which is cheap.

This is the only way red-green is a fact rather than a claim, and it surfaces the most common way an
autonomous agent produces work that looks finished and isn't: a test that asserts nothing.

### 2. Suite green on the branch

The agent runs the full suite before declaring done.

**The gate is a baseline comparison, not a fixed count.** The orchestrator records the pass/fail set
at run start and gates on *no regressions* — nothing that passed at baseline may fail. A hardcoded
number is wrong by the second merged ticket, because every ticket adds tests.

Measured 15 Aug 2026 on the clone: **486 tests, 4 min 03 s**, exit 0 once the collection artifact
below is excluded. That sits in the 2–8 minute band, so the design holds as written: with a ceiling
of 3 and a ~60 min mean ticket, merges arrive roughly every 20 minutes against a 4-minute lock —
about an 18% duty cycle, no contention.

**`pytest.ini` is load-bearing.** The repo had no pytest configuration at all, so rootdir was
inferred and `sys.path` was patched per test file — fragile when pytest is invoked from a worktree.
It now pins `testpaths` and excludes `tests/test_analysis_modules.py`, which is a standalone
diagnostic script whose `test_*` helpers take positional arguments; pytest collected them by name and
errored on missing fixtures, producing six errors and a non-zero exit. Left unfixed that would have
failed gate 2 on **every** ticket, tripping the circuit breaker three tickets into night one.

### 3. Scope check

`git diff --name-only` against the ticket's declared `files:` list. Out-of-scope files are a **soft
gate**: they do not block the merge, but they are listed in `REPORT.md` and appended to the review
prompt as "the agent touched these files the ticket didn't declare — check whether that's justified."
Hard-blocking would be wrong; sometimes a legitimate fix needs a neighbour. An unexplained edit to
`Adapters/base.py` from a ticket that isn't 05 or 10 is exactly what you want in a table at 8am.

### 4. Two-axis review

The in-repo two-axis review skill — `.claude/skills/code-review/`, invoked as **`code-review`**, not
`code-review-two-axis` — runs against the branch diff, with `docs/CODING_STANDARDS.md` as the
Standards source and the ticket file as the Spec source. Both must exist for the gate to mean anything — a
review with no standards document falls back to Fowler smells, which are judgement calls and produce
false blockers at 3am.

The review step ends by writing **`review.json`**: every finding tagged with axis (`standards` /
`spec`) and severity (`blocker` / `major` / `minor`). The orchestrator gates on blocker count. The
prose stays in the log for you; the gate reads one integer.

**Disposition is severity-asymmetric:**

- **Blockers, either axis** → one auto-fix round: a fresh agent gets the diff plus the findings, fixes,
  re-reviews. Still blocked → quarantine.
- **Majors and minors** → merge, and append to `FOLLOWUPS.md` on the integration branch.

A style finding that blocks a merge overnight also blocks every dependent ticket, and that cost is
measured in milestones. A spec blocker that merges costs correctness. The asymmetry is deliberate.

**Hard cap of two review rounds per ticket.** Agent-fixes-reviewer-objects is a classic overnight burn,
and the ticket that has been round-tripping for four hours is one you want quarantined, not persevered
with.

### 5. Overlap check

Blocking edges capture logical dependency. They do not capture two agents in different modules both
writing `resample_and_znorm`. Git merges that cleanly and you find out in week three.

The check is **mechanical, not an LLM judgement**: AST-parse the branch diff, extract added top-level
function and class names, intersect against everything already merged into the integration branch and
everything in flight. On collision: merge the first branch, **hold** the second, mark it `OVERLAP`,
continue with the rest of the DAG. **Never auto-resolve.** Two implementations of the same idea are
precisely the 3am decision that cannot be audited the next morning — and the one most likely to look
fine and be wrong.

An LLM sibling-comparison may run as an *advisory* note in the morning report. It is never a gate.

### Human gates

Two tiers.

**`human-gate` — never dispatched.** Tickets 04 and 49. They appear in the DAG so their dependents are
correctly held, and are reported each morning as waiting on you. Ticket 04 rebuilds an 11,000-row
table with a foreign-keyed join, against the only irreplaceable artefact in the project. Ticket 49
unlocks the held-out recording, which is a research act, not a build step.

**`human-verify` — dispatched, merged, flagged.** Every ticket that mounts or renders a Panel surface:
17, 18, 20, 21, 22, 23, 29, 30, 31, 32, 33, 34, 37, 38, 39, 42, 44. They land normally but are listed
in `REPORT.md` as needing your eyes before you fast-forward `main`.

The reason this tier can merge unattended at all is the guard in standards rule 4.5: every Panel
ticket carries a headless construction test asserting the surface returns its expected panes with
non-`None` objects. That converts "renders as a blank pane" — the failure mode this codebase has hit
twice — from an invisible failure into a red test. `human-verify` then covers only interaction and
aesthetics, which is what a human is actually needed for.

---

## Observability

The requirement: the next morning, a fault isolates to one ticket without a full re-audit.

Three mechanisms serve it.

**Git is the ledger.** Every commit message is prefixed with its ticket id. Every merge is `--no-ff`.
`git log --merges --oneline` is the landing order; `git revert -m 1 <sha>` is per-ticket undo.

**The run directory** — `runs/<label>-<timestamp>/`, gitignored:

```
REPORT.md          one table row per ticket
plan.md            the run-plan preview as printed at launch
state.json         the DAG state, written atomically on every transition
T17/
  transcript.log   the full agent session
  red-proof.txt    the test output at the test-only commit
  suite.txt        the full suite output on the branch
  post-merge.txt   the full suite output after merging
  review.json      structured findings
  review.md        the reviewer's prose
  scope.txt        files touched vs files declared
  diff.patch
```

**`REPORT.md`** is what you read at 8am. One row per ticket: id, model, status, wall-clock, tokens,
red-proof result, suite result, review blockers by axis, scope deviations, overlap flags, merge sha.
You open a ticket directory only for the rows that are red.

`state.json` is written atomically after every state transition, so killing the orchestrator and
restarting it resumes rather than restarts.

---

## Repository layout for the runner

```
CLAUDE.md                       repo context, loaded by every agent
docs/
  PIPELINE_PRD.md               what is being built and why
  CODING_STANDARDS.md           the Standards axis source
  ORCHESTRATOR_SPEC.md          this document
  tickets/
    README.md                   index, DAG, mutexes, flags, dispatch order
    T01-....md … T49-....md     one file per ticket, YAML front-matter + prose
orchestrator/                   the runner (not yet written)
runs/                           gitignored — transcripts, reports, state
```

Ticket files are committed because the review step must be handed a path to the originating spec. Each
carries YAML front-matter — `id`, `model`, `size`, `blocked_by`, `mutex`, `files`, `flags`, `level`,
`unblocks`, `budget_minutes` — so the scheduler and the human read the same source of truth. An agent
is handed **its own ticket only**, plus `CLAUDE.md` and `CODING_STANDARDS.md`. Never the whole backlog.

---

## Known consequences to accept before the first run

**Ticket 04 is the bottleneck of the entire backlog.** It is human-gated, and 20 further tickets sit
downstream of it — including 18, the four-workspace shell, which gates the whole UI half. Simulating
the scheduler over the real DAG: night one drains 27 of 49 tickets in about 10 hours and then stalls
against 04. **Doing ticket 04 by hand is the single highest-leverage human action available**, and it
should happen before night two, not after.

**The post-merge suite is the throughput ceiling.** Merges serialise behind it, and the suite never
runs under `pytest -n` because `tests/_session_isolation.py` documents exactly why that breaks. Measure
`pytest` wall-clock before writing any of this. Under ~2 minutes and the design holds; at 15 minutes
the merge gate becomes the bottleneck and the policy needs revisiting — most likely to a
subset-by-touched-module gate at merge with one full suite at end of run.

**Cutting ticket 15 shortens the critical path.** The longest chain is
`01 → 05 → 13 → 14 → 15 → 24 → 25 → 26 → 31 → 32 → 44 → 48 → 49`, and 15 (the step cache) is first on
the PRD's cut list. Cutting it removes a link from the critical path and a HIGH-risk `execution.py`
edit. That is a better argument for cutting it than the PRD's own.

---

## Appendix A — `state.json`

The orchestrator's memory. Written atomically after **every** state transition:

```python
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps(state, indent=1))
os.replace(tmp, path)        # atomic on NTFS
```

**The DAG is not stored here.** Blocking edges, mutexes, flags and models are re-derived from the
ticket front-matter on every start. `state.json` holds only what is *mutable*, so editing a ticket's
`blocked_by` never requires migrating state.

```json
{
  "schema": 1,
  "run_id": "run-20260815-2130",
  "integration_branch": "integration/run-20260815-2130",
  "base_sha": "9f2c1ab",
  "config_hash": "sha256:…",
  "started_at": "2026-08-15T21:30:00+10:00",
  "wall_clock_stop": "2026-08-16T07:00:00+10:00",
  "circuit_breaker": { "consecutive_quarantines": 0, "tripped": false },
  "merge_lock_holder": null,
  "symbols": { "resample_and_znorm": 35, "load_fixture_db": 2 },
  "tickets": {
    "17": {
      "status": "MERGED",
      "attempts": 1,
      "branch": "ticket/T17",
      "worktree": "C:/Users/mmebr/Documents/.wt/T17",
      "gates": {
        "red_proof": "pass", "suite": "pass", "scope": "warn",
        "review": "pass", "overlap": "pass"
      },
      "review_rounds": 1,
      "review_blockers": { "standards": 0, "spec": 0 },
      "scope_deviations": ["UI/plots.py"],
      "merge_sha": "4b7e0c2",
      "started_at": "2026-08-15T23:30:00+10:00",
      "ended_at": "2026-08-16T00:34:11+10:00",
      "exit_class": null
    }
  }
}
```

**Status values.** `PENDING` → `READY` → `RUNNING` → `GATING` → `MERGING` → `MERGED`. Terminal
alternatives: `FAILED` (quarantined), `BLOCKED_UPSTREAM` (a blocker was quarantined),
`OVERLAP` (held by the overlap check), `HELD` (`human-gate`, never dispatched).

`symbols` is the accumulated top-level function/class name → owning ticket index that the overlap
check reads. It is rebuildable from git, but carrying it makes the check cheap.

### Recovery on restart

**Git is the durable truth; `state.json` is an index over it.** Where they disagree, git wins.

On startup, every ticket found in `RUNNING`, `GATING` or `MERGING` is stale by definition — its
subprocess died with the orchestrator. Each is reconciled against git rather than trusted:

| Git says | Action |
|---|---|
| Branch merged into the integration branch | Mark `MERGED`, record the merge sha, move on |
| Branch exists with commits, not merged | Resume at the first ungated step; do not re-dispatch the agent |
| Branch exists, no commits beyond base | Delete branch and worktree, reset to `READY` |
| No branch | Reset to `READY` |

Nothing is ever re-dispatched on the strength of a `state.json` field alone. A crash mid-merge is the
one case worth stating explicitly: if the merge commit exists but the post-merge suite never ran, the
ticket returns to `MERGING` and the suite runs again — running it twice is free, skipping it is not.

---

## Appendix B — Pre-flight checks

Run these once, before the first real dispatch. Each is a silent-degradation risk, not a crash.

1. **The reviewer resolves.** Open a Claude Code session *inside a git worktree* and confirm the
   two-axis review skill is discoverable there. Worktrees contain only tracked files, and `.claude/`
   is gitignored — so a project-level skill under `.claude/skills/` will **not** exist in any
   worktree. Either install the skills user-level (`~/.claude/skills/`), or track `.claude/skills/`
   by adding a negation to `.gitignore`. If the reviewer cannot be found, gate 4 degrades to nothing
   and every ticket merges unreviewed.
2. **The reviewer does not ask questions.** The in-repo `code-review` skill asks for a fixed point if
   none is given, and asks where the spec is if it cannot find one. Unattended, either question
   hangs the ticket until its budget expires. The runner passes **both** explicitly: the merge-base
   against the integration branch, and the ticket file path.
3. **`docs/agents/issue-tracker.md` exists.** Without it the review skill instructs the agent to run
   `/setup-matt-pocock-skills`, which is interactive. The stub in this repo tells it not to.
4. **`review.json` is the runner's output, not the skill's.** Neither review skill emits structured
   findings. The runner converts the prose into severity-tagged JSON, grading against the per-rule
   severities already assigned in `docs/CODING_STANDARDS.md`.
5. **Suite wall-clock measured.** `pytest -q --durations=15`, run twice (the first pays import cost
   for torch/kymatio/aeon). Under ~2 min the design holds as written; 2–8 min holds with a lower
   ceiling; over ~15 min switch the merge gate to subset-by-touched-module with one full suite at end
   of run.
6. **`annotations.sqlite` backed up** to a location outside the working clone. Moving off Drive
   removed the incidental backup `DATA/README.md` was relying on.
