"""Explore › Signal (frame explore-2-signal): three tiers on one time axis.

Tier 1 CHANNEL — the full-channel peak-preserving envelope with a Bokeh ``RangeTool`` linked to tier
2's x_range (the RangeTool overlay IS the frame's blue selected-span box; dragging it or its edges
moves the span), plus a verdict coverage ribbon and a detection-density ribbon.
Tier 2 SPAN — wheel zoom + pan (x only). Every x_range change is coalesced (~60 ms, leading +
trailing) and **re-fetches the envelope for that viewport** through ``corpus.window``; tinted bands
come from ``corpus.spans`` per viewport. Per-fetch timings are recorded server-side and the browser
closes the loop: a CustomJS stamps when each range left the browser and when its data came back,
and writes the round trip into a hidden Bokeh ``Div`` whose change syncs back to Python.
Tier 3 MOTIF — the selected span ±20 s with ONSET/END lines.
"""
from __future__ import annotations

import html
import json
import logging
import time

import numpy as np
import panel as pn
from bokeh.core.properties import value
from bokeh.models import (BoxAnnotation, ColumnDataSource, CustomJS, CustomJSTickFormatter, Div, FixedTicker, Label,
                          PanTool, Range1d, RangeTool, Span, TapTool, WheelZoomTool)

from server import corpus

from . import charts as C
from . import debug

log = logging.getLogger("protoB.signal")
esc = html.escape
BAND_CAP = 600       # bands drawn per viewport; beyond this the viewport shows caps only (and says so)
MIN_SPAN_S = 30.0    # the tier-2 viewport never collapses below this (Range1d.min_interval is ignored by Bokeh 3.9's wheel zoom)


def _fmt_h(h: float, span_h: float) -> str:
    d = 0 if span_h >= 50 else 1 if span_h >= 5 else 2 if span_h >= 0.5 else 3
    return f"{h:.{d}f}"


