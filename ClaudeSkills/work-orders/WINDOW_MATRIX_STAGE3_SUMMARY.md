# Window matrix — Stage 3 (UI), verification, and cleanup — summary

Autonomous run against `WINDOW_MATRIX_STAGE3_PROMPT.md`. Read this before reading any code.

---

## 1. What now works

The Stage 1/2/4 window-matrix code (storage format, cost model, adapter, backfill script) that a
prior session wrote against copied code in an isolated sandbox now actually imports and runs
correctly in this environment, with one real bug fixed. On top of that, Stage 3 is built: a new
`UI/window_matrix_panel.py` component, composed into the Run panel's sidebar and hidden unless
`preprocessing.window_matrix` is the selected algorithm, renders the four-scale timescale ladder
with per-state affordances (Compute / Resume / Recompute / greyed-invalid), shows a cost estimate
and routing tier computed from whichever measure stages the user has actually checked, runs
interactively or in the background through `Working.execution.execute_recipe` with live per-window
progress and a working Cancel button, and can export an HPC job script instead of running locally.
Alongside it, `UI.plots.build_window_matrix_ribbon` (factored out of the existing reviewed-coverage
ribbon's bucketing code, not copied) draws one coverage-ribbon pane per ladder scale that has any
stored coverage anywhere in the channel, stacked under the staged-span preview, correctly showing a
real gap between disjoint spans, a fully-aligned band when zoomed into a covered region, and a lane
background (not a blank pane) when zoomed into a region a given scale hasn't covered — all three
verified with actual Playwright screenshots, not just Python-level object inspection. The
infinite-resubmit bug the design brief centers on (§0.2: NaN meaning both "not yet computed" and
"computed, NaN") is closed at both ends: the old `build_window_matrix.py` is now a thin, tested
shim over the new resumable builder + storage layer, and `HPC/Preprocessing/wm_job.sh` resubmits on
`wm_status.py`'s exit code (derived from the artifact's own `computed` mask) rather than grepping
`--status` text. One real HPC job was generated with `export_wm_job` and inspected by hand against
every item in the work order's checklist; all of them check out. 39 test files now pass cleanly
(five of them new), covering every piece touched.

---

## 2. DECISIONS

Ordered roughly as they came up.

**Commit scope was limited to window-matrix files, not the whole uncommitted tree.** The repo had a
large amount of *other* pre-existing uncommitted work sitting in the working tree at the start of
this run — DSAX experimentation, matrix-profile UI files, a catalogue-import pipeline, several
`Adapters/*.py` files unrelated to window matrix, etc. — none of it mentioned by this work order.
Rather than bundling all of that into my commits (which the prompt's "commit as you go" instruction
could be read to imply), I `git add`ed only the exact files this work order's sections touch, for
every commit. Reason: committing unrelated, unreviewed work under a window-matrix commit message
would misrepresent what changed and risk the operator losing track of what's actually been
reviewed. **Reverse:** `git log --oneline` shows six commits, each scoped to one or two sections;
the rest of the tree is exactly as it was found, still uncommitted.

**`WindowMatrix.is_full_window` fixed to return a Python `bool`, not `numpy.bool_`.** Found via
`tests/test_window_matrix_store.py`'s one failing test on first run
(`test_partial_tail_opt_in_restores_the_overhang`). The comparison `start_idx + window_samples <=
len(x)` involves a numpy int64 (from a DataFrame index), so the bare result is `np.bool_(False)`,
and `x is False` is `False` for that value even though `x == False` is `True` — a real, if narrow,
correctness bug independent of the test. Fixed by wrapping in `bool(...)` at the source
(`matrix_calc.py`) rather than changing the test's assertion style, since other callers doing the
same `is True`/`is False` check would hit the identical bug. **Reverse:** revert the one-line
change in `Working/Preprocessing/window_matrix/matrix_calc.py`; the test will fail again.

**Backfill (§2) found nothing importable.** All six `MATRICES/*.csv` files fall exactly into the
categories the design brief already anticipated as un-importable (see §4 below) — this isn't a
judgement call so much as confirmation the script's classification logic matches reality. Verified
`--apply` is a true no-op on this state (prints `SKIP` for all six, moves nothing, writes nothing to
the DB) and is idempotent on a second run.

