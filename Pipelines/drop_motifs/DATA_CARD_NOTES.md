# Data card notes — spike-drop motifs

Lift-and-shift material for the dataset section of the NeurIPS 2026 *Foundation Models for Temporal
Systems* submission. Structured against the fields the brief names: modalities, collection context,
sampling and duration, annotation process, preprocessing, composition and counts, known biases and
limitations, recommended and discouraged uses.

Every number below is transcribed from `DATA/derived/drop_motifs/<recording_id>/manifest.json` and
`Plots/drop_motifs/cluster_summary.json`. Nothing here is eyeballed off a figure. Where a number is
an estimate rather than a measurement it says so.

Scope note: this documents the **derived spike-drop event set**, not the parent recordings. It is
one artefact within a larger curated corpus and is written to slot into that corpus's card as a
subsection.

---

## Modalities

A single modality: extracellular bio-electric potential recorded differentially from mycelial
substrate, in volts, stored as float64 and reported throughout in millivolts. There is no imaging,
no environmental covariate stream and no behavioural channel accompanying these events.

The derived artefact adds no modality. Each event carries the raw trace, a detrended trace and an
absolute time index over the same samples.

## Collection context

Two source recordings, chosen because they differ on nearly every axis a temporal foundation model
would have to generalise across, while both containing the same nominal phenomenon — a spike.

| | Mushroom_260720 | M2_aug_concat_fs1 |
|---|---|---|
| `recordings.id` | 385 | 1 (channel 0 of 16) |
| source file | `Mushroom_260720_0509_4hrs_CH14_fs1.mat` | `M2_aug_concat_fs1.mat` |
| sampling rate | 1.0 Hz | 1.0 Hz |
| recording length | 14,401 samples (4.00 h) | 2,595,600 samples (721.0 h) |
| span analysed | the whole recording | 336.00–346.00 h (10.00 h) |
| resting potential | approx. −420 mV | approx. −440 mV |
| event amplitude | 9–14 mV | 15–47 mV |
| event fall duration | 3–47 s | 98–251 s |

`CH14` in the Mushroom filename is the hardware channel from the original acquisition; the database
`channel` column is 0 because the file was ingested as single-channel. There is one channel, not
fourteen.

The two M2 datasets in this corpus, `M2` and `M2_aug`, are **different data** — a window of one does
not match anywhere in the other. Anything citing these events must name `M2_aug` specifically.

## Annotation process

No annotation was produced by this pipeline, and none was consumed as a label. Annotations were used
in exactly two ways, both stated so that neither can be mistaken for supervision:

1. **Span selection.** The M2_aug span is read at run time from annotation id 11266, a human
   `interesting` verdict spanning 336.0–346.0 h with the note *"amplitude modulation am increasing;
   frequency modulation fm decreasing; 16 cycles; 20–70 mV"*. The span is therefore traceable to a
   human judgement rather than to a number typed into a script. Two nested child annotations exist
   over the same region (11279, "4x sharkfin sequence"; 11267, "single cycle; type specimen") and
   were not used for selection.

2. **Verification.** That annotation independently records **16 cycles**. The detector returned
   **16 drops from 16 candidate rises with zero rejections** over the same span. This is the
   strongest available external check on the detector and it was not used to tune it — the
   parameters were fixed by a sweep against detrend-window and segment-length behaviour before the
   count was compared.

Mushroom_260720 has no equivalent annotation. Its recall figures below are against a
hand-constructed reference (deep minima of the detrended trace, ≥ 4 mV, separated by ≥ 60 s) built
for this work, which is weaker evidence than a human annotation and should be described as such.

This repository keeps machine detections and human annotations in separate tables by design, and no
code path in this pipeline writes into the annotations table.

## Preprocessing applied here specifically

Applied per recording, in order. Parameter values differ between the two recordings and are **not**
harmonised; forcing a shared value would mean choosing one recording's time scale for both.

| Step | Mushroom_260720 | M2_aug 336–346 h |
|---|---|---|
| rolling-mean detrend window | 180 s | 1800 s |
| dSAX segment duration | 2 s (2 samples/symbol) | 120 s (120 samples/symbol) |
| dSAX alphabet | 3 symbols (DOWN / SAME / UP) | same |
| dSAX trend estimator | `ols_slope` | same |
| dSAX threshold mode | `quantile` | same |
| target SAME occupancy | 0.50 (observed 0.504) | 0.70 (observed 0.720) |
| learned cutlines | ±0.0081 mV per segment | ±3.577 mV per segment |
| rise-run merge gap | 1 segment | 0 segments |
| onset slope threshold | −0.0568 mV/s (6 × MAD sigma 0.00947) | −0.1849 mV/s (6 × MAD sigma 0.0308) |
| fall-end knee fraction | 0.05 | 0.05 |
| minimum depth | 0.10 × the deepest fall in the span | same |
| minimum onset separation | 120 s | 0 s (disabled) |
| stored context | 2 fall-durations before onset, 4 after the trough | same |
| random seed | 20260819 (recorded; consumed by no step in this configuration) | same |

