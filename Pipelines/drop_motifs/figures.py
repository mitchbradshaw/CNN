"""
figures.py
===========
Every figure the drop-motif pipeline produces. The only module in this
pipeline that imports matplotlib, and it imports it lazily with the Agg
backend forced - the same split `motif_report.py` keeps between its
headless core and `MotifFamilyFigure`, and the reason
`Working/Detection/drop_motifs/` can run on a compute node.

Everything here reads the STORE, never a recording. `write_all` is handed
a clustering result and a list of store directories; nothing below opens
an `.npy` or a database. That is what makes "adjust the plot without
rerunning the algorithm" literally rather than nominally true.

The one rule that governs every overlay
---------------------------------------
The clustering z-normalises; the drawn traces never do. This is not a
stylistic preference - the submission this serves names the failure
directly: "normalisation of amplitude destroys the evidence of scaling
laws for depolarisation events". A z-normalised overlay of a 12 mV
Mushroom icicle and a 45 mV M2_aug sharkfin shows them as the same trace
and throws away the finding. So `transform_snippet(..., mode="centred")`
is used and `"znorm"` is not, and the y axis is always millivolts.

Time is a separate question from amplitude and is treated separately.
Each cluster overlay is drawn twice: once against absolute seconds, where
the duration spread IS the point, and once against time normalised by
each event's own fall duration, which is the alignment under which "the
same shape at a different scale" becomes visible. Amplitude stays in mV
in both.

Figures written
---------------
    overview_<id>.png            detection QC: the span, every drop marked
    cluster_<k>.png              one cluster's members overlaid (section 5)
    dendrogram_hero.png          the tree with a waveform at every leaf and
                                 a cluster overlay at every cut node (6.2)
    dendrogram_panels.png        the safer fallback layout
    cross_scale.png              distance heatmaps, via family_search's own
                                 `plot_cross_scale`
    gradient_rose.png            rose diagram of the falling edges, by
                                 absolute steepness and by peakedness
    gradient_rose_by_cluster.png the same rose per shape cluster
"""

import os
import sys
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import gradients as dg
from Working.Detection.drop_motifs import store as ds
from Working.distances import DISTANCE_NATIVE_LENGTH, DISTANCE_SCALE_INVARIANT
from Pipelines.motif_report.motif_report import (
    CYCLE_PALETTE,
    SEED_COLOR,
    _apply_report_style,
    overlay_limits,
)

# Per-recording colour, so a leaf's provenance is readable at a glance on
# the pooled dendrogram. Deliberately two clearly separable hues rather
# than two shades of one: the cross-dataset composition claim is the
# figure's main content and it must survive being printed in a hurry.
RECORDING_COLORS = {
    385: "#c0392b",      # Mushroom_260720
    1: "#2471a3",        # M2_aug CH00
}
RECORDING_FALLBACK = "#7f8c8d"

# Per-SPAN colour. Three of the shipped spans live on recording 1, so a
# recording-keyed palette would draw them identically on the pooled
# dendrogram and the pooled rose - which is exactly where telling them
# apart matters. Ordered so the two originally-validated spans keep the
# red/blue they have had throughout.
SPAN_COLORS = {
    "mushroom_icicles": "#c0392b",
    "m2aug_ch00_am16": "#2471a3",
    "m2aug_ch00_sharkfin14": "#16a085",
    "m2aug_ch00_furrycaterpillar": "#8e44ad",
    "m2aug_ch01_growing": "#d68910",
    "m2aug_ch03_troughtrain": "#2c3e50",
}
SPAN_FALLBACK_PALETTE = ["#7f8c8d", "#c0392b", "#2471a3", "#16a085",
                         "#8e44ad", "#d68910", "#2c3e50", "#e74c3c"]


def span_color(span_key):
    """Stable colour per span, with an unnamed span still getting a
    distinct one rather than everything unknown sharing grey."""
    key = str(span_key)
    if key in SPAN_COLORS:
        return SPAN_COLORS[key]
    return SPAN_FALLBACK_PALETTE[hash(key) % len(SPAN_FALLBACK_PALETTE)]


def event_color(event):
    """The colour for one event's trace: by span where the store carries
    one, falling back to the recording for older stores."""
    key = event.get("span_key") if isinstance(event, dict) else None
    if key:
        return span_color(key)
    return recording_color(event["recording_id"])


def event_label(event):
    """Short human label for one event's span."""
    if isinstance(event, dict):
        return (event.get("span_label")
                or event.get("span_key")
                or short_name(event["source_file"]))
    return short_name(event)

# Above this many leaves an embedded thumbnail is a smudge rather than a
# waveform, and the panels fallback is drawn instead. Set from the row
# height the hero layout allocates: below ~60 leaves each thumbnail gets
# more than a quarter inch of figure height, which is enough for a drop.
THUMBNAIL_LEAF_LIMIT = 60

# Above this many events the pairwise cross-scale heatmap stops being a
# figure: its axes carry one tick label per event, and it costs two O(n^2)
# distance matrices to build. It stays useful per span, where n is tens.
CROSS_SCALE_MAX_EVENTS = 60

# Panels in a split-by-span overlay share one amplitude axis only while
# their ranges are within this factor. Beyond it, sharing flattens the
# smaller spans into straight lines and the figure stops carrying the
# comparison it exists for. 5x is roughly where a trace still reads as a
# shape at one fifth of the axis height.
SHARED_AMPLITUDE_RATIO = 5.0

# x range for every fall-duration-normalised overlay, in units of one
# event's own fall. -3 puts the rise in view, +10 reaches well into the
# recovery on both recordings without letting M2_aug's long tail push
# Mushroom's whole event into the left margin. Shared by every such panel
# so two clusters drawn side by side are on the same axis.
SCALED_TIME_XLIM = (-3.0, 7.0)


