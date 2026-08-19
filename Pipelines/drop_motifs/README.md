# drop_motifs

Spike-**drop** motif discovery: the sharp negative-going fall that follows the rise of a spike,
found by trend classification rather than by nearest-neighbour search, collected across two very
different recordings, and asked whether it is itself a recurring, clusterable motif.

This is the complement to [`Pipelines/motif_report/`](../motif_report/README.md), not a replacement.
Those tools find families of **whole** spikes by matrix-profile self-similarity. This one finds one
**sub-shape** and asks a different question: not "do whole spikes repeat" but "does the
*rise-then-drop* dynamic have a small vocabulary of shapes, and is that vocabulary shared across
recordings whose events differ by a factor of forty in duration?"

## Quick start

```powershell
# both recordings at their tuned defaults: detect, store, cluster, every figure
python Pipelines/drop_motifs/run_drop_report.py --export-all

# re-cut the tree and redraw, touching no recording and no database
python Pipelines/drop_motifs/run_drop_report.py `
    --replot-from DATA/derived/drop_motifs/385 `
    --replot-from DATA/derived/drop_motifs/1 --n-clusters 7 --export-all
```

The second form is the point of the store existing. `--replot-from` reads `events.csv` and
`snippets.npz` and nothing else — no `.npy`, no SQLite — so a figure can be re-cropped, re-coloured
or re-clustered without paying for detection again.
[`tests/test_drop_motifs_store.py`](../../tests/test_drop_motifs_store.py) asserts that by deleting
the source array before reloading.

## What it found

42 drops, from 950 candidate rises. Pooled and clustered at k=5:

| cluster | n | composition | median depth | median fall |
|---|---|---|---|---|
| 1 | 7 | pure Mushroom | 9.1 mV | 4 s |
| 2 | 7 | pure Mushroom | 8.8 mV | 5 s |
| **3** | **17** | **9 Mushroom + 8 M2_aug** | **14.1 mV** | **9 s** |
| 4 | 2 | pure Mushroom | 1.5 mV | 41 s |
| **5** | **9** | **1 Mushroom + 8 M2_aug** | **37.5 mV** | **177 s** |

Two of the five clusters mix both recordings. Cluster 3 is the headline: nine 4-hour-recording
icicles with 8-second falls and eight 721-hour-recording sharkfins with 190-second falls land in the
same shape family. `Plots/drop_motifs/cluster_3.png` draws them twice — once in absolute seconds,
where they share nothing, and once with time in units of each event's own fall duration, where they
superimpose. Amplitude is in millivolts in both panels and is never normalised.

On M2_aug the detector returns **16 drops from 16 rises with zero rejections**, against a human
annotation (id 11266) that independently records "16 cycles" over the same span. That is the
strongest available check that the onsets are landing where a person would put them.

## The algorithm, and the two places it departs from the obvious

```
  1. rolling-mean detrend            remove slow baseline drift
  2. dSAX trend encoding, k=3        D / S / U per segment
  3. regex `U+` over the letters     every maximal run of U is a rise
  4. derivative scan after each      first steep fall is the drop onset
  5. knee on the slope               where the steep fall ends
  6. depth + separation filters      one event per real event, no noise
```

### 1. dSAX runs in `quantile` mode, not `learned`

This is the single most consequential choice in the pipeline and it is the opposite of dSAX's own
default.

`learned` mode fits Lloyd-Max cutlines that are MSE-optimal against the observed delta distribution.
On a spiking recording that distribution is dominated by the rare, enormous drop deltas, so the
optimal answer is a SAME band wide enough to swallow 99% of segments — **including the entire
rise**. Measured on Mushroom_260720 the learned SAME fraction is 0.98–0.99 and the letters around a
real icicle read:

```
learned    SSSSSSSSDSSSSSS      the fall is classified, the rise never is
quantile   SSSUDDUDDU           a rise, then the fall
```

With `learned`, "the first fall after a rise" matches **nothing** on Mushroom_260720: zero events
across every detrend window and segment length tried. Quantile mode sets the band by *occupancy*
instead, which is scale-free with respect to how big the drops are.

A second, free benefit: quantile mode consumes no RNG at all (see `dsax()`'s own "Determinism"
note), so detection is reproducible without depending on anybody remembering to seed. The seed is
still recorded in the manifest because the clustering step may consume one.

### 2. The negative-slope threshold is a noise floor, not a dSAX cutline

