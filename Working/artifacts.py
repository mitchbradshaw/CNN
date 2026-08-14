"""
artifacts.py
=============
Filename generation and saving for `Plots/` output — the naming convention
that makes it possible to look at any PNG and know what produced it.

Naming
------
    <recording>_CH<nn>_<stage>_<algorithm>_<paramslug>_<hash8>.<ext>

    e.g.  M2aug_CH03_prep_lowpass_fc0p05_a1b2c3d4.png

`hash8` is the recipe's short hash (`Working.recipes.short_hash`) — any
file traces back to its exact recipe via the `configs` table, regardless
of how much the human-readable part of the name had to be abbreviated or
truncated to fit. That's also what guarantees uniqueness: two recipes that
happen to abbreviate to the same `paramslug` still get different `hash8`.

Layout
------
    Plots/<Stage>/<Algorithm>/<filename>

Legacy content already under `Plots/` (from before this convention
existed) is left exactly where it is — nothing here renames or moves it.

Saving is explicit only: nothing in this module is called automatically by
`Working.execution.execute_recipe`. The UI's "Save plot" action is the only
caller (see `UI/` — Panel/matplotlib figures never get generated here,
only paths and directories).
"""

import os
import re

MAX_FILENAME_LENGTH = 200  # conservative cross-platform cap (well under both
                            # Windows' 260-char MAX_PATH and the common
                            # 255-byte single-filename limit)

STAGE_DISPLAY = {
    "preprocessing": "Preprocessing",
    "detection": "Detection",
    "catalogue": "Catalogue",
    "comparison": "Comparison",
}
_STAGE_ABBREV = {
    "preprocessing": "prep",
    "detection": "det",
    "catalogue": "cat",
    "comparison": "comp",
}

# Short tags for common parameter names, purely cosmetic (filenames stay
# unique via hash8 regardless of what this table does or doesn't cover).
_PARAM_ABBREV = {
    "cutoff_hz": "fc", "low_hz": "lo", "high_hz": "hi", "order": "ord",
    "penalty": "pen", "cost_model": "cost", "dim_ratio": "dr",
    "alphabet_size": "alpha", "max_order": "maxord", "window_min": "wmin",
    "min_spike_duration": "minspk", "min_roi_wavelet": "minroi",
    "epsilon_factor": "eps", "n_p": "np", "measure": "meas",
    "window_size": "win", "hop_size": "hop", "n_log_bins": "bins",
    "n_bins": "bins", "normalize": "norm", "min_size": "minsz",
    "jump": "jump", "width": "w", "delta": "delta", "d": "d",
    "m": "m", "tau": "tau", "J": "J", "Q": "Q", "r": "r",
}


def _slugify_recording(source_file):
    """'M2_aug_concat_fs1.mat' -> 'M2aug'; 'M2_concat_fs1.mat' -> 'M2'.

    Strips the extension and the common '_concat_fs<N>' suffix, then drops
    remaining underscores so the recording tag stays short.
    """
    stem = os.path.splitext(source_file)[0]
    stem = re.sub(r"_concat_fs\d+(\.\d+)?$", "", stem)
    return stem.replace("_", "")


def _format_value(value):
    """Filesystem-safe rendering of one parameter value: no dots, slashes,
    or spaces — 'p' stands in for a decimal point, '-' becomes 'neg'."""
    s = str(value)
    s = s.replace(".", "p").replace("-", "neg")
    return re.sub(r"[^a-zA-Z0-9]", "", s)


def paramslug(params, max_params=3):
    """2-3 most salient params (the first `max_params` in the adapter's own
    declared order — presumed most-important-first) as a filesystem-safe
    slug, e.g. {"cutoff_hz": 0.05, "order": 4} -> "fc0p05_ord4"."""
    parts = []
    for name, value in list(params.items())[:max_params]:
        tag = _PARAM_ABBREV.get(name, name[:4])
        parts.append(f"{tag}{_format_value(value)}")
    return "_".join(parts) if parts else "default"


def build_artifact_filename(source_file, channel, stage, algorithm, params, hash8, ext):
    """Build `<recording>_CH<nn>_<stage>_<algorithm>_<paramslug>_<hash8>.<ext>`,
    truncating the human-readable middle (never the hash8 suffix, which is
    what actually guarantees uniqueness) if the full name would exceed
    `MAX_FILENAME_LENGTH`.
    """
    rec_slug = _slugify_recording(source_file)
    ch_slug = f"CH{int(channel):02d}"
    stage_slug = _STAGE_ABBREV.get(stage, stage[:4])
    algo_slug = algorithm.split(".")[-1]
    p_slug = paramslug(params)
    ext = ext.lstrip(".")

    suffix = f"_{hash8}.{ext}"
    prefix = f"{rec_slug}_{ch_slug}_{stage_slug}_{algo_slug}_{p_slug}"
    full = prefix + suffix
    if len(full) <= MAX_FILENAME_LENGTH:
        return full

    keep = MAX_FILENAME_LENGTH - len(suffix)
    if keep < 1:
        # Pathological case (absurdly long hash/ext) — hash8 alone still
        # uniquely identifies the file.
        return suffix.lstrip("_")
    return prefix[:keep] + suffix


def build_artifact_path(source_file, channel, stage, algorithm, params, hash8, ext, root="Plots"):
    """Full path: `Plots/<Stage>/<Algorithm>/<filename>`."""
    filename = build_artifact_filename(source_file, channel, stage, algorithm, params, hash8, ext)
    stage_dir = STAGE_DISPLAY.get(stage, stage.capitalize())
    algo_dir = algorithm.split(".")[-1]
    return os.path.join(root, stage_dir, algo_dir, filename)


def save_plot(fig, source_file, channel, stage, algorithm, params, hash8, root="Plots"):
    """Save a matplotlib Figure using the naming convention above. Explicit
    call only — never invoked automatically by `execute_recipe`.

    Returns the path the figure was written to (relative to `root`'s
    caller — typically the repo root).
    """
    path = build_artifact_path(source_file, channel, stage, algorithm, params, hash8, "png", root=root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return path