def _pyplot():
    """Agg forced before pyplot's first import - matplotlib picks its
    backend then, so setting it afterwards is too late, and this has to
    render with no display."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def recording_color(recording_id):
    return RECORDING_COLORS.get(int(recording_id), RECORDING_FALLBACK)


def short_name(source_file):
    """A dataset alias short enough for a panel title.

    Truncating the filename to N characters cuts mid-word
    (`Mushroom_26072`) and drops the part that distinguishes M2 from M4,
    so the split is on the meaningful boundary instead.
    """
    stem = str(source_file).split(".")[0]
    for marker in ("_concat", "_0509"):
        if marker in stem:
            return stem.split(marker)[0]
    return stem[:16]


def cluster_color(cluster_id):
    return CYCLE_PALETTE[(int(cluster_id) - 1) % len(CYCLE_PALETTE)]


def fmt_mv(value):
    """Millivolts at a precision that survives three orders of magnitude.

    The spans here run from 0.2 mV furrycaterpillar teeth to 117 mV trough
    spikes. A fixed `.0f` prints the caterpillars as "0 mV", which reads
    as a measurement failure rather than as a small number.
    """
    value = float(value)
    if abs(value) >= 10.0:
        return f"{value:.0f}"
    if abs(value) >= 1.0:
        return f"{value:.1f}"
    return f"{value:.2f}"


def composition_text(composition, width=None):
    """`span: n` pairs, optionally wrapped.

    At six spans the unwrapped string is wider than the axes it labels, so
    a panel title built from it runs off the figure. Wrapping keeps it
    inside; the count is what matters and it stays legible either way.
    """
    parts = [f"{short_name(name)}:{count}"
             for name, count in composition["composition"].items()]
    text = ", ".join(parts)
    if width is None or len(text) <= width:
        return text
    import textwrap
    return "\n".join(textwrap.wrap(text, width))


def _save(fig, out_dir, stem, args):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for fmt in (f.strip() for f in args.formats.split(",") if f.strip()):
        path = os.path.join(out_dir, f"{stem}.{fmt}")
        fig.savefig(path, dpi=args.dpi)
        written.append(path)
    return written


# -- per-event traces ------------------------------------------------------

def event_trace(snippets, event, *, centred=True):
    """One event's drawable trace: `(t_seconds_from_onset, values_mV)`.

    Millivolts, never z-scores. `centred` subtracts the pre-onset baseline
    rather than the whole snippet's mean, so several events with different
    resting potentials stack on a common zero WITHOUT their amplitudes
    being touched - the distinction between removing an offset (fine, the
    resting potential is not the finding) and removing a scale (not fine,
    the scale IS the finding).
    """
    arrays = snippets[event["event_id"]]
    values = np.asarray(arrays["raw_mv"], dtype=float)
    onset_offset = int(event["onset_idx"]) - int(event["snippet_start_idx"])
    fs = float(event["fs"])
    t = (np.arange(len(values)) - onset_offset) / fs

    if centred and onset_offset > 0:
        baseline = float(np.median(values[:onset_offset]))
        values = values - baseline
    return t, values


def event_trace_scaled_time(snippets, event, *, centred=True):
    """The same trace with time in units of that event's own fall duration.

    t = 0 is the onset, t = 1 is the trough. This is the alignment under
    which "the same shape at a different duration" becomes a visible claim
    rather than two traces of different widths. Amplitude is untouched.
    """
    t, values = event_trace(snippets, event, centred=centred)
    fall = max(float(event["fall_duration_s"]), 1.0 / float(event["fs"]))
    return t / fall, values


# -- 1. detection overview -------------------------------------------------

def plot_detection_overview(out_dir, args):
    """The span, the detrended span, and every confirmed drop marked.

    The QC figure, and the one that makes the detector arguable: a reader
    can see directly whether the onsets sit at the top of the falls or
    somewhere along them, and on M2_aug can count the marks against the
    annotation's stated cycle count. It reads the store like everything
    else, so the trace shown is a mosaic of the stored snippets rather
    than the channel - gaps between snippets are quiescent stretches with
    no event in them, which is itself informative.
    """
    plt = _pyplot()
    _apply_report_style(args.linewidth, args.font_scale)

    events = ds.load_events(out_dir)
    snippets = ds.load_snippets(out_dir)
    manifest = ds.load_manifest(out_dir)
    rec = manifest["recording"]

    fig, axes = plt.subplots(2, 1, figsize=(16.0, 7.6), sharex=True)

    for event in events:
        arrays = snippets[event["event_id"]]
        t_h = np.asarray(arrays["t_s"], dtype=float) / 3600.0
        color = span_color(manifest.get("span_key") or rec["id"])
        axes[0].plot(t_h, arrays["raw_mv"], lw=0.9 * args.linewidth, color=color)
        axes[1].plot(t_h, arrays["detrended_mv"], lw=0.9 * args.linewidth,
                     color=color)
        onset_h = float(event["onset_h"])
        for ax in axes:
            ax.axvline(onset_h, color=SEED_COLOR, lw=0.8 * args.linewidth,
                       alpha=0.55, zorder=1)
        axes[0].axvspan(float(event["up_region_start_h"]),
                        float(event["up_region_end_h"]),
                        color="#27ae60", alpha=0.18, lw=0, zorder=0)

    counts = manifest["counts"]
    note = manifest.get("extra", {}).get("annotation_note")
    axes[0].set_ylabel("amplitude (mV)")
    axes[1].set_ylabel("detrended (mV)")
    axes[1].set_xlabel("time in recording (hours)")
    axes[0].set_title(
        f"{rec['source_file']} CH{rec['channel']:02d}   "
        f"{rec['span_start_h']:.2f}-{rec['span_end_h']:.2f} h   —   "
        f"{counts['drops_confirmed']} drop(s) from {counts['up_regions']} UP region(s)   "
        f"(green = rise, black line = drop onset)", fontsize=11.5)
    axes[1].set_title(
        f"detrended at {manifest['params']['detrend_window_s']:.0f} s   |   "
        f"rejected: {counts['rejected_no_slope']} no qualifying slope, "
        f"{counts['rejected_shallow']} too shallow, "
        f"{counts['rejected_duplicate']} duplicate"
        + (f"\nannotation: {note}" if note else ""), fontsize=10)

    fig.tight_layout()
    return fig


# -- 2. per-cluster overlays (section 5) -----------------------------------

def plot_cluster_overlay(clustering, snippets, cluster_id, args):
    """One cluster, every member overlaid, NON-NORMALISED.

    No family mean drawn: the operator asked for the members and nothing
    else, and on a family whose members differ by a factor of four in
    amplitude a mean is a line no member resembles.

    Left panel is absolute seconds - the duration spread is the content.
    Right panel is time in units of each event's own fall, which is the
    only alignment under which members of different scale can be compared
    at all. Both are in millivolts.
    """
    plt = _pyplot()
    _apply_report_style(args.linewidth, args.font_scale)

    labels = clustering["labels"]
    members = [e for e, lab in zip(clustering["events"], labels)
               if lab == cluster_id]
    ratios = clustering["roughness"]["ratios"]
    keep = clustering["roughness"]["keep"]
    member_keep = [k for k, lab in zip(keep, labels) if lab == cluster_id]
    member_ratio = [r for r, lab in zip(ratios, labels) if lab == cluster_id]

    fig, axes = plt.subplots(1, 2, figsize=(15.0, 5.6))
    stacked_abs, stacked_rel = [], []

    for event, kept, ratio in zip(members, member_keep, member_ratio):
        color = event_color(event)
        # A member the roughness filter flags is DRAWN, faintly, rather
        # than removed: `seed_replicas.py` established on this data that
        # the rejects are usually noisy recordings of the right shape, not
        # wrong matches, and hiding them would overstate the family.
        style = dict(color=color, lw=1.6 * args.linewidth, alpha=0.85) if kept \
            else dict(color="#95a5a6", lw=0.9 * args.linewidth, alpha=0.5)

        t, v = event_trace(snippets, event)
        axes[0].plot(t, v, **style)
        stacked_abs.append(v)

        tr, vr = event_trace_scaled_time(snippets, event)
        axes[1].plot(tr, vr, **style)
        stacked_rel.append(vr)

    for ax in axes:
        ax.axvline(0.0, color=SEED_COLOR, lw=1.0, alpha=0.5, ls="--")
        ax.axhline(0.0, color="#999999", lw=0.8, alpha=0.6)
        ax.set_ylabel("amplitude (mV, baseline-subtracted)")
    axes[0].set_ylim(*overlay_limits(stacked_abs))
    axes[1].set_ylim(*overlay_limits(stacked_rel))
    axes[0].set_xlabel("time from drop onset (s)")
    axes[1].set_xlabel("time from drop onset (fall durations)")
    axes[1].set_xlim(*SCALED_TIME_XLIM)

    composition = next(r for r in clustering["composition"]
                       if r["cluster_id"] == int(cluster_id))
    # Source files shortened to their dataset stem: the full
    # `Mushroom_260720_0509_4hrs_CH14_fs1.mat` in a title runs off the
    # figure, and the recording id beside it is the unambiguous key.
    parts = composition_text(composition, width=110)
    n_excluded = int(sum(1 for k in member_keep if not k))
    lo, hi = composition["fall_range_s"]
    axes[0].set_title(f"absolute time — fall durations {lo:.0f}-{hi:.0f} s "
                      f"({hi / max(lo, 1e-9):.0f}x)", fontsize=11)
    axes[1].set_title("time normalised by each event's own fall duration\n"
                      "(amplitude NOT normalised)", fontsize=11)
    fig.suptitle(
        f"Cluster {cluster_id}  ·  n={composition['n']}  ·  "
        f"{'PURE' if composition['pure'] else 'MIXED'} [{parts}]  ·  "
        f"median {fmt_mv(composition['median_depth_mv'])} mV / "
        f"{composition['median_fall_s']:.0f} s  ·  "
        f"{n_excluded} flagged noisy (grey)",
        fontsize=12, y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def plot_cluster_overlay_by_span(clustering, snippets, cluster_id, args):
    """One cluster, ABSOLUTE TIME only, one panel per source span.

    The companion to `plot_cluster_overlay`, and the one to read when a
    cluster mixes spans. On a shared absolute-time axis a 200-second
    M2_aug fall and a 9-second Mushroom icicle cannot both be legible -
    the long one sets the x range and the short one becomes a vertical
    line at the origin. Splitting by span gives each its own axes and its
    own time range, so the shape of each contribution is visible, while
    the shared y axis keeps the amplitudes honestly comparable.

    Every panel is aligned on the drop onset at t=0, which is the same
    alignment the pooled overlays use, so a reader can move between the
    two figures without re-learning the x axis.
    """
    plt = _pyplot()
    _apply_report_style(args.linewidth, args.font_scale)

    labels = np.asarray(clustering["labels"])
    events = clustering["events"]
    members = [e for e, lab in zip(events, labels) if lab == cluster_id]
    keep = [k for k, lab in zip(clustering["roughness"]["keep"], labels)
            if lab == cluster_id]

    groups = {}
    for event, kept in zip(members, keep):
        groups.setdefault(event.get("span_key", event["source_file"]),
                          []).append((event, kept))
    order = sorted(groups)
    n = len(order)

    fig, axes = plt.subplots(1, n, figsize=(6.2 * n, 5.4), squeeze=False)
    axes = axes[0]

    # Shared y axis, but only when sharing leaves every panel readable.
    #
    # The first version of this figure shared it unconditionally, on the
    # reasoning that the amplitude difference between spans is a finding
    # and should not be scaled away. That reasoning is right and the
    # implementation was wrong: a pooled cluster can span 0.06 mV
    # caterpillars and 109 mV trough spikes, and on one axis the small two
    # thirds of the figure are flat lines. The amplitude difference is
    # already carried, exactly and in numbers, by each panel's own title.
    #
    # So: share when the panels' amplitude ranges are within
    # SHARED_AMPLITUDE_RATIO of each other, and otherwise give each its
    # own and SAY SO on the figure, because an unshared axis that looks
    # shared is the more dangerous of the two failures.
    per_panel = {}
    spans_mv = {}
    for key in order:
        traces = [event_trace(snippets, e) for e, _ in groups[key]]
        per_panel[key] = traces
        lo, hi = overlay_limits([v for _, v in traces]) if traces else (-1.0, 1.0)
        spans_mv[key] = (lo, hi, hi - lo)

    extents = [s[2] for s in spans_mv.values() if s[2] > 0]
    ratio = (max(extents) / min(extents)) if len(extents) > 1 else 1.0
    share = ratio <= SHARED_AMPLITUDE_RATIO
    if share:
        stacked_all = [v for key in order for _, v in per_panel[key]]
        shared_ylim = overlay_limits(stacked_all) if stacked_all else (-1.0, 1.0)

    for ax, key in zip(axes, order):
        entries = groups[key]
        for (event, kept), (t, v) in zip(entries, per_panel[key]):
            style = dict(color=event_color(event),
                         lw=1.7 * args.linewidth, alpha=0.85) if kept else \
                dict(color="#95a5a6", lw=0.9 * args.linewidth, alpha=0.5)
            ax.plot(t, v, **style)
        ax.axvline(0.0, color=SEED_COLOR, lw=1.0, alpha=0.5, ls="--")
        ax.axhline(0.0, color="#999999", lw=0.8, alpha=0.6)
        ax.set_ylim(*(shared_ylim if share else spans_mv[key][:2]))
        ax.set_xlabel("time from drop onset (s)")
        falls = [float(e["fall_duration_s"]) for e, _ in entries]
        depths = [float(e["drop_depth_mv"]) for e, _ in entries]
        label = entries[0][0].get("span_label") or short_name(
            entries[0][0]["source_file"])
        ax.set_title(f"{label}\n"
                     f"n={len(entries)}   fall {min(falls):.0f}-{max(falls):.0f} s   "
                     f"depth {min(depths):.2f}-{max(depths):.2f} mV",
                     fontsize=10.5 * args.font_scale)
    for ax in axes:
        ax.set_ylabel("amplitude (mV, baseline-subtracted)")

    composition = next(r for r in clustering["composition"]
                       if r["cluster_id"] == int(cluster_id))
    scale_note = ("shared amplitude scale" if share else
                  f"INDEPENDENT amplitude scales — the spans' ranges differ "
                  f"{ratio:.0f}x, so one axis would flatten the smaller ones")
    fig.suptitle(
        f"Cluster {cluster_id}  ·  n={composition['n']}  ·  by source span  ·  "
        f"absolute time, aligned on the drop onset  ·  {scale_note}",
        fontsize=12.0, y=0.985)
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    return fig


# -- 3. the hero dendrogram (section 6.2) ----------------------------------

def plot_dendrogram_hero(clustering, snippets, args):
    """The tree, with every leaf's own waveform drawn beside it and every
    cluster's overlay drawn beside that.

    Layout, and why it is horizontal. A vertical tree gives each of N
    leaves 1/N of the figure WIDTH, which at 42 leaves is a third of an
    inch - a thumbnail there is a smudge. `orientation="left"` gives each
    leaf a full row instead, so the thumbnail is wide and short, which is
    the aspect ratio a drop actually wants.

    Three columns:
      left    the tree, leaves ordered top to bottom
      middle  one thumbnail per leaf, that single drop, in mV
      right   one overlay per cluster, spanning its members' rows

    scipy's `orientation="left"` places leaf 0 at the BOTTOM and numbers
    leaf centres at 5, 15, 25, ... in its own coordinate space; both facts
    are used below rather than assumed away, because getting either wrong
    silently pairs a thumbnail with the wrong branch - which is precisely
    the "technically present, useless to the reader" failure this repo has
    hit before.
    """
    plt = _pyplot()
    from scipy.cluster.hierarchy import dendrogram

    _apply_report_style(args.linewidth, args.font_scale)

    events = clustering["events"]
    Z = clustering["linkage"]
    labels = np.asarray(clustering["labels"])
    n = len(events)

    row_height = 0.30
    fig_height = max(7.0, row_height * n + 2.2)
    fig = plt.figure(figsize=(17.0, fig_height))

    left, right = 0.045, 0.985
    bottom, top = 0.055, 0.925
    tree_w, thumb_w, gap = 0.26, 0.30, 0.022
    overlay_x = left + tree_w + gap + thumb_w + gap
    overlay_w = right - overlay_x

    ax_tree = fig.add_axes([left, bottom, tree_w, top - bottom])
    cut = _cut_height(Z, labels)
    dendro = dendrogram(Z, orientation="left", ax=ax_tree, no_labels=True,
                        link_color_func=_link_color_func(Z, labels, n))
    for line in ax_tree.get_lines():
        line.set_linewidth(1.6 * args.linewidth)
    ax_tree.axvline(cut, color=SEED_COLOR, lw=1.2, ls="--", alpha=0.65)
    ax_tree.set_xlabel(f"{clustering['method']} linkage distance\n"
                       f"(resampled, z-normalised; cut at {cut:.2f})")
    ax_tree.grid(False)
    ax_tree.set_title(f"{n} drops, {clustering['n_clusters']} clusters\n"
                      f"cophenetic r = {clustering['cophenetic_r']:.3f}",
                      fontsize=11)

    # scipy's leaf coordinate space: leaf i sits at 5 + 10*i, bottom-first.
    leaves = dendro["leaves"]
    y_lo, y_hi = ax_tree.get_ylim()
    span = y_hi - y_lo

    def leaf_axis_fraction(position):
        """Leaf at `position` (0 = bottom of the tree) -> figure y."""
        y_data = 5.0 + 10.0 * position
        frac = (y_data - y_lo) / span
        return bottom + frac * (top - bottom)

    thumb_h = min(row_height * 0.82, (top - bottom) / max(n, 1) * 0.86)
    thumb_x = left + tree_w + gap

    for position, leaf in enumerate(leaves):
        event = events[leaf]
        y = leaf_axis_fraction(position) - thumb_h / 2.0
        ax = fig.add_axes([thumb_x, y, thumb_w, thumb_h])
        t, v = event_trace(snippets, event)
        ax.plot(t, v, color=event_color(event),
                lw=1.1 * args.linewidth, solid_capstyle="round")
        ax.axvline(0.0, color=SEED_COLOR, lw=0.6, alpha=0.45)
        _strip_axis(ax)
        # One label per leaf, small, INSIDE the thumbnail's own axes: which
        # recording, when, how deep, how long. Placed inside rather than in
        # a gutter so the column can be as wide as the figure allows - a
        # thumbnail squeezed to make room for its own caption is the thing
        # this layout exists to avoid.
        ax.text(0.995, 0.06,
                f"{event['onset_h']:.2f} h   {event['drop_depth_mv']:.0f} mV   "
                f"{event['fall_duration_s']:.0f} s",
                transform=ax.transAxes, ha="right", va="bottom",
                fontsize=6.2 * args.font_scale, color="#555555")

    # -- cluster overlays, one per contiguous block of leaves -------------
    # The leaves of one cluster are contiguous in `leaves` by construction
    # (they are a subtree), so a block is found by walking the order.
    blocks = _contiguous_blocks([labels[leaf] for leaf in leaves])
    for cluster_id, start, end in blocks:
        y0 = leaf_axis_fraction(start) - thumb_h / 2.0
        y1 = leaf_axis_fraction(end - 1) + thumb_h / 2.0
        height = max(y1 - y0, 0.035)
        ax = fig.add_axes([overlay_x + 0.055, y0, overlay_w - 0.075, height])
        members = [events[leaf] for leaf in leaves[start:end]]
        stacked = []
        for event in members:
            tr, vr = event_trace_scaled_time(snippets, event)
            ax.plot(tr, vr, color=event_color(event),
                    lw=1.3 * args.linewidth, alpha=0.8)
            stacked.append(vr)
        if stacked:
            ax.set_ylim(*overlay_limits(stacked))
        ax.set_xlim(*SCALED_TIME_XLIM)
        ax.axvline(0.0, color=SEED_COLOR, lw=0.8, alpha=0.5, ls="--")
        ax.set_facecolor("#fbfbfb")
        for spine in ax.spines.values():
            spine.set_edgecolor(cluster_color(cluster_id))
            spine.set_linewidth(2.0)
        ax.set_xticks([])
        ax.tick_params(labelsize=6.5 * args.font_scale)
        ax.grid(False)
        composition = next(r for r in clustering["composition"]
                           if r["cluster_id"] == int(cluster_id))
        # A small cluster gets a short block, so its caption is shortened
        # and shrunk to match rather than moved: a caption in the gutter
        # collides with the neighbouring block's axis, and a full-length
        # one laid across a two-row block covers the only two traces it
        # has. Both were tried; this is what fits.
        small = (end - start) < 3
        caption = (f"c{cluster_id}  n={composition['n']}  "
                   f"{fmt_mv(composition['median_depth_mv'])} mV / "
                   f"{composition['median_fall_s']:.0f} s") if small else (
                   f"cluster {cluster_id}  n={composition['n']}  "
                   f"{'PURE' if composition['pure'] else 'MIXED'}  "
                   f"median {fmt_mv(composition['median_depth_mv'])} mV / "
                   f"{composition['median_fall_s']:.0f} s")
        ax.text(0.012, 0.94 if small else 0.965, caption,
                transform=ax.transAxes, ha="left", va="top",
                fontsize=(5.8 if small else 7.5) * args.font_scale,
                color=cluster_color(cluster_id), fontweight="bold")

    _legend(fig, events, args)
    # Each thumbnail spans its OWN snippet, so the column is not a shared
    # time axis and must not claim to be - the per-leaf duration label is
    # what carries the scale, and that is what the header points at.
    fig.text(left + tree_w + gap + thumb_w / 2.0, top + 0.012,
             "each drop (mV; own time axis — hour, depth, fall duration labelled)",
             ha="center", va="bottom", fontsize=10 * args.font_scale)
    fig.text(overlay_x + overlay_w / 2.0, top + 0.012,
             "cluster overlay (mV, time in fall durations — amplitude NOT normalised)",
             ha="center", va="bottom", fontsize=10 * args.font_scale)
    fig.suptitle("Spike-drop motifs: every drop at its leaf, every cluster overlaid",
                 fontsize=15, y=0.982)
    return fig


def _strip_axis(ax):
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.patch.set_alpha(0.0)


def _contiguous_blocks(sequence):
    """`[(value, start, end), ...]` over runs of an equal value."""
    blocks, start = [], 0
    for i in range(1, len(sequence) + 1):
        if i == len(sequence) or sequence[i] != sequence[start]:
            blocks.append((int(sequence[start]), start, i))
            start = i
    return blocks


def _cut_height(Z, labels):
    """The linkage height that produces exactly the labels in hand.

    Derived from the tree rather than passed in, so the dashed line drawn
    on the figure is provably the cut that produced the clusters beside
    it, whether they came from `--n-clusters`, `--cut-height` or the
    heuristic.
    """
    k = len(set(np.asarray(labels).tolist()))
    heights = Z[:, 2]
    if k <= 1 or k > len(heights):
        return float(heights[-1] * 1.01)
    idx = len(heights) - k
    below = heights[idx - 1] if idx >= 1 else 0.0
    return float((below + heights[idx]) / 2.0)


def _link_color_func(Z, labels, n):
    """Colour every branch by the CLUSTER beneath it, not by a height.

    scipy's own `color_threshold` colours subtrees below a height, which
    is only the same thing as colouring by cluster when the cut height is
    exactly right - and when it is not, the tree is coloured into a
    different number of groups from the panels beside it, which makes the
    figure quietly self-contradicting. Resolving membership per node
    instead makes the two agree by construction.

    Same approach as `Working/Catalogue/dendrogram/dendrogram_cluster.
    _make_link_color_func`, reimplemented rather than imported because
    that module imports matplotlib at module scope and takes a
    `ClusterResult` built from a window-matrix DataFrame; neither is
    available here.
    """
    labels = np.asarray(labels)
    members = {i: {i} for i in range(n)}
    for i, (left, right, _h, _c) in enumerate(Z):
        members[n + i] = members[int(left)] | members[int(right)]

    def color(node_id):
        leaf_labels = {int(labels[leaf]) for leaf in members[int(node_id)]}
        if len(leaf_labels) == 1:
            return cluster_color(leaf_labels.pop())
        return "#7f8c8d"        # a merge that spans clusters: above the cut

    return color


def _legend(fig, events, args):
    from matplotlib.lines import Line2D
    seen = {}
    for event in events:
        key = event.get("span_key") or ("r%s" % event["recording_id"])
        seen.setdefault(key, event_label(event))
    handles = [Line2D([0], [0], color=span_color(key), lw=2.6, label=label)
               for key, label in sorted(seen.items())]
    ncol = min(len(handles), 3)
    fig.legend(handles=handles, loc="lower center", ncol=ncol,
               frameon=False, fontsize=9.0 * args.font_scale,
               bbox_to_anchor=(0.5, 0.002))


# -- 4. the fallback layout (section 6.2) ----------------------------------

def plot_dendrogram_panels(clustering, snippets, args):
    """Tree on the left, a grid of per-cluster overlays on the right, in
    the same top-to-bottom cluster order as the tree's leaves.

    The lower-risk layout, kept available regardless of which one is
    chosen for a given run: it says the same thing as the hero figure -
    here is the tree, here is what each branch looks like as a shape -
    with none of the inset-placement risk, and it stays legible at leaf
    counts where a thumbnail per leaf would not.
    """
    plt = _pyplot()
    from scipy.cluster.hierarchy import dendrogram

    _apply_report_style(args.linewidth, args.font_scale)

    events = clustering["events"]
    Z = clustering["linkage"]
    labels = np.asarray(clustering["labels"])
    leaves = clustering["leaves"]
    blocks = _contiguous_blocks([labels[leaf] for leaf in leaves])
    n_blocks = len(blocks)

    fig = plt.figure(figsize=(16.0, max(6.0, 2.5 * n_blocks + 1.6)))
    gs = fig.add_gridspec(n_blocks, 2, width_ratios=[1.0, 1.75],
                          left=0.055, right=0.98, top=0.90, bottom=0.09,
                          hspace=0.45, wspace=0.16)

    ax_tree = fig.add_subplot(gs[:, 0])
    cut = _cut_height(Z, labels)
    dendrogram(Z, orientation="left", ax=ax_tree, no_labels=True,
               link_color_func=_link_color_func(Z, labels, len(events)))
    for line in ax_tree.get_lines():
        line.set_linewidth(1.5 * args.linewidth)
    ax_tree.axvline(cut, color=SEED_COLOR, lw=1.2, ls="--", alpha=0.65)
    ax_tree.grid(False)
    ax_tree.set_xlabel(f"{clustering['method']} linkage distance")
    ax_tree.set_title(f"{len(events)} drops, {clustering['n_clusters']} clusters\n"
                      f"cophenetic r = {clustering['cophenetic_r']:.3f}", fontsize=11)

    # scipy's `orientation="left"` puts the first leaf at the bottom, so
    # the grid is filled bottom-up to keep the two panels reading in the
    # same direction. Cluster ids are annotated on both, so the pairing is
    # checkable by eye and not merely asserted here.
    for row, (cluster_id, start, end) in enumerate(reversed(blocks)):
        ax = fig.add_subplot(gs[row, 1])
        members = [events[leaf] for leaf in leaves[start:end]]
        stacked = []
        for event in members:
            tr, vr = event_trace_scaled_time(snippets, event)
            ax.plot(tr, vr, color=event_color(event),
                    lw=1.4 * args.linewidth, alpha=0.82)
            stacked.append(vr)
        if stacked:
            ax.set_ylim(*overlay_limits(stacked))
        ax.set_xlim(*SCALED_TIME_XLIM)
        ax.axvline(0.0, color=SEED_COLOR, lw=0.9, alpha=0.5, ls="--")
        composition = next(r for r in clustering["composition"]
                           if r["cluster_id"] == int(cluster_id))
        ax.set_title(f"cluster {cluster_id}   n={composition['n']}   "
                     f"{'PURE' if composition['pure'] else 'MIXED'}   "
                     f"median {fmt_mv(composition['median_depth_mv'])} mV / "
                     f"{composition['median_fall_s']:.0f} s\n"
                     f"[{composition_text(composition, width=88)}]",
                     fontsize=9.0, color=cluster_color(cluster_id))
        ax.set_ylabel("mV")
        if row == n_blocks - 1:
            ax.set_xlabel("time from drop onset (fall durations)")

        # Same id on the tree side, at the block's vertical centre.
        y_lo, y_hi = ax_tree.get_ylim()
        centre = 5.0 + 10.0 * (start + end - 1) / 2.0
        ax_tree.text(ax_tree.get_xlim()[0], centre, f" {cluster_id}",
                     ha="left", va="center", fontsize=10 * args.font_scale,
                     color=cluster_color(cluster_id), fontweight="bold")

    _legend(fig, events, args)
    fig.suptitle("Spike-drop motif clusters (amplitude NOT normalised)",
                 fontsize=14, y=0.965)
    return fig


# -- 5. the slope rose -----------------------------------------------------

def plot_slope_rose(rose, args, *, ax=None, title=None, show_events=True):
    """A rose diagram of the falling edges.

    Each ray points at the angle of a fall and its length is how many
    spikes fall at that steepness - a circular histogram, drawn as rays
    rather than wedges so it reads as the teacher described: a line from
    the centre whose direction is the gradient and whose length is the
    population at that gradient.

    Two conventions worth stating on sight:

      - Angles are NEGATIVE and the rays point down-and-right, into the
        fourth quadrant, because a fall goes down as time goes right. The
        ray is therefore the falling edge itself, drawn to scale. Nothing
        can land outside that quadrant, so the other three are drawn
        greyed rather than left looking empty by accident.
      - The angle depends on a REFERENCE slope, printed on the figure.
        `arctan` needs a dimensionless argument and mV/s is not one; see
        `Working/Detection/drop_motifs/gradients.py`.

    Individual events are drawn as short ticks just inside the rim, so the
    raw data is visible behind the binning and a lobe made of three events
    cannot pass for one made of thirty.
    """
    plt = _pyplot()

    created = ax is None
    if created:
        fig = plt.figure(figsize=(8.4, 8.0))
        ax = fig.add_subplot(111, projection="polar")
    else:
        fig = ax.get_figure()

    ax.set_theta_zero_location("E")
    ax.set_theta_direction(1)          # counter-clockwise; negative -> below
    # Only the falling quadrant is reachable, so only the falling quadrant
    # is drawn. Showing the full circle would leave three quarters of the
    # figure permanently blank and imply the other directions were
    # measured and found empty, which is a different and false statement.
    # The two limits are labelled with what they physically mean instead.
    ax.set_thetamin(-90)
    ax.set_thetamax(0)

    counts = np.asarray(rose["counts"])
    peak = int(counts.max()) if counts.size and counts.max() > 0 else 1
    rug_radius = peak * 1.13
    ceiling = peak * 1.30

    groups = rose["groups"]
    width = rose["bin_width"]
    n_groups = max(len(groups), 1)

    # A faint arc marking where the per-event ticks sit, so the rug reads
    # as one band of raw data rather than as stray marks at odd radii.
    if show_events:
        arc = np.linspace(rose["lo"], rose["hi"], 200)
        ax.plot(arc, np.full_like(arc, rug_radius), color="#cccccc",
                lw=0.8, zorder=1)

    for slot, (key, group) in enumerate(sorted(groups.items())):
        color = span_color(key)
        # Rays within a bin are fanned slightly so two recordings at the
        # same steepness are both visible instead of one hiding the other.
        offset = (slot - (n_groups - 1) / 2.0) * width * 0.30
        for centre, count in zip(rose["bin_centres"], group["counts"]):
            if not count:
                continue
            ax.plot([centre + offset, centre + offset], [0.0, count],
                    color=color, lw=3.6 * args.linewidth,
                    solid_capstyle="round", alpha=0.9, zorder=3)

        if show_events:
            # One tick per event on the arc: the raw data behind the
            # binning, so a lobe made of three events cannot pass for one
            # made of thirty.
            ax.plot(group["angles"], np.full(len(group["angles"]), rug_radius),
                    linestyle="none", marker="|",
                    markersize=9 * args.linewidth,
                    markeredgewidth=1.4 * args.linewidth,
                    color=color, alpha=0.85, zorder=4)

        # Mean direction, dashed, with its length encoding the resultant
        # length R. A short dash IS the statement "these directions are not
        # concentrated" - drawing every mean at full length would make a
        # meaningless mean look like a finding.
        mean_theta = np.deg2rad(group["mean_deg"])
        ax.plot([mean_theta, mean_theta],
                [0.0, peak * group["resultant_length"]],
                color=color, lw=1.8 * args.linewidth, ls=(0, (5, 3)),
                alpha=0.95, zorder=5)

    ax.set_ylim(0, ceiling)
    ax.set_yticks(_integer_ticks(peak))
    # Radial labels sit down the vertical (90 degree) edge. Inside a
    # restricted theta range matplotlib ignores `set_rlabel_position`, so
    # rather than fight it the theta labels are kept single-line and the
    # "flat"/"vertical" gloss moved into the subtitle, which is what was
    # actually colliding with them.
    ax.set_thetagrids([0, -15, -30, -45, -60, -75, -90],
                      ["0°", "15°", "30°", "45°", "60°", "75°", "90°"])
    ax.tick_params(labelsize=9.0 * args.font_scale, pad=1.0)
    ax.grid(alpha=0.3)

    if title is None:
        title = f"Fall-gradient rose — {rose['field'].replace('_mv_s', '')}"
    ax.set_title(f"{title}\n{rose['caption']}\n"
                 f"0° = flat, 90° = vertical   ·   "
                 f"radius = spikes per {np.rad2deg(width):.1f}° bin",
                 fontsize=10.5 * args.font_scale, pad=14)
    return fig


def plot_cluster_roses(clustering, snippets, args):
    """One rose per shape cluster, on a shared radial scale.

    The pooled rose says what the population's falling edges look like.
    This asks a different and sharper question: do the clusters found by
    SHAPE also separate by GRADIENT? They need not - shape clustering
    z-normalises, so it is blind to steepness by construction, and a
    cluster could perfectly well contain a 5 mV/s fall and a 0.5 mV/s one
    with the same profile. Where a cluster's rose is tight, steepness and
    profile are carrying the same information; where it is broad, they are
    independent, and that is worth knowing before either is used as a
    feature.

    Every panel shares one radial limit so lobe lengths are comparable
    across clusters by eye - the usual small-multiples rule, and the one
    that is easiest to break by letting each panel autoscale.
    """
    plt = _pyplot()
    _apply_report_style(args.linewidth, args.font_scale)

    events = clustering["events"]
    labels = np.asarray(clustering["labels"])
    cluster_ids = sorted(set(labels.tolist()))

    per_cluster = {}
    for cluster_id in cluster_ids:
        members = [e for e, lab in zip(events, labels) if lab == cluster_id]
        # `pooled` scale here, not `raw`: these panels are compared with
        # each other, and a global 1 mV/s reference collapses every
        # low-amplitude cluster onto the horizontal.
        per_cluster[cluster_id] = dg.rose_data(
            members, snippets, scale="pooled", fixed=args.slope_ref,
            field=args.gradient_field, n_bins=args.rose_bins)

    peak = max((int(np.max(r["counts"])) if len(r["counts"]) else 1)
               for r in per_cluster.values())
    peak = max(peak, 1)

    n = len(cluster_ids)
    cols = min(n, 3)
    rows = int(np.ceil(n / cols))
    # A restricted-theta polar axes does not fill its box vertically - the
    # quarter wedge occupies roughly the upper two thirds - so the per-row
    # height is set below the width rather than square, otherwise the grid
    # opens up a band of dead space under every row.
    fig = plt.figure(figsize=(5.4 * cols, 4.7 * rows + 0.7))

    for i, cluster_id in enumerate(cluster_ids):
        ax = fig.add_subplot(rows, cols, i + 1, projection="polar")
        rose = per_cluster[cluster_id]
        plot_slope_rose(rose, args, ax=ax, title=None, show_events=True)

        composition = next(r for r in clustering["composition"]
                           if r["cluster_id"] == int(cluster_id))
        ax.set_title(
            f"cluster {cluster_id}   n={composition['n']}   "
            f"{'PURE' if composition['pure'] else 'MIXED'}\n"
            f"[{composition_text(composition, width=44)}]\n"
            f"mean {rose['mean_deg']:.1f}°   R={rose['resultant_length']:.3f}   "
            f"SD={rose['circular_sd_deg']:.1f}°",
            fontsize=10.0 * args.font_scale,
            color=cluster_color(cluster_id), pad=14)
        # One radial scale across every panel, so a long lobe means the
        # same thing everywhere.
        ax.set_ylim(0, peak * 1.30)
        ax.set_yticks(_integer_ticks(peak))

    _legend(fig, events, args)
    fig.suptitle(
        "Fall-gradient rose per shape cluster   ·   45° = each cluster's own "
        "median steepest slope   ·   shared radial scale",
        fontsize=13, y=0.985)
    fig.tight_layout(rect=(0, 0.04, 1, 0.925))
    return fig, per_cluster


def _write_rose_summary(roses, target):
    """The rose's numbers as JSON, so they can be quoted without being
    read off the figure - the same discipline the manifest keeps for
    detection."""
    import json

    payload = {}
    for name, rose in roses.items():
        payload[name] = {
            "gradient_field": rose["field"],
            "slope_scale": rose["scale"],
            "reference_caption": rose["caption"],
            "n": rose["n"],
            "mean_deg": rose["mean_deg"],
            "resultant_length": rose["resultant_length"],
            "circular_sd_deg": rose["circular_sd_deg"],
            "uniformity_p": rose["uniformity_p"],
            "per_recording": {
                str(key): {k: v for k, v in group.items()
                           if k not in ("angles", "counts", "slopes_mv_s")}
                for key, group in rose["groups"].items()
            },
        }
    path = os.path.join(target, "gradient_rose_summary.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def _integer_ticks(peak, max_ticks=5):
    """Radial ticks that are whole numbers of events. A rose's radius is a
    COUNT, so a tick at 2.5 spikes is meaningless."""
    step = max(1, int(np.ceil(peak / max_ticks)))
    return list(range(step, peak + step, step))


def plot_rose_figure(events, snippets, args, *, pooled=True):
    """The rose deck: the same population under two different references.

    Left, `raw` — 45 degrees means a stated mV/s, so the two recordings
    separate by their absolute steepness. This is the scale question, and
    on this data the answer is large: Mushroom_260720's falls are roughly
    six times steeper in mV/s than M2_aug's.

    Right, `peakedness` — each fall's steepest gradient divided by its own
    mean gradient, then divided again by the POOLED MEDIAN of that ratio.
    This is the SHAPE question, how front-loaded the fall is, and it is
    the one that survives the two recordings living at different scales.

    That second division is not decoration. `arctan` compresses hard above
    about 3, so plotting the raw ratio puts Mushroom_260720's 2.36 at 67°
    and M2_aug's 4.26 at 77° - a 1.8x difference rendered as 10°, which
    makes the figure understate a real separation. Referencing the pooled
    median instead puts a typical fall at 45°, where arctan is most
    sensitive, and the same 1.8x difference opens out to roughly 17°.
    The reference is printed on the panel either way.

    A statistics panel underneath carries the numbers, because a rose is
    persuasive enough that it should not be the only evidence: mean
    direction, resultant length R, circular SD and a uniformity p-value
    per recording.
    """
    plt = _pyplot()
    _apply_report_style(args.linewidth, args.font_scale)

    # Which reference the left panel uses depends on what the figure is
    # for, and getting this wrong empties the panel.
    #
    # Pooled: a stated absolute reference (1 mV/s), because comparing the
    # spans' absolute steepness against each other IS the question.
    #
    # Per span: that span's own median steepest slope, so 45 degrees means
    # "typical here" and what is left on the plot is the SPREAD. A fixed
    # 1 mV/s reference on the furrycaterpillar span, whose drops run about
    # 0.1 mV/s, puts every ray inside six degrees of horizontal and the
    # panel shows nothing at all.
    scale = "raw" if pooled else "pooled"
    raw = dg.rose_data(events, snippets, scale=scale, fixed=args.slope_ref,
                       field=args.gradient_field, n_bins=args.rose_bins)
    shape = dg.rose_data(events, snippets, scale="pooled",
                         field="peakedness", n_bins=args.rose_bins)

    fig = plt.figure(figsize=(15.0, 9.6))
    gs = fig.add_gridspec(2, 2, height_ratios=[3.5, 1.0],
                          left=0.05, right=0.97, top=0.82, bottom=0.08,
                          hspace=0.16, wspace=0.10)

    plot_slope_rose(raw, args, ax=fig.add_subplot(gs[0, 0], projection="polar"),
                    title="Absolute steepness (scale)")
    plot_slope_rose(shape, args, ax=fig.add_subplot(gs[0, 1], projection="polar"),
                    title="Peakedness — steepest ÷ own mean gradient (shape)")

    for column, rose, label in ((0, raw, "absolute"), (1, shape, "shape")):
        ax = fig.add_subplot(gs[1, column])
        ax.axis("off")
        lines = [f"{'recording':<26}{'n':>4}{'mean':>9}{'R':>7}"
                 f"{'circ SD':>9}{'uniform p':>11}"]
        for key, group in sorted(rose["groups"].items()):
            lines.append(
                f"{(group.get('span_label') or short_name(group['source_file']))[:24]:<26}"
                f"{group['n']:>4}{group['mean_deg']:>8.1f}°"
                f"{group['resultant_length']:>7.3f}"
                f"{group['circular_sd_deg']:>8.1f}°"
                f"{group['uniformity_p']:>11.2g}")
        lines.append(
            f"{'ALL POOLED':<26}{rose['n']:>4}{rose['mean_deg']:>8.1f}°"
            f"{rose['resultant_length']:>7.3f}"
            f"{rose['circular_sd_deg']:>8.1f}°{rose['uniformity_p']:>11.2g}")
        ax.text(0.0, 1.0, "\n".join(lines), transform=ax.transAxes,
                va="top", ha="left", family="monospace",
                fontsize=8.6 * args.font_scale)
        ax.text(0.0, 0.0,
                "R: 0 = spread evenly, 1 = all identical.  uniform p: against "
                "uniform over the\nreachable quadrant, by KS — NOT a Rayleigh "
                "test, which is significant here by construction.",
                transform=ax.transAxes, va="bottom", ha="left",
                fontsize=7.6 * args.font_scale, color="#555555")

    _legend(fig, events, args)
    fig.suptitle(
        "Spike-drop gradient roses — ray angle is the falling edge, "
        "ray length is how many spikes share it",
        fontsize=14, y=0.975)
    return fig, {"raw": raw, "shape": shape}


# -- 6. distance heatmaps --------------------------------------------------

def plot_cross_scale_figure(clustering, args):
    """`family_search.plot_cross_scale`, reused verbatim on drop events.

    Not reimplemented: the third panel it draws - native-length minus
    scale-invariant - is exactly the "same shape at a different duration"
    control this pipeline's cross-dataset claim needs, and it already
    exists. The only work here is building the two matrices and the
    labels it expects.
    """
    from Pipelines.motif_report.family_search import plot_cross_scale

    waveforms = clustering["waveforms"]
    events = clustering["events"]
    D = dc.distance_matrix(waveforms, metric=DISTANCE_SCALE_INVARIANT)
    control = dc.distance_matrix(waveforms, metric=DISTANCE_NATIVE_LENGTH)
    labels = [f"c{lab} r{e['recording_id']} {e['onset_h']:.2f}h"
              for e, lab in zip(events, clustering["labels"])]
    lengths_min = [float(e["fall_duration_s"]) / 60.0 for e in events]
    return plot_cross_scale(D, labels, lengths_min, control=control,
                            lw_scale=args.linewidth, font_scale=args.font_scale)


# -- orchestration ---------------------------------------------------------

def write_all(clustering, out_dirs, args, *, out_dir=None, scope="pooled",
              pooled=True):
    """Every figure for one scope.

    `pooled=False` is a single span clustered on its own; `pooled=True` is
    the cross-span set. The split-by-span cluster overlays are drawn only
    in the pooled scope, where they have more than one group to split.
    """
    plt = _pyplot()
    target = out_dir or args.plot_dir
    snippets = {}
    for d in out_dirs:
        snippets.update(ds.load_snippets(d))

    os.makedirs(target, exist_ok=True)
    written = []

    for d in out_dirs:
        manifest = ds.load_manifest(d)
        if manifest["empty"]:
            print(f"  {d}: empty run, no overview figure to draw")
            continue
        key = manifest.get("span_key") or str(manifest["recording"]["id"])
        fig = plot_detection_overview(d, args)
        written += _save(fig, target, f"overview_{key}", args)
        plt.close(fig)

    n_leaves = len(clustering["events"])
    style = args.dendrogram_style
    if style == "auto":
        style = "thumbnails" if n_leaves <= THUMBNAIL_LEAF_LIMIT else "panels"
    print(f"  dendrogram style: {style} ({n_leaves} leaves; "
          f"thumbnails are used at or below {THUMBNAIL_LEAF_LIMIT})")

    if style == "thumbnails":
        fig = plot_dendrogram_hero(clustering, snippets, args)
        written += _save(fig, target, "dendrogram_hero", args)
        plt.close(fig)

    # The fallback is written every time, not only when the hero is
    # skipped: it costs one figure and it is the layout that survives
    # being shrunk into a two-column paper.
    fig = plot_dendrogram_panels(clustering, snippets, args)
    written += _save(fig, target, "dendrogram_panels", args)
    plt.close(fig)

    # The rose is drawn every run, not only under --export-all: it is a
    # one-picture summary of the whole event set and costs one figure.
    events = clustering["events"]
    fig, roses = plot_rose_figure(events, snippets, args, pooled=pooled)
    written += _save(fig, target, "gradient_rose", args)
    plt.close(fig)
    _write_rose_summary(roses, target)

    if args.export_all:
        labels = np.asarray(clustering["labels"])
        for cluster_id in sorted(set(labels.tolist())):
            fig = plot_cluster_overlay(clustering, snippets, cluster_id, args)
            written += _save(fig, target, f"cluster_{cluster_id}", args)
            plt.close(fig)

            # Split by span: only meaningful where a cluster actually HAS
            # more than one span in it, which in practice means the pooled
            # scope. On a shared absolute-time axis a 200 s fall and a 9 s
            # icicle cannot both be legible, so each span gets its own
            # panel and its own x range while sharing the y axis.
            members = [e for e, lab in zip(clustering["events"], labels)
                       if lab == cluster_id]
            spans = {e.get("span_key", e["source_file"]) for e in members}
            if len(spans) > 1:
                fig = plot_cluster_overlay_by_span(
                    clustering, snippets, cluster_id, args)
                written += _save(fig, target,
                                 f"cluster_{cluster_id}_by_span", args)
                plt.close(fig)

        fig, _ = plot_cluster_roses(clustering, snippets, args)
        written += _save(fig, target, "gradient_rose_by_cluster", args)
        plt.close(fig)

        # The pairwise heatmap is O(n^2) in BOTH distance calls and in the
        # rendered cell count. At 191 pooled events it is 36k cells with
        # unreadable tick labels and takes minutes; it stays a per-span
        # figure, where n is tens and the labels can be read.
        if len(clustering["events"]) <= CROSS_SCALE_MAX_EVENTS:
            fig = plot_cross_scale_figure(clustering, args)
            written += _save(fig, target, "cross_scale", args)
            plt.close(fig)
        else:
            print(f"  cross_scale skipped: {len(clustering['events'])} events "
                  f"exceeds the {CROSS_SCALE_MAX_EVENTS}-event legibility cap")

    print(f"  {len(written)} file(s) written to {target}")
    for path in written:
        if path.endswith(".png"):
            print(f"    {os.path.basename(path)}")
    return written
