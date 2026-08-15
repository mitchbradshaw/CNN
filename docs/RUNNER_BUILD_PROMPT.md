# Build prompt — autonomous ticket runner

Paste the block below into a fresh Claude Code session opened at the root of
`C:\Users\mmebr\Documents\CNN`. It is written to be self-contained.

---

```
Build the autonomous ticket runner for this repository.

CONTEXT — read these first, in this order:
  docs/ORCHESTRATOR_SPEC.md   the complete settled design. This is the specification.
                              Every architectural and failure-handling decision in it
                              is settled and not open for redesign. Implement it; do
                              not re-litigate it. Appendix A is the state schema,
                              Appendix B the pre-flight checks.
  docs/tickets/README.md      the backlog's shape: DAG levels, the 18 live mutex pairs,
                              flags, dispatch order, and the ticket-04 bottleneck.
  docs/tickets/T01-*.md       one example ticket, to see the YAML front-matter the
                              scheduler consumes.
  CLAUDE.md                   repo conventions.
  pytest.ini                  why one test file is excluded from collection.

Do NOT read the whole ticket backlog or docs/PIPELINE_PRD.md. The runner is
indifferent to what the tickets say; it consumes only their front-matter.

WHAT TO BUILD

A deterministic Python orchestrator under orchestrator/ implementing that spec. It
dispatches tickets to `claude -p` subprocesses, one git worktree each, gates them,
merges them into an integration branch, and writes an auditable trail.

Hard constraints:
  - Python standard library only. No third-party dependencies. subprocess, pathlib,
    json, ast, argparse, dataclasses, tomllib, logging are the whole toolkit. The
    orchestrator must be boring, inspectable, and unable to fail in an interesting way.
  - Windows/PowerShell host, conda environment already active. Do not create a venv,
    do not install anything, do not add a requirements file for the runner.
  - Deterministic. No LLM decides scheduling, merging, or conflict resolution. The
    only LLM calls are the per-ticket agent, the review agent, and the auto-fix agent.
  - Config in orchestrator/config.toml — ceilings, budgets, wall-clock stop, paths,
    model names, retry counts. Nothing tuneable is hardcoded.

BUILD ORDER — each stage is independently testable. Build in this sequence.

  0. Worktree smoke check. Create a throwaway worktree, confirm that `.claude/skills/`
     and `pytest.ini` are present inside it, and that the `code-review` skill resolves
     from that directory. Worktrees contain only COMMITTED files, so anything merely
     untracked is invisible to every agent. This is a five-minute check that prevents
     a silent no-op review gate; do it before writing anything else.
  1. Backlog loader. Parse YAML front-matter from docs/tickets/T*.md. Validate: every
     blocked_by and mutex id exists, the graph is acyclic, no self-reference. Compute
     level, transitive dependents, critical-path length.
  2. Scheduler — a PURE function, no side effects. Given ticket states and config,
     return the set to dispatch now. Enforces in priority order: blocking edges,
     mutexes, the solo flag, global and Opus ceilings, human-gate exclusion. Orders by
     most-unblocking, then critical-path length, then id.
  3. `--plan` preview. Simulate with size-based durations and print the wave-by-wave
     schedule exactly as illustrated in the spec: which tickets start together, model,
     size, budget, what each was blocked on, which mutex held a ready ticket back,
     projected wall-clock, and the tickets that will not run and why. Get this working
     before anything executes — it is how the design gets validated.
  4. State store. state.json per Appendix A, written atomically. Reconciliation on
     restart is against git, not against the file: git is the durable truth.
  5. Worktree provisioning and teardown — create from the integration branch, copy the
     fixture database in, junction the read-only recording directories, remove after.
  6. Agent dispatch. Launch `claude -p` in a worktree with the ticket file, CLAUDE.md
     and docs/CODING_STANDARDS.md. Capture the transcript, enforce the wall-clock
     budget, classify exit conditions into the four failure classes.
  7. The five gates in order: verified red proof, suite green (baseline comparison plus
     the flake amendment — re-run only the failing node ids once), scope check,
     two-axis review producing review.json, mechanical AST overlap check.
  8. Merge. --no-ff into the integration branch behind a merge lock, full suite after,
     auto-revert on post-merge red.
  9. Reporting. REPORT.md and the per-ticket run directories described in the spec.

THINGS THAT WILL BITE YOU, ALREADY KNOWN

  - The review skill is invoked as `code-review`, NOT `code-review-two-axis`. It lives
    at .claude/skills/code-review/.
  - That skill ASKS for a fixed point if none is given, and asks where the spec is if
    it cannot find one. Unattended, either question hangs the ticket until its budget
    expires. Pass BOTH explicitly: the merge-base against the integration branch, and
    the ticket file path.
  - The skill emits prose, not JSON. Converting its findings into severity-tagged
    review.json is the runner's job, graded against the per-rule severities already
    assigned in docs/CODING_STANDARDS.md.
  - The suite is 486 tests, about 4 minutes, and it is NOT green-by-construction:
    UI/window_matrix_panel.py leaks a background worker thread that outlives its test
    and touches SQLite from the wrong thread. Do not try to fix that here — it needs
    its own ticket. It is why the flake amendment exists.
  - Never run the suite under `pytest -n`. tests/_session_isolation.py documents why.

DISCIPLINE

Test-first, using the tdd skill. Every stage gets a failing test before an
implementation. The scheduler especially must be a pure function over ticket state so
it can be tested exhaustively without git, subprocesses or the network — test it
against the real 49-ticket graph and assert that the mutex pairs named in
docs/tickets/README.md are never co-scheduled, that 17 never runs alongside anything,
and that 04 and 49 are never dispatched.

SAFETY — this matters more than anything else here

Develop and test against a DISPOSABLE scratch git repository with FAKE tickets that you
create under a temp directory. Never against this repository, never against the real
backlog, and never by launching a real agent on a real ticket. The merge and worktree
code rewrites git history; prove it somewhere disposable.

The first real run is a decision the user makes deliberately after reading `--plan`
output. It is not something a test triggers.

DELIVERABLES

  orchestrator/            the runner, config.toml, and its tests
  orchestrator/README.md   how to run it: --plan, --run, --resume, --status

Start by reading the spec, then show me the module breakdown you intend before writing
any code.
```

---

## Notes

**`to-spec` is not needed.** `docs/ORCHESTRATOR_SPEC.md` is already the spec — it came out of a
grilling session and carries the problem statement, the settled decisions, the failure policy, the
state schema and the out-of-scope boundary.

**`to-tickets` is optional.** The build order above is the runner's ticket list. Reach for
`to-tickets` only if the build gets handed to an autonomous agent rather than worked interactively.

**Build it interactively, not autonomously.** This is the component that will later be trusted to
merge unattended. It is the one piece of the project that should be watched while it is written.

**Commit before the first run.** `git worktree add` materialises only committed files. Anything left
untracked — skills, `pytest.ini`, ticket edits — is invisible inside every agent's worktree, and the
gates that depend on it fail open rather than closed.
