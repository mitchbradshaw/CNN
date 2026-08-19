"""
motif_report.py
=================
Report-grade, UI-free rebuild of the Motif browser's dual panel (full
channel with occurrence markers on top, all occurrences overlaid below).

Same headless core as the Panel tab -- `Working.database.matrix_profile_store`
for find-or-compute of the profile, `Working.Detection.matrix_profiling.
motif_groups` for the seed-and-exclude group walk, both persisted in the
existing `runs`/`artifacts`/`detections` tables so nothing is recomputed on
a second invocation. Only the rendering is different: matplotlib, sized and
weighted for a printed figure rather than a browser pane.

What this adds over the browser (all requested for the report):

1. Weights are set for print. `--linewidth` scales every trace together;
   the defaults are roughly 3x the browser's.

2. The overlay's y-axis shows the WHOLE occurrence. The browser fences the
   axis with a Tukey IQR rule (`UI/plots.build_motif_waveform_overlay`),
   which keeps the baseline legible on screen at the cost of clipping
   exactly the transient a spiking-families argument is about. Here the
   limits come from the true min/max of what is drawn, with a 6% pad, so
   nothing is cut. `--clip iqr` restores the browser's behaviour.

3. Normalised and non-normalised views of the same group, side by side
   (`--mode both`, the default) or one at a time. Three transforms:
     znorm    (x - mu) / sigma   -- shape only; what the matrix profile
                                    itself compares, so this is the view
                                    in which "same motif" is literally true
     centred  x - mu             -- shape AND relative amplitude, with the
                                    slow DC drift removed. Usually the most
                                    informative for comparing spike sizes
                                    within a family
     raw      x                  -- untouched, in mV; occurrences separate
                                    vertically by whatever the baseline was
                                    doing at the time

4. Neighbours are selected by a DISTANCE THRESHOLD, not a fixed count. A
   family is "every subsequence within `d` of the seed", so its size is a
   finding rather than a setting. The threshold is given in units of
   sqrt(m) (`--max-distance-norm`, default 0.10) because z-normalised
   Euclidean distance grows as sqrt(m): the same absolute number means
   different things at 1, 3 and 10 minutes, whereas d/sqrt(m) is roughly
   comparable across scales (it is bounded by 2, and is the RMS z-score
   difference per sample). `--max-distance` sets it absolutely instead.

   The group walk stops where mp[seed] exceeds the threshold -- past that
   point a seed has no neighbour inside it, so every remaining group would
   be a singleton.

5. `--window-min` picks the scale; anything missing is computed once
   through `execute_recipe` and persisted as a normal `artifacts` row, so
   it is reused here AND becomes visible in the app's scale ladder.

Navigation: Prev/Next buttons, left/right arrow keys, a slider, or a click
anywhere on the top panel to jump to the nearest group. `t` cycles the
transform, `s` saves the current figure.

Examples
--------
    # 3-minute scale, interactive
    python Pipelines/motif_report/motif_report.py --window-min 3

    # 1-minute scale, tighter families, export every group for the report
    python Pipelines/motif_report/motif_report.py --window-min 1 \
        --max-distance-norm 0.06 --export-all --export-dir Plots/motifs_1min
"""

import argparse
import csv
import os
import sys

import numpy as np

# -- Repo-root bootstrap --------------------------------------------------
# Same pattern as `Pipelines/matrix_profile/run_matrix_profile.py`: walk up
# to the directory holding Working/ so this survives being moved or being
# run from anywhere.
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Working.database.schema import init_db
from Working.database import matrix_profile_store as store
from Working.Detection.matrix_profiling import motif_groups as mg


# -- Defaults -------------------------------------------------------------

DEFAULT_RECORDING = "Mushroom_260720"

# Threshold in units of sqrt(m). Measured on Mushroom_260720 CH14: the 5th
# percentile of the profile sits near 0.04 at BOTH the 1- and 3-minute
# scales and 0.086 at 10 -- i.e. this quantity really is roughly portable
# across window lengths, which an absolute distance is not. 0.10 lands
# between the 10th and 25th percentile at the short scales: tight enough
# that a family is visibly one shape, loose enough to have members.
DEFAULT_MAX_DISTANCE_NORM = 0.10

# Safety cap on how many neighbours one group may draw. Not a modelling
# choice -- purely a guard against a loose threshold producing a group with
# thousands of members and a figure that takes minutes to render.
DEFAULT_MAX_MATCHES = 200

# How far down `argsort(mp)` the group walk may go. The walk stops early at
# the threshold anyway (see module docstring); this only bounds the cost of
# the case where the threshold admits a great many families.
DEFAULT_MAX_MOTIFS = 80

SEED_COLOR = "#111111"
CYCLE_PALETTE = [
    "tomato", "steelblue", "mediumseagreen", "darkorange", "mediumpurple",
    "deeppink", "teal", "goldenrod", "coral", "slategray",
]

TRANSFORM_LABELS = {
    "znorm": "z-normalised   (x - mean) / std",
    "centred": "mean-centred   (x - mean)",
    "raw": "raw, untransformed",
}
TRANSFORM_YLABEL = {
    "znorm": "z-score",
    "centred": "amplitude (mV, centred)",
    "raw": "amplitude (mV)",
}
MODE_CYCLE = ["both", "znorm", "centred", "raw"]


