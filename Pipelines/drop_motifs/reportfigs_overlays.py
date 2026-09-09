"""
reportfigs_overlays.py
=======================
Report figures 3 and 4: `ID001_overlays.pdf` and `ID385_overlays.pdf`, the
drop_motifs5 span-and-overlay plate redrawn.

    +-------------------------------------------------------------+
    |  the whole span, every detected drop shaded in place         |
    |  (figure 4 adds a strip of inter-drop intervals under it)    |
    +----------------------------+--------------------------------+
    |  baseline removed          |  baseline kept                  |
    |  every drop from y = 0     |  raw millivolts as recorded     |
    +----------------------------+--------------------------------+

The layout is `overlays5.plot_span_and_overlays`'s and so is the reason
for the two lower panels differing in both respects: the left one asks "do
these drops have the same shape", so it removes the baseline and can be
compared by eye; the right one asks "what was actually there", so it keeps
the recorded level and the drift between events stays visible. Amplitude
is never scaled in either - subtracting a constant per trace removes an
offset, which is a different operation from normalising, and it leaves
every depth exactly as measured.

Three things change.

1. The gradient
---------------
`overlays5` coloured by position in the span on `plasma`, which runs
purple to yellow. Yellow is excluded from this report and is also the end
of that ramp carrying the most saturation, so the late events were the
loudest thing on the plate. Colour is now `style6.TIME_CMAP` - deep blue
through teal to green, monotone in luminance so it still reads as an
ordering in greyscale, reaching no excluded hue.

2. The baseline every trace is aligned on
------------------------------------------
`overlays5` subtracted the single sample at the onset. One sample is a
noisy estimate of a level, and on a sharkfin the onset is not quite the
peak, so a few traces sat several millivolts above the rest and the drops
did not start from a common origin. Two rules replace it, chosen per
figure because the two morphologies present different things to align on:

  `peak`     the local maximum in a short window ending at the onset.
             For a sharkfin the peak IS the thing to align, and there is
             no flat stretch before the fall to average over.
  `pre_mean` the mean of the first `BASELINE_WINDOW_S` of the drawn
             window. For a trough the pre-drop level is genuinely flat,
             so an average over it beats any single sample.

3. One window per family, re-cut from the recording
----------------------------------------------------
`overlays5` drew each event over its own stored snippet, and the detector
sizes a snippet from the event, so the traces ended at wildly different
distances and the panel was ragged. Every trace here spans the same
window, still aligned on its own drop onset.

The window cannot be "the smallest stored snippet", which is the obvious
rule and does not survive contact with the data: three of ID 385's
twenty-odd windows start within a second of their own onset, so that
minimum is zero and the figure would have no pre-drop baseline at all.
It is the family's MEDIAN stored extent instead - the framing the
detector typically chose for this family - and the samples to fill it come
off the source recording rather than out of the store. Nothing is
invented: it is the same channel the snippet was cut from, read wider.

And the window is per FAMILY, not per figure. ID 385 holds two clearly
separated populations - fourteen drops of 8.8-9.6 mV and ten of
13.5-14.1 mV, with nothing between - and the deeper family is also the
wider one. Cutting both to the shallower family's extent would clip the
deeper family's recovery, so each family gets its own window and the
figure says so.

Figure 4 also carries the interval strip. See `_interval_strip`.
"""

import numpy as np

from Pipelines.drop_motifs import reportstyle

# The pre-drop stretch `pre_mean` averages over, in seconds. The operator's
# suggestion, and it is comfortably inside every ID 385 window that has a
# baseline at all.
BASELINE_WINDOW_S = 15.0

# `peak` looks back over this fraction of the fall from the onset. Short,
# because the point is to land on the shoulder the fall leaves, not to
# find the largest value anywhere in the approach - on a rising sharkfin
# a long lookback would find nothing earlier than the onset anyway, and on
# a noisy one it would find a spike.
PEAK_LOOKBACK_FALLS = 0.12
PEAK_LOOKBACK_MIN_S = 2.0

IMPURE_COLOUR = "#8A8A8A"
IMPURE_DASH = (0, (4, 2))

LW_TRACE = 1.0
LW_SIGNAL = 0.55


# ==========================================================================
# the common window
# ==========================================================================