**Added `window_matrix_store.coverage_by_completeness` as a new function, not a parameter on
`coverage_for_span`.** The coverage ribbon needs to render "complete" and "partial" coverage in
different colours (§4/§8.3), but `coverage_for_span`'s documented contract
(`{window_min: [(start,end),...]}`) has no room for that split, and `tests/test_window_matrix_store.py`
already has tests pinning that exact shape. Rather than overload it with a flag that changes its
return type conditionally, I added a sibling function reusing a new shared helper
(`_matching_wm_spans`) so the matching rules (stale exclusion, span clipping, step_frac tolerance)
can't drift between the two. **Reverse:** delete `coverage_by_completeness` and
`_matching_wm_spans`, inline `coverage_for_span`'s old body back; `window_matrix_panel.py`'s
`_refresh_ribbons` would need a different data source.

**`build_window_matrix_ribbon` reuses `REVIEWED_FULL_COLOR`/`REVIEWED_PARTIAL_COLOR` verbatim**, not
new constants — per §8.3's explicit "the same distinction the reviewed ribbon already draws, reused
rather than re-invented." No separate "gap" colour rectangle is drawn (unlike the reviewed ribbon,
which draws an explicit grey `REVIEWED_GAP_COLOR` tier): the lane background alone communicates "no
coverage here," since a WM-coverage gap isn't itself a reviewable event the way a low annotation
count is. `_bucket_coverage_fractions` (already a standalone helper inside `build_reviewed_ribbon`)
is reused directly rather than copied, as instructed, and it turned out to require no changes at all
to reuse.

**`Working.execution.execute_recipe` gained an optional `run_kwargs=` parameter.** The design brief
requires two things that are in tension without this: (a) go through `execute_recipe` for the
interactive/background paths, since that's what registers `runs`/`artifacts` rows and fires the
adapter's `persist` hook, and (b) drive a *real*, per-window progress bar from
`build_window_matrix`'s own `on_progress(done, total, stage)` — a completely different granularity
from `execute_recipe`'s existing `on_progress(step_index, n_steps, stage, algorithm)`, which fires
once for a single-step window-matrix recipe. `execute_recipe` previously called
`spec.run(x, t, fs, **params)` with no way to pass anything beyond the recipe's own declared
params. `run_kwargs` forwards extra keyword arguments to `spec.run()` *only* for adapters whose
`run` signature actually declares them (checked via `inspect.signature`), so every other adapter is
completely unaffected — confirmed by re-running the full suite after the change. The window-matrix
adapter's `_run` gained `on_progress=None, should_cancel=None` parameters (not `ParamSpec` params,
since they're execution-time callables that must never enter the recipe/config hash) and forwards
them straight into `build_window_matrix`. **Reverse:** revert `Working/execution.py` and
`Adapters/preprocessing_window_matrix.py`'s signature changes; the panel would fall back to
step-level progress only (a single "running..." message with no bar).

**Both "interactive" and "background" tiers execute on the same background `threading.Thread`.**
Panel/Bokeh serve one process per session (or shared, depending on deployment), so a call that
truly blocks the serving thread — even for the ≤60s an "interactive" build is estimated at — would
freeze *every* session's UI, not just this tab's Cancel button; that's a worse failure than the
tiers' UX difference is meant to prevent. This mirrors `RunPanel._on_run`, which already always
threads regardless of estimated duration. The only observable difference between the two tiers is
the label/estimate shown on the button before committing (`Compute (≈ 42 s)` vs `Compute in
background (≈ 6 min)`), exactly as §3.3 specifies for *that* part. **Reverse:** if a truly
synchronous interactive path is wanted later, gate on `desc["tier"] == "interactive"` in
`_on_action` and call the worker function directly instead of spawning a thread — but see the
freezing risk above first.

