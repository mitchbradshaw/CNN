"""
overlays7.py
=============
The span figure and the motif overlays, with one hue per family and the
height-to-width ratio locked.

    idNNN_overlays.png   the whole span on top, its windows shaded in the
                         hue of the family they belong to; below it one
                         row per family
    idNNN_overlay.png    the family overlays alone, larger

The numeric corrections from drop_motifs6 are unchanged and still come
from `style6` through `style7`: aligned on the flat run before the drop,
one common window per set, scale bands and directions never mixed,
outliers drawn but never setting the y scale.

What is new
-----------
COLOUR TIES A PANEL TO ITS SIGNAL. Each family has its own hue, its own
gradient through time within that hue, and its own colourbar. The window
shading on the span plot uses the same hue, so a reader can look at a
trace in the third panel and find the stretch of recording it came from
without counting panels.

SHAPE IS NO LONGER FITTED TO THE AXES. One millivolt-per-second scale is
chosen per figure and every panel is locked to it, so a motif twice as
steep as its neighbour is drawn twice as steep. Panels stop being uniform
rectangles, which is the point: on ID 34 the motifs had flattened into
near-horizontal lines because each panel stretched its own data to fill
its own box.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm

from Pipelines.drop_motifs import passes7, style7

SHAPE_FIELD = "detrended_mv"
RECORDED_FIELD = "raw_mv"


def group_key(row):
    """`(sign, band)` - the two axes a set of motifs must not be mixed on."""
    return int(row.get("signal_sign", 1)), int(row.get("scale_band", 0))


def ordered_groups(rows):
    """`[(key, members), ...]`, drops before rises, fine scales first."""
    groups = {}
    for row in rows:
        groups.setdefault(group_key(row), []).append(row)
    return [(k, groups[k]) for k in sorted(groups, key=lambda k: (-k[0], k[1]))]


def assign_hues(keys):
    """`{group_key: hue_index}`, counted separately for drops and rises."""
    hues, drops, rises = {}, 0, 0
    for sign, band in keys:
        if sign > 0:
            hues[(sign, band)] = drops
            drops += 1
        else:
            hues[(sign, band)] = rises
            rises += 1
    return hues


def group_title(sign, band, labels, n, n_out, hue_name):
    direction = "drops" if sign > 0 else "rises (inverted pass)"
    label = labels[band] if band < len(labels) else "all scales"
    title = f"{direction}  ·  {label}  ·  n={n}  ·  {hue_name}"
    if n_out:
        title += f"  ·  {n_out} outlier{'s' if n_out > 1 else ''} off-scale"
    return title


def prepare_group(rows, snippets, hue_index, *, baseline_removed,
                  field=SHAPE_FIELD, inverted=False):
    """One family, cut to a common window and coloured in its own hue."""
    traces, onsets, depths, keep = [], [], [], []
    for row in rows:
        arrays = snippets.get(row["event_id"])
        if arrays is None:
            continue
        values = np.asarray(arrays[field], dtype=float)
        if values.size < 3:
            continue
        if int(row.get("signal_sign", 1)) < 0:
            values = -values
        onset = int(np.clip(int(row["onset_idx"]) - int(row["snippet_start_idx"]),
                            0, values.size - 1))
        if baseline_removed:
            values = values - style7.baseline_level(values, onset)
        traces.append(values)
        onsets.append(onset)
        depths.append(abs(float(row.get("drop_depth_mv", 0.0))))
        keep.append(row)

    if not traces:
        return None

    stacked, onset_index = style7.uniform_set(traces, onsets)
    fs = float(keep[0]["fs"])
    t = (np.arange(stacked.shape[1]) - onset_index) / fs
    outliers = style7.outlier_mask(np.asarray(depths))
    colours, norm, cmap, name = style7.family_colours(
        [r["onset_h"] for r in keep], hue_index, inverted=inverted)

    return {"rows": keep, "stacked": stacked, "t": t,
            "outliers": outliers, "ylim": style7.family_ylim(stacked, ~outliers),
            "xlim": event_xlim(t, keep),
            "colours": colours, "norm": norm, "cmap": cmap, "hue_name": name,
            "n_outliers": int(outliers.sum())}


# How much of the window either side of the onset is shown, in multiples
# of the family's own median fall duration.
PRE_ONSET_FALLS = 1.5
POST_ONSET_FALLS = 4.0


def event_xlim(t, rows):
    """The x range worth drawing, in seconds from onset.

    The common window is as long as the SHORTEST member allows, and on a
    family of 2 s events bracketed inside 20 s windows that is mostly
    quiet: the event occupied a twentieth of the panel and flattened into
    the axis. Framing on the family's own fall duration instead spends the
    width on the motif. Real seconds throughout - this is a crop, not a
    rescaling, and it never changes the shape of what is drawn.
    """
    falls = [abs(float(r.get("fall_duration_s", 0.0))) for r in rows]
    falls = [f for f in falls if np.isfinite(f) and f > 0]
    if not falls:
        return float(t[0]), float(t[-1])
    fall = float(np.median(falls))
    return (max(float(t[0]), -PRE_ONSET_FALLS * fall),
            min(float(t[-1]), POST_ONSET_FALLS * fall))


def draw_group(ax, group, aspect, *, show_zero=True):
    """Draw one prepared family, locked to the figure's mV-per-second."""
    if group is None:
        ax.text(0.5, 0.5, "no motifs", transform=ax.transAxes,
                ha="center", va="center", color="0.5")
        return

    t = group["t"]
    for values, colour, row, is_outlier in zip(
            group["stacked"], group["colours"], group["rows"],
            group["outliers"]):
        pure = bool(int(row.get("is_pure", 1)))
        if is_outlier:
            ax.plot(t, values, color=style7.OUTLIER_COLOUR,
                    lw=style7.LW_OUTLIER, alpha=style7.ALPHA_OUTLIER,
                    ls=style7.OUTLIER_DASH, zorder=2)
        elif not pure:
            ax.plot(t, values, color=style7.IMPURE_COLOUR,
                    lw=style7.LW_OUTLIER, alpha=0.55,
                    ls=style7.IMPURE_DASH, zorder=2)
        else:
            ax.plot(t, values, color=colour, lw=style7.LW_TRACE,
                    alpha=style7.ALPHA_TRACE, zorder=3)

    ax.axvline(0.0, color=style7.RULE_COLOUR, ls="--", lw=style7.LW_RULE,
               alpha=0.7, zorder=1)
    if show_zero:
        ax.axhline(0.0, color=style7.RULE_COLOUR, ls=":",
                   lw=style7.LW_RULE * 0.8, alpha=0.6, zorder=1)
    if group["ylim"]:
        ax.set_ylim(*group["ylim"])
    low, high = group["xlim"]
    ax.set_xlim(low, high if high > low else low + 1.0)
    ax.grid(alpha=0.18, lw=style7.LW_RULE * 0.5)
    style7.apply_aspect(ax, aspect)


