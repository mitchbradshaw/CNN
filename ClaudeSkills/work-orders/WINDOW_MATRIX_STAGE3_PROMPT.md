# Window matrix — Stage 3 (UI), verification, and cleanup

Autonomous work order for Claude Code. The operator is AFK for the duration.

---

## 0. How to work

**Never stop to ask a question.** Every choice below either has a stated
default or is yours to make. When you make a judgement call, apply it,
carry on, and record it — decision, alternatives considered, and why — in
the `DECISIONS` section of the final summary (§9). A blocked task is
written up as blocked with what you tried; it is never a reason to halt the
run.

**Read these first, in this order:**

1. `WINDOW_MATRIX_UI_PROMPT.md` — the design brief this implements. §1
   (ladder), §3 (storage), §6 (cost/routing), §8 (UI) are the ones you
   need. §0.1 and §0.2 are the two corrections that must not be
   engineered away.
2. `UI/README.md` — especially the HoloViews rules and the "Visual
   verification during development" section.
3. `UI/motif_browser.py` — the matrix-profile scale switcher. Stage 3's
   timescale control should look and behave like it, because they are the
   same idea at two stages of the pipeline.
4. `UI/plots.py` — `build_reviewed_ribbon` and `build_channel_dmap`.

**Ground rules inherited from the repo:**

- `Working/` and `Adapters/` must not import Panel, HoloViews, or
  Datashader, directly or transitively. The cluster runs them.
- Adding an algorithm is one file in `Adapters/` and zero UI changes. Do
  not special-case `preprocessing.window_matrix` in the generic parameter
  form; the extra controls in §3 sit *beside* the auto-generated form, not
  inside it.
- Tunable thresholds go in `Working/config.py` with a comment explaining
  the number, never inline.
- Comments explain *why*, not *what*. Match the density and tone of
  `Working/config.py` and `Working/database/matrix_profile_store.py`.

**Commit as you go**, one commit per numbered section, message in the
existing style. Do not force-push, do not rebase, do not touch anything
outside this repo.

---

## 1. Get the existing work green (do this first)

Stage 1, 2 and 4 landed in a session that could not execute Python against
this repo. The logic was verified in an isolated sandbox against copied
code; it has **never been imported in this environment**. Assume there are
import errors, signature mismatches, and typos, and clear them before
building anything new.

New/changed files from that session:

```
WINDOW_MATRIX_UI_PROMPT.md                              (new, design brief)
Working/config.py                                       (added WM_* block)
Working/database/window_matrix_store.py                 (new)
Working/Preprocessing/window_matrix/build.py            (new)
Working/Preprocessing/window_matrix/cost.py             (new)
Working/Preprocessing/window_matrix/matrix_calc.py      (grid + API fixes)
Working/Preprocessing/window_matrix/plot_matrix.py      (fs bug, accessors)
Working/Preprocessing/window_matrix/create_matrix.py    (accessor)
Working/Catalogue/dendrogram/dendrogram_cluster.py      (scalability + filters)
Working/hpc/job_export.py                               (added export_wm_job)
Adapters/preprocessing_window_matrix.py                 (new)
Pipelines/import_wm_artifacts/import_wm_artifacts.py    (new)
Pipelines/window_matrix_build/wm_status.py              (new)
tests/test_window_matrix_store.py                       (new)
tests/test_window_matrix_resume.py                       (new)
HPC/README.md                                           (generated-jobs section)
```

Do:

1. `python -m compileall` over every file above. Fix syntax errors.
2. `python -c "from Adapters.registry import discover_adapters; print([s.name for s in discover_adapters()])"`
   from the repo root. `preprocessing.window_matrix` must appear.
   `discover_adapters` swallows import failures with a traceback to
   stderr — read that stderr, do not just check the list length.
3. `python tests/test_window_matrix_store.py`
4. `python tests/test_window_matrix_resume.py`
5. The **whole** existing suite: every `tests/test_*.py`. Use pytest if it
   runs cleanly here, otherwise the `python tests/test_x.py` runner each
   file provides.

**Regressions to expect and how to resolve them.** These are consequences
of deliberate changes, so fix the caller, not the change — unless the
change is actually wrong, in which case fix it and say so in the summary.

