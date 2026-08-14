# Matrix Profile — storage, cost routing, and motif browser

Implementation brief for bringing matrix profiling into the UI, in the same
form as `DSAX_UI_PROMPT.md`. Written 2026-08-10 against the repo as it stands.

Scope: stored-run reuse, a canonical scale ladder, cost-based routing between
in-UI / background / HPC execution, and the slide-27 motif browser. Seeded
motif discovery (slide 28) is **out of scope here** and is Stage 5 below —
but the storage format must carry what it needs, so don't drop `left_i`/
`right_i` on the way through.

---

## 0. A correction that shapes everything below

The working assumption in the request was that a matrix profile at one
timescale is "the same shape, more detailed" than at another, so intermediate
scales could be interpolated. **This is not true, and the design must not
encode it.**

For window length `m`, the matrix profile stores, for each subsequence
`x[i : i+m]`, the z-normalised Euclidean distance to its nearest neighbour
elsewhere in the series. Changing `m` changes:

1. **What is being compared.** A 10-minute window and the 60-minute window
   containing it are different queries. The nearest neighbour of the 10-minute
   window can be — and routinely is — at a completely unrelated location from
   the nearest neighbour of the enclosing 60-minute window. Nothing constrains
   `argmin` to move continuously with `m`.
2. **What z-normalisation removes.** Each window is normalised over its own
   span, so a slow drift that dominates a 60-minute window is *inside* the
   normalisation at that scale but is a *baseline offset* at 10 minutes and
   gets removed. The two profiles are responding to different components of
   the signal, not to the same component at different resolutions.
3. **The units of the distance.** z-normalised Euclidean distance over `m`
   points is bounded by `2·sqrt(m)`. A raw distance of 0.5 at `m=600` and 0.5
   at `m=3600` do not mean the same degree of similarity. Any cross-scale
   comparison must divide by `sqrt(m)` first.

The apparent self-similarity across scales in the plots so far is the shape of
the *underlying signal*, not a property of the profile.

There is a principled version of the cross-scale idea — the **pan matrix
profile** (`stumpy.stimp`), which computes MP over a range of `m` with
`sqrt(m)`-normalised distances specifically so scales become comparable. It is
substantially more expensive than a single MP and is deferred. Per the
decision taken: **fixed ladder now, each scale computed independently, no
interpolation, and the storage layer built so `scale` is a first-class axis
that a PMP surface could later slot into.**

Wherever the UI shows a scale that has not been computed, it must say
"not computed" — never estimate it from a neighbouring scale.

---

## 1. The canonical scale ladder

Defined once, in `Working/config.py`:

```python
# Matrix-profile window ladder, in minutes. Every stored MP is at one of
# these. Not interpolable — see MATRIX_PROFILE_UI_PROMPT.md §0.
MP_SCALE_LADDER_MIN = (1, 10, 60, 600)
```

At `fs=1` that is `m = 60 / 600 / 3600 / 36000` samples.

Rules:

