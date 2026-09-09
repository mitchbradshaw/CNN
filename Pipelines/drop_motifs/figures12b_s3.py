"""
figures12b_s3.py
=================
Section 3 redrawn: S3.1 the sequence morph, S3.2 the morph across scales,
S3.3 the isolated-pair probe. Every waveform on this page is real samples
against real time; nothing here resamples and nothing here detects.

What changed from `figures11_s3`, and why each change was forced
-----------------------------------------------------------------
S3.1 gained the raw REFERENCE STRIP it was missing. Without it a reader has
no way to see where 25 stacked waveforms came from, which is most of why the
round-11 figure read as decoration.

Both waterfalls are now offset by 0.8 of their own drawn peak-to-peak rather
than by roughly four times it, and both are height-to-width locked. Those
two together are the whole fix for "a bunch of flat lines". They also force
the panel to be a TALL COLUMN - stacking N traces at 0.8 of their own
amplitude makes a column about 0.8N amplitudes tall and one event wide - so
the trace count is cut to what fits a printable shape and the figure states
how many of the run's events that is. Round 11 kept 42 traces and paid for
it by drawing the column in a landscape box, which is exactly the fault.

The normalised panel runs -0.5 to 1.5 fall-fractions, so the shoulder and
the recovery are in frame; at 0 to 1 every species is the same monotone
descent by construction.

S3.2 is no longer a stack of waterfalls. It is a small-multiples catalogue
in `Plots/drop_motifs5/id385_contact.png`'s style: one row per species, each
event its own small panel in time order, fall span shaded, depth and
duration on the panel.
"""

import numpy as np
from matplotlib import gridspec
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D

from Pipelines.drop_motifs import (config11, drawing_rules, sequences11,
                                   store11, style7)

LW_TRACE = 1.0
LW_ENDS = 1.8

# Small-multiples grid for S3.2. Twelve panels per row is what
# `id385_contact.png` uses across a 16-inch page and it stays legible.
CONTACT_COLUMNS = 12
CONTACT_PANEL_W_IN = 1.25
CONTACT_PANEL_H_IN = 1.55

# The view each contact panel gets, in multiples of THAT EVENT'S own fall
# and depth. Locking per panel rather than per row is what makes the sheet
# uniform: the drawn height-to-width of a panel's box is
# `TARGET_RATIO x depth_span / fall_span`, which is the same number for
# every panel however large the event is, so every box comes out the same
# shape and every event inside it is drawn at exactly the 1.8:1 lock.
#
# A single row-wide lock was tried first and is what `id385_contact.png`
# does NOT do. Within one Reishi sequence the events run 0.04 mV over 0.3 s
# to 1.5 mV over 1.6 s, and one scale across that range draws half the row
# as dots and the other half off the panel - boxes of a dozen different
# sizes, which is the round-11 fault in a new place. The native scale is not
# lost: it is on every panel's own tick labels and depth/duration title, and
# the ROW's range is in the row caption.
CONTACT_VIEW_FALLS = (-0.6, 2.0)
CONTACT_VIEW_DEPTH = (-1.35, 0.30)


# ==========================================================================
# shared: the banked waterfall
# ==========================================================================

# The native bank draws the WHOLE CYCLE: each event framed back to the
# previous event's trough, so the slow rise the fall departs from is in the
# panel. `Plots/drop_motifs7/id003_overlays.png` is legible because it draws
# both halves of the sharkfin; a 1.2-fall shoulder shows the last tenth of a
# 55-second rise and reads as a step rather than a ramp.
#
# The x view reaches back `NATIVE_REACH_QUANTILE` of the drawn events' own
# reaches, so a single long gap cannot set the axis. Events reaching further
# are drawn and start inside the panel; the count is stated.
NATIVE_REACH_QUANTILE = 0.60

# Inches of width per waterfall column. The normalised panel's window is
# two fall-units wide and it only has to be legible, so it is narrow; the
# native panel's window is a whole cycle and its width is what buys the
# bank its height - at a fixed lock, a bank's height in inches is its
# column width times its height-to-width, so a wider native column is the
# only way to give seven stacked sharkfins room without breaking the lock.
COLUMN_W_IN = 1.3
NATIVE_COLUMN_W_IN = 4.0

# The tallest a bank may be drawn, in inches. A page, in the end.
MAX_BANK_H_IN = 11.5


