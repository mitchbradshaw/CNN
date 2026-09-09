# drop_motifs — the detection process and the figures it produces

Reference for `Pipelines/drop_motifs/`. Written to be read before wiring any of this into the
Pipeline GUI: it names, for every stage, the function that does the work, the parameters that
control it, and the artefact it produces.

Scope: **drop_motifs9** (sliding-window detection on Fig2A) and **refine9** (the v2 corrections).
Earlier versions 5–8 are described in their own `Plots/drop_motifs*/PROVENANCE.md`.

---

## 1. The detection chain

Everything below `Working/Detection/drop_motifs/` is UI-free and importable from a worker.
`Pipelines/drop_motifs/` orchestrates it and owns all the matplotlib.

```
channel (.npy, volts)
  │
  ├─ passes9.window_bounds ............ 50 s windows, 50% overlap → 47 windows / channel
  │
  └─ per window:  passes7.detect_multiscale(inverted=False)
        │
        ├─ STEP 2  detrend .................. detect.detrend, rolling median
        │                                     window = params.detrend_window_s (auto-derived)
        ├─ STEP 3  symbolic encoding ........ detect5.stage_letters
        │            dSAX at k=3 ............ Working/Detection/sax/dsax_python/dsax.py
        │            + MAD noise-floor split  → d D S U u
        ├─ STEP 4  five-stage drop rules .... detect5.detect_drops5
        │            run per pass: base / fine / sens / micro
        └─ within-window merge .............. passes6.deduplicate   ← SEE THE BUG IN §4
  │
  ├─ cross-window merge ................. passes9.deduplicate_across_windows
  ├─ scale bands + size split ........... passes6.scale_bands, passes8.size_split
  └─ store .............................. motifs5.write_store
```

### The four passes

All four are DROP passes; `inverted` is off in drop_motifs9, so no rise pass runs.

| pass | what it is | why it exists |
|---|---|---|
| `base` | the derived scale, unchanged since drop_motifs5 | the reference; every validated count reproduces |
| `fine` | the detector at the best of a ladder of narrower widths | events a single derived scale frames past |
| `sens` | the slope gate relaxed as far as window purity allows | gentle rather than sharp falls |
| `micro` | relaxed depth/dominance/rise gates, scanned by segment | short events the other three miss |

### Why the window slides

Every pass derives its scale from the signal handed to it, via autocorrelation. Given a whole
1200 s channel that is **one** scale for the whole channel. Given 50 s at a time, the scale is that
of whatever is locally dominant. Measured on CH2: **101 motifs whole-channel → 391 sliding**, and
`sens` goes from 0 kept to 6.

The per-window adaptation is real and visible in the case studies:

| | CH2 win33 | CH4 win05 |
|---|---|---|
| detrend window (auto) | 7 s | 2.92 s |
| slope-noise σ (MAD) | 0.0096 mV/s | 0.0763 mV/s |
| passes that fired | base, fine | base, fine, sens |

### Not saving the same drop twice

Two mechanisms, and **both are needed**:

- `passes9.deduplicate_across_windows` — with 50% overlap every interior event is in two windows.
  Two detections whose absolute onsets are within `DEDUP_ONSET_FRAC × fall × fs` are one drop, and
  **the best-framed copy wins**: candidates are ranked by `window_centre_frac`, so an event caught
  at a window edge (one-sided detrend baseline, possibly truncated snippet) loses to the same event
  caught mid-window.
- `refine9.dedup_same_drop` — within a window. See §4; this is the one that was missing.

---

## 2. Units, and the one conversion that matters

| quantity | unit | where |
|---|---|---|
| channel `.npy` on disk | **volts** | `DATA/derived/channels/<stem>/CH<n>.npy` |
| everything in the store | **millivolts** | `motifs5.rows_and_arrays` multiplies by 1000 |
| slopes | **mV per second** | `gradients.fall_gradients` multiplies by `fs` |
| `t_s` in a snippet | **absolute seconds in the recording** | not time-from-onset — a frequent trap |
| `onset_idx`, `trough_idx`, `snippet_*_idx` | **absolute sample index in the channel** | `span_offset` already added |

