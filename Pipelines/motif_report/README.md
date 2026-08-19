# motif_report

Report-grade motif-family figures, outside the UI.

`motif_report.py` rebuilds the Motif browser tab's dual panel (channel + occurrence markers on top,
all occurrences overlaid below) in matplotlib, weighted and scaled for a printed figure. It shares
the browser's headless core — `Working.database.matrix_profile_store` for find-or-compute of the
profile, `Working.Detection.matrix_profiling.motif_groups` for the group walk — so a scale computed
here is persisted in `runs`/`artifacts` and shows up in the app's scale ladder, and a group set
computed here is reused on the next invocation.

## Quick start

```powershell
# 1-minute scale on Mushroom_260720, interactive
python Pipelines/motif_report/motif_report.py --window-min 1

# export every family as PNG + PDF, plus the summary table
python Pipelines/motif_report/motif_report.py --window-min 1 --align peak `
    --export-all --export-dir Plots/motif_families/win1min_peakaligned
```

Navigation: `<-`/`->` or the Prev/Next buttons, the slider, or a click anywhere on the top panel to
jump to the nearest family. `t` cycles the overlay transform, `s` saves.

## The knobs that matter

| Flag | Why it exists |
|---|---|
| `--window-min` | Matrix-profile window. Missing scales are computed once and persisted. |
| `--max-distance-norm` | Neighbour cutoff in units of `sqrt(m)`. Family size becomes a finding, not a setting. Scale-portable in a way an absolute distance is not — z-normalised Euclidean distance grows as `sqrt(m)`. |
| `--min-separation-frac` | Occurrences must be this many window-lengths apart. `1.0` (the default) means non-overlapping, which is what stops one event being counted several times through slightly shifted windows. |
| `--context-frac` | Context drawn either side of the window. Non-zero by default because the profile puts the window where the *distance* is lowest, not where the event is — at 1 minute on this recording the window starts part-way down the spike. |
| `--align` | `window` is faithful to the profile; `peak` lines the events themselves up, which is what separates sub-shapes within one family. |
| `--mode` | `both` (default) shows z-normalised and raw side by side; also `znorm`, `centred`, `raw` alone. |
| `--clip` | `full` (default) shows every sample drawn. `iqr` reproduces the browser's Tukey fence, which trades a clipped transient for a legible baseline. |
| `--linewidth` | Scales every line weight together. |
| `--show-profile` | Draws the matrix profile and the cutoff on the top panel — turns the figure into an explanation of where the families came from. |

## Outputs

`--export-all` writes one PNG + PDF per family (navigation strip hidden) plus
`families_WIN{n}min_d{threshold}.csv`, one row per family: seed time, occurrence count, tightest and
loosest member distance, mean and SD of peak-to-peak amplitude in mV, and median inter-occurrence
interval.

---

# family_search.py

Seeded cross-channel search, and cross-scale comparison of the families it finds.

**This needs no matrix profile.** A profile answers "where is every subsequence's nearest
neighbour" — needed to *discover* motifs with no prior. Searching for a motif you already have is one
distance profile of one query against one series, which `stumpy.match` does by FFT in ~4 s even on a
2.6M-sample channel. On this machine's calibration a fresh whole-channel profile of M2 costs tens of
hours, so a search that required one would be unusable. It also means channels profiled at 1, 34 and
50 minutes can still be searched against each other — the seed carries its own duration.

## Seed sources

| `--seed-source` | What it is |
|---|---|
| `catalogue` | Rows of `DATA/catalogue/signal_catalog.xlsx`. The only source carrying a **shape name** (`Elements`: sharkfin, halfdome, crestedwave, ridge …), so the only one that makes a result a statement about a named family. Filter with `--element sharkfin`. |
| `annotations` | Spans with `verdict='interesting'`. Large and uniform (mostly 10-min windows from a bulk import) with no shape label — good coverage, weak taxonomy. |
| `family` | Seeds discovered by `motif_report.build_families` from a stored profile. Needs `--seed-recording` and `--window-min`. |
| `manual` | `--seed-recording --seed-start-h --seed-end-h`. |

## Usage

```powershell
# every catalogue sharkfin, searched across M2_aug CH0, CH2, CH13
python Pipelines/motif_report/family_search.py --seed-source catalogue --element sharkfin `
    --targets 1,3,14 --out-dir Plots/family_search/sharkfin --cross-scale

# families discovered from CH0's stored 10-min profile, searched everywhere
python Pipelines/motif_report/family_search.py --seed-source family `
    --seed-recording 33 --window-min 10 --targets 33,35,46
