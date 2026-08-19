# Spike-drop motifs — summary

## 1. What now works

`python Pipelines/drop_motifs/run_drop_report.py --export-all` detects spike-drops on
Mushroom_260720 (id 385, whole recording) and M2_aug CH00 (id 1, the 336–346 h span read from
annotation 11266 at run time), writes a per-recording event table + snippet archive + manifest under
`DATA/derived/drop_motifs/`, pools the 42 events into one Ward dendrogram, and writes ten figures
into `Plots/drop_motifs/` — including the embedded-thumbnail hero dendrogram §6.2 asked for. A
second entry point, `--replot-from`, replays the store into figures while touching neither a
recording nor the database, and a test asserts that by deleting the source array before reloading.
Detection is deterministic and consumes no RNG. On M2_aug the detector returns 16 drops from 16
rises with zero rejections, against a human annotation that independently records "16 cycles".

## 2. DECISIONS

Ordered roughly as §3–§6 raise them. Where a decision departs from the work order's recommendation
it says so explicitly.

### 2.1 Annotation span for M2_aug — took the full 336–346 h

**Chose:** annotation 11266's full span, read from the database at run time rather than hardcoded.
**Alternative:** the narrower 336.8–344.4 h the operator quoted informally.
**Why:** the annotation is the record; the wider span costs nothing because its quiet head and tail
simply produce no events (first onset 337.01 h, last 343.94 h — the crop would have made no
difference to the event set, which is worth knowing). Reading it at run time makes the crop
traceable to a human verdict instead of a number in a script, and the run prints the annotation note
so a mismatch is visible.
**Reverse:** `RECORDING_PRESETS[1]["annotation_id"] = None` falls back to the hardcoded
`"span": (336.0, 346.0)`, or edit that tuple.

### 2.2 dSAX `threshold_mode="quantile"`, NOT the recommended `learned` — the big one