def split_families(rows, boundary_mv=None):
    """`{family_label: [rows]}` - one entry, or two split on drop depth.

    `boundary_mv` is stated by the caller and never guessed here. A figure
    that discovered its own families would redraw differently every time
    the store moved, and "two classes" is a claim about this recording that
    belongs in the caller and in the manifest.
    """
    if boundary_mv is None:
        return {"all": list(rows)}
    shallow = [r for r in rows if abs(float(r["drop_depth_mv"])) < boundary_mv]
    deep = [r for r in rows if abs(float(r["drop_depth_mv"])) >= boundary_mv]
    out = {}
    if shallow:
        out["shallow"] = shallow
    if deep:
        out["deep"] = deep
    return out or {"all": list(rows)}


# How far either side of an onset a window may reach, as a fraction of the
# family's SHORTEST inter-onset interval. Asymmetric, because the two sides
# meet different things.
#
# Going back, a window meets this event's own approach - on a sharkfin, the
# rise it falls from, which is the larger half of the motif and belongs on
# the plate. Going forward it meets this event's recovery and then the NEXT
# event's approach, and drawing the neighbour's rise is how an overlay
# comes to show every trace turning upward at the right-hand edge as though
# the drops recovered past their own baseline. They do not; that is the
# next cycle.
PRE_INTERVAL_CAP = 0.75
POST_INTERVAL_CAP = 0.30

# No drop's own trough may fall outside the frame, whatever the caps say.
TROUGH_MARGIN = 1.15


def common_window(rows, fs):
    """`(pre_samples, post_samples)` - the window every trace will span.

    The family's median stored extent either side of the onset - see the
    module docstring for why the median and not the minimum - capped so the
    window cannot reach a neighbouring drop, and floored so it cannot clip
    this family's own longest fall.

    All three parts are needed and each answers a different failure. The
    median alone framed ID 1 over 900 s of recovery on a train whose
    tightest cycle is 917 s, so every trace ran into the next sharkfin's
    rise. The caps alone would frame ID 385 on a 144 s interval and say
    nothing about how wide its drops are. The floor alone cannot choose a
    frame at all.
    """
    pre = [int(r["onset_idx"]) - int(r["snippet_start_idx"]) for r in rows]
    post = [int(r["snippet_end_idx"]) - int(r["onset_idx"]) for r in rows]
    pre_n = int(round(float(np.median(pre))))
    post_n = int(round(float(np.median(post))))

    onsets = sorted(int(r["onset_idx"]) for r in rows)
    gaps = np.diff(onsets) if len(onsets) > 1 else np.array([])
    if gaps.size:
        shortest = float(gaps.min())
        pre_n = min(pre_n, int(round(PRE_INTERVAL_CAP * shortest)))
        post_n = min(post_n, int(round(POST_INTERVAL_CAP * shortest)))

    longest_fall = max(int(r["trough_idx"]) - int(r["onset_idx"])
                       for r in rows)
    post_n = max(post_n, int(round(longest_fall * TROUGH_MARGIN)))
    return max(pre_n, 1), max(post_n, 2)


def recut(row, x_mv, span_offset, pre_n, post_n):
    """`(t_rel_s, mV)` for one event over the common window.

    `x_mv` is the whole span in millivolts and `span_offset` the absolute
    index of its first sample, because store indices are absolute - see
    `DETECTION_AND_FIGURES.md` section 2, which names this the most common
    plotting bug in this package.

    Returns `(None, None)` if the window would run off either end of the
    span. A partial trace here would be exactly the ragged edge this
    function exists to remove.
    """
    onset = int(row["onset_idx"]) - int(span_offset)
    lo, hi = onset - int(pre_n), onset + int(post_n)
    if lo < 0 or hi > len(x_mv):
        return None, None
    values = np.asarray(x_mv[lo:hi], dtype=float)
    t_rel = (np.arange(lo, hi) - onset) / float(row["fs"])
    return t_rel, values