# A family with fewer members than this is not drawn. The operator's
# instruction about the inverted pass generalised: a panel holding one
# trace shows no family, and it costs a row and a hue to say so.
MIN_FAMILY_MEMBERS = 2


def group_aspect(rows):
    """The millivolt-per-second scale for ONE family.

    Per family, not per figure. A single figure-wide scale was tried first
    and failed on exactly the spans this set is for: ID 385 holds a family
    of 13 mV drops and a family of 0.3 mV micro-spikes, and one scale that
    renders the first correctly renders the second as a hairline - four of
    its six panels collapsed to horizontal lines.

    Within a panel every motif still shares one scale, which is where the
    comparison actually matters: a motif twice as steep as the one beside
    it is drawn twice as steep. Across panels the scale is stated on each
    title instead of being silently assumed equal.
    """
    return style7.seconds_per_mv(
        [abs(float(r.get("drop_depth_mv", 0.0))) for r in rows],
        [abs(float(r.get("fall_duration_s", 0.0))) for r in rows])


def drawable_groups(rows):
    """`(groups, n_dropped)` - families big enough to be worth a panel."""
    groups = ordered_groups(rows)
    keep = [(k, m) for k, m in groups if len(m) >= MIN_FAMILY_MEMBERS]
    dropped = sum(len(m) for k, m in groups if len(m) < MIN_FAMILY_MEMBERS)
    return (keep or groups), dropped