`t_s` and `onset_idx` being absolute is the single most common source of an off-by-a-window plotting
bug. To draw time-from-onset: `t_rel = t_s - onset_idx / fs`.

---

## 3. The figures

### Pooled (whole store)

| file | function | what it shows |
|---|---|---|
| `ALL_dendrogram.png` | `clusterfigs9.plot_dendrogram` | truncated Ward tree on a ranked axis, plus **two rows** of family overlays — the coarse cut and a finer one (6–10 families) |
| `ALL_families.png` | `clusterfigs9.plot_family_atlas` | every motif by family, **both cuts**, with a channel-composition bar per panel |
| `ALL_rose.png` | `clusterfigs9.plot_rose` | 4 panels: rose by channel, rose by drop height, height-vs-angle, and **the control** |

### Case study (one window)

| file | function |
|---|---|
| `*_01_pipeline.png` | `casestudy9.plot_pipeline` — raw → detrend → dSAX staging → slope cut → detections |
| `*_02_clustering.png` | `casestudy9.plot_clustering` — motifs, feature vectors, tree, distance matrix |
| `*_03_fall_angle.png` | `casestudy9.plot_fall_angle` — onset / trough / steepest sample, and where depth comes from |
| `*_04_dendrogram.png`, `*_05_rose.png` | the pooled figures restricted to one window |

### Three things a UI must not get wrong

1. **The tree's distance is not `cluster.distance_matrix`.** `cluster.build_linkage` runs Ward over
   the *feature* matrix (each motif resampled to 200 points, z-normalised), so the distance it
   minimises is plain Euclidean between those vectors. `cluster.distance_matrix` is a separate
   utility with a different (scale-invariant, length-normalised) metric and did **not** produce any
   shipped dendrogram.
2. **Clustering is scale-invariant.** A family is a *shape*; its medoid is a shape representative,
   not an amplitude one. A 0.014 mV motif and a 0.39 mV motif can be siblings.
3. **A dynamic map that throws renders as a blank pane, not an error** (`CLAUDE.md`). Any Panel port
   of these needs the headless construction test *and* `pytest -m ui`.

---

## 4. What refine9 corrects, and why

`refine9` is a **post-processing pass over a finished store**. It changes no detection, so
drop_motifs9 remains reproducible and refine9's effect is exactly the difference between two stores.
Run: `python Pipelines/drop_motifs/run_refine9.py`.

### 4.1 The duplicate-detection bug — a real defect, and it reached the store

`passes6.deduplicate` computes

```python
tolerance = onset_frac * max(float(fall_s), float(kept_fall))
```

That is a duration in **seconds** compared against a difference in **sample indices**. `passes8`
found and fixed exactly this, but the fix lives in `passes8.deduplicate`, and `passes9` only calls
that for the *cross-window* merge — **within** a window the unfixed `passes6` rule still runs.

Every recording drop_motifs5–8 was validated on is 1 Hz, where the two quantities are numerically
equal and the bug is invisible. Fig2A is 10 Hz, so the tolerance comes out **ten times too small**.

Worked example, CH1 window 36: `base` finds onset 9063 → trough 9069, `fine` finds 9064 → 9069.
Tolerance as computed is `0.5 × 0.6 = 0.3` "samples"; the onsets differ by 1, so both survive.
Multiplied by `fs` it is 3 samples and they merge.

Measured on the shipped drop_motifs9 store: **61 pairs share a channel *and* a trough sample**, and
79 more sit within two samples. `refine9.dedup_same_drop` restores `fs` and adds two tests the onset
rule cannot make — **same trough = same drop**, and **containment** — which catch the nested case
(`base` 9161→9175 against `fine` 9163→9165).

### 4.2 Where the fall starts and ends

- **Onset (the "peak")** — walk back from the steepest sample while the trace is still descending;
  stop at the first sample that is not. That is the local maximum the fall departs from. The
  detector's own onset is wherever its slope gate first fired, which on a rounded shoulder is
  part-way down.
- **Trough (the "end of slope")** — scan forward from the steepest sample for the first run of
  `RISE_RUN_SAMPLES` (3) consecutive samples whose gradient is at least `RISE_SIGMA` (0.5) × the
  snippet's own slope noise. The fall ends where the recovery begins.

