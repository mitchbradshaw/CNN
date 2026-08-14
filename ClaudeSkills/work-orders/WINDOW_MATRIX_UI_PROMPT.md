# Window Matrix — storage, cost routing, and the timescale ladder

Implementation brief for bringing the window matrix into the UI, in the same
form as `MATRIX_PROFILE_UI_PROMPT.md` and `DSAX_UI_PROMPT.md`. Written
2026-08-10 against the repo as it stands.

Scope: a stable, tested `WindowMatrix`; a storage format that replaces the
Excel/CSV files in `MATRICES/`; the same `configs`/`runs`/`artifacts` registry
the matrix profile uses; a fixed timescale ladder shared with matrix
profiling; per-stage cost routing between in-UI / background / HPC; and a
coverage display so a user can see which regions of a channel already have
window matrices, at which scales.

Dendrogram clustering is **out of scope here** and is Stage 5 below — but the
storage format and the preprocessing pipeline must carry what it needs, so
don't drop the `computed` mask or collapse partial matrices into full ones on
the way through.

---

## 0. Two corrections that shape everything below

### 0.1 A window matrix at one timescale is not derivable from another

Same correction as `MATRIX_PROFILE_UI_PROMPT.md` §0, for a different reason,
and it must not be encoded away.

Almost none of the measures in the matrix are aggregatable. Sample entropy of
a 60-minute window is not any function of the sample entropies of the six
10-minute windows inside it — the template-matching count that defines it
ranges over the whole window, so the cross-boundary pairs that exist at 60
minutes have no representative at 10. The same holds for every Catch22
feature (all are non-linear statistics of the window), for permutation and SVD
entropy (both depend on embedding vectors that straddle sub-window
boundaries), and for the CNN scores (a Gramian image of a 60-minute window is
not a tiling of six 10-minute images).

Two measures *look* aggregatable and are not: Shannon entropy over a
histogram is not the mean of sub-window Shannon entropies (Jensen), and
spectral entropy at 60 minutes resolves frequencies that do not exist in a
10-minute periodogram at all.

**So: fixed ladder, each timescale computed independently, no derivation
between scales.** Wherever the UI shows a scale that has not been computed, it
says "not computed" — never estimates it from a neighbouring scale.

### 0.2 NaN is currently used as two different sentinels, and the job chain depends on the difference

`Pipelines/window_matrix_build/build_window_matrix.py` decides what still
needs computing by looking for NaN:

```python
def _pending(wm, first_col):
    if first_col not in wm.df.columns:
        return list(wm.df.index)
    return wm.df.index[wm.df[first_col].isna()].tolist()
```

But `compute_incremental` also *writes* NaN when a feature function raises:

```python
except Exception as exc:
    log.warning("[%s] window %d raised %s — storing NaN", stage_name, idx, exc)
    out = np.nan if scalar else [np.nan] * len(col_names)
```

So "not yet computed" and "computed, and the answer is NaN" are the same
value. A window that reliably raises — a flat segment where sample entropy has
no matching template, a truncated tail window, a channel gap — is retried on
every subsequent job, forever. It is never marked done, so `--status` never
reports `DONE` for that stage, so this in `HPC/Preprocessing/wm_job.sh`:

```bash
if printf '%s\n' "$STATUS_OUT" | grep -qE "(not started|[0-9]+ / [0-9]+)"; then
    sbatch "$(pwd)/HPC/Preprocessing/wm_job.sh"
```

**resubmits the job chain indefinitely.** One unluckily-shaped window burns the
allocation until someone notices and `scancel`s it.

This is not a detail to fix in passing — it determines the storage format.
Every design below carries an explicit `computed` boolean mask alongside the
values, so "never attempted" and "attempted, result was NaN" are distinct
states at rest, in the artifact, not just in memory during one job.

---

## 1. The canonical timescale ladder

Defined once, in `Working/config.py`, deliberately reusing the matrix-profile
ladder's *values* so a user comparing an MP at 10 minutes against a window
matrix at 10 minutes is comparing the same span of signal:

```python
# Window-matrix timescale ladder, in minutes. Shares MP_SCALE_LADDER_MIN's
# values so the two features' scale switchers agree; kept as a SEPARATE
# constant because their validity rules differ (see below) and because a
# future divergence must not be a silent edit to the MP ladder.
WM_SCALE_LADDER_MIN = (1, 10, 60, 600)
```

At `fs=1` that is `m = 60 / 600 / 3600 / 36000` samples per window.

Rules — note these are **not** the matrix profile's rules:

- **A scale is valid for a span only if the measures are defined on it.**
  `MP_MIN_WINDOW_SAMPLES = 4` is stumpy's floor. The window matrix's floor is
  set by its slowest-to-define measure, not by an array-length check:
  permutation entropy at `order=3` needs `m >= 4` but is meaningless below a
  few dozen; Catch22 features have their own internal minima; a periodogram
  over 15 samples has 8 bins. `WM_MIN_WINDOW_SAMPLES = 32` is the floor —
  above stumpy's, and chosen so every measure in §2 returns something
  interpretable rather than something merely non-crashing.
