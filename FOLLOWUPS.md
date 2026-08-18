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

## Harness — 2026-08-17 (post-run-20260817-1157)

**The 2026-08-16 entry above predicted this run's failure and was not actioned, so it happened
again.** `DATA/derived/channels/M2_aug_concat_fs1/` was empty; all 16 fixture rows pointed at absent
`.npy` files; `import UI.app` raised `FileNotFoundError` at collection; pytest aborted the session in
every worktree. T01 and T02 were graded `suite: pass` having run **zero** tests, and T01 merged on
that. The channel data has been rematerialised from `DATA/raw/M2_aug_concat_fs1.mat` (317 MB) and
three guards added — but the underlying defect is still the import-time `create_app()`, and it will
keep converting ordinary data problems into total-collection failures until it is fixed.

- [blocker] [harness] **Promote the 2026-08-16 entry to a real ticket.** It is one line of code
  (`if __name__ == "__main__":`) standing between this repo and a class of silent, total gate
  failure. It also closes the writable-recordings isolation tradeoff in `ORCHESTRATOR_SPEC.md
  §Isolation`, since the 317 MB junction exists only to make `import` succeed.
- [major] [harness] **The 98 `_channel_available()` guards `print` and `return` rather than skip.**
  A test that returns early is reported as *passed*. With the channel data absent, a large share of
  the "505 passed" was vacuous — restoring the data moved the suite from 152 s to 276 s, which is the
  size of what was not being executed. These should be `pytest.skip(...)`, so absent data reads as
  skipped rather than green.
- [minor] [harness] `DATA/db/ui_session.json` is why the main repo kept passing while every worktree
  failed: it pins the viewer to `Mushroom_260720_0509_4hrs_CH14_fs1.mat`, whose channel file exists,
  so `import UI.app` never touched the broken recording. Delete that file and `main` reproduces the
  worktree failure exactly. Tests should not depend on a gitignored session file for their import to
  succeed.

## Harness — 2026-08-18 (post-run-20260817-2050)

The fixture repair held: the baseline was empty and the suite gate was real. Three new defects, all in
how the runner treats an agent that misbehaves rather than in what the agents built.

- [fixed] **The CLI's `~/.claude.json` is global, and the worktrees are not.** All three agents launched
  at 20:56:35, raced on it, and two read it mid-write. They then looped on `JSON Parse error:
  Unexpected EOF` for their entire 60-minute budget. Launches are now staggered
  (`agent.launch_stagger_seconds`), and the corruption signature is an infrastructure marker so the
  ticket is not blamed for it.
- [fixed] **`agent.stall_minutes` was configured and never implemented.** T35 committed its failing
  tests at 21:02 and its implementation at 21:08, then hung until the budget killed it at 21:56 — and
  the runner discarded a complete, test-first ticket, retried it, and quarantined it while both commits
  sat on the branch. Two causes: nothing watched for silence, and `timed_out` was checked before the
  commit count, contradicting this module's own rule that work goes to the gates.
- [fixed] **Judgement calls were being promoted to merge blockers.** The T02 review wrote "No blockers"
  and marked all nine findings judgement; four cited rules graded `blocker`, and the runner re-graded
  them into blockers. The findings block now carries a `judgement` field that caps a finding below
  `blocker`. Replaying that review through the new grading yields 0 blockers and 15 follow-ups.
- [watch] **`stall_minutes = 20` is now live, and has never been validated against a large ticket.**
  It is the value the config already declared, so it is what got implemented rather than a number
  invented here. Both observed failures are caught comfortably by it — T35 was silent for 48 minutes,
  and the config-corruption case never commits at all. The exposure is a genuinely slow ticket: T17
  splits two god-class UI modules, and an agent that spends more than 20 minutes between commits there
  would be killed with partial work, fail the suite gate, and be quarantined where previously it had
  the full 60 minutes. Nothing is lost silently — the commits still go to the gates — but if T17 or
  another `L` ticket starts dying this way, raise the number rather than assuming the ticket is bad.
- [open] **The transcript is lost when an agent is killed on Windows.** `subprocess.run` with
  `capture_output=True` returns no stdout on `TimeoutExpired`, which is why T35's transcript was 69
  bytes and the diagnosis took a branch inspection rather than a log read. The watched path now writes
  to a file and keeps it, but `run_agent`'s unwatched path and the review/fix calls still lose it.

## Harness — 2026-08-18 (post-run-20260818-0554)

The night the gates finally behaved: T02 and T35 both merged clean on the first review round, the
baseline was empty, the circuit breaker never tripped, and no agent stalled. Two things to record.

- [fixed] **The overlap gate counted test-file symbols as shared vocabulary.** T13 passed red-proof,
  suite and review with zero findings and was held anyway, because its test file's `_run_all()`
  collided with T35's — the identical footer that 41 of this repo's 42 test files carry. Every
  `test_*` function name was in the owner map too, so any two tickets naming a test the same way
  would have collided next. Test modules are leaves that nothing imports; `overlap.ignore_paths`
  now drops `tests/` from the comparison. Replayed against the real branches, T13 goes hold -> pass
  and its reported symbols fall from 20 to the 3 real ones.