Both are bounded; if either fails the event keeps the detector's mark and the refusal is counted.
Measured: 1249 onsets moved, 952 troughs moved, 33 refused.

### 4.3 A motif is one drop, not a train

After the marks move, the snippet is **re-cut** to `SNIPPET_PRE_MULT` (1.2) falls before the onset
and `SNIPPET_POST_MULT` (1.8) after the trough. This only ever shrinks — the cut is clipped to what
was stored, so no sample is invented. This is what stops family overlays showing a *sequence* of
rounded humps where they should show one event.

### 4.4 The noise floor

`depth_gate` drops any event whose refined depth is ≤ `MIN_DROP_DEPTH_MV` (0.1 mV, the operator's
stated instrument floor).

**A low-pass filter was considered and deliberately not used.** It would suppress the same humps,
but it would also change every gradient the rose reports, and the angle measurement is the one
quantity in this pipeline with no independent check on it. The depth gate rejects the same events
without touching a sample of signal, and keeps preprocessing at one step — a detrend — which is
worth protecting.

### Net effect

```
1736 in  →  131 duplicates  →  547 below floor  →  1058 out
```

---

## 5. Why the angle uses the STEEPEST slope, not the mean

This is a reporting question, so here is the argument in full.

`fall_gradients` measures three quantities per event:

| | definition | what it answers |
|---|---|---|
| `onset_slope_mv_s` | gradient at the onset sample | how abruptly it departs |
| `mean_slope_mv_s` | (trough − onset) / duration — the **chord** | the average rate of the excursion |
| `max_slope_mv_s` | the steepest single sample between them — the **tangent** | how fast it fell at its fastest |

The rose uses `max_slope`. Four reasons, in the order they should be argued:

1. **The mean slope is not independent of the depth axis.** `mean_slope ≡ depth / duration`
   *exactly*. Plotting depth against an angle derived from the mean is plotting depth against a
   function of depth — the correlation is guaranteed and means nothing. `max_slope` is a separate
   measurement of the trace and can, in principle, disagree; that it largely does not is a finding
   rather than an identity. (See the control panel: even with `max_slope` the relationship is mostly
   arithmetic, which is a claim you can only make *because* the two are not definitionally locked.)
2. **It is the physiologically interesting instant.** If a drop reflects a depolarisation event, the
   quantity with a mechanism behind it is the maximum rate of change, not the average over an
   interval whose end is set by a recovery threshold.
3. **It is robust to where the trough is placed.** The mean slope moves whenever the trough
   definition changes — and §4.2 has just changed it. `max_slope` depends only on the interval
   containing the steepest sample, so the rose is not hostage to the trough rule.
4. **The ratio of the two is itself informative.** `peakedness = max/mean` is 1.0 for a perfectly
   linear fall and larger for a front-loaded one. Reporting `max` on the rose and `peakedness`
   alongside gives both readings; reporting `mean` alone throws the shape away.

**The honest counter-argument, which should also be in the report:** `max_slope` is a single-sample
statistic and is therefore the noisiest of the three, and at 10 Hz a "sample" is 0.1 s. On a fall of
5 samples the steepest sample is one of five, and the estimate is coarse. `mean_slope` is smoother.
The defensible position is that `max_slope` measures the right thing imprecisely, `mean_slope`
measures the wrong thing precisely, and the figure states which it used and what the reference is.

---

## 5b. Querying the store — the trap v2 fell into

**Select motifs by SAMPLE RANGE, not by `window_index`.** A drop lying in two overlapping windows is
stored once, tagged with whichever window won the best-framed rule — often the *neighbour*. Filtering
`window_index == N` therefore silently hides drops inside window N's time range. This undercounted
every case-study window (CH4: 11 vs 21; CH2: 1 vs 2). Any UI panel showing "the motifs in this
window" must use the range.

Related, and confirmed by measurement over the 1058 refined motifs: **overlapping `onset→trough`
spans, 1 pair; overlapping `snippet` spans, 261 pairs.** Snippets carry `onset − 1.2 falls` to
`trough + 1.8 falls` of context, so neighbouring drops share context without the drops overlapping.
Overlapping shaded spans in a figure are context, not double-counting.