- **A scale is valid only if it yields enough windows to be a matrix.**
  `n_windows = floor((span_len - m) / step) + 1`. Below
  `WM_MIN_WINDOWS = 3` there is no matrix, just a few rows;
  `preprocess_window_matrix` will drop most columns as constant and clustering
  is meaningless. This is a genuinely different failure from MP's, which is
  perfectly happy on a short series.
- **Some scales are valid for some measures and not others.** This has no
  matrix-profile equivalent and is the ladder's most important difference —
  see §3.3. A ladder entry can be "available for 28 of 33 measures", which is
  a real, legitimate state, not an error.
- **`fs` is part of the identity.** `WM_SCALE_LADDER_MIN` is in minutes so the
  same ladder means the same thing at `fs=0.25` and `fs=1`; `m` is derived,
  never stored as the primary key. At `fs=0.25`, the 1-minute entry gives
  `m=15` and is **invalid** by `WM_MIN_WINDOW_SAMPLES` — the ladder is
  genuinely shorter at a lower sample rate, and the UI must say why rather
  than offering a Compute button that produces garbage.
- **Step fraction is not part of the ladder.** `step_frac` (1.0 = contiguous
  non-overlapping windows, 0.5 = 50 % overlap) stays a free parameter with
  default 1.0. Matrices at a non-default `step_frac` are still stored and
  still usable via the adapter's own parameter, but they are **not** browsable
  in the scale switcher — same treatment `MATRIX_PROFILE_UI_PROMPT.md` §1
  gives off-ladder windows, and for the same reason: the ladder exists to make
  scales comparable across channels and recordings.

---

## 2. The measure set

Confirmed 2026-08-10: **single-value measures only, redundant twins dropped.**
33 columns.

| group | count | columns |
|---|---|---|
| Entropy | 6 | `shannon entropy`, `spectral entropy`, `svd entropy`, `permutation entropy`, `sample entropy`, `approximate entropy` |
| Catch22 | 22 | `catch22_{name}` for each of `CATCH22_FEATURE_NAMES` |
| CNN | 4 | `cnn_p_{fusion,GASF,GADF,recurrence}_interesting` |
| Random forest | 1 | `rf_p_interesting` |

Column names are kept **exactly as the existing CSVs spell them**, including
the spaces in the entropy names, so the backfill in §5 is a pure
re-serialisation and existing analysis code keeps working. The names are ugly;
changing them is a separate decision with its own migration, not something to
do quietly inside a storage change.

### 2.1 What is excluded, and why

- **`cnn_p_*_notinteresting`, `rf_p_notinteresting`** — these are `1 - p` of
  their twins to within float error. Keeping both puts a perfectly
  anti-correlated pair into a Euclidean distance, which double-weights the
  CNN/RF direction relative to every other measure. `preprocess_window_matrix`
  does not currently catch this (it has no correlation filter), so today they
  silently bias the clustering.
- **SAX / cSAX / pSAX / dSAX columns** — symbol strings, not scalars. They
  round-trip through CSV as string reprs of lists and are then dropped by
  `_remove_non_numeric` anyway. They belong in the encoding cache
  (`Working/encoding_cache.py`), which already stores them properly.
- **`stft_bin_0..63`** (present in `MATRICES/features.csv`) — a 64-element
  spectrum is a vector measure, not a single-value one. It also single-handedly
  triples the feature count and pushes `preprocess_window_matrix` past its own
  `warn_high_dim=100` threshold. If band power is wanted later, add a handful
  of named band-power scalars, not 64 raw bins.
- **`category`, `fusion_pred_v1`, `fusion_pred_v1_error`** — labels and
  predictions. They are metadata (`_DEFAULT_METADATA_COLS` already treats them
  as such) and must never enter a distance calculation.
- **`mean`, `std_dev`** (present in the legacy `features.csv`) — excluded to
  keep the set to what slide 20 shows. See the limitation below.

### 2.2 A limitation worth stating out loud

Catch22 operates on z-normalised windows. Shannon entropy is computed over a
50-bin histogram of the window's own range. Permutation and SVD entropy are
ordinal/subspace measures. The Gramian encodings feeding the CNN are
themselves normalised per window.

**The 33-column set therefore contains essentially no amplitude information.**
Two windows with identical shape and a 100× amplitude difference land in the
same place in feature space. That is a defensible choice — it is what makes
windows comparable across electrodes with different contact impedance — but it
is a choice, and it means "cluster 3" can never mean "the high-amplitude
state". If amplitude structure turns out to matter, the fix is a small named
set (`window_mean`, `window_std`, `window_ptp`, `window_rms`) added as a
distinct group, not a quiet reintroduction of the legacy `mean`/`std_dev`
columns.