def baseline_of(t_rel, values, row, mode, *, window_s=BASELINE_WINDOW_S):
    """The level a trace is shifted by, under one of the two rules."""
    if mode == "pre_mean":
        # The flat stretch at the START of the drawn window, not the
        # samples just before the onset: on a trough train the approach to
        # the onset is already bending into the fall.
        n = max(2, int(round(window_s * float(row["fs"]))))
        pre = values[:n]
        return float(np.mean(pre)) if pre.size else float(values[0])

    if mode == "peak":
        fall_s = float(row["fall_duration_s"])
        back_s = max(PEAK_LOOKBACK_MIN_S, PEAK_LOOKBACK_FALLS * fall_s)
        inside = (t_rel >= -back_s) & (t_rel <= 0.0)
        if not inside.any():
            inside = t_rel <= 0.0
        return float(np.max(values[inside])) if inside.any() \
            else float(values[0])

    raise ValueError(f"unknown baseline mode {mode!r}")


# ==========================================================================
# the panels
# ==========================================================================

def _span_panel(ax, x_mv, fs, span_offset, rows, colours, *, own_x_axis=True):
    """The whole span, with every detected window shaded where it sits.

    `own_x_axis=False` hands the time axis to the strip below, so the two
    share one set of tick labels instead of printing them twice with a
    band of interval arrows in between.
    """
    t_h = (np.arange(len(x_mv)) + span_offset) / fs / 3600.0
    ax.plot(t_h, x_mv, lw=LW_SIGNAL, color=reportstyle.SIGNAL_COLOUR,
            zorder=3)
    for row, colour in zip(rows, colours):
        start = int(row["snippet_start_idx"]) - span_offset
        end = int(row["snippet_end_idx"]) - span_offset
        pure = bool(row["is_pure"])
        ax.axvspan(t_h[max(0, start)], t_h[min(len(t_h) - 1, end - 1)],
                   color=colour if pure else IMPURE_COLOUR,
                   alpha=0.30 if pure else 0.35, lw=0, zorder=1)
    if own_x_axis:
        ax.set_xlabel("time in recording (h)", fontsize=reportstyle.FS_LABEL)
    else:
        ax.tick_params(labelbottom=False)
    ax.set_ylabel("amplitude (mV, raw)", fontsize=reportstyle.FS_LABEL)
    # A little air on y. Autoscale puts the deepest spike exactly on the
    # frame, and a spike whose tip is the axis line reads as clipped.
    ax.margins(x=0.004, y=0.06)
    ax.grid(alpha=reportstyle.GRID_ALPHA, lw=0.5)