Notes a reader needs in order to judge these:

- The detrend window is a **high-pass**. It must be long relative to noise and comparable to one
  spike. On M2_aug a 60 s window leaves 7 mV of a 63 mV excursion — it removes the event along with
  the drift; the 1800 s window leaves 40 mV.
- The dSAX segment duration is bounded above by the *rise*, not the fall. On Mushroom_260720 the
  rise preceding a drop is one to two samples — a +0.6 mV overshoot immediately before a 12 mV fall
  — so at 3 s and above it is averaged into the quiescent bin and the event stops being detectable
  by a rise-then-drop rule at all.
- `quantile` rather than the `learned` default is a deliberate departure and is the reason the
  method works on Mushroom_260720 at all; see **Known biases** below.
- No filtering, resampling, imputation or artefact rejection beyond the above. There are no missing
  samples in either analysed span.
- Normalisation is applied **only inside the clustering step** (resample to 200 points, z-normalise)
  and never to any stored array or drawn figure. This is deliberate and is discussed under
  discouraged uses.

## Composition and counts

### Detection

| | Mushroom_260720 | M2_aug 336–346 h | total |
|---|---|---|---|
| segments encoded | 7,200 | 300 | 7,500 |
| candidate rises (UP regions) | 950 | 16 | 966 |
| rises reaching the slope threshold | 109 | 16 | 125 |
| **drops confirmed** | **26** | **16** | **42** |
| rejected: no qualifying fall within lookahead | 841 | 0 | 841 |
| rejected: fall shallower than 0.10 × the deepest | 52 | 0 | 52 |
| rejected: duplicate of a deeper nearby drop | 31 | 0 | 31 |
| detection wall-clock | 0.046 s | 0.012 s | — |

The rejection profile differs sharply between the recordings and that difference is itself a
finding, not a defect. On M2_aug the rise-to-drop mapping is 1:1 and nothing is rejected. On
Mushroom_260720, 88% of candidate rises are baseline fluctuations with no fall behind them — the
recording is mostly quiet, and the 0.50 SAME occupancy needed to see the one-sample pre-drop
overshoot necessarily also admits a great many noise rises. The slope threshold, not the trend
alphabet, is what separates them.

### Measured distributions

Drop depth (onset to the foot of the steep fall), millivolts:

| | n | min | p25 | median | p75 | max | mean | sd |
|---|---|---|---|---|---|---|---|---|
| Mushroom_260720 | 26 | 1.44 | 8.78 | 9.07 | 13.20 | 14.06 | 9.79 | 3.52 |
| M2_aug | 16 | 14.61 | 21.09 | 28.56 | 38.81 | 46.50 | 30.18 | 10.23 |

Fall duration, seconds:

| | n | min | p25 | median | p75 | max | mean | sd |
|---|---|---|---|---|---|---|---|---|
| Mushroom_260720 | 26 | 3 | 5 | 5.5 | 8 | 47 | 11.23 | 12.95 |
| M2_aug | 16 | 98 | 123.75 | 176 | 196.25 | 251 | 165.50 | 44.53 |

Peak-to-peak amplitude over the stored snippet, millivolts:

| | n | min | p25 | median | p75 | max | mean | sd |
|---|---|---|---|---|---|---|---|---|
| Mushroom_260720 | 26 | 2.75 | 9.31 | 9.57 | 13.94 | 14.27 | 11.02 | 2.77 |
| M2_aug | 16 | 17.68 | 23.50 | 31.66 | 45.55 | 54.59 | 34.34 | 12.58 |

The M2_aug peak-to-peak range (17.7–54.6 mV) sits inside the human annotation's independently
recorded "20–70 mV", which is a second consistency check on the extraction.

### Fall-gradient geometry

Circular statistics over the falling edges, measured from the stored snippets. The angle is
`arctan(slope / reference)` with the reference stated — `arctan` takes a dimensionless argument and
mV/s is not one, so the reference is a documented parameter rather than an implicit 1.0.

| | n | mean angle | R | circular SD | median |
|---|---|---|---|---|---|
| **absolute steepness**, reference 1 mV/s | | | | | |
| M2_aug | 16 | −36.0° | 1.000 | 1.3° | −0.730 mV/s |
| Mushroom_260720 | 26 | −72.8° | 0.961 | 16.1° | −4.185 mV/s |
| **peakedness** (steepest ÷ own mean), reference = pooled median 3.09 | | | | | |
| M2_aug | 16 | −52.7° | 0.997 | 4.4° | 4.262 |
| Mushroom_260720 | 26 | −42.5° | 0.968 | 14.6° | 2.357 |