- `cluster_window_matrix` now returns `cophenetic_r=None` when the
  cophenetic correlation was skipped (it needs the full pairwise distance
  array, which ward runs deliberately no longer allocate). Anything
  formatting it with `:.3f` must go through `_fmt_cophenetic`.
- `preprocess_window_matrix` gained a correlation filter (default
  `|r| > 0.99`) and changed its near-constant filter from
  coefficient-of-variation to absolute variance. Both change which columns
  survive. If a test asserts an exact surviving-column set, update the
  expectation and note it.
- `create_matrix_at_timescale` no longer emits windows that run past the
  end of the signal, so window counts drop by up to `m/step`. Tests
  asserting a window count need updating; that is the bug being fixed, not
  a regression.
- `WindowMatrix.save_window` now takes a path rather than a bare filename
  prefixed with `MATRICES/` internally. Bare filenames still work.

Report the before/after pass count in the summary.

---

## 2. Backfill the existing `MATRICES/` CSVs

```
python Pipelines/import_wm_artifacts/import_wm_artifacts.py
```

Report mode first. Then `--apply`.

**Decisions, already made — apply them, do not deviate:**

- `M2_concat_fs1_10min_27118wins_consecutive.csv` does not record its
  channel and nothing inside the file does either. **Do not guess and do
  not pass `--assume`.** Leave it in `MATRICES/`, report it in the
  summary under "needs a human", and state exactly what is needed
  (`--assume "<file>=CH<n>"` once the channel is known).
- `features.csv`, `features - Copy.csv`, `features_graph.csv` — no
  recoverable identity. Skip, leave in place, list in the summary.
- `0.01_percent_*.csv` — a subsample, its `start_idx` values do not index
  a real channel. Skip, leave in place.
- Anything the script reports as READY: import it.

Then verify:

- Every imported matrix resolves through `store.find_wm`.
- Re-running `--apply` writes nothing and moves nothing (it must print
  `HAVE` for each, not `OK`).
- `store.ladder_status` shows the imported scales as `available` (or
  `partial`, if the CSV had NaNs — expected, and correct, since a
  backfilled mask is inferred).

If the recordings for a READY file are not registered in the DB, the
script says so. In that case run `Pipelines/materialize_channels` for the
channel first if the `.npy` exists; if it does not, record it as blocked.

---

## 3. Stage 3 — the timescale control

New file `UI/window_matrix_panel.py`, composed into the Run panel. Do
**not** grow `run_panel.py` by 500 lines; it is already 2,100.

Structure it as a small component class with a `layout()` method and a
`refresh(recording, span)` the Run panel calls, mirroring how
`motif_browser.py` is composed by `app.py`.

### 3.1 Visibility

The whole component is hidden unless
`run_panel.algorithm_select.value == "preprocessing.window_matrix"`.
Hidden, not disabled, and not shown empty — same convention
`encoding_section` follows.

### 3.2 The ladder

A `pn.widgets.RadioButtonGroup` over `WM_SCALE_LADDER_MIN`, rendered from
`window_matrix_store.ladder_status(conn, recording_id, fs, n_samples,
step_frac=..., span=..., estimate=cost.estimate_seconds)`.

Per state:

| state | affordance |
|---|---|
| `available` | selectable. Label carries `n_windows`; if `unavailable_stages` is non-empty, also `"28/33 measures"` and the excluded group names |
| `partial` | selectable. Shows `"1,180 / 1,247 windows"` and a **Resume** button |
| `stale` | greyed, reason shown, **Recompute** button |
| `missing` | shows the cost estimate and tier, **Compute** button |
| `invalid` | greyed, **no** Compute button, `reason` shown verbatim |

Selecting a scale writes `window_min` into the auto-generated parameter
form so the recipe and the ladder can never disagree about what will run.
`motif_browser.py` already does exactly this for the MP adapter — copy the
mechanism.

**Never estimate an uncomputed scale's contents from a neighbouring one.**
The number shown on a `missing` entry is a *cost* estimate; label it so
that is unambiguous.

### 3.3 Cost and routing

Use `Working.Preprocessing.window_matrix.cost.describe(n_windows, m,
stages)`. It returns `per_stage_seconds`, `estimated_seconds`,
`unbudgeted_stages`, and `tier`.

