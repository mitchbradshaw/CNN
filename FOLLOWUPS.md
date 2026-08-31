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

## Harness — 2026-08-19 (post-run-20260818-1114, written late)

**Written retrospectively on 2026-08-19.** This run and the one after it were never written up at the
time, which is itself the finding: the improvement loop was a habit rather than a mechanism, and it
lapsed precisely on the two worst nights. `append_run_postmortem` now writes a stub for every run, so
a missing post-mortem is visible instead of silent.

Three losses, one merge (T28).

- [fixed] **The red-proof gate ran in a dirty worktree.** T14 and T17 both wrote genuinely failing
  first commits and both were graded "the first commit's test passed on arrival". The gate checked out
  the test-only commit without cleaning the tree first, so the implementation from the agent's later
  commits was still on disk and the tests passed against it. Fixed in `d8be32f`. T17 was subsequently
  worked by hand and landed; T14 is still open and was innocent.
- [open] **T08 is the only genuine ticket failure in the run** — red suite at exit, nine failing tests
  in `tests/test_execution.py`. Not a harness fault. Still to be re-dispatched.
- [note] **T08's transcript is the usage-cap message**, not a work log: `You're out of extra usage ·
  resets 3:15pm`. The suite failure above is real, but the agent was also working against a closing
  window. Worth re-running before concluding anything about the ticket.

## Harness — 2026-08-19 (post-run-20260818-2244, written late)

**Four dispatched, zero merged, breaker tripped, night over at 23:00.** Every one of the four agents
printed `You're out of extra usage · resets 3:30am` and did nothing else. This is the run that
motivated the 2026-08-19 harness work below.

- [fixed] **An infrastructure failure quarantined the ticket.** `b051595` had already added
  `out of extra usage` to `INFRASTRUCTURE_MARKERS`, so the *classification* was right — but
  `runloop._run_agent_with_retry` quarantined on an `infrastructure` verdict immediately, with no
  retry, counted it at full weight against the circuit breaker, and set every dependent to
  `BLOCKED_UPSTREAM`. `ORCHESTRATOR_SPEC.md` has said "backoff, up to 3 retries, does not count
  against the ticket" since the design was settled; that policy existed only for `provision()`. The
  fix was one commit away for four days and the label change hid it.
- [fixed] **Fifteen-minute backoff against an hours-long window.** `rate_limit.max_backoff_seconds =
  900`. The transcript states its own reset time and nothing read it.
- [fixed] **A tripped run cannot be resumed.** `--resume` re-enters `Runner.run`, which breaks out
  immediately on `circuit_breaker.tripped`, and `reconcile` only touches `IN_FLIGHT` records — so the
  four `FAILED` tickets stayed failed and their dependents stayed blocked. There was no way to pick
  the night back up.

## Harness — 2026-08-19 (the usage-resilience work)

Six defects addressed together, on `fix/runner-usage-resilience`. Orchestrator suite 273 passing with
4 failures before, 316 passing with 0 after.

- [fixed] **Infrastructure failures now defer rather than quarantine.** New `DEFERRED` status: no
  circuit-breaker weight, no `BLOCKED_UPSTREAM` for dependents, empty ticket branch deleted so the next
  dispatch can provision. Terminal for the night, re-queued at the top of the next pass, which is what
  makes `--resume` worth running once the window reopens.
- [fixed] **The runner reads the reset time out of the transcript** (`resets 3:30am`) and pauses the
  whole fleet until then, bounded by `rate_limit.max_usage_wait_seconds` (6h). The blind exponential
  backoff stays bounded low and is used only when nothing named a time.
- [fixed] **Token and cost accounting exists.** `agent.output_format = "stream-json"` gives a per-agent
  usage record; `REPORT.md` gains `tokens` and `cost` columns and a run total that separates spend on
  work that landed from spend on work that did not. This implements a spec requirement
  (`ORCHESTRATOR_SPEC.md` §REPORT.md) that five runs shipped without — every model-tier decision in
  `config.toml` up to now was taken against no measurement. `transcript-N.log` stays prose
  (reconstructed from the stream, so the review gate still finds its findings block) and the raw
  stream is kept beside it as `transcript-N.jsonl`.
- [fixed] **`ceilings.concurrent` 3 → 2.** Concurrency does not reduce token spend, it concentrates
  it: three agents for an hour and one for three hours cost the same, but only the first shape
  overruns a usage window and takes everything in flight with it. Projected drain at ceiling 2 is 19h
  against a ~20h dispatch window.
- [fixed] **The Opus sub-ceiling counted declared tiers, not effective ones.** With
  `models.model_cap = "sonnet"` no ticket spends an Opus token, yet 19 of the 41 remaining tickets
  were still queuing behind an Opus limit — serialisation with no saving. It now counts the tier a
  ticket will actually launch on. This alone was worth 1.5h of drain.
- [fixed] **`UI/app.py` no longer builds the application at import.** The servable call moved to a new
  `UI/serve.py`; `panel serve UI/serve.py` is the documented command now. This is the defect first
  raised on 2026-08-16 and re-raised as a blocker on 2026-08-17 — root cause of run 1's cascade, of
  the vacuous "505 passed" in run-20260817-1157, and the sole reason 317 MB of real recordings are
  junctioned into every worktree.
- [fixed] **`Ceilings` was declared twice** — once in `config.py`, once in `scheduler.py`. The runtime
  passed the config one to `schedule()` while the tests exercised the scheduler one, so a field added
  to either was invisible through the other. Now one definition, re-exported.
