"""
overlays73.py
==============
drop_motifs7.3. The numbers are 7.2's - the millivolt-per-second is still
measured from the span panel's own geometry - and what changes is the
LAYOUT, because 7.2's was undoing the measurement it had just made.

The fault
---------
7.2 put each shape-locked panel in a gridspec cell. `set_aspect` cannot
change a cell, so it satisfies the aspect by shrinking the AXES inside it,
anchored at the centre. On catalogue ID 22 that produced five panels
between one and two inches wide floating in a 15-inch page, the widest
gutter on the page running down the middle of a two-column grid, and a
final row holding one panel parked over the left third of the sheet.

The fix
-------
Solve the geometry first, then build the figure around it.

  1. prepare every family, so its x and y ranges are known
  2. `style73.panel_box` turns each range plus the span's aspect into the
     box in INCHES that holds it at true shape
  3. the figure is made that size, and `style73.centred_row` places the
     row in it

Nothing shrinks, because nothing is asked to fit a cell it does not fit,
and a row of one is centred because the row is centred rather than the
cell.

A panel that comes out too narrow to read is enlarged - taller AND wider
together, shape untouched - before any stretching is considered, and the
stretch that remains is capped and captioned. See `style73.panel_box`.

The span panel is now drawn at exactly `REFERENCE_SPAN_*`, the box its
own ratio claim is quoted against. In 7.2 the reference was nominal and
the drawn panel merely close to it.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm

from Pipelines.drop_motifs import passes7, style7, style73
from Pipelines.drop_motifs.overlays7 import (RECORDED_FIELD, _span_panel,
                                             assign_hues, drawable_groups,
                                             draw_group, group_title,
                                             prepare_group)
from Pipelines.drop_motifs.overlays72 import (REFERENCE_SPAN_HEIGHT_IN,
                                              REFERENCE_SPAN_WIDTH_IN,
                                              span_aspect)

# Page furniture, in inches. Each panel is placed inside a CELL that also
# holds the room its own decorations need, so two panels can never be laid
# out close enough for one's y label to land on the other.
MARGIN_X = 0.60
MARGIN_TOP = 1.15
MARGIN_BOTTOM = 0.45
GAP_X = 0.55
GAP_Y = 0.60

LABEL_LEFT_IN = 1.05      # y label, tick labels
LABEL_BOTTOM_IN = 0.68    # x label, tick labels
LABEL_TOP_IN = 0.62       # panel title (two lines)

CBAR_PAD_IN = 0.12
CBAR_WIDTH_IN = 0.18
CBAR_LABEL_IN = 0.68      # its tick labels and "onset (h)"
CBAR_CELL_IN = CBAR_PAD_IN + CBAR_WIDTH_IN + CBAR_LABEL_IN

PANELS_PER_ROW = 2


def _panel_ranges(group):
    """`(x_range, y_range)` the panel will actually display.

    Taken from the prepared group rather than from the axes, because the
    box has to be solved before any axes exists - which is the whole point
    of this module.
    """
    low, high = group["xlim"]
    x_range = float(high - low) if high > low else 1.0
    if group["ylim"]:
        y_range = float(group["ylim"][1] - group["ylim"][0])
    else:
        finite = group["stacked"][np.isfinite(group["stacked"])]
        y_range = float(np.ptp(finite)) if finite.size else 1.0
    return x_range, (y_range if y_range > 0 else 1.0)


def _rect(fig_w, fig_h, x, y, w, h):
    """Inches to the figure fractions `add_axes` wants."""
    return [x / fig_w, y / fig_h, w / fig_w, h / fig_h]


def _colourbar(fig, ax, group, fig_w, fig_h, x, y, h):
    """A colourbar in its OWN axes, beside the panel.

    `fig.colorbar(ax=...)` steals space from the axes it is given, which
    would shrink the panel this module went to the trouble of sizing.
    """
    if group is None or group["norm"] is None:
        return
    cax = fig.add_axes(_rect(fig_w, fig_h, x, y, CBAR_WIDTH_IN, h))
    bar = fig.colorbar(cm.ScalarMappable(norm=group["norm"],
                                         cmap=group["cmap"]), cax=cax)
    bar.set_label("onset (h)", fontsize=7.5)
    bar.ax.tick_params(labelsize=6.5)


# The overlays contact sheet stacks one row per family, so a panel budget
# that suits the standalone page multiplies into a sheet several feet
# long. It gets a smaller one; the standalone `overlay` figure is where a
# family is looked at closely.
SHEET_HEIGHT_IN = 4.4
SHEET_MAX_HEIGHT_IN = 5.2


def _solve_panels(groups, snippets, hues, aspect, *, height_in,
                  max_height_in=style73.PANEL_MAX_HEIGHT_IN,
                  baseline_removed=True, pure_only=False):
    """One prepared group plus its box, per family, in draw order."""
    solved = []
    for (sign, band), members in groups:
        rows = ([r for r in members if int(r.get("is_pure", 1))] or members) \
            if pure_only else members
        group = prepare_group(rows, snippets, hues[(sign, band)],
                              baseline_removed=baseline_removed,
                              inverted=sign < 0)
        if group is None:
            continue
        x_range, y_range = _panel_ranges(group)
        width, height, fill, distortion = style73.panel_box(
            aspect, x_range, y_range, height_in=height_in,
            max_height_in=max_height_in)
        solved.append({"key": (sign, band), "members": members, "rows": rows,
                       "group": group, "w": width, "h": height,
                       "fill": fill, "distortion": distortion})
    return solved


def _worst_distortion(solved):
    """The panel that departs furthest from the recording, either way."""
    if not solved:
        return 1.0
    return max((p["distortion"] for p in solved),
               key=lambda d: abs(np.log(d)) if d > 0 else 0.0)


def plot_family_overlay(x, fs, rows, snippets, summary, out_path,
                        band_labels=()):
    """The family overlays alone: every panel at the span's own scale,
    every row centred, the sheet no wider than the panels need."""
    if not rows:
        return None
    style7.apply_style()

    rows = sorted(rows, key=lambda r: r["onset_h"])
    pure = [r for r in rows if int(r.get("is_pure", 1))] or rows
    groups, dropped = drawable_groups(pure)
    hues = assign_hues([k for k, _ in groups])
    aspect, true_ratio, compression = span_aspect(x, fs, pure)

    solved = _solve_panels(groups, snippets, hues, aspect,
                           height_in=style73.PANEL_HEIGHT_IN)
    if not solved:
        return None

    bands = [solved[i:i + PANELS_PER_ROW]
             for i in range(0, len(solved), PANELS_PER_ROW)]
    cells = [[LABEL_LEFT_IN + p["w"] + CBAR_CELL_IN for p in band]
             for band in bands]
    row_heights = [max(p["h"] for p in band) + LABEL_TOP_IN + LABEL_BOTTOM_IN
                   for band in bands]

    fig_w = max(style73.row_span(c, GAP_X) for c in cells) + 2 * MARGIN_X
    fig_h = sum(row_heights) + GAP_Y * (len(bands) - 1) + MARGIN_TOP + MARGIN_BOTTOM
    fig = plt.figure(figsize=(fig_w, fig_h))

    top = fig_h - MARGIN_TOP
    for band, widths, row_height in zip(bands, cells, row_heights):
        lefts = style73.centred_row(widths, GAP_X, fig_w - 2 * MARGIN_X)
        for panel, cell_left in zip(band, lefts):
            px = MARGIN_X + cell_left + LABEL_LEFT_IN
            py = top - row_height + LABEL_BOTTOM_IN
            ax = fig.add_axes(_rect(fig_w, fig_h, px, py, panel["w"],
                                    panel["h"]))
            sign, band_index = panel["key"]
            draw_group(ax, panel["group"], panel["fill"])
            ax.set_xlabel("time from onset (s)")
            ax.set_ylabel("mV, detrended, baseline removed")
            ax.set_title(
                group_title(sign, band_index, band_labels,
                            len(panel["rows"]), panel["group"]["n_outliers"],
                            panel["group"]["hue_name"]),
                fontsize=9.5)
            _colourbar(fig, ax, panel["group"], fig_w, fig_h,
                       px + panel["w"] + CBAR_PAD_IN, py, panel["h"])
        top -= row_height + GAP_Y

    fig.suptitle(
        f"catalogue ID {summary['catalogue_id']} — motif families"
        f"  ·  one hue per family  ·  amplitude NOT normalised\n"
        + style73.shape_caption(true_ratio, compression,
                                _worst_distortion(solved))
        + (f"  ·  {dropped} single-member family not shown" if dropped else ""),
        fontsize=10.5, y=1.0 - 0.30 / fig_h, wrap=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return str(out_path)


# The as-recorded panel is a context view, not shape-locked, so its size is
# chosen rather than solved. It tracks the shape panel's height so the two
# sit on one baseline, and its width is bounded so it can neither dominate
# the row nor vanish beside a wide one.
CONTEXT_MIN_W_IN = 3.6
CONTEXT_MAX_W_IN = 6.6


def plot_span_and_overlays(x, fs, span_offset, rows, snippets, summary,
                           out_path, band_labels=()):
    """The span on top at exactly the reference box, then one centred row
    per family: shape on the left, as recorded on the right."""
    if not rows:
        return None
    style7.apply_style()

    rows = sorted(rows, key=lambda r: r["onset_h"])
    groups, dropped = drawable_groups(rows)
    hues = assign_hues([k for k, _ in groups])
    aspect, true_ratio, compression = span_aspect(x, fs, rows)

    solved = _solve_panels(groups, snippets, hues, aspect,
                           height_in=SHEET_HEIGHT_IN,
                           max_height_in=SHEET_MAX_HEIGHT_IN, pure_only=True)
    if not solved:
        return None

    for panel in solved:
        panel["context_w"] = float(np.clip(panel["w"] * 1.15,
                                           CONTEXT_MIN_W_IN, CONTEXT_MAX_W_IN))

    cells = [[LABEL_LEFT_IN + p["w"] + CBAR_CELL_IN,
              LABEL_LEFT_IN + p["context_w"]] for p in solved]
    row_heights = [p["h"] + LABEL_TOP_IN + LABEL_BOTTOM_IN for p in solved]

    span_cell = LABEL_LEFT_IN + REFERENCE_SPAN_WIDTH_IN
    fig_w = max([span_cell] + [style73.row_span(c, GAP_X) for c in cells]) \
        + 2 * MARGIN_X
    fig_h = (REFERENCE_SPAN_HEIGHT_IN + LABEL_BOTTOM_IN + GAP_Y
             + sum(row_heights) + GAP_Y * (len(solved) - 1)
             + MARGIN_TOP + MARGIN_BOTTOM)
    fig = plt.figure(figsize=(fig_w, fig_h))

    # The span panel at exactly the box its ratio claim is quoted against,
    # so "shape as in the recording" refers to a panel that is on the page.
    span_left = MARGIN_X + (fig_w - 2 * MARGIN_X - span_cell) / 2.0
    span_bottom = fig_h - MARGIN_TOP - REFERENCE_SPAN_HEIGHT_IN
    ax_span = fig.add_axes(_rect(fig_w, fig_h, span_left + LABEL_LEFT_IN,
                                 span_bottom, REFERENCE_SPAN_WIDTH_IN,
                                 REFERENCE_SPAN_HEIGHT_IN))
    _span_panel(ax_span, x, fs, span_offset, groups, hues, snippets)

    top = span_bottom - LABEL_BOTTOM_IN - GAP_Y
    for panel, widths, row_height in zip(solved, cells, row_heights):
        lefts = style73.centred_row(widths, GAP_X, fig_w - 2 * MARGIN_X)
        sign, band_index = panel["key"]
        py = top - row_height + LABEL_BOTTOM_IN

        px = MARGIN_X + lefts[0] + LABEL_LEFT_IN
        left = fig.add_axes(_rect(fig_w, fig_h, px, py, panel["w"], panel["h"]))
        draw_group(left, panel["group"], panel["fill"])
        left.set_ylabel("mV, detrended,\nbaseline removed")
        left.set_xlabel("time from onset (s)")
        left.set_title(
            group_title(sign, band_index, band_labels, len(panel["rows"]),
                        panel["group"]["n_outliers"],
                        panel["group"]["hue_name"]), fontsize=9)
        _colourbar(fig, left, panel["group"], fig_w, fig_h,
                   px + panel["w"] + CBAR_PAD_IN, py, panel["h"])

        cx = MARGIN_X + lefts[1] + LABEL_LEFT_IN
        right = fig.add_axes(_rect(fig_w, fig_h, cx, py, panel["context_w"],
                                   panel["h"]))
        kept = prepare_group(panel["members"], snippets, hues[panel["key"]],
                             baseline_removed=False, field=RECORDED_FIELD,
                             inverted=sign < 0)
        draw_group(right, kept, None, show_zero=False)
        right.set_ylabel("mV, as recorded")
        right.set_xlabel("time from onset (s)")
        n_impure = sum(1 for r in panel["members"]
                       if not int(r.get("is_pure", 1)))
        right.set_title(
            f"all windows, n={len(panel['members'])}  ·  baseline kept"
            + (f"  ·  {n_impure} impure dashed" if n_impure else "")
            + "\ncontext view — not shape-locked", fontsize=8.5)
        top -= row_height + GAP_Y

    kept_counts = summary.get("per_pass_kept", {})
    passes = ", ".join(f"{passes7.PASS_LABELS[k]} {v}"
                       for k, v in kept_counts.items() if v)
    fig.suptitle(
        f"catalogue ID {summary['catalogue_id']}  ·  n={len(rows)} motifs"
        f" in {len(solved)} famil{'ies' if len(solved) != 1 else 'y'}"
        f"  ·  one hue per family\n"
        + (f"passes: {passes}\n" if passes else "")
        + style73.shape_caption(true_ratio, compression,
                                _worst_distortion(solved))
        + "; every family panel shares the span plot's own scale"
        + (f"  ·  {dropped} single-member famil"
           f"{'ies' if dropped != 1 else 'y'} not shown" if dropped else "")
        + f"\n{str(summary.get('note',''))[:110]}",
        fontsize=10.5, y=1.0 - 0.28 / fig_h, wrap=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return str(out_path)
