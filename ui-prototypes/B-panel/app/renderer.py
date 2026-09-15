"""THE single dispatch seam over the seven interchange payload types (the Python twin of A's
``client/src/analyse/Renderer.tsx``): ``render(payload, x_range, height, ghost)`` → a Panel viewable.

Every time-aligned renderer draws into the chain's ONE shared ``Range1d`` (hours since recording
start), hides its own axes (the chain footer carries the one shared axis) and writes its value range
as in-plot mono labels, so every row has the same borders and the rows line up pixel for pixel. The
ghost (the previous Signal) sits on its own ``extra_y_range`` — ghosted, never normalised into the
output's scale. Encoding images are not time-aligned and get their own x range, which they say.

``RENDER_INFO`` is filled per call (type, glyph row counts) so the smoke test can assert what was drawn."""
from __future__ import annotations

import base64
import html

import numpy as np
import panel as pn
from bokeh.core.properties import value
from bokeh.models import ColumnDataSource, HoverTool, Label, LinearAxis, Range1d, Span

from . import charts as C

esc = html.escape
LEFT_BORDER = 10


def _fig(height, x_range, y_lo, y_hi, *, pad=0.1):
    lo, hi = C.padded(y_lo, y_hi, pad)
    f = C.base_figure(height=height, x_range=x_range, y_range=Range1d(lo, hi), x_axis=False, y_axis=False, grid=False)
    f.min_border_left = f.min_border_right = LEFT_BORDER
    f.min_border_top = f.min_border_bottom = 2
    f.outline_line_color = C.BORDER
    return f


def _range_labels(f, lo, hi, unit="mV"):
    def fmt(v):
        if v is None or not np.isfinite(v):
            return "–"
        span = abs(hi - lo) if (hi is not None and lo is not None) else 1
        d = 2 if span >= 1 else 3 if span >= 0.1 else 4 if span >= 0.01 else 5
        return f"{v:+.{d}f} {unit}".strip()
    f.add_layout(Label(x=4, y=0, x_units="screen", y_units="screen", y_offset=height_top(f), text=fmt(hi), text_font=C.MONO,
                       text_font_size="9.5px", text_color=C.MUTED, background_fill_color="white", background_fill_alpha=0.7))
    f.add_layout(Label(x=4, y=3, x_units="screen", y_units="screen", text=fmt(lo), text_font=C.MONO, text_font_size="9.5px",
                       text_color=C.MUTED, background_fill_color="white", background_fill_alpha=0.7))


def height_top(f):
    return max(0, int(f.height) - 18)


def _note(f, text, x=None, color=None, align="right"):
    f.add_layout(Label(x=x if x is not None else 8, y=3, x_units="screen", y_units="screen", text=text, text_font=C.MONO,
                       text_font_size="9.5px", text_color=color or C.MUTED, text_align="left"))


def _ghost(f, ghost: dict | None):
    if not ghost or not ghost.get("envelope"):
        return 0
    gx, gy = C.env_xy(ghost["envelope"])
    fin = gy[np.isfinite(gy)]
    if not fin.size:
        return 0
    lo, hi = C.padded(float(fin.min()), float(fin.max()), 0.1)
    f.extra_y_ranges = {"ghost": Range1d(lo, hi)}
    f.line(gx, gy, y_range_name="ghost", line_color=C.GHOST, line_width=1)
    return len(gx)


# ------------------------------------------------------------------------------ per type --

def _signal(p, x_range, height, ghost, info):
    x, y = C.env_xy(p["envelope"])
    lo, hi = (p.get("y_range") or [np.nanmin(y), np.nanmax(y)])
    f = _fig(height, x_range, lo, hi)
    info["ghost_points"] = _ghost(f, ghost)
    f.line(x, y, line_color=C.BLUE if ghost else C.INK, line_width=1)
    _range_labels(f, lo, hi)
    if ghost:
        f.add_layout(Label(x=x_range.end, y=3, y_units="screen", text="input ghosted · own scale", text_font=C.MONO,
                           text_font_size="9.5px", text_color=C.MUTED, text_align="right", x_offset=-6))
    info["points"] = len(x)
    return pn.pane.Bokeh(f, sizing_mode="stretch_width", margin=0)


