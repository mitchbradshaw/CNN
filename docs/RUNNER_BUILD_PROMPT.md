# Build prompt — autonomous ticket runner

Paste the block below into a fresh Claude Code session opened at the root of the local clone
(`C:\Users\mmebr\Documents\CNN`). It is written to be self-contained.

---

```
Build the autonomous ticket runner for this repository.

CONTEXT — read these first, in this order:
  docs/ORCHESTRATOR_SPEC.md   the complete settled design. This is the specification.
                              Every architectural and failure-handling decision in it is
                              settled and not open for redesign. Implement it; do not
                              re-litigate it.
  docs/tickets/README.md      the backlog's shape: DAG levels, mutex pairs, flags,
                              dispatch order, and the ticket-04 bottleneck.
  docs/tickets/T01-*.md       one example ticket, to see the YAML front-matter the
                              scheduler consumes.
  CLAUDE.md                   repo conventions.

Do NOT read the whole ticket backlog or docs/PIPELINE_PRD.md. The runner is
indifferent to what the tickets say; it only consumes their front-matter.

WHAT TO BUILD

A deterministic Python orchestrator under orchestrator/ that implements
docs/ORCHESTRATOR_SPEC.md. It dispatches tickets to `claude -p` subprocesses, one
git worktree each, gates them, merges them, and writes an auditable trail.

Hard constraints:
  - Python standard library only. No third-party dependencies. The orchestrator must
    be boring, inspectable, and unable to fail in an interesting way. subprocess,
    pathlib, json, ast, argparse, dataclasses, logging are the whole toolkit.
  - Windows/PowerShell host, conda environment already active. Do not create a venv,
    do not install anything, do not add a requirements file for the runner.
  - Deterministic. No LLM decides scheduling, merging, or conflict resolution. The
    only LLM calls are the per-ticket agent, the review agent, and the auto-fix agent.
  - Config lives in orchestrator/config.toml (read with tomllib) — ceilings, budgets,
    wall-clock stop, paths, model names. Nothing tuneable is hardcoded.

BUILD ORDER — each stage is independently testable, build them in this sequence:

  1. Backlog loader. Parse YAML front-matter from docs/tickets/T*.md into ticket
     objects. Validate: every blocked_by and mutex id exists, the graph is acyclic,
     no ticket declares itself. Compute level, transitive dependents, critical-path
     length.
  2. Scheduler (pure, no side effects). Given ticket states and config, return the
     set to dispatch now. Enforces, in priority order: blocking edges, mutexes, the
     solo flag, global and Opus ceilings, human-gate exclusion. Orders by
     most-unblocking, then critical-path length, then id.
  3. `--plan` preview. Simulate the scheduler with size-based durations and print the
     wave-by-wave schedule, exactly as illustrated in the spec: which tickets start
     together, model, size, budget, what each was blocked on, which mutex held a
     ready ticket back, projected wall-clock, and the tickets that will not run and
     why. Writes to the run directory and prints at launch. This is the first thing
     to get working — it is how the design gets validated before anything executes.
  4. State store. state.json, written atomically after every transition. The
     orchestrator restarts from it rather than starting over.
  5. Worktree provisioning and teardown. Create from the integration branch, copy the
     fixture database in, junction the read-only recording directories, remove on
     completion.
  6. Agent dispatch. Launch `claude -p` in a worktree with the ticket file, CLAUDE.md
     and docs/CODING_STANDARDS.md. Capture the transcript. Enforce the wall-clock
     budget. Classify exit conditions into the four failure classes in the spec.
  7. The five gates, in order: verified red proof, suite green on branch, scope check,
     two-axis review producing review.json, mechanical AST overlap check.
  8. Merge. --no-ff into the integration branch behind a merge lock, full suite after,
     auto-revert on post-merge red.
  9. Reporting. REPORT.md and the per-ticket run directories described in the spec.

DISCIPLINE

Test-first, using the tdd skill. Every stage above gets a failing test before it gets
an implementation. The scheduler in particular must be a pure function over ticket
state so it can be tested exhaustively without git, subprocesses or the network — test
it against the real 49-ticket graph and assert the mutex pairs the spec names are never
co-scheduled.

SAFETY — this matters more than anything else here

Develop and test the runner against a DISPOSABLE scratch git repository with FAKE
tickets that you create under a temp directory. Never against this repository, never
against the real backlog, and never by launching a real agent on a real ticket. The
first real run is a decision the user makes deliberately, after reading `--plan`
output, not something that happens because a test invoked it.

The merge and worktree code touches git history. Prove it on the scratch repo.

DELIVERABLES

  orchestrator/            the runner, config.toml, and its tests
  orchestrator/README.md   how to run it: --plan, --run, --resume, --status

Start by reading the spec, then show me the module breakdown you intend before writing
code.
```

---

## Notes on this prompt

**`to-spec` is not needed.** `docs/ORCHESTRATOR_SPEC.md` is already the spec — it came out of a
grilling session and carries the problem statement, the settled decisions, the failure policy and
the out-of-scope boundary. Running `to-spec` again would restate what exists.

**`to-tickets` is optional.** The runner is a few hundred lines with a clean internal dependency
order, and the build order above already serves as its ticket list. Reach for `to-tickets` only if
the build gets handed to an autonomous agent rather than worked interactively.

**Build it interactively, not autonomously.** The runner is the thing that will later be trusted to
merge unattended. It is the one piece of this project that should be watched while it is written.
