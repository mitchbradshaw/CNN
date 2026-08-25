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
