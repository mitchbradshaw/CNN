# Claude Code prompt — drop_motifs12a: Lion's mane detection and pipeline plots

Run this first. `12b` redraws the figures against the store this run produces.

---

# PROMPT

## What this run does

Three things, and no figure redesign:

1. **Detect events in the full Lion's mane recording** at 10 Hz, over two operator-chosen regions,
   using the same sliding-window chain the Reishi corpus used.
2. **Retire `id385`** — the 1 Hz, 4 h excerpt of this same recording — and replace it with the 10 Hz
   detections, which recover the same events and more.
3. **Produce pipeline plots** — the `Plots/drop_motifs9_fig2a/example_case_studies_v3/*_01_pipeline.png`
   figure, showing every stage from raw trace to detected events — for each oyster span and for a
   seeded random selection of Reishi and Lion's mane sequences. These exist so the operator can
   confirm by eye that the detector is doing what it claims.

Read first: `Pipelines/drop_motifs/DETECTION_AND_FIGURES.md`,
`Plots/drop_motifs9_fig2a/example_case_studies_v3/README.md`, and `Plots/drop_motifs10/PROVENANCE.md`.

## Task 1 — Lion's mane, 10 Hz

**Source.** `L_LM_Jul_26_J_raw_fs10`, derived channels already on disk under
`DATA/derived/channels/<stem>/CH<n>.npy`. Channels are numbered 0–4. **Verify the stem and the
sample rate from the recordings table before anything else** and state both in the manifest; the
filename says 10 Hz and the recording spans roughly 26 days, which is consistent, but confirm rather
than assume.

**Two regions**, by sample index:

| region | channel | from | to | duration at 10 Hz |
|---|---|---|---|---|
| A | CH3 | 7.4e6 | 2.0e7 | ~350 h |
| B | CH2 | 1.376e7 | 1.71e7 | ~93 h |

`id385` (`Mushroom_260720`) is a 1 Hz excerpt of this same recording — the dates match — and region B
is believed to contain it.

**The window length is measured, not assumed. Do this before the production run.**

The two channels carry events at very different scales. On CH3 the operator measures falls of
roughly 1e4 samples — about 17 minutes. On CH2 the events are visibly narrower and much denser.
A window must be long enough that the autocorrelation can derive a sensible scale, and long enough
that an event's fall is a small fraction of it: the Reishi corpus used a 50 s window for 0.7 s falls,
a ratio of about 70:1, and an event whose fall approaches the window length cannot be framed at all.

So:

1. **Scale probe.** For each region, take three trial sub-windows at 5%, 50% and 95% through it, each
   of 2e5 samples, and run the detector over each at three candidate window lengths spanning two
   orders of magnitude. Record the fall-duration distribution found at each.
2. **Set the production window** to approximately **100× the median measured fall duration**, clamped
   to between 30× and 200×, rounded to a round number of minutes or hours.
3. **Report the probe table and the chosen window** at the top of the run report, per region. If the
   probe finds nothing at any candidate length, stop and say so rather than proceeding with a guess.

Everything else follows the Reishi run exactly: **50% overlap**, the four drop passes (`base`,
`fine`, `sens`, `micro`), no inverted pass, cross-window deduplication with the best-framed rule,
then refinement — mark relocation, within-window dedup, depth floor.

**Floor.** Derive it per region from that region's own noise, as `drop_motifs10` does, and also write
a global-floor store for comparison. Quote the floor with every count. Do not carry the 0.1 mV number
across: it is an M2-specific value, 3.1–5.3σ there but 15–58σ on the 10 Hz corpora.

**Region overview plots.** One per region, before detection: all five channels stacked over the
region, sample index on x, so the operator can see the context the events sit in. On the two analysed
channels, shade the detected events after detection and re-save. The operator's own screenshot of
region B is the model for this figure — CH2 dense narrow spikes on a drifting baseline, CH3 large
isolated drops with slow recovery, CH0/CH1/CH4 carrying no events. **Note in the manifest which
channels carry no detections**; that is a result, not an omission.

## Task 2 — Retire id385 and extend the store

Write `Plots/drop_motifs12a/motifs/`, containing:

- every oyster row from `Plots/drop_motifs10/motifs/`, unchanged — **the 15 catalogue IDs already in
  that store are the complete oyster set and no new oyster detection is needed**;
- every Reishi row from that store, unchanged;
- the new Lion's mane rows from Task 1, `species = "lionsmane"`, `corpus = "lionsmane_10hz"`;
- **not** the `sp385` rows, and **not** the `reishi_1hz` rows.