def _waterfall(ax, traces, rows, colours, *, aspect, offset, xlim, ylim,
               lw=LW_TRACE):
    """One column of a bank: successive traces, oldest at top.

    Oldest at top and descending, so reading down a column is reading
    forward in time - the same direction the colour ramp runs.

    `ylim` is passed in and is the SAME for every column of a bank. Left to
    its own data a short last column - 23 traces over four columns leaves
    two in the fourth - gets a smaller y range, and an aspect-locked axes
    answers a smaller y range by shrinking its box, so the last column comes
    out a different size from the three beside it for no reason a reader
    could recover.
    """
    for position, ((t, y), row) in enumerate(zip(traces, rows)):
        ax.plot(t, y - offset * position, color=colours[row["event_id"]],
                lw=lw, solid_capstyle="round", zorder=3)
    ax.axvline(0.0, color=style7.RULE_COLOUR, ls="--", lw=style7.LW_RULE,
               alpha=0.45, zorder=1)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_yticks([])
    ax.tick_params(labelsize=config11.FS_TICK)
    ax.grid(axis="x", alpha=0.15, lw=style7.LW_RULE * 0.5)
    drawing_rules.apply_aspect(ax, aspect)


def _bank_ylim(traces, offset, per_column, margin=0.04):
    """The y range every column of a bank shares.

    Bounds what is ACTUALLY DRAWN: the deepest trace in the bank, sitting at
    the last position of a full column, plus a margin. The first version of
    this used the median excursion as a proxy and clipped the bottom trace
    off several panels wherever one event in a bank was deeper than the rest
    - which on a waterfall reads as the sequence fading out rather than as a
    cropped axis.

    A full column and a part-full one get the same range, so the last column
    of a bank is drawn the same size as the others.
    """
    lows = [float(np.min(y)) for _t, y in traces if np.asarray(y).size]
    highs = [float(np.max(y)) for _t, y in traces if np.asarray(y).size]
    if not lows:
        return (-1.0, 1.0)
    low = min(lows) - offset * (per_column - 1)
    high = max(highs)
    pad = margin * max(high - low, 1e-9)
    return (low - pad, high + pad)


def _bank(fig, cell, traces, rows, colours, *, aspect, offset, per_column,
          xlim, ylim, n_columns, scale_unit=None):
    """A waterfall BANKED into columns, read down then across.

    This is the one place where two of the work order's rules pull against
    each other, and the arithmetic is shown rather than a rule quietly
    dropped.

    Rule 6 asks for up to 25 traces at 0.8 of their own peak-to-peak. Rules
    3 and 4 ask each event to be drawn between 1:1 and 3:1 height-to-width.
    Stack 25 traces at 0.8 and the COLUMN is about twenty peak-to-peaks tall
    and one event wide; lock each event at 1.8:1 and the column is then
    around 18:1. There is no page width at which that is both legible and
    printable, and round 11 resolved it by drawing the column in a landscape
    box - which is exactly what flattened every trace and is the fault this
    run exists to fix.

    Banking keeps every rule. Each column holds `per_column` traces at the
    full 0.8 offset and the full lock, so no trace is flattened and the
    proportion is exact; the columns run left to right, so all 25 events are
    still on the page. Time order is unambiguous from the colour ramp, and
    the colourbar states it.
    """
    grid = gridspec.GridSpecFromSubplotSpec(1, n_columns, subplot_spec=cell,
                                            wspace=0.26)
    axes = []
    for column in range(n_columns):
        block = slice(column * per_column, (column + 1) * per_column)
        ax = fig.add_subplot(grid[0, column])
        _waterfall(ax, traces[block], rows[block], colours, aspect=aspect,
                   offset=offset, xlim=xlim, ylim=ylim)
        if column == 0 and scale_unit:
            drawing_rules.scale_bar(
                ax, offset / drawing_rules.OFFSET_FRACTION, scale_unit)
        axes.append(ax)
    return axes


# Where a bank's title and caption sit, in INCHES from the cell edge. In
# figure fractions they would mean different things on a 12-inch figure and
# on a 22-inch one, and these figures are sized from their own panels so
# their heights differ by nearly that much. Below a bank the gap has to
# clear the columns' own tick labels; above it there is nothing to clear.
PAD_ABOVE_IN = 0.09
PAD_BELOW_IN = 0.34


def _cell_text(fig, cell, text, *, above, fontsize=None, pad_in=None):
    """One caption per BANK, not one per column.

    Positioned from the gridspec CELL rather than from an axes: every axes
    in a bank is aspect-locked and has therefore been reshaped inside its
    own cell, so no single axes' position describes the bank.
    """
    box = cell.get_position(fig)
    if pad_in is None:
        pad_in = PAD_ABOVE_IN if above else PAD_BELOW_IN
    pad = float(pad_in) / float(fig.get_figheight())
    fig.text(box.x0 + box.width / 2.0,
             (box.y1 + pad) if above else (box.y0 - pad), text,
             ha="center", va="bottom" if above else "top",
             fontsize=fontsize or config11.FS_LABEL, color="#111111")