**Chose:** quantile mode with an explicit target SAME occupancy per recording.
**Alternative:** `learned` (Lloyd-Max), which §2.3 of the work order recommended.
**Why:** `learned` **finds zero events on Mushroom_260720**, at every detrend window (60/120/180 s)
and segment length (3/4/6/10 s) tried. Lloyd-Max cutlines are MSE-optimal against the observed delta
distribution, which on a spiking recording is dominated by the rare enormous drop deltas, so the
optimal SAME band swallows 98–99% of segments — including the whole rise. The letters around a real
icicle read `SSSSSSSSDSSSSSS` under `learned` and `SSSUDDUDDU` under `quantile`: the fall is
classified either way, but the rise only exists in the second, and "the first fall after a rise"
cannot match anything without it. Bonus: quantile mode touches no RNG (dSAX's own Determinism note),
so reproducibility no longer depends on seeding discipline.
**Reverse:** `THRESHOLD_MODE` in `Working/Detection/drop_motifs/detect.py`. Expect zero Mushroom
events if you do.

### 2.3 Detrend windows — 180 s (Mushroom) / 1800 s (M2_aug), not harmonised

**Chose:** per-recording, differing 10×.
**Alternative:** one shared window; the work order suggested "a few minutes" as a starting point.
**Why:** measured. On M2_aug a 60 s window leaves 7.1 mV of a 62.8 mV excursion — it removes the
spike along with the drift — while 1800 s leaves 40 mV with the rise and fall both intact. On
Mushroom the events are ~50–100 s end to end, so 180 s is the largest value that still flattens the
slow wander visible around 2.4–2.6 h without touching the icicles; at 30 s the residual is already
13.8 of 16.5 mV, so the recording is insensitive here and 180 s is a comfortable middle.
Harmonising would mean choosing one recording's time scale for both.
**Reverse:** `--detrend-window-s`, or the presets.

### 2.4 Segment durations — 2 s (Mushroom) / 120 s (M2_aug)

**Chose:** per-recording, differing 60×.
**Why:** the segment length is bounded above by the **rise**, not the fall. On Mushroom the rise
before a drop is *one to two samples* — a +0.64 mV overshoot immediately before a 12 mV fall. Recall
against a hand-built icicle reference by segment length, at otherwise-shipped parameters: 2 s →
0.92–0.96, 3 s → 0.80, 4 s → 0.76, 6 s → 0.60. On M2_aug 120 s gives ~8 segments across a 15-minute
rise and puts the fall in its own one or two.
**Reverse:** `--segment-seconds`.

### 2.5 SAME occupancy — 0.5 (Mushroom) / 0.7 (M2_aug)

**Chose:** lower on Mushroom.
**Why:** the one-sample overshoot needs a narrow SAME band to register as UP at all. The cost is
950 candidate rises on Mushroom against 16 on M2_aug, 88% of which are baseline fluctuation — those
are then declined by the slope threshold, which is the filter doing the real work.
**Reverse:** `--same-fraction`.

### 2.6 Lone `S` between two `U` runs — merged on Mushroom, not on M2_aug

**Chose:** `merge_gap_segments = 1` on Mushroom, `0` (the bare regex, and the work order's default)
on M2_aug. A `D` is never bridged at any setting.
**Why:** at 2 s segments the Mushroom overshoot is often `U S U` — one rise with a sampling notch in
it, not two rises. Merging lifts recall from 0.92 to 0.96 there. M2_aug's rises are 8 segments long
and need no help.
**Reverse:** `--merge-gap-segments`.

### 2.7 Negative-slope threshold — a MAD noise floor, NOT dSAX's DOWN cutline

**Chose:** `slope_threshold = -slope_sigma × robust_sigma(d/dt x_detrended)`, `slope_sigma = 6`.
**Alternative:** `details["cutlines_raw"][0] / samples_per_symbol`, which §3.4 recommended in order
to avoid a second free parameter.
**Why:** that recommendation is sound for `learned` mode, where the cutline is a magnitude. Under
`quantile` mode (2.2) the cutline is an *occupancy quantile* and carries no information about how
steep "steep" is — at the shipped settings it is ±0.008 mV per segment on Mushroom, three orders of
magnitude below the real drop's slope. It cannot serve. The MAD estimate replaces it and reads
directly as a claim: "the fall is at least 6× steeper than noise alone produces". MAD rather than
`np.std` is essential and is tested: on this data the huge drops *are* the outliers, so an sd-based
scale is set by the very events being looked for.
**Reverse:** `--slope-sigma`; the estimator is `robust_sigma` in `detect.py`.

### 2.8 Lookahead bound — 3× the rise's own duration

**Chose:** the work order's own recommendation, unchanged.
**Why:** bounded rather than unbounded so a rise at the end of a span cannot walk off the data;
proportional to the rise so it means the same thing at both time scales. 841 of Mushroom's 950
candidates are declined here and the count is in the manifest.
**Reverse:** `--lookahead-mult`.

### 2.9 Where the fall ENDS — a knee on the slope. Not in the work order at all.

**Chose:** the fall ends where its slope has recovered to `knee_frac = 0.05` of its own steepest,
with 3-sample hysteresis.
**Alternatives, both tried and both wrong:**
- `argmin` over the search window (the obvious reading of §3.5). On M2_aug the window after a
  sharkfin's onset spans several multiples of a 15-minute rise — long enough to reach the *next*
  cycle's minimum, which is often deeper. Fall durations came back as 344 / 457 / 665 / … / 1763 s
  for what is visibly one event shape, and the stored snippet swallowed two whole cycles. The
  overlay showed a train of spikes. Nothing raised.
- a prominence rule on the level (stop once the signal has climbed back a fraction of the depth so
  far). Correct on M2_aug, wrong on Mushroom: with a tiny running depth any upward noise sample ends
  the walk, median measured depth fell from 1.62 mV to 0.31 mV, and a third of the real icicles were
  then rejected as too shallow (26 events → 18).
**Why the knee works:** `knee_frac` is a fraction of *this event's own* steepest slope, so it is
scale-free by construction, and it terminates where the vertical part of the fall does whatever
follows. Measured: Mushroom 3–47 s, M2_aug 98–251 s, no runaway on either. It is also the operator's
own phrase — "the most vertical drop at the start of the drop" — made measurable.
**Reverse:** `--trough-knee-frac`; `find_trough` in `detect.py`.

### 2.10 A depth filter, relative to the deepest fall in the span. Not in the work order.

**Chose:** keep a candidate whose fall depth is ≥ `0.10 ×` the deepest fall in the same span.
**Alternative:** an absolute mV threshold, or no filter.
**Why:** without it Mushroom returns ~50 extra events that are baseline blips. Relative rather than
absolute so one setting works on a 12 mV recording and a 45 mV one — a self-calibrating,
dimensionless number. On M2_aug it rejects nothing at all, which is the right behaviour on a span
where every candidate is a real sharkfin.
**Cost, stated:** "kept" means something slightly different in each span. Absolute depths are all in
the event table so a reader can re-impose an absolute cut.
**Reverse:** `--min-depth-frac 0` disables it.

### 2.11 Deduplication — deepest wins within `min_separation_s`; 120 s on Mushroom, off on M2_aug

**Chose:** an explicit separation in seconds per recording, rather than a fraction of anything.
**Alternatives tried:** separation as a fraction of the snippet length (over-merges M2_aug, whose
snippets are ~47 min against a 15-min minimum true spacing — 16 events collapsed to 7); as a
fraction of the core event extent (still over-merges M2_aug: 1028 s core against 917 s minimum true
spacing).
**Why:** the two recordings genuinely need different answers and no derived quantity gets both
right. On Mushroom one icicle generates several rises (the overshoot, then bumps on the recovery),
each finding its own onset; the shortest true inter-icicle interval measured is 149 s, so 120 s
separates real events and collapses duplicates. On M2_aug the rise-to-drop mapping is already 1:1 —
16 rises, 16 onsets, one per sharkfin — so any non-zero separation only does harm. Depth plays the
role distance plays in `family_search.dedupe_matches`.
**Reverse:** `--min-separation-s`.

### 2.12 Snippet extent — anchored on the FALL, 2× before the onset and 4× after the trough

**Chose:** multiples of the fall's own duration.
**Alternative:** §3.5's recommendation of multiples of the *rise*'s duration.
**Why:** a rise-anchored window is ~15 minutes wide on M2_aug and ~4 seconds wide on Mushroom, which
stores the whole recovery on one recording and truncates it on the other. The fall is the motif, so
the fall sets the scale. Absolute sample indices are stored alongside, as §3.5 requires, so the
original `.npy` can be re-sliced exactly if more context is ever wanted.
**Reverse:** `--pre-context-mult` / `--post-context-mult`.

### 2.13 Storage — one packed `.npz` per recording, not one file per event

**Chose:** three files per run (`events.csv`, `snippets.npz`, `manifest.json`).
**Why:** tens of events, not thousands; three files copy or attach as a unit, and the "every row has
a snippet" invariant is one `set()` comparison rather than a directory walk.
**Note:** a `store.py` module was added under `Working/Detection/drop_motifs/` — §8's layout named
only `detect.py` and `cluster.py`, but §4 requires a store and `tests/test_drop_motifs_store.py`
requires something to import.

### 2.14 Clustering — Ward on the resampled vectors

**Chose:** resample every drop to 200 points, z-normalise, Ward linkage, cut at k=5.
**Alternative:** average linkage on a pairwise `scale_invariant_distance` matrix, as
`family_search.cluster_order` does.
**Why:** the work order called this the lighter-weight default and it is — every event is resampled
to a common length anyway, so the vectors are directly Euclidean-comparable and the second O(n²)
pass is avoidable. Ward's compact clusters are also what a per-cluster overlay needs to be legible.
The pairwise scale-invariant matrix is still built for `cross_scale.png`, which is the control:
its native-length-minus-scale-invariant panel is exactly the "same shape at a different duration"
question.
**Reverse:** `--linkage average` / `--resample-length`.

### 2.15 Roughness — a QC axis, drawn grey rather than removed

**Chose:** each member against its own cluster's **mean shape** (there is no hand-picked seed here),
threshold 2.0× as in `seed_replicas.py`. Flagged members are drawn faintly, not excluded.
**Alternative:** fold roughness into a composite distance.
**Why:** `seed_replicas.py` measured roughness varying 16× among matches at essentially identical
distance — distance does not carry the information, so a composite would hide the fact rather than
report it. Drawing rather than removing follows that module's own caveat: on this data the rejects
are usually noisy *recordings* of the right shape, not wrong matches, so hiding them overstates the
family. 4.8% of events (2 of 42) are flagged.
**Reverse:** `--max-roughness`.

### 2.16 Cluster count — k=5, an editorial choice, made the default so the figures reproduce

**Chose:** k=5 as the CLI default, with `--n-clusters 0` for the largest-merge-gap heuristic.
**Why:** the heuristic returns **k=2** on this event set. That is the honest unsupervised answer and
it separates fast-shallow from slow-deep, but *both* k=2 clusters mix the two recordings, so the
cross-dataset claim cannot be read off the picture at all. At k=5 the tree has resolved three pure
clusters and two mixed ones, which is a statement with content. Making it the default rather than a
flag means the plain command reproduces what is in `Plots/drop_motifs/` instead of something
adjacent to it.
**Flagged as editorial** in the code, the README and the data card. The final cut for the paper is
§9.7's human call.

### 2.17 Dendrogram rendering — the embedded-thumbnail version (§6.2), horizontal

**Chose:** §6.2's ambitious layout, not the fallback. Three columns: the tree with leaves ordered
top-to-bottom, one waveform thumbnail per leaf, one cluster overlay per branch.
**Why horizontal:** a vertical tree gives each of 42 leaves 1/42 of the figure *width* — a third of
an inch, where a thumbnail is a smudge. `orientation="left"` gives each leaf a full row, which is
also the aspect ratio a drop wants. 42 leaves was known before committing to the layout, and
`--dendrogram-style auto` falls back to panels above 60.
**Branch colours come from cluster membership, not from a height.** scipy's `color_threshold`
colours subtrees below a height, which only coincides with the clusters when the cut lands exactly
right; when it does not, the tree is coloured into a different number of groups from the panels
beside it and the figure quietly contradicts itself. That happened in the first draft. A
`link_color_func` resolving membership per node makes them agree by construction — the same approach
`dendrogram_cluster._make_link_color_func` takes, reimplemented because that module imports
matplotlib at module scope and wants a `ClusterResult` built from a window-matrix DataFrame.
**The fallback is written every run anyway** (`dendrogram_panels.png`) — it costs one figure and it
is the layout that survives being shrunk into a two-column paper.

### 2.18a The gradient rose's angle reference — stated, not defaulted

**Added after the original work order, at the operator's request.**

**Chose:** every angle is `arctan(slope / reference)` with the reference selectable
(`raw` / `recording` / `pooled` / `event`), printed on the figure, and recorded in
`gradient_rose_summary.json`. Default `raw` at 1.0 mV/s.
**Alternative:** `arctan(slope)` directly, which is what the phrase "the angle representing the
steepness of the slope" literally suggests.
**Why:** arctan takes a dimensionless argument and mV/s is not one. `arctan(slope)` silently fixes
the reference at 1 mV/s, so every angle on the figure would be an artefact of a unit choice nobody
made — and on this data that choice matters a great deal, because the two recordings sit either side
of it (−0.73 and −4.19 mV/s). Making it a stated parameter turns a hidden assumption into a caption.
**Reverse:** `--slope-ref`, `--gradient-field`.

### 2.18b The peakedness panel divides by the pooled median first

**Chose:** the shape rose plots `arctan(peakedness / pooled_median_peakedness)`.
**Alternative:** `arctan(peakedness)` directly.
**Why:** arctan compresses hard above ~3. Plotting the raw ratio puts Mushroom's 2.36 at 67° and
M2_aug's 4.26 at 77° — a 1.8× difference rendered as 10°, which makes the figure *understate* a real
separation. Referencing the pooled median puts a typical fall at 45° where arctan is most sensitive,
and the same difference opens to ~17° (−42.5° vs −52.7°). This was caught by looking at the first
draft and noticing the two roses looked more alike than the underlying numbers.
**Reverse:** pass `--gradient-field peakedness` with `--slope-ref` for a stated reference instead.

### 2.18c Uniformity is a KS test over the quadrant, not a Rayleigh test

**Chose:** a one-sample KS test against uniform over the reachable angular support.
**Alternative:** the Rayleigh test, which is the standard tool in circular statistics.
**Why:** Rayleigh tests uniformity over the **full circle**. Slope angles can only occupy one
quadrant, so a Rayleigh test here is significant by construction and measures the constraint rather
than the data. The KS test against uniform-on-the-quadrant asks the question actually of interest.
The choice is stated on the figure itself so a reader familiar with rose diagrams is not left
assuming a Rayleigh test was run.

### 2.18d The rose is built on `max_slope`, not `onset_slope`

**Chose:** the steepest single sample of the fall.
**Why:** `np.gradient` is a central difference, so at the corner where flat meets fall it averages
the two and reports half the true steepness — pinned by a test. Combined with the onset being the
first sample past the detection threshold on a 2 s segment grid, `onset_slope_raw`'s Mushroom median
(−0.088 mV/s) understates the real steepness (−4.18 mV/s) by a factor of fifty. `onset_slope_mv_s`
remains selectable but is not the default.
**Reverse:** `--gradient-field onset_slope_mv_s`.

### 2.18 Overlays are non-normalised in amplitude and normalised in TIME

**Chose:** every cluster overlay is drawn twice — absolute seconds, and time in units of each
event's own fall duration. Amplitude is millivolts in both and is never z-normalised.
**Why:** §5 and the docx are explicit that normalising amplitude destroys the evidence of scaling in
depolarisation events. But the two recordings' falls differ ~39× in duration, so without *some*
alignment the members of a mixed cluster share no x-axis and the figure shows nothing. Normalising
time and preserving amplitude separates the two questions and makes the finding visible: in
`cluster_3.png` the left panel shows nine icicles and eight sharkfins sharing nothing, and the right
panel shows them superimposed. No family mean is drawn, per the brief.

## 3. Numbers

All from `DATA/derived/drop_motifs/*/manifest.json` and `Plots/drop_motifs/cluster_summary.json`.

### Detection

| | Mushroom_260720 (385) | M2_aug 336–346 h (1) | total |
|---|---|---|---|
| span | 14,401 samples (4.00 h) | 36,000 samples (10.00 h) | |
| segments encoded | 7,200 | 300 | 7,500 |
| candidate rises | 950 | 16 | 966 |
| rises reaching the slope threshold | 109 | 16 | 125 |
| **drops confirmed** | **26** | **16** | **42** |
| rejected — no qualifying fall in lookahead | 841 | 0 | 841 |
| rejected — shallower than 0.10× the deepest | 52 | 0 | 52 |
| rejected — duplicate of a deeper nearby drop | 31 | 0 | 31 |
| SAME occupancy requested / observed | 0.50 / 0.504 | 0.70 / 0.720 | |
| slope threshold | −0.0568 mV/s | −0.1849 mV/s | |
| wall-clock | 0.046 s | 0.012 s | |

**External check:** M2_aug returned 16 drops from 16 rises with **zero** rejections, against
annotation 11266's independently recorded "16 cycles". Its measured peak-to-peak range
(17.7–54.6 mV) also sits inside that annotation's "20–70 mV".

**Mushroom check** (against a hand-built reference — deep minima of the detrended trace ≥ 4 mV,
separated by ≥ 60 s; weaker evidence than a human annotation, and built for this work):
25 reference icicles, 26 detected, **recall 24/25 = 0.96, precision 25/26 = 0.96**.

### Distributions

| | n | min | p25 | median | p75 | max | mean | sd |
|---|---|---|---|---|---|---|---|---|
| drop depth mV — Mushroom | 26 | 1.44 | 8.78 | 9.07 | 13.20 | 14.06 | 9.79 | 3.52 |
| drop depth mV — M2_aug | 16 | 14.61 | 21.09 | 28.56 | 38.81 | 46.50 | 30.18 | 10.23 |
| fall duration s — Mushroom | 26 | 3 | 5 | 5.5 | 8 | 47 | 11.23 | 12.95 |
| fall duration s — M2_aug | 16 | 98 | 123.75 | 176 | 196.25 | 251 | 165.50 | 44.53 |
| peak-to-peak mV — Mushroom | 26 | 2.75 | 9.31 | 9.57 | 13.94 | 14.27 | 11.02 | 2.77 |
| peak-to-peak mV — M2_aug | 16 | 17.68 | 23.50 | 31.66 | 45.55 | 54.59 | 34.34 | 12.58 |

### Fall-gradient rose (added after the original work order)

Circular statistics over the falling edges, from `Plots/drop_motifs/gradient_rose_summary.json`.

| | n | mean angle | R | circular SD | uniform p | median |
|---|---|---|---|---|---|---|
| **absolute steepness**, 45° = 1 mV/s | | | | | | |
| M2_aug | 16 | −36.0° | **1.000** | **1.3°** | 1.3e−05 | −0.730 mV/s |
| Mushroom_260720 | 26 | −72.8° | 0.961 | 16.1° | 5.9e−14 | −4.185 mV/s |
| pooled | 42 | −58.6° | 0.929 | 22.1° | 6.7e−06 | |
| **peakedness**, 45° = pooled median 3.09 | | | | | | |
| M2_aug | 16 | −52.7° | 0.997 | 4.4° | 6.5e−04 | 4.262 |
| Mushroom_260720 | 26 | −42.5° | 0.968 | 14.6° | 6.7e−03 | 2.357 |
| pooled | 42 | −46.5° | 0.975 | 12.8° | 3.0e−04 | |

Three findings:

1. **M2_aug's sixteen sharkfins have R = 1.000 and a circular SD of 1.3°.** Their falling edges are
   the same angle to measurement precision. This is a much stronger statement of regularity than
   anything the shape clustering produces, and it is on the one recording with an independent human
   annotation.
2. **The two recordings separate on both axes but in opposite directions.** Mushroom's icicles are
   ~6× steeper in mV/s yet closer to a uniform cliff (peakedness 2.36); M2_aug's sharkfins are
   shallower yet far more front-loaded (4.26). Absolute steepness and fall profile are carrying
   different information, and a model given only one of them would miss the other.
3. **Per-cluster: clusters 1 and 2 are both pure-Mushroom at mean −76.3° with R = 1.000** — identical
   gradient signatures, separated purely by shape. Shape clustering z-normalises and is blind to
   steepness by construction, so this is the expected-but-worth-checking confirmation that gradient
   and shape are independent axes. Cluster 3, the mixed one, is visibly bimodal in gradient
   (Mushroom at −76°, M2_aug at −34°) while being one shape family — which is the scale-free claim
   restated in gradient terms.

### Clustering — Ward, cophenetic r = 0.758, k = 5

| cluster | n | composition | median depth | median fall |
|---|---|---|---|---|
| 1 | 7 | Mushroom 7 — **pure** | 9.1 mV | 4 s |
| 2 | 7 | Mushroom 7 — **pure** | 8.8 mV | 5 s |
| **3** | **17** | **Mushroom 9 + M2_aug 8 — mixed** | **14.1 mV** | **9 s** |
| 4 | 2 | Mushroom 2 — **pure** | 1.5 mV | 41 s |
| **5** | **9** | **Mushroom 1 + M2_aug 8 — mixed** | **37.5 mV** | **177 s** |

Roughness-excluded fraction: **4.8%** (2 of 42), at 2.0× the cluster mean shape.

**The substantive result:** cluster 3 puts nine Mushroom_260720 icicles with 5–9 s falls in the same
shape family as eight M2_aug sharkfins with 98–195 s falls — a ~39× duration ratio and a ~2× depth
ratio. Two of five clusters mix the recordings; three are pure. Cluster 4 (n=2, 1.5 mV) is at the
noise floor and is kept visible rather than pruned, but should not be quoted as a motif family.

## 4. Test results

**Added — 45 tests, all passing:**

`tests/test_drop_motifs_detect.py` (17): exact onset index on a clean ramp-then-cliff and on a long
fall; a rise with no drop yielding zero events *and* a non-zero rejection count; two separated events
returning two; `min_separation_s` collapsing a pair into the deeper one; flat and constant-non-zero
signals returning zero events without raising; the three trough rules (ends the steep fall and
ignores a slow tail after it, survives one flat sample mid-fall, scale-free in the fall it measures,
does not run off the window end); `up_regions` / `merge_up_runs` unit cases; `robust_sigma`
insensitivity to outliers where `np.std` triples; run-to-run determinism; snippet indices bracketing
the onset; events carrying their own parameters; and a direct check that none of the three `Working/`
modules imports a plotting library.

`tests/test_drop_motifs_store.py` (11): CSV round trip with integer indices still integers; hours
columns agreeing with the indices they describe; span offsets making stored indices absolute in the
channel; bit-identical snippet reload; **replot with the source array deleted from the process**;
row/snippet bijection; manifest carrying every parameter and every rejection reason; an empty run
writing all three files with `empty: true`; manifest valid JSON on disk; `cluster_id` starting at −1
and being written back without disturbing the rest of the table.

Both files were written first and confirmed red (`ModuleNotFoundError: Working.Detection.drop_motifs`)
before any implementation existed.

`tests/test_drop_motifs_gradients.py` (17): fall gradients on a linear ramp agreeing across the
three measures; peakedness exceeding 1 on a front-loaded fall; gradients scaling with `fs` while the
dimensionless ratio does not; degenerate falls not raising; `slope_angle` honouring its reference
and staying bounded in the falling quadrant; every named slope scale being implemented; the circular
mean differing from the arithmetic mean across a wrap (where the latter points 180° wrong);
resultant length reading as concentration; uniformity testing calibrated against the reachable
quadrant rather than the full circle, checked over 40 draws rather than one lucky seed; binning
conserving every event, placing a known angle in the expected bin, including both endpoints, and
tolerating an empty input; and the no-plotting-library check.

Two of these caught real defects: `reference_slope` raised `KeyError` on gradient dicts built
without provenance, and the first draft of the uniformity test asserted on a single draw, which is
asserting on a seed rather than on calibration.

It also pinned a property that was initially mistaken for a bug — `np.gradient` is a central
difference, so at the corner where flat meets fall it reports half the true steepness. That is
correct behaviour and is the reason `max_slope_mv_s`, not `onset_slope_mv_s`, is the rose's default.

**Pre-existing suite — no regressions.** Baseline before this work, measured by running `pytest -q`
from the repo root with the new files ignored: **632 passed** in 231 s. Full suite after this work:
**677 passed**, exit code 0. 632 + 28 + 17 = 677, so every pre-existing test still passes and
nothing was quarantined or skipped.

## 5. Figures produced

Under `Plots/drop_motifs/`, PNG and PDF for each:

| File | What it is |
|---|---|
| `dendrogram_hero.png` | **§6.2's embedded-thumbnail version**, not the fallback. Horizontal tree, 42 leaves, one waveform per leaf labelled with hour / depth / fall duration, one cluster overlay per branch, leaf colour by source recording. Chosen because 42 leaves fits comfortably; `--dendrogram-style` forces either layout and `auto` falls back above 60 leaves. |
| `dendrogram_panels.png` | The §6.2 fallback, written every run regardless: tree beside a grid of per-cluster overlays, cluster ids annotated on both sides, leaf order and grid order visibly matched. This is the one that survives two-column shrinking. |
| `cluster_1..5.png` | §5's per-cluster overlays. Non-normalised amplitude, no family mean, absolute time beside fall-normalised time. **`cluster_3.png` is the figure to look at first.** |
| `overview_385.png`, `overview_1.png` | Detection QC: raw and detrended, every rise shaded, every onset marked. `overview_1.png` is where the 16-drops-against-16-annotated-cycles check is visible. |
| `cross_scale.png` | `family_search.plot_cross_scale` reused verbatim — dendrogram plus scale-invariant heatmap plus the native-length-minus-scale-invariant control. |
| `gradient_rose.png` | **Rose diagram** of the falling edges: ray angle is the fall's gradient, ray length is how many spikes share it. Two panels — absolute steepness and peakedness — plus a circular-statistics table. |
| `gradient_rose_by_cluster.png` | The same rose per shape cluster, on a shared radial scale, so gradient and shape can be compared as independent axes. |
| `cluster_summary.json` | Composition table, roughness report and linkage metadata, machine-readable. |
| `gradient_rose_summary.json` | Every circular statistic on the rose, so a number can be quoted without being read off the figure. |

## 6. Blocked / not done

- **`Working/Catalogue/dendrogram/dendrogram_cluster.py` was not reused directly**, despite §6's
  pointer. It imports matplotlib at module scope (a pre-existing violation of CLAUDE.md rule 1 — the
  enforcing test in `tests/test_types.py` only covers `Working.types`), calls `plt.show()` inside
  `plot_dendrogram`, and takes a `ClusterResult`/`PreprocessResult` pair built from a window-matrix
  DataFrame. Importing it from `Working/Detection/drop_motifs/` would have pulled matplotlib into the
  headless core. Its `_make_link_color_func` approach was reimplemented (10 lines, credited in a
  comment); nothing else was copied.
- **No sweep is exposed as a flag.** The parameter sweeps behind every preset in §2 were run by
  hand in a scratch directory; the measured figures each preset comment quotes are their results,
  but re-running a sweep means writing the loop again. A `--sweep` flag would be a genuine
  convenience if these parameters need revisiting for other channels.
- **Only one channel of each recording.** M2_aug has 16; the other 15 were not run. Nothing in the
  pipeline prevents it — add preset entries — but the presets are per-recording-id, so 15 more
  entries would be needed unless a default preset is introduced.
- **n=42.** This is a demonstration set, not a corpus. Every per-cluster statistic in §3 is
  descriptive.
- **The `native_length_distance` control is computed and plotted but not analysed.** `cross_scale.png`
  shows it; nobody has read off which pairs are "same shape, different duration" and put a number on
  it. That is a short piece of work and would strengthen the scale-free claim considerably.

## 7. Next

The honest next step is the editorial one this work order deliberately left open: **pick the cut and
the crop for the paper figure.** Specifically —

1. Decide whether k=5 is the cut to publish. k=2 is the unsupervised answer and makes the
   cross-dataset claim unfalsifiable by the picture; k=5 is legible but chosen. k=3 or k=4 have not
   been looked at. One command each: `--replot-from ... --n-clusters N --export-all`.
2. Decide whether `cluster_3.png`'s right panel alone is the hero figure, or whether the full
   `dendrogram_hero.png` is. The first makes one claim cleanly; the second shows the whole
   vocabulary and needs a full page.
3. Decide whether cluster 4 (n=2, 1.5 mV, at the noise floor) should be pruned by raising
   `--min-depth-frac`, or kept as an honest picture of where detection ends.

Two things that are not editorial and would materially strengthen the result if there is time:
quantify the `native_length` control (§6), and run the remaining 15 M2_aug channels so the
cross-dataset claim rests on more than one channel of each recording.