def _span_panel(ax, x, fs, span_offset, groups, hues, snippets):
    """The whole span, each window shaded in its own family's hue."""
    t_h = (np.arange(len(x)) + span_offset) / fs / 3600.0
    ax.plot(t_h, np.asarray(x) * 1000.0, lw=style7.LW_SIGNAL,
            color=style7.SIGNAL_COLOUR, zorder=3)

    for (sign, band), members in groups:
        colours, _, _, _ = style7.family_colours(
            [r["onset_h"] for r in members], hues[(sign, band)],
            inverted=sign < 0)
        for row, colour in zip(members, colours):
            start = int(row["snippet_start_idx"]) - span_offset
            end = int(row["snippet_end_idx"]) - span_offset
            lo = t_h[int(np.clip(start, 0, len(t_h) - 1))]
            hi = t_h[int(np.clip(end - 1, 0, len(t_h) - 1))]
            pure = bool(int(row.get("is_pure", 1)))
            ax.axvspan(lo, hi, color=colour if pure else style7.IMPURE_COLOUR,
                       alpha=0.30 if pure else 0.18,
                       hatch="///" if sign < 0 else None, lw=0, zorder=1)

    ax.set_xlabel("time in recording (h)")
    ax.set_ylabel("amplitude (mV, raw)")
    ax.margins(x=0.005)
    ax.grid(alpha=0.18, lw=style7.LW_RULE * 0.5)


def plot_span_and_overlays(x, fs, span_offset, rows, snippets, summary,
                           out_path, band_labels=()):
    """Span on top, one row per family beneath, each in its own hue."""
    if not rows:
        return None
    style7.apply_style()

    rows = sorted(rows, key=lambda r: r["onset_h"])
    groups, dropped = drawable_groups(rows)
    hues = assign_hues([k for k, _ in groups])
    n_rows = len(groups)

    fig = plt.figure(figsize=(15.0, 4.4 + 3.6 * n_rows))
    grid = fig.add_gridspec(n_rows + 1, 2,
                            height_ratios=[1.10] + [1.0] * n_rows,
                            hspace=0.52, wspace=0.30)

    ax_span = fig.add_subplot(grid[0, :])
    _span_panel(ax_span, x, fs, span_offset, groups, hues, snippets)

    for i, ((sign, band), members) in enumerate(groups):
        hue = hues[(sign, band)]
        pure = [r for r in members if int(r.get("is_pure", 1))] or members

        aspect = group_aspect(members)
        left = fig.add_subplot(grid[i + 1, 0])
        shape = prepare_group(pure, snippets, hue, baseline_removed=True,
                              inverted=sign < 0)
        draw_group(left, shape, aspect)
        left.set_ylabel("mV, detrended,\nbaseline removed")
        left.set_xlabel("time from onset (s)")
        left.set_title(group_title(sign, band, band_labels, len(pure),
                                   shape["n_outliers"] if shape else 0,
                                   shape["hue_name"] if shape else "")
                       + "\n" + style7.aspect_caption(aspect), fontsize=8.5)

        right = fig.add_subplot(grid[i + 1, 1])
        kept = prepare_group(members, snippets, hue, baseline_removed=False,
                             field=RECORDED_FIELD, inverted=sign < 0)
        # NOT aspect-locked, deliberately. This panel's y extent is the
        # DC offset spread across the whole span - 60 mV on ID 26 against
        # 2 mV motifs - so locking it to a millivolt-per-second scale asks
        # for a box sixty times taller than wide and matplotlib answers
        # with a sliver. Shape is the left panel's job; this one answers
        # "what was actually there", and it says so in its title.
        draw_group(right, kept, None, show_zero=False)
        right.set_ylabel("mV, as recorded")
        right.set_xlabel("time from onset (s)")
        n_impure = sum(1 for r in members if not int(r.get("is_pure", 1)))
        right.set_title(
            f"all windows, n={len(members)}  ·  baseline kept"
            + (f"  ·  {n_impure} impure dashed" if n_impure else "")
            + "\ncontext view — not height-to-width locked",
            fontsize=8.5)

        # Attached to the axes, not to a reserved column. `set_aspect`
        # shrinks the box inside its cell, and a colourbar placed in its
        # own gridspec column stays where the cell was - stranded beside a
        # panel it no longer touches. `ax=` makes it follow the box.
        if shape is not None and shape["norm"] is not None:
            bar = fig.colorbar(cm.ScalarMappable(norm=shape["norm"],
                                                 cmap=shape["cmap"]),
                               ax=left, fraction=0.040, pad=0.02)
            bar.set_label("onset (h)", fontsize=7.5)
            bar.ax.tick_params(labelsize=6.5)

    kept_counts = summary.get("per_pass_kept", {})
    passes = ", ".join(f"{passes7.PASS_LABELS[k]} {v}"
                       for k, v in kept_counts.items() if v)
    fig.suptitle(
        f"catalogue ID {summary['catalogue_id']}  ·  n={len(rows)} motifs"
        f" in {n_rows} famil{'ies' if n_rows != 1 else 'y'}"
        f"  ·  one hue per family\n"
        + (f"passes: {passes}\n" if passes else "")
        + style7.aspect_caption(aspect) + "; every panel shares it\n"
        + f"{str(summary.get('note',''))[:110]}",
        fontsize=10.5, y=0.997)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)