def _interval_strip(ax, rows, *, fs, span_offset, x_len, levels=2,
                    min_gap_pt=3.0):
    """Inter-drop intervals, drawn under the span panel and labelled.

    A strip of its own rather than annotation on the signal: a label placed
    on the trace lands on whatever the trace is doing there, and these
    intervals have to be readable against a signal that is mostly flat with
    tall spikes in it.

    Labels alternate between `levels` heights. Adjacent intervals here
    differ by a factor of six - 144 s next to 781 s - so a single row of
    centred labels collides on the short ones; alternating means a label
    can only meet its second neighbour, which is several hundred seconds
    away. A label with no room even so is dropped and counted, because a
    figure that silently overprints is worse than one that reports a gap.
    """
    t_h = np.array([(int(r["onset_idx"]) - span_offset) / fs / 3600.0
                    for r in rows], dtype=float)
    span_h = (x_len / fs / 3600.0) or 1.0

    # The strip carries the shared time axis, so it keeps its bottom spine
    # and its tick labels and the span panel above it has neither.
    ax.set_ylim(-1.25, 1.25)
    ax.set_yticks([])
    ax.set_xlabel("time in recording (h)", fontsize=reportstyle.FS_LABEL)
    ax.tick_params(labelsize=reportstyle.FS_TICK)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)

    # Points of x per hour, so "will this label fit" is asked in the units
    # the label is measured in.
    ax.figure.canvas.draw()
    box = ax.get_window_extent()
    lo, hi = ax.get_xlim()
    pt_per_h = (box.width * 72.0 / ax.figure.dpi) / ((hi - lo) or span_h)

    # A tick under each drop, joining the strip to the trace above it.
    for at in t_h:
        ax.plot([at, at], [0.72, 1.15], color="0.45", lw=0.7, zorder=2,
                clip_on=False)

    drawn, skipped, intervals = 0, 0, []
    for i in range(len(t_h) - 1):
        a, b = t_h[i], t_h[i + 1]
        seconds = (b - a) * 3600.0
        intervals.append(float(seconds))
        y = 0.30 if i % levels == 0 else -0.62
        ax.annotate("", xy=(b, y), xytext=(a, y),
                    arrowprops=dict(arrowstyle="<->", color="0.45",
                                    lw=0.6, shrinkA=0.0, shrinkB=0.0),
                    zorder=2)
        text = f"{seconds:.0f}"
        # Width of the label against the width of the space it has. The
        # space is its own interval plus, because labels alternate, half of
        # each neighbour's.
        room_h = (b - a)
        if i > 0:
            room_h += (t_h[i] - t_h[i - 1]) * 0.5
        if i + 2 < len(t_h):
            room_h += (t_h[i + 2] - t_h[i + 1]) * 0.5
        need_pt = len(text) * reportstyle.FS_ANNOT * 0.60 + min_gap_pt
        if room_h * pt_per_h < need_pt:
            skipped += 1
            continue
        ax.text((a + b) / 2.0, y, text, ha="center", va="center",
                fontsize=reportstyle.FS_ANNOT, color="0.25", zorder=4,
                bbox=dict(boxstyle="square,pad=0.10", fc="white", ec="none"))
        drawn += 1

    # In the margin the strip's absent y ticks leave free, so it cannot
    # land on an arrow however tight the first interval is.
    ax.text(-0.011, 0.5, "interval\nbetween\ndrops (s)",
            transform=ax.transAxes, ha="right", va="center",
            fontsize=reportstyle.FS_ANNOT, color="0.30", linespacing=1.35)
    return {"n_intervals": len(intervals), "n_labelled": drawn,
            "n_unlabelled_for_room": skipped,
            "label_levels": int(levels),
            "intervals_s": intervals,
            "median_interval_s": (float(np.median(intervals))
                                  if intervals else float("nan"))}


def _overlay_panel(ax, families, x_mv, span_offset, colour_of, *,
                   baseline_mode, remove_baseline, include_impure):
    """One overlay. Every trace aligned on its own drop onset."""
    drawn, refused = 0, 0
    for label, entry in families.items():
        pre_n, post_n = entry["window"]
        for row in entry["rows"]:
            pure = bool(row["is_pure"])
            if not include_impure and not pure:
                continue
            t_rel, values = recut(row, x_mv, span_offset, pre_n, post_n)
            if t_rel is None:
                refused += 1
                continue
            if remove_baseline:
                values = values - baseline_of(t_rel, values, row,
                                              baseline_mode)
            ax.plot(t_rel, values,
                    color=colour_of[row["event_id"]] if pure
                    else IMPURE_COLOUR,
                    linestyle="-" if pure else IMPURE_DASH,
                    lw=LW_TRACE if pure else LW_TRACE * 0.8,
                    alpha=0.9 if pure else 0.6,
                    zorder=3 if pure else 2)
            drawn += 1

    ax.axvline(0.0, color=reportstyle.RULE_COLOUR, ls="--", lw=0.9, zorder=1)
    if remove_baseline:
        ax.axhline(0.0, color=reportstyle.RULE_COLOUR, ls=":", lw=0.8,
                   zorder=1)
    ax.set_xlabel("time from drop onset (s)", fontsize=reportstyle.FS_LABEL)
    ax.grid(alpha=reportstyle.GRID_ALPHA, lw=0.5)
    return drawn, refused


# ==========================================================================
# the plate
# ==========================================================================