- [fixed] **Four orchestrator tests were pinned to a world where T04 was still an open human gate.**
  They had been failing since T04 was flagged `done` and were failing on arrival at this work — a red
  harness suite is exactly what stops anyone trusting the harness. Rewritten to derive from the
  backlog rather than hardcode a snapshot.
- [decided: keep] **The junction stays, and it is now a declared dependency rather than a secret.**
  The earlier entry here said `paths.recordings` "may now be droppable" once the guards were fixed,
  and recommended dropping it. Measured in real provisioned worktrees, that recommendation was wrong.

  |                       | passed | skipped | failed | errors |
  |---|---|---|---|---|
  | with the junction     | 632    | 0       | 0      | 0      |
  | without the junction  | 544    | 88      | 0      | 0      |

  Dropping it is *safe* — nothing errors, every guarded test skips cleanly. It is the distribution
  that rules it out. Those 88 tests are **100% of the coverage in eight of their ten files**
  (`test_ui_selection`, `test_session_persistence`, `test_encoding_view`, `test_run_panel`,
  `test_filters`, `test_ribbon_panes`, `test_shortcuts_and_view_controls`,
  `test_run_panel_matrix_profile`), and **seven of the eight tests in `test_execution.py`** — the
  module T03, T08, T14, T15 and T24 all touch, with T14 and T15 flagged HIGH merge risk against each
  other. Dropping the junction would trade a recorded, bounded isolation tradeoff (agents can write to
  regenerable derived data on a held-out-safe recording) for a silent, unbounded one: five remaining
  tickets gated on an execution engine with a single test.

  The guard fix is what actually removed the danger. The junction was hazardous *because the guards
  lied*: a broken junction meant 88 silent passes and a gate reporting green on nothing, which is how
  T01 merged in run-20260817-1157. Now a broken junction is 88 visible skips, and
  `_refuse_a_baseline_that_skipped_the_data_it_junctioned` stops the run rather than letting it
  proceed on half a suite.

  Revisit only if the remaining backlog stops touching `Working/execution.py` and `UI/viewer/`, or if
  an agent actually damages the junctioned data. Reversing is one line in `config.toml`, and the
  baseline check already handles both configurations.
- [fixed] **The 88 `_channel_available()` guards now skip instead of returning.** A test that returned
  early reported as *passed*, so absent data read as green rather than as skipped — and the
  orchestrator gates every ticket on "no regressions against the baseline" with both sides measuring
  the same vacuum. All 88 call sites across ten files now call `pytest.skip`. Three things had to move
  with them: none of the ten files imported pytest; `Skipped` derives from `BaseException` rather than
  `Exception`, so each file's standalone `_run_all` would have aborted on the first guarded test; and
  that runner now prints its skip count rather than folding skips into the pass total.
  `tests/test_channel_guards_are_honest.py` is the standing guarantee — a `return` is one careless
  edit away from coming back and nothing else in the suite would notice. With the data present the
  conversion is a no-op: 591 passed before, 632 after (591 + 41 new guard tests), 0 skipped.
- [open] **`UI/window_matrix_panel.py` still leaks background `_worker` threads** that outlive their
  test and touch SQLite from the wrong thread. Raised 2026-08-18, unchanged.
- [fixed] **The stall retry now provides the clean worktree it promises.** `RETRY_PREFIX` told the
  agent "you are starting again from a clean worktree, so do not assume any of its work exists" while
  `_run_agent_with_retry` handed it the same half-edited tree the previous attempt stalled in.

  Fixed by teardown-and-reprovision, **not** by the `git reset --hard` plus `git clean -fd` this entry
  originally proposed. `clean` is a recursive delete aimed at a tree containing a junction to 317 MB of
  shared recording data. It is safe today only because `DATA/*` is gitignored and `clean` without `-x`
  honours that — a one-line dependency, in a repo that has already had a near-miss where a recursive
  walk followed exactly that junction and would have deleted its target. `teardown()` is the code that
  already knows to unlink junctions before anything recursive runs, so the fix reuses it rather than
  opening a second route to the same cliff.

  Safe only because a stall means zero commits by construction: `classify_exit` grades a timeout that
  *did* produce commits as `ok` and sends it to the gates, precisely so the run loop never discards
  work. That precondition is asserted rather than assumed — with commits present
  `_reprovision_for_retry` refuses and leaves the worktree alone.
- [watch] **`agent.output_format = "stream-json"` has not met the real CLI.** The parsers degrade
  deliberately — an unrecognised schema yields "no usage recorded" and returns the transcript
  untouched, so the worst case is the cost column staying empty. But the first real run should be
  checked for a populated `tokens` column before trusting the numbers.


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

## T29 — 2026-08-25 03:27

- [major] [standards] (rule 6.4) `block.name.split(".",1)[1]` in builder.py duplicates the same one-liner in UI/analyse/execution.py and UI/analyse/derive.py
- [minor] [standards] (rule 6.2) _delete_step's ChainStateError handler is unreachable/untested since this surface never sets side_inputs yet
- [minor] [spec] (no rule cited) "compose the three worked chains without blanking" AC is currently unsatisfiable — registry lacks train_cnn/seeded_score/banded_score adapters, a gap outside this ticket's files
- [minor] [spec] (no rule cited) ticket's "relocates and extends RunPanel's staged-list behaviour" note points at unrelated prior art (span basket / single-algorithm select, not a step chain); building ChainBuilder fresh atop ChainState is the correct reading, not a missed relocation

## T15 — 2026-08-25 13:54