`R` is the mean resultant length: 0 for directions spread evenly, 1 for all identical.

Two properties worth quoting. **M2_aug's sixteen falls have R = 1.000 and a circular SD of 1.3°** —
their descent angles are identical to measurement precision, which is a stronger regularity claim
than the shape clustering supports and sits on the recording that has independent human annotation.
And **the two recordings separate on both axes in opposite directions**: Mushroom's icicles are ~6×
steeper in mV/s yet closer to a uniform cliff, M2_aug's sharkfins shallower yet far more
front-loaded. Absolute steepness and fall profile therefore carry different information about the
same events.

Uniformity is tested by KS against uniform over the reachable quadrant, **not** by a Rayleigh test:
slope angles can only occupy one quadrant, so a Rayleigh test against uniform-on-the-full-circle is
significant by construction and describes the constraint rather than the data.

### Clustering

Ward linkage on the resampled, z-normalised vectors; cophenetic correlation **0.758**; cut at k=5.

| cluster | n | composition | median depth | median fall | fall range |
|---|---|---|---|---|---|
| 1 | 7 | Mushroom 7 | 9.1 mV | 4 s | pure |
| 2 | 7 | Mushroom 7 | 8.8 mV | 5 s | pure |
| **3** | **17** | **Mushroom 9, M2_aug 8** | **14.1 mV** | **9 s** | **mixed** |
| 4 | 2 | Mushroom 2 | 1.5 mV | 41 s | pure |
| **5** | **9** | **Mushroom 1, M2_aug 8** | **37.5 mV** | **177 s** | **mixed** |

Two of five clusters mix the recordings. **Cluster 3 is the substantive result**: nine
Mushroom_260720 icicles with 5–9 s falls and eight M2_aug sharkfins with 98–195 s falls occupy the
same shape family, a duration ratio of roughly 39×. Cluster 5 mixes in the opposite direction, one
Mushroom event among eight M2_aug ones.

