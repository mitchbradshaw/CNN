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
A channel is 1-3M+ samples. `build_channel_dmap` drives a `hv.DynamicMap`
off a `hv.streams.RangeX` stream: each callback slices the memory-mapped
`.npy` to just the currently visible span (only that span pages in off
disk) and builds a `hv.Curve` from it — always a `Curve`, never a
datashader `Image` (see bug 3 below for why that distinction matters).
Above `MAX_RENDER_POINTS` samples in the slice, it's reduced with min/max
decimation (`_minmax_decimate`) rather than simple striding, so spikes
survive zoomed-out view instead of being aliased away between kept samples
— this app exists to spot exactly that kind of structure.

Three bugs were diagnosed and fixed here (see git history for prior
versions):

1. **Drag-to-select did nothing.** HoloViews does not auto-add a box-select
   tool to the toolbar just because a `BoundsX` stream is attached to an
   element — confirmed by inspecting the rendered Bokeh toolbar, which had
   no `BoxSelectTool` at all. Every drag was handled by the default active
   pan tool instead. Fix: explicitly request `"xbox_select"` in `tools` and
   make it the active drag tool.

2. **The trace vanished at some zoom levels.** An earlier version fixed the
   y-axis to the whole channel's padded min/max. A channel's local variance
   at typical zoom scales is a tiny fraction of its whole-recording range
   (measured on a real channel: median ~0.4% for 600-sample windows) —
   pinning the y-axis to the global extent squashed the signal to a
   sub-pixel sliver almost everywhere. Fix: compute an explicit `ylim` from
   each frame's own slice, with `framewise=True` so it actually takes effect
   every frame instead of only the first.

3. **The plot went blank at high zoom (not just blurry).** An intermediate
   version rasterized the slice through `holoviews.operation.datashader.
   rasterize` above a sample-count threshold and returned a raw `hv.Curve`
   below it. Two problems, one merely cosmetic and one fatal:
   (a) `rasterize` draws onto a *fixed*-resolution pixel grid regardless of
   the pane's actual (often wider, `sizing_mode="stretch_width"`) on-screen
   width, so the browser stretches/interpolates it — visibly smeared no
   matter how far you zoom in; and (b) far worse, `hv.DynamicMap` requires
   *every* frame its callback returns to be the same element type — once
   the callback had returned both a `Curve` and an `Image` across different
   zoom levels, HoloViews raised `AssertionError: DynamicMap must only
   contain one type of object, not both Curve and Image` on the next frame
   that switched type. That exception is swallowed by Panel's callback
   error handling (only a `WARNING` in the server log), so the plot pane
   simply stopped updating — "disappeared" — the next time a zoom crossed
   the threshold in either direction. Confirmed by driving the `RangeX`
   stream directly and watching the exact same `AssertionError` fire.
   Fix: never return anything but `Curve`. Above `MAX_RENDER_POINTS`, decimate
   the slice in Python (see `_minmax_decimate`) instead of handing it to
   datashader — still a vector line, so still pixel-crisp, and it fixes (a)
   as a side effect since there's no raster grid at all anymore.