---

## 3. Storage format and the run registry

### 3.1 What is wrong with the current files

```
MATRICES/
  features.csv                                   <- start_idx, category, entropy,
                                                    std_dev, mean, Unnamed: 5, stft_bin_0..63
  features - Copy.csv                            <- unknown relationship to the above
  features_graph.csv
  M2_concat_fs1_10min_27118wins_consecutive.csv  <- only 2 columns: cnn_p_interesting,
                                                    cnn_1_minus_p_notinteresting
  0.01_percent_M2_concat_fs1.mat_step0.5.csv     <- ".mat" inside a .csv name
  0.01_percent_M2_concat_fs1_consecutive.csv
```

Five problems, all of which block "show me the existing window matrices for
this channel":

- **No channel in any filename.** `M2_concat_fs1_10min_27118wins_consecutive.csv`
  does not say which of the 16 channels it is. Nothing in the file says either.
- **No `fs`, `timescale`, or `step_frac` inside the file.** `load_matrix` takes
  `timescale` and `fs` from the *caller*:

  ```python
  wm = WindowMatrix(df.index.tolist(), x, timescale, fs)
  ```

  Load a matrix with the wrong `TIMESCALE` and every subsequent
  `get_window_signal(idx)` returns a wrong-length slice, silently. There is no
  check and no error.
- **Window count encoded in the filename** (`27118wins`) rather than derived —
  which means it can disagree with the file's actual contents.
- **Nothing records the source data's identity.** Re-materialise a channel and
  every existing CSV is stale with no way to detect it. The matrix profile
  solved this with `data_sha1`; the window matrix has no equivalent.
- **NaN is overloaded** (§0.2), so a partially-built matrix cannot be
  distinguished from a fully-built one containing legitimate NaNs.

Two of these files (`features.csv`, `features - Copy.csv`) also carry an
`Unnamed: 5` column — a pandas artefact of a trailing comma — which
`_remove_non_numeric` happens to drop, but only by luck.

### 3.2 New format

Path:
`Results/Preprocessing/window_matrix/wm_v1_{source_stem}_CH{ch}_WIN{window_min:g}min_STEP{step_pct:d}pct.npz`

`.npz`, not Parquet or CSV: it is what the matrix-profile artifacts already
use, it needs no dependency the repo doesn't have (there is no `pyarrow`
anywhere in this tree), and the payload is a dense float32 rectangle plus a
boolean mask — precisely what `savez_compressed` is good at. At the repo's
real size (27,118 windows × 33 features) that is 3.6 MB of values and 0.9 MB
of mask before compression.

| key | dtype | note |
|---|---|---|
| `values` | float32 `(n_windows, n_features)` | the matrix |
| `computed` | bool `(n_windows, n_features)` | **the fix for §0.2.** True where a value was actually attempted and produced (NaN included); False where never attempted. Resume reads this, never `isnan(values)`. |
| `columns` | `<U` `(n_features,)` | column names, order matches `values` axis 1 |
| `start_idx` | int64 `(n_windows,)` | window start, absolute sample index in the channel — not relative to the span |
| `m` | int32 | window length in samples |
| `step` | int32 | step in samples |
| `fs` | float32 | |
| `window_min` | float32 | |
| `step_frac` | float32 | |
| `span_start`, `span_end` | int64 | region of the channel this matrix covers |
| `n_samples` | int64 | length of the source channel |
| `partial_tail` | bool | whether windows shorter than `m` were included (default False — see §4.1) |
| `complete` | bool | `computed.all()`, stored explicitly so a reader doesn't have to load the mask to know |
| `source_file`, `channel`, `recording_id` | | identity of the input |
| `data_sha1` | str | sha1 of the source `.npy` — staleness detection, same helper the MP store uses |
| `config_hash` | str | links to `configs` |
| `builder_version`, `created_at`, `elapsed_s` | | provenance |

`start_idx` is **absolute in the channel**, not relative to `span_start`. This
is the one place it is worth deviating from a "spans are self-contained"
instinct: the whole point of §6 is overlaying coverage from several matrices
onto one channel plot, and a relative index would need `span_start` added back
at every read site — which is exactly the kind of thing that gets forgotten in
one of them.

`t` (window mid-point times) is **not** stored — it is
`(start_idx + m/2) / fs`, recomputable, and storing it would add a float array
the length of the matrix for nothing. This is the same call
`MATRIX_PROFILE_UI_PROMPT.md` §2.2 makes about `t_mp`.

### 3.3 Per-column availability

A ladder scale can be valid for some measures and not others. Two hard limits:

- **Sample entropy and approximate entropy are O(m²) per window.** At `m=600`
  (10 min at fs=1) that is ~360 k operations per window and already the
  dominant cost. At `m=36000` (600 min) it is 1.3 × 10⁹ per window, ×~120
  windows for a 4-day channel. Not slow — infeasible.
  `WM_SLOW_ENTROPY_MAX_SAMPLES = 4096`.