Roughness QC (each member against its own cluster's mean shape, threshold 2.0×):
**4.8% of events flagged as noisy** (2 of 42). Flagged events are drawn in grey rather than removed.

The unsupervised largest-merge-gap heuristic would cut this tree at k=2. That is the honest
unsupervised answer and it separates fast-shallow from slow-deep, but both k=2 clusters mix the
recordings, so the cross-dataset claim cannot be read off the picture. k=5 is an **editorial
choice** made for legibility and is flagged as one wherever it is quoted.

## Known biases and limitations

State all of these; several are consequential.

1. **The detector requires a rise, and not all real drops have one.** On Mushroom_260720 roughly
   half the visible icicles are preceded by a measurable overshoot and roughly half are not. The
   event set is therefore biased toward drops with a detectable pre-drop rise, and the recall figure
   against the hand-built reference (0.92–0.96 at the shipped parameters) should not be read as
   recall over all downward excursions.

2. **The slope threshold is learned per recording, so it is not the same physical quantity across
   the two.** −0.0568 mV/s on Mushroom_260720 and −0.1849 mV/s on M2_aug. Both are 6 robust sigmas
   of that recording's own derivative noise. This makes the criterion comparable in *meaning* and
   not in *value*, which is the right trade for a cross-dataset claim but must not be described as a
   single shared threshold.

3. **The same applies to every other parameter.** Detrend window differs 10×, segment duration 60×,
   SAME occupancy and separation both differ. Every value is recorded per run in the manifest. A
   reader should treat the two event sets as two independently parameterised extractions that are
   then compared, not as one extraction applied twice.

4. **dSAX's documented offset sensitivity applies.** The trend alphabet segments on a fixed grid, so
   shifting the analysed span by a fraction of a segment can move which segment a rise falls into
   and therefore change the symbol string. On M2_aug at 120 s segments this is a real sensitivity;
   the 16/16 agreement with the annotation is evidence that it is not currently biting, not proof
   that it cannot.

5. **`quantile` mode is not dSAX's default, and the default does not work here.** Under `learned`
   mode the SAME band is MSE-optimal against a delta distribution dominated by the rare huge drops,
   so it swallows 98–99% of segments including the whole rise, and the detector finds **zero**
   events on Mushroom_260720. Anyone reproducing this with dSAX's defaults will get nothing and
   should be told why in the paper, not left to discover it.

6. **The depth filter is relative, so it cannot be compared across spans.** A candidate is kept at
   ≥ 0.10 of the deepest fall *in the same span*. This makes one setting work across recordings
   differing 4× in amplitude, at the cost that "kept" means something slightly different in each.
   The absolute depths are all in the event table, so a reader can re-impose an absolute cut.

7. **Small clusters are near the noise floor.** Cluster 4 (n=2) has a median depth of 1.5 mV against
   a Mushroom median of 9.1 mV. It is included rather than pruned so the marginal end of the
   detection is visible, but it should not be quoted as a discovered motif family.

8. **Two recordings, two subjects, one channel each.** There is no subject-level replication, no
   device-level replication and no site-level replication in this artefact. It cannot support any
   claim that requires them. n=42 events is a demonstration, not a corpus.

9. **Temporal leakage is a live risk for any downstream split.** The 42 events come from two
   contiguous spans. Events within a span are minutes apart and share the same slow drift, the same
   electrode and the same physiological state. Any train/test split over these events must be by
   span or by recording, never by shuffling events, or the result will be inflated.

10. **The clustering z-normalises and the figures do not.** This is intentional and is the point,
    but it means a cluster label and a figure are answering different questions: the label says
    "same shape after removing scale", the figure shows the scale that was removed. Quoting a
    cluster as evidence of amplitude similarity would be wrong.

11. **No missingness, and therefore no missingness handling to document** — for these two spans. The
    parent corpus has gaps; this artefact does not exercise any of that machinery, so it provides no
    evidence about it.

12. **Every gradient angle depends on a chosen reference slope.** `arctan` needs a dimensionless
    argument, so the angles in the rose are `arctan(slope / reference)` and the reference is a
    parameter, not a fact about the data. Quoting an angle without also quoting its reference is
    meaningless. All references used are printed on the figures and stored in
    `gradient_rose_summary.json`.

13. **`onset_slope_raw` in the event table is not a good steepness measure and should not be quoted
    as one.** `np.gradient` is a central difference, so at the corner where flat meets fall it
    reports half the true gradient; combined with the onset being the first sample past the
    detection threshold on a 2 s segment grid, its Mushroom_260720 median (−0.088 mV/s) understates
    the real steepness (−4.185 mV/s) fiftyfold. The column is retained because it records what the
    detector actually triggered on. Use the max-slope figures for steepness.

## Recommended uses

- As a **demonstration that a spike sub-shape recurs and is comparable across recordings** whose
  event durations differ by ~39×. Cluster 3 is the evidence and the fall-duration-normalised overlay
  is how to show it.
- As a **stress case for temporal foundation models**: the same nominal morphology at two time
  scales two orders of magnitude apart, in a signal with strong slow drift and a resting potential
  two orders of magnitude larger than the excursions of interest.
- As a **worked preprocessing pipeline** with every parameter recorded per run and a store that
  replays into figures without re-running detection — the reproducibility property the brief asks
  for.
- As **input to scale-free / scaling-law analysis of depolarisation events**, for which the
  amplitude-preserving storage is a prerequisite.

## Discouraged uses

- **Do not train or benchmark on 42 events.** This is a demonstration set. Treat any per-cluster
  statistic as descriptive.
- **Do not treat the cluster labels as ground truth.** They come from one linkage method at one
  editorially chosen cut, on a tree with cophenetic correlation 0.758. A different method or cut
  gives different labels, and the pipeline makes trying that a one-command operation for exactly
  that reason.
- **Do not normalise amplitude before analysing scaling.** Doing so removes the evidence. The stored
  arrays are in millivolts and unnormalised precisely so this remains a choice made downstream.
- **Do not compare drop depths across the two recordings without also quoting the resting potential
  and the detrend window**, which differ.
- **Do not read the Mushroom_260720 rejection counts as false-positive rates.** 841 rises rejected
  for having no fall behind them are not errors; they are the quiet baseline being correctly
  declined.
- **Do not use this event set to claim anything about the other 15 M2_aug channels or the rest of
  the corpus.** One channel of each recording was analysed.

## Provenance and reproduction

```
Working/Detection/drop_motifs/{detect,cluster,store}.py     headless core
Pipelines/drop_motifs/run_drop_report.py                    CLI
Pipelines/drop_motifs/figures.py                            figures
DATA/derived/drop_motifs/{385,1}/                           the event store (gitignored)
Plots/drop_motifs/                                          the figures (gitignored)
```

```powershell
python Pipelines/drop_motifs/run_drop_report.py --export-all
```

Detection is deterministic: dSAX in `quantile` mode consumes no RNG, so a rerun reproduces the
identical event set without depending on the seed. The seed (20260819) is recorded regardless.

Verified against `pytest` from the repository root: 45 tests added across
`tests/test_drop_motifs_detect.py`, `tests/test_drop_motifs_store.py` and
`tests/test_drop_motifs_gradients.py`; full suite 677 passed, exit code 0, no regressions in the
pre-existing 632.
