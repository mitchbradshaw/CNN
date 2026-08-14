# Plots/

Saved figures, organised by the same four stages as the code. **Gitignored** —
only this README is tracked. Figures are regenerable from the code plus `DATA/`.

```
Preprocessing/
  signal/            raw recording overviews
  window_matrix/     window-matrix feature heatmaps

Detection/
  mp/profile/        matrix profile over the full signal
  mp/motifs_10min/   top-motif slideshow, 10-minute window, 10 neighbours
  mp/motifs_1min/    top-motif slideshow, 1-minute window, 10 neighbours
  mp/seeding/        seeded motif chains — seed shape and its recurrences
  wavelet/           Morse scalograms and the Dehshibi Omega(tau) energy sum
  change_point/      ruptures breakpoint detection
  entropy/           per-window entropy against window index
  frequency/         STFT log-power across all windows

Classification/
  cnn/               CNN score against signal; fusion-prediction error
  gramian/           GASF / GADF / recurrence / fusion encoding suite
  dendrogram/        linkage trees and per-cluster signal groupings

Comparison/
  category_stats/    interesting vs not-interesting: feature, frequency and
                     STFT log-power distributions
```

## Naming

Figures were saved by hand, so names are inconsistent (`Mp_seeding_1.png` vs
`mp_seeding_2_3peat.png`, and `anaylsis_dist.png` carries a typo). They were
moved verbatim rather than renamed, so anything referring to them by name in a
thesis draft still resolves. Rename freely if nothing external points at them.

## Where do new figures go?

Under the stage that produced them, in a technique subfolder. Add a new
subfolder rather than dropping files in a stage root — the mp/ series shows how
fast a flat directory stops being navigable.