- **The Gramian encodings behind the CNN scores are O(m²) in memory.** A GASF
  image at `m=36000` is a 36000² float matrix before the resize to 224² — ~5 TB.
  The `catalogue_gramian_*` adapters already declare `max_span_samples` for
  exactly this reason; reuse that number rather than inventing a second one.
  `WM_GRAMIAN_MAX_SAMPLES` = whatever `Adapters/catalogue_gramian_gasf.py`
  declares.

Above those limits the affected columns are **unavailable at that scale** —
not slow, not missing, not failed. They are written with `computed=False` and
the artifact records why. `ladder_status` reports
`"available (28/33 measures)"` and the UI names which groups are excluded.

This is the window matrix's analogue of the matrix profile's `invalid` state,
and it is finer-grained: MP scales are all-or-nothing, WM scales are not.

### 3.4 The registry is the existing `runs` tables — do not add a sidecar index

Identical reasoning to `MATRIX_PROFILE_UI_PROMPT.md` §2.3, and it applies
unchanged. A stored window matrix is already expressible in the schema: a
`configs` row (recipe = one `preprocessing.window_matrix` step with
`window_min=S`, `step_frac=F`), a `runs` row with `status='completed'` and the
span, and an `artifacts` row of `kind='encoding'`.

Add `Working/database/window_matrix_store.py` — a thin, headless query layer,
no new tables, deliberately shaped like `matrix_profile_store.py` so the two
read as siblings:

```python
def list_wm_runs(conn, recording_id, *, include_partial=True) -> list[dict]
    # one dict per stored WM: window_min, step_frac, m, n_windows,
    # columns, complete, n_computed, run_id, artifact_path, span,
    # created_at, elapsed_s, stale (bool)

def find_wm(conn, recording_id, window_min, *, step_frac=1.0,
            span=None, require_complete=False) -> dict | None
    # prefers complete-and-fresh, then partial-and-fresh, then stale --
    # but a stale or partial result is returned WITH its flags set, never
    # silently dropped and never silently substituted for a complete one.

def ladder_status(conn, recording_id, fs, n_samples, *, step_frac=1.0) -> list[dict]
    # one row per WM_SCALE_LADDER_MIN entry:
    #   {"window_min", "m", "step", "n_windows",
    #    "state": "available"|"partial"|"stale"|"missing"|"invalid",
    #    "available_columns", "unavailable_columns", "reason",
    #    "est_seconds", "run_id"}

def coverage_for_span(conn, recording_id, span, *, step_frac=1.0) -> dict
    # {window_min: [(start, end), ...]} -- merged intervals of the channel
    # already covered by a stored matrix at each ladder scale. Backs §6.

def load_wm(artifact_path, *, mmap=True) -> dict
def save_wm(...) -> str        # writes the v1 npz, returns the path
def to_dataframe(loaded) -> pd.DataFrame   # start_idx-indexed, NaN where
                                           # computed is False
```

`stale` = the artifact's `data_sha1` no longer matches the current `.npy`.
Reuse `matrix_profile_store.compute_data_sha1` rather than writing a second
one — it is already streamed in 1 MiB chunks and already tested.

`to_dataframe` is the bridge to everything downstream: `preprocess_window_matrix`
takes a DataFrame, so the dendrogram pipeline needs no changes to consume the
new format. It sets `NaN` wherever `computed` is False, which is exactly the
right input for `preprocess_window_matrix`'s existing `nan_col_threshold` /
`impute_strategy` handling — an unavailable column at that scale (§3.3) is
100 % NaN and gets dropped by `_remove_all_nan_columns` on its own.

---

## 4. Fixing the algorithms

### 4.1 `Working/Preprocessing/window_matrix/matrix_calc.py`

1. **Tail windows are computed on truncated data.**
   `create_matrix_at_timescale` does `np.arange(0, len(x), stepsize)`, which
   emits start indices right up to `len(x)`. The final `m/step` windows are
   shorter than `m` — `get_window_signal` silently returns the short slice and
   every feature function computes on it. Only the RF path checks
   (`if len(sig) < win_len: continue`); Catch22 and the entropies do not. The
   last windows of every existing matrix therefore carry values that look
   comparable to the rest and are not.
   Fix: generate indices over `range(0, len(x) - m + 1, step)` by default, and
   add an explicit `partial_tail: bool = False` parameter for callers who
   genuinely want the ragged tail. Record it in the artifact.

2. **`step_frac=0` crashes.** `stepsize = int(np.floor(stepfrac * winlength))`
   gives 0, and `np.arange(0, n, 0)` raises. Validate `0 < step_frac <= 1` and
   `step >= 1` with a message that names the parameter.