- [major] [standards] (rule 6.1) test fixture name "t15_scores_probe" doesn't convey it's a side-input-dependent probe
- [minor] [standards] (rule 6.3) comment on skipping persist on cache hit restates the condition instead of explaining the rationale
- [minor] [standards] (no rule cited) _TYPED_VALUE_CLASSES in execution.py duplicates the type-name-lowercasing already done by TYPE_KINDS in Adapters/base.py
- [minor] [spec] (no rule cited) force=True on execute_recipe does not bypass the per-step cache, silently defeating the "recompute even if exists" contract
- [minor] [spec] (no rule cited) cached Signal round-trip loses t and reconstructs it from the live loop variable; correct only because no current signal-output adapter changes array length

## T16 — 2026-08-25 14:10

- [major] [standards] (rule 6.4) motif_browser.py _on_save_motif re-derives detection→run→recording by hand instead of calling runs.py::insert_motif, duplicating logic across modules
- [minor] [spec] (no rule cited) vocabulary.py edited outside the ticket's declared file list, though necessary to support motif_entry_tags
- [minor] [spec] (no rule cited) tag-linking (set_motif_entry_tags) is duplicated across all 4 save call sites rather than folded into the "one entry-creation helper", contrary to the "Why [O]" risk note
- [minor] [spec] (no rule cited) insert_motif_entry's INSERT OR IGNORE silently discards label/rating/notes/sax_string updates on a re-save to an already-occupied span while still reporting success; untested

## T24 — 2026-08-25 14:31

- [major] [standards] (rule 1.4) schema.py edited outside declared file list; additive/idempotent and consistent with existing run-row columns, but the touch wasn't proactively flagged
- [minor] [standards] (no rule cited) _last_step_results initialized in _on_run instead of RunPanel.__init__, breaking the file's stated convention that shared run state lives in __init__
- [minor] [standards] (rule 6.2) _last_step_results dict is written per-stage but never read anywhere in the tree; possible speculative generality unless it's groundwork for the ticket this one unblocks
- [minor] [spec] (no rule cited) Working/database/schema.py is touched but absent from ticket 24's declared files list; change is a necessary, additive consequence of AC1 but should have been called out explicitly

## T36 — 2026-08-25 14:52

- [minor] [standards] (no rule cited) Data Clumps: edge natural key (member_a_id, member_b_id, distance_function, threshold, recipe_hash) travels together across insert_motif_edge/get_motif_edge; defensible in a plain-SQL accessor layer
- [minor] [standards] (no rule cited) Duplicated Code: mmap-slice load pattern appears in both Working/library.py:_load_span and the recompute test's independent reload; acceptable since the test must not depend on the code it's verifying
- [minor] [spec] (no rule cited) get_or_create_motif_member's docstring claims member identity is enforced by the 4-tuple key, but motif_member has no UNIQUE constraint at the schema level — idempotency holds only through this one code path, and schema.py is outside T36's declared file list so a fix is arguably a different ticket's job

## Harness — 2026-08-25 (post-run-20260825-1310)

4 merged of 6 dispatched. 31.12M tokens, $22.44 total, $4.24 of it on work that did not land. Written by the runner; the triage below is not.

- [ ] **T19** GATING (no exit class, gate: —) — Adjudication store and divergence queries
- [ ] **T25** GATING (no exit class, gate: —) — Scope selection and run-group fan-out

For each: was this the ticket, or was this the harness? A harness cause belongs in the runner's own tests before the next run.

### Triage — all three landed by hand, none was a bad ticket

**T11 — harness.** Held on `_run`, which is the adapter entry-point
convention: twenty shipped adapters already define it and T11 adds a
twenty-first (`Adapters/catalogue_cluster.py`). A per-module convention name
is not two implementations of one idea, which is what the gate exists to
catch. Every future adapter ticket will hit this. Merged at d16f675.

- [ ] [major] `orchestrator/gates/overlap.py` compares module-private
  top-level symbols across the whole tree. Adapters are required to define
  `_run`, so the gate reports a collision for doing the thing the contract
  demands. Adding `Adapters/` to `[overlap] ignore_paths` would fix this case
  and hide genuine adapter collisions with it; scoping the comparison to
  symbols within one module path is the narrower fix. Same shape as the
  `_run_all()` test-footer false positive already fixed by `ignore_paths`.

**T34 — harness.** Held on `_fmt_seconds`, which T34 never wrote. It *moved*
`UI/window_matrix_panel.py` to `UI/workspaces/analyse/window_matrix.py`; the
symbol travelled with the file, and the gate read the rename as an addition.
Merged at 8af1bcf.

- [ ] [major] The overlap gate does not detect renames. `git diff -M` would
  tell it the symbol is the same one that already existed.
- [ ] [minor] The duplication the gate pointed at is nonetheless real, and is
  now inside one package: `_fmt_seconds` is defined in both
  `UI/workspaces/analyse/run_surface.py` (T31) and
  `UI/workspaces/analyse/window_matrix.py` (pre-existing, relocated by T34).
  One should import the other.

**T41 — neither, but it exposes a gap.** Every gate passed; it failed at
merge as `conflict`, because T39 and T40 landed first and touched the same
two places. `Working/library.py` took appended functions from both. And both
T39 and T41 independently created `UI/workspaces/library/detail.py` for
unrelated classes — `EntryDetail` and `CrossChannelClassifier`. T41's class
is now `cross_channel.py`. Merged at 884cbd0, nothing dropped.

- [ ] [major] The overlap gate compares symbols, not paths, so two tickets
  creating the *same file* with *different* symbols passes it cleanly and
  fails later at merge, after the full budget has been spent. A path-level
  check would have held T41 in the same cheap way T11 and T34 were held.


## Harness — 2026-08-25 (post-run-20260825-1310)