`reishi_1hz` existed only as a rate control against a 1 Hz Lion's mane corpus. With Lion's mane now
at 10 Hz it has no job, and dropping it simplifies every downstream figure. Keep both retired sets in
`drop_motifs10` where they are; this run writes a new store and modifies nothing.

**State the species map in the manifest** with each species' sampling rate, framing and event count.
Note explicitly that Reishi and Lion's mane are now both 10 Hz and both sliding-window, and that
Oyster remains 1 Hz and span-framed — so a Lion's mane/Reishi comparison is now free of the sampling
rate confound that undermined the previous cross-species result, while any comparison involving
Oyster is not.

## Task 3 — Pipeline plots

The figure is `casestudy9`'s `_01_pipeline` layout: raw window; rolling baseline and detrended trace;
the five-letter slope encoding with its noise threshold; the segment slopes against that threshold;
and the detected events shaded onset to trough. Reuse the existing plotting code rather than
rewriting it.

Produce one for:

- **each of the 15 oyster spans** — from the detections already in the store, redrawn, not re-detected;
- **3 Reishi sequences**, drawn at random from the qualifying sequences in
  `Plots/drop_motifs11/sequences.csv`;
- **3 Lion's mane sequences**, drawn the same way from the sequences found in Task 1.

**Seeded, and biased toward reuse.** Seed `20260904`. Where a sequence already appears in
`drop_motifs11`'s S3_1 or S3_2 figures, prefer it, so the pipeline plot and the morph figure show the
same events. Record the chosen sequence keys in the manifest so the same six come back on a re-run.

**Select by sample range, never by `window_index`** — a drop stored under a neighbouring window's
index is invisible to an index query, which undercounted every case-study window in an earlier run.

### Drawing rules, which apply here and in 12b

These are the corrections from the round-11 review and they are requirements.

1. **Never plot a resampled feature vector.** Every waveform drawn anywhere is real samples against
   real seconds. The 200-point z-normalised vector exists for distance computation and appears in no
   figure. Resampling a 6-sample fall to 200 points produces five straight line segments, which is
   why the round-11 figures looked flat and synthetic.
2. **Draw the whole stored snippet** — 1.2 falls before the onset and 1.8 after the trough — so the
   shoulder the fall departs from and the recovery it returns through are both visible. Never crop to
   onset→trough.
3. **Lock height-to-width.** Use `style7.span_locked_aspect` / `style7.figure_aspect` /
   `style7.apply_aspect`, which already exist and already handle the extreme-ratio cap. Target the
   median event in each figure at between **1:1 and 3:1 height-to-width**; where the true ratio
   exceeds the cap, print the true ratio in the panel label, as `overlays7` does. State the lock once
   per figure in the form `1 mV drawn as 11.3 s of width`.
4. **A drop must look like a drop.** If a panel's events render as near-horizontal lines the aspect is
   wrong, not the data.

The visual references are `Plots/drop_motifs7/id003_overlays.png` — raw signal strip on top with the
detected spans shaded and time-graded, full-context overlays beneath, height-to-width locked and
stated — and `Plots/drop_motifs5/id385_contact.png`, whose small-multiples catalogue keeps every drop
shape legible with the fall span shaded and the detrended trace faint beneath. Match those.

## Deliverables

```
Plots/drop_motifs12a/
  motifs/                       the extended store: oyster + reishi + lionsmane_10hz
  motifs_globalfloor/
  scale_probe.json              the probe table and the chosen window per region
  region_A_CH3_overview.png     five channels stacked, events shaded
  region_B_CH2_overview.png
  pipelines/oyster/id###_01_pipeline.png        x15
  pipelines/reishi/<seqkey>_01_pipeline.png     x3
  pipelines/lionsmane/<seqkey>_01_pipeline.png  x3
  manifest.json  PROVENANCE.md  run_report.json
```

## Order

1. Verify the stem and sampling rate
2. Scale probe, and report it before proceeding
3. Region overviews, pre-detection
4. Detection over both regions
5. Store assembly and the species map
6. Region overviews re-saved with events shaded
7. Pipeline plots — oyster first, since they need no new detection

## Reporting

Print only: the verified sampling rate; the scale-probe table and the chosen window per region; event
counts per region and channel under both floors, with the floor value; which channels carried no
detections; the six chosen sequence keys; and anything about the recording that contradicts the
assumption that it is one continuous 10 Hz series.