- [fixed] **The worktree fixture went stale the moment T02 landed.** `test_the_shipped_fixture_database
  _is_not_the_real_one` caught it: the fixture predates the schema extension and was missing all nine
  new tables. Rebuilt. This is now a standing obligation — **run `python -m orchestrator.make_fixture`
  after any ticket that changes `schema.py`**, which for the remaining backlog means 04 and 16.
- [watch] **The judgement cap is what let T35 merge, and it was not free.** Three of T35's findings
  cite `blocker`-graded rules (5.1, 4.2, 1.4) and were capped to `major` because the reviewer marked
  them judgement calls — without that change T35 would have been quarantined. The policy is the one
  chosen deliberately, and all nineteen findings are recorded below, but one of the capped three was a
  real unmet obligation: 35 was supposed to own the correlation helper ticket 41 imports, and shipped
  only `z_normalize`. T41's ticket has been corrected to write its own rather than hunt for a function
  that does not exist. Worth re-reading the capped findings on each merged ticket rather than trusting
  the `0/0` blocker column in REPORT.md.
- [not a bug] **The run only got three tickets because it started at 05:54.** `wall_clock_stop` is
  07:00, so the dispatch window was 66 minutes; T13 was allowed to finish and ran to 07:31. Nothing
  was held or blocked — 44 tickets were simply never dispatched. A run started after 07:00 gets the
  next day's stop and a ~20h window.

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

## T35 — 2026-08-18 06:28

- [major] [standards] (rule 5.1) Distance identity recorded as a bare name while word_length/alphabet_size/n_samples materially change the value and are not part of it
- [major] [standards] (rule 6.1) Magic default `alphabet_size=10` unnamed and unjustified in a module built around named constants
- [major] [standards] (rule 6.1) `symbolic_distance` omits the classic sqrt(n/w) factor, so the "MINDIST" name and Lin/Keogh citation promise a lower bound the code does not deliver
- [major] [standards] (rule 6.4) `scale_invariant_distance` and `native_length_distance` duplicate the same z-normalise-then-Euclidean body
- [major] [standards] (rule 6.4) `_sax_symbols` re-implements psax.py's single-window `timeseries2symbol(..., NR_opt=1)` plus 1-based-to-0-based idiom
- [major] [standards] (rule 6.4) Two conflicting constant-span policies in one pipeline: `z_normalize` uses `sigma == 0`, `timeseries2symbol` uses `sigma > 0.001`
- [minor] [standards] (rule 6.2) `n_samples=None` on `scale_invariant_distance` is an unrequested, untested extension point
- [major] [standards] (rule 4.2) Symbolic hand-case expectation re-derives cutlines with `normal_cutlines`' exact scipy expression instead of a hand-worked constant
- [major] [standards] (rule 1.3) `Working/README.md` assigns SAX MINDIST-style comparison to `Working/Comparison/`; module placed at top-level `Working/distances.py` (ticket declares the path)
- [minor] [standards] (no rule cited) `DISTANCE_REGISTRY` values have non-uniform signatures, so a name-driven caller cannot invoke them uniformly
- [minor] [standards] (no rule cited) Possible Data Clump: `(word_length, alphabet_size)` SAX configuration travels alongside the span pair through `symbolic_distance`/`_sax_symbols`/`_mindist_cell_table`
- [major] [spec] (rule 1.4) Merge-risk clause says T35 owns the correlation helper T41 imports; only `z_normalize` was delivered, no correlation helper exists
- [minor] [spec] (no rule cited) Scale-invariant "hand-computed case" uses equal-length inputs, so `resample_to_length` short-circuits and the resampling limb is never hand-verified
- [minor] [spec] (no rule cited) `word_length` is a required caller argument rather than a fixed constant, giving `symbolic_distance` a signature incompatible with the other two registry entries
- [major] [spec] (rule 7.1) `native_length_distance` silently truncates to `min(len)` — undeclared behaviour that makes an empty span read as distance 0.0 from any span
- [minor] [spec] (no rule cited) `symbolic_distance` omits the `sqrt(n/w)` factor, so it is not the MINDIST it names and cites and does not lower-bound Euclidean distance
- [major] [spec] (rule 6.4) Reimplements `_mindist_cell_table` when `symbol_distance_table`/`mindist` already exist in `Experimentation/Detection experiments/sax_seed_search.py`
- [minor] [spec] (no rule cited) Scale-invariant distance is unnormalised by `n_samples = max(len)`, so its magnitude grows ~sqrt(n) and a single recorded threshold is not comparable across durations
- [minor] [spec] (no rule cited) Constant-span guard differs between `z_normalize` (`sigma == 0`) and `timeseries2symbol` (`norm_thresh = 0.001`), so near-constant pairs score 8.94 native vs 0.0 symbolic