# =========================================================================
#  Headless core -- nothing below imports matplotlib until the Figure part
# =========================================================================

def resolve_recording(conn, recording_id=None, source_file=None, channel=None):
    """Find one `recordings` row by id, or by a case-insensitive substring
    of `source_file` (+ optional channel). Raises with the candidate list
    rather than picking one silently when a substring is ambiguous."""
    if recording_id is not None:
        row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if row is None:
            raise SystemExit(f"No recording with id={recording_id}.")
        return row

    rows = [r for r in conn.execute("SELECT * FROM recordings")
            if source_file.lower() in r["source_file"].lower()]
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    if not rows:
        raise SystemExit(f"No recording matching {source_file!r}"
                         + (f" channel {channel}" if channel is not None else "") + ".")
    if len(rows) > 1:
        listing = "\n".join(f"  id={r['id']}  {r['source_file']}  CH{r['channel']:02d}" for r in rows)
        raise SystemExit(f"{source_file!r} matches several recordings -- pass --recording-id:\n{listing}")
    return rows[0]


def ensure_matrix_profile(conn, recording, window_min, *, backend="auto", force=False, verbose=True):
    """Return the stored MP artifact row for (recording, window_min),
    computing and persisting it first if it is missing or stale.

    Goes through `execute_recipe` rather than calling stumpy directly, so
    the profile lands in `runs` + `artifacts` in the v2 format the rest of
    the app already reads -- a scale computed here is immediately available
    to the Motif browser tab, and to the next invocation of this script.
    """
    if not force:
        hit = store.find_mp(conn, recording["id"], window_min)
        if hit is not None and not hit["stale"]:
            if verbose:
                print(f"  window_min={window_min:g}: reusing run_id={hit['run_id']} "
                      f"(m={hit['m']} samples, backend={hit['backend']})")
            return hit

    from Working.recipes import make_recipe
    from Working.execution import execute_recipe

    if verbose:
        m = int(round(window_min * 60 * recording["fs"]))
        print(f"  window_min={window_min:g}: computing (m={m} samples, "
              f"n={recording['n_samples']}) ...")
    recipe = make_recipe(recording["id"], [{
        "stage": "detection", "algorithm": "matrix_profile",
        "params": {"window_min": float(window_min), "backend": backend},
    }])
    execute_recipe(recipe, force=force)

    hit = store.find_mp(conn, recording["id"], window_min)
    if hit is None:
        raise SystemExit(f"Computed window_min={window_min} but no artifact was registered.")
    if verbose:
        print(f"  window_min={window_min:g}: stored as run_id={hit['run_id']} "
              f"-> {hit['artifact_path']}")
    return hit


def load_scale(conn, recording, window_min, **kwargs):
    """Everything one scale needs to render: the channel, its profile, the
    window length, and the run the profile belongs to."""
    hit = ensure_matrix_profile(conn, recording, window_min, **kwargs)
    data = store.load_mp(hit["artifact_path"], mmap=False)
    x = np.asarray(np.load(recording["npy_path"], mmap_mode="r"), dtype=np.float64)
    return {
        "x": x,
        "mp": np.asarray(data["mp"], dtype=np.float64),
        "m": int(data["m"]),
        "fs": float(data["fs"]),
        "run_id": hit["run_id"],
        "window_min": float(window_min),
        "recording": recording,
        "artifact_path": hit["artifact_path"],
    }


def resolve_threshold(m, *, max_distance=None, max_distance_norm=None):
    """The absolute z-normalised Euclidean cutoff to hand `stumpy.match`.

    Exactly one of the two knobs decides it; `max_distance` wins if both
    are given. Rounded to 6dp because this value is part of the persisted
    group-set key (`motif_groups.find_motif_group_set` matches it with `==`
    through a JSON round-trip), so an unrounded float risks recomputing a
    set that already exists.
    """
    if max_distance is not None:
        return round(float(max_distance), 6)
    norm = DEFAULT_MAX_DISTANCE_NORM if max_distance_norm is None else float(max_distance_norm)
    return round(norm * float(np.sqrt(m)), 6)


