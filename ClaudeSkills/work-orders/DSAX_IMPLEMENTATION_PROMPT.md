# Work order: implement dSAX (trend-symbolic encoding) — headless only

You are working autonomously in the CNN repo. **I have stepped away from the computer and will not answer questions.** Do not stop to ask anything. Where this brief is ambiguous or where you disagree with it, make a reasonable decision, implement it, and justify the choice in the final summary document. Never block on a decision; never leave the work half-finished waiting for input.

---

## 0. Hard constraints — read before touching anything

1. **Do not modify, create, or delete any file under `UI/`.** I am actively editing that directory. Any change there will be lost or will cause a conflict.
2. **Do not create `Adapters/detection_sax_dsax.py`.** `Adapters/registry.discover_adapters()` auto-imports every module in `Adapters/`, so an adapter placed there would immediately appear in the UI run panel — which is exactly what I don't want yet. Write the adapter as a **draft, outside the discovered package** (see §5).
3. **Do not modify any existing file.** Not `_sax_common.py`, not `csax.py`, not `psax.py`, not existing tests. If you conclude an existing file must change for this to work, **do not change it** — implement around it and record the requested change under "Requested upstream changes" in the summary.
4. **No git state changes.** No `commit`, `push`, `checkout`, `stash`, `reset`, `clean`. Leave everything in the working tree. `git status` / `git diff` for inspection is fine.
5. **No package installation.** Use only `numpy`, `scipy`, `matplotlib` (all already used in this repo). If you want something else, don't — degrade gracefully and note it.
6. **Do not read, write, or touch** the SQLite database, any `.npy` memmap, any `.mat` file, or anything under `Results/`. Every dataset used in this work order is synthetic and generated in code.
7. **Everything must be headless and pure-numpy/scipy** — importable in a SLURM job with no display and no Panel/HoloViews. Use the matplotlib `Agg` backend explicitly in any plotting code.

---

## 1. Baseline first

Before writing any code:

1. Run the existing standalone test files (`python tests/test_<name>.py` for each `tests/test_*.py`; also try `python -m pytest tests -q` and note whether pytest is available).
2. Record which tests pass and which already fail, into `Working/Detection/sax/dsax_python/BASELINE.md`.

This matters: I need to be able to tell pre-existing failures apart from anything you introduce. At the end you will re-run the same set and diff against this baseline.

---

## 2. What to build

A new symbolic representation, **dSAX** (delta-SAX), that segments a series exactly like PAA does but encodes each segment by its **trend** rather than its mean, into an ordered alphabet whose middle symbol is "no meaningful change".

For a 3-symbol alphabet the symbols are `0 = DOWN`, `1 = SAME`, `2 = UP` (0-based, ascending, so `np.searchsorted(cutlines, delta, side="right")` produces them directly — same convention as `csax`/`psax`).

### Prior art — cite these in the module docstring

This is a known family of methods. Do not present it as novel; the module header must say what it reuses and what differs.

- **Esmael, Arnaout, Fruhwirth, Thonhauser (ICCSA 2012)** — "Multivariate Time Series Classification by Combining Trend-Based and Value-Based Approximations" (TVA): per-segment `U`/`D`/`S` trend symbols concatenated with SAX value symbols. This is the closest antecedent to the alphabet.
- **Sun, Li, Wang, Xia (Neurocomputing 2014)** — "An improvement of symbolic aggregate approximation distance measure for time series" (SAX-TD): defines a trend factor from the **starting and ending points** of each segment. This is the `endpoints` estimator below.
- **Malinowski, Guyet, Quiniou, Tavenard (IDA 2013)** — "1d-SAX": quantises per-segment mean **and** OLS slope. Strictly more informative than dSAX; dSAX is the slope channel alone, with a learned zero-anchored alphabet.
- **Agrawal, Psaila, Wimmers, Zaït (VLDB 1995)** — Shape Definition Language, the original up/down/stable shape alphabet.
- **Bountrogiannis, Tzagkarakis, Tsakalides (EUSIPCO 2020; IEEE TKDE 2022)** — the cSAX/pSAX work already vendored in this repo. dSAX reuses pSAX's Epanechnikov KDE + k-means++ + Lloyd-Max machinery unchanged, applied to the **delta** distribution instead of the PAA distribution.