- Show the estimate and tier **before** the user commits, never after.
- `tier == "unknown"` (uncalibrated, or a CNN stage is enabled) →
  "not calibrated" plus a **Calibrate** button that calls
  `cost.calibrate()` in a background thread. Do not substitute a guess.
- When `unbudgeted_stages` is non-empty but other stages are budgeted, say
  so explicitly: *"≈ 4 min for Catch22 + entropy; the CNN stage is not
  cost-calibrated on this machine."* A single number that silently omits
  the most expensive stage is worse than no number.
- The primary button's label is the tier: `Compute (≈ 42 s)` /
  `Compute in background (≈ 6 min)` / `Export HPC job (≈ 4 h)`.

**On first use, if `cost.calibration_status()` shows any stage
uncalibrated, run `cost.calibrate()` automatically in the background** —
it is a few seconds and the alternative is a UI that says "unknown" until
someone finds the button. Show a small "calibrating…" indicator. Record
this decision in the summary.

### 3.4 Running

- **interactive** — run inline on the UI thread with a determinate
  `pn.indicators.Progress` driven by `build_window_matrix`'s
  `on_progress(done, total, stage)`, plus a Cancel button wired to
  `should_cancel`. Note the callback signature differs from
  `execute_recipe`'s `on_progress(step_index, n_steps, stage, algorithm)`
  — do not conflate them.
- **background** — thread, same progress bar, tab stays usable, Cancel
  live. Follow `run_panel.py`'s existing threading pattern exactly,
  including `_run_on_ui_thread` and capturing `pn.state.curdoc` on the
  serving thread *before* spawning.
- **hpc** — call `Working.hpc.job_export.export_wm_job`, then show the
  script path, the recipe path, the `sbatch` line, **and an explicit
  statement that the files still need to reach rangpur**. A confirmation
  that reads like the job was submitted would be a lie.

Go through `Working.execution.execute_recipe` for the interactive and
background paths, not by calling `build_window_matrix` directly — that is
what registers the `runs`/`artifacts` rows and fires the adapter's
`persist` hook, and it is why a UI run and a cluster run produce
interchangeable artifacts.

Resume: set `resume_path` from
`Adapters.preprocessing_window_matrix.default_artifact_path(recording,
window_min, step_frac)` **on every run, not only on resumes** — the path
is deterministic, and putting it in from the start is what keeps the
config hash stable across a chain. Resuming requires `force=True` on
`execute_recipe`, because it would otherwise short-circuit on the
completed run that produced the partial artifact.

---

## 4. Stage 3 — coverage ribbons (the "which regions already have one" view)

**Reuse `UI/plots.py`'s reviewed-coverage ribbon machinery. Do not write a
second overlay renderer.** `build_reviewed_ribbon` already solves this
exact rendering problem: it buckets the channel, computes true fractional
coverage per bucket through `queries.merge_intervals`, and renders full /
partial / absent as three *distinct colours* rather than an alpha blend —
specifically because scattered short spans across a multi-million-sample
channel otherwise merge visually into apparent continuous coverage at a
coarse zoom. That failure mode is identical here and misleads in the same
direction.

Build `build_window_matrix_ribbon(coverage_intervals, x_range, ...)` in
`UI/plots.py` by factoring the bucketing out of `build_reviewed_ribbon`
rather than copying it. If factoring turns out to be more invasive than
you expect, copy it and say so in the summary — but try factoring first.

Layout: one thin ribbon pane per ladder timescale that has any coverage,
stacked under the staged-span preview, each labelled with its scale.
Source the intervals from `window_matrix_store.coverage_for_span(conn,
recording_id, span)`.

Hard requirements, all previously learned the hard way in this repo:

- Ribbons are **separate panes** with a fixed `(0, 1)` y-range, linked to
  the main plot by x-range only. Never overlays inside the curve's frame.
  `Working/config.py`'s `RIBBON_PANE_HEIGHT` comment explains why at
  length.
- Use `RIBBON_FRAME_MIN_BORDER_LEFT` and `RIBBON_FRAME_MIN_BORDER_RIGHT`
  so the ribbon frames start and end at the same pixel x as the curve's.