def build_families(conn, scale, *, threshold, max_matches=DEFAULT_MAX_MATCHES,
                   max_motifs=DEFAULT_MAX_MOTIFS, min_neighbours=1, min_separation=None,
                   cache=True, force=False, verbose=True):
    """Motif groups for `scale`, keeping only those that are genuinely
    families under `threshold`.

    `motif_groups.build_motif_groups` walks `argsort(mp)` ascending, so
    every seed with `mp[seed] <= threshold` is visited before any seed
    whose nearest neighbour lies outside the threshold. Truncating there is
    therefore exact, not a heuristic -- and it is done HERE rather than
    inside the walk so the persisted group set stays keyed by its declared
    parameters and remains reusable at a tighter threshold.

    Returns `(families, truncated)`. `truncated` is True when the walk hit
    `max_motifs` while still inside the threshold, i.e. there are more
    families to be had at a larger `--max-motifs`.
    """
    if cache:
        groups, reused = mg.get_or_build_motif_groups(
            conn, scale["run_id"], scale["x"], scale["mp"], scale["m"],
            n_neighbors=max_matches, max_motifs=max_motifs,
            max_distance=threshold, force=force,
        )
        if verbose:
            source = "reused from the database" if reused else "computed and stored"
            print(f"  group set: {len(groups)} raw groups ({source})")
    else:
        groups = mg.build_motif_groups(
            scale["x"], scale["mp"], scale["m"],
            max_motifs=max_motifs, n_neighbors=max_matches, max_distance=threshold,
        )
        if verbose:
            print(f"  group set: {len(groups)} raw groups (not cached)")

    inside = [g for g in groups if g["mp_distance"] <= threshold]
    truncated = len(inside) == len(groups) and len(groups) >= max_motifs

    sep = scale["m"] if min_separation is None else int(min_separation)
    before = sum(len(g["neighbours"]) for g in inside)
    deduped = [enforce_separation(g, scale["m"], sep) for g in inside]
    after = sum(len(g["neighbours"]) for g in deduped)
    families = [g for g in deduped if len(g["neighbours"]) >= min_neighbours]

    if verbose:
        norm = threshold / float(np.sqrt(scale["m"]))
        if sep > 0 and before != after:
            print(f"  separation >= {sep} samples: dropped {before - after} of {before} "
                  "neighbours as overlapping windows on an already-counted event")
        print(f"  {len(families)} families within d <= {threshold:.4f} "
              f"(= {norm:.4f} x sqrt(m)), each with >= {min_neighbours} neighbour(s)")
        if truncated:
            print(f"  NOTE: hit --max-motifs={max_motifs} while still inside the "
                  "threshold; raise it to see more families.")
    return families, truncated


def occurrences(family):
    """(index, distance) for the seed then every neighbour, closest first.
    The seed's distance to itself is 0 by definition."""
    return [(int(family["seed_idx"]), 0.0)] + [(int(i), float(d)) for i, d in family["neighbours"]]


def enforce_separation(family, m, min_separation):
    """Drop neighbours that overlap an occurrence already kept.

    `stumpy.match` only guarantees its matches are `m/4` apart (its own
    exclusion-zone default), and `build_motif_groups` excludes a returned
    neighbour from being a future SEED without excluding it from being a
    future neighbour of the same seed. Two windows 45 samples apart on a
    600-sample-wide event are therefore both returned, both draw as
    near-identical traces, and both count towards "n occurrences" -- which
    is how a family of six distinct events reports eleven members and a
    neighbour at d=0.000 that is really the seed's own event seen through
    a slightly shifted window.

    Greedy over distance (closest first, seed always kept), so what
    survives is the best-matching window on each distinct event.
    """
    if min_separation <= 0:
        return family
    kept_idx = [int(family["seed_idx"])]
    kept_nb = []
    for idx, dist in family["neighbours"]:
        idx = int(idx)
        if all(abs(idx - k) >= min_separation for k in kept_idx):
            kept_idx.append(idx)
            kept_nb.append((idx, float(dist)))
    out = dict(family)
    out["neighbours"] = kept_nb
    return out


def family_summary(families, scale):
    """One row per family -- the numbers a report needs to quote (when, how
    many, how tight, how big, how often)."""
    x, m, fs = scale["x"], scale["m"], scale["fs"]
    rows = []
    for rank, fam in enumerate(families, start=1):
        occ = occurrences(fam)
        dists = [d for _, d in occ[1:]]
        spans = [x[i:i + m] for i, _ in occ if i + m <= len(x)]
        amplitudes = [float(np.ptp(s)) * 1000.0 for s in spans]
        gaps = np.diff(sorted(i for i, _ in occ)) / fs
        rows.append({
            "rank": rank,
            "seed_idx": int(fam["seed_idx"]),
            "seed_time_s": fam["seed_idx"] / fs,
            "seed_time_h": fam["seed_idx"] / fs / 3600.0,
            "mp_distance": float(fam["mp_distance"]),
            "mp_distance_norm": float(fam["mp_distance"]) / float(np.sqrt(m)),
            "n_occurrences": len(occ),
            "max_member_distance": max(dists) if dists else 0.0,
            "mean_member_distance": float(np.mean(dists)) if dists else 0.0,
            "mean_peak_to_peak_mV": float(np.mean(amplitudes)) if amplitudes else float("nan"),
            "std_peak_to_peak_mV": float(np.std(amplitudes)) if amplitudes else float("nan"),
            "median_inter_occurrence_s": float(np.median(gaps)) if len(gaps) else float("nan"),
        })
    return rows