The stated contribution is: applying a **data-adaptively quantised, zero-anchored trend alphabet** to fungal bio-electric recordings, to support a shared morphology vocabulary. Nothing more. Do not overclaim in comments or docs.

### Files to create

```
Working/Detection/sax/dsax_python/__init__.py
Working/Detection/sax/dsax_python/trend_estimators.py
Working/Detection/sax/dsax_python/dsax.py
Working/Detection/sax/dsax_python/adapter_draft.py          # NOT under Adapters/ — see §5
Working/Detection/sax/dsax_python/BASELINE.md               # from §1
Working/Detection/sax/dsax_python/IMPLEMENTATION_NOTES.md   # the summary, see §7
tests/test_dsax.py                                          # contract / invariant tests
tests/test_dsax_engineered.py                               # engineered-dataset tests
Experimentation/Detection experiments/run_dsax_validation.py
Experimentation/Detection experiments/dsax_validation/      # output dir (PNGs + metrics.json)
```

**House style:** match the existing files. Long module docstrings that explain *why* a decision was made and what would otherwise go wrong — read `Working/Detection/sax/csax_python/csax.py`, `Working/Detection/sax/psax_python/psax.py` and `Adapters/_sax_common.py` first and write in that voice. Comments should record reasoning, not restate the code. British spelling ("normalise", "quantisation") to match.

---

## 3. Algorithm specification

### 3.1 Signature

```python
def dsax(data, training_len, dim_ratio, alphabet_size=3,
         trend_estimator="ols_slope", threshold_mode="learned",
         endpoint_k=1, absolute_threshold=None, same_fraction=0.5,
         min_same_halfwidth=None, force_symmetric=True,
         normalize=True, return_details=False):
```

`data`, `training_len`, `dim_ratio`, `normalize`, `return_details` have **exactly** the same meaning and behaviour as in `psax()` — including the `data_nseg = floor(dim_ratio * data_len)` computation and the trimming to an exact multiple. Copy that arithmetic verbatim so `Adapters._sax_common.segment_plan()` round-trips against dSAX identically to how it does against pSAX. This is tested (§6.3).

`return_details=False` returns just the symbol array; `return_details=True` returns `(str_out, details)`. Same convention as csax/psax.

### 3.2 Normalisation — one step only, and deltas convert differently