3. **`save_window` hardcodes `MATRICES/` relative to the process CWD** and
   prefixes the directory *inside* the function, while `load_matrix` takes a
   full path. So `wm.save_window("a.csv")` and `load_matrix("a.csv")` refer to
   different files, and neither works unless the process was started from the
   repo root. Make both take a path; keep a thin
   `save_window(name)` shim during the transition if anything still calls it.

4. **`load_matrix` loses all column metadata.** Every column comes back as
   `{"type": "external"}`, so `recompute_column` raises `TypeError` on any
   reloaded matrix — the method is unusable in practice. Either persist the
   column kind in the artifact (the v1 format has room) or delete
   `recompute_column`; a method that only works on a matrix that has never
   been saved is a trap.

5. **`add_vector_columns` accepts `n` and immediately overwrites it**
   (`n = vectors.shape[1]` on the line after the ragged check). The documented
   "expected output length" validation never runs. Either honour the parameter
   or remove it.

6. **`np.array([fn(...) for ...])` in `add_vector_columns`** raises an opaque
   dtype error on ragged output rather than naming the offending window.

7. **`WindowMatrix` holds the full signal `self._x`** and `save_window` writes
   only the DataFrame — so a matrix is never self-describing. The v1 format
   fixes this by storing `recording_id` + `data_sha1`; `load_wm` should
   re-derive the signal through `Working.database.queries.get_recording_by_id`
   rather than making the caller supply it.

### 4.2 `Pipelines/window_matrix_build/build_window_matrix.py`

8. **The NaN-sentinel / infinite-resubmit bug** — §0.2. This is the one that
   costs real allocation hours.

9. **`_is_complete` is defined and never called.**

10. **`CH` / `FILENAME` / `WINSIZE` / `FS` / `STEPFRAC` are module-level
    constants**, edited per job — exactly what `HPC/README.md` says not to do,
    and the reason §7's HPC export goes through `run_recipe.py` instead.

11. **`float(out)` on line 220 is outside the try block** that catches feature
    failures, so a function returning `None` raises `TypeError` and kills the
    stage rather than being recorded as a failed window.

### 4.3 `Working/Preprocessing/window_matrix/plot_matrix.py`

12. **`plot_wm_signal` multiplies by `fs` where it should divide:**

    ```python
    t = np.linspace(0, len(x)*fs, len(x))
    ```

    Correct is `len(x)/fs`. At `fs=1` the two agree, which is why this has
    never been caught — and why it will silently produce a 4×-wrong time axis
    the first time it is used on an `fs=0.25` output.

13. `plot_singlevalue_columns` reaches into `wm._x`, `wm._fs`,
    `wm._window_samples`. Add real accessors; the private attributes are
    already load-bearing in three modules.

### 4.4 `Working/Catalogue/dendrogram/dendrogram_cluster.py`

14. **`ssd.pdist(X)` is computed unconditionally**, including for
    `method="ward"`, which scipy computes from `X` directly and does not need
    it. At the repo's real matrix size (27,118 windows) the condensed distance
    array is 3.7 × 10⁸ doubles — **2.9 GB** — allocated before linkage starts.
    The existing `_PDIST_MEMORY_WARN_MB = 400` warns and then proceeds anyway.
    Fix: compute `dist_condensed` only when the linkage method needs it, or
    when the caller explicitly asks for the cophenetic correlation. Make the
    memory check a refusal above a hard ceiling, not a warning.

15. **`silhouette_score` calls `ssd.squareform(dist_condensed)`** — a *second*
    n² allocation on top of the condensed one, at double the size. Use
    `sample_size=` or the raw-feature path instead of materialising the square
    form.

16. **`_remove_near_constant_columns` filters on the wrong quantity.** It drops
    columns whose coefficient of variation `std / |mean|` is below 1 %. The
    very next step is `StandardScaler`, which makes relative spread
    irrelevant — a Catch22 feature centred at 100 with std 0.9 has CV 0.009 and
    is dropped, despite being perfectly discriminative once z-scored. The
    criterion should be near-zero *absolute* variance relative to float
    precision (guarding the divide-by-zero that motivated it), not relative
    spread. Keep the CV filter available behind a flag if it is wanted for a
    different reason, but it must not be the default.

17. `_remove_near_constant_columns` also materialises
    `df.abs().values.flatten()` — a full copy of the matrix — to compute a
    single median. Use `np.nanmedian` over a subsample.

18. **No correlation filter.** With `cnn_p_*_notinteresting` present (as in
    every existing matrix), pairs at `r = -1.0` survive into the distance
    calculation. §2.1 removes them at the source; the pipeline should still
    refuse to cluster on a pair above `|r| > 0.99` and say which columns it
    dropped. The docstring already recommends this as a "future extension";
    the data it is run on makes it a present requirement.

19. `find_outliers` computes `(d - mean) / std` on a distance-from-centroid
    distribution and calls it a z-score. That distribution is right-skewed by
    construction (a norm of squared terms), so a symmetric ±3σ cut over-flags
    on the upper tail by design. Worth a docstring note at minimum; a
    quantile-based threshold would be more honest.

