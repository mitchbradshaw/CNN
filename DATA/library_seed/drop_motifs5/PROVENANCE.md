# drop_motifs5 — provenance

**This bundle cannot be regenerated. Treat it as source data, not as output.**

## What it is

410 individual drop motifs (rise-then-fall depolarisation events) extracted from 16 catalogued
spans across 7 channels of two recordings. It is the seed data for the motif library
(`motif_entry` / `motif_member` / `motif_edge`), which is otherwise empty.

| File | What it holds |
|---|---|
| `motifs/events.csv` | One row per motif — 36 columns: identity, provenance, morphology, geometry, QC |
| `motifs/snippets.npz` | Three arrays per motif, keyed `<event_id>__raw_mv`, `__detrended_mv`, `__t_s` |
| `motifs/manifest.json` | `kind: drop_motifs5`, counts, and the per-span breakdown |
| `AUTODERIVE_REPORT.md` | How every detector parameter was derived from the signal, graded per span |
| `autoderive_summary.json` | The machine-readable form of that report |
| `figure_index.json` | Index of the figures in `Plots/drop_motifs5/` (left in place; 17 MB of PNGs) |

## Why it is tracked when the rest of `DATA/` is not

The code that produced it is **gone**. `AUTODERIVE_REPORT.md` names its generator as
`Pipelines/drop_motifs/run_drop5_report.py`; that file and its 5-series modules (`report5.py`,
`clusterfigs5.py`, `spans5.py`, `overlays5.py`, `figures5.py`, `figuresets5.py`) were never
committed to git. Commit `5b7f1fa` ("T48: remove bespoke importers and superseded motif path")
deleted the directory, taking the uncommitted files with it. Only compiled bytecode survives, in
`Pipelines/drop_motifs/__pycache__/*.pyc` — decompilable in principle, and the only remaining
record of the derivation.

The bundle previously lived at `Plots/drop_motifs5/motifs/`, under the blanket `Plots/*` ignore
rule whose stated rationale is "large binaries / regenerable". Neither half of that applies here,
and a scratch directory is where a future cleanup ticket would reasonably look for things to
delete. Moved here 2026-08-27 and re-included via a `!DATA/library_seed/` negation in `.gitignore`.

## Shape of the data

Ordered in 16 contiguous blocks, one per span, in this order:

    id001×17  id003×16  id008×4   id010×84  id020×4   id021×14  id022×24  id024×40
    id025×26  id026×2   id028×19  id029×48  id033×30  id034×40  id035×18  id385×24

Two facts that matter for grouping:

- **`span_key` is provenance and is already exact.** Each span is morphologically pure — every span
  is all-`sharkfin` or all-`trough` — so grouping by `span_key` yields 16 families for free.
- **`cluster_id` is `-1` on all 410 rows.** That is not lost ordering; it means *shape* clustering
  was never run. Shape families are computed, by
  `Working/Detection/drop_motifs/cluster.py` (Ward linkage on resampled, z-normalised vectors via
  `Working.distances.scale_invariant_distance`), and are a different axis from provenance.

Totals: 254 `trough` / 156 `sharkfin`; 362 `is_pure` / 48 impure.

## One rule for anything that renders these

Cluster on z-normalised vectors; **draw in millivolts, unnormalised**. `cluster.py` states the
reason and it is the project's own submission language: "normalisation of amplitude destroys the
evidence of scaling laws for depolarisation events". The maths normalises so that "same shape" has
a definition; the figure must not, so that the scaling stays visible.

## Filenames

`motifs.csv` / `motifs.npz` as generated were renamed to `events.csv` / `snippets.npz` on 2026-08-27
so that `Working.Detection.drop_motifs.store.load_run` reads this bundle with no code change — its
`EVENTS_FILENAME` / `SNIPPETS_FILENAME` contract. Nothing else was touched. Verified: 410 events,
410 snippet triples, `event_id` keys align, and `cluster.cluster_events` clusters the pooled set.
