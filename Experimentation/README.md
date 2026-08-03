# Experimentation/

**Exploratory, one-off, and in-progress analysis.** Nothing here is guaranteed
to work, to keep working, or to be reusable. Nothing in `Working/` or
`Pipelines/` may import from this directory.

Code here is free to hardcode filenames, leave knobs at module level, and go
stale. That is the point — this is where you find out whether an idea is worth
promoting.

## The four stages

Same four subfolders as `Working/` and `HPC/`, named with an `experiments`
suffix:

```
Preprocessing experiments/   loading, cleaning, windowing, channel plots
Detection experiments/       spike / wavelet / change-point / motif exploration
Catalogue experiments/       clustering and classification exploration
Comparison experiments/      cross-method and cross-scale comparison
```

The folder names contain a space, so **they are deliberately not importable
packages.** Everything here is a leaf script you run directly. Each carries a
repo-root bootstrap so `Working.*` imports resolve:

```bash
python "Experimentation/Detection experiments/rupture_testing.py"
```

## Known state of what's in here

Some of these do not currently run. That is expected and recorded rather than
hidden:

- `oldtestingcode_stft.py` — references six undefined names; kept for its STFT
  power-matrix plotting approach, not because it executes.
- `aeon_testing.py` — calls an undefined `est`; scratch.
- `aeon_anomaly_detection_stub.py`, `aeon_segmentation_stub.py` — empty stubs
  that were never written.

## Promoting work out of here

When an experiment settles, split it:

- The **reusable function** moves to `Working/<Stage>/`.
- The **orchestration that calls it** becomes a `Pipelines/<workflow>/` entry
  point, or stays here as a driver if it is still one-off.

Deleting a dead experiment is fine. Leaving a dead one *without saying so* is
what causes the next person — probably you — to waste an afternoon.