---

## 5. Backfill

`Pipelines/import_wm_artifacts/import_wm_artifacts.py` — one-shot, idempotent,
safe to re-run. Same shape as the matrix-profile backfill.

1. Scan `MATRICES/` for `*.csv`.
2. Parse what the filename carries. Only
   `M2_concat_fs1_CH{n}_WIN{n}min_STEP{n}pct.csv` (the naming
   `build_window_matrix.py` produces) is fully self-describing. For the rest:
   - `M2_concat_fs1_10min_27118wins_consecutive.csv` — timescale and window
     count are recoverable, **channel is not**. Report it and require the
     channel to be passed explicitly (`--channel`); do not guess.
   - `features.csv`, `features - Copy.csv`, `features_graph.csv` — no
     recoverable identity at all. Report them, import nothing, leave them in
     place.
   - `0.01_percent_*` — a 0.01 % subsample, not a matrix over a real channel
     span. Report and skip.
3. For anything importable: derive `start_idx` from the index, cross-check
   `m` against the recording's `n_samples` and the observed index spacing, and
   **fail loudly if the implied step is not consistent across the file** —
   an inconsistent spacing means the filename's timescale is wrong.
4. Set `computed = ~isnan(values)` for backfilled matrices, with a
   `backfilled=True` flag in the artifact, so a reader knows the mask is
   *inferred* (and therefore still conflates the two NaN meanings for
   pre-existing files) rather than recorded. Nothing can recover the
   distinction retroactively; recording that it is unrecoverable is the
   honest option.
5. Drop excluded columns per §2.1, logging each drop.
6. Register `configs` / `runs` / `artifacts` rows via `get_or_create_config` +
   `insert_run` + `insert_artifact`.
7. Move originals to `MATRICES/_legacy/` rather than deleting them — same as
   `Results/Detection/matrix_profile/_legacy/`.
8. Re-running is a no-op: `get_or_create_config` is idempotent on hash, and
   an existing completed run over the same (recording, span) short-circuits.

---

## 6. Cost model and execution routing

### 6.1 Estimating — different shape from the matrix profile

`MATRIX_PROFILE_UI_PROMPT.md` §3.1 gets away with one constant per backend
because `stump` is O(n²) in series length and flat in `m`. The window matrix
is the opposite: **linear in the number of windows, and strongly
super-linear in `m` per window**, with the exponent differing by stage.

```
t_est = n_windows * sum_over_enabled_stages( k_stage * cost_shape_stage(m) )

n_windows = floor((span_len - m) / step) + 1

cost_shape:
  catch22          m * log(m)
  fast entropy     m * log(m)     (shannon, spectral, svd, permutation)
  slow entropy     m ** 2         (sample, approximate)
  gramian + CNN    m ** 2         (image construction; the 224x224 forward
                                   pass itself is constant)
  random forest    m              (single predict_proba over the raw window)
```

`Working/Preprocessing/window_matrix/cost.py`, mirroring
`Working/Detection/matrix_profiling/cost.py`'s structure and its refusal to
guess:

- `calibrate(force=False)` — times each stage on synthetic windows at two `m`
  values, solves for `k_stage` against the shape above, writes
  `DATA/db/wm_calibration.json` keyed by
  `{cpu_count, gpu_name, aeon_version, torch_version}`. Two `m` values, not
  one, specifically so a wrong exponent shows up as a bad fit rather than
  being absorbed into `k`.
- `estimate_seconds(n_windows, m, stages)` — returns `None` if uncalibrated,
  never a hardcoded fallback. Same reasoning as the MP module: a wrong
  estimate here routes a multi-hour job into the "wait with a spinner" path.
- `routing_tier(seconds)` — reuses the MP thresholds' *structure* with its own
  constants, since the workloads are not comparable:

  ```python
  WM_INTERACTIVE_BUDGET_S = 60     # <= this: run inline, progress bar
  WM_BACKGROUND_BUDGET_S  = 900    # <= this: background + cancel
                                   #  > this: HPC export
  ```

- `max_span_samples_for_background(m, stages)` — the `max_span_samples` the
  adapter declares at registration, computed rather than hardcoded, `None`
  while uncalibrated.

**A real progress bar is free here**, unlike for the matrix profile. The build
is already a per-window loop with a natural `n_windows` denominator, so
`on_progress(done, total)` is exact — no SCRIMP++-style anytime approximation
needed to fake determinacy.

### 6.2 Routing

- **Interactive** — run inline with a determinate progress bar driven by the
  window loop. Cancellable between windows (not between steps, as
  `execute_recipe` is for multi-step recipes) — a single feature call on one
  window is short enough that between-window granularity is responsive.
- **Background** — thread + Cancel, `runs` row goes `running` → `completed` /
  `failed`, so a crash mid-run leaves a visible record rather than a missing
  artifact.