- A scale is **valid for a span** only if `m >= 4` (stumpy's floor) and
  `m <= len(x) // 2` (below that the exclusion zone leaves almost nothing to
  match against). The UI greys out invalid ladder entries with the reason,
  rather than letting a run fail at the stumpy call.
- Off-ladder windows stay possible via the existing adapter's `window_min`
  param (there are already artifacts at `WIN4.704`, `WIN34`, `WIN50`), but
  they are **not** browsable in the scale switcher — they show in the run list
  as "custom scale". The ladder exists to make scales comparable *across
  channels and recordings*, which off-ladder values defeat.
- `fs` is part of the identity. `MP_SCALE_LADDER_MIN` is in minutes precisely
  so the same ladder means the same thing at `fs=0.25` and `fs=1`; `m` is
  derived, never stored as the primary key.

---

## 2. Storage format and the run registry

### 2.1 What is wrong with the current artifacts

```
Results/Detection/matrix_profile/
  0_mp_M2_concat_fs1_CH0.npz          <- CPU, window unknown
  1_mp_M2_concat_fs1_CH0.npz          <- GPU, same logical artifact, different name
  1_mp_M2_concat_fs1_CH0_1hr.npz      <- third naming convention
  1_mp_M2_concat_fs1_CH0_WIN1.npz
  1_mp_M2_concat_fs1_CH0_WIN5.npz
  1_mp_M2_concat_fs1_CH2_WIN4.704.npz <- float in a filename
  1_mp_M2_concat_fs1_CH2_WIN50.npz
  1_mp_M2_concat_fs1_CH13_WIN34.npz
```

Three problems, all of which block "show me the existing runs for this
dataset":

- **The GPU flag is the leading character of the filename.** Whether a run
  used a GPU is a property of *how* it was computed, not *what* it is. As a
  name prefix it means the same logical artifact has two possible paths, so
  nothing can look one up by identity.
- **Window length is optional and inconsistently encoded** (absent, `_1hr`,
  `_WIN5`, `_WIN4.704`). The first two files above cannot be interpreted
  without re-deriving the window from the array length and the source.
- **Nothing records the source data's identity.** If a channel is
  re-materialised, every existing `.npz` silently becomes stale with no way to
  detect it.

### 2.2 New format

Path: `Results/Detection/matrix_profile/mp_v2_{source_stem}_CH{ch}_WIN{scale_min:g}min.npz`

Keys:

| key | dtype | note |
|---|---|---|
| `mp` | float32 | distance profile |
| `mpi` | int32 | nearest-neighbour index |
| `left_i` | int32 | **new** — `profile[:, 2]`, needed for chains (§Stage 5) |
| `right_i` | int32 | **new** — `profile[:, 3]` |
| `m` | int32 | window in samples |
| `fs` | float32 | |
| `window_min` | float32 | |
| `n_samples` | int64 | length of the source channel |
| `source_file`, `channel`, `recording_id` | | identity of the input |
| `data_sha1` | str | sha1 of the source `.npy` — staleness detection |
| `config_hash` | str | links to `configs` |
| `approx` | bool | True if produced by `scrump` rather than `stump` |
| `approx_percentage` | float32 | fraction of the full computation done; 1.0 when exact |
| `backend` | str | `"gpu_stump"` / `"stump"` / `"scrump"` |
| `stumpy_version`, `created_at`, `elapsed_s` | | provenance |

`t_mp` is **dropped** — it is `np.arange(len(mp)) / fs`, recomputable, and
currently stored as a float32 array the same length as `mp`, roughly doubling
every file for nothing.

`approx` is load-bearing: an approximate profile must never be silently reused
where an exact one was requested. `find_mp(..., require_exact=True)` skips
`approx` artifacts.

### 2.3 The registry is the existing `runs` tables — do not add a sidecar index

A stored MP is already expressible in the schema: a `configs` row (recipe =
one `detection.matrix_profile` step with `window_min=S`), a `runs` row with
`status='completed'` and the span, and an `artifacts` row of
`kind='encoding'`. `find_completed_run(conn, config_id, recording_id,
span_start, span_end)` in `Working/database/runs.py` is exactly the reuse
lookup this feature needs, and `execute_recipe` already short-circuits on it.

Add `Working/database/matrix_profile_store.py` — a thin, headless query layer,
no new tables:

```python
def list_mp_runs(conn, recording_id, *, include_approx=True) -> list[dict]
    # one dict per stored MP: window_min, m, approx, backend, elapsed_s,
    # run_id, artifact_path, created_at, stale (bool)

def find_mp(conn, recording_id, window_min, *, require_exact=False) -> dict | None

def ladder_status(conn, recording_id, fs, n_samples) -> list[dict]
    # one row per MP_SCALE_LADDER_MIN entry:
    #   {"window_min", "m", "state": "available"|"approx"|"stale"|
    #                                 "missing"|"invalid",
    #    "reason", "est_seconds", "run_id"}
    # This is what the scale switcher renders directly. "missing" and
    # "invalid" are distinct states with distinct affordances — one offers a
    # Compute button, the other explains why the scale cannot exist here.

def load_mp(artifact_path, *, mmap=True) -> dict
    # np.load(..., mmap_mode='r') by default; a 1M-sample MP is ~4 MB per
    # array but the browser opens several at once when comparing scales.
```

`stale` = the artifact's `data_sha1` no longer matches the current `.npy`.
Surface stale artifacts in the list, greyed, with a "recompute" action — never
hide them and never load them silently.

### 2.4 Backfill

`Pipelines/import_mp_artifacts/import_mp_artifacts.py` — one-shot, idempotent,
safe to re-run:

1. Scan `Results/Detection/matrix_profile/` for both old and new names.
2. Parse `source_stem` / `CH` / window from the filename; for the two files
   with no window token, derive `m` from `n_samples - len(mp) + 1` against the
   matching channel `.npy` and report it for confirmation rather than guessing
   silently.
3. Rewrite into the v2 format. `left_i` / `right_i` are **not recoverable**
   from the old files (the pipeline discarded columns 2–3 before saving) —
   write them as `-1` sentinels and set a `has_chain_indices=False` flag, so
   Stage 5 can tell "no chains available, recompute" from "no chains found".
4. Register `configs` / `runs` / `artifacts` rows via
   `get_or_create_config` + `insert_run` + `insert_artifact`.
5. Move the originals to `Results/Detection/matrix_profile/_legacy/` rather
   than deleting them.
6. Where two files are the same logical artifact (`0_mp_...CH0.npz` and
   `1_mp_...CH0.npz`), keep the one whose `mp` is finite over more of its
   length, and log the choice.

---

## 3. Cost model and execution routing

### 3.1 Estimating

`stump` is O(n²/T) in the series length and effectively flat in `m` (the
sliding dot-product is incremental). So a single calibration constant per
backend suffices:

```
t_est(n) = k_backend * n**2
```

`Working/Detection/matrix_profiling/cost.py`:

- `calibrate(backend, force=False)` — runs `stump` (and `gpu_stump` if
  available) on a synthetic `n0 = 20_000` series, solves for `k`, writes
  `DATA/db/mp_calibration.json` keyed by
  `{backend, cpu_count, gpu_name, stumpy_version}`.
- `estimate_seconds(n, backend)` — returns `None` if uncalibrated rather than
  falling back to a hardcoded constant; the UI then shows "not calibrated"
  with a Calibrate button, which is honest. A wrong estimate here routes a
  40-minute job into the "wait with a spinner" path.
- Calibration is per-machine and cheap (a few seconds). Re-run automatically
  when `cpu_count` or `stumpy_version` changes.

Sanity anchor from the presentation: ~300 h at 1 Hz (n ≈ 1.08e6) exceeds
20 min on the current hardware, i.e. `k_cpu` on the order of 1e-9. Use it as a
plausibility check on a fresh calibration, not as a substitute for one.

### 3.2 Routing

Three tiers, thresholds in `Working/config.py`:

```python
MP_INTERACTIVE_BUDGET_S = 60     # <= this: run inline, progress bar, blocking
MP_BACKGROUND_BUDGET_S  = 900    # <= this: offer background run with cancel
                                 # >  this: offer HPC export
```

- **Interactive** — run in the UI thread with a determinate progress bar.
  Use `stumpy.scrump(x, m, percentage=p)` as an *anytime* algorithm: it yields
  progressive refinement, which is what makes a real progress bar possible
  (plain `stump` is opaque until it returns). Run it to `percentage=1.0` when
  the exact cost fits the budget — at `percentage=1.0` SCRIMP++ converges to
  the exact profile — and mark `approx=False` only in that case.
- **Background** — `Working.execution.execute_recipe` already accepts
  `on_progress` and `should_cancel`; run it on a thread, surface progress and
  a Cancel button, keep the tab usable. The run row goes to `status='running'`
  and then `'completed'` / `'cancelled'`, so a crash mid-run leaves a visible
  record instead of a missing artifact.
- **HPC** — §5.

The tier is chosen from `estimate_seconds`, and the estimate plus the tier is
always displayed *before* the user commits ("≈ 4 min 20 s — will run in the
background"), never after.

### 3.3 The `max_span_samples` guard

`AdapterSpec.max_span_samples` exists and is enforced in `execute_recipe`.
`detection.matrix_profile` currently leaves it `None`. Set it to the n
corresponding to `MP_BACKGROUND_BUDGET_S` at the calibrated `k` — computed at
registration time, not hardcoded — so the headless path cannot be handed a
job the UI would have refused.

---

## 4. Segment semantics — three different things that look alike

This is the part most likely to produce a quietly wrong plot, so the API names
must carry the distinction and the UI must label it.

Given a whole-channel profile `mp` and a segment `[a, b)`:

**(1) Slice of the channel profile** — `mp[a : b - m + 1]`.
For each subsequence starting in the segment: the distance to its nearest
neighbour **anywhere in the channel**. Free, exact, no recomputation. This is
usually what "where else does this thing occur?" means, and it is the correct
backing for the motif browser's neighbour lists.

**(2) Segment-only profile** — `stump(x[a:b], m)`.
For each subsequence in the segment: the distance to its nearest neighbour
**within the segment**. A different quantity. Cheap (the segment is small), so
recompute — never approximate it by slicing (1). Answers "does this pattern
repeat *inside* this window?"

**(3) Seed distance profile** — `stumpy.match(Q, x)` for one window `Q`.
Distance from a single query to every position in the channel, via FFT, ~O(n
log n). Fast enough to run interactively on a full channel. Backs the motif
browser's per-group neighbour retrieval and, later, slide 28's seeded search.

API in `Working/Detection/matrix_profiling/segments.py`:

```python
def slice_channel_profile(mp, m, a, b) -> np.ndarray      # (1), with bounds checks
def segment_profile(x, m, a, b) -> dict                   # (2)
def seed_matches(x, m, seed_idx, k, max_distance=None) -> np.ndarray  # (3)
```

UI rule: every MP plot carries a subtitle naming which of the three it is —
`"nearest neighbour across full channel"` vs `"nearest neighbour within this
segment"`. They differ most exactly where it matters (a segment whose pattern
is unique locally but common globally), so an unlabelled plot is a trap.

---

## 5. HPC export

Per the decision taken: generate the script and the recipe JSON, show the
`sbatch` line. No SSH, no submission from the UI.

`Working/hpc/job_export.py` (headless — `Working/` must not import Panel):

```python
def export_mp_job(conn, recording_id, window_min, span=None, *,
                  est_seconds=None, out_dir="HPC/Detection/generated") -> dict
    # returns {"script_path", "recipe_path", "sbatch_command", "job_name"}
```

Emits two files, named by config hash so re-exporting the same job overwrites
rather than accumulating:

- `HPC/Detection/generated/mp_{source_stem}_CH{ch}_WIN{scale}min_{hash8}.json`
  — a recipe JSON in exactly the shape `Pipelines/run_recipe/run_recipe.py`
  already reads.
- `HPC/Detection/generated/mp_..._{hash8}.sh` — the `mp_job.sh` header with:
  - `--time` set from `est_seconds × 3`, rounded up to the next 15 min, floor
    30 min (SLURM kills at the wall clock; the estimate is from a different
    machine than the one the job lands on).
  - `--job-name=mp_CH{ch}_WIN{scale}min`
  - body: `python Pipelines/run_recipe/run_recipe.py --config <recipe_path>`

**Invoke `run_recipe.py`, not `run_matrix_profile.py`.** The latter has
`CH`/`FILE`/`WINDOW_MIN` as module-level constants and would need editing per
job — precisely the thing `HPC/README.md` says not to do. Going through
`run_recipe` also means the cluster run registers its own `runs`/`artifacts`
rows, so a returned `.npz` slots into the browser with no separate import
step.

Two blockers to clear first:

- `HPC/README.md` records that `--chdir` disagrees between scripts
  (`/home/s4699158/CNN` vs `/home/Student/s4699158/CNN`). The generator needs
  one answer; put it in `Working/config.py` as `HPC_REMOTE_REPO_ROOT` and
  resolve which is correct before generating anything.
- The generated script must be checked in / synced to the cluster the same way
  the hand-written ones are; the UI's confirmation message should say where
  the file landed and that it still needs to reach rangpur.

---

## 6. The motif browser (slide 27)

A new tab, `UI/motif_browser.py`, composed by `UI/app.py` alongside
`run_panel.py` / `run_history.py`. Port of `plot_motif_slideshow` in
`Working/Detection/matrix_profiling/plot_matrix_profile.py` — same algorithm,
HoloViews/Panel rendering.

### 6.1 Precompute the group list once — the current loop cannot run on tab load

`plot_motif_slideshow` walks `np.argsort(mp)` and calls `stumpy.match` **per
slide**, then marks an exclusion zone around every returned neighbour. At the
`max_motifs=1000` used for the slide, that is up to 1000 full distance
profiles over a 1M-sample series. It is fine as a one-off script; it is not
something to do when a tab opens.

Split it:

- `Working/Detection/matrix_profiling/motif_groups.py`:

  ```python
  def build_motif_groups(x, mp, m, *, max_motifs, n_neighbors,
                         max_distance=None, on_progress=None) -> list[dict]
      # [{"seed_idx", "mp_distance", "neighbours": [(idx, dist), ...]}, ...]
  ```

  Same exclusion logic as the existing loop (`excl_zone = m // 2`, seed and
  every returned neighbour excluded from being a future seed) — keep it
  identical so the browser reproduces the slides, and note the deviation from
  `stumpy.motifs`, whose default `cutoff` is `np.nanmax(...)`-derived rather
  than `inf` and whose exclusion accounting differs. If you switch to
  `stumpy.motifs` for speed, pass `cutoff=np.inf` explicitly and verify a
  handful of groups match the current output before trusting it.

- **Persist the result.** Each group becomes one `detections` row against the
  MP's `run_id`: `start_idx=seed_idx`, `end_idx=seed_idx+m`,
  `score=mp_distance`, `meta_json={"neighbours": [[idx, dist], ...],
  "n_neighbors": N, "max_motifs": K, "rank": i}`. Browsing is then pure DB
  reads. The group set is keyed by `(run_id, n_neighbors, max_motifs,
  max_distance)`; changing any of those is a **new** group set, computed with
  a visible progress bar and stored alongside — never silently recomputed on
  every parameter nudge, and never conflated with the previous set.

### 6.2 Layout

Two stacked panes, matching the slide:

**Top — full channel with occurrence markers.**
- The curve goes through the existing rasterized `RangeX`-driven path in
  `UI/plots.py`, not a raw `hv.Curve` over 1M points. Reuse
  `build_channel_dmap`; do not write a second channel renderer.
- Occurrences as **one vectorized `hv.Rectangles`** with a `role` value
  dimension (seed / neighbour) plus one `hv.Scatter` of inverted-triangle
  markers — not one element per occurrence. `UI/README.md` records a
  confirmed multi-minute hang from per-row elements; the same failure applies
  here at 10–50 occurrences × redraws.
- Seed styled distinctly (higher alpha, border), neighbours coloured by rank
  from the existing `PALETTE`.
- Title carries `Motif {i+1} / {N}   seed @ {t:.3f} h   MP distance = {d:.4f}`,
  as on the slide.

**Bottom — z-normalised overlay.**
- One `hv.Curve` per occurrence inside an `Overlay`, legend on the right with
  `nb{k} @ {t} h  d={dist:.3f}`.
- Optional mean ± 1σ envelope over the neighbours (excluding the seed) as an
  `hv.Spread` + dashed mean `hv.Curve`.
- x-axis in seconds within the window; y-axis z-score.

**Both panes must follow the two rules `UI/README.md` states as hard-won:**
every `DynamicMap` callback returns the *same element type* on every frame
(always an `Overlay`, even when empty), and `axiswise=True` goes on **every
leaf element**, not just the enclosing `Overlay` — the overlay pane's y-range
will otherwise be captured document-wide by `_decimated_curve`'s shared
`amplitude` dimension and render every motif as a flat line.

### 6.3 Controls

Sidebar, above the panes:

| control | notes |
|---|---|
| Recording / channel | defaults to whatever the Viewer has loaded |
| **Scale** | radio group over `MP_SCALE_LADDER_MIN`, rendered from `ladder_status()`. Available scales selectable; missing ones show the estimate and a Compute button; invalid ones show why. Approximate ones are labelled. |
| ◀ / ▶ + `i / N` | group navigation, plus left/right arrow keys via the existing hidden-button pattern in `UI/app.py` |
| `n_neighbors` | 1–50, default 10 |
| `max_motifs` | 1–1000, default 50 (not 1000 — that is a long precompute; make the cost visible) |
| `max_distance` | optional cutoff, blank = ∞ |
| Jump to group | index entry, for returning to a specific motif |

Changing `n_neighbors` / `max_motifs` / `max_distance` must show "this
requires recomputing the group set (≈ Xs)" with an explicit Recompute button.
Do not recompute on every widget event.

Actions:

- **Open in Viewer** — jump the Viewer tab to the seed span, same mechanism
  `run_history.py` already uses.
- **Save group as motif** — `insert_motif` against the group's `detections`
  row, with the controlled-vocabulary tag picker (`motif_tags`), so a motif
  found here enters the same taxonomy as a hand-annotated one.
- **Segment mode** — when the Viewer has a span staged, offer both readings
  from §4 as an explicit choice, labelled, never defaulted silently.

---

## 7. Bugs in the current code, to fix as part of Stage 1–2

All in `Pipelines/matrix_profile/run_matrix_profile.py` and
`Working/Detection/matrix_profiling/plot_matrix_profile.py`:

1. **`compute_chains` cannot run.** It does
   `mp, mpi, t_mp = matrix_profile(x, t, m)` against a 4-tuple return
   (`ValueError`), then calls `stumpy.allc(mp.left_I_, mp.right_I_)` on what
   would be a plain `float32` ndarray with no such attributes. It needs the
   left/right index columns — which is the other reason §2.2 adds `left_i` /
   `right_i` to the artifact.
2. **`matrix_profile` discards `profile[:, 2:4]`.** Every existing artifact is
   therefore chain-incapable. Keep all four columns.
3. **`save_matrix_profile` references `m` without taking it as a parameter.**
   It works only because `m` happens to be a module global under
   `__main__`; imported and called from anywhere else it raises `NameError`.
   Add `m` to the signature.
4. **`plot_matrix_profile` truncates the signal but not the profile** —
   `x = x[:10000]` while `mp` is loaded full-length, so `motif_idx` from
   `argsort(mp)` indexes into a 10000-sample `t_hours`. Silently plots markers
   at wrong times, or `IndexError`s. Either slice both consistently or don't
   slice.
5. **`plot_matrix_discords`'s default `npz_path` omits the `_WIN{n}` token**,
   so it only ever finds the two legacy no-window files.
6. **`plt.style.use(<github URL>)` at import time** in
   `plot_matrix_profile.py` — a network fetch on import, which will hang or
   fail on a compute node. Vendor the `.mplstyle` locally.

---

## 8. Staging

Each stage ends in a state where the repo runs and the previous stage's
behaviour is unchanged.

**Stage 1 — storage and identity.** v2 format; `matrix_profile_store.py`;
`ladder_status`; backfill script; bugs 1–3, 6. No UI change. Test: backfill
the 8 existing artifacts, assert every one resolves through `find_mp` and that
re-running the script is a no-op.

**Stage 2 — cost and execution.** `cost.py` + calibration; `segments.py`;
extend `detection.matrix_profile` to persist `mpi`/`left_i`/`right_i`, accept
a `backend` param (`auto` / `stump` / `gpu_stump` / `scrump`), set
`max_span_samples`. Test: estimate vs. actual within 2× on three span sizes.

**Stage 3 — motif browser.** `motif_groups.py` + group persistence +
`UI/motif_browser.py`. Verify with a real browser screenshot per
`UI/README.md` §"Visual verification during development" — the two failure
modes here (flat-line overlay from missing `axiswise`, blank pane from mixed
element types) are both invisible to Python-level inspection.

**Stage 4 — HPC export.** `job_export.py`; resolve `--chdir`; generate for one
real over-threshold job and confirm the produced script runs on rangpur.

**Stage 5 — seeded discovery (slide 28).** Chains via `stumpy.allc` on the now-
stored `left_i`/`right_i`, and the `plot_seed_chain` explorer ported to Panel.
Deferred by request; Stages 1–2 must not close the door on it.

---

## 9. Verification

Beyond per-stage tests:

- `tests/test_matrix_profile_store.py` — ladder status across a channel too
  short for the top scales; stale detection after touching the source `.npy`;
  `require_exact` skipping an `approx` artifact.
- `tests/test_mp_segments.py` — construct a series where the slice-of-channel
  profile and the segment-only profile **provably disagree** (a pattern unique
  within the segment but repeated outside it) and assert both functions return
  the expected different answers. This test is the guard against §4 collapsing
  back into one code path.
- `tests/test_motif_groups.py` — group list from a synthetic series with three
  planted motifs; assert exclusion zones prevent a neighbour reappearing as a
  later seed, and that group sets are keyed correctly so changing
  `n_neighbors` yields a new set rather than mutating the old one.
- Motif browser: browser screenshot at two scales and two group indices,
  checked for a non-flat overlay pane and correctly positioned markers.
