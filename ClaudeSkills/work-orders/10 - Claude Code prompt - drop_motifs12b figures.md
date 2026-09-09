# Claude Code prompt — drop_motifs12b: redrawing the figures

Run after `12a`. Reads `Plots/drop_motifs12a/motifs/` and redraws the figures that failed review.

---

# PROMPT

## What this run does

Redraws **S2_2, S2_3, S3_1 and S3_2** from `drop_motifs11` under corrected drawing rules, against the
enlarged store from `drop_motifs12a`. **S2_1 (fall angle) is good and is not touched** — copy it
across unchanged, or regenerate it identically against the new store if the species set has changed.

This run detects nothing and adds no analysis. Every figure it produces is a redraw.

Read first: `Plots/drop_motifs11/FIGURES.md`, `Plots/drop_motifs12a/PROVENANCE.md`, and the two
visual references named below.

## Why the round-11 figures failed, so the same mistakes are not repeated

Three causes, diagnosed:

1. **The normalised panels plotted "fraction of the fall" — onset to trough only.** The shoulder the
   fall departs from and the recovery it returns through were cropped out, which is why families were
   indistinguishable: only the middle of each waveform was drawn.
2. **A 200-point resample of a 6-sample fall is linear interpolation between six points.** The Reishi
   normalised curve was literally five straight segments. The feature vector is a distance
   representation, not a picture.
3. **The waterfall offset was roughly 4× each waveform's own amplitude**, flattening every trace to a
   horizontal line.

## The drawing rules — requirements, not preferences

Put these in one shared module that every figure imports. They are not per-figure decisions.

1. **Real samples, real seconds.** No figure ever plots a resampled feature vector. Where a normalised
   comparison is wanted, normalise the *values*; the time axis is described in rule 5.
2. **Draw the whole stored snippet** — 1.2 falls before onset, 1.8 after trough. Never crop to
   onset→trough.
3. **Height-to-width locked** with `style7.span_locked_aspect` / `figure_aspect` / `apply_aspect`,
   which already exist and already cap extreme ratios. Target the median event in each figure at
   between **1:1 and 3:1 height-to-width**; print the true ratio in the panel label where the cap
   bites. State the lock once per figure as `1 mV drawn as 11.3 s of width`.
4. **Panels are taller than they are wide** wherever a single waveform is the subject. The round-11
   panels were roughly 1.6:1 landscape and that alone flattened the drops.
5. **The normalised axis runs −0.5 to 1.5 in fall-fractions, not 0 to 1.** Keep the "fraction of the
   fall" axis — it is the right axis — but extend it either side so the approach and the recovery are
   in frame. Where a figure normalises both axes, say so on the axis label.
6. **Waterfall offset = 0.8 × the drawn peak-to-peak of the events in that panel**, so successive
   traces slightly overlap and none is flattened. Draw at most **25** traces; if the sequence is
   longer, draw every *k*th and state *k*. Include an explicit mV scale bar.
7. **Colour graded by time within the sequence**, following `overlays6` / `overlays7`.
8. **Every sequence figure carries a raw-signal reference strip across the top** — the source trace
   over the sequence's whole span, with each detected event shaded in its own gradient colour, so a
   reader can see where the waveforms came from.
9. **A drop must look like a drop.** If any panel's events render as near-horizontal lines, the aspect
   is wrong.

**Visual references, and they are the standard to hit:**
`Plots/drop_motifs7/id003_overlays.png` — raw strip on top with time-graded shaded spans, full-context
overlays beneath, height-to-width locked and stated in the title.
`Plots/drop_motifs5/id385_contact.png` — small-multiples catalogue, raw mV against absolute seconds
from each event's own onset, fall span shaded, detrended trace faint beneath, each panel labelled with
depth and duration and impure events drawn in a warning colour.

Style rules from the previous brief still stand: noun-phrase titles, no explanatory prose inside the
axes, legends that never overlap another subplot, consistent typography, units and *n* everywhere,
provenance footer, species colour keyed by name so the palette survives new species.

---

## Figure S2_2 — Scale collapse

Two columns, one row per species. Seeded random sample, equal n per species.

**Left, native units.** Each sampled event drawn as real samples against seconds from onset, whole
snippet, height-to-width locked to that species' own median event. Print the sample's duration and
amplitude ranges beneath.

**The round-11 left panels were unreadable** because the x-range was set by the longest event, so
short events collapsed into the left edge. Fix by **drawing each species' sample at a common
fall-duration scale within that species** — clip the x-range to a stated quantile of the sample's
snippet lengths (say the 90th) and note how many events extend beyond it, rather than letting one
280-second event set the axis for a 2-second one.

**Right, normalised.** Values z-normalised per event; x in fall-fractions **from −0.5 to 1.5**, so the
approach and recovery are visible. This is the panel that shows the collapse, and it needs the context
either side to be convincing. Species median drawn solid over a faint sample.

Reduce the sample to **40 per species** if 60 is still crowded, and say which was used.