- **HPC** — §7.

The estimate and the chosen tier are always displayed *before* the user
commits ("≈ 6 min 40 s over 1,247 windows — will run in the background"),
never after. Where a stage is unavailable at the chosen scale (§3.3), the
estimate is for the stages that *will* run and the message names the ones that
won't.

### 6.3 Checkpoint and resume are part of the adapter, not a separate script

The existing builder's checkpoint/resume is the right idea in the wrong place
— it lives in a script with hardcoded module constants. Move it into the
adapter:

- The adapter takes `timeout_s` (default `None` = no limit).
- On timeout it stops cleanly, returns what it has, and the `persist` hook
  writes an artifact with `complete=False` and a `computed` mask recording
  exactly which cells were done.
- On the next run of the *same recipe over the same span*, the adapter loads
  the existing artifact via `find_wm`, seeds itself from the `computed` mask,
  and continues.

The `runs` row is genuinely `completed` — the step ran to its declared
timeout and produced a valid artifact. The *matrix* is partial, and that is a
property of the artifact, recorded in the artifact. Do not mark the run
`failed` to signal partiality; a failed run means the step raised.

---

## 7. HPC export

Same decision as the matrix profile: generate the script and the recipe JSON,
show the `sbatch` line. No SSH, no submission from the UI.

Generalise `Working/hpc/job_export.py` rather than copying it —
`_slurm_time_from_estimate`, `_SCRIPT_TEMPLATE`, and the config-hash naming
are already correct and shared:

```python
def export_wm_job(conn, recording_id, window_min, span=None, *,
                  step_frac=1.0, stages=None, est_seconds=None,
                  timeout_min=None, out_dir="HPC/Preprocessing/generated") -> dict
    # returns {"script_path", "recipe_path", "sbatch_command", "job_name"}
```

Differences from `export_mp_job`, all of them consequences of the window
matrix being resumable:

- Output goes to `HPC/Preprocessing/generated/` (matching `wm_job.sh`'s
  location), named `wm_{stem}_CH{ch}_WIN{scale}min_STEP{pct}pct_{hash8}`.
- The recipe carries `timeout_s` set from the SLURM `--time` minus a cleanup
  margin, so the job saves and exits *before* SLURM kills it. `wm_job.sh` gets
  this right today (`--time=00:20:00` against `--timeout 19`) and the
  generated script must preserve the relationship rather than rediscovering it.
- **The generated script keeps the self-resubmit chain**, because the window
  matrix genuinely resumes and the matrix profile does not. But it must
  resubmit on the *artifact's* `complete` flag, not by grepping `--status`
  text — that string-matching is what turns §0.2's stuck window into an
  infinite loop. A small `--check-complete` entry point returning an exit code
  is the right interface.
- A hard cap on chain length (`SBATCH` job counter or a recorded resubmit
  count) so that even a bug that always reports incomplete terminates.
- `--gres=gpu:a100` only when a CNN stage is enabled; a Catch22 + entropy
  build is CPU-only and should not queue for a GPU node.

`HPC_REMOTE_REPO_ROOT` in `Working/config.py` is already the one answer to the
`--chdir` disagreement `HPC/README.md` records. Reuse it; do not add a second.

---

## 8. The UI

### 8.1 Where it attaches

`preprocessing.window_matrix` is a normal adapter, so the Run panel builds its
parameter controls automatically from `AdapterSpec.params` — no hand-built
form. What needs deliberate design is the timescale control and the coverage
display.

### 8.2 The timescale control

A `pn.widgets.RadioButtonGroup` over `WM_SCALE_LADDER_MIN`, rendered from
`ladder_status()` — the same pattern `UI/motif_browser.py` already uses for the
matrix-profile ladder, and it should look and behave identically so the two
features feel like one system.

Per entry:

| state | affordance |
|---|---|
| `available` | selectable; label carries `n_windows` and, if fewer than all 33, `"28/33 measures"` with the excluded groups named |
| `partial` | selectable; shows `"1,180 / 1,247 windows"` and a Resume button |
| `stale` | greyed, reason shown, Recompute button |
| `missing` | shows the estimate and the tier ("≈ 6 min — background"), Compute button |
| `invalid` | greyed, no Compute button, reason shown (`m = 15 samples at fs=0.25; measures need at least 32`) |

Never estimate an uncomputed scale's *contents* from a neighbouring one
(§0.1). The estimate shown for a `missing` entry is a **cost** estimate, and
the label must make that unambiguous.

### 8.3 Coverage — item 3

When the window-matrix preprocessing step is selected in the Run panel, show
which regions of the current channel already have matrices, and at what
scales.