- Draw `RIBBON_LANE_BACKGROUND_COLOR` under every bucket, spanning the
  full pane regardless of data, so "no coverage at this scale" renders as
  visibly empty rather than as a broken pane.
- Every `DynamicMap` callback returns the **same element type on every
  frame** — always an `Overlay`, even when empty.
- `axiswise=True` on **every leaf element**, not just the enclosing
  `Overlay`.
- One vectorized `hv.Rectangles` for all buckets. Never one element per
  interval — `UI/README.md` records a confirmed multi-minute hang from
  per-row elements.

A `partial` matrix renders in the partial colour; a `stale` one is not
drawn at all (`coverage_for_span` already excludes stale by default —
keep that).

Add a `WM_COVERAGE_RIBBON_BUCKETS` constant to `Working/config.py` if you
need one; default it to `REVIEWED_COVERAGE_BUCKETS`'s value and say why in
the comment.

---

## 5. Close the loop on the infinite-resubmit bug

`Pipelines/window_matrix_build/build_window_matrix.py` still contains the
bug described in `WINDOW_MATRIX_UI_PROMPT.md` §0.2, and
`HPC/Preprocessing/wm_job.sh` still requeues by grepping its `--status`
output. Leaving both in place next to a fixed implementation is how the
bug comes back.

Do:

1. Rewrite `build_window_matrix.py` as a **thin deprecation shim** over
   `Working.Preprocessing.window_matrix.build.build_window_matrix` +
   `window_matrix_store.save_wm`. Keep its CLI flags working
   (`--status`, `--reset`, `--timeout`, `--no-cnn`, `--no-slow-entropy`,
   `--no-rf`) so anything that calls it does not break; have `--status`
   read the artifact's `computed` mask. Print a one-line deprecation
   notice pointing at `run_recipe.py`. Keep the module-level `CH` /
   `WINSIZE` / `FS` constants as *defaults* but expose them as CLI flags
   so a job no longer needs a source edit.
2. Update `HPC/Preprocessing/wm_job.sh` to requeue on
   `Pipelines/window_matrix_build/wm_status.py`'s exit code instead of
   grepping, and add the same chain cap the generated scripts use. Keep
   its existing SBATCH header.
3. Leave a comment at each site naming §0.2, so a future reader knows why
   the exit-code form is not an arbitrary style preference.

---

## 6. Generate and inspect one real HPC job

Pick the largest recording registered in the DB and a timescale whose
estimate lands in the `hpc` tier (600-minute windows at fs=1 over the full
~4-day channel should, if the machine is calibrated; if nothing reaches
that tier, force it by calling `export_wm_job` directly and say so).

```python
from Working.hpc.job_export import export_wm_job
```

Then verify by inspection:

- `bash -n` on the generated `.sh` (syntax only; it will not run here).
- The `--time` is `est_seconds * 3` rounded up to 15 min, floor 30 min.
- `timeout_s` in the recipe is the wall clock minus the cleanup margin —
  the job must save a resumable artifact before SLURM kills it.
- `--gres=gpu:a100` is present **only** when a CNN stage is enabled.
- The `resume_path` in the recipe JSON equals the path
  `save_wm` would write.
- `--force` is on the `run_recipe.py` line.
- The chain cap is present and the resubmit passes `$NEXT`.

Do not submit anything. Note in the summary where the files landed and
that they still need to reach rangpur.

---

## 7. Tests to add

- `tests/test_window_matrix_panel.py` — headless, no browser. Construct
  the component against a temp DB, assert: the ladder renders one entry
  per `WM_SCALE_LADDER_MIN`; an `invalid` entry has no Compute button; a
  `missing` entry has one; selecting a scale writes `window_min` into the
  parameter form; the component is hidden for a non-window-matrix
  algorithm. Follow `tests/test_run_panel.py`'s approach to instantiating
  UI objects without a live server.
- `tests/test_window_matrix_coverage_ribbon.py` — assert that two
  disjoint stored matrices produce two visibly separated bands and not one
  continuous one, and that a scale with no coverage still renders a
  non-empty `Overlay` (the lane background). Element-level assertions on
  the HoloViews objects, not screenshots.
- `tests/test_wm_backfill.py` — the importable files round-trip to the
  same values; the unidentifiable ones are reported and left in place; a
  second `--apply` writes nothing.
