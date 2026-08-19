# Spike-drop motifs — round 2

Follow-up to `SPIKE_DROP_MOTIFS_SUMMARY.md`. Four requests: split the cluster
overlays by dataset, recompute the dendrograms and roses per dataset, and run the
whole pipeline on more annotated spike-train spans.

## 1. What changed

The pipeline now runs over **six spans, 191 drops**, instead of two spans and 42.
Presets are keyed by **span**, not by recording — three of the six sit on M2_aug
CH00 alone and want detrend windows a factor of fifteen apart, so a
recording-keyed store had them overwriting each other. Figures are written twice:
once per span (each clustered on its own) and once pooled.

```
Plots/drop_motifs/
    <span_key>/    overview, dendrogram_hero, dendrogram_panels,
                   gradient_rose, gradient_rose_by_cluster, cluster_<k>, cross_scale
    pooled/        the same, plus cluster_<k>_by_span
```

## 2. The spans

| span key | annotation | span | events | median depth | median fall |
|---|---|---|---|---|---|
| `mushroom_icicles` | — | 0–4 h | 28 | 9.05 mV | 8 s |
| `m2aug_ch00_am16` | 11266 "16 cycles" | 336–346 h | **16** | 28.56 mV | 176 s |
| `m2aug_ch00_sharkfin14` | 11280 "14x sharkfin sequence" | 314.5–316.5 h | **13** | 6.93 mV | 140 s |
| `m2aug_ch00_furrycaterpillar` | 11271 "100 furrycaterpillars" | 485.9–488.5 h | 68 | **0.20 mV** | 7 s |
| `m2aug_ch01_growing` | 11283 "long sequence, small then larger" | 400–460 h | 38 | 61.60 mV | 44 s |
| `m2aug_ch03_troughtrain` | 11295 "spike train of trough spikes" | 405–450 h | 28 | 71.48 mV | 44 s |

Two spans now check against a stated human count: **16 from 16** on annotation
11266 and **13 of the annotated 14** on 11280.

The measured event set spans **0.05 mV to 135 mV** — a factor of 2,700 — and fall
durations from 2 s to 4,955 s.

### furrycaterpillar

Found where you remembered it: annotation 11271 / catalogue ID 6, *"Regular
sequence of 100 furrycaterpillars; 30 mV rollinghills"*. Each tooth is a ~90 s
rise then a ~0.3 mV drop, riding on a slow rolling hill — thirty times smaller
than anything previously tested.

68 detected against the annotated 100 (~69% recall). The **measured median
inter-onset interval is 102 s against the annotation's implied 92 s**, so what is
found is the right rhythm rather than noise. It needs `slope_sigma=4` rather than
the default 8: its drops run −0.10 to −0.125 mV/s against a noise sigma of 0.016,
i.e. genuinely only 6–8 sigma above the sample-level floor. That is a
signal-to-noise limit of a 0.3 mV event on this electrode, not a tuning fudge, and
it is recorded as such in the preset.

### Stegasauras — not located

The catalogue has it (spelled `Stegasauras`, ID 12, DATASET **M2** not M2_aug,
CH00, 181–188.5 h, *"Transitioning sequence; 10mV -> 3mV"*). Nothing at that
address matches: I checked **all sixteen** M2_concat channels over that span and
the busiest four by eye. CH00 has one −35 mV spike at 184.3 h and otherwise smooth
drift; no channel shows a transitioning spike train.

Most likely the catalogue's time base for the M2 family does not align with the
ingested `M2_concat_fs1.mat`, which is itself a concatenation —
`family_search.py`'s README already warns the DATASET column maps to a recording
family rather than a file. **Unblocking it needs someone who knows how the
catalogue's M2 offsets map onto the concatenated file.** I have not guessed at a
different address.

## 3. A real bug this surfaced

`m2aug_ch00_sharkfin14` returned **14 rises and zero drops**. The cause was the
noise estimator, and it is the same class of failure as the dSAX `learned` mode
already documented:

> `robust_sigma(np.gradient(x))` measures noise only while events are RARE. On
> that span 14 events fill the whole 1.97 h, so more than half of all samples lie
> on an event slope and the MAD reports the typical *event* slope, 0.0387 mV/s.
> Six of those is −0.232 mV/s — steeper than the steepest sample anywhere in the
> span (−0.186). The detector found the rises and no drops. Nothing raised.

Fixed by estimating the noise from the **second difference**, which annihilates
any locally linear trend so smooth event slopes contribute nothing:

```
sigma = MAD(diff(x, 2)) / sqrt(6) / sqrt(2)
```

Both factors matter — `sqrt(6)` because Var of a second difference of white noise
is 6σ², `sqrt(2)` because the thresholded quantity is a central difference. With
those, `slope_sigma` means the number of sigmas written on it; the default moved
6 → 8 to land on the same physical threshold.

**Impact on the already-validated spans is minimal**: Mushroom 26 → 28 events,
and M2_aug's 16-from-16 match against annotation 11266 is unchanged.

Two guards were needed, both tested:
- a **piecewise-linear signal** has a second difference of ~0, so its MAD reports
  float round-off; the estimate is floored at 1/100 of the gradient estimate.
  Across the six spans the two sit within 0.6×–1.25× of each other, so the floor
  binds only where there is no noise to measure.