4. **Drag-select worked in isolated testing but not in the live app.**
   `app.py`'s `_refresh_view()` used to reassign `plot_pane.object` to a
   *brand-new* `Overlay` on every routine update (a filter change, a
   show/hide toggle, even the box-select handler's own follow-up refresh).
   Confirmed with a real `bokeh.document.Document` + `pane.get_root(doc)`:
   the underlying Bokeh `Plot` model's `id` changes on every single one of
   those reassignments, even though the *Python* object graph (`self._dmap`)
   didn't change — i.e. Panel was tearing down and rebuilding the whole
   plot, including its `BoxSelectTool`'s `selectiongeometry` event wiring,
   on essentially every interaction. A `hv.streams.BoundsX` fired
   programmatically via `.event()` still updates its Python subscriber
   fine (that's a pure Python call, no Bokeh model involved) — which is
   why simulating it that way looked correct while the live browser
   version silently stopped working. Fix: `app.py` now builds the
   annotation/reviewed/detection/pending overlays as their own
   `DynamicMap`s driven by a shared manual trigger stream, and assigns
   `plot_pane.object` exactly once per recording load. Routine updates call
   `.event()` on that trigger instead of reassigning `.object`, so Panel
   patches the existing Bokeh model's data in place rather than replacing
   it — the box-select plot, and its live event wiring, is now built once
   and never torn down.
"""

import numpy as np
import holoviews as hv
import param

from Working.config import (
    CURVE_FRAME_MIN_BORDER_RIGHT,
    DENSITY_RIBBON_BUCKETS,
    ENCODING_FRAME_MIN_BORDER_LEFT,
    ENCODING_FRAME_MIN_BORDER_RIGHT,
    ENCODING_LETTER_THRESHOLD,
    ENCODING_PAA_HEIGHT,
    ENCODING_QUANT_HEIGHT,
    ENCODING_SIGNAL_HEIGHT,
    ENCODING_STRIP_HEIGHT,
    OVERLAY_DENSITY_THRESHOLD,
    PLOT_LABEL_FONT_SIZE,
    PLOT_TICK_FONT_SIZE,
    PLOT_TITLE_FONT_SIZE,
    REVIEWED_COVERAGE_BUCKETS,
    REVIEWED_FULL_COVERAGE_THRESHOLD,
    RIBBON_ALPHA,
    RIBBON_FRAME_MIN_BORDER_LEFT,
    RIBBON_FRAME_MIN_BORDER_RIGHT,
    RIBBON_LANE_BACKGROUND_ALPHA,
    RIBBON_LANE_BACKGROUND_COLOR,
    RIBBON_PANE_HEIGHT,
    WM_COVERAGE_RIBBON_BUCKETS,
)
from Working.database.queries import merge_intervals

hv.extension("bokeh")

# Part 7: one fontsize dict applied to every plot this module builds (the
# main curve, the cross-channel peek, and all four encoding panels) via
# Bokeh's `fontsize=` opts dict, so the whole app reads at a consistent
# size rather than newer panels looking like a different application.
PLOT_FONTSIZE = {
    "title": PLOT_TITLE_FONT_SIZE, "labels": PLOT_LABEL_FONT_SIZE,
    "xticks": PLOT_TICK_FONT_SIZE, "yticks": PLOT_TICK_FONT_SIZE,
}

VERDICT_COLORS = {
    "interesting": "#2ca02c",
    "not_interesting": "#7f7f7f",
    "artifact": "#d62728",
    "unsure": "#9467bd",
}
REVIEWED_FULL_COLOR = "#1f77b4"     # solid, saturated -- "fully reviewed"
REVIEWED_PARTIAL_COLOR = "#f0ad4e"  # amber -- deliberately NOT a blend of the full colour,
                                     # so partial can never read as "a lighter version of full"
REVIEWED_GAP_COLOR = "#d9d9d9"      # neutral grey "track", always drawn -- absence is the payload
DETECTION_COLOR = "#ff7f0e"  # distinct from every verdict colour above
CURVE_COLOR = "#1f4e8c"

# Above this many samples in the visible slice, min/max-decimate before
# building the Curve — see module docstring, bug 3. Set generously (Bokeh
# renders a 40k-point Line comfortably) so ordinary zoom levels show every
# real sample; only very wide zoom-outs (whole-channel = millions of
# samples) actually get reduced. A tighter cap here visibly "facets" a
# slow, naturally smooth signal into straight segments even though the
# min/max choice at each bucket keeps genuine spikes intact — confirmed by
# comparing total-variation of raw vs. decimated data at the old cap
# (8,000): ~84% retained, but connecting only 2 points per ~6-sample
# bucket with a straight line still looks visibly kinked next to a smooth
# curve, which read as "lost detail".
MAX_RENDER_POINTS = 40000


def load_channel_mmap(npy_path):
    """Memory-map a materialized channel .npy — pages in lazily on slicing."""
    return np.load(npy_path, mmap_mode="r")


PEEK_CURVE_COLOR = "#d62728"  # distinct from the main trace (CURVE_COLOR, blue)


def _decimated_curve(x_slice, t_slice, max_points, color, height, xlabel="time (s)"):
    """The shared decimate-then-build-a-Curve step behind every simple
    trace in this app (the cross-channel peek, and the "staged span, not
    yet processed" preview in `UI/run_panel.py`'s `_refresh_preview` —
    Part 6 3b, Part 7) — ONE renderer, never reimplemented per caller (see
    this module's docstring, bug 3, and the encoding view's own module
    note on reuse).

    `axiswise=True` (Part 7 bug, found during live-screenshot
    verification): every caller of this function shares the "amplitude"
    vdim name with `build_encoding_panels`' panels, which live in a
    SEPARATE `pn.pane.HoloViews` — confirmed directly (via the live
    browser's own Bokeh model state, not just suspected) that without
    this, HoloViews' default cross-plot axis-linking gave this curve's
    figure and the encoding panels' figures the literal SAME `Range1d`
    Python/JS object, keyed purely by the shared "amplitude" name — not
    scoped to one `hv.Layout`, but apparently document-wide. Since this
    curve never recomputes when preprocessing changes (it always shows
    the raw, un-preprocessed span — see its "not yet processed" title),
    its own wide raw-scale range kept winning the shared object back from
    the encoding panels' correctly-recomputed, much narrower one, so the
    preprocessed encoding panels rendered as a flat line pinned near zero
    against an axis still sized for the raw signal. `axiswise=True` is
    the documented way to opt an element out of that linking.
    """
    x_plot, t_plot = _minmax_decimate(np.asarray(x_slice), np.asarray(t_slice), max_points)
    curve = hv.Curve((t_plot, x_plot), "time", "amplitude")
    return curve.opts(
        color=color, line_width=1, height=height, responsive=True,
        framewise=True, axiswise=True, xlabel=xlabel, ylabel="amplitude", fontsize=PLOT_FONTSIZE,
    )


def build_peek_curve(npy_path, fs, x_range_samples, time_unit="s",
                      max_points=MAX_RENDER_POINTS, height=150):
    """Part E4: a small, secondary curve for the SAME sample range on a
    DIFFERENT channel — "cross-channel peek". Deliberately simple (no
    ribbons/overlays, just the decimated trace) since its only job is
    "does this artifact-looking thing also appear on another channel at
    the same moment" — equipment faults tend to, real biological activity
    tends not to. `x_range_samples` is supplied by the caller (see
    `UI/app.py`'s `_rebuild_cross_channel_peek`, which drives this off the
    MAIN plot's own `RangeX` stream, so the two stay linked/synced)."""
    data = load_channel_mmap(npy_path)
    unit_scale = 3600.0 if time_unit == "h" else 1.0
    xlabel = "time (h)" if time_unit == "h" else "time (s)"
    lo, hi = x_range_samples
    lo = max(0, lo)
    hi = min(len(data), hi)
    if hi <= lo:
        hi = min(len(data), lo + 1)
    x_slice = np.asarray(data[lo:hi])
    t_slice = np.arange(lo, hi) / fs / unit_scale
    return _decimated_curve(x_slice, t_slice, max_points, PEEK_CURVE_COLOR, height, xlabel=xlabel)


def _minmax_decimate(x_slice, t_slice, max_points):
    """Reduce a slice to roughly `max_points` samples while preserving its
    peaks and troughs, using bucketed min/max (not simple striding, which
    would alias away exactly the spikes this app exists to find).

    Each bucket contributes its min and max value, in that order if the min
    occurs first in the bucket, else max-then-min — so the result traces
    the same up/down envelope a human would see in the full-resolution
    data, just with the flat-ish stretches between extremes omitted.
    """
    n = len(x_slice)
    if n <= max_points:
        return x_slice, t_slice

    n_buckets = max(1, max_points // 2)
    edges = np.unique(np.linspace(0, n, n_buckets + 1).astype(np.int64))
    starts = edges[:-1]

    xs_out = np.empty(2 * len(starts), dtype=x_slice.dtype)
    ts_out = np.empty(2 * len(starts), dtype=t_slice.dtype)
    ends = np.append(starts[1:], n)
    for i, (lo, hi) in enumerate(zip(starts, ends)):
        seg = x_slice[lo:hi]
        i_min = lo + int(np.argmin(seg))
        i_max = lo + int(np.argmax(seg))
        if i_min <= i_max:
            xs_out[2 * i], xs_out[2 * i + 1] = x_slice[i_min], x_slice[i_max]
            ts_out[2 * i], ts_out[2 * i + 1] = t_slice[i_min], t_slice[i_max]
        else:
            xs_out[2 * i], xs_out[2 * i + 1] = x_slice[i_max], x_slice[i_min]
            ts_out[2 * i], ts_out[2 * i + 1] = t_slice[i_max], t_slice[i_min]
    return xs_out, ts_out


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


def x_range_to_sample_bounds(x0, x1, full_extent, fs, unit_scale, n_samples):
    """The exact sample-index boundary computation `build_channel_dmap`'s
    per-frame callback uses to decide which slice of the channel to page
    in -- extracted so anything else that needs "the samples the curve is
    CURRENTLY actually rendering from" (the annotation/reviewed ribbons'
    bucketing domain, the ribbons' own y-range, the cross-channel peek)
    computes the identical bounds, not an independently-rounded
    approximation that drifts from what's really on screen as the zoom
    narrows. `floor`/`ceil(...)+1` (not `round`) matches the curve's own
    "always include the edge sample" behaviour.
    """
    x0 = max(x0, full_extent[0])
    x1 = min(x1, full_extent[1])
    if x1 <= x0:
        x0, x1 = full_extent
    i0 = max(0, int(np.floor(x0 * unit_scale * fs)))
    i1 = min(n_samples, int(np.ceil(x1 * unit_scale * fs)) + 1)
    if i1 <= i0:
        i1 = min(n_samples, i0 + 1)
    return i0, i1


def compute_display_y_range(x_slice, y_extent, y_autoscale=True, y_pan_fraction=0.0,
                             dc_offset=False, detrend=False):
    """The exact per-frame y-axis computation `build_channel_dmap`'s
    callback uses (transform -> autoscale-or-fixed-extent -> pan shift) --
    extracted so the ribbons can compute the SAME y-range the curve is
    actually plotted against, instead of a second, independent
    reimplementation that ignores whichever of these is currently active
    and silently drifts away from the visible axis (a real bug, 2026-08:
    the ribbons floated to mid-plot once zoomed in, because their own
    y-range never accounted for y_autoscale being off, a transform being
    on, or a vertical pan).

    `x_slice` must be the RAW (untransformed) slice -- transforms are
    applied here, in the same order `build_channel_dmap` applies them, so
    a caller never has to duplicate that order itself.
    """
    x_slice = np.asarray(x_slice, dtype=np.float64)
    if len(x_slice) == 0:
        return y_extent
    if detrend and len(x_slice) > 1:
        idx = np.arange(len(x_slice))
        coeffs = np.polyfit(idx, x_slice, 1)
        x_slice = x_slice - np.polyval(coeffs, idx)
    elif dc_offset:
        x_slice = x_slice - x_slice.mean()

    if y_autoscale:
        local_lo, local_hi = float(x_slice.min()), float(x_slice.max())
        lpad = (local_hi - local_lo) * 0.1 or 1e-9
        local_y_range = (local_lo - lpad, local_hi + lpad)
    else:
        local_y_range = y_extent

    if y_pan_fraction:
        span = local_y_range[1] - local_y_range[0]
        shift = span * y_pan_fraction
        local_y_range = (local_y_range[0] + shift, local_y_range[1] + shift)
    return local_y_range


def build_channel_dmap(npy_path, fs, n_samples, height=350, max_points=MAX_RENDER_POINTS,
                        active_tools=("xbox_select", "xwheel_zoom"), initial_x_range=None,
                        time_unit="s", y_pan_fraction=0.0,
                        dc_offset=False, detrend=False, y_autoscale=True):
    """Build the zoom-driven curve for one channel.

    `dc_offset`, `detrend`, `y_autoscale` are Part E3's VIEW TRANSFORMS —
    display only, computed fresh per-frame from the already-loaded slice,
    never touching `data`/the underlying .npy or anything written to the
    database (annotations/reviewed-spans only ever store sample INDICES —
    time positions — never amplitude values, so there is no path from
    these transforms to stored data regardless). `dc_offset` subtracts the
    current slice's own mean; `detrend` additionally subtracts a
    least-squares linear fit; `y_autoscale` (on by default, matching
    existing behaviour) auto-ranges the y-axis to the current slice —
    turning it off pins the axis to the whole channel's fixed extent
    instead, for comparing a zoomed-in view against the full-channel scale.

    `y_pan_fraction` shifts the per-frame auto-computed local y-range by
    that fraction of its own span (e.g. 0.3 -> shift up by 30% of the
    current vertical span) — a simple, reliable "vertical pan" (Part C3)
    that doesn't depend on a Bokeh y-pan tool actually working the way a
    given Bokeh/browser version implements it (unverifiable headlessly;
    this app-level control is deterministic and testable). Baked in at
    construction time like `active_tools`/`time_unit`, so changing it goes
    through `UI/app.py`'s `_rebuild_plot`, not a live-updating stream.

    `initial_x_range` seeds the view — pass the caller's *current* zoom
    range when rebuilding the plot for a reason unrelated to navigation
    (e.g. re-arming a Bokeh tool, which requires a fresh `DynamicMap`; see
    `UI/app.py`'s `_rebuild_plot`), so that rebuild doesn't also reset the
    zoom back to the whole channel. Defaults to the whole channel, as
    before, when omitted (e.g. loading a different recording/channel,
    where carrying over the old zoom wouldn't make sense anyway).

    `time_unit` is `"s"` (seconds, default) or `"h"` (hours) — a pure
    display transform. Every x-axis value this function hands back or
    consumes (`full_extent`, `range_stream.x_range`, the curve's own
    coordinates, `initial_x_range`) is expressed in this unit; conversion
    to seconds/samples happens only internally, using `fs`. A caller that
    needs seconds for something sample-index-related (annotation
    start/end indices, `scale_viewed`) must convert explicitly — see
    `UI/app.py`'s `ViewerApp._unit_scale`.

    Returns
    -------
    (dmap, range_stream, full_extent, y_extent)
        `range_stream.x_range` is the live (x0, x1) in `time_unit` units —
        read it wherever "the zoom span active right now" is needed
        (annotation scale_viewed, "mark viewport reviewed"), converting to
        seconds first if `time_unit == "h"`. `y_extent` is the padded
        (min, max) of the whole channel — NOT used for the curve's own axis
        (see module docstring for why a fixed axis was the bug), only to
        size annotation/reviewed rectangles so they safely exceed whatever
        the current per-frame y-axis is and visually fill the plot.
    """
    unit_scale = 3600.0 if time_unit == "h" else 1.0  # seconds per display-unit
    xlabel = "time (h)" if time_unit == "h" else "time (s)"

    data = load_channel_mmap(npy_path)
    full_extent = (0.0, (n_samples - 1) / fs / unit_scale)
    y_min, y_max = float(np.min(data)), float(np.max(data))
    gpad = (y_max - y_min) * 0.05 or 1.0
    y_extent = (y_min - gpad, y_max + gpad)

    def _callback(x_range):
        if x_range is None or x_range[0] is None or x_range[1] is None:
            x0, x1 = full_extent
        else:
            x0, x1 = x_range

        # x0/x1 arrive in display units (whatever the figure's x-axis
        # currently is) — convert to seconds, then samples, only here.
        # Shared with `UI/app.py` (ribbons, cross-channel peek) via
        # `x_range_to_sample_bounds` so everything that asks "what's
        # currently visible" agrees on the exact same sample range.
        i0, i1 = x_range_to_sample_bounds(x0, x1, full_extent, fs, unit_scale, n_samples)

        x_slice_raw = np.asarray(data[i0:i1]).astype(np.float64, copy=True)  # pages in only this span
        t_slice = np.arange(i0, i1) / fs / unit_scale  # back to display units

        # Part E3 view transforms — display only, applied to this LOCAL
        # in-memory slice after paging it in, never to `data` itself.
        if detrend and len(x_slice_raw) > 1:
            idx = np.arange(len(x_slice_raw))
            coeffs = np.polyfit(idx, x_slice_raw, 1)
            x_slice = x_slice_raw - np.polyval(coeffs, idx)
        elif dc_offset and len(x_slice_raw) > 0:
            x_slice = x_slice_raw - x_slice_raw.mean()
        else:
            x_slice = x_slice_raw

        # Per-frame y-bounds -- shared with the ribbons via
        # `compute_display_y_range` (same transform/autoscale/pan
        # handling), so they can never independently drift from the axis
        # this curve is actually plotted against.
        local_y_range = compute_display_y_range(
            x_slice_raw, y_extent, y_autoscale=y_autoscale,
            y_pan_fraction=y_pan_fraction, dc_offset=dc_offset, detrend=detrend,
        )

        x_plot, t_plot = _minmax_decimate(x_slice, t_slice, max_points)
        curve = hv.Curve((t_plot, x_plot), "time", "amplitude")

        # Always a Curve, never a datashader Image — a DynamicMap crashes
        # (silently, from Panel's perspective) if its callback ever returns
        # two different element types across frames. See module docstring,
        # bug 3.
        return curve.opts(
            color=CURVE_COLOR, line_width=1, height=height, responsive=True,
            framewise=True, xlabel=xlabel, ylabel="amplitude", fontsize=PLOT_FONTSIZE,
            xlim=(float(t_slice[0]), float(t_slice[-1])), ylim=local_y_range,
            # Part A3 (2026-08): fixed, not auto -- the ribbon panes above
            # and below this curve have no y-axis of their own and must
            # reserve the IDENTICAL left width so their frames start at the
            # same pixel x-position as this one's. An auto-sized
            # min_border_left would otherwise vary with y-tick label width
            # (e.g. "-0.0987" vs "-140000") and visibly shift per zoom
            # level, which a fixed value here rules out entirely.
            #
            # NOT set via a `hooks=` opt here: a hook attached to one
            # element of what becomes a multi-DynamicMap Overlay (this
            # curve is combined with the selected/detection/pending
            # overlays in `UI/app.py`'s `_rebuild_plot`) is silently
            # dropped by HoloViews' `OverlayPlot` when it builds the
            # SHARED figure for all of them -- confirmed directly: a hook
            # on this element alone applies fine, but as soon as it's
            # combined with even one more `hv.DynamicMap` the figure's
            # `min_border_left/right` reverts to Bokeh's plain default.
            # `style_main_plot_frame` below must be called on the FINAL
            # combined overlay instead, where a hook reliably applies.
        )

    range_stream = hv.streams.RangeX(x_range=initial_x_range or full_extent)
    dmap = hv.DynamicMap(_callback, streams=[range_stream]).opts(
        # "xbox_select" must be requested explicitly — HoloViews does not
        # auto-add a select tool merely because a BoundsX stream exists, so
        # without this a drag can only ever pan (this was bug 1a).
        default_tools=[],
        tools=["xpan", "xwheel_zoom", "xbox_select", "save", "reset"],
        active_tools=list(active_tools),
    )
    return dmap, range_stream, full_extent, y_extent


def style_main_plot_frame(overlay):
    """Applies the curve's fixed frame borders (Part A3, 2026-08) to the
    FINAL combined main-plot overlay (curve * selected * detection *
    pending, built in `UI/app.py`'s `_rebuild_plot`) -- NOT to the curve
    element alone. A `hooks=` opt on one constituent of a multi-DynamicMap
    Overlay is silently dropped by HoloViews when it builds the shared
    Bokeh figure for the whole group; only a hook on the OVERLAY itself
    reliably reaches that figure. Confirmed directly: `curve.opts(hooks=
    [...])` alone survives being combined with a single static element,
    but not with even one more `hv.DynamicMap` -- exactly the shape of
    the real main plot, which combines four."""
    return overlay.opts(hooks=[_set_frame_borders(RIBBON_FRAME_MIN_BORDER_LEFT, CURVE_FRAME_MIN_BORDER_RIGHT)])


def _empty_rectangles():
    return hv.Rectangles([]).opts(alpha=0, apply_ranges=False)


def _set_frame_borders(min_left, min_right, min_top=2, min_bottom=2):
    """`min_border_*` aren't recognized `.opts()` keywords (HoloViews
    raises `ValueError: Unexpected option` if passed that way) -- a
    `hooks` callback, which HoloViews calls with the live Bokeh figure
    after construction, is the documented escape hatch for Bokeh Figure
    properties with no direct opts equivalent. Used for both the curve
    and the ribbon panes so a plain closure captures the two numbers
    without six near-identical one-off hook functions (Part A3, 2026-08)."""
    def _hook(plot, element):
        plot.state.min_border_left = min_left
        plot.state.min_border_right = min_right
        plot.state.min_border_top = min_top
        plot.state.min_border_bottom = min_bottom
    return _hook


def _set_x_range(x0, x1):
    """Force the Bokeh figure's x_range to exactly (x0, x1) -- NOT
    redundant with the `xlim`/`framewise=True` opts on the same element
    (Part A, 2026-08 bug): confirmed directly, with a minimal
    reproduction outside this codebase, that `xlim`+`framewise=True`
    alone is only honoured on a DynamicMap's FIRST rendered frame. On
    every subsequent stream-triggered refresh, HoloViews' Bokeh backend
    left the figure's x_range exactly as it was at construction, even
    though the newly-returned element's `xlim` opt held the correct
    value the whole time (checked directly on the raw element, bypassing
    Bokeh entirely) and even with `apply_ranges` set either way. This is
    what actually caused the ribbons to render bucket data for the
    correct (narrow) viewport while the AXIS stayed pinned to the
    full-channel extent from initial page load forever after -- a 600s
    annotation rendered at its true width, just against an axis ~4300x
    too wide, so it occupied a sliver instead of ~26% of the pane.
    A `hooks` callback bypasses HoloViews' range-update pipeline
    entirely and sets the Bokeh model property directly, which DOES take
    effect on every refresh. The main curve never hit this because
    `hv.streams.RangeX` has special, built-in two-way sync with the
    FIGURE IT WAS ORIGINALLY SOURCED FROM (that IS its whole purpose);
    the ribbon panes use that same stream only as an ordinary listener on
    a DIFFERENT figure, which gets no such special treatment.
    """
    def _hook(plot, element):
        plot.state.x_range.start = x0
        plot.state.x_range.end = x1
    return _hook


def _set_y_range(y0, y1):
    """The same bypass `_set_x_range` uses, for the y-axis (Part 7, Part 2
    bug found during live-screenshot verification): switching the encoding
    section's preprocessing mode produced a fresh `_panel_paa`/`_panel_quant`
    frame whose `ylim` opt held the correct, newly-recomputed (tiny,
    preprocessed-scale) range — visible directly in that frame's own title
    text, which embeds the same `yr` value — while the RENDERED Bokeh
    y_range stayed pinned to the previous (raw-scale) value, so the curve
    drew as a flat line pinned near the old axis's zero. `ylim`+
    `framewise=True` alone is, exactly like the x-range case documented at
    `_set_x_range`, not reliably honoured on every refresh path — only a
    direct hook that sets the Bokeh model's `y_range.start`/`.end` bypasses
    that pipeline and takes effect every time.
    """
    def _hook(plot, element):
        plot.state.y_range.start = y0
        plot.state.y_range.end = y1
    return _hook


def _lane_background(x0, x1):
    """Part B1 (2026-08): a flat, colour-neutral tint spanning the FULL
    ribbon pane (the whole visible width, y in [0, 1]) drawn UNDERNEATH
    every bucket/individual rectangle -- without it, an empty stretch (no
    data in view) renders as blank space indistinguishable from a broken
    pane. Always included regardless of whether there's any data, so its
    presence never varies the DynamicMap's per-frame element composition."""
    return hv.Rectangles([(x0, 0.0, x1, 1.0)]).opts(
        color=RIBBON_LANE_BACKGROUND_COLOR, alpha=RIBBON_LANE_BACKGROUND_ALPHA,
        line_width=0, apply_ranges=False, show_legend=False,
    )


def _style_ribbon_pane(overlay, x0, x1):
    """Every ribbon pane is a SEPARATE, thin Bokeh figure (Part A,
    2026-08 restructure -- see this module's top-level docstring) linked
    to the main curve by x-range only, never by sharing an axis or a
    frame. Applied identically to both ribbon builders below so their
    frames stay pixel-aligned with each other and with the curve:
    - fixed fake y-range (0, 1): completely decoupled from the curve's
      own y-axis, which is the whole point of the restructure.
    - `xlim=(x0, x1)` + `framewise=True`: necessary but NOT sufficient
      (see the `_set_x_range` hook below) -- kept because they're still
      correct/harmless and document intent, but the actual enforcement
      is the hook.
    - `hooks=[_set_x_range(...)]`: THE actual fix for a real bug
      (2026-08): `xlim`+`framewise=True` alone is only honoured by
      HoloViews' Bokeh backend on a DynamicMap's FIRST rendered frame.
      On every subsequent stream-triggered refresh the figure's x_range
      stayed exactly as it was at construction (pinned to the
      full-channel extent from initial page load) even though the
      newly-built element's `xlim` opt held the correct narrower value
      the whole time -- confirmed both on the real app and with a
      minimal reproduction outside it. The bucket DATA was always
      correct for the current viewport; only the AXIS never moved, so a
      600s annotation rendered at its true width against an axis
      ~4300x too wide and occupied a sliver instead of ~26% of the pane.
      `hv.streams.RangeX` has special two-way sync with the figure it
      was ORIGINALLY SOURCED FROM (that's its whole purpose) -- the main
      curve never hit this because it IS that figure. The ribbon panes
      only LISTEN to that same stream object on a DIFFERENT figure, which
      gets no such special treatment; a `hooks` callback bypasses
      HoloViews' range-update pipeline entirely and sets the Bokeh model
      property directly, which does take effect on every refresh.
    - `min_border_left`/`min_border_right` matching the curve's own
      (Part A3) -- without this, the curve's y-tick-label width would
      make its frame start at a different pixel x-position than a
      no-y-axis ribbon pane's frame, visibly offsetting every bucket
      from the region of the trace it annotates.
    - no axes, no toolbar, no title: a thin data strip, not a second plot.
    """
    return overlay.opts(
        height=RIBBON_PANE_HEIGHT, responsive=True,
        xlim=(x0, x1), ylim=(0.0, 1.0), framewise=True,
        xaxis=None, yaxis=None, toolbar=None, show_title=False,
        hooks=[
            _set_frame_borders(RIBBON_FRAME_MIN_BORDER_LEFT, RIBBON_FRAME_MIN_BORDER_RIGHT),
            _set_x_range(x0, x1),
        ],
    )


def build_annotation_ribbon(annotation_rows, fs, x_range_samples,
                             density_threshold=OVERLAY_DENSITY_THRESHOLD,
                             n_buckets=DENSITY_RIBBON_BUCKETS):
    """The annotation-density pane's content: individual verdict-coloured
    rectangles, or — above `density_threshold` rows *within the current
    viewport* — a compact bucketed density ribbon instead (Part 4b, made
    viewport-reactive in Part B, moved into its own dedicated pane in
    Part A). Some channels carry ~10,000 annotations; drawing each as its
    own span makes the pane unreadable, and gets worse as counts grow.

    `x_range_samples = (lo, hi)` is the CURRENT visible span in samples.
    Both the threshold decision and the ribbon's own bucketing are relative
    to THIS range, not the whole channel or the full annotation set's own
    extent — recomputed on every pan/zoom (this function backs a
    `hv.DynamicMap` driven by both the app's refresh trigger and its
    `RangeX` stream; see `UI/app.py`'s `_rebuild_plot`). Bucketing over a
    fixed whole-channel range made the ribbon either invisible or one
    undifferentiated block once zoomed in far enough to matter.

    Both branches return an `hv.Overlay` of `hv.Rectangles` — never
    anything else. This is a hard requirement, not a style choice: this
    function backs a `hv.DynamicMap`, and HoloViews raises
    `AssertionError: DynamicMap must only contain one type of object` the
    moment a callback returns two different element types across frames —
    silently swallowed by Panel, leaving the plot blank (see this module's
    docstring, bug 3). Crossing `density_threshold` must not risk that.
    """
    lo, hi = x_range_samples
    x0, x1 = lo / fs, (max(hi, lo + 1) - 1) / fs  # match the curve's own t_slice[-1] convention exactly  # `fs` here is already the EFFECTIVE fs (fs * unit_scale)
    rows_in_view = [r for r in annotation_rows if r["start_idx"] < hi and r["end_idx"] > lo]

    if len(rows_in_view) > density_threshold:
        return _build_annotation_density_ribbon(rows_in_view, fs, lo, hi, n_buckets)

    from Working.database.queries import SOURCE_IMPORTED_10MIN

    imported_rows = [r for r in rows_in_view if r["source"] == SOURCE_IMPORTED_10MIN]
    manual_rows = [r for r in rows_in_view if r["source"] != SOURCE_IMPORTED_10MIN]

    def _rect_data(rows):
        return [(r["start_idx"] / fs, 0.0, r["end_idx"] / fs, 1.0, r["verdict"], r["id"])
                for r in rows]

    # show_legend=False: the app already renders a manual colour-key legend
    # (see app.py) — an auto-generated Bokeh legend here is redundant, and
    # since two separate Rectangles elements both map the same 'verdict'
    # field with different underlying data sources, Bokeh's own legend
    # logic complains (NON_MATCHING_DATA_SOURCES_ON_LEGEND_ITEM_RENDERERS).
    # Part B1: the lane background goes in FIRST (drawn underneath) and
    # unconditionally, so the pane reads as a distinct strip even when
    # nothing is currently drawn on top of it.
    elems = [_lane_background(x0, x1)]
    if imported_rows:
        elems.append(
            hv.Rectangles(_rect_data(imported_rows), vdims=["verdict", "annotation_id"]).opts(
                color="verdict", cmap=VERDICT_COLORS, alpha=0.35, line_width=0,
                apply_ranges=False, show_legend=False, tools=["hover"],
            )
        )
    if manual_rows:
        elems.append(
            hv.Rectangles(_rect_data(manual_rows), vdims=["verdict", "annotation_id"]).opts(
                color="verdict", cmap=VERDICT_COLORS, alpha=0.7,
                line_color="black", line_width=1, apply_ranges=False, show_legend=False,
                tools=["hover"],
            )
        )
    return _style_ribbon_pane(hv.Overlay(elems), x0, x1)


def _build_annotation_density_ribbon(annotation_rows, fs, lo, hi, n_buckets=DENSITY_RIBBON_BUCKETS):
    """The annotation-density pane's bucketed content, showing where
    annotations concentrate WITHIN THE CURRENT VIEWPORT `[lo, hi)`. One
    `hv.Rectangles` element per verdict (matching the individual-span
    palette), one rectangle per occupied time-bucket, with per-bucket
    alpha driven by that bucket's share of its verdict's busiest bucket —
    confirmed HoloViews supports a vdim-driven `alpha` the same way
    `color="verdict"` already works (`.opts(alpha="alpha")` maps the CDS
    column through to Bokeh's `fill_alpha`, verified against a rendered
    Bokeh glyph).
    """
    x0, x1 = lo / fs, (max(hi, lo + 1) - 1) / fs  # match the curve's own t_slice[-1] convention exactly
    span = hi - lo
    # Part B1: lane background always present, even with zero annotations
    # in view, so the pane's extent never depends on there being any data.
    elems = [_lane_background(x0, x1)]
    if not annotation_rows or span <= 0:
        return _style_ribbon_pane(hv.Overlay(elems), x0, x1)
    bucket_width = span / n_buckets

    counts_by_verdict = {v: [0] * n_buckets for v in VERDICT_COLORS}
    for r in annotation_rows:
        mid = (max(r["start_idx"], lo) + min(r["end_idx"], hi)) / 2.0
        idx = min(n_buckets - 1, max(0, int((mid - lo) / bucket_width)))
        counts_by_verdict.setdefault(r["verdict"], [0] * n_buckets)[idx] += 1

    for verdict, color in VERDICT_COLORS.items():
        bucket_counts = counts_by_verdict.get(verdict)
        if not bucket_counts:
            continue
        max_count = max(bucket_counts)
        if max_count == 0:
            continue
        data = []
        for i, c in enumerate(bucket_counts):
            if c == 0:
                continue
            bx0 = (lo + i * bucket_width) / fs
            bx1 = (lo + (i + 1) * bucket_width) / fs
            # Scaled within [0.5, 1.0] of the base alpha, so even a
            # single-count bucket stays visible without every bucket
            # looking uniformly saturated regardless of count.
            alpha = RIBBON_ALPHA * (0.5 + 0.5 * (c / max_count))
            # Part B2: `verdict`/`count` carried as vdims purely so the
            # hover tooltip can report "what's in this bucket" without
            # zooming in — at coarse zoom the ribbon IS the only readable
            # summary.
            data.append((bx0, 0.0, bx1, 1.0, alpha, verdict, c))
        if data:
            elems.append(
                hv.Rectangles(data, vdims=["alpha", "verdict", "count"]).opts(
                    color=color, alpha="alpha", line_width=0,
                    apply_ranges=False, show_legend=False, tools=["hover"],
                    hover_tooltips=[("verdict", "@verdict"), ("annotations", "@count")],
                )
            )
    return _style_ribbon_pane(hv.Overlay(elems), x0, x1)


SELECTED_ANNOTATION_COLOR = "#ffd700"  # gold — distinct from every verdict/detection/pending colour


def build_selected_overlay(selected_rows, fs, y_extent):
    """Heavy gold outline + brighter fill over whichever annotations are
    currently selected — deliberately drawn as its OWN overlay layer, on
    top of (not instead of) the main curve, and independent of the
    current filter/show-annotations state: a selection must stay visible
    (and stay selected) even if the selected annotation is filtered out
    of the table/ribbon pane, per the brief. `selected_rows` should come
    from `queries.get_annotations_by_ids`, not from a filtered list, for
    exactly that reason.

    Unlike the density/reviewed ribbons (Part A, 2026-08), this STAYS an
    overlay on the main plot rather than moving to its own pane — it
    marks a specific span ON the trace you're looking at, not a
    separate summary, so it belongs on the same axes. `apply_ranges=False`
    keeps it (like every other main-plot overlay) out of the curve's own
    y-autoscale computation; confirmed by direct comparison of the
    rendered y-range with and without this layer present (Part A1 — see
    UI/README.md), which also refuted the hypothesized cause of the
    ribbon bug for every remaining main-plot overlay, not just this one.
    """
    y0, y1 = y_extent
    if not selected_rows:
        return hv.Overlay([_empty_rectangles()])
    data = [(r["start_idx"] / fs, y0, r["end_idx"] / fs, y1) for r in selected_rows]
    return hv.Overlay([
        hv.Rectangles(data).opts(
            color=SELECTED_ANNOTATION_COLOR, alpha=0.35,
            line_color=SELECTED_ANNOTATION_COLOR, line_width=3,
            apply_ranges=False, show_legend=False,
        )
    ])


def _bucket_coverage_fractions(merged_intervals, lo, hi, n_buckets):
    """Exact per-bucket coverage fraction from DISJOINT merged intervals.
    Because the intervals don't overlap each other (that's what "merged"
    means), summing each one's overlap with a bucket can't double-count —
    unlike summing overlaps against the raw, possibly-overlapping spans
    directly would, which would over-report coverage."""
    span = hi - lo
    if span <= 0 or n_buckets <= 0:
        return []
    bucket_width = span / n_buckets
    fractions = [0.0] * n_buckets
    for s, e in merged_intervals:
        s = max(s, lo)
        e = min(e, hi)
        if e <= s:
            continue
        i0 = max(0, min(n_buckets - 1, int((s - lo) / bucket_width)))
        i1 = max(0, min(n_buckets - 1, int((e - lo) / bucket_width)))
        for i in range(i0, i1 + 1):
            b0 = lo + i * bucket_width
            b1 = b0 + bucket_width
            overlap = min(e, b1) - max(s, b0)
            if overlap > 0:
                fractions[i] += overlap / bucket_width
    return [min(1.0, f) for f in fractions]


def build_reviewed_ribbon(reviewed_rows, fs, x_range_samples, n_buckets=REVIEWED_COVERAGE_BUCKETS):
    """The reviewed-coverage pane's content — a separate question from,
    and a separate pane from (Part A, 2026-08), the annotation density
    ribbon: that one shows where annotations concentrate, this one shows
    where you have NOT looked. Gaps are the payload, not concentration.

    `x_range_samples = (lo, hi)` is the CURRENT visible span in samples —
    buckets span exactly this range (whatever it is: the whole channel at
    full zoom-out, or a narrow slice once zoomed in), recomputed on every
    pan/zoom (this function backs a `hv.DynamicMap` driven by both the
    app's refresh trigger and its `RangeX` stream; see `UI/app.py`'s
    `_rebuild_plot`). At full zoom-out this naturally covers the whole
    channel — an unreviewed stretch at either end is exactly the kind of
    gap this exists to surface — and at high zoom it gives fine-grained
    resolution within just what's on screen, rather than one
    undifferentiated whole-channel bucket that would otherwise dominate
    the view or vanish once zoomed in far enough.

    Per bucket, computes the TRUE fraction of that bucket's time covered
    by the union of reviewed spans (`Working.database.queries.
    merge_intervals` — the identical merge the "reviewed: X%" summary
    figure uses, so ribbon and summary can never silently disagree) and
    sorts into three FIXED, qualitatively distinct colours rather than a
    continuous alpha gradient: full (>= REVIEWED_FULL_COVERAGE_THRESHOLD),
    partial (0 < fraction < threshold), and gap (fraction == 0, rendered
    explicitly in grey, never left blank). A gradient would let a
    coarse-zoom bucket containing a few scattered ~600-sample reviewed
    islands, out of thousands of unreviewed samples, render as some vague
    middling shade easily mistaken for meaningful coverage — three fixed
    tiers, distinguished by HUE rather than opacity, can't drift that way,
    and the grey "track" makes "not reviewed" a positive, explicit
    statement rather than an absence a viewer could mistake for a
    rendering gap.

    Always returns `hv.Overlay` of `hv.Rectangles` — same hard
    type-consistency requirement as `build_annotation_ribbon`, see its
    docstring for why.
    """
    lo, hi = x_range_samples
    x0, x1 = lo / fs, (max(hi, lo + 1) - 1) / fs  # match the curve's own t_slice[-1] convention exactly
    span = hi - lo
    if span <= 0:
        return _style_ribbon_pane(hv.Overlay([_lane_background(x0, x1)]), x0, x1)

    merged = merge_intervals(
        (max(r["start_idx"], lo), min(r["end_idx"], hi))
        for r in reviewed_rows if r["start_idx"] < hi and r["end_idx"] > lo
    )
    fractions = _bucket_coverage_fractions(merged, lo, hi, n_buckets)
    bucket_width = span / n_buckets

    # Part B2: `fraction` (as an exact percentage) carried as a vdim so
    # hovering a bucket shows the true coverage number, not just which of
    # the three fixed tiers it fell into.
    gap_data, partial_data, full_data = [], [], []
    for i, frac in enumerate(fractions):
        bx0 = (lo + i * bucket_width) / fs
        bx1 = (lo + (i + 1) * bucket_width) / fs
        pct = round(frac * 100, 1)
        if frac <= 0.0:
            gap_data.append((bx0, 0.0, bx1, 1.0, pct))
        elif frac >= REVIEWED_FULL_COVERAGE_THRESHOLD:
            full_data.append((bx0, 0.0, bx1, 1.0, pct))
        else:
            partial_data.append((bx0, 0.0, bx1, 1.0, pct))

    hover_tooltips = [("reviewed", "@fraction%")]
    # Part B1: lane background first/underneath, always present.
    elems = [
        _lane_background(x0, x1),
        hv.Rectangles(gap_data, vdims=["fraction"]).opts(
            color=REVIEWED_GAP_COLOR, alpha=RIBBON_ALPHA, line_width=0,
            apply_ranges=False, show_legend=False, tools=["hover"],
            hover_tooltips=hover_tooltips,
        ),
    ]
    if partial_data:
        elems.append(
            hv.Rectangles(partial_data, vdims=["fraction"]).opts(
                color=REVIEWED_PARTIAL_COLOR, alpha=RIBBON_ALPHA, line_width=0,
                apply_ranges=False, show_legend=False, tools=["hover"],
                hover_tooltips=hover_tooltips,
            )
        )
    if full_data:
        elems.append(
            hv.Rectangles(full_data, vdims=["fraction"]).opts(
                color=REVIEWED_FULL_COLOR, alpha=RIBBON_ALPHA, line_width=0,
                apply_ranges=False, show_legend=False, tools=["hover"],
                hover_tooltips=hover_tooltips,
            )
        )
    return _style_ribbon_pane(hv.Overlay(elems), x0, x1)


def build_window_matrix_ribbon(coverage, fs, x_range_samples, n_buckets=WM_COVERAGE_RIBBON_BUCKETS):
    """One coverage-ribbon pane for ONE window-matrix ladder scale
    (WINDOW_MATRIX_UI_PROMPT.md §8.3, `UI.workspaces.analyse.window_matrix`) — the caller
    builds one of these per scale that has any coverage, stacked under the
    staged-span preview.

    `coverage` is one entry of `Working.database.window_matrix_store.
    coverage_by_completeness(...)`'s return value: `{"complete": [(start,
    end), ...], "partial": [...]}`, both already merged (via `merge_intervals`
    — the same function the reviewed-coverage ribbon and the "reviewed: X%"
    summary use) and already excluding stale artifacts by default. Either key
    may be absent.

    Bucketing reuses `_bucket_coverage_fractions` — the exact per-bucket
    fractional-overlap helper `build_reviewed_ribbon` factors out and uses —
    rather than a second implementation, so "what fraction of this bucket's
    time is covered" can't drift between the two ribbons. `complete` and
    `partial` intervals never overlap in practice (a given (window_min,
    step_frac, span) has one run), but are unioned defensively before the
    'any coverage' fraction is computed so an edge case can't double-count.

    Same three-tier colour treatment as `build_reviewed_ribbon`, reusing its
    exact colours rather than inventing new ones — WINDOW_MATRIX_UI_PROMPT.md
    §8.3 calls this out explicitly ("the same distinction the reviewed ribbon
    already draws, reused rather than re-invented"): a bucket dominated by a
    COMPLETE matrix (>= REVIEWED_FULL_COVERAGE_THRESHOLD) renders full;
    any other bucket touched by a matrix (complete or partial) renders
    partial; an untouched bucket shows only the lane background, unlike the
    reviewed ribbon there is no separate flat "gap" rectangle colour, since
    a gap here is not itself a reviewable event, just an absence.

    Always returns an `hv.Overlay` of `hv.Rectangles`, never empty even with
    zero coverage (the lane background alone) — same hard type-consistency
    requirement as every other ribbon builder in this module (see the module
    docstring's bug 3): a `DynamicMap` callback that sometimes returns a bare
    element and sometimes an `Overlay` blanks the pane with no visible error.
    """
    lo, hi = x_range_samples
    x0, x1 = lo / fs, (max(hi, lo + 1) - 1) / fs  # match the curve's own t_slice[-1] convention exactly
    span = hi - lo
    if span <= 0:
        return _style_ribbon_pane(hv.Overlay([_lane_background(x0, x1).opts(axiswise=True)]), x0, x1)

    complete_intervals = [
        (max(s, lo), min(e, hi)) for s, e in coverage.get("complete", []) if s < hi and e > lo
    ]
    partial_intervals = [
        (max(s, lo), min(e, hi)) for s, e in coverage.get("partial", []) if s < hi and e > lo
    ]

    # `axiswise=True` on THIS ribbon's leaf elements, not just the enclosing
    # Overlay (UI/README.md, "y-range linking is document-wide, not
    # Layout-scoped") — unlike `build_reviewed_ribbon` (one instance per
    # app), this builder is called once PER LADDER SCALE, so up to
    # len(WM_SCALE_LADDER_MIN) separate `hv.Rectangles`-based panes sharing
    # the same 'fraction' vdim coexist in the same Bokeh document at once —
    # exactly the multi-pane-same-vdim shape that caused two encoding panels
    # to silently share one Range1d there. Overlay-level axiswise alone was
    # confirmed NOT to protect its own constituents in that bug.
    elems = [_lane_background(x0, x1).opts(axiswise=True)]
    if not complete_intervals and not partial_intervals:
        return _style_ribbon_pane(hv.Overlay(elems), x0, x1)

    complete_fractions = _bucket_coverage_fractions(complete_intervals, lo, hi, n_buckets)
    any_merged = merge_intervals(complete_intervals + partial_intervals)
    any_fractions = _bucket_coverage_fractions(any_merged, lo, hi, n_buckets)

    bucket_width = span / n_buckets
    partial_data, full_data = [], []
    for i in range(n_buckets):
        frac_any = any_fractions[i] if any_fractions else 0.0
        if frac_any <= 0.0:
            continue
        frac_complete = complete_fractions[i] if complete_fractions else 0.0
        bx0 = (lo + i * bucket_width) / fs
        bx1 = (lo + (i + 1) * bucket_width) / fs
        pct = round(frac_any * 100, 1)
        if frac_complete >= REVIEWED_FULL_COVERAGE_THRESHOLD:
            full_data.append((bx0, 0.0, bx1, 1.0, pct))
        else:
            partial_data.append((bx0, 0.0, bx1, 1.0, pct))

    hover_tooltips = [("coverage", "@fraction%")]
    if partial_data:
        elems.append(
            hv.Rectangles(partial_data, vdims=["fraction"]).opts(
                color=REVIEWED_PARTIAL_COLOR, alpha=RIBBON_ALPHA, line_width=0,
                apply_ranges=False, show_legend=False, tools=["hover"],
                hover_tooltips=hover_tooltips, axiswise=True,
            )
        )
    if full_data:
        elems.append(
            hv.Rectangles(full_data, vdims=["fraction"]).opts(
                color=REVIEWED_FULL_COLOR, alpha=RIBBON_ALPHA, line_width=0,
                apply_ranges=False, show_legend=False, tools=["hover"],
                hover_tooltips=hover_tooltips, axiswise=True,
            )
        )
    return _style_ribbon_pane(hv.Overlay(elems), x0, x1)


def build_detection_overlay(detection_rows, fs, y_extent):
    """Algorithm-detected intervals — visually distinct from annotations
    (a single fixed colour, orange, with a dashed border) so it's obvious
    at a glance which regions came from your own judgement (the verdict-
    coloured, solid/no-border annotation rectangles) versus an algorithm's
    output, and whether the two agree. One vectorized `hv.Rectangles`
    element, same scaling reason as `build_annotation_ribbon`.
    """
    y0, y1 = y_extent
    if not detection_rows:
        return hv.Overlay([_empty_rectangles()])
    data = [(r["start_idx"] / fs, y0, r["end_idx"] / fs, y1) for r in detection_rows]
    return hv.Overlay([
        hv.Rectangles(data).opts(
            color=DETECTION_COLOR, alpha=0.3, line_color=DETECTION_COLOR,
            line_width=1.5, line_dash="dashed", apply_ranges=False, show_legend=False,
        )
    ])


PENDING_SELECTION_COLOR = "#e91e63"  # bright magenta — distinct from every other overlay colour


def build_pending_selection_overlay(bounds):
    """The currently selected-but-not-yet-saved span (drag-select or the
    manually-entered Start/End Time fields), if any. Deliberately the most
    visually prominent overlay — a bright, thick-bordered fill — since this
    is the one span the very next action (Save annotation) will act on."""
    if bounds is None or bounds[0] is None or bounds[1] is None:
        return hv.Overlay([hv.VSpan(0, 0).opts(alpha=0)])
    x0, x1 = bounds
    return hv.Overlay([hv.VSpan(x0, x1).opts(
        color=PENDING_SELECTION_COLOR, alpha=0.2,
        line_color=PENDING_SELECTION_COLOR, line_width=2, line_dash="dashed",
    )])


# ══════════════════════════════════════════════════════════════════════════
#  Motif browser (Matrix profile tab, MATRIX_PROFILE_UI_PROMPT.md §6)
# ══════════════════════════════════════════════════════════════════════════
#
# Two panes per motif group: (top) the full channel, reusing
# `build_channel_dmap` verbatim, with seed/neighbour occurrences overlaid;
# (bottom) all occurrences overlaid on a shared, z-normalised relative time
# axis. Same "always the same top-level element type" DynamicMap rule as
# everywhere else in this module — confirmed safe (via
# `build_annotation_ribbon`'s precedent) for the NUMBER of constituent
# elements inside that Overlay to vary between frames; only the top-level
# return type (always `hv.Overlay`) must stay fixed.

SEED_MOTIF_COLOR = "gold"
MOTIF_MEAN_COLOR = "#000000"
# Categorical, rank-cycled -- same 10-colour set `plot_matrix_slideshow`
# (the static-matplotlib precedent this view ports) already uses, kept
# identical so a motif looks the same whether viewed there or here.
MOTIF_PALETTE = [
    "tomato", "steelblue", "mediumseagreen", "darkorange", "mediumpurple",
    "deeppink", "teal", "goldenrod", "coral", "slategray",
]


def _empty_motif_scatter():
    return hv.Scatter([], "time", ["amplitude", "color", "size"]).opts(apply_ranges=False)


def build_motif_occurrence_overlay(group, m, fs, y_extent, unit_scale=1.0):
    """Top pane's occurrence markers: one vectorized `hv.Rectangles`
    (seed + neighbours, coloured/styled per row) plus one `hv.Scatter` of
    inverted-triangle markers above each — never one element per
    occurrence (`UI/README.md` records a confirmed multi-minute hang from
    per-row elements at 10-50 occurrences x redraws).

    `group` is one dict from `motif_groups.build_motif_groups` /
    `get_or_build_motif_groups` (`"seed_idx"`, `"neighbours"`), or `None`
    for "no group selected yet" — still returns the same Overlay shape
    (empty Rectangles + empty Scatter), so this stays a safe DynamicMap
    return before any scale/group is chosen.

    Deliberately shares axes with whatever this is overlaid onto (the
    reused `build_channel_dmap` curve) — NO `axiswise=True` here, unlike
    the bottom pane: these markers must move with the main curve's own
    y-range, the same way `build_detection_overlay`'s rectangles do.
    """
    y0, y1 = y_extent
    if group is None:
        return hv.Overlay([_empty_rectangles(), _empty_motif_scatter()])

    effective_fs = fs * unit_scale
    seed_idx = group["seed_idx"]
    rows = [(seed_idx, "seed", 0)] + [
        (idx, "neighbour", rank + 1) for rank, (idx, _dist) in enumerate(group["neighbours"])
    ]

    yrange = y1 - y0
    arrow_y = y1 + 0.04 * yrange
    rect_data, scatter_data = [], []
    for idx, role, rank in rows:
        color = SEED_MOTIF_COLOR if role == "seed" else MOTIF_PALETTE[(rank - 1) % len(MOTIF_PALETTE)]
        alpha = 0.55 if role == "seed" else 0.25
        lw = 2.0 if role == "seed" else 0.75
        x0, x1 = idx / effective_fs, (idx + m) / effective_fs
        rect_data.append((x0, y0, x1, y1, role, color, alpha, lw))
        scatter_data.append(((x0 + x1) / 2.0, arrow_y, color, 14 if role == "seed" else 9))

    rectangles = hv.Rectangles(rect_data, vdims=["role", "color", "alpha", "lw"]).opts(
        color="color", alpha="alpha", line_color="color", line_width="lw",
        apply_ranges=False, show_legend=False,
    )
    scatter = hv.Scatter(scatter_data, "time", ["amplitude", "color", "size"]).opts(
        marker="inverted_triangle", color="color", size="size",
        apply_ranges=False, show_legend=False,
    )
    return hv.Overlay([rectangles, scatter])


#: How `build_motif_waveform_overlay` chooses its y-range.
#:
#: "fit"   -- every sample of every overlaid curve is inside the frame.
#: "fence" -- a Tukey IQR fence (q25-q75, k=3) computed from the stacked
#:            curves, so one deep transient cannot squash the others flat.
MOTIF_Y_RANGE_MODES = ("fit", "fence")

#: The IQR fence's multiplier, in "fence" mode.
_MOTIF_Y_FENCE_K = 3.0


def _motif_overlay_y_bounds(all_values, mode):
    """`(lo, hi)` for the motif waveform overlay, unpadded.

    The two modes answer two different questions and both are legitimate,
    which is why this is a mode rather than a constant.

    "fence" bounds the range using only the MIDDLE 50% of the stacked
    values, so it is insensitive to how extreme or how numerous the tail
    points are -- it finds "the flat/wiggly baseline" as the bulk shape
    and fences the transient out. That was the original behaviour, added
    because a single deep drop rendered every other curve as a flat line.
    A percentile cutoff will not do the same job: on real
    electrophysiology-shaped data a sharp transient is several samples
    wide, so even a 1st/99th-percentile bound still includes it
    (measured: p1 at -5.9 against a true min of -6.0, on a 600-sample
    window whose baseline sits in roughly [0.1, 0.25]) -- a percentile is
    a bound on RANK, and >1% of a window can legitimately belong to one
    transient.

    But a Curve outside `ylim` simply clips at the frame edge (normal
    Bokeh behaviour, not a bug), so in "fence" mode the transient -- the
    part of a drop motif that carries its amplitude -- draws cut off.
    Reported as "the overlaid motifs plot is cut short on the y range".
    "fit" is therefore the default: it shows the whole motif, transient
    included, and is the correct default for a library of drop shapes
    whose depth is the evidence.
    """
    if mode not in MOTIF_Y_RANGE_MODES:
        raise ValueError(
            f"y_range_mode must be one of {MOTIF_Y_RANGE_MODES}, got {mode!r}"
        )

    data_lo, data_hi = float(all_values.min()), float(all_values.max())
    if mode == "fit":
        return data_lo, data_hi

    q1, q3 = np.percentile(all_values, [25, 75])
    iqr = q3 - q1
    if iqr <= 0:
        return data_lo, data_hi
    lo = max(q1 - _MOTIF_Y_FENCE_K * iqr, data_lo)
    hi = min(q3 + _MOTIF_Y_FENCE_K * iqr, data_hi)
    if hi <= lo:
        return data_lo, data_hi
    return float(lo), float(hi)


def build_motif_waveform_overlay(group, x, m, fs, *, normalize=True, show_envelope=True,
                                 y_range_mode="fit"):
    """Bottom pane: one `hv.Curve` per occurrence (seed first, then
    neighbours), z-normalised, in a shared Overlay, plus an optional
    mean +/- 1 std envelope over the neighbours (excluding the seed).

    `axiswise=True` on EVERY leaf element (curves AND the spread), per
    `UI/README.md`'s hard-won rule — without it, this pane's y-range gets
    captured document-wide by the Viewer's own `_decimated_curve`
    (elsewhere entirely, sharing the "amplitude" dimension name), which
    renders every motif as a flat line. A distinct vdim name ("zscore",
    not "amplitude") is used here too, as a second, independent layer of
    protection against that exact failure mode.

    `x` is the FULL channel array the group's indices were computed
    against (typically a `load_mp`+`load_channel_mmap` pairing at the
    same scale) -- occurrence snippets are sliced out of it here.

    `y_range_mode` is `"fit"` (default -- every sample inside the frame)
    or `"fence"` (a Tukey IQR fence, so one deep transient cannot squash
    the rest flat). See `_motif_overlay_y_bounds` for why both exist.

    Always returns an `hv.Overlay` (never a bare `Curve`), even with
    `group=None` or zero valid occurrences.
    """
    empty = hv.Overlay([hv.Curve([], "time_s", "zscore").opts(axiswise=True)])
    if group is None:
        return empty

    seed_idx = group["seed_idx"]
    occurrences = [(seed_idx, None)] + list(group["neighbours"])
    t_win = np.arange(m) / fs

    series = []  # (values, color, label, k)
    for k, (idx, dist) in enumerate(occurrences):
        snippet = np.asarray(x[idx:idx + m], dtype=np.float64)
        if len(snippet) < m:
            continue
        if normalize:
            std = snippet.std()
            values = (snippet - snippet.mean()) / std if std > 0 else snippet - snippet.mean()
        else:
            values = snippet
        color = SEED_MOTIF_COLOR if k == 0 else MOTIF_PALETTE[(k - 1) % len(MOTIF_PALETTE)]
        label = "seed" if k == 0 else f"nb{k} d={dist:.3f}"
        series.append((values, color, label, k))

    if not series:
        return empty

    # Explicit, PER-FRAME y-range. Without this, later frames don't
    # reliably rescale the axis at all -- `_set_y_range`'s docstring
    # (elsewhere in this module) documents the same root cause:
    # `ylim`+`framewise=True` alone is only honoured on a DynamicMap's
    # FIRST rendered frame, so switching motif groups left the axis stuck
    # wherever an earlier group (or the initial empty placeholder) left
    # it, while the real data rendered squashed into whatever sliver of
    # that stale range it happened to overlap (reported: every motif
    # looked flat and hard to read).
    #
    # WHICH range is `y_range_mode`'s decision -- see
    # `_motif_overlay_y_bounds`. This is only about making whichever
    # range was chosen actually stick to the axis.
    all_values = np.concatenate([v for v, _, _, _ in series])
    lo, hi = _motif_overlay_y_bounds(all_values, y_range_mode)
    pad = (hi - lo) * 0.12 or 1.0
    y0, y1 = float(lo - pad), float(hi + pad)

    curves = []
    envelope_stack = []
    for values, color, label, k in series:
        curves.append(hv.Curve((t_win, values), "time_s", "zscore", label=label).opts(
            color=color, line_width=(2.2 if k == 0 else 1.0), alpha=(0.95 if k == 0 else 0.55),
            axiswise=True, framewise=True, ylim=(y0, y1),
        ))
        if k > 0:
            envelope_stack.append(values)

    if show_envelope and len(envelope_stack) > 1:
        stack = np.array(envelope_stack)
        mu, sigma = stack.mean(axis=0), stack.std(axis=0)
        curves.append(hv.Spread((t_win, mu, sigma), "time_s", ["zscore", "spread"], label="+/-1 std").opts(
            color=MOTIF_MEAN_COLOR, alpha=0.12, axiswise=True, framewise=True, ylim=(y0, y1),
        ))
        curves.append(hv.Curve((t_win, mu), "time_s", "zscore", label="mean").opts(
            color=MOTIF_MEAN_COLOR, line_width=1.6, line_dash="dashed",
            axiswise=True, framewise=True, ylim=(y0, y1),
        ))

    # `_set_y_range` bypasses HoloViews' range-update pipeline entirely and
    # sets the Bokeh model property directly, which DOES take effect on
    # every refresh -- defense in depth alongside `ylim`+`framewise=True`
    # above, same reasoning as everywhere else `_set_y_range` is used in
    # this module. Safe to apply at the Overlay level here (unlike the
    # main curve's overlays): this Overlay is this DynamicMap's entire,
    # self-contained return value, never combined with another DynamicMap
    # afterwards.
    return hv.Overlay(curves).opts(hooks=[_set_y_range(y0, y1)])


# ══════════════════════════════════════════════════════════════════════════
#  Encoding inspection view (Run algorithm tab, Part 6, 2026-08)
# ══════════════════════════════════════════════════════════════════════════
#
# Four panels sharing one x-axis, showing exactly how a span was carved
# into PAA segments, quantised, and symbolised by cSAX/pSAX — see
# `Adapters._sax_common` and `Working.Detection.sax.csax_python.csax.csax`
# for where `symbols`/`details` (this section's only inputs, besides the
# signal itself) come from. Pure HoloViews construction, same module
# contract as everything else here (no Panel, no DB).
#
# Architecture mirrors the main curve + ribbon panes exactly (see this
# module's top-level docstring and `_style_ribbon_pane`): FOUR SEPARATE
# `hv.DynamicMap`s share one `RangeX` stream. The signal panel owns that
# stream NATIVELY (constructed the same way `build_channel_dmap` builds
# the main curve); the other three are only LISTENERS on it, so — per the
# bug documented at `_set_x_range` — they need that same hook to keep
# their axis correct on every refresh, not just the first frame.

SYMBOL_CMAP_NAME = "viridis"  # perceptually ordered: symbol value -> monotonic lightness

# The DELTA-domain alphabet wants a different colour logic from the
# amplitude one, and this is the only place in the encoding view where
# cSAX/pSAX and dSAX legitimately differ in appearance rather than in
# content. An amplitude alphabet is ORDERED — symbol 0 is "lowest", symbol
# k-1 is "highest", and a sequential map (viridis) reads correctly. A trend
# alphabet is DIVERGING about a privileged origin: SAME is not "the middle
# amount of rise", it is "no rise", and a sequential ramp actively hides
# that by giving zero no special appearance.
#
# The stops are hand-picked rather than taken from a stock diverging map
# (coolwarm, RdBu) for one concrete reason: every stock diverging map is
# near-WHITE at its midpoint, and the symbol strip draws its per-cell
# letters in white. A near-white SAME cell would render its letter
# invisible — which is the single most important cell to be able to read,
# since SAME is what a morphology pattern is padded with. These three stops
# keep every bin dark enough for white text (relative luminance <= 0.16,
# contrast ratio >= 4.4 against white) while still reading blue-to-red
# through a neutral centre.
DELTA_SYMBOL_CMAP_NAME = "dsax_diverging"
_DELTA_CMAP_STOPS = ("#2b5d9e", "#6e6e6e", "#b03a2e")


def cutline_domain(details):
    """Which quantity the cutlines are a threshold on. Declared by newer
    encoders; inferred for cSAX/pSAX, whose details dicts predate the key
    and which must not be edited (they carry unrelated uncommitted work).
    Absence of a `deltas` key is a reliable negative: no amplitude-domain
    encoder in this repo produces one."""
    return details.get("cutline_domain") or ("delta" if "deltas" in details else "amplitude")


def quantised_values(details):
    """The array the cutlines were actually applied to, in raw units —
    `paa_raw` for an amplitude encoder, `deltas_raw` for a trend one.

    This one function is what lets the quantisation panel, the symbol
    strip's hover, and the legend share a single code path across both
    domains instead of branching three times. Requantising it against
    `details["cutlines_raw"]` reproduces the symbol array in either
    domain, which is the property that makes the panels honest.
    """
    key = "deltas_raw" if cutline_domain(details) == "delta" else "paa_raw"
    return np.asarray(details[key], dtype=np.float64)


def value_axis_label(details):
    """Y-axis label for the quantisation panel, and the legend's range
    column header, in whichever domain this encoding lives."""
    return ("rise per segment" if cutline_domain(details) == "delta" else "amplitude")


def symbol_cmap_name(details):
    return (DELTA_SYMBOL_CMAP_NAME if cutline_domain(details) == "delta"
            else SYMBOL_CMAP_NAME)


def symbol_letters(details):
    """The per-symbol display letters for an encoding, or None for the
    default a/b/c convention. dSAX at k=3 reads D/S/U, which is the whole
    point of a trend alphabet being regex-searchable.

    Sourced from `dsax.SYMBOL_LETTERS` rather than redefined here, so the
    letters in the run panel's string box, the letters in the cached
    `.txt` written by `_persist_sax_encoding`, the strip's cell labels and
    the legend cannot drift apart — a regex a user saves against one of
    those has to keep matching the others.

    Returns None (a/b/c) for any alphabet size without a declared
    mnemonic, which deliberately includes every EVEN size: an even
    alphabet has no SAME bin at all, so a D/S/U-shaped scheme would be
    actively misleading there.
    """
    if cutline_domain(details) != "delta":
        return None
    from Working.Detection.sax.dsax_python.dsax import SYMBOL_LETTERS
    return SYMBOL_LETTERS.get(int(details.get("alphabet_size", 0)))


def symbol_names(details):
    """Full human names per symbol (DOWN/SAME/UP, DOWN2/DOWN1/...), or
    None — shown alongside the letter in the legend and colour key so a
    single-character alphabet is self-explanatory rather than a code the
    reader has to have memorised."""
    if cutline_domain(details) != "delta":
        return None
    from Working.Detection.sax.dsax_python.dsax import SYMBOL_NAMES
    return SYMBOL_NAMES.get(int(details.get("alphabet_size", 0)))


def same_symbol_index(details):
    """Index of the SAME bin, or None when the alphabet has no such bin.

    An EVEN alphabet size puts a cutline exactly AT zero rather than a bin
    around it, so there is no "no meaningful change" symbol to highlight —
    the legend has to say that plainly instead of highlighting an
    arbitrary row (see IMPLEMENTATION_NOTES.md 7.7).
    """
    if cutline_domain(details) != "delta":
        return None
    alphabet_size = int(details.get("alphabet_size", 0))
    if alphabet_size % 2 == 0:
        return None
    return int(details.get("zero_symbol", alphabet_size // 2))


def symbol_to_letter(i):
    """0->'a', 1->'b', ..., 25->'z', 26->'aa', 27->'ab', ... — what a SAX
    seed actually looks like pasted into a search (Part 6 3c). Shared by
    the symbol strip's cell labels, the alphabet legend, and the run
    panel's string/RLE display so a given symbol reads as the same letter
    everywhere it appears."""
    i = int(i)
    if i < 26:
        return chr(ord("a") + i)
    i -= 26
    return chr(ord("a") + i // 26) + chr(ord("a") + i % 26)


def symbol_label(i, letters=None):
    """One symbol's display character. `letters=None` is the default a/b/c
    convention (`symbol_to_letter`); a `letters` sequence overrides it
    per-index, which is how dSAX's D/S/U trend alphabet reaches every
    place a symbol is written.

    Out-of-range indices fall back rather than raising: a legend or a
    strip is a readout, and killing a render over one unexpected symbol
    would lose the other several thousand that are fine."""
    if letters is not None and 0 <= int(i) < len(letters):
        return letters[int(i)]
    return symbol_to_letter(i)


def symbols_to_string(symbols, letters=None):
    """The seed string a SAX run produces, e.g. "aabccba..." (Part 6 3c) —
    one letter per symbol via `symbol_to_letter`. Unambiguous to read back
    only while every symbol maps to a SINGLE letter (index < 26, i.e.
    alphabet_size <= 26) — cSAX rarely finds that many clusters and pSAX
    is capped at 64 in the UI, but a >26-symbol alphabet's multi-letter
    codes (from index 26 on) concatenate ambiguously, same limitation
    classic SAX has always had. Good enough for what this is for: a
    seed to eyeball or paste into a search, not a lossless serialisation
    (the real, lossless form is the int `symbols` array itself).

    `letters` (2026-08, dSAX) supplies an alternative single-character
    alphabet — D/S/U for a 3-symbol trend encoding. Passing None
    reproduces the pre-dSAX output byte for byte, which
    `tests/test_encoding_view_dsax.py` pins, because cSAX/pSAX strings are
    already persisted in the `encodings` cache and in `motifs.sax_string`
    and must keep reading back identically."""
    return "".join(symbol_label(s, letters) for s in symbols)


def symbols_to_rle(symbols, letters=None):
    """Run-length-encoded form, e.g. "a3 b2 c7" (Part 6 3c) — often the
    only readable summary once a string runs into the thousands of
    symbols, and repeated structure is immediately visible in it. See
    `symbols_to_string` for `letters`."""
    symbols = np.asarray(symbols, dtype=int)
    if len(symbols) == 0:
        return ""
    change = np.flatnonzero(np.diff(symbols)) + 1
    starts = np.concatenate([[0], change])
    ends = np.concatenate([change, [len(symbols)]])
    return " ".join(f"{symbol_label(symbols[s], letters)}{e - s}" for s, e in zip(starts, ends))


def _resolve_colormap(cmap_name):
    """`DELTA_SYMBOL_CMAP_NAME` is built on demand rather than registered
    with matplotlib's global colormap registry — registering would be a
    process-wide side effect of importing a plotting module, and would
    raise on a second import in the same interpreter."""
    import matplotlib
    from matplotlib.colors import LinearSegmentedColormap

    if cmap_name == DELTA_SYMBOL_CMAP_NAME:
        return LinearSegmentedColormap.from_list(cmap_name, list(_DELTA_CMAP_STOPS))
    return matplotlib.colormaps[cmap_name]


def symbol_colors(alphabet_size, cmap_name=None):
    """One hex colour per symbol index, 0..alphabet_size-1, via a
    perceptually-ordered colormap (Part 6 3b/3e) — used identically by
    the symbol strip, the quantisation bands, and the alphabet legend so
    a symbol is never a different colour in one panel than another.

    `cmap_name=None` keeps the sequential default every existing caller
    gets; pass `symbol_cmap_name(details)` to get the diverging
    zero-anchored palette a trend alphabet needs (see
    `DELTA_SYMBOL_CMAP_NAME`)."""
    n = max(int(alphabet_size), 2)
    cmap = _resolve_colormap(cmap_name or SYMBOL_CMAP_NAME).resampled(n)
    return ["#%02x%02x%02x" % tuple(int(round(c * 255)) for c in cmap(i)[:3]) for i in range(n)]


def segment_time_edges(t, n_symbols, samples_per_symbol):
    """seg_t[i]..seg_t[i+1] is segment i's time span, read directly off
    `t`'s own sample spacing (never recomputed from `fs`) so this is
    correct regardless of anything upstream that already shifted or
    resampled `t` — it's the exact array the symbols were computed from."""
    idx = np.arange(n_symbols + 1) * samples_per_symbol
    idx = np.minimum(idx, len(t) - 1)
    return np.asarray(t)[idx]


def _band_edges(cutlines_raw, y_extent):
    """(lo, hi) per symbol band, in the raw units of whichever quantity
    was quantised — the two open ends are clamped to the current y_extent
    purely for DRAWING a bounded shaded rectangle; the decision boundary
    itself (`cutlines_raw`) is exact and unclamped."""
    edges = [y_extent[0]] + list(cutlines_raw) + [y_extent[1]]
    return list(zip(edges[:-1], edges[1:]))


# Above this many highlighted matches the strip stops drawing them. A
# regex over a 100k-symbol string can legitimately match thousands of
# times; `re.finditer` handles that fine, but every match is a Bokeh
# glyph, and a few thousand extra Rectangles per frame makes pan/zoom
# visibly stutter. The run panel keeps the FULL match list (so the
# match counter and the step-through navigation are exact) and passes
# only the first `ENCODING_HIGHLIGHT_CAP` here, saying so in the UI when
# the cap bites.
ENCODING_HIGHLIGHT_CAP = 500

# A manual trigger stream for the symbol strip's regex-match highlights.
# `spans` is part of the stream, so changing it changes the DynamicMap's
# key and the frame is genuinely rebuilt — calling `.event()` with an
# unchanged `x_range` would otherwise be served from HoloViews' frame
# cache and the new highlights would never appear. (Same "shared manual
# trigger stream" pattern `app.py` uses for the overlay DynamicMaps; see
# this module's docstring, bug 4.)
#
# `param.Parameter`, NOT a bare `()` default: `Stream.define` infers a
# parameter type from the default value, and a tuple default becomes a
# `param.Tuple`, which pins its LENGTH to the default's — so the first
# `.event(spans=((3, 7),))` raised "not of the correct length (1 instead
# of 0)". Confirmed by exactly that failure. An untyped Parameter accepts
# any length; tuples (not lists) are still passed in so the value stays
# hashable for HoloViews' frame keying.
HighlightStream = hv.streams.Stream.define(
    "EncodingHighlight", spans=param.Parameter(default=()),
)


def build_encoding_panels(x, t, symbols, details, initial_x_range=None,
                           letter_threshold=ENCODING_LETTER_THRESHOLD,
                           signal_title="Encoded signal", y_mode="auto",
                           highlight_stream=None):
    """Part 6/7. `x`/`t` are the EXACT array the SAX adapter encoded
    (after any upstream preprocessing step — see
    `Adapters.detection_sax_csax`'s module note on why
    `AdapterResult.x`/`.t` are populated even though `output_kind`
    ="encoding"); `symbols` is the 0-based symbol array; `details` is the
    dict `csax()`/`psax()` return under `return_details=True` (already
    unpacked from `AdapterResult.meta["details"]` by the caller).

    `y_mode`: "auto" (default) autoscales each panel to ITS OWN visible
    data every frame, via the same `compute_display_y_range` the Viewer's
    main curve and the Before/After panels use (Part 7, Part 2) — never a
    second y-range computation. "shared" instead matches every panel to
    the signal panel's own range, for the rarer case where comparing
    absolute amplitudes across panels is the point.

    Part 7 architecture notes (see this module's docstring, bug 3, and
    UI/README.md's x-range-linking section for the established patterns
    this follows):
    - All four panels use "time_s"/"amplitude" — the SAME kdim/vdim names
      `UI/run_panel.py`'s Before/After panels use — never HoloViews'
      default "x"/"y". Mixing dimension names within one panel's own
      Overlay was confirmed (empirically, not just suspected) to corrupt
      that panel's inferred axis label independent of which element
      "wins"; giving every element the same names removes the ambiguity
      instead of relying on inference order.
    - Every DynamicMap's SIZING opts (height, responsive, toolbar, axis
      labels, fontsize) are set ONCE via `.opts()` on the DynamicMap
      object after construction, never inside the per-frame callback —
      confirmed directly that a single missing `responsive=True` inside
      one panel's per-frame `.opts()` call (Quantisation, previously) is
      enough to leave that one panel's figure at Bokeh's plain fixed
      300x300ish default forever, since nothing ever corrects it on
      subsequent frames. `xlim`/`ylim`/`title`/`hooks` still vary by
      frame and stay inside the callback — hooks in particular CANNOT be
      hoisted: confirmed directly that HoloViews' per-key option
      resolution takes the DynamicMap-level `hooks` list INSTEAD of the
      per-frame one when both are set, not a merge of the two, so the
      per-frame `_set_x_range` hook and this module's border-alignment
      hook must be combined into ONE list inside the callback.
    - `_set_x_range` keeps panels 2-4 (which only LISTEN to `range_stream`,
      not natively own it — see `_set_x_range`'s docstring) x-aligned with
      panel 1 past the first frame; the same border-alignment hook this
      module's `style_main_plot_frame` applies to the main plot is applied
      to all four here too, since four independently-sized y-axis tick
      label widths (these panels' y-ranges can differ by orders of
      magnitude) would otherwise shift where each panel's frame starts.
    - `axiswise=True` on every LEAF element, not just the enclosing
      Overlay (Part 7, Part 2 root cause): confirmed directly, via the
      live browser's own Bokeh model state (not just suspected), that an
      `Overlay`-level `axiswise=True` does NOT exempt its constituent
      elements from HoloViews' cross-plot "same dimension name -> shared
      Range1d" linking — that linking is document-wide, not scoped to one
      `hv.Layout`. Two real instances of this were caught: (1) the PAA and
      Quantisation panels' Overlays were linked to EACH OTHER's y_range
      despite both setting `axiswise=True` at the Overlay level, because
      none of their individual constituent elements (the grey background
      curve, the PAA bars, the boundary lines, the band `HSpan`s, the
      cutline `HLine`s, the step curve, the labels) had it themselves; (2)
      separately, `_decimated_curve` (the "staged span, not yet
      processed" preview and the cross-channel peek, both sharing this
      module's "amplitude" vdim name) had NO `axiswise` at all, so its own
      never-changing raw-scale range kept winning the shared object back
      from the encoding panels. Only `_panel_signal`'s bare `Curve` (no
      Overlay wrapper, `axiswise=True` set directly on itself) was ever
      actually protected. Fixed by setting `axiswise=True` on every leaf
      element in `_panel_paa`/`_panel_quant` AND on `_decimated_curve`.
    - `_set_y_range` (Part 7, Part 2): the Y-axis analogue of `_set_x_range`,
      kept as defense in depth alongside the `axiswise=True` fix above —
      even a correctly-unshared Range1d still needs its `.start`/`.end`
      forced past the first frame, for the same reason `_set_x_range` is
      needed for X. Included in panels 1-3's hooks list (panel 4's
      y-range is a fixed 0..1 lane coordinate, never data-driven, so
      doesn't need it).
    - Only panel 1 carries a toolbar — panels 2-4 get `toolbar=None`,
      matching the ribbon panes' "one interactive plot in the stack".

    Two quantisation DOMAINS (2026-08, dSAX)
    -----------------------------------------
    cSAX/pSAX quantise a segment's MEAN (`paa_raw`, an amplitude in mV);
    dSAX quantises its RISE (`deltas_raw`, an amplitude per segment). The
    cutlines are a threshold on whichever of those the encoder used, so
    panels 2 and 3 read the domain off `cutline_domain(details)` and take
    their arrays from `quantised_values(details)` rather than from
    `paa_raw` unconditionally. Drawing delta cutlines against an amplitude
    level is not merely unhelpful: they are quantities of DIFFERENT
    DIMENSION, and on a real channel (tens of mV of standing potential,
    sub-mV excursions) the delta cutlines collapse to a sliver near zero
    and the panel looks like a broken encoder.

    The domain is fixed for the whole lifetime of these DynamicMaps (it
    comes from `details`, which does not change), so the branch sits
    OUTSIDE the per-frame callbacks and every frame still returns the same
    element composition — the invariant bug 3 in this module's docstring
    is about.

    Returns `(dmap_signal, dmap_paa, dmap_quant, dmap_strip, range_stream)`.
    """
    x = np.asarray(x, dtype=np.float64)
    t = np.asarray(t, dtype=np.float64)
    symbols = np.asarray(symbols, dtype=int)
    full_extent = (float(t[0]), float(t[-1])) if len(t) else (0.0, 1.0)

    sps = int(details["samples_per_symbol"])
    n_symbols = int(details["n_symbols"])
    alphabet_size = int(details["alphabet_size"])
    paa_raw = np.asarray(details["paa_raw"], dtype=np.float64)
    cutlines_raw = np.asarray(details["cutlines_raw"], dtype=np.float64)
    seg_t = segment_time_edges(t, n_symbols, sps)

    domain = cutline_domain(details)
    is_delta = domain == "delta"
    # `quant_values` is what the cutlines actually decided on: the segment
    # means for an amplitude encoder, the segment rises for a trend one.
    quant_values = quantised_values(details)
    letters = symbol_letters(details)
    colors = symbol_colors(alphabet_size, symbol_cmap_name(details))
    # Per-segment rise in raw units, for panel 2's trend lines. `seg_slope`
    # is per-SAMPLE, so the rise across the segment is slope * (sps - 1) —
    # the same convention `trend_estimators` normalises every estimator to,
    # which is why this equals `deltas_raw[i]` exactly and the test pins it.
    seg_rise_raw = (np.asarray(details["seg_slope_raw"], dtype=np.float64) * (sps - 1)
                    if is_delta else None)

    quant_label = value_axis_label(details)
    quant_title = ("Quantisation — segment rise vs. learned cutlines" if is_delta
                   else "Quantisation — PAA vs. learned cutlines")
    paa_title = ("Segment trends over signal" if is_delta
                 else "PAA (red) over signal (grey)")

    range_stream = hv.streams.RangeX(x_range=initial_x_range or full_extent)
    highlight_stream = highlight_stream if highlight_stream is not None else HighlightStream()
    border_hook = _set_frame_borders(ENCODING_FRAME_MIN_BORDER_LEFT, ENCODING_FRAME_MIN_BORDER_RIGHT)

    def _visible_sample_range(x0, x1):
        i0 = max(0, int(np.searchsorted(t, x0)))
        i1 = min(len(t), int(np.searchsorted(t, x1)) + 1)
        if i1 <= i0:
            i1 = min(len(t), i0 + 1)
        return i0, i1

    def _visible_segment_range(x0, x1):
        i0 = max(0, int(np.searchsorted(seg_t, x0, side="right")) - 1)
        i1 = min(n_symbols, int(np.searchsorted(seg_t, x1, side="left")) + 1)
        if i1 <= i0:
            i1 = min(n_symbols, i0 + 1)
        return i0, i1

    def _signal_yrange(i0, i1):
        return compute_display_y_range(x[i0:i1], (0.0, 1.0), y_autoscale=True)

    # ── Panel 1: the actual encoded signal (owns the RangeX natively) ───
    def _panel_signal(x_range):
        x0, x1 = x_range if x_range and x_range[0] is not None else full_extent
        i0, i1 = _visible_sample_range(x0, x1)
        yr = _signal_yrange(i0, i1)
        x_plot, t_plot = _minmax_decimate(x[i0:i1], t[i0:i1], MAX_RENDER_POINTS)
        return hv.Curve((t_plot, x_plot), "time_s", "amplitude").opts(
            color=CURVE_COLOR, line_width=1,
            xlim=(x0, x1), ylim=yr, framewise=True, axiswise=True,
            title=f"{signal_title}  [y: {yr[0]:.4g} to {yr[1]:.4g}]",
            hooks=[border_hook, _set_y_range(yr[0], yr[1])],
        )

    dmap_signal = hv.DynamicMap(_panel_signal, streams=[range_stream]).opts(
        height=ENCODING_SIGNAL_HEIGHT, responsive=True, show_title=True,
        xlabel="time (s)", ylabel="amplitude", fontsize=PLOT_FONTSIZE,
        default_tools=[], tools=["xpan", "xwheel_zoom", "save", "reset"], active_tools=["xwheel_zoom"],
    )

    # ── Panel 2: PAA overlay — signal in grey, PAA bars + boundaries on top ─
    def _panel_paa(x_range):
        x0, x1 = x_range if x_range and x_range[0] is not None else full_extent
        si0, si1 = _visible_sample_range(x0, x1)
        gi0, gi1 = _visible_segment_range(x0, x1)
        if y_mode == "shared":
            yr = _signal_yrange(si0, si1)
        else:
            visible_paa = paa_raw[gi0:gi1]
            if is_delta and len(visible_paa):
                # The trend lines run from mean-rise/2 to mean+rise/2, so
                # a steep segment reaches further than its own mean does;
                # including only `paa_raw` would clip the very lines this
                # panel exists to show.
                half = seg_rise_raw[gi0:gi1] / 2.0
                visible_paa = np.concatenate([visible_paa - half, visible_paa + half])
            combined = np.concatenate([x[si0:si1], visible_paa]) if len(visible_paa) else x[si0:si1]
            yr = compute_display_y_range(combined, (0.0, 1.0), y_autoscale=True)

        x_plot, t_plot = _minmax_decimate(x[si0:si1], t[si0:si1], MAX_RENDER_POINTS)
        # axiswise=True on every LEAF element, not just the enclosing
        # Overlay below — see this function's sibling `_panel_quant` and
        # the module docstring's Part 7 note on `_set_y_range` for why:
        # confirmed directly (via the live browser's own Bokeh model
        # state) that an `axiswise=True` set only on the Overlay wrapper
        # does not exempt its CONSTITUENT elements from HoloViews'
        # document-wide "same dimension name -> shared Range1d" linking;
        # only `panel_signal`'s single bare Curve (which sets axiswise on
        # itself directly, having no Overlay wrapper at all) was ever
        # actually protected by it.
        bg = hv.Curve((t_plot, x_plot), "time_s", "amplitude").opts(
            color="#bbbbbb", line_width=1, apply_ranges=False, axiswise=True,
        )
        if is_delta:
            # One sloped line per segment instead of a flat PAA bar. The
            # line is CENTRED on `paa_raw[i]` — the segment's own mean —
            # so it sits on the stretch of signal it describes rather than
            # floating at an arbitrary offset, and its rise from end to
            # end is exactly the delta that chose the symbol. That makes
            # the panel directly falsifiable by eye: if a red (UP) line
            # visibly runs downhill, the encoding is wrong.
            #
            # Coloured by symbol via a STRING-valued dimension with a
            # string-keyed dict `cmap`, not the raw int — see
            # `_panel_strip`'s comment for the confirmed degenerate case a
            # numeric colour dimension hits when every visible value is
            # identical (a long quiescent run of SAME is exactly that).
            bar_data = [
                (seg_t[i], paa_raw[i] - seg_rise_raw[i] / 2.0,
                 seg_t[i + 1], paa_raw[i] + seg_rise_raw[i] / 2.0,
                 str(int(symbols[i])))
                for i in range(gi0, gi1)
            ] or [(x0, yr[0], x0, yr[0], "0")]
            bars = hv.Segments(bar_data, kdims=["x0", "y0", "x1", "y1"],
                               vdims=["symbol"]).opts(
                color="symbol", cmap={str(i): colors[i] for i in range(alphabet_size)},
                line_width=3, apply_ranges=False, axiswise=True, show_legend=False,
            )
        else:
            bar_data = [(seg_t[i], paa_raw[i], seg_t[i + 1], paa_raw[i]) for i in range(gi0, gi1)]
            bars = hv.Segments(bar_data, kdims=["x0", "y0", "x1", "y1"]).opts(
                color="#d62728", line_width=3, apply_ranges=False, axiswise=True,
            )
        boundary_data = [(seg_t[i], yr[0], seg_t[i], yr[1]) for i in range(gi0, gi1 + 1)]
        boundaries = hv.Segments(boundary_data, kdims=["x0", "y0", "x1", "y1"]).opts(
            color="#999999", line_width=0.5, alpha=0.5, apply_ranges=False, axiswise=True,
        )
        return (bg * boundaries * bars).opts(
            hv.opts.Overlay(
                xlim=(x0, x1), ylim=yr, framewise=True, axiswise=True,
                title=f"{paa_title}  [y: {yr[0]:.4g} to {yr[1]:.4g}]",
                hooks=[border_hook, _set_x_range(x0, x1), _set_y_range(yr[0], yr[1])],
            ),
        )

    dmap_paa = hv.DynamicMap(_panel_paa, streams=[range_stream]).opts(
        hv.opts.Overlay(height=ENCODING_PAA_HEIGHT, responsive=True, show_title=True, toolbar=None,
                         xlabel="time (s)", ylabel="amplitude", fontsize=PLOT_FONTSIZE),
    )

    # ── Panel 3: quantisation — PAA step curve, cutlines, shaded bands ──
    def _panel_quant(x_range):
        x0, x1 = x_range if x_range and x_range[0] is not None else full_extent
        si0, si1 = _visible_sample_range(x0, x1)
        gi0, gi1 = _visible_segment_range(x0, x1)
        if y_mode == "shared":
            yr = _signal_yrange(si0, si1)
        else:
            # Part 7, Part 2 item 3: union of the VISIBLE quantised values
            # and ALL cutlines_raw (not just visible ones — the point is to
            # always show where the current view sits within the whole
            # alphabet), padded. The two outermost bands (+/-inf) are
            # clipped to this range in `_band_edges` below, never driving
            # it to infinity. Unchanged logic; `quant_values` is `paa_raw`
            # in the amplitude domain and `deltas_raw` in the delta one.
            visible_q = quant_values[gi0:gi1]
            combined = np.concatenate([visible_q, cutlines_raw]) if len(visible_q) else cutlines_raw
            yr = compute_display_y_range(combined, (0.0, 1.0), y_autoscale=True)

        step_x, step_y = [], []
        for i in range(gi0, gi1):
            step_x += [seg_t[i], seg_t[i + 1]]
            step_y += [quant_values[i], quant_values[i]]
        if not step_x:
            step_x, step_y = [x0, x1], [yr[0], yr[0]]
        curve = hv.Curve((step_x, step_y), "time_s", "amplitude").opts(
            color="#1f1f1f", line_width=1.5, apply_ranges=False, axiswise=True,
        )
        bands = []
        for sym, (blo, bhi) in enumerate(_band_edges(cutlines_raw, yr)):
            bands.append(
                hv.HSpan(blo, bhi).opts(color=colors[sym % len(colors)], alpha=0.35,
                                        apply_ranges=False, axiswise=True)
            )
        cutline_elems = [
            hv.HLine(c).opts(color="#333333", line_width=1, line_dash="dashed", axiswise=True)
            for c in cutlines_raw
        ]
        # Right-edge band labels — position tracks the CURRENT view's
        # right edge every frame, so they always sit at the visible edge
        # rather than a fixed data coordinate that scrolls out of view.
        label_x = [x1 - (x1 - x0) * 0.01] * alphabet_size  # inset 1% so text isn't clipped at the frame edge
        label_y = [(blo + bhi) / 2 if np.isfinite(blo) and np.isfinite(bhi) else 0.0
                   for blo, bhi in _band_edges(cutlines_raw, yr)]
        label_text = [symbol_label(i, letters) for i in range(alphabet_size)]
        labels = hv.Labels((label_x, label_y, label_text), ["time_s", "amplitude"], "label").opts(
            text_align="right", text_baseline="middle", text_font_size="10pt",
            text_color="black", text_font_style="bold", apply_ranges=False, axiswise=True,
        )
        return hv.Overlay(bands + cutline_elems + [curve, labels]).opts(
            hv.opts.Overlay(
                xlim=(x0, x1), ylim=yr, framewise=True, axiswise=True,
                title=f"{quant_title}  [y: {yr[0]:.4g} to {yr[1]:.4g}]",
                hooks=[border_hook, _set_x_range(x0, x1), _set_y_range(yr[0], yr[1])],
            ),
        )

    dmap_quant = hv.DynamicMap(_panel_quant, streams=[range_stream]).opts(
        # The vdim stays "amplitude" in BOTH domains — every element in
        # this Overlay must share one dimension name (see the docstring's
        # Part 7 note on mixed kdims corrupting the inferred axis label),
        # and the leaf-level `axiswise=True` is what keeps the delta panel
        # from sharing a Range1d with the genuinely-amplitude panels. Only
        # the DISPLAYED label changes, via the `ylabel` opt that was
        # already set explicitly here.
        hv.opts.Overlay(height=ENCODING_QUANT_HEIGHT, responsive=True, show_title=True, toolbar=None,
                         xlabel="time (s)", ylabel=quant_label, fontsize=PLOT_FONTSIZE),
    )

    # ── Panel 4: symbol strip — one coloured cell per segment ───────────
    def _panel_strip(x_range, spans):
        x0, x1 = x_range if x_range and x_range[0] is not None else full_extent
        gi0, gi1 = _visible_segment_range(x0, x1)
        n_visible = gi1 - gi0
        # `symbol_str` (not the raw int) is what drives colour — a numeric
        # colour dimension whose values happen to be IDENTICAL across
        # every visible cell (a long run of the same symbol, or a
        # collapsed 1-symbol alphabet) degenerates HoloViews' automatic
        # linear colormapper to a literal constant instead of the mapped
        # colour (confirmed directly: `color=<int vdim>` renders every
        # cell as `fill_color=0`, not `colors[0]`, whenever min==max).
        # A STRING-valued dimension with a matching string-keyed dict
        # `cmap` forces an explicit CATEGORICAL colour mapper instead,
        # which has no such degenerate case.
        cmap = {str(i): colors[i] for i in range(alphabet_size)}
        # `value` is the quantity the cutlines decided on (segment mean or
        # segment rise, per domain); `level` is always the segment's mean
        # amplitude. In the amplitude domain they are the same number by
        # construction — kept anyway so the hover carries the SAME field
        # set whichever encoder produced the strip, and in the delta domain
        # `level` is the context that makes a trend readable at all ("a
        # +0.4 mV rise" means something different at -60 mV than at 0 mV).
        lo_fallback = float(quant_values.min()) if quant_values.size else 0.0
        hi_fallback = float(quant_values.max()) if quant_values.size else 0.0
        rect_data = [
            (seg_t[i], 0.0, seg_t[i + 1], 1.0, str(int(symbols[i])), symbol_label(symbols[i], letters),
             float(cutlines_raw[symbols[i] - 1]) if symbols[i] > 0 else lo_fallback,
             float(cutlines_raw[symbols[i]]) if symbols[i] < alphabet_size - 1 else hi_fallback,
             float(quant_values[i]), float(paa_raw[i]), float(seg_t[i]), float(seg_t[i + 1]))
            for i in range(gi0, gi1)
        ] or [(x0, 0.0, x0, 0.0, "0", "", 0.0, 0.0, 0.0, 0.0, x0, x0)]
        vdims = ["symbol", "letter", "range_lo", "range_hi", "value", "level", "t0", "t1"]
        value_label = "segment rise" if is_delta else "PAA value"
        rects = hv.Rectangles(rect_data, vdims=vdims).opts(
            color="symbol", cmap=cmap, line_width=0.5, line_color="white",
            apply_ranges=False, show_legend=False, tools=["hover"],
            hover_tooltips=[
                ("symbol", "@letter (index @symbol)"),
                (f"{quant_label} range", "@range_lo{0.000} to @range_hi{0.000}"),
                ("time", "@t0{0.0}s to @t1{0.0}s"),
                (value_label, "@value{0.000}"),
                ("level", "@level{0.000}"),
            ],
        )
        # Regex-match highlights (Part dSAX F). ALWAYS constructed, with a
        # degenerate zero-area rectangle when there is nothing to show, for
        # the same reason `labels` below is always constructed: a
        # DynamicMap callback must never vary which element types it
        # returns across frames (this module's docstring, bug 3). Drawn as
        # an unfilled heavy outline rather than a fill so the symbol colour
        # underneath — the thing being searched — stays visible.
        match_data = [
            (seg_t[s], 0.0, seg_t[min(e, n_symbols)], 1.0)
            for s, e in (spans or ()) if s < n_symbols and e > gi0 and s < gi1
        ] or [(x0, 0.0, x0, 0.0)]
        highlights = hv.Rectangles(match_data).opts(
            fill_alpha=0.0, line_color="#ffcc00", line_width=3,
            apply_ranges=False, show_legend=False,
        )
        # Always present (never omitted) so every frame returns the same
        # element COMPOSITION regardless of the letter-threshold branch —
        # see this module's docstring, bug 3: a DynamicMap callback must
        # never vary which element types it returns across frames.
        if n_visible <= letter_threshold and gi1 > gi0:
            label_data = [((seg_t[i] + seg_t[i + 1]) / 2, 0.5, symbol_label(symbols[i], letters))
                          for i in range(gi0, gi1)]
        else:
            label_data = [(x0, 0.5, "")]
        labels = hv.Labels(label_data, ["time_s", "lane"], "label").opts(
            text_font_size="9pt", text_color="white", apply_ranges=False,
        )
        return (rects * highlights * labels).opts(
            hv.opts.Overlay(xlim=(x0, x1), ylim=(0.0, 1.0), hooks=[border_hook, _set_x_range(x0, x1)]),
        )

    dmap_strip = hv.DynamicMap(_panel_strip, streams=[range_stream, highlight_stream]).opts(
        # Part 7, Part 4 item 4: a real, visible time axis (shared with the
        # three panels above it) so the strip can be related to them by
        # eye — it used to hide both axes entirely, like the ribbon panes,
        # but unlike those it sits directly under panels that DO show a
        # time axis, so hiding its own made it float unanchored.
        hv.opts.Overlay(height=ENCODING_STRIP_HEIGHT, responsive=True, show_title=False, toolbar=None,
                         yaxis=None, xlabel="time (s)", fontsize=PLOT_FONTSIZE),
    )

    return dmap_signal, dmap_paa, dmap_quant, dmap_strip, range_stream


# ── Render a value of any interchange type ─────────────────────────────────
# T56: the single entry point for turning a pipeline value into a renderable
# element. Every plot-centric surface — filmstrip, focus mode, block-card
# preview — goes through this one function, and NOTHING downstream may switch
# on a value's type locally. That rule is what keeps "plot-centric" from
# degrading into "blank for half the blocks": a pane that renders nothing does
# not raise, it is blank, and it looks exactly like a feature that was never
# built. This module imports no Panel and reads no database — that stays true.

_VALUE_HEIGHT = 150


def _value_curve(x, fs, color):
    """The shared `_decimated_curve` call behind Signal and Scores — the two
    interchange types that render as a curve against time. Reuses the exact
    decimate-then-build path every other trace in this module uses, so a
    value can never visually disagree with the main Viewer curve."""
    x = np.asarray(x, dtype=np.float64)
    t = np.arange(len(x)) / float(fs) if len(x) else np.array([])
    return _decimated_curve(x, t, MAX_RENDER_POINTS, color, _VALUE_HEIGHT, xlabel="time (s)")


def _render_signal_value(value):
    return _value_curve(value.x, value.fs, CURVE_COLOR)


def _render_scores_value(value):
    return _value_curve(value.values, value.fs, CURVE_COLOR)


def _encoding_summary(value):
    """Renderable text-card fallback for an `Encoding` that cannot use the
    symbol-strip builder — an image encoding, an empty symbolic encoding, or
    a symbolic encoding whose metadata lacks the encoded arrays/details the
    strip needs. A text readout is never a decorative lie: it states what the
    encoding is, which is all a degenerate value has to offer."""
    values = value.values
    if getattr(value, "kind", None) == "symbolic":
        rows = [("kind", "symbolic"), ("symbols", str(int(np.size(values))))]
    else:
        arr = np.asarray(values)
        shape = " x ".join(str(int(d)) for d in arr.shape) if arr.ndim else "scalar"
        rows = [("kind", getattr(value, "kind", None) or "image"), ("shape", shape)]
    return hv.Table(rows, "field", "value").opts(
        height=_VALUE_HEIGHT, fontsize=PLOT_FONTSIZE,
    )


def _render_encoding_value(value, meta):
    """Symbolic encodings reuse the existing symbol-strip builder
    (`build_encoding_panels`'s fourth panel) rather than writing a second
    strip renderer; anything the strip builder cannot handle falls back to a
    text summary rather than returning None or raising (a raise becomes a
    silently blank pane)."""
    if getattr(value, "kind", None) == "symbolic":
        symbols = np.asarray(value.values)
        x = meta.get("encoded_x")
        t = meta.get("encoded_t")
        details = meta.get("details")
        if (symbols.size and x is not None and t is not None and details is not None
                and np.asarray(x).size and np.asarray(t).size):
            try:
                _, _, _, dmap_strip, _ = build_encoding_panels(x, t, symbols, details)
                return dmap_strip
            except Exception:
                # Never let a strip the builder cannot draw produce a blank
                # pane — say what the encoding is instead.
                pass
    return _encoding_summary(value)


def _render_spanset_value(value, meta):
    """An interval overlay: one `Rectangles` per span, in time units. The
    SpanSet stores sample indices, so `fs` is taken from the adapter metadata
    when present and defaults to 1.0 (sample space) otherwise. An empty
    SpanSet returns a zero-area, fully transparent rectangle — the smallest
    thing that still renders as an interval overlay."""
    fs = float(meta.get("fs", 1.0))
    starts = np.asarray(value.starts, dtype=np.float64) / fs
    ends = np.asarray(value.ends, dtype=np.float64) / fs
    if starts.size == 0:
        # A bare `hv.Rectangles([])` is NOT renderable standalone — the
        # Bokeh backend raises `KeyError: 'x0'` because nothing establishes
        # a range (confirmed headlessly). A single zero-area, fully
        # transparent rectangle renders and is the closest thing to "an
        # empty interval overlay that still draws".
        return hv.Rectangles([(0.0, 0.0, 0.0, 0.0)]).opts(
            color=CURVE_COLOR, alpha=0, line_width=0,
            height=_VALUE_HEIGHT, responsive=True, fontsize=PLOT_FONTSIZE,
        )
    rects = hv.Rectangles([(s, 0.0, e, 1.0) for s, e in zip(starts, ends)])
    return rects.opts(
        color=CURVE_COLOR, alpha=0.5, line_color="black", line_width=1,
        height=_VALUE_HEIGHT, responsive=True, fontsize=PLOT_FONTSIZE,
    )


def _render_windowset_value(value):
    """A window index: a spike at each window's start time. A one-window
    WindowSet renders as a single spike; a zero-window one as an empty spike
    plot — both renderable, neither a blank pane."""
    t = np.asarray(value.starts, dtype=np.float64) / float(value.fs)
    return hv.Spikes(t).opts(
        color=CURVE_COLOR, height=_VALUE_HEIGHT, responsive=True,
        fontsize=PLOT_FONTSIZE,
    )


def _render_grouping_value(value):
    """A cluster-size summary: one bar per cluster label, counting the
    windows in it. An empty grouping renders as an empty bar chart."""
    labels = np.asarray(value.labels, dtype=int)
    counts = np.bincount(labels) if labels.size else np.array([], dtype=int)
    data = [(str(i), int(c)) for i, c in enumerate(counts)]
    return hv.Bars(data, "cluster", "count").opts(
        height=_VALUE_HEIGHT, responsive=True, fontsize=PLOT_FONTSIZE,
    )


def _render_model_value(value, meta):
    """A text card. A trained model has no natural plot, and inventing one
    produces a decorative lie — a picture that looks like evidence and is
    not. State what the model is (its path and the adapter's key metadata);
    do not chart it."""
    rows = [("model path", str(value.path))]
    for key in ("n_windows", "n_classes", "holdout_accuracy", "n_features_kept"):
        if key in meta:
            rows.append((key, str(meta[key])))
    return hv.Table(rows, "field", "value").opts(
        height=_VALUE_HEIGHT, fontsize=PLOT_FONTSIZE,
    )


def render_value(type_kind, value, meta=None):
    """Turn a value the pipeline produces into a renderable element, given
    its interchange type and the adapter's metadata.

    This is the single entry point for value rendering. Nothing downstream
    may switch on a value's type locally. All seven interchange types return
    a non-`None`, renderable HoloViews object, including for a degenerate
    value (an empty SpanSet, a one-window WindowSet); returning `None` is
    never correct. An unknown type name raises with a message naming it.

    `type_kind` is one of the seven lowercase interchange types (`signal`,
    `encoding`, `scores`, `spanset`, `windowset`, `grouping`, `model`).
    `value` is the typed object from `Working.types` named by `type_kind`.
    `meta` is the adapter's metadata dict (`AdapterResult.meta`), consulted
    where a type needs something its value object does not carry (e.g. the
    encoded arrays/details behind an `Encoding`, or `fs` for a `SpanSet`).
    """
    meta = dict(meta or {})
    kind = (type_kind or "").lower()
    if kind == "signal":
        return _render_signal_value(value)
    if kind == "scores":
        return _render_scores_value(value)
    if kind == "encoding":
        return _render_encoding_value(value, meta)
    if kind == "spanset":
        return _render_spanset_value(value, meta)
    if kind == "windowset":
        return _render_windowset_value(value)
    if kind == "grouping":
        return _render_grouping_value(value)
    if kind == "model":
        return _render_model_value(value, meta)
    raise ValueError(f"render_value: unknown interchange type {type_kind!r}")