def plot_span_and_overlays(x_mv, fs, span_offset, rows, path, *, title,
                           baseline_mode, depth_boundary_mv=None,
                           interval_strip=False, show_overlays=True,
                           proof_png=None, family_labels=None):
    """Figure 3 or figure 4. Returns `(path, manifest)`.

    `show_overlays=False` drops the bottom row - the two `_overlay_panel`
    axes that give this function its name - and leaves just the span panel
    (plus the interval strip, unchanged, when `interval_strip=True`). ID 385
    uses this: with the two families already shown once as an overlay
    elsewhere in the report, this plate's job is the chronology, not a
    second copy of the shape comparison.

    `title` is never drawn - rule 3 keeps process and description off the
    plate - and travels to the manifest instead, so the plate carries only
    axis labels and its data.
    """
    from matplotlib import cm
    from matplotlib import pyplot as plt

    if not rows:
        return None, {"reason": "no events"}
    reportstyle.apply_style()

    rows = sorted(rows, key=lambda r: float(r["onset_h"]))
    onsets_h = [float(r["onset_h"]) for r in rows]
    colours, norm = reportstyle.time_colours(onsets_h)
    colour_of = {r["event_id"]: c for r, c in zip(rows, colours)}

    families = {}
    for label, members in split_families(rows, depth_boundary_mv).items():
        families[label] = {"rows": members,
                           "window": common_window(members, fs)}

    left, right = 0.105, 0.885

    # Every band below is an absolute inch height, chosen for what sits in
    # it rather than a fraction tuned against a suptitle that used to sit
    # above everything. The two `*_axis_room_in` constants are not panels
    # of their own - they are the tick-label-and-xlabel strip under
    # whichever axes owns an x axis (the top block's is the strip if there
    # is one, the span panel otherwise; the bottom block's is each overlay
    # panel's own) - and a plain gap has no such text under it.
    top_margin_in = 0.10
    span_h_in = 1.55
    strip_gap_in = 0.06
    strip_h_in = 0.62
    top_axis_room_in = 0.40
    mid_gap_in = 0.24
    overlay_h_in = 2.75
    overlay_axis_room_in = 0.42
    bottom_margin_in = 0.08

    # Placed with a top-down cursor in inches rather than pre-computed
    # fractions, so a figure with no overlay row is exactly as tall as its
    # own content and not the fraction arithmetic of a taller one.
    strip_block_in = (strip_gap_in + strip_h_in) if interval_strip else 0.0
    fig_h = top_margin_in + span_h_in + strip_block_in + top_axis_room_in
    if show_overlays:
        fig_h += mid_gap_in + overlay_h_in + overlay_axis_room_in
    fig_h += bottom_margin_in

    fig = plt.figure(figsize=(9.6, fig_h))
    cursor_in = fig_h

    cursor_in -= top_margin_in
    span_top = cursor_in / fig_h
    cursor_in -= span_h_in
    span_bottom = cursor_in / fig_h
    # Explicit axes rather than a gridspec, because the interval strip has
    # to sit hard against the span panel above it and share its x range;
    # a gridspec row with its own spacing puts a gap there that reads as a
    # separation between two unrelated things.
    ax_span = fig.add_axes([left, span_bottom, right - left, span_h_in / fig_h])

    ax_strip = None
    if interval_strip:
        cursor_in -= strip_gap_in
        strip_top = cursor_in / fig_h  # noqa: F841 (named for readability)
        cursor_in -= strip_h_in
        strip_bottom = cursor_in / fig_h
        # Directly under it, sharing one time axis: the strip owns the tick
        # labels and the span panel above has none. Two sets of hour labels
        # with a band of arrows between them reads as two figures.
        ax_strip = fig.add_axes([left, strip_bottom, right - left,
                                 strip_h_in / fig_h])
        axis_owner_bottom = strip_bottom
    else:
        axis_owner_bottom = span_bottom

    _span_panel(ax_span, x_mv, fs, span_offset, rows, colours,
                own_x_axis=ax_strip is None)

    strip_info = None
    if ax_strip is not None:
        # The strip inherits the span panel's x limits AFTER that panel has
        # set its own margins, so a tick under a drop is under that drop.
        ax_strip.set_xlim(*ax_span.get_xlim())
        strip_info = _interval_strip(ax_strip, rows, fs=fs,
                                     span_offset=span_offset,
                                     x_len=len(x_mv))
        ax_strip.set_xlim(*ax_span.get_xlim())

    n_pure = sum(1 for r in rows if r["is_pure"])
    n_impure = len(rows) - n_pure

    cursor_in -= top_axis_room_in
    drawn_left = drawn_right = refused_left = refused_right = None
    if show_overlays:
        cursor_in -= mid_gap_in
        lower_top = cursor_in / fig_h
        cursor_in -= overlay_h_in
        bottom = cursor_in / fig_h
        panel_w = (right - left - 0.095) / 2.0
        ax_left = fig.add_axes([left, bottom, panel_w, lower_top - bottom])
        ax_right = fig.add_axes([left + panel_w + 0.095, bottom, panel_w,
                                 lower_top - bottom])

        drawn_left, refused_left = _overlay_panel(
            ax_left, families, x_mv, span_offset, colour_of,
            baseline_mode=baseline_mode, remove_baseline=True,
            include_impure=False)
        ax_left.set_ylabel("amplitude (mV, baseline removed)",
                           fontsize=reportstyle.FS_LABEL)
        ax_left.set_title(f"Drop shape, baseline removed  (n = {drawn_left})",
                          fontsize=reportstyle.FS_TITLE)

        drawn_right, refused_right = _overlay_panel(
            ax_right, families, x_mv, span_offset, colour_of,
            baseline_mode=baseline_mode, remove_baseline=False,
            include_impure=True)
        ax_right.set_ylabel("amplitude (mV, as recorded)",
                            fontsize=reportstyle.FS_LABEL)
        ax_right.set_title(f"Drop shape, recorded level  (n = {drawn_right})",
                           fontsize=reportstyle.FS_TITLE)

        cbar_bottom, cbar_top = bottom, lower_top
    else:
        # No overlay row to pair the colorbar with, so it runs alongside
        # the span (and strip) instead - the same time-to-colour mapping
        # is what shades the span panel's own detection windows.
        cbar_bottom, cbar_top = axis_owner_bottom, span_top

    if norm is not None:
        bar = fig.colorbar(cm.ScalarMappable(norm=norm,
                                             cmap=reportstyle.TIME_CMAP),
                           cax=fig.add_axes([right + 0.028, cbar_bottom,
                                             0.017, cbar_top - cbar_bottom]))
        bar.set_label("onset time in recording (h)",
                      fontsize=reportstyle.FS_LABEL)
        bar.ax.tick_params(labelsize=reportstyle.FS_TICK)

    manifest = {
        "title": title,
        "show_overlays": show_overlays,
        "n_events": len(rows),
        "n_pure": n_pure,
        "n_impure": n_impure,
        "n_drawn_baseline_removed": drawn_left,
        "n_drawn_recorded_level": drawn_right,
        "n_refused_window_off_span": (
            (refused_left + refused_right) if show_overlays else None),
        "baseline_rule": {
            "peak": "the local maximum in a short window ending at the "
                    "onset",
            "pre_mean": f"the mean of the first {BASELINE_WINDOW_S:g} s of "
                        f"the drawn window",
        }[baseline_mode],
        "colour": "position in the recording, on a deep blue to green ramp",
        "amplitude_scaling": "none; the left panel subtracts a constant "
                             "per trace and every depth is as measured",
        "depth_boundary_mv": depth_boundary_mv,
        "families": {
            label: {
                "name": (family_labels or {}).get(label, label),
                "n": len(entry["rows"]),
                "pre_onset_s": entry["window"][0] / fs,
                "post_onset_s": entry["window"][1] / fs,
                "depth_range_mv": [
                    float(min(abs(float(r["drop_depth_mv"]))
                              for r in entry["rows"])),
                    float(max(abs(float(r["drop_depth_mv"]))
                              for r in entry["rows"]))],
                "fall_range_s": [
                    float(min(float(r["fall_duration_s"])
                              for r in entry["rows"])),
                    float(max(float(r["fall_duration_s"])
                              for r in entry["rows"]))],
            } for label, entry in families.items()},
        "window_rule": "the family's median stored extent either side of "
                       "the onset, floored so no trough is clipped; every "
                       "trace re-cut from the source recording so all of a "
                       "family span the same distance",
        "intervals": strip_info,
        "events": [{"event_id": r["event_id"],
                    "onset_h": float(r["onset_h"]),
                    "drop_depth_mv": float(r["drop_depth_mv"]),
                    "fall_duration_s": float(r["fall_duration_s"]),
                    "is_pure": bool(r["is_pure"])} for r in rows],
    }
    manifest["type_sizes_outside_band"] = reportstyle.check_type_sizes(fig)
    return reportstyle.save(fig, path, proof_png=proof_png), manifest