def _scores(p, x_range, height, ghost, info):
    x, y = C.env_xy(p["envelope"])
    lo, hi = (p.get("value_range") or [0.0, 1.0])
    f = _fig(height, x_range, lo, hi, pad=0.12)
    f.line(x, y, line_color=C.BLUE, line_width=1)
    marks = 0
    for k, t in enumerate(p.get("top", {}).get("low", [])):
        f.add_layout(Span(location=t["t_s"] / 3600, dimension="height", line_color=C.GREEN, line_width=1))
        f.add_layout(Label(x=t["t_s"] / 3600, y=height - 16, y_units="screen", text=f"M{k + 1}", text_font=C.MONO,
                           text_font_size="9.5px", text_color=C.GREEN, x_offset=3))
        marks += 1
    for t in p.get("top", {}).get("high", []):
        f.add_layout(Span(location=t["t_s"] / 3600, dimension="height", line_color=C.RED, line_width=1))
        f.add_layout(Label(x=t["t_s"] / 3600, y=height - 16, y_units="screen", text="D1", text_font=C.MONO,
                           text_font_size="9.5px", text_color=C.RED, x_offset=3))
        marks += 1
    _range_labels(f, lo, hi, unit="")
    f.add_layout(Label(x=x_range.end, x_offset=-6, y=3, y_units="screen", text=f"z-norm distance · NaN tail {p.get('nan_tail', 0)} · ▏motif ▏discord",
                       text_font=C.MONO, text_font_size="9.5px", text_color=C.MUTED, text_align="right"))
    f.add_tools(HoverTool(tooltips=[("t", "@x{0.0000} h"), ("score", "@y{0.000}")], mode="vline", renderers=[f.renderers[0]]))
    info["points"], info["marks"] = len(x), marks
    return pn.pane.Bokeh(f, sizing_mode="stretch_width", margin=0)


def _spanset(p, x_range, height, ghost, info):
    f = _fig(height, x_range, 0.0, 1.0, pad=0.0)
    info["ghost_points"] = _ghost(f, ghost)
    n = int(p.get("n", 0))
    starts = [s / 3600 for s in p.get("start_s", [])]
    ends = [e / 3600 for e in p.get("end_s", [])]
    if starts:
        f.quad(left=starts, right=ends, bottom=0, top=1, fill_color=C.BLUE, fill_alpha=0.22, line_color=C.BLUE, line_alpha=0.5)
        f.quad(left=starts, right=ends, bottom=0.9, top=1.0, fill_color=C.BLUE, line_color=None)
    else:
        f.add_layout(Label(x=0, y=height / 2 - 6, x_units="screen", y_units="screen", text="0 spans — nothing crossed the threshold",
                           text_font=C.MONO, text_font_size="11px", text_color=C.MUTED, x_offset=0))
    f.add_layout(Label(x=x_range.end, x_offset=-6, y=3, y_units="screen", text=f"{n} span{'s' if n != 1 else ''}" + (" · capped" if p.get("capped") else ""),
                       text_font=C.MONO, text_font_size="9.5px", text_color=C.MUTED, text_align="right"))
    info["bands"] = len(starts)
    return pn.pane.Bokeh(f, sizing_mode="stretch_width", margin=0)