**Cost estimate for the ladder's detailed panel uses the user's currently-checked stages, not
`ladder_status`'s own generic estimate.** `ladder_status(..., estimate=cost.estimate_seconds)`
computes each row's `est_seconds` from *every stage available at that scale* — appropriate for a
compact ladder-row label on a `missing` entry (§3.2), but not for §3.3's detailed cost/routing
panel, which must reflect what Compute would *actually* run. `WindowMatrixPanel._render_cost`
therefore calls `cost.describe(n_windows, m, stages)` itself with the intersection of "currently
checked in the auto-generated param form" and "available at this scale," separately from the
`ladder_status` call. Both code paths are exercised and both are correct for the question each one
answers.

**`_partial_progress`'s "N / M windows" count is defined as "every column belonging to a stage
available at this scale is computed for that row."** The design brief shows `"1,180 / 1,247
windows"` as an example but doesn't define the count precisely for a matrix with several stages at
different completion points. Loading only the selected scale's `computed` mask (not every ladder
row's — `ladder_status` stays deliberately cheap) and applying the same "skip columns belonging to
an unavailable stage" rule `build.py`'s `_only_skipped_missing` already uses, per row instead of
matrix-wide, is what's implemented. **Reverse:** none needed unless a different definition of
"windows done" is wanted; the logic is isolated to one small method.

**Tier button labels combine the §3.2 per-state verb (Compute / Recompute / Resume) with the §3.3
tier wording** (`{verb}`, `{verb} in background`, `Export HPC {verb} job`) rather than picking one
of the two literally, since the brief states both requirements and they aren't quite the same
string. E.g. a stale scale computing in the background reads "Recompute in background (≈ 6 min)."

**On first use, if any stage is uncalibrated, `cost.calibrate()` runs automatically in a background
thread**, per §3.3's explicit instruction, with a "calibrating…" indicator and an automatic
re-refresh of the panel when it finishes. Re-entrancy guarded by a `_calibrating` flag so a rapid
sequence of `refresh()` calls (e.g. span changes while calibration is still running) doesn't spawn a
second calibration thread.

**Coverage ribbons are not wired to a live pan/zoom stream.** The Viewer tab's own ribbons are
genuinely live (`hv.DynamicMap` + `RangeX`), but the Run panel's staged-span preview
(`build_peek_curve`, assigned once to `result_pane.object`) is a static, one-shot render that only
changes when the span mode or staged row changes — there's no interactive zoom inside the Run
panel to link to. The window-matrix ribbons follow that same refresh cadence (rebuilt in
`_refresh_ribbons`, called from `_on_span_context_changed`), which is the correct behaviour given
what they're stacked under, not a shortcut. `build_window_matrix_ribbon` itself is a pure function
(same shape as `build_peek_curve`), so if a future live-zoom preview is added here, no change to the
ribbon builder itself is needed.

