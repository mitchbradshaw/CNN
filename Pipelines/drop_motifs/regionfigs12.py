"""
regionfigs12.py
================
The region overview: all five channels stacked over one operator-chosen
region, so the context the events sit in is visible before any detection is
argued about.

Drawn twice - once before detection and once after, with the detected events
shaded on the analysed channel - because the pre-detection figure is the one
that can be checked against the operator's own screenshot without any of
this run's choices in it.

Every waveform here is real samples
-----------------------------------
Drawing rule 1 of the work order, and it binds harder on a 350-hour region
than anywhere else: 12.6 million samples cannot be drawn one per pixel, and
the obvious remedy - `x[::step]` - is a resample, which throws away exactly
the narrow events this figure exists to show. A 4-second CH2 spike is 40
samples; at a stride of 630 it is invisible unless it happens to land on a
kept sample.

`envelope` instead draws the MIN AND MAX of every pixel column as a vertical
extent. No sample is invented and no excursion is lost: a spike one sample
wide still reaches its true depth on the page. What is lost is the shape
inside a column, which at this zoom is below one pixel anyway.

No aspect lock on these panels, and the reason is stated rather than assumed
away: a 350-hour panel drawn at the events' own millivolt-per-second would be
about four metres wide. The pipeline plots (`pipelines12`) are where the
locked-aspect rule applies, because there a window is a few hundred seconds
and the lock is achievable.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from Pipelines.drop_motifs import lionsmane12, style7

# Columns of envelope across a panel. Above the panel's pixel width this
# buys nothing; 4000 covers a 16-inch panel at 250 dpi.
ENVELOPE_COLUMNS = 4000

ANALYSED_COLOUR = "#1b6ca8"
QUIET_COLOUR = "#7a7a7a"
EVENT_COLOUR = "#d95f02"
ID385_COLOUR = "#4d9221"


def envelope(x, columns=ENVELOPE_COLUMNS):
    """`(centres, lo, hi)` - the min and max of each pixel column.

    Not a stride. See the module docstring: a stride is a resample and it
    deletes narrow events; an envelope keeps every excursion's true extent.
    """
    x = np.asarray(x, dtype=float).ravel()
    n = x.size
    columns = int(min(columns, n))
    if columns < 1:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    if n <= columns:
        index = np.arange(n, dtype=float)
        return index, x, x

    edges = np.linspace(0, n, columns + 1).astype(np.int64)
    lo = np.empty(columns)
    hi = np.empty(columns)
    for i in range(columns):
        block = x[edges[i]:edges[i + 1]]
        if block.size == 0:
            lo[i] = hi[i] = np.nan
            continue
        lo[i] = block.min()
        hi[i] = block.max()
    centres = (edges[:-1] + edges[1:]) / 2.0
    return centres, lo, hi


def plot_region(region, out_path, *, rows=None, id385=None, title=None,
                floor_note=None):
    """Five channels stacked over one region; `rows` shades detected events.

    `rows` are store rows with absolute `onset_idx` / `trough_idx`; only
    those on the region's own channel are shaded, and the other four panels
    are labelled with the fact that they carry none. That labelling is the
    point: "CH0, CH1 and CH4 carry no detections" is a result of this run
    and has to be legible on the figure, not only in the manifest.
    """
    style7.apply_style()
    region = lionsmane12.REGIONS[region] if isinstance(region, str) else region
    rows = list(rows or [])

    fig, axes = plt.subplots(
        lionsmane12.N_CHANNELS, 1, figsize=(16.0, 11.6), sharex=True,
        gridspec_kw=dict(hspace=0.16, left=0.075, right=0.985,
                         top=0.845, bottom=0.055))

    per_channel = {}
    for channel, ax in enumerate(axes):
        x_mv = lionsmane12.load_channel(
            channel, region.start, region.stop) * 1000.0
        centres, lo, hi = envelope(x_mv)
        index = region.start + centres
        analysed = channel == region.channel
        colour = ANALYSED_COLOUR if analysed else QUIET_COLOUR

        ax.fill_between(index, lo, hi, color=colour, lw=0.0,
                        alpha=0.95 if analysed else 0.65)
        ax.set_ylabel(f"CH{channel}\nmV", fontsize=9,
                      color="#111111" if analysed else "0.35")
        ax.grid(alpha=0.16)
        ax.tick_params(labelsize=8)

        mine = [r for r in rows if int(r["channel"]) == channel]
        for row in mine:
            ax.axvspan(int(row["onset_idx"]), int(row["trough_idx"]),
                       color=EVENT_COLOUR, alpha=0.45, lw=0.0, zorder=3)
        if mine:
            # A shaded span is SUB-PIXEL at this zoom and cannot carry the
            # count: a 15-sample event across 3.34 million samples is one
            # 220,000th of the panel's width, so 844 of them render as a
            # handful of visible marks and the figure silently understates
            # its own result. The rug is one tick per event along the
            # bottom, which is the distribution the spans cannot show.
            ax.plot([int(r["onset_idx"]) for r in mine],
                    np.full(len(mine), 0.02), marker="|", ls="none",
                    ms=6, mew=0.7, color=EVENT_COLOUR, alpha=0.85,
                    transform=ax.get_xaxis_transform(), zorder=7,
                    clip_on=False)

        if analysed:
            note = (f"ANALYSED  ·  {len(mine)} events — shaded onset → "
                    "trough, and one rug tick each along the bottom"
                    if rows else "ANALYSED  ·  pre-detection")
        else:
            note = "not analysed — no detection was run on this channel"
        ax.set_title(f"CH{channel}  ·  {note}", fontsize=9, loc="left",
                     color="#111111" if analysed else "0.4")

        per_channel[f"CH{channel}"] = {
            "analysed": bool(analysed),
            "n_events": len(mine),
            "min_mv": float(np.nanmin(lo)),
            "max_mv": float(np.nanmax(hi)),
        }
        if id385 and channel == int(id385["channel"]):
            ax.axvspan(int(id385["start_idx"]), int(id385["stop_idx"]),
                       facecolor="none", edgecolor=ID385_COLOUR, lw=1.6,
                       zorder=6)

    axes[-1].set_xlabel(
        f"sample index in {lionsmane12.STEM} "
        f"(fs = {lionsmane12.FS:g} Hz, so 1 h = {int(3600 * lionsmane12.FS):,} samples)")
    axes[-1].set_xlim(region.start, region.stop)

    hours = axes[0].secondary_xaxis(
        "top", functions=(lambda s: (s - region.start) / lionsmane12.FS / 3600.0,
                          lambda h: h * 3600.0 * lionsmane12.FS + region.start))
    # No xlabel: it would land in the same strip as the legend and the
    # first panel's own title. The subtitle names the axis instead.
    hours.tick_params(labelsize=8)

    handles = [
        Line2D([], [], color=ANALYSED_COLOUR, lw=6,
               label=f"CH{region.channel} — the analysed channel"),
        Line2D([], [], color=QUIET_COLOUR, lw=6, label="not analysed"),
    ]
    if rows:
        handles.append(Line2D([], [], color=EVENT_COLOUR, lw=6, alpha=0.6,
                              label="detected event, onset → trough "
                                    "(plus one rug tick each, below)"))
    if id385:
        handles.append(Line2D([], [], color=ID385_COLOUR, lw=1.6,
                               label="catalogue ID 385, located by "
                                     f"cross-correlation (r = {id385['r']:.4f})"))

    subtitle = (f"{region.n_samples:,} samples = {region.hours:.0f} h at "
                f"{lionsmane12.FS:g} Hz  ·  {region.note}\n"
                "every column is drawn as the min–max of its samples, not as "
                "a stride, so no narrow event is lost to decimation  ·  "
                "top axis: hours into the region")
    if floor_note:
        subtitle += f"\n{floor_note}"
    fig.suptitle(title or f"{lionsmane12.STEM} — {region.label}",
                 fontsize=13, y=0.988)
    fig.text(0.5, 0.945, subtitle, fontsize=9, ha="center", va="top",
             color="0.30", linespacing=1.5)
    # Below the hours axis, not over it: the secondary axis and its label
    # occupy the strip immediately above the first panel.
    fig.legend(handles=handles, fontsize=8.5, frameon=False,
               ncol=len(handles), loc="upper center",
               bbox_to_anchor=(0.53, 0.917))

    fig.savefig(out_path, dpi=170)
    plt.close(fig)
    return str(out_path), {
        "region": region.key,
        "channel": region.channel,
        "start_idx": region.start,
        "stop_idx": region.stop,
        "n_samples": region.n_samples,
        "hours": region.hours,
        "envelope_columns": ENVELOPE_COLUMNS,
        "n_events_shaded": len(rows),
        "per_channel": per_channel,
    }