def _encoding(p, x_range, height, ghost, info):
    kind = p.get("kind")
    if kind == "symbolic":
        syms = p.get("symbols") or []
        sps = p.get("seconds_per_symbol") or 1.0
        t0 = float(p.get("t0_s", 0.0))
        f = _fig(height, x_range, 0.0, 1.0, pad=0.0)
        xs = [(t0 + (k + 0.5) * sps) / 3600 for k in range(len(syms))]
        cols = [C.SYMBOL_PALETTE[int(s) % len(C.SYMBOL_PALETTE)] for s in syms]
        src = ColumnDataSource(dict(x=xs, color=cols, letter=list(p.get("letters") or "")[:len(xs)] or [""] * len(xs)))
        f.rect(x="x", y=0.5, width=sps / 3600 * 0.94, height=0.62, source=src, fill_color="color", line_color=None)
        if len(xs) <= 80:
            f.text(x="x", y=0.5, text="letter", source=src, text_align="center", text_baseline="middle",
                   text_font=value(C.MONO), text_font_size="10px", text_color="#ffffff")
        _note(f, f"{len(syms)} symbols · alphabet {p.get('alphabet_size')} · {sps:g} s per symbol")
        info["rects"] = len(xs)
        return pn.pane.Bokeh(f, sizing_mode="stretch_width", margin=0)
    if kind == "image" and p.get("pixels_b64"):
        h, w = p["display_shape"]
        ch = int(p.get("channels", 1))
        u8 = np.frombuffer(base64.b64decode(p["pixels_b64"]), dtype=np.uint8)
        img = u8.reshape(h, w, ch)[:, :, 0] if ch > 1 else u8.reshape(h, w)
        # blue ramp LUT → RGBA uint32 (the image is data, not a waveform; its own colour scale is labelled)
        lut = np.array([int(0xFF000000 | (int(255 - 245 * t) & 0xFF) << 16 | (int(255 - 145 * t) & 0xFF) << 8 | 255)
                        for t in np.linspace(0, 1, 256)], dtype=np.uint32)
        rgba = lut[img[::-1]]   # bokeh images origin bottom-left
        side = max(40, height - 8)
        f = C.base_figure(height=height, width=int(side * w / h) + 20, x_range=Range1d(0, w), y_range=Range1d(0, h),
                          x_axis=False, y_axis=False, grid=False)
        f.image_rgba(image=[rgba.view(np.uint8).reshape(h, w, 4)], x=0, y=0, dw=w, dh=h)
        info["image"] = [int(h), int(w)]
        cap = pn.pane.HTML(f'<div class="mono small muted" style="padding:8px">{esc(p.get("summary", ""))}<br>not time-aligned · '
                           f'value range {p.get("value_range")}</div>', width=260)
        return pn.Row(pn.pane.Bokeh(f, margin=0), cap, sizing_mode="stretch_width", margin=0)
    if p.get("series") is not None:
        ys = np.asarray([np.nan if v is None else v for v in p["series"]], dtype=float)
        fin = ys[np.isfinite(ys)]
        f = C.base_figure(height=height, x_range=Range1d(0, len(ys)), y_range=Range1d(*C.padded(float(fin.min()) if fin.size else 0, float(fin.max()) if fin.size else 1)),
                          x_axis=False, y_axis=False, grid=False)
        f.line(np.arange(len(ys)), ys, line_color=C.BLUE, line_width=1)
        _note(f, f"{len(ys)} log-frequency bins · not time-aligned")
        info["points"] = len(ys)
        return pn.pane.Bokeh(f, sizing_mode="stretch_width", margin=0)
    info["placeholder"] = True
    return pn.pane.HTML(f'<div class="waits" style="height:{height - 8}px">encoding · {esc(str(p.get("summary")))} · no renderer for this shape</div>',
                        sizing_mode="stretch_width", margin=0)


def _windowset(p, x_range, height, ghost, info):
    starts = [s / 3600 for s in p.get("starts_s", [])]
    L = float(p.get("length_s", 0)) / 3600
    f = _fig(height, x_range, 0.0, 1.0, pad=0.0)
    feats = p.get("features") or {}
    mat = feats.get("matrix")
    if mat and starts:
        m = np.asarray([[np.nan if c is None else c for c in row] for row in mat], dtype=float)   # windows × features
        rng = np.asarray([[a if a is not None else 0, b if b is not None else 1] for a, b in feats.get("col_range", [])], dtype=float)
        norm = (m - rng[:, 0]) / np.where((rng[:, 1] - rng[:, 0]) == 0, 1, rng[:, 1] - rng[:, 0])
        norm = np.nan_to_num(norm, nan=0.0).T   # features × windows
        x0, x1 = starts[0], starts[-1] + L
        f.image(image=[norm], x=x0, y=0.15, dw=x1 - x0, dh=0.85, palette=C.RAMP5, level="image")
        info["heatmap"] = list(norm.shape)
    f.segment(x0=starts, x1=starts, y0=0, y1=0.13, line_color=C.INK, line_width=1)
    _note(f, f"{p.get('n_windows')} windows · {p.get('length_s', 0):g} s each" + (f" · {feats.get('n_columns')} features (per-feature scaled)" if feats else ""))
    info["ticks"] = len(starts)
    return pn.pane.Bokeh(f, sizing_mode="stretch_width", margin=0)