**`build_window_matrix.py` was rewritten as a full-fidelity shim, not a minimal one.** The prompt's
literal wording ("thin deprecation shim over `build_window_matrix` + `save_wm`") could be read as
"just call those two functions and nothing else," but that would leave every build launched from
this legacy entry point invisible to the UI ladder and coverage ribbons (no `configs`/`runs`/
`artifacts` rows), which is exactly the kind of "second-class, untracked artifact" the section's own
framing ("leaving both in place... is how the bug comes back") argues against. The shim registers a
run through the same `get_or_create_config`/`insert_run`/`insert_artifact` path a real
`execute_recipe` call would use — with one deliberate difference: it never checks for an existing
completed run to reuse (unlike `execute_recipe`'s default), since this script is specifically
invoked *because* the previous invocation timed out, and reuse-by-default here would risk exactly
the completed-run-shadows-a-partial-artifact problem `force=True` exists to prevent elsewhere.

**The shim's recording resolution tries both filename conventions.** The old script's
`FILENAME = f"M2_concat_fs1_CH{CH}.npy"` embedded the channel in the filename, but
`Pipelines.materialize_channels` (the actual DB population path) registers `source_file` as the
*shared* `.mat` basename with no channel in it, `channel` as its own column. `_resolve_recording`
tries the filename's stem as given, then with a trailing `_CH{ch}` stripped, so it works against
either convention rather than assuming one. Caught by testing the shim against a synthetic DB with
the realistic (channel-less) `source_file` convention and finding the first version couldn't
resolve anything.

**Added `--print-artifact-path` to the shim.** `wm_job.sh` needs to know the exact artifact path to
pass to `wm_status.py` for the resubmit-decision exit code, but that path is derived from the
recording's registered identity, which the shell script has no way to compute on its own. Rather
than duplicate the naming logic in bash, the flag makes the Python script the single source of
truth; `wm_job.sh` captures it via `$(...)` before running the build.

**`wm_job.sh`'s chain cap (`MAX_CHAIN=12`) is a hand-copied constant**, not generated from
`Working.hpc.job_export.export_wm_job`'s own default, since `wm_job.sh` is a hand-written script,
not one of that module's outputs. If the generated scripts' default chain cap changes, this needs a
manual update to match — flagged in both files' comments as a maintenance seam, not fixed further
since making `wm_job.sh` itself generated was out of scope here.

**Section 6 target recording: largest `fs=1` channel actually registered, not literally "~4 days."**
No recording in this DB's `recordings` table is close to 4 days; the largest `fs=1` one
(`M2_aug_concat_fs1.mat` CH0) is ~2.6M samples, ~721 hours (~30 days) — the design brief's
"~4-day channel" example appears to be an approximate illustration rather than a fact about this
specific dataset. Measured real cost at 600-minute windows on this dev machine came out to ~49
seconds (`interactive` tier), not `hpc` — because at that scale there are only ~72 non-overlapping
windows regardless of the channel's total length, so the cost stays low even over a long channel.
Per the brief's own fallback instruction ("if nothing reaches that tier, force it"), I called
`export_wm_job` directly with the real measured stages/estimate rather than waiting for a tier that
wasn't going to happen on this hardware.

**Generated HPC job files (`HPC/Preprocessing/generated/*.sh`/`.json`) were left untracked, not
committed.** This matches the existing repo convention: `HPC/Detection/generated/` from a prior
matrix-profile HPC session is likewise untracked in this repo. Generated job artifacts are treated
as local, regenerable output, referenced by path rather than committed. **Reverse:** `git add
HPC/Preprocessing/generated/` if the operator wants them versioned.

**`Experimentation/wm_stage3_visual_check.py` was kept as a committed, reusable tool**, not deleted
as scratch after use, since `UI/README.md` documents exactly this verification pattern as a
recurring development need for this codebase, not a one-off task-specific script.

---

## 3. Test results

**Before this run:** unknown/untested — the Stage 1/2/4 code had never been imported in this
environment (per the work order). The very first run of the existing suite surfaced exactly one
real failure across all 34 pre-existing test files:
`tests/test_window_matrix_store.py::test_partial_tail_opt_in_restores_the_overhang`
(32/33 in that file; every other file was already fully green on the first run, including all four
"regressions to expect" listed in §1 of the work order — none of them actually manifested as a test
failure, meaning the prior session had already accounted for them correctly).

**After the one-line fix** (`matrix_calc.py`'s `is_full_window`, see DECISIONS): all 34 pre-existing
test files pass, 636 individual assertions. `python -m compileall` is clean over every file the
work order names, and `Adapters.registry.discover_adapters()` lists `preprocessing.window_matrix`
with no stderr traceback.

**New test files added (5), all passing:**

| file | count | covers |
|---|---|---|
| `tests/test_window_matrix_panel.py` | 9/9 | ladder rendering, invalid/missing button states, visibility toggle, window_min sync to the param form |
| `tests/test_window_matrix_coverage_ribbon.py` | 8/8 | disjoint-span gap, empty-scale lane background, full/partial colour reuse, axiswise on every leaf, viewport clipping |
| `tests/test_wm_backfill.py` | 8/8 | self-describing round-trip, unidentifiable/subsample skips, `--assume`, inconsistent-grid refusal, §2.1 column exclusion |
| `tests/test_wm_cost.py` | 12/12 | `None` when uncalibrated, `routing_tier(None)`, budgeted/unbudgeted split, two-point calibration fit, idempotent calibrate |
| `tests/test_job_export.py` (extended, not new) | 13/13 (6 pre-existing MP tests + 7 new WM tests) | chain cap, `--force`, GPU-line-only-with-CNN, resume-path identity, re-export overwrite |

**Total after this run: 39 test files, 679 individual test-function assertions, all green**, except
`tests/test_analysis_modules.py`, which fails under the default Windows console codepage
(`UnicodeEncodeError: 'charmap' codec can't encode...` — a pre-existing environment quirk, unrelated
to any file this work order touches) and passes 195/195 when run with `PYTHONIOENCODING=utf-8`. Not
a regression, not touched by this work.

**No pre-existing test's expectations were changed.** The four "regressions to expect" in §1 of the
work order (cophenetic formatting, correlation-filter column survival, tail-window counts, save-path
handling) were all already correctly reflected in the existing tests before this run started —
nothing needed updating.

---

## 4. Backfill outcome

`python Pipelines/import_wm_artifacts/import_wm_artifacts.py` (report mode) and `--apply` both ran
against the real `MATRICES/` directory. **Nothing was imported; nothing was moved.** All six files
present are reported `SKIP`, each for exactly the reason the design brief and work order anticipated:

| file | reason | what a human needs to supply |
|---|---|---|
| `M2_concat_fs1_10min_27118wins_consecutive.csv` | timescale (10 min) recoverable, channel is not | `--assume "M2_concat_fs1_10min_27118wins_consecutive.csv=CH<n>"` once the channel is known |
| `features.csv` | no recoverable identity (no stem, no timescale) | nothing recoverable — would need external provenance records, if any exist |
| `features - Copy.csv` | same, plus unknown relationship to `features.csv` | same, plus confirmation of whether it duplicates or differs from `features.csv` |
| `features_graph.csv` | same as `features.csv` | same |
| `0.01_percent_M2_concat_fs1.mat_step0.5.csv` | a 0.01% subsample, not a contiguous channel span | not importable at all — this file's `start_idx` values don't index a real channel |
| `0.01_percent_M2_concat_fs1_consecutive.csv` | same | same |

Re-running `--apply` a second time reproduces the identical report (verified) — every line is a
`SKIP` both times, confirming idempotency even in the all-skip case. `store.find_wm` was not
exercised against a real imported matrix (there was nothing to import), but the round-trip path is
directly covered by `tests/test_wm_backfill.py::test_self_describing_file_is_ready_and_round_trips_to_the_same_values`
against a synthetic self-describing CSV, which does exercise the full `plan_file` → `apply_plan` →
`find_wm` → `load_wm` chain and confirms values, columns, and the `backfilled=True` flag all
round-trip correctly.

---

## 5. Visual verification

Real browser (Playwright/Chromium), following `UI/README.md`'s documented pattern exactly —
isolated temp DB, isolated session file, isolated calibration file, real computed window matrices
(not fabricated coverage dicts), never the real database. Driver script:
`Experimentation/wm_stage3_visual_check.py` (kept as a reusable tool).

Three screenshots saved to `Plots/Preprocessing/window_matrix/` (gitignored per `Plots/README.md`,
referenced here by path):

1. **`window_matrix_stage3_01_full_channel_gap.png`** — full-channel view, two 10-minute matrices
   computed over disjoint spans (`[0, 15000)` and `[30000, 50000)` samples). The ribbon shows two
   separated blue bands with a real, visible grey gap between them — not a merged block. A second
   ribbon (60-minute matrix, covering only `[20000, 50000)`) shows the same effect at a different
   boundary.
2. **`window_matrix_stage3_02_zoomed_covered_and_empty.png`** — zoomed into `[2000, 8000)`, fully
   inside the 10-minute coverage and fully outside the 60-minute coverage. The 10-minute band fills
   the entire pane, its left/right edges aligned with the curve's frame above it; the 60-minute pane
   renders as lane background only — visibly present and distinct from a blank/broken pane, not
   merely "nothing drawn."
3. **`window_matrix_stage3_03_zoomed_60min_covered.png`** — zoomed into `[42000, 48000)`, inside
   both scales' coverage. Both bands fill their panes.

Two real bugs were found and fixed specifically because of this step (both were invisible to the
unit tests, which only exercise `build_window_matrix_ribbon` in isolation, not the panel's data flow
into it) — see §6.

---

## 6. Bugs found

Not already listed in `WINDOW_MATRIX_UI_PROMPT.md` §4.

1. **`WindowMatrix.is_full_window` returned `numpy.bool_` instead of `bool`**
   (`Working/Preprocessing/window_matrix/matrix_calc.py:143`, now fixed). Breaks any `is True`/`is
   False` identity check downstream even though the value itself was correct. Found by the existing
   test suite's own first run.

2. **The Run panel's staged-span preview curve had no frame-border hook matching the ribbon panes'**
   (`UI/run_panel.py`, `_refresh_preview`, now fixed by applying `style_main_plot_frame` when the
   window-matrix panel is visible). Without it, a ribbon band's left/right edges would not actually
   line up with the curve above it — the exact "misaligned by the y-axis label width" failure mode
   `UI/README.md` and this work order's §8 both warn about generically. Found only by rendering in a
   real browser; nothing in the Python object graph indicated a problem.

3. **`WindowMatrixPanel._refresh_ribbons` clipped coverage to the current viewport before deciding
   which ladder scales get a pane at all**, not just for bucketing within a shown pane (`UI/window_matrix_panel.py`,
   now fixed to fetch whole-channel coverage via `span=None` and let
   `build_window_matrix_ribbon` do its own per-viewport clipping). The bug: a scale with real
   coverage elsewhere in the channel but none in the current view was dropped from
   `ribbon_column.objects` entirely, instead of rendering its lane background — silently *worse*
   than the "blank pane" failure mode §8 explicitly tests for, since the pane didn't exist at all
   rather than merely rendering wrong. Found by driving the actual zoomed-in scenario in a real
   browser and noticing only one ribbon pane appeared where two were expected; confirmed by
   `object` counts printed from the driver script before opening the screenshot.

4. **Artifact writes from any headless `execute_recipe` call land in the real
   `Results/Preprocessing/window_matrix/` tree unless `Adapters.preprocessing_window_matrix.RESULTS_DIR`
   is explicitly overridden** — not a logic bug (the module's own docstring documents the override
   point), but a real footgun: it bit the visual-check script once (cleaned up, then fixed by
   redirecting `RESULTS_DIR`) and would bite any future ad-hoc script the same way. Worth a note
   for anyone writing another driver against `execute_recipe` with a real DB path.

---

## 7. Blocked / not done

Nothing was left unfinished, but three execution paths were verified at the mechanism level (unit
tests, direct `execute_recipe`/`export_wm_job` calls) rather than by clicking all the way through
the live panel's threaded UI:

- **Resume** (`force=True` on a `partial` scale): the underlying guarantee is directly tested
  (`tests/test_window_matrix_resume.py`, `Adapters.preprocessing_window_matrix`'s own docstring
  reasoning), and the panel's `_on_action` correctly sets `force = row["state"] in ("partial",
  "stale")` — but no end-to-end run was done where a real timeout produced a partial artifact and
  the panel's own Resume button was clicked to complete it through the live thread.
- **Cancel** (`_on_cancel` → `self._cancel_event` → `run_kwargs["should_cancel"]`): the underlying
  plumbing was verified directly (`execute_recipe(..., run_kwargs={"should_cancel": ...})` against a
  real build, and `tests/test_window_matrix_resume.py` exercises cancellation at the `build.py`
  level), but the panel's actual Cancel button was not clicked mid-run in a live scenario.
- **HPC export via the panel's Compute button** (`_export_hpc`, reached when `tier == "hpc"`): the
  underlying function (`export_wm_job`) was exercised directly and by hand-inspection in §6, and by
  `tests/test_job_export.py`, but the button path itself (which only differs by which values it
  reads from the auto-generated param form) wasn't separately clicked through a live panel instance.

These aren't expected to behave differently from what's verified — the code paths are short and
share the exact same `execute_recipe`/`export_wm_job` calls already proven correct — but I'm not
claiming visual/interactive confirmation I didn't actually do.

---

## 8. Next

**Stage 5 — dendrogram clustering analysis**, as the work order's own default states. Nothing above
displaced it: `to_dataframe`, the `computed` mask, and the correlation-filter fix in
`Working/Catalogue/dendrogram/dendrogram_cluster.py` (already landed in the Stage 1/2/4 code this
run got green) exist specifically so Stage 5 can consume them without further storage-layer changes.