4 merged of 6 dispatched. 31.12M tokens, $22.44 total, $4.24 of it on work that did not land. Written by the runner; the triage below is not.

- [ ] **T19** GATING (no exit class, gate: —) — Adjudication store and divergence queries
- [ ] **T25** GATING (no exit class, gate: —) — Scope selection and run-group fan-out

For each: was this the ticket, or was this the harness? A harness cause belongs in the runner's own tests before the next run.

## T25 — 2026-08-25 16:15

- [major] [standards] (rule 4.2) test_band_fan_out_reuses_existing_band_definitions only borrows SPIKE_TRAIN_BANDS label strings, doesn't exercise real integration with bands.py
- [major] [standards] (rule 6.1) run_groups.py docstring implies reuse of Working.database.bands vocabulary that the production code never actually consults
- [minor] [standards] (rule 6.2) get_run_group() is defined but unused anywhere in this diff - speculative generality ahead of ticket 10's need
- [minor] [standards] (no rule cited) baseline smell Primitive Obsession: band target {label, low_hz, high_hz} travels as a bare dict with no shared type/validator
- [minor] [spec] (no rule cited) "Existing band definitions ... reused, not redefined" acceptance criterion met only cosmetically - production path never imports/enforces Working.database.bands, and no pre-existing frequency-band vocabulary exists in the repo to reuse
- [minor] [spec] (no rule cited) band branch of _normalize_fan_out raises KeyError instead of ValueError when low_hz/high_hz are missing, inconsistent with the rest of the function's error handling

## T21 — 2026-08-25 18:10

- [minor] [standards] (no rule cited) Dead `import pytest` in tests/test_review_surface.py:35, never used
- [minor] [standards] (no rule cited) `_load_recording`'s recording-is-None branch leaves stale `_dmap`/`_range_stream`/`_x` from a prior recording instead of resetting them

## T31 — 2026-08-25 18:15

- [minor] [standards] (no rule cited) summary
- [minor] [standards] (no rule cited) _recording_n_samples/_recording_fs reach three attrs off self.app plus a DB fallback (possible Feature Envy, minor)
- [minor] [standards] (no rule cited) fan-out scope passed as raw dict rather than a small type (possible Primitive Obsession, consistent with existing recipe-dict convention)

## T22 — 2026-08-25 18:45

- [major] [standards] (rule 6.4) Verdict-shortcut widget/JS pattern in surface.py near-duplicates UI/viewer/shortcuts.py's ShortcutsMixin (same hidden-button helper, same KEY_MAP/keydown JS, same focus guard/dispatch, same window handler-reattach idiom) instead of sharing one helper.
- [major] [standards] (rule 7.1) note_input and its wiring into _on_verdict is behaviour not named in T22's acceptance criteria (which are limited to five verdict keys, one-keystroke advance, undo, focus-guard, no-collision, 50-candidate soak).
- [major] [standards] (rule 4.5) tests/test_review_keyboard.py is new and outside the ticket's declared file list, but matches the 4.5-mandated headless surface-construction test and the established test_shortcuts_and_view_controls.py precedent — judged justified, not an invented fourth seam under 4.4.
- [major] [standards] (rule 4.2) test_key_listener_ignores_text_fields asserts JS source substrings ("document.activeElement", "INPUT") rather than behaviour, bordering on 4.2's "transcription of implementation"; mitigated by the same technique being pre-established in the sibling Explore test file for the same stated reason.
- [minor] [spec] (no rule cited) Ticket carries flags:['human-verify'] and the "person adjudicates fifty real candidates" criterion; the diff satisfies it only via a headless simulated-click test over synthetic data, with no note that the human-verify half remains outstanding.
- [minor] [spec] (no rule cited) note_input/note-saving behaviour is not named anywhere in T22's acceptance criteria (spec-level scope creep), though it reuses an existing note column/param from tickets 19/20.

## T07 — 2026-08-25 18:52

- [minor] [spec] (no rule cited) "Existing tests ... pass unmodified" is in tension with the edit to tests/test_adapter_spec.py's remapped_by_ticket_07 allow-set; resolved by T06 precedent (same shared-guard-test mechanism), read as referring to per-adapter test files rather than the shared registry guard.

## T32 — 2026-08-25 19:20

- [major] [standards] (rule 6.4) progress text rebuilt twice in-file (tested _update_* methods vs. untested worker-thread closures) instead of closures calling the tested methods
- [major] [standards] (rule 1.4) _stage_label hardcodes "preprocessing.bandpass", echoing Working/run_groups.py's fan-out step instead of deriving from it
- [minor] [standards] (no rule cited) _describe_result's output_kind cascade repeats the shape of similar switches in Working/execution.py and UI/analyse/execution.py (Repeated Switches, baseline smell)
- [minor] [spec] (no rule cited) the only live-launch test for "earlier stage stays inspectable while later runs" (criterion 3) uses a single-step chain; the two-stage version bypasses the worker-thread/on_step_result path entirely
- [minor] [spec] (no rule cited) intra-step progress test calls _update_intra_step_progress directly rather than through execute_recipe's real run_kwargs forwarding, so no test proves an adapter's on_progress reaches the pane end-to-end
- [minor] [spec] (no rule cited) a fully-cached recipe rerun returns before the step loop in Working/execution.py, so on_step_result never fires and stage_results stays empty despite "Done" status — root cause is out-of-scope for this ticket's file list but affects criterion 3/4
- [major] [spec] (rule 7.1) per-target "(target X)" heading suffix is a reasonable but unspecified addition beyond the literal acceptance criteria