```

`--targets` is a comma-separated list of `recordings.id` to search **in**. A seed's own span is
dropped from its own channel's matches unless `--include-self`.

`--max-distance-norm` (default 0.30) is the match cutoff in units of √m, the same convention
`motif_report` uses. It is looser than the unsupervised default because a hand-picked exemplar is not
guaranteed to have anything as close to it as the tightest pair in a channel does.

## Cross-scale comparison

`--cross-scale` builds a pairwise distance matrix over the seed exemplars using
[Working/distances.py](../../Working/distances.py), and writes a dendrogram + two heatmaps:

- **scale-invariant** — resamples both spans to a common length before z-normalising, so a 20-minute
  and a 200-minute instance of the same shape can register as identical.
- **native-length minus scale-invariant** — the control. Large positive entries are exactly the pairs
  that are *the same shape at a different duration*, which is the question the figure exists to
  answer.

Distances are divided by √n so they read as RMS z-score difference per sample and stay comparable
across lengths.

## The drift trap (read this before trusting a `family` seed)

On a channel with strong slow drift — which M2 has — the **lowest** matrix-profile distances belong
to smooth monotonic drift ramps, not to events. After z-normalisation any two ramps look nearly
identical, so they are each other's perfect nearest neighbour. Unsupervised discovery then returns
drift as its top families, those families match everywhere in every channel, and a cross-scale
comparison of them reports near-zero distances. It looks like a spectacular result and means nothing.

`--min-linear-residual` (default 0.35) guards against this. It scores each seed by how much of it a
straight line does *not* explain, and lists what it rejects rather than filtering silently — on a
drifting channel the rejects *are* the profile's top families, which is the most useful thing the run
can tell you.

Measured here:

| seed set | median linear residual |
|---|---|
| top families from M2_concat's stored 10 / 34 / 50-min profiles | **0.156** |
| hand-curated catalogue exemplars | **0.819** |

13 of 15 M2_concat family seeds were rejected at 10/34/50 min.

**A second, different degeneracy the residual score does not catch:** a span that is flat baseline
plus one sharp step. A step is not a line, so it scores *high* on linear residual (0.94 was
observed), but it is still an edge detector rather than a shape and it matches everywhere. The
empirical catch for that is `--max-matches` saturation: a seed that hits the cap in **every** channel
has not found a family, it has found something ubiquitous. Those seeds are flagged inline as
`<- NON-DISCRIMINATING` and listed again in a warning at the end.

At 1 and 5 minutes on M2_concat CH0, 6 of 12 seeds survived the residual guard and 5 of those 6 were
then flagged as non-discriminating — so short windows help but do not solve it on this data. The
real fix is to detrend before computing the profile (`Adapters/preprocessing_detrend.py`), which is
an HPC job here, not a local one. Catalogue-seeded search is unaffected either way, because a
hand-picked exemplar is a real shape.

---

# seed_replicas.py

One seed, one channel, and only the matches that are **smooth replicas** rather than noise with the
same underlying trend.

## Why distance alone cannot do this

z-normalised Euclidean distance cannot tell a clean copy of a shape from a jagged span wandering
along the same trend — the noise is zero-mean, so most of it cancels in the sum of squared
differences. Measured on `cat04 crestedwave` against M2_aug CH0: among the 80 matches inside
`d/√m ≤ 0.30`, roughness varied by a factor of **16** with essentially no relationship to distance.
Matches at d=0.260 and d=0.248 sat at 13.0× and 1.6× the seed's roughness respectively. No threshold
on distance can recover this, because distance does not carry the information.

## The second axis

```
roughness(v)     = RMS first difference of the z-normalised span
roughness_ratio  = roughness(match) / roughness(seed)
```

`--max-roughness` (default 2.0) reads directly as a claim about the figure: nothing shown is more
than twice as jagged as the exemplar it is supposed to replicate. This is the complexity term from
Batista et al.'s complexity-invariant distance, used as a *filter* rather than as a correction.

## Usage

```powershell
python Pipelines/motif_report/seed_replicas.py                      # cat02 sharkfin + cat04 crestedwave
python Pipelines/motif_report/seed_replicas.py --element sharkfin --max-roughness 1.8
```

Layout: the channel across the top with kept replicas in colour and rejected ones in grey; then the
seed on its own, the kept overlay (the main panel), and a panel showing exactly what the filter
removed. The seed is drawn on the overlay **dotted and semi-transparent, behind the replicas** — a
reference line, not a competing trace.

Results on M2_aug CH0: `cat02 sharkfin` 28 matches → **13 smooth**; `cat04 crestedwave` 80 → **30
smooth**. In both cases the kept set spans nearly the full allowed distance range, confirming that
roughness and not distance did the selecting.

**Interpretation caveat:** the rejected traces mostly follow the seed's shape faithfully — they are
noisy *recordings* of the same event, not false matches. The filter selects for signal quality, not
for correctness, which is what a report figure wants but is not the same claim.

## Note on datasets

The catalogue's `DATASET` column maps to a recording family, not a file, via `DATASET_TO_SOURCE_FILE`.
`M2` and `M2_aug` are **different data** — a window of one does not match anywhere in the other — so
the mapping is explicit rather than a prefix guess. Catalogue exemplars and the `interesting`
annotations both live on `M2_aug` (recordings 1–16); the stored matrix profiles live on
`M2_concat_fs1` (recordings 33, 35, 46).