def write_summary_csv(rows, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["rank"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


# -- Extraction and transforms --------------------------------------------

def extract_occurrence(x, idx, m, *, pad=0, align="window"):
    """Pull one occurrence out of the channel, with `pad` samples of
    context on each side, as `(offsets, values, stats)`.

    Context matters more here than it looks. A matrix-profile window lands
    wherever the profile put it, not where the event is: on this recording
    the 1-minute motif starts part-way DOWN the spike, so a plot of the
    bare window shows the recovery and cuts the depolarisation off the left
    edge entirely. Padding shows the event whole while keeping the window
    itself marked, so what the profile actually compared stays visible.

    `align`:
      "window" -- t=0 is the window start (faithful to the profile).
      "peak"   -- t=0 is the window's largest excursion from its own mean.
                  Lines up the events themselves, which is what you want
                  when comparing one family's mean against another's.

    Out-of-range context comes back as NaN rather than being dropped, so
    every occurrence has the same length and offsets and can be stacked
    into a mean/SD envelope.

    `stats` is `(mean, std)` computed over the WINDOW only, never over the
    padded region -- those are the statistics the z-normalised distance was
    computed with, so normalising by anything else would draw a shape the
    reported distance does not describe.
    """
    window = np.asarray(x[idx:idx + m], dtype=np.float64)
    stats = (float(window.mean()), float(window.std())) if len(window) else (0.0, 0.0)

    length = m + 2 * pad
    if align == "peak" and len(window):
        anchor = idx + int(np.argmax(np.abs(window - stats[0])))
        start = anchor - length // 2
        offsets = np.arange(length) - length // 2
    else:
        start = idx - pad
        offsets = np.arange(length) - pad

    values = np.full(length, np.nan, dtype=np.float64)
    lo, hi = max(start, 0), min(start + length, len(x))
    if hi > lo:
        values[lo - start:hi - start] = np.asarray(x[lo:hi], dtype=np.float64)
    return offsets, values, stats


def transform_snippet(values, mode, stats):
    """Apply one display transform. `values` is in volts; every mode except
    `znorm` returns mV, so the non-normalised views are readable at the
    scale this data actually has (tens of microvolts of structure on a
    ~-420 mV baseline). `stats` comes from `extract_occurrence` -- see
    there for why it is the window's, not the padded trace's."""
    mean, std = stats
    if mode == "znorm":
        return (values - mean) / std if std > 0 else values - mean
    if mode == "centred":
        return (values - mean) * 1000.0
    return values * 1000.0


def _iqr_limits(values, k=3.0):
    """The browser's Tukey fence, kept available behind `--clip iqr` so the
    two framings can be compared rather than one silently replacing the
    other."""
    full = (float(np.nanmin(values)), float(np.nanmax(values)))
    q1, q3 = np.nanpercentile(values, [25, 75])
    iqr = q3 - q1
    if iqr <= 0:
        return full
    lo = max(q1 - k * iqr, full[0])
    hi = min(q3 + k * iqr, full[1])
    return full if hi <= lo else (lo, hi)


def overlay_limits(stacked, clip="full", pad=0.06):
    """y-limits for an overlay panel. `full` (the default) shows every
    sample that is drawn -- this is the fix for the browser's clipped
    transients. NaN-tolerant, since padded context runs off the ends of
    the channel."""
    values = np.concatenate([np.asarray(v).ravel() for v in stacked])
    if not np.any(np.isfinite(values)):
        return -1.0, 1.0
    lo, hi = (_iqr_limits(values) if clip == "iqr"
              else (float(np.nanmin(values)), float(np.nanmax(values))))
    span = hi - lo
    margin = span * pad if span > 0 else 1.0
    return lo - margin, hi + margin


def time_axis(n_samples, fs):
    """(values, label, divisor) for a whole-channel x-axis, in whichever
    unit keeps the tick labels short."""
    seconds = n_samples / fs
    if seconds >= 2 * 3600:
        return np.arange(n_samples) / fs / 3600.0, "time (hours)", 3600.0
    if seconds >= 300:
        return np.arange(n_samples) / fs / 60.0, "time (minutes)", 60.0
    return np.arange(n_samples) / fs, "time (s)", 1.0


def window_axis(offsets, fs, align="window"):
    """(values, label) for the within-window x-axis, given sample offsets
    relative to whatever `align` anchored on."""
    anchor = "window start" if align == "window" else "peak"
    if (offsets[-1] - offsets[0]) / fs >= 300:
        return offsets / fs / 60.0, f"time from {anchor} (minutes)"
    return offsets / fs, f"time from {anchor} (s)"


# =========================================================================
#  Figure
# =========================================================================

def _apply_report_style(lw_scale, font_scale):
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.linewidth": 1.1 * lw_scale,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.7,
        "axes.titlesize": 13 * font_scale,
        "axes.labelsize": 12 * font_scale,
        "xtick.labelsize": 11 * font_scale,
        "ytick.labelsize": 11 * font_scale,
        "legend.fontsize": 9 * font_scale,
        "font.size": 11 * font_scale,
        "savefig.facecolor": "white",
        "savefig.bbox": "standard",
    })