## T33 — 2026-08-25 19:36

- [major] [standards] (rule 6.1) Working/compare.py defaults iou_threshold to SIMILARITY_IOU_THRESHOLD, a constant named/scoped for annotation-duplicate warnings, reused undocumented for run-set overlap comparison
- [minor] [standards] (no rule cited) UI/workspaces/__init__.py imports CompareSurface from the analyse.compare submodule, contradicting analyse/__init__.py's stated "import from here, not a submodule" convention
- [minor] [standards] (rule 6.2) tests/test_compare.py adds a hand-rolled _run_all()/__main__ test runner duplicating pytest, unrequested machinery
- [minor] [standards] (no rule cited) CompareSurface._route_to_review reaches through app.review_surface.queue and app.review_surface.on_tab_activated via getattr guards, borderline Feature Envy/Message Chain

## T43 — 2026-08-25 20:00

- [minor] [standards] (no rule cited) _run seeds with np.random.RandomState while every stochastic site in Working/ uses np.random.default_rng; no rule mandates either but it diverges from repo convention
- [minor] [standards] (no rule cited) Adding the adapter forced a companion edit to tests/test_adapter_spec.py (count bump + new membership set) — Shotgun Surgery smell, though arguably inherent to that test's role as a registry-completeness guard

## T38 — 2026-08-25 20:15

- [minor] [standards] (no rule cited) motif_browser.py's layout() now changes for two unrelated reasons (motif-browsing UI vs Library-workspace tab composition) — Divergent Change smell.
- [minor] [standards] (no rule cited) grid.py repeats review/surface.py's 2-line single-occurrence-group dict-literal glue before calling build_motif_waveform_overlay — cosmetic Duplicated Code smell.
- [major] [spec] (rule 4.5) LibraryGrid is instantiated unconditionally inside MotifBrowser.__init__, but no test asserts the composed MotifBrowser.layout() (the actual Library surface) returns non-None panes — only LibraryGrid is tested standalone against a fake app.
- [minor] [spec] (no rule cited) "Absorbing" the motif browser was implemented as a hand-rolled nested pn.Tabs inside MotifBrowser.layout() instead of registering "Library grid" as a second section through the existing UI/workspaces registry, bypassing the sibling-registration pattern used elsewhere.

## T48 — 2026-08-25 23:46

- [major] [standards] (rule 3.3) T48 edits frozen Adapters/base.py to remove legacy output-kind vocabulary; rule 3.3 blocks base.py edits outside ticket 10, but its second sentence scopes the blocker to "an adapter ticket" and T48's own acceptance criteria mandate the removal
- [major] [standards] (rule 4.4) tests/test_end_to_end.py is a new file rather than an extension of an existing seam-test file, though the ticket explicitly names it as a deliverable
- [minor] [standards] (no rule cited) Adapters/base.py's intervals field comment calls it a "legacy carrier" though it is still actively read by several detection adapters' plot helpers (Mysterious Name/comment smell)
- [minor] [spec] (no rule cited) AC "gone from the tree, not merely unused" is not fully met: an archived snapshot directory still contains references to the deleted import_10min_labels.py path and the removed output_kind == "intervals" vocabulary

## T37 — 2026-08-25 23:51

- [major] [standards] (rule 6.1) _SEED_VERDICT round-trips the literal "seed" through VERDICTS.index()/[]; comment claims it avoids a second copy of the term but the literal key is still hardcoded
- [major] [spec] (rule 7.1) test_non_seed_annotation_does_not_create_a_library_entry is not asked for by any acceptance criterion; defensible as regression coverage for the seed-only behaviour, but arguably scope beyond what was requested

## T40 — 2026-08-26 00:25

- [major] [standards] (rule 5.2) recording_id hashed by row id, not content, in the search recipe dict
- [minor] [standards] (no rule cited) "recall" field is a raw match count, not a normalized recall rate (Mysterious Name)
- [minor] [standards] (no rule cited) recording fetched from DB twice for the same entry in detail.py (Duplicated Code)
- [minor] [standards] (no rule cited) nested duration/start loop reloads exemplar .npy from disk per candidate window
- [minor] [spec] (no rule cited) AC4 control test only asserts strictly-fewer matches, doesn't guard against a degenerate zero-recovery control
- [minor] [spec] (no rule cited) self-overlap not excluded beyond exact span match; default UI search-to-own-recording can write spurious self-similarity matches as real results

## Harness — 2026-08-26 (post-run-20260825-1528)

25 merged of 28 dispatched. 192.26M tokens, $126.52 total, $12.19 of it on work that did not land. Written by the runner; the triage below is not.

- [ ] **T11** OVERLAP (no exit class, gate: overlap) — New adapter: clustering to a Grouping
- [ ] **T34** OVERLAP (no exit class, gate: overlap) — Fold run history and the window-matrix panel into Analyse
- [ ] **T41** FAILED (conflict, gate: —) — Cross-channel classification

For each: was this the ticket, or was this the harness? A harness cause belongs in the runner's own tests before the next run.

## T46 — 2026-08-26 06:21

- [major] [standards] (rule 1.3) gather_entry_members/entry_edges_by_member placed in export.py rather than library.py, defensible given T46's declared file list but worth a note for future cross-file work
- [minor] [standards] (no rule cited) _copy_entry_plots duplicates _copy_plots's makedirs/isfile/used-names dedup logic within the same module instead of a shared helper
- [minor] [standards] (no rule cited) _build_library_entry_manifest hand-rolls the envelope (manifest_version/code_version/created_at) instead of calling a shared envelope builder, unlike export_run_group which calls M.build_manifest
- [minor] [spec] (no rule cited) export_library_entry replaces ticket 27's "runs" envelope key with a differently-shaped "entry" key rather than nesting alongside it, a structural deviation from the documented manifest schema
- [major] [spec] (rule 6.4) bins dict hardcodes the three classification-bin strings instead of importing BINS/ARTIFACT/PROPAGATION/INDEPENDENT_RECURRENCE from Working/cross_channel.py, re-declaring vocabulary owned by another module

