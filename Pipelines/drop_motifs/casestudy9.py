"""
casestudy9.py
==============
The drop_motifs9 pipeline drawn out end to end for ONE window, so a reader
of the report can see what every stage actually did rather than take the
pooled figures on trust.

Three figures:

    casestudy_01_pipeline.png    raw -> preprocessing -> dSAX staging ->
                                 detections, one panel per stage, all on
                                 one shared time axis
    casestudy_02_clustering.png  every motif in the window, the feature
                                 vectors the clusterer actually sees, the
                                 full distance matrix, and the tree
    casestudy_03_fall_angle.png  where the onset, the trough and the
                                 steepest sample are on a real motif, and
                                 how those become one angle on the rose

Everything is RECOMPUTED here by calling the same functions the run calls
- `passes6.run_base`, `detect5.stage_letters`, `cluster.feature_matrix`,
`gradients.fall_gradients`. Nothing is re-implemented for the picture, so
a figure that disagrees with the pipeline is a bug in the pipeline, not a
lie in the illustration.

Two things worth knowing before reading the figures
---------------------------------------------------
DSAX IS REAL HERE, AT k=3. `detect5` does not use dSAX's five-symbol
alphabet: `_quantile_cutlines` honours `same_fraction` only at k=3, so
`dsax(alphabet_size=5)` would silently redefine the one parameter that has
been tuned per recording. Instead dSAX runs at k=3 - exactly as the older
`detect.py` runs it - and the D and U bands are then split by the MAD
noise floor into `d`/`D` and `U`/`u`. Panel C draws both readings, because
the split is the step that turns "going down" into "going down faster than
the noise", which is the claim the detector gates on.

THE TREE'S DISTANCE IS NOT `cluster.distance_matrix`. `build_linkage` runs
Ward over the FEATURE matrix - each motif resampled to 200 samples and
z-normalised - so the distance the tree actually minimises is plain
Euclidean between those vectors. `cluster.distance_matrix` is a separate
utility with a different (scale-invariant, length-normalised) metric and
is NOT what produced `ALL_dendrogram.png`. Figure 2 shows the real one and
says so, because showing the other would explain the wrong algorithm
convincingly.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Arc, Rectangle
from scipy.cluster.hierarchy import dendrogram
from scipy.spatial.distance import pdist, squareform

from Pipelines.drop_motifs import clusterfigs9 as cf9
from Pipelines.drop_motifs import passes6, passes7, style7
from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import detect5
from Working.Detection.drop_motifs import gradients as dg

# The five stages, in the order they are drawn, with a diverging ramp:
# falls warm, rises cool, SAME neutral. Deliberately NOT the family ramp -
# a stage is not a family and the two must not look alike.
STAGE_COLOURS = {
    detect5.FAST_DOWN: "#8c2d04",
    detect5.DOWN: "#e08214",
    detect5.SAME: "#d9d9d9",
    detect5.UP: "#8da0cb",
    detect5.FAST_UP: "#2c4f9e",
}
STAGE_ORDER = (detect5.FAST_DOWN, detect5.DOWN, detect5.SAME,
               detect5.UP, detect5.FAST_UP)
STAGE_TITLES = {
    detect5.FAST_DOWN: "d  fast down",
    detect5.DOWN: "D  down",
    detect5.SAME: "S  same",
    detect5.UP: "U  up",
    detect5.FAST_UP: "u  fast up",
}

PASS_MARKERS = {"base": "o", "fine": "s", "sens": "^", "micro": "D"}

# Above this many events in one pipeline panel, only every tenth is named.
# See the annotate call in `plot_pipeline`.
LABEL_EVERY_UP_TO = 45


# ===========================================================================
# recompute one window, exactly as the run does
# ===========================================================================

def replay_window(x_channel, fs, start, end, *, catalogue_id, recording_id,
                  source_file, channel, span_key, span_label, max_passes=3):
    """Everything figure 1 needs, from the same calls `passes9` makes.

    Returns a dict carrying the window samples, the base pass's tuned
    params and result, the staging details, and the multi-pass detections
    with their per-pass identity.
    """
    segment = np.asarray(x_channel[start:end], dtype=float)

    # The base pass, which is what chooses the scale everything else is
    # measured against.
    base = passes6.run_base(segment, fs, max_passes=max_passes)
    params = base.result.params

    # The staging, recomputed so its intermediate arrays are available.
    # `detect5.stage_letters` is the function the detector itself calls.
    letters, details = detect5.stage_letters(segment, fs, params)

    # The full multi-pass detection for this window, drops only - the same
    # call `passes9.detect_sliding` makes per window.
    rows, arrays, info = passes7.detect_multiscale(
        segment, fs, catalogue_id=catalogue_id, recording_id=recording_id,
        source_file=source_file, channel=channel, span_offset=start,
        span_label=span_label, span_key=span_key, max_passes=max_passes,
        fine=True, sensitive=True, micro=True, inverted=False)

    return dict(segment=segment, fs=float(fs), start=int(start),
                end=int(end), base=base, params=params, letters=letters,
                details=details, rows=rows, arrays=arrays, info=info)


# ===========================================================================
# figure 1 — the pipeline
# ===========================================================================

def plot_pipeline(replay, x_channel, out_path, *, title, family_of=None,
                  kept_ids=None, store_rows=None):
    """Raw -> preprocessed -> dSAX staged -> detected, on one time axis.

    `family_of` maps event_id to the pooled family number, so the reader
    can carry a colour from this figure into `ALL_dendrogram.png`.
    `kept_ids` are the detections that survived cross-window dedup; the
    rest are drawn hollow, because "found here but a better-framed copy
    won" is part of the process and hiding it would overstate the window.

    `store_rows` REPLACES the replayed detections in STEP 4 with rows from
    a finished store. Added for drop_motifs12a, whose work order asks for
    the oyster pipeline plots "from the detections already in the store,
    redrawn, not re-detected". Steps 0-3b are still recomputed - they have
    to be, since the store carries no staging - but what is shaded is then
    the shipped store rather than a fresh detection that may not agree with
    it. Their `onset_idx` must be in the SAME FRAME as the replay's, which
    means replaying with the span's absolute bounds rather than from zero.
    Default `None` keeps every existing caller's behaviour unchanged.
    """
    style7.apply_style()
    fs = replay["fs"]
    segment = replay["segment"] * 1000.0          # mV, as the store stores
    details = replay["details"]
    detrended = np.asarray(details["x_detrended"], dtype=float) * 1000.0
    letters = replay["letters"]
    start, end = replay["start"], replay["end"]
    t = (np.arange(len(segment)) + start) / fs

    fig = plt.figure(figsize=(17.5, 10.8))
    gs = fig.add_gridspec(
        6, 1, height_ratios=[0.7, 2.2, 2.2, 1.4, 1.5, 2.5], hspace=0.38,
        left=0.06, right=0.985, top=0.975, bottom=0.055)
    ax_loc = fig.add_subplot(gs[0])
    ax_raw = fig.add_subplot(gs[1])
    ax_pre = fig.add_subplot(gs[2], sharex=ax_raw)
    ax_sax = fig.add_subplot(gs[3], sharex=ax_raw)
    ax_slope = fig.add_subplot(gs[4], sharex=ax_raw)
    ax_det = fig.add_subplot(gs[5], sharex=ax_raw)

    # -- 0. where in the channel ------------------------------------------
    whole = np.asarray(x_channel, dtype=float) * 1000.0
    n_whole = len(whole)
    t_lo, t_hi, reduced = _context_strip(ax_loc, whole, fs)
    ax_loc.add_patch(Rectangle(
        (start / fs, float(np.nanmin(whole))), (end - start) / fs,
        float(np.ptp(whole)), facecolor="#d95f02", alpha=0.30,
        edgecolor="#d95f02", lw=1.2, zorder=3))
    ax_loc.set_xlim(t_lo, t_hi)
    ax_loc.set_ylabel("mV", fontsize=9)
    ax_loc.tick_params(labelsize=8)
    ax_loc.set_title("Step 0", fontsize=10, loc="left", fontweight="bold")

    # -- A. the raw window -------------------------------------------------
    ax_raw.plot(t, segment, lw=1.3, color="#222222")
    ax_raw.set_ylabel("Amplitude (mV)", fontsize=10)
    ax_raw.tick_params(labelsize=8)
    ax_raw.set_title("Step 1", fontsize=10, loc="left", fontweight="bold")
    ax_raw.grid(alpha=0.18)

    # -- B. preprocessing --------------------------------------------------
    baseline = segment - detrended
    # The detrended trace is an order of magnitude smaller than the raw one
    # it came from, so sharing one y-axis flattens it into a line. It gets
    # its own axis, coloured to match, and both are labelled in their own
    # units - the alternative (one axis) hides the very thing this panel
    # exists to show.
    ax_pre.plot(t, segment, lw=0.9, color="0.70", label="raw")
    ax_pre.plot(t, baseline, lw=1.8, color="#d95f02",
                label=f"rolling baseline "
                      f"({replay['params'].detrend_window_s:g} s median)")
    ax_pre.set_ylabel("Amplitude (mV)", fontsize=10, color="0.35")
    ax_pre.tick_params(axis="y", labelcolor="0.35", labelsize=8)
    ax_pre.tick_params(axis="x", labelsize=8)

    ax_pre2 = ax_pre.twinx()
    ax_pre2.plot(t, detrended, lw=1.5, color="#1b6ca8",
                 label="detrended = raw − baseline")
    ax_pre2.axhline(0.0, color="#1b6ca8", lw=0.7, ls="--", alpha=0.6)
    ax_pre2.set_ylabel("Detrended (mV)", fontsize=10, color="#1b6ca8")
    ax_pre2.tick_params(axis="y", labelcolor="#1b6ca8", labelsize=8)
    ax_pre2.spines["right"].set_color("#1b6ca8")
    handles = ax_pre.get_legend_handles_labels()
    handles2 = ax_pre2.get_legend_handles_labels()
    ax_pre.legend(handles[0] + handles2[0], handles[1] + handles2[1],
                  fontsize=8, frameon=False, ncol=3, loc="upper center",
                  bbox_to_anchor=(0.5, -0.05))
    ax_pre.set_title("Step 2", fontsize=10, loc="left", fontweight="bold")
    ax_pre.grid(alpha=0.18)

    # -- C. the dSAX staging ----------------------------------------------
    sps = int(details["samples_per_symbol"])
    three = details["three_stage_letters"]
    n_seg = len(letters)
    seg_edges = start + np.arange(n_seg + 1) * sps

    for i, letter in enumerate(letters):
        left_t = seg_edges[i] / fs
        width = (seg_edges[i + 1] - seg_edges[i]) / fs
        ax_sax.add_patch(Rectangle((left_t, 0.55), width, 0.42,
                                   facecolor=STAGE_COLOURS[letter],
                                   edgecolor="white", lw=0.4))
        ax_sax.add_patch(Rectangle(
            (left_t, 0.06), width, 0.42,
            facecolor=STAGE_COLOURS[three[i]] if i < len(three) else "0.9",
            edgecolor="white", lw=0.4))
    ax_sax.set_ylim(0, 1.05)
    ax_sax.set_yticks([0.27, 0.76])
    ax_sax.set_yticklabels(["dSAX k=3\n(D S U)", "5 stages\n(d D S U u)"],
                           fontsize=8)
    ax_sax.set_title("Step 3", fontsize=10, loc="left", fontweight="bold")
    ax_sax.grid(False)
    handles = [Rectangle((0, 0), 1, 1, facecolor=STAGE_COLOURS[s])
               for s in STAGE_ORDER]
    ax_sax.legend(handles, [STAGE_TITLES[s] for s in STAGE_ORDER],
                  fontsize=8, frameon=False, ncol=5,
                  loc="upper center", bbox_to_anchor=(0.5, -0.12))

    # -- C2. what the split is made of ------------------------------------
    slopes = np.asarray(details["segment_slopes"], dtype=float) * 1000.0
    cut = float(details["fast_cut_raw"]) * 1000.0
    sigma = float(details["sigma_slope"]) * 1000.0
    centres = (seg_edges[:-1] + seg_edges[1:]) / 2.0 / fs
    ax_slope.bar(centres, slopes[:n_seg], width=sps / fs * 0.9,
                 color=[STAGE_COLOURS[c] for c in letters],
                 edgecolor="white", linewidth=0.4)
    ax_slope.axhline(0.0, color="0.4", lw=0.7)
    for sign, label in ((-1, f"−{replay['params'].slope_sigma:g}σ = "
                             f"{-cut:.3g} mV/s"),
                        (+1, f"+{replay['params'].slope_sigma:g}σ = "
                             f"{cut:.3g} mV/s")):
        ax_slope.axhline(sign * cut, color="#8c2d04" if sign < 0 else "#2c4f9e",
                         lw=1.2, ls="--", alpha=0.9,
                         label=label if sign < 0 else label)
    ax_slope.set_ylabel("Slope (mV/s)", fontsize=10)
    ax_slope.tick_params(labelsize=8)
    ax_slope.legend(fontsize=8, frameon=False, ncol=2, loc="upper center",
                    bbox_to_anchor=(0.5, -0.09))
    ax_slope.set_title("Step 3b", fontsize=10, loc="left", fontweight="bold")
    ax_slope.grid(alpha=0.18, axis="y")

    # -- D. the detections -------------------------------------------------
    ax_det.plot(t, detrended, lw=1.1, color="#333333", zorder=2)
    from_store = store_rows is not None
    kept_ids = set() if from_store else set(kept_ids or [])
    rows = sorted(store_rows if from_store else replay["rows"],
                  key=lambda r: int(r["onset_idx"]))
    for index, row in enumerate(rows):
        onset = int(row["onset_idx"])
        trough = int(row["trough_idx"])
        survived = (not kept_ids) or (row["event_id"] in kept_ids)
        family = (family_of or {}).get(row["event_id"])
        if family is not None:
            _, cmap = style7.family_ramp(int(family) - 1)
            colour = cmap(0.75)
        else:
            colour = "#2ca25f"
        ax_det.axvspan(onset / fs, trough / fs,
                       color=colour, alpha=0.30 if survived else 0.10,
                       zorder=1)
        y_on = detrended[onset - start] if 0 <= onset - start < len(detrended) else 0.0
        ax_det.plot([onset / fs], [y_on],
                    marker=PASS_MARKERS.get(row["pass_key"], "o"),
                    ms=7, mfc=colour if survived else "none",
                    mec=colour, mew=1.5, zorder=6)
        # Two rows of labels, alternating, so consecutive detections a
        # second apart do not print on top of each other.
        #
        # Above `LABEL_EVERY_UP_TO` events the alternation stops being
        # enough and the labels become a grey band across the panel:
        # measured on catalogue ID 24, 117 events over 60 hours, where
        # M0-M116 overprint each other and hide the trace they annotate.
        # Past that only every tenth is named, which still lets a reader
        # count along to any event, and the title says the labels are
        # thinned so a missing "M53" is not read as a missing detection.
        if len(rows) <= LABEL_EVERY_UP_TO or index % 10 == 0:
            ax_det.annotate(f"M{index}", (onset / fs, y_on),
                            textcoords="offset points",
                            xytext=(0, 7 if index % 2 == 0 else 14),
                            ha="center", fontsize=7, color=colour,
                            fontweight="bold")
    ax_det.set_ylabel("Amplitude (mV)", fontsize=10)
    ax_det.set_xlabel("Time (s)", fontsize=10)
    ax_det.tick_params(labelsize=8)
    ax_det.grid(alpha=0.18)
    # Extra headroom above the trace: the alternating M-labels are offset in
    # fixed POINTS, which does not shrink with the axes, so a tightly
    # squeezed panel needs a wider autoscale margin or the top row clips
    # against the panel above.
    ax_det.margins(y=0.30)

    per_pass = {k: sum(1 for r in rows if r["pass_key"] == k)
                for k in PASS_MARKERS}
    ax_det.set_xlim(t[0], t[-1])
    shape = _panel_event_shape(ax_det, rows, fs)
    ax_det.set_title("Step 4", fontsize=10, loc="left", fontweight="bold")

    for ax in (ax_raw, ax_pre, ax_sax, ax_slope):
        ax.tick_params(labelbottom=False)

    fig.savefig(out_path, dpi=180)
    plt.close(fig)
    return str(out_path), {"n_detected": len(rows), "n_segments": n_seg,
                           "samples_per_symbol": sps,
                           "sigma_slope_mv_s": sigma,
                           "fast_cut_mv_s": cut,
                           "rows_from_store": bool(from_store),
                           "panel_event_shape": shape,
                           "letters": letters}



# Above this many samples, STEP 0's context strip is drawn as an envelope.
# Chosen well above any per-pixel need (a 16-inch strip at 180 dpi is 2880
# columns) and well below the point where matplotlib's line simplification
# stops coping: a Lion's mane channel is 22.9 million samples.
CONTEXT_MAX_POINTS = 200_000
CONTEXT_COLUMNS = 4_000


def _context_strip(ax, whole_mv, fs):
    """Draw STEP 0's whole-channel strip. `(t_lo, t_hi, was_reduced)`.

    Under `CONTEXT_MAX_POINTS` this is the plain line every earlier run
    drew. Over it, the channel is drawn as the MIN AND MAX of each pixel
    column instead - the same rule `regionfigs12.envelope` uses, and for the
    same reason: a stride is a resample and would drop narrow events out of
    the context strip, which is the one panel whose job is to show that the
    window is not the whole story.

    It is also simply not drawable otherwise. Fig2A's channel is 12,001
    samples and an M2_aug channel is 2.6 million; a Lion's mane channel is
    22.9 million, and asking matplotlib for a 22.9-million-point line takes
    longer than the detection did.
    """
    n = len(whole_mv)
    t_hi = (n - 1) / fs if n else 0.0
    if n <= CONTEXT_MAX_POINTS:
        ax.plot(np.arange(n) / fs, whole_mv, lw=0.4, color="0.55")
        return 0.0, t_hi, False

    edges = np.linspace(0, n, CONTEXT_COLUMNS + 1).astype(np.int64)
    lo = np.empty(CONTEXT_COLUMNS)
    hi = np.empty(CONTEXT_COLUMNS)
    for i in range(CONTEXT_COLUMNS):
        block = whole_mv[edges[i]:edges[i + 1]]
        if block.size:
            lo[i], hi[i] = block.min(), block.max()
        else:
            lo[i] = hi[i] = np.nan
    centres = (edges[:-1] + edges[1:]) / 2.0 / fs
    ax.fill_between(centres, lo, hi, color="0.55", lw=0.0)
    return 0.0, t_hi, True


def _panel_event_shape(ax, rows, fs):
    """How tall the median event is drawn against how wide, and the scale.

    Drawing rule 3 of the drop_motifs12a work order asks every figure to
    STATE its millivolt-per-second, in the form "1 mV drawn as 11.3 s of
    width", and to check that the median event lands between 1:1 and 3:1
    height-to-width.

    The pipeline figure is the one place that rule cannot also be ENFORCED,
    and the reason is structural rather than a preference: six panels share
    one time axis so that a reader can carry a moment down the page from
    the raw trace to the detection, and `set_aspect` reshapes the box,
    which would give each panel a different width and break exactly that.
    So this measures and reports rather than locking, and says which way
    the panel is out. Rule 4 - "a drop must look like a drop" - only
    forbids the FLAT direction, and that is the direction the caption
    calls out.

    `style7.aspect_caption` writes the sentence, so this figure and the
    locked-aspect overlays state the scale in the same words.
    """
    width_in, height_in = ax.get_window_extent().transformed(
        ax.figure.dpi_scale_trans.inverted()).size
    seconds = float(np.ptp(ax.get_xlim()))
    span_mv = float(np.ptp(ax.get_ylim()))
    if not rows or seconds <= 0 or span_mv <= 0 or width_in <= 0:
        return {"caption": "aspect not measurable — no events in this panel"}

    seconds_per_inch = seconds / width_in
    mv_per_inch = span_mv / height_in
    # Seconds of width that one millivolt of height occupies on this page.
    mv_as_seconds = seconds_per_inch / mv_per_inch

    depths = np.abs([float(r["drop_depth_mv"]) for r in rows])
    falls = np.abs([(int(r["trough_idx"]) - int(r["onset_idx"])) / float(fs)
                    for r in rows])
    good = np.isfinite(depths) & np.isfinite(falls) & (depths > 0) & (falls > 0)
    if not good.any():
        return {"caption": "aspect not measurable — no sized events"}

    ratio = float(np.median((depths[good] / mv_per_inch)
                            / (falls[good] / seconds_per_inch)))
    if ratio < 1.0:
        verdict = (f"FLATTER than 1:1 — a fall this shallow on the page is "
                   f"the failure drawing rule 4 names")
    elif ratio > 3.0:
        verdict = "taller than the 1:1–3:1 target, not flatter"
    else:
        verdict = "inside the 1:1–3:1 target"
    return {
        "mv_as_seconds": float(mv_as_seconds),
        "median_height_to_width": ratio,
        "seconds_per_inch": float(seconds_per_inch),
        "mv_per_inch": float(mv_per_inch),
        "in_target": bool(1.0 <= ratio <= 3.0),
        "caption": (
            f"{style7.aspect_caption(mv_as_seconds)}  ·  the median event is "
            f"drawn at {ratio:.2f}:1 height-to-width ({verdict})  ·  "
            "measured, not locked: six panels share one time axis"),
    }


# ===========================================================================
# figure 2 — how the clustering sees these motifs
# ===========================================================================

def plot_clustering(rows, snippets, out_path, *, title, family_of=None):
    """The motifs, the feature vectors, the distance matrix, and the tree.

    The distance drawn is the one `cluster.build_linkage` actually
    minimises: Euclidean between 200-sample resampled, z-normalised
    vectors. See the module docstring.
    """
    style7.apply_style()
    rows = sorted(rows, key=lambda r: int(r["onset_idx"]))
    waveforms = [dc.event_waveform(snippets, r) for r in rows]
    features = dc.feature_matrix(waveforms)
    n = len(rows)
    if n < 3:
        return None, {"reason": f"only {n} motifs in this window"}

    condensed = pdist(features, metric="euclidean")
    D = squareform(condensed)
    Z, cophenetic = dc.build_linkage(features)
    order = dendrogram(Z, no_plot=True)["leaves"]

    # PORTRAIT, and the two waterfalls side by side across the top.
    # Stacked in one narrow column they were wide and short, which flattens
    # every trace - the operator's note that the left-hand plots "look too
# flat". Side by side each gets the full page height for its rows, and
    # the page is now A4-proportioned for the report.
    # THREE rows, no insets. The pair panel was tried as an inset on the
    # tree and covered the very branches it was meant to explain.
    # NARROWER and TALLER again, and the bottom row no longer spans the
    # page. A drop drawn across 13 inches of paper is a gentle slope; the
    # whole point of these panels is that a drop looks like a drop, so the
    # width is spent only where it buys resolution.
    fig = plt.figure(figsize=(11.0, 19.5))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.75, 1.05, 0.70],
                          hspace=0.28, wspace=0.24,
                          left=0.085, right=0.955, top=0.900, bottom=0.045)
    ax_raw = fig.add_subplot(gs[0, 0])
    ax_feat = fig.add_subplot(gs[0, 1])
    ax_tree = fig.add_subplot(gs[1, 0])
    ax_mat = fig.add_subplot(gs[1, 1])
    ax_pairs = fig.add_subplot(gs[2, 0])

    def colour_of(index):
        family = (family_of or {}).get(rows[index]["event_id"])
        if family is None:
            return "#777777"
        _, cmap = style7.family_ramp(int(family) - 1)
        return cmap(0.75)

    # Panels 1, 2 and 5 are all drawn in TREE LEAF ORDER, top to bottom, so
    # a row is the same motif in all three and the reader can carry one
    # motif across the whole figure. Overlaying seventeen traces instead -
    # which is what this first drew - is unreadable and hides exactly the
    # per-motif comparison the figure is for.
    grid = np.linspace(0, 1, features.shape[1])

    def waterfall(ax, curves, step, *, xs=None, annotate=None):
        for slot, index in enumerate(order):
            offset = -slot * step
            values = np.asarray(curves[index], dtype=float)
            x = xs if xs is not None else np.arange(len(values)) / float(
                rows[index]["fs"])
            ax.plot(x, values + offset, lw=1.2, color=colour_of(index))
            ax.axhline(offset, color="0.85", lw=0.5, zorder=0)
            ax.text(-0.012, offset, f"M{index}", transform=ax.get_yaxis_transform(),
                    ha="right", va="center", fontsize=7,
                    color=colour_of(index), fontweight="bold")
            if annotate:
                # Inside the axes, right-aligned. Outside, these ran into
                # the next column's y-axis label.
                ax.text(0.995, offset, annotate(index),
                        transform=ax.get_yaxis_transform(), ha="right",
                        va="center", fontsize=6.2, color="0.45",
                        bbox=dict(facecolor="white", edgecolor="none",
                                  alpha=0.75, pad=0.8))
        ax.set_yticks([])
        ax.set_ylim(-(n - 0.4) * step, step)

    # -- 1. as recorded: different sizes, different lengths -----------------
    baselined = [np.asarray(w, dtype=float) - np.asarray(w, dtype=float)[0]
                 for w in waveforms]
    step_raw = float(np.percentile([np.ptp(w) for w in baselined], 75)) or 1.0
    waterfall(ax_raw, baselined, step_raw,
              annotate=lambda i: f"{abs(float(rows[i]['drop_depth_mv'])):.3g} mV, "
                                 f"{len(waveforms[i])} samples")
    ax_raw.set_xlabel("seconds from the start of each motif's own window",
                      fontsize=8.5)
    ax_raw.set_title(
        "1. the motifs as stored — different depths AND different lengths,\n"
        "   so they cannot yet be compared sample against sample\n"
        "   (rows in tree order; same order in panels 2 and 5)",
        fontsize=9.5, loc="left")
    ax_raw.grid(alpha=0.18, axis="x")

    # -- 2. what the clusterer sees ---------------------------------------
    waterfall(ax_feat, features, 4.0, xs=grid)
    ax_feat.set_xlabel("normalised position through the motif (0 → 1)",
                       fontsize=8.5)
    ax_feat.set_title(
        f"2. the FEATURE vectors — each motif resampled to "
        f"{features.shape[1]} points and z-normalised.\n"
        "   This is the ONLY place normalisation happens; from here on\n"
        "   everything is shape, not millivolts. Note how rows that were\n"
        "   different sizes in panel 1 now look alike.",
        fontsize=9.5, loc="left")
    ax_feat.grid(alpha=0.18, axis="x")

    # -- 3. the tree over just these motifs --------------------------------
    dendro = dendrogram(Z, ax=ax_tree, labels=[f"M{i}" for i in range(n)],
                        leaf_font_size=7.5, color_threshold=0)
    for line in ax_tree.get_lines():
        line.set_color("0.35")
        line.set_linewidth(1.2)
    ax_tree.set_ylabel("Ward merge distance", fontsize=8.5)
    ax_tree.set_title(
        f"3. Ward linkage over those vectors\n"
        f"   cophenetic r = {cophenetic:.3f} — how faithfully the tree's\n"
        f"   distances reproduce the matrix on the right",
        fontsize=9.5, loc="left")
    ax_tree.grid(axis="y", alpha=0.18)
    for label in ax_tree.get_xticklabels():
        index = int(label.get_text()[1:])
        label.set_color(colour_of(index))
        label.set_fontweight("bold")

    # -- 4. the closest and furthest pair, drawn ---------------------------
    iu = np.triu_indices(n, k=1)
    flat = D[iu]
    near = int(np.argmin(flat))
    far = int(np.argmax(flat))
    for (a, b), colour, style, name, value in (
            ((iu[0][near], iu[1][near]), "#1b9e77", "-", "closest pair", flat[near]),
            ((iu[0][far], iu[1][far]), "#b8336a", "--", "furthest pair", flat[far])):
        ax_pairs.plot(grid, features[a], lw=2.0, ls=style, color=colour,
                      label=f"{name}: M{a} vs M{b},  d = {value:.2f}")
        ax_pairs.plot(grid, features[b], lw=2.0, ls=style, color=colour,
                      alpha=0.45)
    ax_pairs.set_xlabel("normalised position", fontsize=8.5)
    ax_pairs.set_ylabel("z-score", fontsize=8.5)
    ax_pairs.legend(fontsize=7.5, frameon=False, loc="best")
    ax_pairs.set_title(
        "4. what a distance means: the most and least alike pair.\n"
        "   d is the Euclidean distance between the two curves above.",
        fontsize=9.5, loc="left")
    ax_pairs.grid(alpha=0.18)

    # -- 5. the matrix -----------------------------------------------------
    ordered = D[np.ix_(order, order)]
    image = ax_mat.imshow(ordered, cmap="magma_r", interpolation="nearest")
    ax_mat.set_xticks(range(n))
    ax_mat.set_yticks(range(n))
    ax_mat.set_xticklabels([f"M{i}" for i in order], fontsize=7,
                           rotation=90)
    ax_mat.set_yticklabels([f"M{i}" for i in order], fontsize=7)
    for tick, index in zip(ax_mat.get_xticklabels(), order):
        tick.set_color(colour_of(index))
    for tick, index in zip(ax_mat.get_yticklabels(), order):
        tick.set_color(colour_of(index))
    if n <= 20:
        for i in range(n):
            for j in range(n):
                value = ordered[i, j]
                ax_mat.text(j, i, f"{value:.1f}", ha="center", va="center",
                            fontsize=5.6,
                            color="white" if value > ordered.max() * 0.55
                            else "0.15")
    fig.colorbar(image, ax=ax_mat, fraction=0.046, pad=0.03,
                 label="Euclidean distance between feature vectors")
    ax_mat.set_title(
        "5. every pairwise distance, rows and columns in tree order.\n"
        "   Dark blocks on the diagonal ARE the families: motifs that sit\n"
        "   close to each other and far from everything else.",
        fontsize=9.5, loc="left")

    # Wrapped for the narrowed page: as two long lines this ran off both
    # edges once the figure went portrait.
    fig.suptitle(
        f"{title}\n"
        f"{n} motifs from this one window\n"
        "distance shown is the one the tree minimises: Euclidean\n"
        f"between z-normalised, {features.shape[1]}-sample vectors\n"
        "(NOT cluster.distance_matrix, which is a different metric)",
        fontsize=10.5, y=0.995, va="top")
    fig.savefig(out_path, dpi=180)
    plt.close(fig)
    return str(out_path), {
        "n": n, "cophenetic": float(cophenetic),
        "closest_pair": [f"M{iu[0][near]}", f"M{iu[1][near]}",
                         float(flat[near])],
        "furthest_pair": [f"M{iu[0][far]}", f"M{iu[1][far]}",
                          float(flat[far])],
        "distance_min": float(flat.min()), "distance_max": float(flat.max()),
    }


# ===========================================================================
# figure 3 — how one motif becomes one angle
# ===========================================================================

def _anatomy(ax, row, snippet, *, reference=1.0, big=False):
    """Draw one motif with every point the gradient measurement uses."""
    fs = float(row["fs"])
    values = np.asarray(snippet["detrended_mv"], dtype=float)
    onset = int(np.clip(int(row["onset_idx"]) - int(row["snippet_start_idx"]),
                        0, values.size - 1))
    trough = int(np.clip(int(row["trough_idx"]) - int(row["snippet_start_idx"]),
                         0, values.size - 1))
    tt = (np.arange(values.size) - onset) / fs

    # The measurement, from the pipeline's own function.
    measured = dg.fall_gradients(values, fs, onset, trough)
    derivative = np.gradient(values) * fs
    if trough > onset:
        steepest = onset + int(np.argmin(derivative[onset:trough + 1]))
    else:
        steepest = onset

    ax.plot(tt, values, lw=2.0, color="#222222", zorder=4)
    ax.axvspan(tt[onset], tt[trough], color="#d95f02", alpha=0.12, zorder=1)

    # The three marks. On a short fall the steepest sample IS the onset, so
    # the steepest marker is drawn large and HOLLOW underneath: a
    # coincident onset dot then sits visibly inside it instead of
    # disappearing under a filled diamond.
    ax.plot([tt[steepest]], [values[steepest]], marker="D", ms=13,
            mfc="none", mec="#7570b3", mew=2.2, zorder=7)
    ax.plot([tt[trough]], [values[trough]], marker="o", ms=9,
            mfc="#b8336a", mec="white", mew=1.4, zorder=8)
    ax.plot([tt[onset]], [values[onset]], marker="o", ms=8,
            mfc="#1b9e77", mec="white", mew=1.3, zorder=9)

    # the chord (mean slope) and the tangent (max slope)
    ax.plot([tt[onset], tt[trough]], [values[onset], values[trough]],
            lw=1.6, ls="--", color="#b8336a", alpha=0.95, zorder=5)
    # Short enough to read as a tangent AT the steepest sample rather than
    # as a line through the whole panel: at 0.45 of the fall it ran off
    # both ends and dominated the motif it was annotating.
    reach = max((tt[trough] - tt[onset]) * 0.16, 1.0 / fs)
    tangent_t = np.array([tt[steepest] - reach, tt[steepest] + reach])
    tangent_y = values[steepest] + measured["max_slope_mv_s"] * (
        tangent_t - tt[steepest])
    ax.plot(tangent_t, tangent_y, lw=2.2, color="#7570b3", zorder=6,
            path_effects=[path_effects.Stroke(linewidth=4.2,
                                              foreground="white"),
                          path_effects.Normal()])

    angle_deg = np.rad2deg(dg.slope_angle(measured["max_slope_mv_s"],
                                          reference))
    if big:
        # DELIBERATELY NO TEXT ON THE TRACE. Six labelled arrows over one
        # small drop buried the drop itself; the operator's note was that
        # panel A was "overwhelming". Every quantity that used to be
        # annotated here is now spelled out in the figure legend, which can
        # be as verbose as it likes without covering the signal.
        depth = float(values[onset] - values[trough])
        ax.annotate("", xy=(tt[trough], values[trough]),
                    xytext=(tt[trough], values[onset]), zorder=10,
                    arrowprops=dict(arrowstyle="<->", color="#0f7b6c",
                                    lw=2.0, shrinkA=0, shrinkB=0))
        ax.plot([tt[onset], tt[trough]], [values[onset]] * 2, lw=1.0,
                ls=":", color="#0f7b6c", alpha=0.9, zorder=3)
        info = (f"depth {depth:.3g} mV   ·   "
                f"max slope {measured['max_slope_mv_s']:.3g} mV/s  "
                f"({angle_deg:.1f}°)   ·   "
                f"mean slope {measured['mean_slope_mv_s']:.3g} mV/s   ·   "
                f"peakedness {measured['peakedness']:.2f}")
        ax.text(0.5, -0.14, info, transform=ax.transAxes, ha="center",
                va="top", fontsize=9.5, color="0.2")
    ax.axhline(values[onset], color="0.6", lw=0.8, ls=":", zorder=2)
    # Frame the fall, not the whole snippet: a motif carrying seconds of
    # flat context either side leaves the construction a smear in the
    # middle of the axes.
    fall = max(tt[trough] - tt[onset], 1.0 / fs)
    ax.set_xlim(max(float(tt[0]), tt[onset] - 0.7 * fall),
                min(float(tt[-1]), tt[trough] + 0.9 * fall))
    ax.grid(alpha=0.18)
    return measured, angle_deg


def plot_fall_angle(rows, snippets, out_path, *, title, reference=1.0,
                    n_examples=6):
    """One big anatomy panel, a rose-placement panel, and small multiples.

    The examples are chosen across the window's depth range so the reader
    sees the construction on a big drop and on a small one, which is the
    comparison the professor's question turns on.
    """
    style7.apply_style()
    # The SAME two exclusions `clusterfigs9._gradient_table` applies before
    # drawing the rose: a fall under MIN_FALL_SAMPLES has no measurable
    # gradient, and one whose steepest sample is not descending has no
    # angle in the rose's [-90, 0] range. Without the second test this
    # figure would illustrate the construction on an event the rose itself
    # refuses to plot - and it did, at +11 degrees, on CH4 window 5.
    def _falls(row):
        onset = int(row["onset_idx"]) - int(row["snippet_start_idx"])
        trough = int(row["trough_idx"]) - int(row["snippet_start_idx"])
        if trough <= onset:
            return False
        values = np.asarray(snippets[row["event_id"]]["detrended_mv"],
                            dtype=float)
        measured = dg.fall_gradients(values, float(row["fs"]), onset, trough)
        return measured["max_slope_mv_s"] < 0.0

    candidates = [r for r in rows
                  if int(r["trough_idx"]) > int(r["onset_idx"])
                  and float(r["fall_duration_s"]) * float(r["fs"])
                  >= cf9.MIN_FALL_SAMPLES]
    usable = [r for r in candidates if _falls(r)]
    n_not_falling = len(candidates) - len(usable)
    if not usable:
        return None, {"reason": "no motif in this window has a usable fall"}
    usable.sort(key=lambda r: abs(float(r["drop_depth_mv"])))

    n_small = int(min(n_examples, 4, len(usable)))
    fig = plt.figure(figsize=(18.0, 11.0))
    gs = fig.add_gridspec(2, 4, height_ratios=[2.35, 1.15],
                          hspace=0.62, wspace=0.26, left=0.055, right=0.975,
                          top=0.855, bottom=0.115)
    ax_big = fig.add_subplot(gs[0, :2])
    ax_rose = fig.add_subplot(gs[0, 2:], projection="polar")

    # The deepest motif gets the annotated anatomy: the marks are furthest
    # apart there and the labels have room.
    hero = usable[-1]
    measured, angle_deg = _anatomy(ax_big, hero, snippets[hero["event_id"]],
                                   reference=reference, big=True)
    ax_big.set_xlabel("time from onset (s)")
    ax_big.set_ylabel("mV, detrended")
    ax_big.set_title(
        f"A. the anatomy of one fall — {hero['event_id']}\n"
        "every quantity on the rose comes from these three points",
        fontsize=11, loc="left")

    # -- the same event placed on the rose --------------------------------
    ax_rose.set_theta_zero_location("E")
    ax_rose.set_theta_direction(1)
    ax_rose.set_thetamin(-90)
    ax_rose.set_thetamax(0)
    ax_rose.set_xticks(np.deg2rad([-90, -75, -60, -45, -30, -15, 0]))
    ax_rose.set_xticklabels(["-90°\nvertical", "-75°", "-60°", "-45°",
                             "-30°", "-15°", "0°\nflat"], fontsize=8)
    angles, depths = [], []
    for row in usable:
        m = dg.fall_gradients(
            np.asarray(snippets[row["event_id"]]["detrended_mv"], dtype=float),
            float(row["fs"]),
            int(row["onset_idx"]) - int(row["snippet_start_idx"]),
            int(row["trough_idx"]) - int(row["snippet_start_idx"]))
        angles.append(dg.slope_angle(m["max_slope_mv_s"], reference))
        depths.append(abs(float(row["drop_depth_mv"])))
    angles = np.asarray(angles)
    radius = np.linspace(0.35, 1.0, len(angles))
    ax_rose.scatter(angles, radius, s=70,
                    c=depths, cmap="viridis", zorder=6, edgecolor="white",
                    linewidth=0.8)
    ax_rose.scatter([np.deg2rad(angle_deg)], [radius[-1]], s=220,
                    facecolor="none", edgecolor="#7570b3", linewidth=2.4,
                    zorder=7)
    # The ringed marker is identified in the TITLE, not labelled in place:
    # any fixed in-axes position collides with the outer arc or a tick for
    # some angle, and the angle is data-dependent.
    ax_rose.set_yticks([])
    ax_rose.set_title(
        "B. each fall becomes ONE angle; the rose counts them\n"
        f"45° = a fall of exactly {reference:g} mV/s — stated, not implied\n"
        "radius is spacing only; colour is drop height\n"
        f"the ringed marker is panel A's fall, at {angle_deg:.1f}°",
        fontsize=10.5, pad=22)

    # -- small multiples across the depth range ---------------------------
    picks = np.unique(np.linspace(0, len(usable) - 1, n_small).astype(int))
    info_rows = []
    for slot, index in enumerate(picks):
        ax = fig.add_subplot(gs[1, slot])
        row = usable[index]
        m, a = _anatomy(ax, row, snippets[row["event_id"]],
                        reference=reference)
        ax.set_title(f"{abs(float(row['drop_depth_mv'])):.3g} mV  ·  "
                     f"{a:.0f}°", fontsize=9)
        ax.tick_params(labelsize=7)
        if slot == 0:
            ax.set_ylabel("mV", fontsize=8)
        ax.set_xlabel("s from onset", fontsize=8)
        info_rows.append({"event_id": row["event_id"],
                          "depth_mv": abs(float(row["drop_depth_mv"])),
                          "angle_deg": float(a),
                          "max_slope_mv_s": float(m["max_slope_mv_s"]),
                          "peakedness": float(m["peakedness"])})

    legend = [
        Line2D([], [], marker="o", ls="none", mfc="#1b9e77", mec="white",
               ms=9,
               label="ONSET, the 'peak' — walk back from the steepest "
                     "sample while the trace still descends; the last "
                     "point before the fall"),
        Line2D([], [], marker="o", ls="none", mfc="#b8336a", mec="white",
               ms=9,
               label="TROUGH, the 'end of slope' — the first run of 3 "
                     "samples whose gradient exceeds +0.5σ of the "
                     "snippet's slope noise: where recovery begins"),
        Line2D([], [], marker="D", ls="none", mfc="none", mec="#7570b3",
               mew=2.0, ms=11,
               label="STEEPEST SAMPLE and its tangent — arctan(that "
                     "slope / 1 mV per s) is the angle this motif "
                     "contributes to the rose"),
        Line2D([], [], ls="--", color="#b8336a", lw=1.6,
               label="CHORD onset→trough = mean slope, which is exactly "
                     "depth / duration; max ÷ mean is 'peakedness', "
                     "1.0 for a straight fall and higher when front-loaded"),
        Line2D([], [], ls="-", color="#0f7b6c", lw=2.0,
               label="DROP DEPTH = level at onset − level at trough — "
                     "the rose's height axis, and the quantity the "
                     "0.1 mV instrument floor gates on"),
    ]
    fig.legend(handles=legend, fontsize=9, frameon=False, ncol=1,
               loc="lower left", bbox_to_anchor=(0.055, 0.002),
               labelspacing=0.75, handletextpad=1.2)

    # The "C." caption belongs above the row it describes, not stacked
    # under the suptitle where it reads as part of the title.
    fig.text(0.055, 0.372,
             "C. the same construction across the window's depth range — "
             "the smallest drop and the largest are measured identically",
             fontsize=11, ha="left", va="bottom")
    fig.suptitle(
        title
        + (f"\n{n_not_falling} motif(s) in this window excluded: steepest "
           "sample not descending — the same exclusion ALL_rose.png makes"
           if n_not_falling else ""),
        fontsize=12.5, y=0.965)
    fig.savefig(out_path, dpi=180)
    plt.close(fig)
    return str(out_path), {"hero": hero["event_id"],
                           "hero_angle_deg": float(angle_deg),
                           "hero_max_slope_mv_s":
                               float(measured["max_slope_mv_s"]),
                           "n_usable": len(usable),
                           "n_excluded_not_falling": int(n_not_falling),
                           "examples": info_rows}