def _z_aspect(traces, target=None):
    """The lock for a panel whose BOTH axes are normalised.

    One fall is one x unit and the excursion is in z, so the lock is
    `TARGET_RATIO` z of height per fall of width, derived from the median
    trace's own drawn excursion. Same rule as `figure_aspect`, in the units
    that panel is in.
    """
    target = drawing_rules.TARGET_RATIO if target is None else target
    depth = float(np.median([float(np.ptp(y)) for _t, y in traces])) \
        if traces else 0.0
    return target / depth if depth > 0 else 1.0


def _clip_to_view(traces, xlim):
    """`[(t, y)]` clipped to the view, for measuring rule 6's offset.

    Rule 6 says "the DRAWN peak-to-peak of the events in that panel", so the
    offset is measured on what the panel shows. Measured on the whole frame
    instead it would separate the traces by more than the rule asks for
    wherever the frame runs outside the view.
    """
    clipped = []
    for t, y in traces:
        inside = (t >= xlim[0]) & (t <= xlim[1])
        clipped.append((t[inside], y[inside]) if inside.sum() >= 2 else (t, y))
    return clipped


def _waterfall_plan(members, snippets):
    """Everything the two waterfalls need, decided ONCE.

    The two must show the SAME events in the SAME grouping, or a reader
    cannot pair a trace in one with a trace in the other. So: one thinning,
    one column count, one events-per-column, and each panel's own lock,
    offset and view measured on the traces that survive it.

    The two banks are NOT the same shape and cannot be made so. A bank's
    height-to-width is `aspect x per_column x offset / x_range`; the native
    panel's window is a whole cycle - twelve falls on an Oyster run - where
    the normalised panel's is two, so for the same events the native bank
    comes out about six times shorter. That is arithmetic, not a layout
    choice, and it is why they are stacked rather than set side by side.
    """
    native, native_rows, reaches = drawing_rules.sequence_frames(members,
                                                                 snippets)
    phase, phase_rows = drawing_rules.phase_block(members, snippets)

    drawable = ({r["event_id"] for r in native_rows}
                & {r["event_id"] for r in phase_rows})
    reach_of = {r["event_id"]: v for r, v in zip(native_rows, reaches)}
    native = [tr for tr, r in zip(native, native_rows)
              if r["event_id"] in drawable]
    phase = [tr for tr, r in zip(phase, phase_rows)
             if r["event_id"] in drawable]
    rows = [r for r in native_rows if r["event_id"] in drawable]
    if not rows:
        return None

    # Rule 6's own cap first: at most 25 traces, evenly spaced, ends kept.
    drawn_rows, k = drawing_rules.thin(rows, limit=drawing_rules.MAX_TRACES)
    keep = {r["event_id"] for r in drawn_rows}
    native = [tr for tr, r in zip(native, rows) if r["event_id"] in keep]
    phase = [tr for tr, r in zip(phase, rows) if r["event_id"] in keep]

    median_fall = float(np.median([drawing_rules.fall_duration_s(r)
                                   for r in drawn_rows]))
    drawn_reach = np.array([reach_of[r["event_id"]] for r in drawn_rows])
    reach_falls = float(np.quantile(drawn_reach, NATIVE_REACH_QUANTILE))
    xlim = (-reach_falls * median_fall,
            (1.0 + drawing_rules.POST_TROUGH_FALLS) * median_fall)
    beyond = int(sum(1 for t, _y in native if float(t[-1]) > xlim[1]))
    short_of = int(np.sum(drawn_reach < reach_falls))
    z_xlim = (drawing_rules.PHASE_LO, drawing_rules.PHASE_HI)

    aspect = drawing_rules.figure_aspect(drawn_rows)[0]
    z_aspect = _z_aspect(phase)
    offset = drawing_rules.waterfall_offset(_clip_to_view(native, xlim))
    z_offset = drawing_rules.waterfall_offset(phase)

    per_column = min(
        drawing_rules.waterfall_capacity(aspect, offset, xlim[1] - xlim[0],
                                         len(drawn_rows)),
        drawing_rules.waterfall_capacity(z_aspect, z_offset,
                                         z_xlim[1] - z_xlim[0],
                                         len(drawn_rows)))
    n_columns = int(np.ceil(len(drawn_rows) / float(per_column))) or 1
    ratio = aspect * (per_column * offset) / (xlim[1] - xlim[0])
    z_ratio = z_aspect * (per_column * z_offset) / (z_xlim[1] - z_xlim[0])
    return {
        "rows": drawn_rows, "k": int(k), "n_available": len(rows),
        "native": native, "phase": phase,
        "xlim": xlim, "z_xlim": z_xlim, "n_beyond_x": beyond,
        "reach_falls": reach_falls, "n_short_of_reach": short_of,
        "median_fall_s": median_fall,
        "aspect": aspect, "z_aspect": z_aspect,
        "offset": offset, "z_offset": z_offset,
        "per_column": int(per_column), "n_columns": int(n_columns),
        "column_ratio": float(ratio), "z_column_ratio": float(z_ratio),
        "bank_height_in": float(min(NATIVE_COLUMN_W_IN * ratio,
                                    MAX_BANK_H_IN)),
        "z_bank_height_in": float(min(COLUMN_W_IN * z_ratio, MAX_BANK_H_IN)),
    }


