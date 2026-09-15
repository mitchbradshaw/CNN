"""Bokeh figure factories carrying the design's visual rules: light ground, 1 px lines, real mV
axes (never normalised), tinted span bands, Geist Mono tick labels, no toolbar clutter.

Panel's raw_css cannot reach inside a Bokeh canvas, so every one of those rules is set here, on
the figure objects, by hand."""
from __future__ import annotations

import numpy as np
from bokeh.models import (BasicTickFormatter, CrosshairTool, CustomJSTickFormatter, Range1d, Span)
from bokeh.plotting import figure

MONO = "Geist Mono, ui-monospace, Consolas, monospace"
BLUE, BLUE_100, BLUE_600 = "#0a84ff", "#e6f1ff", "#0066d6"
GREEN, ORANGE, RED, PURPLE = "#22a06b", "#e8900c", "#e5484d", "#8e5cf7"
INK, MUTED, GRID, BORDER, GHOST = "#1f2937", "#6b7280", "#f1f3f5", "#e5e7eb", "#c7ccd4"
RAMP5 = ["#e6f1ff", "#b3d6ff", "#73b3ff", "#3393ff", "#0a6fdc"]   # quantile 5-step blue ramp (low → high)
ZERO = "#eef0f3"
VERDICT_COLOUR = {"seed": BLUE, "interesting": GREEN, "not_interesting": "#9ca3af", "artifact": RED, "unsure": ORANGE}
SYMBOL_PALETTE = ["#dfe3e8", "#9db9e8", ORANGE, "#2f5fb3", "#8b2c1f", "#73b3ff", "#f5c27a", "#5856D6", "#E85AAD", "#30B0C7"]


def hours_formatter(span_h: float | None = None):
    """Ticks in hours since recording start (spec §0 canon) with span-adaptive decimals; spans
    of ≤ 15 min fall back to absolute seconds, as A does."""
    return CustomJSTickFormatter(code="""
        const span = Math.abs(ticks[ticks.length-1] - ticks[0]) || 1;
        if (span * 3600 <= 900 && ticks.length > 1) { return (tick*3600).toFixed(span*3600 < 60 ? 1 : 0) + ' s'; }
        const d = span >= 50 ? 0 : span >= 5 ? 1 : span >= 0.5 ? 2 : span >= 0.05 ? 3 : 4;
        return tick.toFixed(d) + ' h';
    """)


def mv_formatter(unit: str = "mV"):
    # a Bokeh model belongs to ONE document: formatters cannot be module-level singletons across sessions
    return CustomJSTickFormatter(code="""
    const span = Math.abs(ticks[ticks.length-1] - ticks[0]) || 1;
    const d = span >= 1 ? 2 : span >= 0.1 ? 3 : span >= 0.01 ? 4 : 5;
    return (tick >= 0 ? '+' : '') + tick.toFixed(d) + UNIT;
""".replace("UNIT", repr(" " + unit if unit else "")))


def style(fig, *, x_axis=True, y_axis=True, grid=True):
    fig.background_fill_color = "#ffffff"
    fig.border_fill_color = "#ffffff"
    fig.outline_line_color = BORDER
    for ax in fig.axis:
        ax.major_label_text_font = MONO
        ax.major_label_text_font_size = "10px"
        ax.major_label_text_color = MUTED
        ax.axis_line_color = None
        ax.major_tick_line_color = BORDER
        ax.minor_tick_line_color = None
        ax.axis_label_text_font = MONO
        ax.axis_label_text_font_size = "10px"
        ax.axis_label_text_color = MUTED
        ax.axis_label_text_font_style = "normal"
    fig.xaxis.visible = x_axis
    fig.yaxis.visible = y_axis
    fig.xgrid.grid_line_color = GRID if grid else None
    fig.ygrid.grid_line_color = GRID if grid else None
    fig.toolbar.logo = None
    return fig


def base_figure(height: int, x_range=None, y_range=None, *, tools: str = "", toolbar: bool = False,
                x_axis=True, y_axis=True, grid=True, width: int | None = None, **kw):
    if width is None:
        kw["sizing_mode"] = "stretch_width"
    else:
        kw["width"] = width
    f = figure(height=height, x_range=x_range if x_range is not None else Range1d(0, 1),
               y_range=y_range if y_range is not None else Range1d(0, 1), tools=tools,
               toolbar_location="above" if toolbar else None, output_backend="canvas", **kw)
    style(f, x_axis=x_axis, y_axis=y_axis, grid=grid)
    f.min_border_left, f.min_border_right, f.min_border_top, f.min_border_bottom = 8, 8, 4, 4
    return f


def time_axis(fig, span_h: float | None = None):
    fig.xaxis.formatter = hours_formatter(span_h)
    return fig


def mv_axis(fig, unit: str = "mV"):
    fig.yaxis.formatter = mv_formatter(unit)
    fig.yaxis.major_label_text_font_size = "9.5px"
    return fig


def padded(lo, hi, frac=0.08, top_extra=0.0):
    if lo is None or hi is None or not np.isfinite(lo) or not np.isfinite(hi):
        return -1.0, 1.0
    if hi <= lo:
        pad = abs(lo) * 0.01 or 1e-3
        return lo - pad, hi + pad
    pad = (hi - lo) * frac
    return lo - pad, hi + pad + (hi - lo) * top_extra


def linked_crosshair(figs, span: Span | None = None):
    """Bokeh ≥ 3.1 idiom: one ``Span`` overlay shared by a CrosshairTool on every row, so hovering
    any row draws the same vertical line on all of them (the shared hover line)."""
    span = span or Span(dimension="height", line_color="#9ca3af", line_width=1, line_dash="dashed")
    for f in figs:
        f.add_tools(CrosshairTool(overlay=span, dimensions="height"))
    return span


def env_xy(env: dict):
    """Payload envelope → (hours, values) numpy arrays with NaN for JSON nulls."""
    t = np.asarray(env.get("t") or [], dtype=float) / 3600.0
    v = np.asarray([np.nan if a is None else a for a in (env.get("v") or [])], dtype=float)
    return t, v


def quantile_colours(values: np.ndarray) -> list[str]:
    """Quantile 5-step blue ramp over the non-zero cells; zero stays grey."""
    vals = np.asarray(values, dtype=float)
    out = [ZERO] * len(vals)
    nz = vals[vals > 0]
    if nz.size == 0:
        return out
    edges = np.quantile(nz, [0.2, 0.4, 0.6, 0.8])
    for i, v in enumerate(vals):
        if v > 0:
            out[i] = RAMP5[int(np.searchsorted(edges, v, side="left"))]
    return out