## 6. Known limitations — the drop_motifs10 list

1. **Missed drops are not fixed and cannot be fixed here.** `refine9` post-processes existing
   detections; it can merge, move and reject, but never add. The operator's example on CH1 (a drop
   between M2 and M3) measures **0.172 mV** — comfortably *above* the 0.1 mV floor — so it is a
   genuine sensitivity gap in `detect5`, not something the gate explains away. The more diagnostic
   case is **CH4 win05's second visible drop**, where the dSAX strip clearly reaches the `d`
   threshold but no detection results: the encoding fires and the five-stage window rules reject the
   candidate, which points at `detect5.window_bounds` / `significant_rises` rather than at the slope
   gate.
2. **The depth floor is global, and the channels are not comparable.** CH2's median raw drop depth
   is **0.029 mV** against CH1's 0.204 and CH3's 0.267; 77% of CH2's motifs fall under 0.1 mV, so the
   floor removes 391 → 93 there while leaving CH1 at 85%. Either CH2 has genuinely smaller signals
   (different electrode contact) and wants a **per-channel** floor derived from its own noise, or
   CH2 is mostly sub-noise and should be reported as such. This is a measurement decision, not a
   tuning one.
3. **Fall durations are quantised.** At 10 Hz a 0.5 s fall is 5 samples and durations step in 0.1 s.
   The near-constant duration that drives the whole height-vs-slope result is a few samples wide.
4. **The cophenetic correlation falls to 0.681 after refinement** (from 0.910), below the 0.70 floor
   the figures warn at. Fewer, cleaner motifs cluster *less* crisply — worth understanding before
   the tree is quoted.
5. **Nothing is validated against a human count.** Fig2A has no catalogue row.
6. `passes6.deduplicate` still carries the seconds/samples bug for any future non-1 Hz caller that
   uses `passes7` directly. Fixing it at source would change drop_motifs5–8 output, so it was left
   alone and corrected downstream; **drop_motifs10 should fix it at source and re-baseline.**

7. **The stored snippet arrays do not always span what `snippet_start_idx` / `snippet_end_idx`
   claim** — found 2026-09-02 while building `nulls_v1`. Measured: **30 of the 1058 refined rows and
   208 of the 1736 raw rows** have `len(detrended_mv) != snippet_end_idx - snippet_start_idx`.
   Example: `id900_r466_base_3562` carries indices 3508→3625 (117 samples) against a stored array of
   16.

   This is not cosmetic, because `clusterfigs7._waveform_of` converts an absolute onset to a local
   index by subtracting `snippet_start_idx` and then **clips to the array**. Where the array is
   shorter than the indices claim, the clip lands the onset on the last stored sample and the
   returned "fall" is one sample long; `cluster.feature_matrix` resamples that constant to 200 points
   and z-normalises it to **all zeros**. **22 of the 1058 refined motifs enter the shipped Ward tree
   as identical zero vectors at the origin of feature space.**

   Consequence for a number already in circulation: the shipped cophenetic r of **0.681** falls to
   **0.408** on the same store once those 22 rows are removed. The 22 sit on top of each other at
   distance zero, and a block of identical points inflates the cophenetic correlation without
   describing any structure. `nulls_v1` drops zero-variance feature rows on both the real and the
   surrogate side and reports the count; drop_motifs10 should fix the store so the indices and the
   arrays agree.

---

## 7. Commands

```bash
# detection
python Pipelines/drop_motifs/run_drop9_report.py             # → Plots/drop_motifs9_fig2a/
python Pipelines/drop_motifs/run_refine9.py                  # → .../refined_v2/

# explanation
python Pipelines/drop_motifs/run_casestudy9.py               # → .../example_case_study/
python Pipelines/drop_motifs/run_casestudy9_v2.py            # → .../example_case_studies_v2/

# interactive
python Pipelines/drop_motifs/scan_fig2a_motifs.py --store Plots/drop_motifs9_fig2a/refined_v2/motifs
```

Useful flags: `--min-depth-mv` (the floor), `--fine-families` (the second cut),
`--window-s` / `--overlap` (the sliding window), `--no-gate` / `--no-dedup` / `--no-refine`
(isolate one correction at a time).
