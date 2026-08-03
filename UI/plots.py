"""
plots.py
=========
HoloViews / Datashader construction for the signal viewer. Pure
plotting/data-loading code — no Panel widgets, no callbacks wired to the
database. `app.py` composes these into the interactive app.

Only this package (`UI/`) is allowed to import Panel, HoloViews or
Datashader — see the root README's UI rule. Nothing here is imported by
`Working/` or `Pipelines/`.

Rendering strategy
-------------------
A channel is 1-3M+ samples. Rather than handing the whole array to
`rasterize` once and letting it re-aggregate the full array on every zoom,
`build_channel_dmap` drives a `hv.DynamicMap` off a `hv.streams.RangeX`
stream: each callback slices the memory-mapped `.npy` to just the currently
visible span (only that span pages in off disk) and builds a `hv.Curve`
from the slice, which `rasterize` then aggregates. At full zoom-out the
slice is the whole channel (rasterize handles that in well under a second);
at high zoom the slice is small and rasterize effectively shows every
sample — "honest" at every zoom level, per the brief (`rasterize`, not
`datashade`, so aggregated values stay inspectable rather than being
baked into a fixed RGB image).
"""

import numpy as np
import holoviews as hv
from holoviews.operation.datashader import rasterize

hv.extension("bokeh")

VERDICT_COLORS = {
    "interesting": "#2ca02c",
    "not_interesting": "#7f7f7f",
    "artifact": "#d62728",
    "unsure": "#9467bd",
}
REVIEWED_COLOR = "#1f77b4"


def load_channel_mmap(npy_path):
    """Memory-map a materialized channel .npy — pages in lazily on slicing."""
    return np.load(npy_path, mmap_mode="r")


def format_scale_viewed(x_range, full_extent):
    """Human-readable label for the zoom span active right now, e.g.
    '10min', '45s', '2.3h' — stored on every annotation as `scale_viewed`."""
    x0, x1 = x_range if x_range is not None else full_extent
    span_s = max(x1 - x0, 0.0)
    if span_s < 90:
        return f"{span_s:.0f}s"
    if span_s < 5400:
        return f"{span_s / 60:.1f}min"
    return f"{span_s / 3600:.2f}h"


def build_channel_dmap(npy_path, fs, n_samples, height=350):
    """Build the rasterized, zoom-driven curve for one channel.

    Returns
    -------
    (rasterized_dmap, range_stream, full_extent, y_extent)
        `range_stream.x_range` is the live (x0, x1) in seconds — read it
        wherever "the zoom span active right now" is needed (annotation
        scale_viewed, "mark viewport reviewed"). `y_extent` is the padded
        (min, max) of the whole channel — used to size annotation/reviewed
        rectangles so they visually fill the plot's vertical extent, and to
        fix the y-axis so panning/zooming horizontally doesn't rescale it.
    """
    data = load_channel_mmap(npy_path)
    full_extent = (0.0, (n_samples - 1) / fs)
    y_min, y_max = float(np.min(data)), float(np.max(data))
    pad = (y_max - y_min) * 0.05 or 1.0
    y_extent = (y_min - pad, y_max + pad)

    def _callback(x_range):
        if x_range is None or x_range[0] is None or x_range[1] is None:
            x0, x1 = full_extent
        else:
            x0, x1 = x_range
        x0 = max(x0, full_extent[0])
        x1 = min(x1, full_extent[1])
        if x1 <= x0:
            x0, x1 = full_extent

        i0 = max(0, int(np.floor(x0 * fs)))
        i1 = min(n_samples, int(np.ceil(x1 * fs)) + 1)
        if i1 <= i0:
            i1 = min(n_samples, i0 + 1)

        x_slice = np.asarray(data[i0:i1])       # pages in only this span
        t_slice = np.arange(i0, i1) / fs
        return hv.Curve((t_slice, x_slice), "time_s", "amplitude")

    range_stream = hv.streams.RangeX(x_range=full_extent)
    dmap = hv.DynamicMap(_callback, streams=[range_stream])
    rasterized = rasterize(dmap, precompute=False).opts(
        cmap="Blues", colorbar=False, height=height, responsive=True,
        tools=["xwheel_zoom"], active_tools=["xwheel_zoom", "xpan"],
        xlabel="time (s)", ylabel="amplitude", ylim=y_extent,
    )
    return rasterized, range_stream, full_extent, y_extent


def _empty_rectangles():
    return hv.Rectangles([]).opts(alpha=0)


def build_annotation_overlay(annotation_rows, fs, y_extent):
    """Annotations as full-height rectangles, colored by verdict.

    A channel can carry hundreds of annotations (this one has ~700), so
    each group (imported vs manual) is built as a *single* vectorized
    `hv.Rectangles` element rather than one HoloViews element per row —
    overlaying hundreds of individual elements makes HoloViews' path
    de-duplication pathologically slow (confirmed: multi-minute hangs
    building the Bokeh model for ~700 separate hv.VSpan elements).
    Vectorized rectangles render in well under a second regardless of count.

    Shaded differently for imported_10min (low alpha, no border) vs
    manual_ui (higher alpha, black border) so both are distinguishable
    "at a glance", per the brief.
    """
    from Working.Preprocessing.database.queries import SOURCE_IMPORTED_10MIN

    y0, y1 = y_extent
    imported_rows = [r for r in annotation_rows if r["source"] == SOURCE_IMPORTED_10MIN]
    manual_rows = [r for r in annotation_rows if r["source"] != SOURCE_IMPORTED_10MIN]

    def _rect_data(rows):
        return [(r["start_idx"] / fs, y0, r["end_idx"] / fs, y1, r["verdict"]) for r in rows]

    elems = []
    if imported_rows:
        elems.append(
            hv.Rectangles(_rect_data(imported_rows), vdims=["verdict"]).opts(
                color="verdict", cmap=VERDICT_COLORS, alpha=0.25, line_width=0,
            )
        )
    if manual_rows:
        elems.append(
            hv.Rectangles(_rect_data(manual_rows), vdims=["verdict"]).opts(
                color="verdict", cmap=VERDICT_COLORS, alpha=0.5,
                line_color="black", line_width=1,
            )
        )
    if not elems:
        elems.append(_empty_rectangles())
    return hv.Overlay(elems)


def build_reviewed_overlay(reviewed_rows, fs, y_extent):
    """Faint background bands marking spans that have been examined at all
    (independent of whether anything was annotated in them). One vectorized
    `hv.Rectangles` element for the same scaling reason as annotations."""
    y0, y1 = y_extent
    if not reviewed_rows:
        return hv.Overlay([_empty_rectangles()])
    data = [(r["start_idx"] / fs, y0, r["end_idx"] / fs, y1) for r in reviewed_rows]
    return hv.Overlay([
        hv.Rectangles(data).opts(color=REVIEWED_COLOR, alpha=0.06, line_width=0)
    ])


def build_pending_selection_overlay(bounds):
    """The currently drag-selected (not yet saved) span, if any."""
    if bounds is None or bounds[0] is None or bounds[1] is None:
        return hv.Overlay([hv.VSpan(0, 0).opts(alpha=0)])
    x0, x1 = bounds
    return hv.Overlay([hv.VSpan(x0, x1).opts(
        color="black", alpha=0.12, line_color="black", line_width=1, line_dash="dashed",
    )])