pSAX/cSAX normalise twice (once outer, once inside `timeseries2symbol`'s single-window path) and their `details` code has to compose both. **dSAX does not call `timeseries2symbol` at all** — it computes deltas and quantises them itself with `np.searchsorted`. So there is exactly one normalisation step. Do not replicate the double-normalisation dance; it does not apply.

**Critical and easy to get wrong:** a delta is a *difference*, so the mean offset cancels. If the outer normalisation was `x_norm = (x - mu) / sigma`, then:

```
delta_raw = delta_norm * sigma          # scale only — NO + mu
paa_raw   = paa_norm   * sigma + mu     # offset applies to level quantities
```

Store `delta_scale = sigma` (or `None` when `normalize=False`) in `details` and use it for every delta-domain → raw conversion, including the cutlines. There is a test that asserts the mean does **not** appear in the delta conversion (§6.2). Guard the `sigma < 0.001` degenerate case the same way `psax` does (mean-subtract only, `delta_scale = 1.0`).

### 3.3 Trend estimators (`trend_estimators.py`)

For segment *i* covering samples `[i*sps, (i+1)*sps)` with `sps = data_len // data_nseg`, produce one scalar delta. **All estimators must be normalised to the same unit: "rise across the whole segment"**, so that a threshold means the same thing regardless of which estimator is selected, and so estimators are interchangeable without retuning. This is the single most important design constraint in this section.

- `"endpoints"` — `seg[-1] - seg[0]`. Faithful to SAX-TD.
- `"robust_endpoints"` — `median(seg[-k:]) - median(seg[:k])` with `k = endpoint_k`, clipped so `2k <= sps`. When `k == 1` this must be bit-identical to `"endpoints"` (test this).
- `"ols_slope"` — **default.** Least-squares slope against sample index, multiplied by `(sps - 1)` to express rise-across-segment. Vectorise this across all segments at once (reshape to `(n_seg, sps)` and use the closed-form slope); do not loop in Python over segments.
- `"theil_sen"` — `scipy.stats.theilslopes` slope × `(sps - 1)`. This is O(sps²) per segment; if `sps > 200`, subsample the segment to 200 evenly spaced points before fitting and note that in the docstring and in `details`.

Raise a clear `ValueError` if `sps < 2` (a slope is undefined) or `data_nseg < 2`.

### 3.4 Threshold modes

The cutlines are `alphabet_size - 1` ascending values in **delta space**.

**`"learned"` — the default.** Reuse pSAX's machinery unchanged, applied to the training-set deltas:

```python
from Working.Detection.sax.psax_python.kde      import epanechnikov_kde
from Working.Detection.sax.psax_python.kmeanspp import kmeanspp
from Working.Detection.sax.psax_python.lloydmax import lloydmax
```

Same call pattern as `psax()`, including the `npoints=min(training_len, 1000)` KDE grid cap (that cap exists to avoid a multi-GB matrix on long recordings — keep it).

Do **not** use cSAX's Mean-Shift here. The delta distribution of a roughly stationary signal is unimodal and centred near zero, so Mean-Shift would routinely find one cluster and take the fallback path. Say this in the docstring.

**Symmetrisation and zero-anchoring.** Delta has a privileged origin (zero = no change) that the PAA distribution does not. Unconstrained Lloyd-Max has no reason to respect it. When `force_symmetric=True` (default), symmetrise the learned ascending cutlines `c_0 … c_{k-2}` by

```
c'_j = (c_j - c_{k-2-j}) / 2
```

For `k = 3` this gives exactly `[-s, +s]` with `s = (c_1 - c_0)/2`; for even `k` the self-paired middle cutline lands exactly on 0, which is the correct behaviour (an even alphabet has no SAME bin, just a boundary at zero). This makes zero-anchoring automatic and needs no separate parameter.

When `force_symmetric=False`, keep raw Lloyd-Max cutlines and record in `details["zero_symbol"]` which symbol index contains delta = 0, so the asymmetry is visible rather than silent. Asymmetric cutlines are scientifically interesting here (fast-rise/slow-decay morphologies should produce a skewed delta distribution) — the point is that it must be *reported*, not accidental.

**`min_same_halfwidth`** (default `None`, delta units in the *normalised* domain if `normalize=True`, raw otherwise): if given and the SAME band is narrower than this, widen it to this half-width. This exists so a noise-floor estimate can be injected. Also provide, in the same module, a standalone helper that estimates one:

```python
def surrogate_same_halfwidth(data, samples_per_symbol, trend_estimator="ols_slope",
                             n_surrogates=50, alpha=0.95, random_state=None):
    """Half-width of the delta distribution under a no-trend null, from
    phase-randomised surrogates. Not called by dsax() — dsax() must stay
    deterministic; pass the result in as min_same_halfwidth if wanted."""
```

Implement it with phase randomisation (FFT, randomise phases, preserve magnitude spectrum), return the `alpha` quantile of `|delta|` pooled over surrogates. Do not wire it into `dsax()` by default.

**`"absolute"`** — `absolute_threshold` given in **raw signal units of rise per segment**. Valid for `alphabet_size == 3` only; raise otherwise. Cutlines are `[-absolute_threshold, +absolute_threshold]`, converted into the working domain by dividing by `delta_scale` when `normalize=True`. This mode is fully deterministic and is what the engineered-dataset tests use for exact expected strings.

**`"quantile"`** — for `alphabet_size == 3`, place cutlines at the `±` quantiles of the training deltas such that the SAME bin holds `same_fraction` of segments. For `alphabet_size > 3`, place cutlines at equiprobable quantiles of the training delta distribution (the SAX equiprobable idea, applied to deltas). Apply symmetrisation afterwards if `force_symmetric`.

### 3.5 Quantisation and output

```python
str_out = np.searchsorted(cutlines, deltas, side="right")
```

`cutlines` must be strictly ascending; if symmetrisation or a degenerate distribution collapses two cutlines onto each other, nudge them apart by a documented epsilon and set `details["cutlines_degenerate"] = True`. A constant input signal must **not** raise — it must produce an all-SAME string with that flag set. (`csax` has an analogous fallback path; mirror the spirit, and mirror `tests/test_sax_details.py::test_csax_fallback_path_is_flagged_and_still_reproducible`.)

### 3.6 `details` dict contract

Mirror pSAX's keys where they mean the same thing, so shared consumers keep working, and add the trend-specific ones:

```
samples_per_symbol, n_symbols, data_len_trimmed, n_trimmed   # identical semantics to psax
deltas, deltas_raw                                            # the quantised quantity
cutlines, cutlines_raw                                        # delta space
representatives, representatives_raw                          # Lloyd-Max codewords (learned mode);
                                                              # bin midpoints/medians otherwise
alphabet_size
paa, paa_raw                                                  # segment means, computed via ts_paa —
                                                              # unused by dSAX itself, included so a
                                                              # future TVA-style value+trend combination
                                                              # is free and so level context is available
norm_mean, norm_std                                           # signal-domain constants (may be None)
delta_scale                                                   # delta-domain scale ONLY (may be None)
trend_estimator, threshold_mode, force_symmetric
segment_starts, segment_ends                                  # sample indices, for plotting/alignment
seg_slope                                                     # per-segment fitted slope (per sample)
same_fraction_observed, delta_mean, delta_mean_raw, zero_symbol
cutlines_degenerate, theil_sen_subsampled
```

Also provide, in `dsax.py`:

```python
SYMBOL_NAMES = {3: ("DOWN", "SAME", "UP"), 5: ("DOWN2","DOWN1","SAME","UP1","UP2")}
def dsax_letters(symbols, alphabet_size=3): -> str   # e.g. "UUSDDD" for k=3, using D/S/U
```

`dsax_letters` is the payoff: it makes the encoding regex-searchable, which is how the tag vocabulary (sharkfin, rollinghill, …) becomes a detector. For `k = 3` use `D`/`S`/`U`. For other `k`, use the existing `Adapters._sax_common._letter` convention (a, b, c, …) — but **do not import from `Adapters/`**; `Working/` must not depend on `Adapters/`. Duplicate the four-line helper with a comment saying why, exactly as `_sax_common._letter` itself does.

---

## 4. Plotting (headless, no UI)

In `dsax.py`, add `plot_trend_encoding(x, t, symbols, details, path)` returning a matplotlib Figure and saving to `path`, with `matplotlib.use("Agg")` set before pyplot import.

**Do not reuse `Adapters._sax_common.plot_encoding_matplotlib`.** It draws `cutlines_raw` as horizontal amplitude bands over `paa_raw`; dSAX's cutlines live in delta space, so that figure would be physically meaningless. The correct figure is a different one — four stacked panels:

1. Signal with each segment's fitted slope drawn as a short line over it.
2. Stem/step plot of `deltas_raw` per segment with the cutlines as horizontal lines.
3. Histogram of `deltas_raw` with the cutlines marked and the SAME band shaded — this is the plot that shows whether the threshold is sensible.
4. Symbol strip, coloured, with `D`/`S`/`U` letters when `n_symbols <= 120` (match the existing letter-threshold rule).

---

## 5. Draft adapter — deliberately not discoverable

Write `Working/Detection/sax/dsax_python/adapter_draft.py` containing the `AdapterSpec` exactly as it would look in `Adapters/detection_sax_dsax.py` — same structure as `Adapters/detection_sax_psax.py`, reusing `segment_plan`, `recommend_sax_params`, `derive_sax_rows`, and pointing `plot` at `plot_trend_encoding`.

**But:** it must not call `register()` at import time, and it must not live under `Adapters/`. Guard the registration behind a function:

```python
def register_dsax_adapter():
    """Not called at import. Promote by moving this file to
    Adapters/detection_sax_dsax.py and restoring module-level register(SPEC)
    — see IMPLEMENTATION_NOTES.md §Promotion."""
```

Verify by asserting in a test that `Adapters.registry.discover_adapters()` does **not** contain `detection.sax_dsax`. Then separately verify the spec object itself is well-formed (`validate_params` round-trips, `output_kind == "encoding"`, `recommend`/`derive` callable) by importing it directly.

---

## 6. Tests — the actual deliverable

Both test files must follow the existing convention in `tests/test_sax_details.py`: repo-root `sys.path` bootstrap, plain `assert`, module-level `_run_all()` runner printing `[PASS]`/`[FAIL]` and exiting non-zero on failure, and runnable as `python tests/test_dsax.py`. They must also work under pytest if it is installed. Seed every RNG explicitly.

### 6.1 Engineered datasets — `tests/test_dsax_engineered.py`

Each one has a deterministic expected outcome. Use `normalize=False, threshold_mode="absolute"` where an exact string is asserted, so the expectation is unambiguous.

| # | Dataset | Expectation |
|---|---------|-------------|
| 1 | Linear ramp up, 1000 samples, `sps=100`, `absolute_threshold` well below the per-segment rise | exactly `"UUUUUUUUUU"` |
| 2 | Linear ramp down, same | exactly `"DDDDDDDDDD"` |
| 3 | Constant 5.0 | all `SAME`; no exception; `cutlines_degenerate` handled; also passes with `threshold_mode="learned"` |
| 4 | Triangle wave, 100 up / 100 down × 5, `sps=100` | exactly `"UDUDUDUDUD"` |
| 5 | Flat–step–flat, step inside one segment | exactly one non-`SAME` symbol, and it is `UP`, and it is at the expected index |
| 6 | Staircase with per-segment rises `{-2,-1,0,+1,+2}` × unit, `alphabet_size=5` | symbols exactly `[0,1,2,3,4]` in order |
| 7 | Synthetic **sharkfin**: 1 segment fast rise then 5 segments exponential decay | string matches `^U D{3,}$` after stripping `S` — assert with `re.fullmatch` |
| 8 | White Gaussian noise, no trend, `threshold_mode="learned"`, `force_symmetric=True` | `abs(UP_count - DOWN_count) / n < 0.1`; `abs(delta_mean) < tol`; cutlines satisfy `cutlines ≈ -cutlines[::-1]`; `searchsorted(cutlines, 0.0)` is the middle index |
| 9 | Noise + linear drift, no detrending | `UP` fraction > 0.8 (demonstrates the drift-dominance failure mode); then repeat on the same signal with the fitted line subtracted and assert balance is restored |
| 10 | **Scale invariance**: signal `x` vs `1000 * x`, `normalize=True`, `threshold_mode="learned"` | identical symbol strings |
| 11 | **Sample-rate invariance**: the same underlying function sampled at `fs` and `2*fs`, with matched *seconds*-per-symbol | ≥ 95 % symbol agreement |
| 12 | **Estimator agreement**: noiseless ramps and triangle | all four estimators produce identical strings; `robust_endpoints` with `k=1` is bit-identical to `endpoints` |
| 13 | **Estimator robustness**: noisy ramp, 200 seeded repeats | symbol-flip rate for `ols_slope` and `theil_sen` is strictly lower than for `endpoints`. If this fails, do **not** delete the test — investigate, and if the finding is real, record it prominently in the summary as a result that contradicts the design rationale |

### 6.2 Contract / invariant tests — `tests/test_dsax.py`

- `return_details=False` is byte-identical to `return_details=True`'s first element (mirror the existing csax/psax tests, reseeding identically).
- **The important one**, mirroring `test_csax_requantising_paa_against_cutlines_reproduces_str_out`: `np.searchsorted(details["cutlines"], details["deltas"], side="right")` reproduces `str_out` exactly — proving `deltas`/`cutlines` are what actually produced the output, not a plausible reconstruction.
- Cutlines strictly ascending, length `alphabet_size - 1`.
- `len(deltas) == n_symbols == len(str_out)`; symbol indices within `[0, alphabet_size)`.
- `data_len_trimmed + n_trimmed == len(data)`; `samples_per_symbol == data_len_trimmed // n_symbols` (mirror `test_csax_samples_dropped_accounting`, using a length that does not divide evenly).
- **Delta raw round-trip**: `deltas_raw == deltas * delta_scale` exactly, and `norm_mean` does **not** appear — assert explicitly that `deltas_raw != deltas * delta_scale + norm_mean` when `norm_mean` is non-zero.
- `paa_raw` round-trips *with* the mean (`paa_raw == paa * norm_std + norm_mean`), confirming the two conversion rules are genuinely different.
- `normalize=False` → `norm_mean`/`norm_std`/`delta_scale` are `None` and raw arrays are identical to working arrays.
- Determinism: same seed → identical output across repeated calls.
- `ValueError` on `sps < 2`, on `n_symbols < 2`, on `absolute` mode with `alphabet_size != 3`, and on an unknown `trend_estimator` / `threshold_mode`.

### 6.3 Integration with existing shared code (read-only use of it)

- `Adapters._sax_common.segment_plan(...)` → passing `plan["dim_ratio_for_call"]` into `dsax()` yields exactly `plan["n_symbols"]` symbols and `plan["achieved_sps"]` samples per symbol, for a spread of `n`, `fs` and all four `segment_mode` values including ones that do not divide evenly.
- `Adapters._sax_common.encoding_diagnostics(symbols, 3)` returns a `1.585`-bit ceiling; an all-SAME string gives 0 bits (which trips the existing `< 0.7` warn path — assert `diagnostic_rows` marks it `"warn"`); a balanced noise string gives > 1.3 bits.
- `discover_adapters()` does **not** register `detection.sax_dsax` (§5).

---

## 7. Validation script and summary

`Experimentation/Detection experiments/run_dsax_validation.py` — runs headlessly, no arguments, writes to `Experimentation/Detection experiments/dsax_validation/`:

- One PNG per engineered dataset via `plot_trend_encoding`, so I can eyeball them.
- `metrics.json` containing, at minimum:
  - **Offset sensitivity**: shift each engineered signal by `1 … sps-1` samples, re-encode, record mean symbol agreement against the unshifted encoding. Report per dataset and overall. This characterises the known weakness — it is a *measurement*, not a pass/fail, but assert overall agreement > 0.5 so a catastrophic bug is still caught.
  - **Estimator comparison**: symbol-flip rate per estimator on noisy data (the numbers behind test 13).
  - **SAME fraction** produced by learned cutlines on noise, and the surrogate-derived half-width from `surrogate_same_halfwidth` for comparison — I want to see how far MSE-optimal Lloyd-Max sits from a noise-floor-justified threshold.
  - Occupancy entropy and self-transition rate for each dataset.
- A plain-text console summary at the end.

`Working/Detection/sax/dsax_python/IMPLEMENTATION_NOTES.md` — the document I read when I get back. It must contain:

1. **What was built** — one paragraph, file by file.
2. **Every judgement call, with justification.** This is the most important section. Anything this brief left open, anything you decided differently from what it says, any epsilon or tolerance you picked and why.
3. **Deviations from the brief** — called out explicitly and separately, not buried.
4. **Requested upstream changes** — anything you wanted to change in an existing file but didn't (per §0.3), with the exact diff you would have applied.
5. **Test results table** — every test, pass/fail, and the diff against `BASELINE.md` for the pre-existing suite. State plainly whether anything regressed.
6. **The measured numbers** from `metrics.json`, with a sentence of interpretation each — particularly the offset sensitivity and the Lloyd-Max-vs-noise-floor comparison.
7. **Known limitations** — including the loss of SAX's MINDIST lower-bounding guarantee, and offset sensitivity.
8. **Promotion checklist** — the exact steps to wire dSAX into the UI later: move `adapter_draft.py` to `Adapters/detection_sax_dsax.py`, restore module-level `register(SPEC)`, and the specific reason the shared encoding view cannot render delta-space cutlines without a change (so I know what UI work is actually outstanding).

---

## 8. Definition of done

- Every test in `tests/test_dsax.py` and `tests/test_dsax_engineered.py` passes.
- The pre-existing test suite shows **no regressions** against `BASELINE.md`.
- `run_dsax_validation.py` completes and has written the PNGs and `metrics.json`.
- `python -c "from Adapters.registry import discover_adapters; print([s.name for s in discover_adapters()])"` runs clean and does not list `detection.sax_dsax`.
- No file under `UI/` has been touched (`git status` proves it — include the output in the summary).
- `IMPLEMENTATION_NOTES.md` is complete.

**Do not leave failing tests.** Iterate until they pass. If a test cannot pass because its *expectation* was wrong rather than the code, fix the expectation — and flag that prominently in §7.3, since a silently weakened test is worse than a failing one.

If you run short on time, cut in this order and say so in the summary: `theil_sen` estimator → `quantile` threshold mode → the 5-symbol alphabet path → the validation PNGs. Never cut: the core `learned`/`absolute` paths, the requantisation invariant test, the engineered-dataset tests 1–10, or the summary document.