## Harness — 2026-08-26 (post-run-20260826-0543)

1 merged of 2 dispatched. 10.22M tokens, $6.67 total, $2.05 of it on work that did not land. Written by the runner; the triage below is not.

- [x] **T12** FAILED (stall, gate: —) — New adapter: classifier training to a Model

For each: was this the ticket, or was this the harness? A harness cause belongs in the runner's own tests before the next run.

**T12 — the ticket, and neither attempt was wasted.** Both agents stopped without committing and
reported the same thing, correctly: the ticket's AC1 and AC5 are mutually exclusive. AC1 asks for
`input_kind="WindowSet"` with a `Grouping` side input; AC5 asks for `window_matrix -> cluster ->
classifier` to validate. `Working/chain_validation.py` types a chain as a linear spine, so a step
whose primary input is a `WindowSet` can never follow one that produces a `Grouping`, and no
ordering of those three specs validates. The agents did exactly what `CLAUDE.md` "When to stop"
tells them to do when a ticket contradicts the PRD, and they were right to.

Resolved by hand on 2026-08-26 in favour of AC5: the PRD's own statement of the chain ("the typed
chain from signal through window set and grouping to a model") and the already-shipped
`test_chain_validation.py::test_cnn_chain_validates_end_to_end` both pin
`signal -> windowset -> grouping -> model`, so AC1's ordering was the odd one out. The classifier's
primary input is the `Grouping`; the `WindowSet` is the side input bound to the earlier
window-matrix step. AC2's design requirement survives the correction untouched — `run` still never
asks where its labels came from.

Two harness observations worth acting on before the next run:

- [ ] **A correct stop costs a full retry.** The runner re-dispatched T12 verbatim after attempt 1
      stopped on a ticket/PRD contradiction, and attempt 2 produced a near-identical report for
      another $1.03. A stop-and-report with no commits and no gate failure is not a stall and should
      not be retried on the same unchanged ticket — it should exit as its own class (`contradiction`,
      say) that lands in `REPORT.md` under "Waiting on you" rather than under losses. The exit
      classifier currently has no way to tell "the agent gave up" from "the agent found a real
      blocker and said so", and those want opposite handling.
- [ ] **`exit_class: "stall"` mislabels this in the report.** Same lesson as the `out of extra usage`
      fix above: the classification was wrong *and* the consequence was wrong, and only the
      consequence costs money. Test what the run loop does with the verdict, not just the verdict.
- [ ] **Ticket-level: nothing checks a ticket's ACs against the type system before dispatch.** T12's
      contradiction was statically decidable from `docs/tickets/T12*.md` plus the registry — AC1
      names the input and output kinds, AC5 names the chain. A pre-flight that resolves an AC-named
      chain through `validate_chain` would have caught it before spending $2.05 on discovering it
      twice.

## T10 — 2026-08-26 (worked by hand, not by the runner)

Implemented directly rather than dispatched, because the ticket's declared file list
(`["Adapters/base.py"]`) described a fraction of its own acceptance criteria. AC2 — "every adapter
populates `value` only" — reaches 16 adapter modules, `Working/execution.py`,
`Working/side_inputs.py`, three UI modules and eight test files. Dispatched as written, on `haiku`
at `size: S` / 30 minutes, it would have come back either quarantined or carrying ~30 scope
deviations. The file list is now corrected in the ticket.

- [ ] **The scope gate cannot see this class of mismatch, and it is the cheapest one to catch.** A
      ticket whose `files` list is smaller than its ACs imply is detectable before dispatch, not
      after: T10's AC2 names `AdapterResult` fields, and every module that reads one is a `grep`
      away. Worth a pre-flight check that greps the ACs' named symbols and warns when the hits fall
      outside `files` — the same shape as the T12 suggestion above (resolve an AC-named chain through
      `validate_chain`), and both are static.
- [ ] **`_load_cached_result` built a legacy `signal` result and nothing caught it.** The step cache
      only engages above `STEP_CACHE_WRITE_THRESHOLD_S`, so no test in the suite restores a cached
      *signal* step — the one path that would have crashed. Found by grepping constructor call sites,
      not by a failing test. A step-cache test that forces a signal step through a round trip
      (threshold 0) would close it.
- [ ] **Signal blocks must preserve the sample count, and now that is checked rather than assumed.**
      Previously each adapter passed `t` through by hand, so a block that resampled would have
      silently misaligned every downstream plot against the channel. `execute_recipe` now refuses it
      with a message naming both lengths. No shipped block violates it.

## T57 — 2026-08-27 08:53

- [major] [standards] (rule 6.4) builder.py's _first_invalid_junction duplicates the chain-walk already in Working.chain_validation.validate_chain
- [major] [standards] (rule 1.3) junction-location capability belongs in chain_validation.py (its stated purpose) but was added to the UI renderer
- [minor] [standards] (no rule cited) baseline Data Clump: (index, producing_kind, block) tuple returned/unpacked positionally by _first_invalid_junction
- [minor] [spec] (no rule cited) multi-step construction test never calls builder.layout() to assert non-None, only inspects steps_row/cards directly
- [minor] [spec] (no rule cited) builder.py reimplements chain_validation.py's chain-walk rather than reusing it, risking future drift between the two traversals
- [minor] [spec] (no rule cited) unregistered-adapter edge case falls back to an un-named generic invalid-chain message even if a later junction is the real type break