def _grouping(p, x_range, height, ghost, info):
    strip = p.get("strip")
    labels = p.get("labels") or []
    if strip and labels:
        f = _fig(height, x_range, 0.0, 1.0, pad=0.0)
        L = strip["length_s"] / 3600
        xs = [s / 3600 + L / 2 for s in strip["starts_s"]]
        cols = [C.SYMBOL_PALETTE[(int(l) + 2) % len(C.SYMBOL_PALETTE)] for l in labels[:len(xs)]]
        f.rect(x=xs, y=0.5, width=L * 0.96, height=0.6, fill_color=cols, line_color=None)
        _note(f, " · ".join(f"class {c['id']}: {c['count']}" for c in p.get("clusters", [])) + " · class per window")
        info["rects"] = len(xs)
        return pn.pane.Bokeh(f, sizing_mode="stretch_width", margin=0)
    cl = p.get("clusters", [])
    f = C.base_figure(height=height, x_range=Range1d(0, max([c["count"] for c in cl] or [1]) * 1.1),
                      y_range=[str(c["id"]) for c in cl] or ["–"], x_axis=False, grid=False)
    f.hbar(y=[str(c["id"]) for c in cl], right=[c["count"] for c in cl], height=0.6, fill_color=C.BLUE, line_color=None)
    info["bars"] = len(cl)
    return pn.pane.Bokeh(f, sizing_mode="stretch_width", margin=0)


def _model(p, x_range, height, ghost, info):
    card = p.get("card", {})
    kv = "".join(f'<span class="k">{esc(k)}</span><span>{esc(str(v))[:120]}</span>' for k, v in card.items() if k != "feature_names")
    info["card_keys"] = len(card)
    return pn.pane.HTML(
        f'<div style="display:flex;gap:18px;padding:6px 10px;height:{height - 12}px;overflow:auto">'
        f'<div style="min-width:180px"><div class="card-title">Model</div><div style="font-size:16px;font-weight:600;margin-top:4px">{esc(p.get("summary", ""))}</div>'
        f'<div class="mono small muted" style="margin-top:4px">a model has no natural plot (PRD) · joblib {"present" if p.get("exists") else "missing"}'
        f'{" · " + str(round((p.get("size_bytes") or 0) / 1024)) + " KB" if p.get("size_bytes") else ""}</div></div>'
        f'<div class="kv">{kv}</div></div>', sizing_mode="stretch_width", margin=0)


_DISPATCH = {"signal": _signal, "scores": _scores, "spanset": _spanset, "encoding": _encoding,
             "windowset": _windowset, "grouping": _grouping, "model": _model}


def render(payload: dict, x_range, height: int = 110, ghost: dict | None = None, info: dict | None = None):
    """The one seam. ``payload["type"]`` ∈ the seven interchange types; a serialisation-error payload
    renders as an error card. Unknown types raise — loudly — rather than drawing nothing."""
    info = info if info is not None else {}
    if payload.get("error"):
        info["type"] = "error"
        return pn.pane.HTML(f'<div class="error-card" data-testid="payload-error"><h3>render payload failed</h3>'
                            f'<div class="mono">{esc(payload["error"])}</div></div>', sizing_mode="stretch_width", margin=0)
    kind = payload.get("type")
    fn = _DISPATCH.get(kind)
    if fn is None:
        raise ValueError(f"no renderer for payload type {kind!r}; known: {sorted(_DISPATCH)}")
    info["type"] = kind
    return fn(payload, x_range, height, ghost, info)