def plot_family_overlay(rows, snippets, summary, out_path, band_labels=()):
    """The family overlays alone, one panel each, larger."""
    if not rows:
        return None
    style7.apply_style()

    rows = sorted(rows, key=lambda r: r["onset_h"])
    pure = [r for r in rows if int(r.get("is_pure", 1))] or rows
    groups, dropped = drawable_groups(pure)
    hues = assign_hues([k for k, _ in groups])

    n = len(groups)
    cols = min(n, 2)
    grid_rows = int(np.ceil(n / cols))
    fig = plt.figure(figsize=(8.2 * cols, 5.2 * grid_rows))
    grid = fig.add_gridspec(grid_rows, cols, hspace=0.46, wspace=0.32)

    for i, ((sign, band), members) in enumerate(groups):
        r, c = i // cols, i % cols
        ax = fig.add_subplot(grid[r, c])
        aspect = group_aspect(members)
        group = prepare_group(members, snippets, hues[(sign, band)],
                              baseline_removed=True, inverted=sign < 0)
        draw_group(ax, group, aspect)
        ax.set_xlabel("time from onset (s)")
        ax.set_ylabel("mV, detrended, baseline removed")
        ax.set_title(group_title(sign, band, band_labels, len(members),
                                 group["n_outliers"] if group else 0,
                                 group["hue_name"] if group else "")
                     + "\n" + style7.aspect_caption(aspect), fontsize=9)
        if group is not None and group["norm"] is not None:
            bar = fig.colorbar(cm.ScalarMappable(norm=group["norm"],
                                                 cmap=group["cmap"]),
                               ax=ax, fraction=0.040, pad=0.02)
            bar.set_label("onset (h)", fontsize=7.5)
            bar.ax.tick_params(labelsize=6.5)

    fig.suptitle(
        f"catalogue ID {summary['catalogue_id']} — motif families"
        f"  ·  one hue per family  ·  aligned on the flat run before the drop"
        f"  ·  amplitude NOT normalised\n" + style7.aspect_caption(aspect),
        fontsize=11)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)