## T50 — 2026-08-27 09:36

- [minor] [standards] (no rule cited) npy_path in _ensure_recordings is set to the raw source_file string (e.g. "CH0.npy"), contradicting its own docstring claim of a materialised per-channel path; masked by a test fixture that pre-creates valid recordings before the importer runs
- [minor] [standards] (no rule cited) grouping/aggregation logic in _ensure_recordings (group by source_file/channel, max snippet_end_idx) is duplicated in shape by the test's _precreate_recordings fixture
- [minor] [spec] (no rule cited) on a fresh database (the ticket's own stated starting condition) the importer writes a recording row whose npy_path is a bare unresolvable filename; LibraryGrid's unguarded load_channel_mmap then raises FileNotFoundError, contradicting "the existing Library grid renders the imported entries without modification" and "a card that cannot be traced back to the signal is not evidence" — the included test avoids this path via a fixture that pre-seeds valid recordings before calling the importer
- [minor] [spec] (no rule cited) spike-train identity (span_key) is not 1:1 with recording_id and is never persisted onto motif_member, so the ticket narrative's "provenance must survive... the spike train it came from... its morphology and purity" is unmet, though the checkbox acceptance criteria and the PRD's Library-import subsection don't require it

## T56 — 2026-08-27 10:12

- [minor] [spec] (no rule cited) Unknown-type error names type_kind, not the literal value object — a faithful but debatable reading of "naming the value it was given"

## T52 — 2026-08-27 10:57

- [minor] [standards] (no rule cited) importer.py bypasses the single-writer convention (raw UPDATE on motif_entry.scale after insert_motif_entry) instead of extending the writer, duplicating the 3-line SQL pattern twice in one file
- [minor] [standards] (no rule cited) _write_train_entries re-derives (source_file, channel) keys into recording_map already computed by the caller (mild feature envy)
- [minor] [spec] (no rule cited) insert_motif_entry's INSERT-OR-IGNORE-and-return-existing-id means a train bounding box that coincides with an existing event-scale entry's span silently relabels and re-parents that entry to scale='train', violating "Event-scale entries from T50 are unaffected and still resolve" for cluster cuts other than the one exercised by current tests

## T62 — 2026-08-27 11:05

- [minor] [standards] (rule 6.2) `_render_filmstrip_input`'s `recording`-only fallback branch is unexercised by any caller — speculative generality
- [minor] [standards] (no rule cited) Duplicated Code smell: `result_pane.visible`/`filmstrip_pane.visible` toggle pair repeated verbatim in `_refresh_preview`, `_show_before_after`, `_show_filmstrip`
- [minor] [spec] (no rule cited) Filmstrip is never called from `execution.py:_on_run_finished` — a real Run never shows the filmstrip, only the old single-plot/Before-After pane; core acceptance criterion unmet in the live app
- [minor] [spec] (no rule cited) The untested `recording`-fallback path in `_render_filmstrip_input` is unverified and, given the wiring gap, currently unreachable in production

## T59 — 2026-08-27 12:11

- [major] [standards] (rule 6.4) Side-input picker methods in _BlockCard are copied near-verbatim from BlockInspector in inspector.py rather than extracted into a shared module
- [major] [standards] (rule 6.4) _record_recommended_preserving_edits reimplements the recommendation-bookkeeping core of DeriveMixin._apply_recommended_defaults as a parallel path instead of extending the shared mixin
- [minor] [standards] (no rule cited) Data Clumps: the source/target/exemplar widget triple and the side-input binding dict travel together across methods in both builder.py and inspector.py and arguably want a named type
- [minor] [spec] (no rule cited) Side-input pickers are reimplemented on the card rather than imported from a shared module, contra the PRD's "relocation, not reimplementation" framing for the inspector's whole content
- [minor] [spec] (no rule cited) Cached-result display, part of the inspector's "whole content" the PRD says moves onto the card, is not relocated to _BlockCard (outside this ticket's stated acceptance criteria, so arguable)

## T53 — 2026-08-27 12:30

- [major] [standards] (rule 6.4) grid.py hand-rolls an hv.Curve shape closely mirroring _decimated_curve's documented "ONE renderer" pattern instead of reusing/generalising it
- [minor] [standards] (no rule cited) _build_card and _family_data_bounds each re-fetch the same recording row per entry, and _load_span re-slices the same span twice (range calc + thumbnail)
- [minor] [spec] (no rule cited) commit f054a47's sax-string-less fallback family key (imported entries) ships with no test; both new tests only cover entries with real sax_string values
- [minor] [spec] (no rule cited) "thumbnails render the detrended trace" is assumed via the unchanged recording["npy_path"] load path, not established or verified by this diff
- [major] [spec] (rule 7.1) _Y_PAD_FRACTION, xlabel/ylabel, and responsive=True are additions not traceable to any acceptance criterion or PRD line

## T63 — 2026-08-27 12:44

- [minor] [standards] (no rule cited) invalidated_step_indices(recipe, step_index) mirrors _recipe_prefix_hash's (recipe, up_to_index) parameter shape — consistent with existing module convention, flagged as a Data Clumps judgement call only

## T69 — 2026-08-27 16:05