- a **noiseless** signal gets a floor derived from its own amplitude range, so the
  threshold can never be zero (which would call the first non-increasing sample
  after every rise a drop).

`--noise-estimator gradient` keeps the old behaviour for comparison.

## 4. A preprocessing failure now pinned rather than hidden

Fixing the estimator exposed that the engineered test fixture used a detrend
window of 600 s on a signal with events 1200 samples apart. At that ratio the
**rolling mean's own recovery after the first cliff becomes a 287 s fall in the
detrended trace**, and the detector reports it — correctly, since by then it is a
fall in the signal it was handed. The stricter old threshold had been masking it.

The fixture now uses a window wider than the event spacing, and
`test_a_short_detrend_window_manufactures_a_spurious_slow_fall` pins the
phenomenon deliberately, including the giveaway: a fall duration two orders of
magnitude longer than its neighbours at a fraction of their depth.

## 5. The figures you asked for

**Split cluster overlays** — `pooled/cluster_<k>_by_span.png`. Absolute time only,
one panel per span, all aligned on the drop onset.

I initially shared the y axis across panels on the reasoning that the amplitude
difference is a finding. That was wrong in practice: a pooled cluster spans 0.06 mV
caterpillars and 109 mV trough spikes, and on one axis two thirds of the figure
is flat lines. Panels now share the axis **only when their ranges are within 5×**,
and where they are not the figure says so in the title (*"INDEPENDENT amplitude
scales — the spans' ranges differ 42x"*). The amplitude difference is still carried
exactly, in numbers, by each panel's own subtitle.

**Per-span dendrograms and roses** — each span clustered on its own, in its own
directory. This matters more than colour-coding would have: pooled, a 0.3 mV
caterpillar and a 90 mV trough spike sit at opposite ends of the tree and neither
span's internal structure is visible.

The per-span roses also needed a different angle reference. A fixed 1 mV/s puts
every furrycaterpillar ray within six degrees of horizontal and the panel shows
nothing. Per-span roses now use that span's **own median steepest slope**, so 45°
means "typical here" and what remains on the plot is the spread; the pooled rose
keeps the absolute 1 mV/s, because comparing spans against each other is what it
is for.

## 6. The headline number

From `pooled/gradient_rose_summary.json`:

| span | absolute steepness | R | peakedness | R |
|---|---|---|---|---|
| furrycaterpillar | −5.9° | 1.000 | −52.8° | 0.873 |
| sharkfin ×14 | −9.1° | 1.000 | −38.7° | 0.998 |
| AM sharkfin ×16 | −36.0° | 1.000 | −45.2° | 0.997 |
| Mushroom icicles | −67.1° | 0.917 | −44.9° | 0.915 |
| CH01 growing | −74.6° | 0.967 | −54.2° | 0.967 |
| CH03 trough train | −75.0° | 0.957 | −50.2° | 0.935 |

**Absolute steepness spans 69° across the six spans; peakedness collapses them
into a 16° band.** The *shape* of the fall is conserved across a 2,700× amplitude
range while its *rate* varies enormously. That is the scale-free claim, quantified,
and it is a much stronger version of it than the two-span set could support.

Three spans have **R = 1.000** on absolute steepness — their falling edges are one
angle to measurement precision.

## 7. On cluster 4 — you were right

Your read was correct and the data agrees. Mushroom's icicles largely *do* drop
without a preceding rise: the pre-drop overshoot is one to two samples, present on
roughly half of them, which is why 757 of 950 candidate rises there are rejected
for having no fall behind them and why the old cluster 4 was two near-noise events
at 1.5 mV. The detector is structurally biased toward drops that have a detectable
rise, and that is stated in the data card's limitations rather than buried.

The old cluster 4 is gone from the pooled set — with 191 events the tree has enough
structure that the near-noise pair no longer forms its own branch. The
per-span Mushroom clustering still has a 2-member 1.9 mV cluster, which is the
honest picture of where its detection ends.

## 8. Tests

**48 added** (up from 45): 20 detect, 11 store, 17 gradients. Full suite **680
passed**, exit 0 — 632 pre-existing + 48. New this round:

- the short-detrend-window artefact, pinned deliberately (§4);
- `span_key` round-tripping through the store, and not being interchangeable with
  `recording_id`;
- a store written without a span key still getting a usable one.

## 9. Not done

- **Stegasauras** — see §2.
- **The pooled dendrogram is of limited value at this range.** 191 leaves forces
  the panels layout, and within a single panel the small-amplitude spans are flat
  against the large ones — the same problem the `_by_span` split solves for the
  cluster overlays, but a dendrogram cannot be split that way without ceasing to be
  one tree. The per-span dendrograms are the ones to read.
- **`m2aug_ch01_growing` has one event with a 4,955 s fall** and `m2aug_ch03_troughtrain`
  five between 395–899 s. These are the knee rule running on where a fall is
  followed by slow drift rather than a recovery. They are visible in the tables and
  in cluster 2/4 of the pooled panels as traces containing several spikes. Raising
  `--trough-knee-frac` would cut them; I have not, because the right value is a
  judgement about what counts as one fall on those channels.
- **Roughness excludes 27.9% of the furrycaterpillar span** when clustered on its
  own, and 19.9% pooled. Those are genuinely noisy 0.3 mV events; the threshold is
  `seed_replicas`' default 2.0 and has not been retuned for this amplitude.
