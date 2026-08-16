# Follow-ups

Raised by the review gate and merged anyway. See docs/ORCHESTRATOR_SPEC.md, gate 4.

## Harness — 2026-08-16 (pre-run, not raised by the review gate)

Found while fixing the run-20260816-1943 harness defects. Application code, so out of scope for the
harness work; needs triage into a ticket by a human rather than being self-assigned.

- [major] [standards] (no rule cited) **`UI/app.py:2279` builds the entire application at import
  time.** The module ends with a bare `create_app().servable(title="Mycelium Signal Viewer")`, so
  `import UI.app` constructs a `ViewerApp`, opens the database, and mmaps the first recording's
  channel `.npy`. Consequences:

  - Every test file that imports `UI.app` — ten of them — fails at **collection**, not at assertion
    time, whenever the database has no recordings (`RuntimeError`) or the channel file is absent
    (`FileNotFoundError`). Their own `_channel_available()` skip guards are correct and never get to
    run, because collection never completes. This is the mechanism that quarantined an innocent T01
    and put 36 tickets into `BLOCKED_UPSTREAM`.
  - It is very likely also why `tests/_session_isolation.py` had to exist: importing the module is
    enough to touch real session state.
  - It forces the orchestrator to junction 317 MB of real channel data into every worktree purely so
    that `import` succeeds — which is the reason the writable-recordings tradeoff in
    `ORCHESTRATOR_SPEC.md §Isolation` had to be accepted at all.

  Fix: move the call behind a `if __name__ == "__main__":` guard or into a separate `serve.py` entry
  point, so importing the module defines the app without building it. Worth checking whether the ten
  files' real-data gating can then become a plain module-level `pytest.skip(...)`, and whether the
  junction can be dropped from `recordings` afterwards — which would close the tradeoff rather than
  merely record it.