The work order suggested deriving it from dSAX's learned DOWN cutline, to avoid a second free
parameter. That reasoning holds for `learned` mode, where the cutline is a magnitude. Under
`quantile` mode the cutline is an occupancy quantile and carries no information about how steep
"steep" is, so it cannot serve. Instead:

```
slope_threshold = -slope_sigma * robust_sigma(d/dt x_detrended)
```

`robust_sigma` is a MAD estimate, and the MAD rather than the standard deviation is essential: on
this data the rare huge drops **are** the outliers, so an sd-based scale is set by the very events
being looked for. `--slope-sigma` then reads directly as a claim — "the fall is at least this many
times steeper than noise alone produces".

## The knobs that matter

| Flag | Why it exists |
|---|---|
| `--detrend-window-s` | Long relative to noise, comparable to one spike. Too short removes the spike along with the drift: on M2_aug a 60 s window leaves 7 mV of a 63 mV excursion, a 1800 s window leaves 40 mV. |
| `--segment-seconds` | dSAX segment duration. Must be short enough that the rise spans several segments. On Mushroom the pre-drop rise is **one to two samples**, so 2 s is the largest usable value — at 3 s and above recall against hand-marked icicles falls from 0.96 to 0.80. |
| `--same-fraction` | Target SAME occupancy. Reads as an assumption about how much of the recording is quiescent. Lower on Mushroom (0.5) than on M2_aug (0.7) because that one-sample overshoot needs a narrow band to register as UP at all. |
| `--merge-gap-segments` | Bridge `U S{1,n} U` into one rise. `0` (the bare regex) treats a rise with a plateau as two rises. `1` on Mushroom, where the overshoot is often `U S U` at 2 s segments. A `D` is never bridged. |
| `--slope-sigma` | The onset threshold, in robust sigmas of the per-sample derivative. |
| `--trough-knee-frac` | Where the fall **ends**: the slope has recovered to this fraction of its own steepest. See below. |
| `--min-depth-frac` | Keep a candidate whose fall depth is at least this fraction of the deepest fall in the same span. Relative rather than absolute so one number works on a 12 mV recording and a 45 mV one. |
| `--min-separation-s` | Two onsets closer than this are the same event seen from several rises; the deeper survives. `120` on Mushroom (shortest true inter-icicle interval measured: 149 s); `0` on M2_aug, where the rise-to-drop mapping is already 1:1. |
| `--pre-context-mult` / `--post-context-mult` | Snippet extent in multiples of the fall's own duration. Anchored on the **fall**, not the rise: a rise-anchored window is 15 minutes wide on M2_aug and 4 seconds wide on Mushroom, which stores the recovery on one recording and truncates it on the other. |
| `--n-clusters` | The shipped cut is 5, so the plain command reproduces `Plots/drop_motifs/`. `0` uses the largest-merge-gap heuristic, which returns 2 — the honest unsupervised answer, but one level too coarse for the figure, because at k=2 both clusters mix and the cross-dataset claim becomes unfalsifiable by the picture. |
| `--max-roughness` | Flag members more than this many times as jagged as their cluster's mean shape. Same convention and default as `seed_replicas.py`. Flagged members are drawn grey, not removed. |

### Where the fall ends: a knee on the slope

Two obvious definitions both fail here, and both failed in development before the knee rule
replaced them:

- **`argmin` over the search window.** On M2_aug the window after a sharkfin's onset spans several
  multiples of a 15-minute rise, long enough to reach the *next* cycle's minimum. Fall durations
  came back as 344 / 457 / 665 / … / 1763 s for what is visibly one event shape, and the stored
  snippet swallowed two whole cycles. Nothing raises; the overlay is just wrong.
- **A prominence rule on the level** (stop once the signal has climbed back a fraction of the depth
  so far). Correct on M2_aug and wrong on Mushroom, where a tiny running depth means any upward
  noise sample ends the walk immediately: median measured depth fell from 1.62 mV to 0.31 mV and a
  third of the real icicles were then rejected as too shallow.

A knee on the **slope** has neither failure. `knee_frac` is a fraction of *this event's own*
steepest slope, so it means the same thing on a 4-second icicle and a 3-minute sharkfin, and it
terminates where the vertical part of the fall does whatever the signal does afterwards. Measured at
`knee_frac=0.05`: Mushroom falls at 3–47 s, M2_aug at 98–251 s, with no runaway on either.

This is also the operator's own framing made measurable: *"we are only interested in the most
vertical drop at the start of the drop."*