**Reuse the reviewed-coverage ribbon machinery in `UI/plots.py`.** Do not
build a new overlay. `build_reviewed_ribbon` already solves this exact
rendering problem — it buckets the channel, computes true fractional coverage
per bucket via `merge_intervals`, and renders full / partial / absent as three
*distinct colours* rather than an alpha blend, specifically because scattered
short spans across a multi-million-sample channel otherwise merge visually
into apparent continuous coverage at a coarse zoom. That failure mode is
identical here and misleads in the same direction.

So: one ribbon pane per ladder scale with a stored matrix, stacked, each
labelled with its scale, sharing the main plot's x-range and using the
existing `RIBBON_PANE_HEIGHT` / `RIBBON_FRAME_MIN_BORDER_LEFT` /
`RIBBON_FRAME_MIN_BORDER_RIGHT` constants so the frames line up with the curve.
`coverage_for_span` (§3.4) supplies the intervals; `merge_intervals` merges
them, so a scale covered by three overlapping runs reports one interval, not
three.

The two rules `UI/README.md` records as hard-won apply unchanged: every
`DynamicMap` callback returns the same element type on every frame (always an
`Overlay`, even when empty), and `axiswise=True` goes on **every leaf
element**, not just the enclosing `Overlay`.

A scale with a partial matrix renders in the partial colour — the same
distinction the reviewed ribbon already draws, reused rather than re-invented.

### 8.4 Running — item 4

Below the ladder: the estimate, the tier, and one primary button whose label
is the tier (`Compute (≈ 42 s)` / `Compute in background (≈ 6 min)` /
`Export HPC job (≈ 4 h)`).

- Interactive → inline `pn.indicators.Progress`, determinate, driven by
  `on_progress(done, total)` from the window loop, with a Cancel button.
- Background → same progress bar, tab stays usable.
- HPC → calls `export_wm_job`, then shows the two generated paths and the
  `sbatch` line, **and states explicitly that the files still need to reach
  rangpur** — the module writes only into the local working tree, and a
  confirmation that reads like the job was submitted would be a lie.

---

## 9. Staging

Each stage ends in a state where the repo runs and the previous stage's
behaviour is unchanged.

**Stage 1 — storage and identity.** `WM_*` constants; v1 npz format;
`window_matrix_store.py`; `ladder_status`; `coverage_for_span`; backfill
script; the `matrix_calc.py` / `plot_matrix.py` fixes in §4.1 and §4.3. No UI
change. Test: backfill the importable files in `MATRICES/`, assert every one
resolves through `find_wm`, and that re-running the script is a no-op.

**Stage 2 — cost and execution.** `cost.py` + calibration;
`Adapters/preprocessing_window_matrix.py` with `persist`, `timeout_s`,
resume-from-mask, per-stage availability guards, `max_span_samples`; the
dendrogram scalability and filtering fixes in §4.4. Test: estimate vs. actual
within 2× at three window counts; a timed-out run resumes to completion across
two invocations and produces the same values as a single uninterrupted run.

**Stage 3 — UI.** Timescale radio group; per-scale coverage ribbons; progress
bar; background tier. Verify with a real browser screenshot per
`UI/README.md` §"Visual verification during development" — a blank ribbon pane
from a mixed `DynamicMap` element type is invisible to Python-level
inspection.

**Stage 4 — HPC export.** `export_wm_job`; generated chain script with the
resubmit cap; confirm the produced script runs on rangpur.

**Stage 5 — dendrogram analysis.** Deferred by request. Stages 1–4 must not
close the door on it: the `computed` mask, `to_dataframe`, and the correlation
filter in §4.4 all exist because clustering will consume this.

---

## 10. Verification

Beyond the per-stage tests:

- `tests/test_window_matrix_store.py` — ladder status on a channel too short
  for the top scales; ladder status at `fs=0.25` where the 1-minute entry is
  invalid; staleness after touching the source `.npy`; `require_complete`
  skipping a partial artifact; `coverage_for_span` merging three overlapping
  runs into one interval.
- `tests/test_window_matrix_resume.py` — **the §0.2 guard.** Build a matrix
  where one window's feature function always raises. Assert that after the
  first run the cell has `computed=True` and `value=NaN`, that a second run
  does *not* retry it, and that `complete` is True. This test is the reason
  the mask exists; without it the format silently degrades back to
  NaN-as-sentinel the first time someone "simplifies" the writer.
- `tests/test_window_matrix_tail.py` — assert no window shorter than `m` is
  emitted with `partial_tail=False`, and that the last emitted window's
  `start_idx + m <= span_end`. The current code fails both.
- `tests/test_wm_backfill.py` — import the importable `MATRICES/` files;
  assert the unidentifiable ones are reported and left in place, that the
  imported ones round-trip to the same values, and that a second run writes
  nothing.
- `tests/test_wm_cost.py` — fit quality on the two-point calibration; assert
  `estimate_seconds` returns `None` when uncalibrated rather than a number.
- Coverage ribbons: browser screenshot at two zoom levels with two scales
  stored over disjoint spans, checked for correctly positioned bands and a
  visible gap colour between them.