- `tests/test_wm_cost.py` — `estimate_seconds` returns `None` when
  uncalibrated rather than a number; `routing_tier(None) == "unknown"`;
  `describe` separates budgeted from unbudgeted stages.
- `tests/test_job_export.py` — extend with `export_wm_job`: the chain cap,
  the `--force` flag, the GPU line appearing only with a CNN stage, and
  re-export overwriting rather than accumulating.

---

## 8. Visual verification (required, not optional)

Per `UI/README.md` §"Visual verification during development". The two
failure modes here are both invisible to Python-level inspection:

- a blank ribbon pane from a `DynamicMap` returning mixed element types;
- ribbon frames misaligned with the curve's frame by the y-axis label
  width, which makes every band point at the wrong region.

Serve the app, drive a browser, and capture screenshots at:

1. Full-channel zoom with two timescales stored over **disjoint** spans —
   the gap must be visible.
2. Zoomed into one covered region — the band must line up with the
   region, left and right edges within a pixel or two of the curve's.
3. A scale with no coverage — the lane background must be visible, not a
   blank pane.

Save them under `Plots/` and reference them in the summary. If you cannot
drive a browser in this environment, say so plainly in the summary and
list exactly what remains visually unverified — do not claim verification
you did not do.

---

## 9. The final summary — the main deliverable

Write `WINDOW_MATRIX_STAGE3_SUMMARY.md` at the repo root. The operator
reads this before reading any code. Sections, in order:

1. **What now works** — one paragraph, no bullet list.
2. **DECISIONS** — every judgement call you made. For each: what you
   decided, what the alternatives were, why you chose as you did, and how
   to reverse it if the operator disagrees. This is the most important
   section; err heavily towards including a decision rather than omitting
   it as too small.
3. **Test results** — pass counts before and after §1, every test you
   added, and every pre-existing test whose expectations you changed with
   the reason.
4. **Backfill outcome** — what was imported, what was skipped, and for
   each skipped file exactly what a human has to supply.
5. **Visual verification** — what you saw, with screenshot paths; or what
   you could not check and why.
6. **Bugs found** — anything you hit that was not already in
   `WINDOW_MATRIX_UI_PROMPT.md` §4, with file and line.
7. **Blocked / not done** — anything you could not finish, what you tried,
   and what unblocks it.
8. **Next** — the honest next step, which is Stage 5 (dendrogram analysis)
   unless something above displaced it.

Keep it direct. No praise, no restating the brief back. If something is
half-finished, say it is half-finished.

---

## 10. Things that will bite you

- **`aeon` and `torch` are optional at import time.** `catch22_columns()`
  imports aeon lazily and `measure_columns` only calls the factories for
  requested stages — keep it that way. A UI listing stored matrices must
  work on a machine with neither installed.
- **`start_idx` is absolute in the channel**, not relative to the span.
  The coverage ribbons depend on this. Do not "normalise" it.
- **`complete` is not `computed.all()`.** A stage that cannot run at a
  given window length (sample entropy above 4096 samples, CNN above 5000)
  leaves its columns uncomputed forever; `_only_skipped_missing` in
  `build.py` is what stops the HPC chain resubmitting for work that can
  never be done. Do not simplify it.
- **A backfilled artifact is refused as a resume source** — its mask was
  inferred from NaN, so trusting it reintroduces the §0.2 conflation.
  There is a test; do not delete it.
- **`step_frac` is part of a matrix's identity, not a detail.** Off-default
  step fractions are stored and usable but must not appear in the ladder.
- **The ladder is `WM_SCALE_LADDER_MIN`, deliberately a separate constant
  from `MP_SCALE_LADDER_MIN`** with the same values. Do not merge them;
  their validity rules differ (`WM_MIN_WINDOW_SAMPLES` is 32,
  `MP_MIN_WINDOW_SAMPLES` is 4) and a future divergence must not be a
  silent edit to the MP ladder.
- **`Working/config.py`'s `WM_GRAMIAN_MAX_SAMPLES` duplicates the Gramian
  adapters' `MAX_SPAN_SAMPLES` as a literal**, because config must not
  import `Adapters/`. `tests/test_window_matrix_store.py` asserts they
  agree. If you change one, change both.