## Per-recording presets

The two recordings are **not** forced to share parameters. `RECORDING_PRESETS` in
`run_drop_report.py` holds each set with the reasoning inline, because a preset with no provenance
is a magic number. Every value actually used lands in that run's `manifest.json`, so a figure can
always be traced back to what produced it.

The M2_aug span is read from **annotation 11266** at run time, not hardcoded, so the crop is
traceable to a human verdict. The full annotated span (336–346 h) is used rather than the narrower
336.8–344.4 h quoted informally: the annotation is the record, and the wider span costs nothing
because the quiet head and tail simply produce no events.

## What is stored

```
DATA/derived/drop_motifs/<recording_id>/
    events.csv        one row per drop, 30 columns, indices absolute in the channel
    snippets.npz      raw_mv / detrended_mv / t_s per event, keyed by event_id
    manifest.json     every parameter, every rejection count, the measured distributions
```

Indices are **absolute in the source channel** even for a cropped run, so the original `.npy` can be
re-sliced exactly if somebody later wants more context than was materialised. Indices are the safety
net; the materialised snippet is the convenience copy, independent of whether `DATA/` is reachable.

A run that finds nothing still writes all three files, with `"empty": true` in the manifest. "Found
nothing" and "was never run" must not look alike on disk.

## Clustering

Two axes, kept separate, mirroring what `seed_replicas.py` established on this data:

- **What shape is it** — resample to 200 points, z-normalise, Ward linkage on the vectors.
- **How clean an instance is it** — `roughness` of the member against its own cluster's mean shape.

Roughness is a QC axis, not a clustering dimension. `seed_replicas.py` measured roughness varying by
16× among matches at essentially identical z-normalised distance, so distance simply does not carry
that information; folding it into a composite distance would hide the fact rather than report it.
Flagged members are drawn grey rather than removed, because on this data the rejects are usually
noisy *recordings* of the right shape, not wrong matches.

Ward on the vectors rather than average linkage on a pairwise matrix (which is what
`family_search.cluster_order` does): every event is resampled to a common length here anyway, so the
vectors are directly Euclidean-comparable, and Ward's compact clusters are what a per-cluster
overlay needs to be legible. The pairwise scale-invariant matrix is still built for
`cross_scale.png`, which is the control.

## Figures

| File | What it shows |
|---|---|
| `overview_<id>.png` | Detection QC: the span, every rise shaded, every onset marked. On M2_aug this is where the 16-drops-vs-16-annotated-cycles check is visible. |
| `dendrogram_hero.png` | The tree, one waveform thumbnail per leaf, one cluster overlay per branch. 42 leaves. |
| `dendrogram_panels.png` | The lower-risk fallback: tree beside a grid of per-cluster overlays, cluster ids annotated on both. Written every run. |
| `cluster_<k>.png` | One cluster overlaid, absolute time beside fall-normalised time. No family mean — the operator asked for the members, and on a family spanning 40× in duration a mean is a line no member resembles. |
| `cross_scale.png` | `family_search.plot_cross_scale`, reused verbatim. Its third panel, native-length minus scale-invariant, is exactly the "same shape at a different duration" control this pipeline's claim needs. |
| `gradient_rose.png` | Rose diagram of the falling edges — see below. |
| `gradient_rose_by_cluster.png` | The same rose per shape cluster, on a shared radial scale. |

## The gradient rose

A **rose diagram** — equivalently a circular or polar histogram, a wind rose in meteorology, a
strike/dip rose in structural geology. Each ray points at the angle of one spike's falling edge and
its length is how many spikes fall at that steepness, so the whole population's descent geometry is
one picture. The ray *is* the falling edge, drawn to scale: 0° is flat, 90° is vertical, and
everything lives in the fourth quadrant because a fall goes down as time goes right.

The associated maths is **circular statistics**, and the numbers are on the figure and in
`gradient_rose_summary.json`: the mean direction is a vector mean (not an arithmetic mean of angles,
which is wrong across a wrap), and `R` is the mean resultant length — 0 for spread evenly, 1 for all
identical. A mean direction with a low `R` is not a finding, so the dashed mean-direction ray is
drawn at length `R × peak`: a short dash *is* the statement that the directions are not concentrated.

### The unit trap

