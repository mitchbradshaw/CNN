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

## T01 — 2026-08-17 13:09

- [major] [standards] (rule 6.4) Seven near-identical to_path/from_path bodies and five __eq__ bodies duplicate the same shape across Working/types/*.py
- [major] [standards] (rule 6.1) Signal.x vs Scores.values name the same per-timepoint concept two ways in sibling modules
- [minor] [standards] (rule 6.2) to_path returns a file path no caller can use (from_path takes a directory); windowset.py:90 returns only the geometry path though two files were written
- [minor] [standards] (no rule cited) spanset.py:28 docstring claims ends[i] > starts[i] but spanset.py:51 checks `end < start`, so zero-length spans pass unvalidated
- [minor] [standards] (no rule cited) spanset.py:65 and model.py:36 open text files without encoding="utf-8"; non-ASCII span labels break the round-trip on Windows
- [minor] [standards] (no rule cited) Possible Primitive Obsession: encoding.py:31 kind is an unvalidated str while sibling types validate in __post_init__
- [minor] [standards] (no rule cited) grouping.py:40 and windowset.py:83 silently coerce dtype on write; array_equal in __eq__ hides the asymmetry from the round-trip tests
- [minor] [standards] (no rule cited) Possible Duplicated Code in tests: ten inline `import shutil` cleanups and a 50-line embedded subprocess script re-building all seven types; subprocess.run has no timeout
- [minor] [standards] (no rule cited) Possible Feature Envy: Scores.from_signal reaches into signal.x/signal.fs more than its own state
- [minor] [spec] (no rule cited) Serialisation-format criterion (.npz/.parquet/.json/path-ref) asserted by no test; all 19 tests check only round-trip equality
- [minor] [spec] (no rule cited) "each exists as a frozen dataclass" tested for Signal only (test_types.py:58); six types untested for frozen-ness
- [minor] [spec] (no rule cited) Scores length-vs-signal assertion lives only in opt-in from_signal (scores.py:43-53); bypassed by direct construction and from_path
- [minor] [spec] (no rule cited) test_scores_from_signal_asserts_length_matches_source_signal (test_types.py:235) is tautological, asserting a length from_signal just enforced
- [minor] [spec] (no rule cited) "WindowSet carries no timepoint alignment" is asserted by no test; :143 only checks n_windows
- [minor] [spec] (no rule cited) Scope creep: SpanSet start/end and length validation (spanset.py:40-52) plus two tests, not requested by ticket or PRD
- [minor] [spec] (no rule cited) WindowSet.to_path leaves a stale features.parquet on directory reuse (windowset.py:87-102), so a featureless set reloads with features
- [minor] [spec] (no rule cited) Five of seven types are unhashable (custom __eq__ nulls __hash__) while SpanSet and Model hash; inconsistent for cache keys
- [minor] [spec] (no rule cited) SpanSet docstring promises ends[i] > starts[i] (spanset.py:28) but validation permits end == start (:51)