class MotifFamilyFigure:
    """The two-panel figure and its navigation.

    One instance owns one scale's families and redraws in place as the
    group index or transform changes -- axes are cleared and repopulated
    rather than rebuilt, except when switching between the one-panel and
    two-panel bottom layouts, which genuinely needs different axes.
    """

    def __init__(self, scale, families, *, mode="both", clip="full", lw_scale=1.0,
                 font_scale=1.0, colour_by="distance", figsize=(17.0, 9.5),
                 threshold=None, max_legend=14, show_envelope=True,
                 context_frac=0.5, align="window", show_profile=False):
        import matplotlib.pyplot as plt

        _apply_report_style(lw_scale, font_scale)

        self.scale = scale
        self.families = families
        self.mode = mode
        self.clip = clip
        self.lw = lw_scale
        self.colour_by = colour_by
        self.threshold = threshold
        self.max_legend = max_legend
        self.show_envelope = show_envelope
        self.show_profile = show_profile
        self.align = align
        self.pad = int(round(max(context_frac, 0.0) * scale["m"]))
        self.index = 0
        self._widgets = []          # kept alive; matplotlib widgets are weakly held
        self._control_axes = []     # hidden while saving, so exports are report-clean
        self._colorbar = None
        self._ax_profile = None
        self._bottom_axes = []
        self._bottom_kind = None

        x, fs = scale["x"], scale["fs"]
        self.t_full, self.t_label, self.t_div = time_axis(len(x), fs)
        self.x_mv = x * 1000.0
        self.offsets = np.arange(scale["m"] + 2 * self.pad) - (
            self.pad if align == "window" else (scale["m"] + 2 * self.pad) // 2)
        self.t_win, self.win_label = window_axis(self.offsets, fs, align)

        self.fig = plt.figure(figsize=figsize)
        self.ax_sig = self.fig.add_axes([0.055, 0.615, 0.905, 0.305])
        self._build_controls()
        self.draw()

    # -- layout ----------------------------------------------------------

    def _panel_modes(self):
        """Which transform(s) the bottom row shows, left to right."""
        return ["znorm", "raw"] if self.mode == "both" else [self.mode]

    def _ensure_bottom_axes(self):
        """Create the bottom axes if the layout kind changed. `single`
        leaves room on the right for an outside legend; `pair` splits the
        same strip and puts the legend to the right of the second panel."""
        kind = "pair" if self.mode == "both" else "single"
        if kind == self._bottom_kind:
            return
        for ax in self._bottom_axes:
            ax.remove()
        if self._colorbar is not None:
            self._colorbar.ax.remove()
            self._colorbar = None
        if kind == "pair":
            self._bottom_axes = [
                self.fig.add_axes([0.055, 0.175, 0.355, 0.345]),
                self.fig.add_axes([0.475, 0.175, 0.355, 0.345]),
            ]
        else:
            self._bottom_axes = [self.fig.add_axes([0.055, 0.175, 0.775, 0.345])]
        self._bottom_kind = kind

    def _build_controls(self):
        from matplotlib.widgets import Button, RadioButtons, Slider

        n = len(self.families)
        ax_prev = self.fig.add_axes([0.055, 0.045, 0.075, 0.045])
        ax_next = self.fig.add_axes([0.755, 0.045, 0.075, 0.045])
        # Left edge clears the Prev button (which ends at 0.130) by enough
        # for the Slider's own label, which matplotlib draws to the LEFT of
        # the axes and which otherwise prints on top of the button.
        ax_slider = self.fig.add_axes([0.225, 0.058, 0.485, 0.022])
        ax_radio = self.fig.add_axes([0.855, 0.020, 0.115, 0.105])
        ax_radio.set_title("overlay", fontsize=9, pad=3)

        self.btn_prev = Button(ax_prev, "< Prev")
        self.btn_next = Button(ax_next, "Next >")
        self.slider = Slider(ax_slider, "family", 1, max(n, 1), valinit=1, valstep=1)
        self.radio = RadioButtons(ax_radio, MODE_CYCLE, active=MODE_CYCLE.index(self.mode))

        self.btn_prev.on_clicked(lambda _e: self.step(-1))
        self.btn_next.on_clicked(lambda _e: self.step(+1))
        self.slider.on_changed(self._on_slider)
        self.radio.on_clicked(self._on_radio)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self._widgets = [self.btn_prev, self.btn_next, self.slider, self.radio]
        self._control_axes = [ax_prev, ax_next, ax_slider, ax_radio]

    # -- colours ---------------------------------------------------------

    def _colours(self, occ):
        """Per-occurrence colour. `distance` (the default) maps neighbour
        distance through a colormap, so how close a member is to the seed
        is readable off the figure itself rather than only off the legend
        -- which matters once a threshold admits more members than a
        10-colour cycle can distinguish. Returns (colours, norm_or_None)."""
        import matplotlib as mpl

        if self.colour_by != "distance" or len(occ) < 3:
            return [SEED_COLOR if k == 0 else CYCLE_PALETTE[(k - 1) % len(CYCLE_PALETTE)]
                    for k in range(len(occ))], None

        dists = np.array([d for _, d in occ[1:]], dtype=float)
        hi = self.threshold if self.threshold is not None else float(dists.max())
        norm = mpl.colors.Normalize(vmin=0.0, vmax=max(hi, float(dists.max()), 1e-9))
        cmap = mpl.colormaps["viridis"]
        return [SEED_COLOR] + [cmap(norm(d)) for d in dists], norm

    # -- drawing ---------------------------------------------------------

    def draw(self):
        import matplotlib as mpl

        if not self.families:
            self.ax_sig.clear()
            self.ax_sig.text(0.5, 0.5, "No families at this threshold.",
                             ha="center", va="center", transform=self.ax_sig.transAxes)
            self.fig.canvas.draw_idle()
            return

        self._ensure_bottom_axes()
        fam = self.families[self.index]
        occ = occurrences(fam)
        colours, norm = self._colours(occ)
        m, fs, x = self.scale["m"], self.scale["fs"], self.scale["x"]
        rec = self.scale["recording"]

        # -- top: whole channel + occurrence spans ------------------------
        ax = self.ax_sig
        ax.clear()
        ax.plot(self.t_full, self.x_mv, linewidth=0.9 * self.lw, color="#3b5f8a", alpha=0.85)
        lo, hi = float(self.x_mv.min()), float(self.x_mv.max())
        span = hi - lo
        width = m / fs / self.t_div
        for k, (idx, _d) in enumerate(occ):
            t0 = idx / fs / self.t_div
            is_seed = k == 0
            ax.add_patch(mpl.patches.Rectangle(
                (t0, lo), width, span, facecolor=colours[k], edgecolor=colours[k],
                linewidth=(1.6 if is_seed else 0.8) * self.lw,
                alpha=(0.55 if is_seed else 0.30), zorder=2))
            ax.plot([t0 + width / 2.0], [hi + 0.055 * span], marker="v",
                    markersize=(12 if is_seed else 8) * self.lw,
                    color=colours[k], markeredgewidth=0, zorder=5)
        ax.set_ylim(lo - 0.03 * span, hi + 0.14 * span)
        ax.set_xlim(self.t_full[0], self.t_full[-1])
        ax.set_xlabel(self.t_label)
        ax.set_ylabel("amplitude (mV)")

        # Optional: the profile itself behind the channel, with the cutoff
        # drawn on it -- turns the figure into an explanation of WHERE the
        # families came from, which is what a methods section needs.
        if self._ax_profile is not None:
            self._ax_profile.remove()
            self._ax_profile = None
        if self.show_profile:
            axp = ax.twinx()
            mp = self.scale["mp"]
            axp.plot(self.t_full[:len(mp)], mp, color="#d1741f", linewidth=1.0 * self.lw,
                     alpha=0.65, zorder=1)
            if self.threshold is not None:
                axp.axhline(self.threshold, color="#d1741f", linewidth=1.4 * self.lw,
                            linestyle="--", alpha=0.9)
                axp.text(self.t_full[-1], self.threshold, f" d={self.threshold:.2f} ",
                         color="#a8590f", va="bottom", ha="right", fontsize=9)
            axp.set_ylabel("matrix profile distance", color="#a8590f")
            axp.tick_params(axis="y", colors="#a8590f")
            axp.grid(False)
            axp.set_zorder(0)
            ax.set_zorder(1)
            ax.patch.set_visible(False)
            self._ax_profile = axp
        seed_h = fam["seed_idx"] / fs / 3600.0
        norm_d = fam["mp_distance"] / float(np.sqrt(m))
        ax.set_title(
            f"{rec['source_file']}  CH{rec['channel']:02d}   |   "
            f"window {self.scale['window_min']:g} min (m={m})   |   "
            f"family {self.index + 1} of {len(self.families)}   |   "
            f"seed @ {seed_h:.3f} h   |   MP distance {fam['mp_distance']:.3f} "
            f"({norm_d:.3f} x sqrt(m))   |   {len(occ)} occurrences",
            fontsize=12.5, pad=9)

        # -- bottom: overlays ---------------------------------------------
        extracted = [extract_occurrence(x, idx, m, pad=self.pad, align=self.align)
                     for idx, _d in occ]

        panel_modes = self._panel_modes()
        for ax_b, pmode in zip(self._bottom_axes, panel_modes):
            ax_b.clear()
            stacked, drawn = [], []
            for k, ((idx, dist), (_off, values, stats)) in enumerate(zip(occ, extracted)):
                shown = transform_snippet(values, pmode, stats)
                stacked.append(shown)
                drawn.append((shown, colours[k], k, idx, dist))

            if not stacked:
                continue

            # The window the profile actually compared, marked so the
            # padded context can never be mistaken for part of the match.
            if self.pad:
                if self.align == "window":
                    ax_b.axvspan(float(self.t_win[self.pad]), float(self.t_win[self.pad + m - 1]),
                                 color="#fdf0d5", zorder=0, linewidth=0,
                                 label="matrix-profile window")
                else:
                    ax_b.axvline(0.0, color="#c8873a", linewidth=1.4 * self.lw,
                                 linestyle=":", zorder=0, label="aligned peak")

            for values, colour, k, idx, dist in drawn:
                is_seed = k == 0
                label = (f"seed @ {idx / fs / 3600.0:.3f} h" if is_seed
                         else f"nb{k}  d={dist:.3f}")
                ax_b.plot(self.t_win, values, color=colour,
                          linewidth=(3.0 if is_seed else 1.8) * self.lw,
                          alpha=(1.0 if is_seed else 0.75),
                          zorder=(6 if is_seed else 3),
                          solid_capstyle="round", label=label)

            if self.show_envelope and len(stacked) >= 3:
                arr = np.asarray(stacked)
                mu, sd = np.nanmean(arr, axis=0), np.nanstd(arr, axis=0)
                ax_b.fill_between(self.t_win, mu - sd, mu + sd, color="0.55", alpha=0.22,
                                  zorder=1, linewidth=0, label="mean +/- 1 SD")
                ax_b.plot(self.t_win, mu, color="0.20", linewidth=2.2 * self.lw,
                          linestyle="--", zorder=5, label="family mean")
                stacked.extend([mu - sd, mu + sd])

            ax_b.set_xlim(float(self.t_win[0]), float(self.t_win[-1]))
            ax_b.set_ylim(*overlay_limits(stacked, clip=self.clip))
            ax_b.set_xlabel(self.win_label)
            ax_b.set_ylabel(TRANSFORM_YLABEL[pmode])
            ax_b.set_title(TRANSFORM_LABELS[pmode], fontsize=11.5)

        # Legend once, outside the rightmost panel, only while it can still
        # name individual traces; past that the colorbar carries the same
        # information without a two-column wall of text.
        ax_last = self._bottom_axes[-1]
        if len(occ) <= self.max_legend:
            ax_last.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0),
                           framealpha=0.9, handlelength=1.6, borderaxespad=0)
        if norm is not None:
            self._draw_colorbar(norm)

        self.slider.eventson = False
        self.slider.set_val(self.index + 1)
        self.slider.eventson = True
        self.fig.canvas.draw_idle()

    def _draw_colorbar(self, norm):
        import matplotlib as mpl

        if self._colorbar is None:
            cax = self.fig.add_axes([0.945, 0.175, 0.011, 0.345])
            self._colorbar = self.fig.colorbar(
                mpl.cm.ScalarMappable(norm=norm, cmap=mpl.colormaps["viridis"]), cax=cax)
            self._colorbar.set_label("distance to seed", fontsize=10)
        else:
            self._colorbar.mappable.set_norm(norm)
            self._colorbar.update_normal(self._colorbar.mappable)

    # -- navigation -------------------------------------------------------

    def step(self, delta):
        if not self.families:
            return
        new = int(np.clip(self.index + delta, 0, len(self.families) - 1))
        if new != self.index:
            self.index = new
            self.draw()

    def goto(self, index):
        if not self.families:
            return
        new = int(np.clip(index, 0, len(self.families) - 1))
        if new != self.index:
            self.index = new
            self.draw()

    def _on_slider(self, val):
        self.goto(int(val) - 1)

    def _on_radio(self, label):
        self.mode = label
        self.draw()

    def _on_key(self, event):
        if event.key in ("left", "down"):
            self.step(-1)
        elif event.key in ("right", "up"):
            self.step(+1)
        elif event.key == "home":
            self.goto(0)
        elif event.key == "end":
            self.goto(len(self.families) - 1)
        elif event.key == "t":
            self.mode = MODE_CYCLE[(MODE_CYCLE.index(self.mode) + 1) % len(MODE_CYCLE)]
            self.radio.set_active(MODE_CYCLE.index(self.mode))
        elif event.key == "s":
            path = self.save(os.path.join("Plots", "motif_families"))
            print(f"saved {path}")

    def _on_click(self, event):
        """Click the top panel to jump to whichever family's seed is
        nearest in time -- the fastest way to get from 'that burst looks
        interesting' to the group that contains it."""
        if event.inaxes is not self.ax_sig or event.xdata is None or not self.families:
            return
        target = event.xdata * self.t_div * self.scale["fs"]
        seeds = np.array([f["seed_idx"] for f in self.families], dtype=float)
        self.goto(int(np.argmin(np.abs(seeds - target))))

    # -- export -----------------------------------------------------------

    def save(self, out_dir, formats=("png", "pdf"), dpi=200):
        """Write the current family. The navigation strip is hidden for the
        duration -- a Prev/Next button belongs on screen, not in a figure
        that is going into a document."""
        os.makedirs(out_dir, exist_ok=True)
        rec = self.scale["recording"]
        stem = (f"motif_{rec['source_file'].split('.')[0]}_CH{rec['channel']:02d}"
                f"_WIN{self.scale['window_min']:g}min_family{self.index + 1:03d}")
        for ax in self._control_axes:
            ax.set_visible(False)
        try:
            written = []
            for fmt in formats:
                path = os.path.join(out_dir, f"{stem}.{fmt}")
                self.fig.savefig(path, dpi=dpi)
                written.append(path)
        finally:
            for ax in self._control_axes:
                ax.set_visible(True)
        return written[0]

    def export_all(self, out_dir, formats=("png", "pdf"), dpi=200):
        paths = []
        for i in range(len(self.families)):
            self.index = i
            self.draw()
            self.fig.canvas.draw()
            paths.append(self.save(out_dir, formats=formats, dpi=dpi))
        return paths