**`arctan` takes a dimensionless argument, and mV/s is not one.** A slope of −0.73 mV/s has no angle
until something states how many millivolts equal one second *on the page*. Writing `arctan(slope)`
and letting the reference default to 1 mV/s unremarked produces a figure whose angles are an
artefact of a unit choice nobody made. So every angle here is `arctan(slope / reference)` with the
reference selectable, printed on the panel, and recorded in the summary JSON.

| `--slope-ref` / scale | What 45° means |
|---|---|
| `raw` (default, `--slope-ref 1.0`) | a stated slope in mV/s. Separates the recordings by absolute steepness. |
| `recording` | each recording's own median steepest slope. The two roses become superimposable and what is left is the spread within each. |
| `pooled` | the median over all events. One data-chosen reference for everybody. |
| `event` | the event's own mean fall slope, making the quantity the dimensionless peakedness ratio. |

A second compression trap, fixed rather than documented away: the shape panel plots `peakedness`
(steepest ÷ own mean gradient), and `arctan` compresses hard above ~3. Plotting the raw ratio puts
Mushroom's 2.36 at 67° and M2_aug's 4.26 at 77° — a 1.8× difference rendered as 10°. The panel
therefore divides by the **pooled median peakedness** first, so a typical fall sits at 45° where
arctan is most sensitive and the same difference opens out to ~17°.

### Which gradient

`--gradient-field` selects it. `max_slope_mv_s` (default) is the steepest single sample of the fall
— what "how vertical is the drop" means. `onset_slope_mv_s` is available but is a **poor** steepness
measure here: `np.gradient` is a central difference, so at the corner where flat meets fall it
averages the two and halves the answer, and on Mushroom's 2 s segment grid the declared onset can
sit a step before the real cliff. Its median (−0.088 mV/s) understates the truth (−4.18) fiftyfold.

### What it found

| | n | mean angle | R | circular SD | median |
|---|---|---|---|---|---|
| **absolute steepness** (45° = 1 mV/s) | | | | | |
| M2_aug | 16 | −36.0° | **1.000** | **1.3°** | −0.730 mV/s |
| Mushroom | 26 | −72.8° | 0.961 | 16.1° | −4.185 mV/s |
| **peakedness** (45° = pooled median, 3.09) | | | | | |
| M2_aug | 16 | −52.7° | 0.997 | 4.4° | 4.262 |
| Mushroom | 26 | −42.5° | 0.968 | 14.6° | 2.357 |

Two things worth saying out loud. First, **M2_aug's sixteen sharkfins have R = 1.000 and a circular
SD of 1.3°** — their falling edges are, to measurement precision, the same angle. Second, the two
recordings separate by absolute steepness (a ~6× ratio) *and* by peakedness, but in **opposite
directions**: Mushroom's icicles are steeper in mV/s yet closer to a uniform cliff, while M2_aug's
sharkfins are shallower yet far more front-loaded.

The per-cluster rose adds a third: clusters 1 and 2 are both pure-Mushroom with mean −76.3° and
R = 1.000, i.e. **identical gradient signatures separated purely by shape**. Shape clustering
z-normalises and is blind to steepness by construction, so this is the expected-but-worth-checking
result that the two measures carry independent information.

### The uniformity test is not a Rayleigh test

Slope angles can only ever occupy one quadrant, so a Rayleigh test against uniform-on-the-full-circle
is significant here by construction and measures nothing but the constraint. The reported `uniform p`
is a KS test against uniform **over the reachable quadrant**, which asks the question actually of
interest: given that every fall must land in this quadrant, are they clustered within it?

**Every drawn trace is in millivolts and none is z-normalised.** The clustering z-normalises so that
"same shape" has a definition; the figure does not, because normalising amplitude destroys the
evidence of scaling in depolarisation events — which is the finding these figures exist to show.

## Layout

```
Working/Detection/drop_motifs/       headless core: detect.py, cluster.py,
                                     store.py, gradients.py
Pipelines/drop_motifs/               this: run_drop_report.py, figures.py
tests/test_drop_motifs_detect.py     engineered signals, exact onset indices
tests/test_drop_motifs_store.py      store round trip, replot-without-the-recording
tests/test_drop_motifs_gradients.py  gradient measurement and circular statistics
```

Nothing under `Working/` imports matplotlib, Panel, HoloViews or Bokeh (CLAUDE.md rule 1), which is
what lets detection run on a compute node and what makes the figures replayable from storage alone.
`figures.py` is the only module that imports matplotlib, and it forces the Agg backend before
pyplot's first import — the same split `motif_report.py` keeps.