## Figure S2_3 — Asymmetry of generalisation

The round-11 version was flat lines and unreadable. Rebuild:

**Panel A — the shape vocabularies, side by side.** One column per species, each showing that species'
family medoids drawn as real waveforms with context, amplitude-normalised, height-to-width locked and
**tall**. The reader must be able to see that Reishi's medoids are broad relative to their spacing and
Lion's mane's are narrow. If the medoids are too numerous to draw legibly, show the largest families
covering 80% of events and say so.

**Panel B — matching, both directions.** Two sub-panels. Each foreign medoid drawn beside its nearest
Reishi medoid, paired; then the reverse. Draw them as overlaid pairs, not as a matrix. The first set
matches and the second does not, and that visible difference is the finding. Median matching distance
printed under each sub-panel — one number each, no test.

**Panel C — duty cycle against absolute duration.** Fall duration divided by that channel's median
inter-event interval, per species, with spread; beside it, absolute fall duration. The reversal is the
point and must be visible: Reishi's waveforms are broad relative to their spacing while being the
shortest in absolute time. Recompute both from the new store — the Lion's mane numbers will change
now that it is 10 Hz and much larger.

## Figure S3_1 — Sequence morph

Per sequence. Layout, top to bottom:

**Reference strip.** The raw source trace across the sequence's whole span, each detected event shaded
in its gradient colour. This is the panel that was missing and it is what makes the rest legible.

**Left — native units waterfall.** Successive events offset by 0.8× their drawn peak-to-peak, oldest
at top, gradient-coloured, height-to-width locked, mV scale bar, at most 25 traces.

**Right — normalised waterfall.** Same ordering, same offset rule, values normalised per event, x from
−0.5 to 1.5 fall-fractions.

**Beneath — successive difference.** Distance between event *n* and *n+1* along the sequence, with the
first-to-last distance drawn as a reference line, and the count of steps smaller than it stated.

**Beneath — start against end.** First and last events overlaid as real waveforms with context, their
family ids named. These two would be assigned to different families by any shape clustering, and they
are the ends of one continuous morph.

Produce for: the longest qualifying Reishi run, the longest qualifying Oyster run, one Reishi run with
gap drift beyond ±20%, and — new this run — **the longest qualifying Lion's mane run**, which should
now exist given the 10 Hz corpus is far larger than the retired `id385`.

## Figure S3_2 — Morph across scales

The round-11 version was "a bunch of lines" because each row was a flattened waterfall. Rebuild as a
**small-multiples catalogue in the `id385_contact.png` style**: one row per species, and within each
row a strip of that sequence's events drawn as individual small panels in time order, each with its
fall span shaded, each labelled with depth and duration, gradient-coloured by position in the sequence.

Each panel is height-to-width locked and tall enough that the drop reads as a drop. Rows ordered by
native event duration, with each row's native duration and amplitude range printed at its left.

The claim: the same slow morphing appears at time scales three orders of magnitude apart. It should be
legible without reading a single number.

## Figure S3_3 — Isolated Lion's mane events

Round 11 ran this against 76 events from `id385`. **Re-run it against the much larger 10 Hz corpus**,
where it may now find something. Same test: for consecutive event pairs closer than the species median
interval, does a shallow drop tend to precede a deeper one, against 1000 order-shuffles. If the effect
is absent, one line and no figure.

Also recompute the sequence extraction on the new store — `sequences.csv` — and report how many
qualifying Lion's mane sequences now exist against the 1 of 7 the retired corpus gave.

## Deliverables

```
Plots/drop_motifs12b/
  S2_1_fall_angle.png           (copied or regenerated unchanged)
  S2_2_scale_collapse.png       + .json
  S2_3_asymmetry.png            + .json
  S3_1_sequence_morph_<key>.png x4  + .json
  S3_2_morph_across_scales.png  + .json
  S3_3_isolated_pairs.png       (only if the effect exists)
  sequences.csv
  FIGURES.md   PROVENANCE.md
  drawing_rules.py              the shared module; every figure imports it
```

`FIGURES.md` as before: per figure, what it shows in one sentence, how it was made in at most three
sentences with every threshold named, what it supports, what it does not, and the caption. **Any
figure that cannot be explained in three sentences is flagged, not shipped.**

## Order

1. `drawing_rules.py`, and a smoke test that renders one event from each species and asserts the drawn
   height-to-width of the median event falls between 1:1 and 3:1
2. Sequence extraction on the new store
3. **S3_1** first — it exercises every drawing rule, so if it looks right the rest will
4. S2_2, then S2_3
5. S3_2
6. S3_3, dropped if the effect is absent
7. `FIGURES.md`

## Reporting

Print only: the drawn height-to-width of the median event per figure, from the smoke test; qualifying
sequence counts per species on the new store against round 11's; the median matching distance in each
direction for S2_3; duty cycle and absolute duration per species on the new store; and any figure
flagged as unexplainable in three sentences.
