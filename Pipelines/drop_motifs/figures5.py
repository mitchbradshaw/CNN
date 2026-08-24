"""
figures5.py
============
Contact sheets for the five-stage detector: every detected event in its
own panel, at raw amplitude, in absolute time.

Why a contact sheet and not an overlay
--------------------------------------
An overlay is what hid the defect. A window holding three spikes drawn on
top of four others that also hold three looks like a busy family; it takes
seeing the panels side by side to notice that every one of them is a
train. The whole objective of this pass of work is "one window, one
spike", and the only figure that answers it directly is one panel per
window.

The overlay is still drawn, once per span, underneath the sheet - but as
the SECOND figure, and with the purity score printed on it, so a reader
who looks at an overlay is told how much to trust it.

Amplitude is raw millivolts and is never normalised, at the operator's
request and consistent with the existing figures: normalising amplitude
destroys the evidence of scaling in depolarisation events. Time is
absolute seconds. The detrended trace the detector actually encoded is
drawn faintly under the raw trace so a reader comparing a panel to the
verdict is looking at the same signal the detector saw.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

# One colour per morphology, so a reader flipping between spans can see
# which rule produced a window without reading the title.
MORPHOLOGY_COLOUR = {"sharkfin": "#1f77b4", "trough": "#2ca02c"}
IMPURE_COLOUR = "#d62728"

RAW_KW = dict(lw=0.9, zorder=3)
DETREND_KW = dict(lw=0.7, alpha=0.35, color="0.35", zorder=2)


def _panel(ax, x_raw, x_detrended, event, fs, score, colour):
    """One event, in absolute seconds from its own drop onset."""
    start, end = event.window_start_idx, event.window_end_idx
    if end <= start:
        ax.set_axis_off()
        return

    t = (np.arange(start, end) - event.onset_idx) / fs
    raw = x_raw[start:end] * 1000.0
    detrended = x_detrended[start:end] * 1000.0

    # The raw trace carries the recording's DC offset and the detrended one
    # does not, so plotting both on one axis would put them decades apart.
    # The detrended trace is shifted onto the raw trace's own level at the
    # onset: it is drawn to show SHAPE agreement, not absolute level.
    offset = raw[event.onset_idx - start] - detrended[event.onset_idx - start]

    ax.plot(t, detrended + offset, **DETREND_KW)
    ax.plot(t, raw, color=colour, **RAW_KW)
    ax.axvline(0.0, color="0.4", ls="--", lw=0.8, zorder=1)
    ax.axvspan(0.0, (event.trough_idx - event.onset_idx) / fs,
               color=colour, alpha=0.10, zorder=0)

    ax.set_title(
        f"{event.drop_depth_mv:.1f} mV / {event.fall_duration_s:.0f} s"
        + ("" if score == 1 else f"  [{score} falls]"),
        fontsize=7,
        color="black" if score == 1 else IMPURE_COLOUR)
    ax.tick_params(labelsize=6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def draw_contact_sheets(x, tuned, purity, summary, out_dir,
                        panels_per_sheet=24):
    """One panel per event, paginated. Returns the paths written."""
    events = tuned.events
    fs = summary["fs"]
    stem = f"id{summary['catalogue_id']:03d}"
    paths = []

    if not events:
        return paths

    x_detrended = tuned.result.x_detrended
    base = MORPHOLOGY_COLOUR.get(summary["morphology"], "#1f77b4")

    pages = int(np.ceil(len(events) / panels_per_sheet))
    for page in range(pages):
        chunk = events[page * panels_per_sheet:(page + 1) * panels_per_sheet]
        scores = purity[page * panels_per_sheet:(page + 1) * panels_per_sheet]
        cols = min(4, len(chunk))
        rows = int(np.ceil(len(chunk) / cols))

        fig, axes = plt.subplots(rows, cols, figsize=(3.1 * cols, 2.2 * rows),
                                 squeeze=False)
        for index, ax in enumerate(axes.ravel()):
            if index >= len(chunk):
                ax.set_axis_off()
                continue
            score = scores[index] if index < len(scores) else 1
            _panel(ax, x, x_detrended, chunk[index], fs, score,
                   base if score == 1 else IMPURE_COLOUR)

        suffix = f" - sheet {page + 1} of {pages}" if pages > 1 else ""
        fig.suptitle(
            f"catalogue ID {summary['catalogue_id']}  ·  "
            f"{summary['morphology']}  ·  n={len(events)}  ·  "
            f"{summary['purity_clean_fraction']:.0%} of windows hold exactly "
            f"one fall{suffix}\n"
            f"raw mV, absolute seconds from each event's own drop onset; "
            f"detrended trace faint beneath",
            fontsize=9)
        fig.supxlabel("time from drop onset (s)", fontsize=8)
        fig.supylabel("amplitude (mV, raw)", fontsize=8)
        fig.tight_layout(rect=(0.01, 0.01, 1, 0.94))

        path = out_dir / (f"{stem}_contact.png" if pages == 1
                          else f"{stem}_contact_{page + 1}.png")
        fig.savefig(path, dpi=130)
        plt.close(fig)
        paths.append(str(path))

    paths.append(_draw_overlay(x, tuned, purity, summary, out_dir, stem))
    return paths


def _draw_overlay(x, tuned, purity, summary, out_dir, stem):
    """The overlay, drawn second and captioned with its own purity.

    Kept because it is the view the downstream clustering consumes, and
    labelled because an overlay of impure windows is exactly the figure
    that misled once already.
    """
    fs = summary["fs"]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    base = MORPHOLOGY_COLOUR.get(summary["morphology"], "#1f77b4")

    for index, event in enumerate(tuned.events):
        start, end = event.window_start_idx, event.window_end_idx
        if end <= start:
            continue
        score = purity[index] if index < len(purity) else 1
        t = (np.arange(start, end) - event.onset_idx) / fs
        ax.plot(t, x[start:end] * 1000.0,
                color=base if score == 1 else IMPURE_COLOUR,
                alpha=0.75 if score == 1 else 0.5,
                lw=0.9 if score == 1 else 0.7)

    ax.axvline(0.0, color="0.4", ls="--", lw=0.9)
    ax.set_xlabel("time from drop onset (s)")
    ax.set_ylabel("amplitude (mV, raw)")
    impure = sum(1 for p in purity if p != 1)
    ax.set_title(
        f"catalogue ID {summary['catalogue_id']}  ·  {summary['morphology']}"
        f"  ·  n={len(tuned.events)}  ·  "
        f"{summary['purity_clean_fraction']:.0%} clean"
        + (f"  ·  {impure} impure drawn red" if impure else ""),
        fontsize=10)
    ax.grid(alpha=0.25)
    fig.tight_layout()

    path = out_dir / f"{stem}_overlay.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return str(path)