# =========================================================================
#  CLI
# =========================================================================

def build_parser():
    p = argparse.ArgumentParser(
        description="Report-grade motif family figures from a stored matrix profile.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    src = p.add_argument_group("recording")
    src.add_argument("--recording-id", type=int, default=None,
                     help="exact recordings.id (skips the source-file search)")
    src.add_argument("--source-file", default=DEFAULT_RECORDING,
                     help="case-insensitive substring of recordings.source_file")
    src.add_argument("--channel", type=int, default=None, help="channel number")
    src.add_argument("--db", default=None, help="sqlite path (defaults to DATA/db/annotations.sqlite)")

    prof = p.add_argument_group("profile")
    prof.add_argument("--window-min", type=float, default=3.0,
                      help="matrix-profile window in minutes")
    prof.add_argument("--backend", default="auto", choices=["auto", "stump", "gpu_stump", "scrump"])
    prof.add_argument("--recompute-profile", action="store_true",
                      help="recompute the matrix profile even if a fresh artifact exists")

    fam = p.add_argument_group("families")
    fam.add_argument("--max-distance-norm", type=float, default=DEFAULT_MAX_DISTANCE_NORM,
                     help="neighbour cutoff in units of sqrt(m); scale-portable")
    fam.add_argument("--max-distance", type=float, default=None,
                     help="neighbour cutoff as an absolute distance (overrides the normalised one)")
    fam.add_argument("--max-matches", type=int, default=DEFAULT_MAX_MATCHES,
                     help="hard cap on members per family (render guard, not a modelling choice)")
    fam.add_argument("--max-motifs", type=int, default=DEFAULT_MAX_MOTIFS,
                     help="how far down argsort(mp) the group walk may go")
    fam.add_argument("--min-neighbours", type=int, default=1,
                     help="drop families with fewer than this many neighbours")
    fam.add_argument("--min-separation-frac", type=float, default=1.0,
                     help="occurrences must be this many window-lengths apart; "
                          "1.0 means non-overlapping, 0 disables the check")
    fam.add_argument("--no-cache", action="store_true",
                     help="do not read or write the persisted group set")
    fam.add_argument("--recompute-groups", action="store_true",
                     help="rebuild the group set even if this exact key is already stored")

    fig = p.add_argument_group("figure")
    fig.add_argument("--mode", default="both", choices=MODE_CYCLE,
                     help="overlay transform; 'both' shows z-normalised and raw side by side")
    fig.add_argument("--clip", default="full", choices=["full", "iqr"],
                     help="'full' shows every sample; 'iqr' reproduces the browser's Tukey fence")
    fig.add_argument("--linewidth", type=float, default=1.0, help="scales every line weight")
    fig.add_argument("--font-scale", type=float, default=1.0)
    fig.add_argument("--colour-by", default="distance", choices=["distance", "cycle"])
    fig.add_argument("--context-frac", type=float, default=0.5,
                     help="context drawn either side of the window, in window-lengths; "
                          "0 shows the bare window as the browser does")
    fig.add_argument("--align", default="window", choices=["window", "peak"],
                     help="'window' puts t=0 at the window start; 'peak' at the largest "
                          "excursion, which lines the events themselves up")
    fig.add_argument("--no-envelope", action="store_true", help="hide the mean +/- 1 SD band")
    fig.add_argument("--show-profile", action="store_true",
                     help="overlay the matrix profile and the cutoff on the top panel")
    fig.add_argument("--figsize", default="17,9.5", help="inches, W,H")
    fig.add_argument("--dpi", type=int, default=200)
    fig.add_argument("--start-at", type=int, default=1, help="1-based family to open on")

    out = p.add_argument_group("output")
    out.add_argument("--export-all", action="store_true",
                     help="write every family to --export-dir and exit without showing a window")
    out.add_argument("--export-dir", default=os.path.join("Plots", "motif_families"))
    out.add_argument("--formats", default="png,pdf")
    out.add_argument("--summary-csv", default=None,
                     help="write the per-family summary table here (default: inside --export-dir)")
    out.add_argument("--no-show", action="store_true", help="build the figure but do not display it")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.export_all or args.no_show:
        import matplotlib
        matplotlib.use("Agg")

    conn = init_db(args.db)
    try:
        recording = resolve_recording(conn, args.recording_id, args.source_file, args.channel)
        print(f"recording id={recording['id']}  {recording['source_file']}  "
              f"CH{recording['channel']:02d}  fs={recording['fs']:g} Hz  "
              f"n={recording['n_samples']} "
              f"({recording['n_samples'] / recording['fs'] / 3600.0:.2f} h)")

        scale = load_scale(conn, recording, args.window_min,
                           backend=args.backend, force=args.recompute_profile)
        threshold = resolve_threshold(scale["m"], max_distance=args.max_distance,
                                      max_distance_norm=args.max_distance_norm)
        families, _truncated = build_families(
            conn, scale, threshold=threshold, max_matches=args.max_matches,
            max_motifs=args.max_motifs, min_neighbours=args.min_neighbours,
            min_separation=int(round(args.min_separation_frac * scale["m"])),
            cache=not args.no_cache, force=args.recompute_groups)

        rows = family_summary(families, scale)
        csv_path = args.summary_csv or os.path.join(
            args.export_dir,
            f"families_WIN{args.window_min:g}min_d{threshold:.3f}.csv")
        if rows:
            write_summary_csv(rows, csv_path)
            print(f"  summary -> {csv_path}")
            print(f"  {'#':>3}  {'seed (h)':>9}  {'occ':>4}  {'d_max':>7}  {'p-p mV':>8}")
            for r in rows[:12]:
                print(f"  {r['rank']:>3}  {r['seed_time_h']:>9.3f}  {r['n_occurrences']:>4}  "
                      f"{r['max_member_distance']:>7.3f}  {r['mean_peak_to_peak_mV']:>8.3f}")
            if len(rows) > 12:
                print(f"  ... {len(rows) - 12} more")
    finally:
        conn.close()

    if not families:
        print("\nNo families at this threshold -- try a larger --max-distance-norm.")
        return 1

    width, height = (float(v) for v in args.figsize.split(","))
    view = MotifFamilyFigure(
        scale, families, mode=args.mode, clip=args.clip, lw_scale=args.linewidth,
        font_scale=args.font_scale, colour_by=args.colour_by, figsize=(width, height),
        threshold=threshold, show_envelope=not args.no_envelope,
        context_frac=args.context_frac, align=args.align, show_profile=args.show_profile)
    view.goto(args.start_at - 1)

    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    if args.export_all:
        paths = view.export_all(args.export_dir, formats=formats, dpi=args.dpi)
        print(f"\nwrote {len(paths)} figure(s) to {args.export_dir}")
        return 0

    if not args.no_show:
        import matplotlib.pyplot as plt
        print("\n<- / -> or the buttons to change family; click the top panel to jump; "
              "'t' cycles the overlay; 's' saves.")
        plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