# ==========================================================================
# S3.1  A waveform morphing across a sequence
# ==========================================================================

def plot_sequence_morph(run, snippets, path, *, sources, store_label="",
                        families=None, family_k=None, selection=""):
    """One sequence: reference strip, two waterfalls, the steps, the ends."""
    config11.apply_style()
    members = run["rows"]
    species = run["species"]
    resolved = config11.resolve([species])
    label = resolved[species]["label"]
    fs = float(members[0]["fs"])

    colours_list, norm, cmap = drawing_rules.time_colours(members, species,
                                                          resolved)
    colours = {row["event_id"]: colour
               for row, colour in zip(members, colours_list)}

    plan = _waterfall_plan(members, snippets)
    if plan is None:
        raise ValueError(f"{run['sequence_key']}: no drawable waveform")
    drawn_rows, k = plan["rows"], plan["k"]

    # The figure is sized from the panels rather than the other way round,
    # and the two banks are STACKED. They cannot be set side by side: the
    # native window is a whole cycle where the normalised window is two
    # falls, so for the same events the native bank is about six times the
    # shorter of the two, and any side-by-side row leaves one of them a
    # sliver in a mostly empty cell. Stacked, each is drawn at its own
    # honest proportion; the pairing survives because both banks hold the
    # same events in the same order, the same columns and the same
    # events-per-column.
    bank_h = plan["bank_height_in"]
    z_bank_h = plan["z_bank_height_in"]
    strip_h, step_h, ends_h = 1.5, 2.1, 3.0
    fig = plt.figure(
        figsize=(max(NATIVE_COLUMN_W_IN * plan["n_columns"] + 2.6, 9.5),
                 strip_h + bank_h + z_bank_h + step_h + ends_h + 2.2))
    outer = gridspec.GridSpec(
        5, 1, figure=fig, hspace=0.42, top=0.968, bottom=0.034,
        left=0.070, right=0.968,
        height_ratios=[strip_h, bank_h, z_bank_h, step_h, ends_h])

    # ---- rule 8: the raw reference strip --------------------------------
    strip_ax = fig.add_subplot(outer[0])
    start_idx, stop_idx = sources.span_for(members)
    x_mv = sources.slice_mv(members[0], start_idx, stop_idx)
    strip_note = ""
    if x_mv is None or not len(x_mv):
        strip_ax.text(0.5, 0.5, "source trace not reachable",
                      transform=strip_ax.transAxes, ha="center", va="center",
                      color="0.45", fontsize=config11.FS_ANNOT)
        strip_ax.set_axis_off()
        strip_note = "source trace unavailable; no reference strip"
    else:
        unit = "h" if (stop_idx - start_idx) / fs > 7200 else "s"
        drawing_rules.reference_strip(
            strip_ax, x_mv, fs, start_idx, members, colours_list,
            time_unit=unit)
        strip_ax.set_xlabel(f"time in recording ({unit})")
        config11.panel_title(
            strip_ax, f"{label} - source trace over the sequence, each "
                      f"detected event shaded", n=len(members))

    # ---- the two banks ---------------------------------------------------
    native_row = gridspec.GridSpecFromSubplotSpec(
        1, 2, subplot_spec=outer[1], wspace=0.05,
        width_ratios=[1.0, 0.022])

    aspect, offset = plan["aspect"], plan["offset"]
    ratio = drawing_rules.drawn_ratio(aspect, drawn_rows)
    native_axes = _bank(fig, native_row[0, 0], plan["native"], drawn_rows,
                        colours, aspect=aspect, offset=offset,
                        per_column=plan["per_column"], xlim=plan["xlim"],
                        ylim=_bank_ylim(_clip_to_view(plan["native"],
                                                      plan["xlim"]),
                                        offset, plan["per_column"]),
                        n_columns=plan["n_columns"], scale_unit="mV")
    native_axes[0].set_ylabel("mV, successive events offset")
    _cell_text(fig, native_row[0, 0],
               f"{label} - native units, whole cycle  "
               f"(n = {len(drawn_rows)})",
               above=True, fontsize=config11.FS_TITLE)
    _cell_text(fig, native_row[0, 0],
               f"time from onset (s), read down then across\n"
               f"each event framed back to the previous event's trough; "
               f"the view reaches {plan['reach_falls']:.3g} falls "
               f"({plan['reach_falls'] * plan['median_fall_s']:.3g} s) "
               f"before onset, and {plan['n_short_of_reach']} of "
               f"{len(drawn_rows)} events start inside it because their own "
               f"gap is shorter", above=False)

    phase_axes = _bank(fig, outer[2], plan["phase"], drawn_rows,
                       colours, aspect=plan["z_aspect"],
                       offset=plan["z_offset"],
                       per_column=plan["per_column"], xlim=plan["z_xlim"],
                       ylim=_bank_ylim(plan["phase"], plan["z_offset"],
                                       plan["per_column"]),
                       n_columns=plan["n_columns"], scale_unit="z")
    phase_axes[0].set_ylabel("z, successive events offset")
    _cell_text(fig, outer[2],
               f"{label} - per-event normalised, the fall  "
               f"(n = {len(drawn_rows)}, same events, same columns)",
               above=True, fontsize=config11.FS_TITLE)
    _cell_text(fig, outer[2],
               "fall-fractions from onset, read down then across\n"
               "0 is the onset, 1 the trough "
               "(both axes normalised per event)", above=False)

    bar_ax = fig.add_subplot(native_row[0, 1])
    if norm is None:
        bar_ax.set_axis_off()
    else:
        bar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap),
                           cax=bar_ax)
        bar.set_label("time from sequence start (s)",
                      fontsize=config11.FS_LABEL)
        bar.ax.tick_params(labelsize=config11.FS_TICK)

    # ---- successive difference -------------------------------------------
    step_ax = fig.add_subplot(outer[3])
    features, kept = drawing_rules.phase_features(members, snippets)
    steps = [drawing_rules.rms(features[i], features[i + 1])
             for i in range(len(features) - 1)]
    endpoints = (drawing_rules.rms(features[0], features[-1])
                 if len(features) >= 2 else float("nan"))
    below = sum(1 for step in steps if step < endpoints)
    if steps:
        step_ax.step(np.arange(1, len(steps) + 1), steps, where="mid",
                     color=resolved[species]["colour"], lw=1.4, zorder=3)
        step_ax.axhline(endpoints, color=style7.RULE_COLOUR, ls="--",
                        lw=style7.LW_RULE * 1.4, zorder=2)
        step_ax.annotate(f"first to last {endpoints:.2f}",
                         xy=(0.99, endpoints),
                         xycoords=("axes fraction", "data"),
                         xytext=(0, 4), textcoords="offset points",
                         ha="right", va="bottom",
                         fontsize=config11.FS_ANNOT, color="0.30")
        step_ax.set_ylim(0.0, max(max(steps), endpoints) * 1.35)
    step_ax.set_xlabel(f"step along the sequence\n"
                       f"{below} of {len(steps)} steps smaller than the "
                       f"first-to-last distance")
    step_ax.set_ylabel("distance (z RMS)")
    config11.panel_title(step_ax, "Distance between successive events",
                         n=len(steps))
    step_ax.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)

    # ---- start against end, as real waveforms ----------------------------
    ends = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=outer[4],
                                            wspace=0.30,
                                            width_ratios=[1.0, 1.0])
    first_family = (families or {}).get(kept[0]["event_id"]) if kept else None
    last_family = (families or {}).get(kept[-1]["event_id"]) if kept else None
    pair_rows = [kept[0], kept[-1]] if len(kept) >= 2 else list(kept)

    native_ends = fig.add_subplot(ends[0, 0])
    ends_aspect, ends_ratio, _capped = drawing_rules.figure_aspect(pair_rows)
    for row, dash, family in zip(
            pair_rows, ("-", (0, (4, 2))), (first_family, last_family)):
        t, y, _complete = drawing_rules.framed_trace(row, snippets)
        if t is None:
            continue
        native_ends.plot(
            t, y, color=colours[row["event_id"]], lw=LW_ENDS, ls=dash,
            zorder=3, solid_capstyle="round",
            label=f"F{family}  "
                  f"{abs(float(row['drop_depth_mv'])):.3g} mV / "
                  f"{drawing_rules.fall_duration_s(row):.3g} s")
    native_ends.axvline(0.0, color=style7.RULE_COLOUR, ls="--",
                        lw=style7.LW_RULE, alpha=0.45, zorder=1)
    drawing_rules.apply_aspect(native_ends, ends_aspect)
    native_ends.set_xlabel("time from onset (s)")
    native_ends.set_ylabel("mV")
    native_ends.legend(loc="lower right", frameon=False,
                       fontsize=config11.FS_LEGEND)
    native_ends.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)
    config11.panel_title(native_ends, "First and last event - native units")

    phase_ends = fig.add_subplot(ends[0, 1])
    for row, dash, family in zip(
            pair_rows, ("-", (0, (4, 2))), (first_family, last_family)):
        p, z = drawing_rules.phase_trace(row, snippets)
        if p is None:
            continue
        phase_ends.plot(p, z, color=colours[row["event_id"]], lw=LW_ENDS,
                        ls=dash, zorder=3, solid_capstyle="round",
                        label=f"F{family}")
    phase_ends.set_xlim(drawing_rules.PHASE_LO, drawing_rules.PHASE_HI)
    phase_ends.set_xlabel("fall-fractions from onset\n"
                          "(both axes normalised per event)")
    phase_ends.set_ylabel("z")
    phase_ends.legend(loc="lower right", frameon=False,
                      fontsize=config11.FS_LEGEND)
    phase_ends.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)
    same = first_family is not None and first_family == last_family
    config11.panel_title(
        phase_ends,
        f"First and last event - families F{first_family} and F{last_family}"
        if not same else f"First and last event - both family F{first_family}")

    fig.suptitle(f"{label} sequence {run['sequence_key']}",
                 fontsize=config11.FS_SUPTITLE, y=0.999)
    footer = drawing_rules.rules_footer(aspect, ratio,
                                        n_drawn=len(drawn_rows), k=k)
    extra = (f"{selection}; {footer}; banked "
             f"{plan['n_columns']} x {plan['per_column']}")
    if strip_note:
        extra += f"; {strip_note}"
    config11.footer(fig, store_label, run["n"], extra=extra)

    ok, why = drawing_rules.check_drop_shape(ratio)
    manifest = {
        "store": store_label,
        "run": "drop_motifs12b",
        "selection_rule": selection,
        "sequence": {key: run[key] for key in sequences11.FIELDS},
        "n_events": run["n"],
        "n_drawn": len(drawn_rows),
        "n_drawable": plan["n_available"],
        "every_kth_drawn": int(k),
        "bank": {"columns": plan["n_columns"],
                 "per_column": plan["per_column"],
                 "column_height_to_width": plan["column_ratio"]},
        "waterfall_offset_mv": float(offset),
        "waterfall_offset_z": float(plan["z_offset"]),
        "waterfall_offset_rule":
            f"{drawing_rules.OFFSET_FRACTION} x the median drawn "
            f"peak-to-peak of the traces in the panel",
        "aspect_seconds_per_mv": float(aspect),
        "normalised_aspect_z_per_fall": float(plan["z_aspect"]),
        "median_event_drawn_ratio": float(ratio),
        "drop_shape_ok": bool(ok),
        "drop_shape_note": why,
        "frame": f"{drawing_rules.PRE_ONSET_FALLS} falls before onset to "
                 f"{drawing_rules.POST_TROUGH_FALLS} falls after trough",
        "native_frame": "back to the previous event's trough, capped at "
                        f"{drawing_rules.MAX_PRE_FALLS} falls",
        "native_view_reach_falls": plan["reach_falls"],
        "native_view_s": list(plan["xlim"]),
        "native_view_quantile": NATIVE_REACH_QUANTILE,
        "n_traces_beyond_native_view": plan["n_beyond_x"],
        "n_events_starting_inside_view": plan["n_short_of_reach"],
        "bank_column_height_to_width": {
            "native": plan["column_ratio"],
            "normalised": plan["z_column_ratio"]},
        "normalised_axis": [drawing_rules.PHASE_LO, drawing_rules.PHASE_HI],
        "reference_strip": {
            "drawn": not bool(strip_note),
            "start_idx": int(start_idx), "stop_idx": int(stop_idx),
            "note": strip_note or "min-max envelope, never a stride",
        },
        "family_cut_k": family_k,
        "first_family": first_family,
        "last_family": last_family,
        "ends_in_same_family": bool(same),
        "step_distance_z_rms": {
            "median": float(np.median(steps)) if steps else float("nan"),
            "max": float(np.max(steps)) if steps else float("nan"),
            "n_steps": len(steps),
        },
        "first_to_last_z_rms": endpoints,
        "steps_below_endpoint_distance": int(below),
        "distance": (f"Euclidean over {drawing_rules.N_FEATURE}-point "
                     f"z-normalised PHASE frames "
                     f"({drawing_rules.PHASE_LO} to {drawing_rules.PHASE_HI} "
                     f"fall-fractions), / sqrt(n); a distance "
                     f"representation, never drawn"),
    }
    config11.save(fig, path)
    config11.write_manifest(path, manifest)
    return manifest