- [minor] [standards] (no rule cited) Compare reaches into builder.py's private (_-prefixed) card-rendering surface instead of a purposely-exposed method
- [major] [standards] (rule 6.1) _ReadOnlyCardApp implies read-only but rendered cards keep live move/delete/param-edit controls wired to a throwaway chain
- [minor] [standards] (no rule cited) _builder_for_recipe builds a full ChainBuilder (running __init__'s _refresh()) only to discard it and reach one method
- [minor] [standards] (no rule cited) test's _is_highlighted hardcodes the highlight hex colour, duplicating a cosmetic literal between prod and test
- [minor] [spec] (no rule cited) Reusing the builder's card wholesale leaves live edit affordances (↑/↓/Delete, param widgets) on what the spec frames as a read-only comparison canvas
- [minor] [spec] (no rule cited) Diff highlighting marks the step card but not the connecting arrow/placeholder distinctly for added/removed steps

## Harness — 2026-08-27 (post-run-20260827-0811)

17 merged of 21 dispatched. 84.12M tokens, $60.84 total, $7.48 of it on work that did not land. Written by the runner; the triage below is not.

- [ ] **T64** FAILED (red-at-exit, gate: suite) — Re-run only the suffix when a parameter changes
- [ ] **T65** DEFERRED (infrastructure, gate: —) — Focus one block, with a per-adapter detail view
- [ ] **T66** DEFERRED (infrastructure, gate: —) — Run a single algorithm as a one-block chain
- [ ] **T70** DEFERRED (infrastructure, gate: —) — Collapse the run-history sidebar to a ribbon

For each: was this the ticket, or was this the harness? A harness cause belongs in the runner's own tests before the next run.

## T65 — 2026-08-29 12:22

- [minor] [standards] (rule 6.2) _build_focus handles list/tuple/bare-element return shapes from detail_view that no hook in this diff exercises
- [minor] [standards] (no rule cited) _install_sax_detail_view_hooks mutates shared registry AdapterSpec state as a side effect of widget construction (Feature Envy/Divergent Change)
- [minor] [standards] (no rule cited) _show_focus has no caller anywhere in this diff or its tests (mild Speculative Generality)
- [minor] [spec] (no rule cited) _build_focus/_show_focus implement focus mode but no UI trigger (button/click handler) wires it up in this diff, so it isn't yet reachable by a user

## T70 — 2026-08-29 12:34

- [minor] [standards] (no rule cited) bind_sections duplicates the "resolve active index → is it Chain builder" logic inline and in its watcher closure
- [minor] [standards] (no rule cited) literal "Chain builder" string is duplicated across builtins.py and history.py with no shared constant, so renaming the section silently breaks the collapse default
- [major] [standards] (rule 1.3) UI/workspaces/__init__.py keeps changing for two reasons: generic sidebar-registration machinery and Analyse-specific run_history wiring
- [minor] [standards] (no rule cited) test_analyse_workspace_builds_with_sidebar_in_each_state sets collapsed and calls private _render() directly instead of going through toggle()/section-change, so it wouldn't catch a regression in the real trigger paths
- [minor] [spec] (no rule cited) register_sidebar's factory signature changed from factory(app) to factory(app, content), a non-additive change to a shared registration seam, even though only Analyse uses it today
- [minor] [spec] (no rule cited) bind_sections silently no-ops if content is not a pn.Tabs, so a future single-section Analyse would default to always-expanded with no diagnostic

## Harness — 2026-08-29 (post-run-20260827-0811)

20 merged of 21 dispatched. 89.39M tokens, $68.19 total, $7.48 of it on work that did not land. Written by the runner; the triage below is not.

- [ ] **T64** FAILED (red-at-exit, gate: suite) — Re-run only the suffix when a parameter changes

For each: was this the ticket, or was this the harness? A harness cause belongs in the runner's own tests before the next run.

## T65 / T70 follow-ups actioned — 2026-08-30

All ten findings above are addressed; the notes stay as the record of what was
found. Not a re-review — the fixes carry their own tests.

**T65**
- The [spec] finding was the real one: `_build_focus`/`_show_focus` had no
  caller, so focus mode existed and no researcher could reach it. Each block
  card now carries a "Show algorithm" control that focuses that step on the run
  surface and brings that section forward, plus a "Back to all steps" control so
  focus is not a dead end. Fixing it surfaced a second gap the merged tests
  missed: focusing step 0 needs the recording, because its input is the chain's
  ROOT signal rather than a previous step's output. The merged test only focused
  step 1 and so never loaded a root signal.
- `_install_sax_detail_view_hooks` no longer runs from `_build_result_widgets`.
  Mutating the shared adapter registry as a side effect of constructing a widget
  meant two run panels installed it twice and any consumer that had not built
  one saw adapters with no hook. It runs once at module import.
- `_build_focus`'s list/tuple branch is gone (rule 6.2). The documented contract
  is one element or one Layout; a hook wanting several stacks them itself.

**T70**
- [major, rule 1.3] `analyse_sidebar` moved out of `UI/workspaces/__init__.py`
  into the Analyse package. That module owns generic sidebar-registration
  machinery; deciding what Analyse's own sidebar does is not its job.
- `CHAIN_BUILDER_SECTION` is defined once, beside the section table that names
  it. The literal was duplicated, so renaming the section would have silently
  stopped the sidebar collapsing with nothing failing.
- `bind_sections` and its watcher shared one `_apply_section_default`; they
  resolved the active index and compared the label separately before.
- `bind_sections` raises on non-Tabs content instead of returning quietly. A
  binding that cannot bind is a wiring error, and silent ones are how a surface
  goes missing.
- The acceptance test drove `_render()` directly and so could not catch a
  regression in the trigger. Replaced by tests that drive `pn.Tabs.active` and
  `toggle()` — the two paths a user actually takes.
