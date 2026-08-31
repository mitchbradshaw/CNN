"""
overlays5.py
=============
Figure 1 of three: the whole span above, and beneath it the two overlays
side by side.

    +-------------------------------------------------------------+
    |  the entire span, every detected window shaded in place      |
    +----------------------------+--------------------------------+
    |  PURE windows only,        |  ALL windows,                   |
    |  baseline removed          |  baseline NOT removed           |
    |  (every drop starts at 0)  |  (raw millivolts as recorded)   |
    +----------------------------+--------------------------------+

Why the two panels differ in BOTH respects
------------------------------------------
They answer different questions and each is drawn the way its own question
needs.

The left panel asks "do these drops have the same shape?". Comparison is
what it is for, so the baseline is removed - every trace is shifted so its
own onset sits at y=0 and all the drops fall from a common origin.
Amplitude is still millivolts and is never scaled: subtracting a constant
per trace removes an offset, which is a different operation from
normalising, and it leaves the depth of every drop exactly as measured.

The right panel asks "what was actually there?". It keeps the recorded
level, so the DC offset and the drift between events stay visible, and it
includes the impure windows the left panel excludes - because a figure
that only ever shows the clean subset cannot be used to judge how much was
excluded.

The gradient
------------
Every trace is coloured by WHERE IN THE SPAN it happened, early to late,
on a perceptually uniform ramp. On these recordings amplitude and interval
both drift through a span - annotation 11266 says so outright ("amplitude
modulation increasing; frequency modulation decreasing") - so "is the
spread in this overlay ordered in time, or is it scatter?" is a real
question, and the colour answers it without a second figure. The same ramp
runs along the span plot above, so a trace can be traced back to its
position by eye.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm, colors

# Perceptually uniform and legible in both directions. `viridis` is
# reserved by the existing figures for cluster identity, so time uses a
# different ramp and the two can appear on one page without colliding.
TIME_CMAP = "plasma"

IMPURE_COLOUR = "#c1272d"


def time_colours(onsets_h, cmap=TIME_CMAP, lo=0.08, hi=0.92):
    """One colour per event, by position in the span.

    The ramp is truncated at both ends: the extremes of most colour maps
    are nearly black and nearly white, and a trace drawn in either
    disappears against the axes or the grid.
    """
    onsets = np.asarray(onsets_h, dtype=float)
    if onsets.size == 0:
        return [], None
    span = float(onsets.max() - onsets.min())
    if span <= 0:
        fractions = np.full(onsets.shape, 0.5)
    else:
        fractions = (onsets - onsets.min()) / span
    mapper = cm.get_cmap(cmap)
    return [mapper(lo + (hi - lo) * f) for f in fractions], colors.Normalize(
        vmin=float(onsets.min()), vmax=float(onsets.max()))


def _span_panel(ax, x, fs, span_offset, events, colours):
    """The whole span, with every window shaded where it sits."""
    t_h = (np.arange(len(x)) + span_offset) / fs / 3600.0
    ax.plot(t_h, x * 1000.0, lw=0.5, color="0.25", zorder=2)

    for event, colour in zip(events, colours):
        start = int(event["snippet_start_idx"]) - span_offset
        end = int(event["snippet_end_idx"]) - span_offset
        ax.axvspan(t_h[max(0, start)], t_h[min(len(t_h) - 1, end - 1)],
                   color=colour if event["is_pure"] else IMPURE_COLOUR,
                   alpha=0.16 if event["is_pure"] else 0.22, lw=0, zorder=1)

    ax.set_xlabel("time in recording (h)")
    ax.set_ylabel("amplitude (mV, raw)")
    ax.margins(x=0.005)
    ax.grid(alpha=0.2)


def _overlay_panel(ax, events, snippets, colours, *, baseline_removed,
                   include_impure):
    """One overlay. Every trace is aligned on its own drop onset."""
    drawn = 0
    for event, colour in zip(events, colours):
        pure = bool(event["is_pure"])
        if not include_impure and not pure:
            continue

        values = np.asarray(snippets[event["event_id"]]["raw_mv"], dtype=float)
        if values.size == 0:
            continue
        start = int(event["snippet_start_idx"])
        onset = int(event["onset_idx"]) - start
        onset = int(np.clip(onset, 0, values.size - 1))
        t = (np.arange(values.size) - onset) / float(event["fs"])

        if baseline_removed:
            # Shift only. Every drop then falls from a common origin, so
            # depths are directly comparable BY EYE - and the depth of
            # each is still exactly what was measured, because a constant
            # subtraction is not a scaling.
            values = values - values[onset]

        ax.plot(t, values,
                color=colour if pure else IMPURE_COLOUR,
                lw=0.9 if pure else 0.7,
                alpha=0.85 if pure else 0.45,
                zorder=3 if pure else 2)
        drawn += 1

    ax.axvline(0.0, color="0.35", ls="--", lw=0.9, zorder=1)
    if baseline_removed:
        ax.axhline(0.0, color="0.35", ls=":", lw=0.8, zorder=1)
    ax.set_xlabel("time from drop onset (s)")
    ax.grid(alpha=0.2)
    return drawn


def plot_span_and_overlays(x, fs, span_offset, events, snippets, summary,
                           out_path):
    """Figure 1 for one span. Returns the path written."""
    if not events:
        return None

    order = np.argsort([e["onset_h"] for e in events])
    events = [events[i] for i in order]
    colours, norm = time_colours([e["onset_h"] for e in events])

    fig = plt.figure(figsize=(13.5, 8.4))
    grid = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.25], hspace=0.32,
                            wspace=0.16)

    ax_span = fig.add_subplot(grid[0, :])
    _span_panel(ax_span, x, fs, span_offset, events, colours)

    n_pure = sum(1 for e in events if e["is_pure"])
    n_impure = len(events) - n_pure

    ax_left = fig.add_subplot(grid[1, 0])
    _overlay_panel(ax_left, events, snippets, colours,
                   baseline_removed=True, include_impure=False)
    ax_left.set_ylabel("amplitude (mV, baseline removed)")
    ax_left.set_title(
        f"pure windows only, n={n_pure}  ·  baseline removed\n"
        f"every drop starts at y=0; amplitude NOT scaled",
        fontsize=9)

    ax_right = fig.add_subplot(grid[1, 1])
    _overlay_panel(ax_right, events, snippets, colours,
                   baseline_removed=False, include_impure=True)
    ax_right.set_ylabel("amplitude (mV, as recorded)")
    ax_right.set_title(
        f"all windows, n={len(events)}  ·  baseline kept\n"
        + (f"{n_impure} impure drawn red" if n_impure
           else "no impure windows in this span"),
        fontsize=9)

    if norm is not None:
        bar = fig.colorbar(
            cm.ScalarMappable(norm=norm, cmap=TIME_CMAP),
            ax=[ax_left, ax_right], fraction=0.025, pad=0.02)
        bar.set_label("onset time in recording (h)", fontsize=8)
        bar.ax.tick_params(labelsize=7)

    fig.suptitle(
        f"catalogue ID {summary['catalogue_id']}  ·  {summary['morphology']}"
        f"  ·  n={len(events)}  ·  "
        f"{summary['purity_clean_fraction']:.0%} of windows hold exactly "
        f"one fall\n{summary['note'][:110]}",
        fontsize=10)

    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)