# ==========================================================================
# S3.2  Morph across scales - the contact-sheet catalogue
# ==========================================================================

def plot_morph_across_scales(runs, snippets, path, *, store_label="",
                             summary=None, candidates=None,
                             columns=CONTACT_COLUMNS):
    """One row per species; within a row, that sequence's events as small
    panels in time order, in `id385_contact.png`'s style."""
    config11.apply_style()
    species = config11.order({run["species"] for run in runs})
    resolved = config11.resolve(species)

    chosen = {}
    for name in species:
        run = sequences11.clearest(runs, name)
        if run is not None:
            chosen[name] = run
    ordered = sorted(chosen, key=lambda name: chosen[name]["median_fall_s"])
    if not ordered:
        raise ValueError("no qualifying sequence in any species")

    fig = plt.figure(figsize=(CONTACT_PANEL_W_IN * columns + 2.0,
                              (CONTACT_PANEL_H_IN + 0.95) * len(ordered) + 1.0))
    grid = gridspec.GridSpec(len(ordered), 1, figure=fig, hspace=0.92,
                             top=0.945, bottom=0.055, left=0.055, right=0.985)

    manifest = {"store": store_label, "run": "drop_motifs12b", "rows": [],
                "layout": "small multiples, one panel per event, "
                          "Plots/drop_motifs5/id385_contact.png style",
                "selection_rule": "sequences11.clearest - longest, then most "
                                  "regular among runs within 60% of that "
                                  "length",
                "row_order": "ascending median native fall duration",
                "sequence_thresholds": (summary or {}).get("thresholds")}

    for index, name in enumerate(ordered):
        run = chosen[name]
        members = run["rows"]
        colours_list, _norm, _cmap = drawing_rules.time_colours(
            members, name, resolved)
        colours = {row["event_id"]: c
                   for row, c in zip(members, colours_list)}
        drawn, k = drawing_rules.thin(members, limit=columns)
        aspect = drawing_rules.figure_aspect(drawn)[0]

        strip = gridspec.GridSpecFromSubplotSpec(
            1, columns, subplot_spec=grid[index], wspace=0.46)
        ratios = []
        for column in range(columns):
            ax = fig.add_subplot(strip[0, column])
            if column >= len(drawn):
                ax.set_axis_off()
                continue
            row = drawn[column]
            t, y, _complete = drawing_rules.framed_trace(row, snippets)
            if t is None:
                ax.set_axis_off()
                continue
            depth = abs(float(row["drop_depth_mv"]))
            fall = drawing_rules.fall_duration_s(row)

            # The raw trace faint beneath the detrended one, as
            # `id385_contact.png` does: the detrend is what the detector
            # measured on and the raw is what the electrode recorded, and a
            # reader is entitled to see both.
            raw_t, raw_y, _ = drawing_rules.framed_trace(row, snippets,
                                                         field="raw_mv")
            if raw_t is not None:
                ax.plot(raw_t, raw_y, color="0.62", lw=0.7, zorder=2,
                        solid_capstyle="round")

            ax.axvspan(0.0, fall, color=colours[row["event_id"]], alpha=0.22,
                       lw=0.0, zorder=1)
            ax.plot(t, y, color=colours[row["event_id"]], lw=1.3, zorder=3,
                    solid_capstyle="round")
            ax.axvline(0.0, color=style7.RULE_COLOUR, ls="--",
                       lw=style7.LW_RULE, alpha=0.45, zorder=1)
            ax.set_xlim(CONTACT_VIEW_FALLS[0] * fall,
                        CONTACT_VIEW_FALLS[1] * fall)
            ax.set_ylim(CONTACT_VIEW_DEPTH[0] * depth,
                        CONTACT_VIEW_DEPTH[1] * depth)
            panel_aspect = drawing_rules.figure_aspect([row])[0]
            drawing_rules.apply_aspect(ax, panel_aspect)
            ratios.append(drawing_rules.drawn_ratio(panel_aspect, [row]))
            ax.set_title(f"{depth:.3g} mV / {fall:.3g} s",
                         fontsize=config11.FS_ANNOT, pad=2.5)
            ax.tick_params(labelsize=config11.FS_TICK - 1.0)
            ax.set_yticks([])
            if column == 0:
                ax.set_ylabel(f"{resolved[name]['label']}\nmV",
                              fontsize=config11.FS_LABEL)
            ax.grid(alpha=0.12, lw=style7.LW_RULE * 0.5)
        ratio = float(np.median(ratios)) if ratios else float("nan")

        per = (summary or {}).get("per_species", {}).get(name, {})
        pool = (candidates or {}).get(name)
        scarcity = (f"; {per.get('runs', 0)} of {pool} candidate runs pass "
                    f"the regularity gate" if pool is not None and per else "")
        duration_range = store11.range_label(members, "fall_duration_s", "s")
        depth_range = store11.range_label(members, "drop_depth_mv", "mV")
        # One caption per row, hung under the strip, naming the row's own
        # native scale. Positioned from the GRIDSPEC cell rather than from
        # an axes: the panels are aspect-locked, so each one's box has been
        # reshaped inside its cell and no single axes' position describes
        # the row. `get_position(fig)` asks the cell, which has not moved.
        cell = grid[index].get_position(fig)
        fig.text(0.012, cell.y0 - 0.012,
                 f"{resolved[name]['label']} - {run['sequence_key']}  |  "
                 f"n = {run['n']} events, {drawing_rules.every_kth(k)} drawn  |  "
                 f"native: fall {duration_range}, depth {depth_range}  |  "
                 f"each panel locked to its own event; median event drawn "
                 f"{ratio:.2g}:1 height-to-width; view "
                 f"{CONTACT_VIEW_FALLS[0]:+g} to {CONTACT_VIEW_FALLS[1]:+g} "
                 f"falls, raw trace faint beneath{scarcity}",
                 fontsize=config11.FS_ANNOT, color="0.30", va="top")

        ok, why = drawing_rules.check_drop_shape(ratio)
        manifest["rows"].append({
            "species": name,
            "label": resolved[name]["label"],
            "sequence_key": run["sequence_key"],
            "n_events": run["n"],
            "n_drawn": len(drawn),
            "every_kth_drawn": int(k),
            "row_aspect_seconds_per_mv": float(aspect),
            "panel_lock": "per panel, on that event's own depth and fall",
            "view_falls": list(CONTACT_VIEW_FALLS),
            "view_depths": list(CONTACT_VIEW_DEPTH),
            "median_event_drawn_ratio": float(ratio),
            "drop_shape_ok": bool(ok),
            "drop_shape_note": why,
            "cv_interval": run["cv_interval"],
            "r2_trend": run["r2_trend"],
            "drift_ratio": run["drift_ratio"],
            "arm": run["arm"],
            "median_fall_s": run["median_fall_s"],
            "median_depth_mv": run["median_depth_mv"],
            "fall_duration_s_range": list(
                store11.span_of(members, "fall_duration_s")),
            "drop_depth_mv_range": list(
                store11.span_of(members, "drop_depth_mv")),
            "qualifying_runs": per.get("runs"),
            "candidate_runs": pool,
        })

    fig.suptitle("One qualifying sequence per species, event by event",
                 fontsize=config11.FS_SUPTITLE, y=0.998)
    config11.footer(fig, store_label,
                    sum(run["n"] for run in chosen.values()),
                    extra="rows ordered by native fall duration; each panel "
                          "is real samples against seconds from its own "
                          "onset, fall span shaded")
    config11.save(fig, path)
    config11.write_manifest(path, manifest)
    return manifest


# ==========================================================================
# S3.3  Isolated events - a probe, drawn only if the effect exists
# ==========================================================================

def probe_isolated_pairs(rows, species, path, *, store_label="",
                         n_shuffles=1000, draw=True):
    """Unchanged in method from round 11, re-run on the new store.

    The work order asks for the same test against a larger corpus, not a
    different test, so this delegates to `figures11_s3.probe_isolated_pairs`
    rather than restating it. A second implementation of one permutation
    test is how two runs come to disagree about a p-value.
    """
    from Pipelines.drop_motifs import figures11_s3

    return figures11_s3.probe_isolated_pairs(
        rows, species, path, store_label=store_label,
        n_shuffles=n_shuffles, draw=draw)