def signal_page(ctx, channel_id: int):
    from .explore import locked_card
    conn = corpus.connect(ctx.db_path)
    try:
        rec = corpus.recording_row(conn, channel_id)
        if rec is None:
            return pn.Column(ctx.header("Explore", "Signal", f"no channel {channel_id}"),
                             pn.pane.HTML(f'<div class="pb-page"><div class="error-card"><h3>No recording id {channel_id}</h3></div></div>'),
                             sizing_mode="stretch_width", margin=0)
        if rec["held_out"]:
            rec["held_out_reason"] = (f"{rec['source_file']} is held out (spec §0 D6 / Working.config.HELD_OUT_RECORDING_FILE); "
                                      "this page refuses it and never loads its signal")
            return pn.Column(ctx.header("Explore", "Signal", f"{rec['name']} · held out"), locked_card(rec),
                             sizing_mode="stretch_width", margin=0)
        summary = corpus.channel_summary(conn, channel_id)
        fs, n = float(rec["fs"]), int(rec["n_samples"])
        dur_s = n / fs
        dur_h = dur_s / 3600.0
        ribbons = corpus.ribbons(conn, channel_id, fs, n)
        t = time.perf_counter()
        overview = corpus.window(conn, rec, 0.0, dur_s, 1300)
        overview_ms = (time.perf_counter() - t) * 1e3
        all_spans = corpus.spans(conn, channel_id, 0.0, dur_s, fs)
    finally:
        conn.close()
    name = rec["name"]
    ylo, yhi = corpus.y_range(rec)

    motifs = sorted([dict(kind="annotation", **a) for a in all_spans["annotations"]] +
                    [dict(kind="detection", **d) for d in all_spans["detections"]], key=lambda m: (m["start_s"], m["kind"]))

    views = ctx.explore.setdefault("views", {})
    v0 = views.get(channel_id) or ((276.4, 278.4) if dur_h > 278.4 else (0.0, min(2.0, dur_h)))
    state = {"sel": None, "seq": 0, "pending": False, "busy": False, "last": None, "stats": [], "in_view": 0}

    doc = pn.state.curdoc

    # ------------------------------------------------------------------ header + breadcrumb --
    header = ctx.header("Explore", "Signal", f"{name} · {summary['annotations']:,} annotations · {summary['detections']:,} detections")
    back_btn = pn.widgets.Button(name="‹ back to corpus", css_classes=["btn-link"], margin=(4, 0), width=140)
    back_btn.on_click(ctx.guard("‹ back to corpus", lambda e: ctx.navigate("explore/corpus")))
    mode = pn.widgets.RadioButtonGroup(options=["Signal", "Cross-channel"], value="Signal", css_classes=["seg"], disabled=False, margin=(0, 8))
    mode.param.watch(ctx.guard("mode", lambda e: (setattr(mode, "value", "Signal"), ctx.toast("Cross-channel view is outside this slice")) if e.new != "Signal" else None), "value")
    crumbs = pn.Row(
        pn.pane.HTML(f'<div class="mono small" style="padding-top:8px"><a href="#explore/corpus" style="color:var(--muted);text-decoration:none">Corpus</a>'
                     f' <span class="muted">›</span> <span class="muted">{esc(rec["source_file"])}</span> <span class="muted">›</span> <b>{esc(name)}</b></div>', width=380),
        mode,
        pn.pane.HTML(f'<span class="chip">detections {summary["detection_runs"]} runs</span> <span class="chip">display raw</span>', margin=(4, 8)),
        pn.layout.HSpacer(), back_btn, sizing_mode="stretch_width", margin=(8, 20, 0, 20))

    # ------------------------------------------------------------------ tier 2 (span viewport) --
    span_x = Range1d(start=v0[0], end=v0[1], bounds=(0, dur_h), min_interval=30 / 3600.0)
    span_y = Range1d(ylo, yhi)
    env_src = ColumnDataSource(dict(x=[], y=[]))
    ann_src = ColumnDataSource(dict(left=[], right=[], bottom=[], top=[], cap_b=[], cap_t=[], color=[], idx=[]))
    det_src = ColumnDataSource(dict(left=[], right=[], bottom=[], top=[], cap_b=[], cap_t=[], idx=[]))
    sel_src = ColumnDataSource(dict(left=[], right=[], bottom=[], top=[], cap_b=[], cap_t=[]))
    meta_src = ColumnDataSource(dict(seq=[], t0=[], t1=[], px=[], n_points=[], decimate_ms=[], server_ms=[]), name="zoom_meta")

    fspan = C.base_figure(height=250, x_range=span_x, y_range=span_y, grid=True)
    C.time_axis(fspan)
    C.mv_axis(fspan)
    fspan.yaxis.ticker.desired_num_ticks = 3
    wheel = WheelZoomTool(dimensions="width", maintain_focus=False)
    pan = PanTool(dimensions="width")
    fspan.add_tools(wheel, pan)
    fspan.toolbar.active_scroll = wheel
    fspan.toolbar.active_drag = pan
    det_r = fspan.quad(left="left", right="right", bottom="bottom", top="top", source=det_src, fill_color=C.BLUE, fill_alpha=0.16,
                       line_color=None, nonselection_fill_alpha=0.16, selection_fill_alpha=0.16)
    ann_r = fspan.quad(left="left", right="right", bottom="bottom", top="top", source=ann_src, fill_color="color", fill_alpha=0.16,
                       line_color=None, nonselection_fill_alpha=0.16, selection_fill_alpha=0.16)
    fspan.quad(left="left", right="right", bottom="cap_b", top="cap_t", source=det_src, fill_color=C.BLUE, line_color=None, fill_alpha=0.9)
    fspan.quad(left="left", right="right", bottom="cap_b", top="cap_t", source=ann_src, fill_color="color", line_color=None, fill_alpha=0.9)
    fspan.quad(left="left", right="right", bottom="bottom", top="top", source=sel_src, fill_color=C.ORANGE, fill_alpha=0.18,
               line_color=C.ORANGE, line_width=1.2)
    fspan.quad(left="left", right="right", bottom="cap_b", top="cap_t", source=sel_src, fill_color=C.ORANGE, line_color=None)
    fspan.line("x", "y", source=env_src, line_color=C.INK, line_width=1)
    fspan.add_tools(TapTool(renderers=[det_r, ann_r]))
    capped_label = Label(x=8, y=8, x_units="screen", y_units="screen", text="", text_font=C.MONO, text_font_size="10px",
                         text_color=C.MUTED)
    fspan.add_layout(capped_label)

    # browser-side round-trip stamp (Bokeh model callbacks, no HTTP): range out → data back
    rt_div = Div(text="", visible=False)
    stat_div = Div(text="", styles={"font-family": "Geist Mono, monospace", "font-size": "11px", "color": "#6b7280"})
    # FRICTION (silent): a ColumnDataSource that no renderer uses is NOT serialised into the browser document, so
    # Python writes to it vanish and its js_on_change never fires — no error anywhere. Referencing it from a
    # callback that IS reachable (this one, attached to the x_range) is what pulls it into the document.
    # FIX (critique r1 P1): Range1d(min_interval=…) is NOT honoured by WheelZoomTool in Bokeh 3.9 — the viewport
    # collapsed to 0 h and painted blank. Clamp in the browser first (no blank frame), and again in Python (fetch).
    # FIX (critique r1 P2): round trips are matched through a per-request sequence queue; a matched request and every
    # older one it superseded are dropped, so a repeated viewport can never be timed against a stale stamp.
    js_range = CustomJS(args=dict(r=span_x, meta=meta_src, minw=MIN_SPAN_S / 3600.0, dur=dur_h), code="""
        if (r.end - r.start < minw - 1e-9) {
            if (r.__clamping) return;
            r.__clamping = true;
            const c = (r.start + r.end) / 2;
            let a = c - minw / 2, b = c + minw / 2;
            if (a < 0) { a = 0; b = minw; }
            if (b > dur) { b = dur; a = dur - minw; }
            r.setv({start: a, end: b});
            r.__clamping = false;
            return;
        }
        const k = r.start.toFixed(5) + '|' + r.end.toFixed(5);
        const q = (window.__bReqQ = window.__bReqQ || []);
        window.__bSeq = (window.__bSeq || 0) + 1;
        const last = q.length ? q[q.length - 1] : null;
        if (!last || last.k !== k) q.push({seq: window.__bSeq, k: k, t: performance.now()});
    """)
    span_x.js_on_change("start", js_range)
    span_x.js_on_change("end", js_range)
    meta_src.js_on_change("data", CustomJS(args=dict(meta=meta_src, rt=rt_div, stat=stat_div), code="""
        const d = meta.data; const i = d.seq.length - 1; if (i < 0) return;
        const k = d.t0[i].toFixed(5) + '|' + d.t1[i].toFixed(5);
        const q = (window.__bReqQ = window.__bReqQ || []);
        const now = performance.now();
        let rtt = null, req = null;
        for (let j = q.length - 1; j >= 0; j--) { if (q[j].k === k) { req = q[j]; break; } }
        if (req) { rtt = now - req.t; window.__bReqQ = q.filter(e => e.seq > req.seq); }
        const rec = {seq: d.seq[i], req_seq: req ? req.seq : null, t0_h: d.t0[i], t1_h: d.t1[i], px: d.px[i], n_points: d.n_points[i],
                     decimate_ms: d.decimate_ms[i], server_ms: d.server_ms[i], round_trip_ms: rtt};
        (window.__zoomStats = window.__zoomStats || []).push(rec);
        const tip = d.n_points[i].toLocaleString() + ' pts · server ' + d.decimate_ms[i].toFixed(1) + ' ms decimate / ' +
                    d.server_ms[i].toFixed(1) + ' ms total' + (rtt === null ? '' : ' · round trip ' + rtt.toFixed(0) + ' ms');
        stat.text = '<span title="' + tip + '" style="cursor:help" data-testid="zoom-timing">ⓘ timing</span>';
        rt.text = JSON.stringify(rec);
    """))

    def on_rt(attr, old, new):
        try:
            rec_ = json.loads(new)
        except Exception:
            return
        debug.append("zoom_stats", rec_, cap=400)

    rt_div.on_change("text", ctx.guard("zoom timing sync", on_rt))

    # ------------------------------------------------------------------ fetch per viewport --
    fetch_err = pn.Column(sizing_mode="stretch_width", margin=0)

    def clamp_view() -> bool:
        """Python side of the minimum-span clamp; True when it had to move the range (a new fetch follows)."""
        a, b = float(span_x.start), float(span_x.end)
        minw = MIN_SPAN_S / 3600.0
        if b - a >= minw - 1e-9:
            return False
        c = (a + b) / 2
        a, b = c - minw / 2, c + minw / 2
        if a < 0:
            a, b = 0.0, minw
        if b > dur_h:
            a, b = dur_h - minw, dur_h
        span_x.update(start=a, end=b)
        return True

    def fetch():
        state["pending"] = False
        try:     # critique r1 P1: a failing viewport fetch shows a red card in the span tier
            if clamp_view():
                return
            _fetch()
            if fetch_err.objects:
                fetch_err.objects = []
        except Exception as exc:
            from .main import error_card
            fetch_err.objects = [error_card("span viewport fetch", exc, testid="fetch-error", margin=(4, 14))]

    def _fetch():
        state["window_until"] = time.perf_counter() + 0.06
        t0h, t1h = float(span_x.start), float(span_x.end)
        if t1h <= t0h:
            return
        tt = time.perf_counter()
        try:
            px = int(fspan.inner_width) or 1250      # synced back from the browser once laid out
        except Exception:
            px = 1250                                # UnsetValueError before the first layout
        conn = corpus.connect(ctx.db_path)
        try:
            w = corpus.window(conn, rec, t0h * 3600.0, t1h * 3600.0, px)
            sp = corpus.spans(conn, channel_id, t0h * 3600.0, t1h * 3600.0, fs, cap=BAND_CAP)
        finally:
            conn.close()
        env = w["envelope"]
        x, y = C.env_xy(env)
        fin = y[np.isfinite(y)]
        lo, hi = (float(fin.min()), float(fin.max())) if fin.size else (ylo, yhi)
        rng = (hi - lo) or abs(hi) * 0.01 or 1e-3
        band_b, band_t = lo - rng * 0.06, hi + rng * 0.06
        cap_b, cap_t = hi + rng * 0.12, hi + rng * 0.2
        span_y.start, span_y.end = band_b, cap_t + rng * 0.02
        env_src.data = dict(x=x, y=y)
        a = sp["annotations"]
        d = sp["detections"]
        idx_of = {(m["kind"], m["id"]): i for i, m in enumerate(motifs)}
        ann_src.data = dict(left=[s["start_s"] / 3600 for s in a], right=[s["end_s"] / 3600 for s in a], bottom=[band_b] * len(a),
                            top=[hi + rng * 0.1] * len(a), cap_b=[cap_b] * len(a), cap_t=[cap_t] * len(a),
                            color=[C.RED if s["verdict"] == "artifact" else C.GREEN for s in a],
                            idx=[idx_of.get(("annotation", s["id"]), -1) for s in a])
        det_src.data = dict(left=[s["start_s"] / 3600 for s in d], right=[s["end_s"] / 3600 for s in d], bottom=[band_b] * len(d),
                            top=[hi + rng * 0.1] * len(d), cap_b=[cap_b] * len(d), cap_t=[cap_t] * len(d),
                            idx=[idx_of.get(("detection", s["id"]), -1) for s in d])
        state["band"] = (band_b, hi + rng * 0.1, cap_b, cap_t)
        state["in_view"] = len(a) + len(d)
        capped_label.text = ("band cap reached · showing the first %d of each kind" % BAND_CAP) if (sp["annotations_capped"] or sp["detections_capped"]) else ""
        draw_selection()
        server_ms = (time.perf_counter() - tt) * 1e3
        state["seq"] += 1
        # full replacement, not .stream(): a streamed patch does not fire js_on_change("data") in BokehJS
        meta_src.data = dict(seq=[state["seq"]], t0=[t0h], t1=[t1h], px=[px], n_points=[int(env["n_points"])],
                             decimate_ms=[float(w["decimate_ms"])], server_ms=[server_ms])
        views[channel_id] = (t0h, t1h)
        span_title.object = (f'<span class="card-title">Span</span><span class="mono small" style="margin-left:14px">'
                             f'{_fmt_h(t0h, t1h - t0h)} – {_fmt_h(t1h, t1h - t0h)} h · '
                             f'{(f"{(t1h - t0h) * 3600:.0f} s" if (t1h - t0h) * 3600 < 600 else f"{(t1h - t0h):.2f} h")}</span>')
        update_actions()
        update_nav()

    def schedule(attr, old, new):
        # leading + trailing throttle (~60 ms): a change outside the window fetches on the next tick; changes
        # inside it collapse into ONE trailing fetch of whatever the range is when the window closes
        now = time.perf_counter()
        if state["pending"]:
            return
        if now >= state.get("window_until", 0.0):
            state["pending"] = True
            state["window_until"] = now + 0.06
            doc.add_next_tick_callback(fetch)
        else:
            state["pending"] = True
            doc.add_timeout_callback(fetch, max(1, int((state["window_until"] - now) * 1000)))

    schedule_g = ctx.guard("span viewport", schedule)
    span_x.on_change("start", schedule_g)
    span_x.on_change("end", schedule_g)

    # ------------------------------------------------------------------ tier 1 (channel) --
    fover = C.base_figure(height=92, x_range=Range1d(0, dur_h), y_range=Range1d(*C.padded(ylo, yhi, 0.05)), grid=False,
                          x_axis=False, y_axis=False)
    ox, oy = C.env_xy(overview["envelope"])
    fover.line(ox, oy, line_color=C.INK, line_width=1)
    rtool = RangeTool(x_range=span_x)
    rtool.overlay.fill_color = C.BLUE
    rtool.overlay.fill_alpha = 0.16
    rtool.overlay.line_color = C.BLUE
    rtool.overlay.line_width = 1.5
    fover.add_tools(rtool)
    # (Bokeh 3.9: RangeTool is no longer a GestureTool — it cannot be set as toolbar.active_multi; it is always live)

    cov_colours = [C.VERDICT_COLOUR.get(v) if v else None for v in ribbons["coverage"]]
    bw = dur_h / ribbons["buckets"]
    cx = [(i + 0.5) * bw for i, c in enumerate(cov_colours) if c]
    fcov = C.base_figure(height=16, x_range=fover.x_range, y_range=Range1d(0, 1), grid=False, x_axis=False, y_axis=False)
    fcov.outline_line_color = None
    fcov.rect(x=cx, y=[0.5] * len(cx), width=bw * 0.92, height=0.7, fill_color=[c for c in cov_colours if c], line_color=None)
    dens = np.asarray(ribbons["detection_density"], dtype=float)
    fden = C.base_figure(height=40, x_range=fover.x_range, y_range=Range1d(0, 1.05), grid=False, y_axis=False)
    fden.outline_line_color = None
    if dens.max() > 0:
        fden.vbar(x=[(i + 0.5) * bw for i in range(len(dens))], top=list(dens / dens.max()), width=bw * 0.8, fill_color=C.BLUE,
                  line_color=None, fill_alpha=0.85)
    else:
        fden.add_layout(Label(x=4, y=2, x_units="screen", y_units="screen", text="no detections on this channel",
                              text_font=C.MONO, text_font_size="10px", text_color=C.MUTED))
    fden.xaxis.ticker = FixedTicker(ticks=[0, 120, 240, 360, 480, 600, round(dur_h)] if dur_h > 400 else list(np.linspace(0, dur_h, 7).round(1)))
    fden.xaxis.formatter = CustomJSTickFormatter(code="return tick.toFixed(0) + ' h'")

    tier1 = pn.Column(
        pn.pane.HTML(f'<div style="display:flex;justify-content:space-between"><div><span class="card-title">Channel</span>'
                     f'<span class="mono small" style="margin-left:14px">0 – {dur_h:.0f} h</span></div>'
                     f'<span class="mono small muted" data-testid="overview-stat" style="cursor:help" '
                     f'title="{overview["envelope"]["n_points"]:,} pts · full channel · server {overview_ms:.1f} ms">ⓘ timing</span></div>',
                     sizing_mode="stretch_width", margin=(10, 14, 0, 14)),
        pn.pane.Bokeh(_stack([fover, fcov, fden]), sizing_mode="stretch_width", margin=(2, 8, 4, 8)),
        pn.pane.HTML('<div class="mono small muted" style="margin:0 14px 8px">drag the blue box or its edges to choose the span below · '
                     'ribbons: human verdict per bucket, then machine detection density</div>', sizing_mode="stretch_width"),
        sizing_mode="stretch_width", css_classes=["card"], margin=(8, 20, 4, 20))

    # ------------------------------------------------------------------ tier 2 controls --
    span_title = pn.pane.HTML("", margin=(10, 14, 0, 14), width=420)
    nav_prev = pn.widgets.Button(name="‹", width=28, css_classes=["btn"], margin=(4, 2))
    nav_next = pn.widgets.Button(name="›", width=28, css_classes=["btn"], margin=(4, 2))
    nav_label = pn.pane.HTML("", margin=(10, 4))
    zoom_out = pn.widgets.Button(name="−", width=30, css_classes=["btn"], margin=(4, 2))
    zoom_in = pn.widgets.Button(name="+", width=30, css_classes=["btn"], margin=(4, 2))
    zoom_fit = pn.widgets.Button(name="fit", width=40, css_classes=["btn"], margin=(4, 2), description="show the whole channel")

    def set_view(a, b):
        a, b = max(0.0, a), min(dur_h, b)
        if b - a < 30 / 3600:
            b = a + 30 / 3600
        span_x.update(start=a, end=b)

    def zoom(f):
        c, w = (span_x.start + span_x.end) / 2, (span_x.end - span_x.start) * f
        set_view(c - w / 2, c + w / 2)
    zoom_in.on_click(ctx.guard("zoom in", lambda e: zoom(0.5)))
    zoom_out.on_click(ctx.guard("zoom out", lambda e: zoom(2.0)))
    zoom_fit.on_click(ctx.guard("fit", lambda e: set_view(0.0, dur_h)))

    def select(i, recentre=False):
        if not motifs:
            return
        i = int(i) % len(motifs)
        state["sel"] = i
        m = motifs[i]
        if recentre:
            w = span_x.end - span_x.start
            mid = (m["start_s"] + m["end_s"]) / 7200.0
            mw = (m["end_s"] - m["start_s"]) / 3600.0
            if mw * 1.5 > w:
                w = mw * 3
            set_view(mid - w / 2, mid + w / 2)
        draw_selection()
        update_nav()
        draw_motif()

    nav_prev.on_click(ctx.guard("previous motif", lambda e: select((state["sel"] if state["sel"] is not None else 0) - 1, recentre=True)))
    nav_next.on_click(ctx.guard("next motif", lambda e: select((state["sel"] + 1) if state["sel"] is not None else first_in_view(), recentre=True)))

    def first_in_view():
        a, b = span_x.start * 3600, span_x.end * 3600
        for i, m in enumerate(motifs):
            if m["end_s"] > a and m["start_s"] < b:
                return i
        return 0

    def on_tap(src):
        def cb(attr, old, new):
            if not new:
                return
            i = src.data["idx"][new[0]]
            src.selected.indices = []
            if i >= 0:
                select(i)
        return cb
    ann_src.selected.on_change("indices", ctx.guard("select motif", on_tap(ann_src)))
    det_src.selected.on_change("indices", ctx.guard("select motif", on_tap(det_src)))

    def draw_selection():
        i = state["sel"]
        if i is None or "band" not in state:
            sel_src.data = dict(left=[], right=[], bottom=[], top=[], cap_b=[], cap_t=[])
            return
        m = motifs[i]
        bb, bt, cb_, ct = state["band"]
        sel_src.data = dict(left=[m["start_s"] / 3600], right=[m["end_s"] / 3600], bottom=[bb], top=[bt], cap_b=[cb_], cap_t=[ct])

    def update_nav():
        cur = "–" if state["sel"] is None else f'{state["sel"] + 1:,}'
        nav_label.object = f'<span class="mono small" data-testid="motif-nav">{cur} / {len(motifs):,}</span>'

    legend = pn.pane.HTML(
        f'<div class="mono small muted" style="display:flex;gap:16px;align-items:center;margin:0 14px 10px">'
        f'<span><span class="legend-dot" style="background:{C.BLUE}"></span>detected</span>'
        f'<span><span class="legend-dot" style="background:{C.GREEN}"></span>annotated</span>'
        f'<span><span class="legend-dot" style="background:{C.ORANGE}"></span>selected</span>'
        f'<span><span class="legend-dot" style="background:{C.RED}"></span>artifact</span>'
        f'<span style="margin-left:12px">wheel to zoom · drag to pan · click a band to select that motif · envelope re-fetched per viewport · real mV</span></div>',
        sizing_mode="stretch_width")
    tier2 = pn.Column(
        pn.Row(span_title, pn.pane.Bokeh(_stack([stat_div, rt_div]), margin=(12, 8, 0, 8), width=460), pn.layout.HSpacer(),
               nav_prev, nav_label, nav_next, zoom_out, zoom_in, zoom_fit, sizing_mode="stretch_width", margin=(0, 8, 0, 0)),
        fetch_err,
        pn.pane.Bokeh(fspan, sizing_mode="stretch_width", margin=(2, 8, 4, 8)),
        legend, sizing_mode="stretch_width", css_classes=["card"], margin=(4, 20, 4, 20))

    # ------------------------------------------------------------------ tier 3 (motif) --
    motif_title = pn.pane.HTML("", sizing_mode="stretch_width", margin=(10, 14, 0, 14))
    motif_env = ColumnDataSource(dict(x=[], y=[]))
    fmot = C.base_figure(height=150, x_range=Range1d(-20, 40), y_range=Range1d(ylo, yhi), grid=True)
    C.mv_axis(fmot)
    fmot.yaxis.ticker.desired_num_ticks = 3
    fmot.xaxis.formatter = CustomJSTickFormatter(code="return (tick > 0 ? '+' : '') + tick.toFixed(0) + ' s'")
    box = BoxAnnotation(left=0, right=1, fill_color=C.ORANGE, fill_alpha=0.12, line_color=None)
    onset = Span(location=0, dimension="height", line_color=C.RED, line_width=1)
    end = Span(location=1, dimension="height", line_color=C.RED, line_width=1)
    lab_on = Label(x=0, y=0, y_units="screen", text="ONSET", text_font=C.MONO, text_font_size="9.5px", text_color=C.RED, x_offset=4, y_offset=0)
    lab_end = Label(x=1, y=0, y_units="screen", text="END", text_font=C.MONO, text_font_size="9.5px", text_color=C.RED, x_offset=4, y_offset=0)
    for a in (box, onset, end, lab_on, lab_end):
        fmot.add_layout(a)
    fmot.line("x", "y", source=motif_env, line_color=C.ORANGE, line_width=1.2)
    motif_meta = pn.pane.HTML("", sizing_mode="stretch_width", margin=(0, 14, 10, 14))
    send_motif = pn.widgets.Button(name="Send motif to Analyse →", css_classes=["btn"], disabled=True, width=210, margin=(0, 4))
    review_motif = pn.widgets.Button(name="Review this motif →", css_classes=["btn-primary"], disabled=True, width=190, margin=(0, 4),
                                     description="Review is outside this slice")
    motif_body = pn.Column(pn.pane.HTML('<div class="waits" style="height:120px;margin:6px 14px">select a motif: click a band in the span, or use ‹ ›</div>',
                                        sizing_mode="stretch_width"), sizing_mode="stretch_width", margin=0)
    tier3 = pn.Column(motif_title, motif_body,
                      pn.Row(motif_meta, send_motif, review_motif, sizing_mode="stretch_width", margin=(0, 10, 8, 0)),
                      sizing_mode="stretch_width", css_classes=["card"], margin=(4, 20, 4, 20))

    def draw_motif():
        i = state["sel"]
        if i is None:
            return
        m = motifs[i]
        s0, s1 = m["start_s"], m["end_s"]
        conn = corpus.connect(ctx.db_path)
        try:
            w = corpus.window(conn, rec, max(0.0, s0 - 20), min(dur_s, s1 + 20), 900)
        finally:
            conn.close()
        x, y = C.env_xy(w["envelope"])
        motif_env.data = dict(x=x * 3600.0 - s0, y=y)
        fin = y[np.isfinite(y)]
        if fin.size:
            fmot.y_range.start, fmot.y_range.end = C.padded(float(fin.min()), float(fin.max()), 0.1)
        fmot.x_range.start, fmot.x_range.end = -20, (s1 - s0) + 20
        box.left, box.right = 0, s1 - s0
        onset.location, end.location = 0, s1 - s0
        lab_on.x, lab_end.x = 0, s1 - s0
        lab_on.y = lab_end.y = 128
        motif_body[:] = [pn.pane.Bokeh(fmot, sizing_mode="stretch_width", margin=(2, 8, 4, 8))]
        kind = "annotated" if m["kind"] == "annotation" else "detected"
        verdict = m.get("verdict") or "unadjudicated"
        motif_title.object = (f'<span class="card-title" data-testid="signal-motif">Motif {m["kind"][:3]}-{m["id"]}</span>'
                              f'<span class="mono small" style="margin-left:14px">{s0 / 3600:.3f} – {s1 / 3600:.3f} h · {s1 - s0:.1f} s · {kind}, {esc(verdict)}</span>'
                              f'<span class="mono small muted" style="margin-left:14px">context ±20 s</span>')
        motif_meta.object = (f'<div class="mono small muted" style="padding-top:8px">nearest family — · tagged {esc(m.get("tag") or "—")} · '
                             f'{"run #" + str(m["run_id"]) if m.get("run_id") else "source " + esc(str(m.get("source") or "—"))} · onset and end are the stored span edges</div>')
        short = (s1 - s0) < MIN_SPAN_S
        send_motif.disabled = short
        send_motif.description = f"motif is {s1 - s0:.1f} s · shorter than the {MIN_SPAN_S:.0f} s minimum source span" if short else None

    def send_motif_cb(e):
        i = state["sel"]
        if i is None:
            return
        m = motifs[i]
        if m["end_s"] - m["start_s"] < MIN_SPAN_S:
            ctx.toast(f"motif shorter than {MIN_SPAN_S:.0f} s · not sent", "warning")
            return
        ctx.source = {"recording_id": channel_id, "channel_name": name, "source_file": rec["source_file"], "fs": fs,
                      "start_idx": int(round(m["start_s"] * fs)), "end_idx": int(round(m["end_s"] * fs)),
                      "label": f'motif {m["kind"][:3]}-{m["id"]}'}
        ctx.stale_from = None
        ctx.navigate("analyse/chain")
    send_motif.on_click(ctx.guard("Send motif to Analyse", send_motif_cb))

    # ------------------------------------------------------------------ span actions --
    actions_line = pn.pane.HTML("", sizing_mode="stretch_width", margin=(10, 14, 2, 14))
    note = pn.widgets.TextInput(placeholder="what you saw — kept with the span, never a verdict", width=520, css_classes=["sel-mono"], margin=(2, 14))
    save_btn = pn.widgets.Button(name="Save span", css_classes=["btn"], width=110, margin=(0, 4))
    send_span = pn.widgets.Button(name="Send span to Analyse →", css_classes=["btn"], width=210, margin=(0, 4))
    take_span = pn.widgets.Button(name="Take span for Review →", css_classes=["btn-primary"], disabled=True, width=210, margin=(0, 4),
                                  description="Review is outside this slice")

    def update_actions():
        a, b = span_x.start, span_x.end
        short = (b - a) * 3600 < MIN_SPAN_S - 1e-6
        send_span.disabled = short
        send_span.description = f"span shorter than {MIN_SPAN_S:.0f} s" if short else None
        why = f' &nbsp;<span style="color:#b3262b" data-testid="send-span-reason">send disabled · span shorter than {MIN_SPAN_S:.0f} s</span>' if short else ""
        dur_txt = f"{(b - a) * 3600:.0f} s" if (b - a) * 3600 < 600 else f"{b - a:.2f} h"
        actions_line.object = (f'<div class="mono small muted" data-testid="span-actions">Selected span {_fmt_h(a, b - a)} – {_fmt_h(b, b - a)} h · '
                               f'{dur_txt} · {state["in_view"]} motifs in view &nbsp;&nbsp; tags <span class="chip" style="height:20px">+ tag</span>{why}</div>')

    save_btn.on_click(ctx.guard("Save span", lambda e: ctx.toast("Save span is a stub in this slice: nothing was written (tags and note only, never a verdict)", "warning")))

    def send_span_cb(e):
        a, b = float(span_x.start), float(span_x.end)
        if (b - a) * 3600 < MIN_SPAN_S - 1e-6:
            ctx.toast(f"span shorter than {MIN_SPAN_S:.0f} s · not sent", "warning")
            return
        ctx.source = {"recording_id": channel_id, "channel_name": name, "source_file": rec["source_file"], "fs": fs,
                      "start_idx": int(round(a * 3600 * fs)), "end_idx": int(round(b * 3600 * fs)), "label": "span from Explore"}
        ctx.stale_from = None
        debug.event("send_span", source=ctx.source)
        ctx.navigate("analyse/chain")
    send_span.on_click(ctx.guard("Send span to Analyse", send_span_cb))

    actions = pn.Column(
        actions_line,
        pn.Row(pn.pane.HTML('<span class="mono small muted">note</span>', margin=(8, 0, 0, 14), width=40), note, pn.layout.HSpacer(),
               save_btn, send_span, take_span, sizing_mode="stretch_width", margin=(0, 10, 0, 0)),
        pn.pane.HTML('<div class="mono small muted" style="text-align:right;margin:2px 14px 10px">saving stores tags and note only · verdicts are given in Review</div>',
                     sizing_mode="stretch_width"),
        sizing_mode="stretch_width", css_classes=["card"], margin=(4, 20, 4, 20))

    def ribbon(title_, body_):
        return pn.Card(pn.pane.HTML(body_, sizing_mode="stretch_width"), title=title_, collapsed=True, sizing_mode="stretch_width",
                       margin=(4, 6), header_background="#ffffff", styles={"border-radius": "10px"})
    ann_rows = "".join(f'<tr><td>{a["start_s"] / 3600:.3f} h</td><td>{a["end_s"] - a["start_s"]:.0f} s</td><td>{esc(str(a["verdict"]))}</td><td>{esc(str(a["source"] or ""))}</td></tr>'
                       for a in all_spans["annotations"][:40])
    det_rows = "".join(f'<tr><td>{d["start_s"] / 3600:.3f} h</td><td>{d["end_s"] - d["start_s"]:.0f} s</td><td>{d["score"] if d["score"] is not None else "—"}</td><td>run {d["run_id"]}</td></tr>'
                       for d in all_spans["detections"][:40])
    # FRICTION: four stretch_width Cards in a Row made the page 5,464 px wide (each Card claims the full width);
    # a GridBox with ncols is what actually splits the row.
    ribbons_row = pn.GridBox(
        ribbon("Filters & search", '<div class="mono small muted">ten filter fields, CSV/JSON export and bulk actions live in the drawer (spec §5.3) · out of slice scope</div>'),
        ribbon(f"Annotations {summary['annotations']:,}", f'<table class="mono small">{ann_rows or "<tr><td>none</td></tr>"}</table>'),
        ribbon(f"Detections {summary['detections']:,}", f'<table class="mono small">{det_rows or "<tr><td>no detections on this channel</td></tr>"}</table>'),
        ribbon("Keyboard shortcuts", '<div class="mono small muted">wheel zoom · drag pan · ‹ › step motifs · − + fit</div>'),
        ncols=4, sizing_mode="stretch_width", margin=(4, 14, 20, 14))

    page = pn.Column(header, crumbs, tier1, tier2, tier3, actions, ribbons_row, sizing_mode="stretch_width", margin=0)
    debug.put("signal", {"channel_id": channel_id, "name": name, "overview_points": overview["envelope"]["n_points"],
                         "overview_ms": overview_ms, "motifs": len(motifs)})
    fetch()
    update_nav()
    return page


def _stack(figs):
    from bokeh.layouts import column
    return column(*figs, sizing_mode="stretch_width")
