"""Explore workspace: corpus_page(ctx) (frame explore-1-corpus) and signal_page(ctx, channel_id)
(frame explore-2-signal). Plots are Bokeh figures built directly (no HoloViews DynamicMap)."""
from __future__ import annotations

import html
import logging
import time

import numpy as np
import panel as pn
from bokeh.core.properties import value
from bokeh.models import (ColumnDataSource, CustomJSTickFormatter, FixedTicker, HoverTool, Range1d, TapTool)

from server import corpus

from . import charts as C
from . import debug

log = logging.getLogger("protoB.explore")
esc = html.escape

COLOUR_BY = ["annotations", "detections", "both", "disagree"]
BIN_CHOICES = [28, 57, 114]


def _conn(ctx):
    return corpus.connect(ctx.db_path)


def locked_card(rec: dict) -> pn.pane.HTML:
    return pn.pane.HTML(
        f'<div class="card card-pad" data-testid="locked-card" style="max-width:720px;border-color:#ffd9a8;background:#fffaf2">'
        f'<div class="card-title">🔒 held out · locked</div><h3 style="margin:6px 0 4px;font-size:15px">{esc(rec["source_file"])}</h3>'
        f'<p class="mono small" style="margin:0;color:#7a4a00">{esc(rec.get("held_out_reason") or "held out (spec §0 D6)")}</p>'
        f'<p class="muted small" style="margin:8px 0 0">No coverage, signal or span was fetched for this recording. Unlocking needs the '
        f'recording name typed and is logged (spec P19) — out of slice scope.</p></div>',
        sizing_mode="stretch_width", margin=(12, 20))


# =========================================================================================
# Explore › Corpus
# =========================================================================================

def corpus_page(ctx):
    conn = _conn(ctx)
    try:
        recs = corpus.recordings(conn)
    finally:
        conn.close()
    by_file = {r["source_file"]: r for r in recs}
    st = ctx.explore
    st.setdefault("bins", 57)
    st.setdefault("show", {"annotations": True, "detections": True})
    st.setdefault("verdicts", None)
    if st.get("file") not in by_file:
        st["file"] = recs[0]["source_file"]

    def rec_label(r):
        lock = "🔒 " if r["held_out"] else ""
        return f'{lock}{r["source_file"]}  ·  {r["n_channels"]} ch · {r["duration_h"]:.0f} h · {r["fs"]:g} Hz'

    rec_select = pn.widgets.Select(options={rec_label(r): r["source_file"] for r in recs}, value=st["file"], width=430,
                                   css_classes=["sel-mono"], margin=(0, 4))
    prev_btn = pn.widgets.Button(name="‹", width=32, css_classes=["btn"], margin=(0, 2))
    next_btn = pn.widgets.Button(name="›", width=32, css_classes=["btn"], margin=(0, 2))
    pager = pn.pane.HTML("", margin=(6, 4))
    bins_select = pn.widgets.Select(options={f"bin {b}": b for b in BIN_CHOICES}, value=st["bins"], width=110,
                                    css_classes=["sel-mono"], margin=(0, 4))
    colour = pn.widgets.RadioButtonGroup(options=COLOUR_BY, value=st.get("colour_by", "both"), css_classes=["seg"], margin=(0, 4))
    toolbar = pn.Row(rec_select, prev_btn, pager, next_btn,
                     pn.pane.HTML('<span class="muted mono small">time 0 – full</span>', margin=(8, 10)),
                     bins_select, pn.pane.HTML('<span class="muted mono small">colour by</span>', margin=(8, 4, 8, 12)), colour,
                     sizing_mode="stretch_width", margin=(10, 20, 2, 20))

    body = pn.Column(sizing_mode="stretch_width", margin=0)
    page = pn.Column(ctx.header("Explore", "Corpus", "bird's-eye across every channel"), toolbar, body,
                     sizing_mode="stretch_width", margin=0)

    show_ann = pn.widgets.Checkbox(name="annotations", value=st["show"]["annotations"], css_classes=["chk"], margin=(2, 10))
    show_det = pn.widgets.Checkbox(name="detections", value=st["show"]["detections"], css_classes=["chk"], margin=(2, 10))
    show_rev = pn.widgets.Checkbox(name="reviewed coverage · not in slice", value=False, disabled=True, css_classes=["chk"], margin=(2, 10))
    show_unrev = pn.widgets.Checkbox(name="unreviewed only · not in slice", value=False, disabled=True, css_classes=["chk"], margin=(2, 10))
    verdict_boxes: dict[str, pn.widgets.Checkbox] = {
        v: pn.widgets.Checkbox(name=v, value=(st["verdicts"] is None or v in st["verdicts"]), css_classes=["chk"], margin=(2, 10))
        for v in corpus.VERDICTS}
    match_line = pn.pane.HTML("", sizing_mode="stretch_width", margin=(6, 10))
    runs_line = pn.pane.HTML("", sizing_mode="stretch_width", margin=0)
    bottom_bar = pn.pane.HTML("", sizing_mode="stretch_width", margin=(6, 0))
    open_btn = pn.widgets.Button(name="Open →", css_classes=["btn-primary"], margin=(0, 4), width=170)
    cross_btn = pn.widgets.Button(name="Cross-channel", css_classes=["btn"], disabled=True, margin=(0, 4), width=240,
                                  description="Cross-channel view · not in this slice")
    title = pn.pane.HTML("", sizing_mode="stretch_width", margin=(10, 14, 0, 14))

    source = ColumnDataSource(dict(x=[], y=[], color=[], label=[], row=[]))
    labels_src = ColumnDataSource(dict(x=[], y=[], text=[], color=[]))
    sel_src = ColumnDataSource(dict(x=[], y=[], w=[]))
    state = {"cov": None, "built_for": None, "rect": None}

    def compute():
        """Fetch coverage for the selected recording (never for the held-out one) and redraw."""
        rec = by_file[rec_select.value]
        st["file"] = rec["source_file"]
        idx = [r["source_file"] for r in recs].index(rec["source_file"])
        pager.object = f'<span class="mono small" data-testid="pager">{idx + 1} / {len(recs)}</span>'
        if rec["held_out"]:
            state["cov"], state["built_for"] = None, None
            body[:] = [locked_card(rec)]
            debug.put("heatmap", {"file": rec["source_file"], "held_out": True, "rects": 0})
            return
        chosen = tuple(v for v, b in verdict_boxes.items() if b.value)
        st["verdicts"] = None if len(chosen) == len(verdict_boxes) else chosen
        conn = _conn(ctx)
        try:
            cov = corpus.coverage(conn, rec["source_file"], bins=int(bins_select.value),
                                  verdicts=st["verdicts"] if st["verdicts"] is None or chosen else ("__none__",))
        finally:
            conn.close()
        state["cov"] = cov
        if state["built_for"] != (rec["source_file"], cov["bins"]):
            build(cov)
        redraw(cov)

    def metric_values(cov):
        m, sa, sd = colour.value, show_ann.value, show_det.value
        out = []
        for row in cov["rows"]:
            a = np.asarray(row["annotations"]) * (1 if sa else 0)
            d = np.asarray(row["detections"]) * (1 if sd else 0)
            out.append({"annotations": a, "detections": d, "both": a + d, "disagree": np.asarray(row["disagree"])}[m])
        return out

    def redraw(cov):
        rows, bin_h = cov["rows"], cov["bin_h"]
        mats = metric_values(cov)
        flat = np.concatenate(mats) if mats else np.array([])
        colours = C.quantile_colours(flat)
        xs, ys, labels, rowi = [], [], [], []
        for ri, row in enumerate(rows):
            for b in range(cov["bins"]):
                n = int(mats[ri][b])
                xs.append((b + 0.5) * bin_h)
                ys.append(row["name"])
                labels.append(f'{row["name"]} · {b * bin_h:.0f}–{(b + 1) * bin_h:.0f} h · {n} span{"s" if n != 1 else ""}')
                rowi.append(ri)
        source.data = dict(x=xs, y=ys, color=colours, label=labels, row=rowi)
        sel_row = next((r for r in rows if r["id"] == st.get("channel_id")), None)
        names = [r["name"] for r in rows]
        labels_src.data = dict(x=[-cov["duration_h"] * 0.012] * len(rows), y=names, text=names,
                               color=[C.BLUE if (sel_row and r["id"] == sel_row["id"]) else C.MUTED for r in rows])
        sel_src.data = (dict(x=[cov["duration_h"] / 2], y=[sel_row["name"]], w=[cov["duration_h"] + bin_h * 0.4])
                        if sel_row else dict(x=[], y=[], w=[]))
        matching = int(flat.sum()) if flat.size else 0
        chans = sum(1 for m in mats if m.sum() > 0)
        match_line.object = (f'<div class="mono small muted">matching</div><div style="display:flex;justify-content:space-between;align-items:baseline">'
                             f'<span class="mono small muted">across {chans} of {len(rows)} channels</span>'
                             f'<b data-testid="matching-count" style="font-size:15px">{matching:,} spans</b></div>')
        runs_line.object = (f'<div class="card-title" style="margin:14px 10px 2px">Detections from</div>'
                            f'<div class="mono small muted" style="margin:2px 10px">runs all · {cov["n_detection_runs"]} &nbsp;·&nbsp; method any</div>')
        vc = cov["verdict_counts"]
        for v, b in verdict_boxes.items():
            b.name = f"{v} · {vc.get(v, 0)}"
        debug.put("heatmap", {"file": cov["source_file"], "bins": cov["bins"], "rows": len(rows), "rects": len(xs),
                              "distinct_colours": len(set(colours)), "colour_by": colour.value, "matching": matching,
                              "channels": chans, "compute_ms": cov["compute_ms"], "selected": sel_row["name"] if sel_row else None})
        swatches = "".join(f'<span style="display:inline-block;width:14px;height:10px;margin-left:2px;background:{c};border-radius:2px"></span>'
                           for c in [C.ZERO] + C.RAMP5)
        title.object = (f'<div style="display:flex;align-items:center;justify-content:space-between"><div><span class="card-title">Coverage map</span>'
                        f'<span class="mono small muted" style="margin-left:14px">{len(rows)} channels · 0 – {cov["duration_h"]:.0f} h · bin {bin_h:.1f} h</span></div>'
                        f'<div class="mono small muted">{colour.value} · spans per bin &nbsp; low {swatches} high</div></div>')
        update_bottom()

    def build(cov):
        rows = cov["rows"]
        names = [r["name"] for r in rows]
        dur = cov["duration_h"]
        fig = C.base_figure(height=33 * len(rows) + 34, x_range=Range1d(-dur * 0.075, dur * 1.004),
                            y_range=list(reversed(names)), grid=False, y_axis=False)
        fig.min_border_bottom = 22
        rect = fig.rect(x="x", y="y", width=cov["bin_h"], height=0.84, source=source, fill_color="color",
                        line_color="#ffffff", line_width=1, nonselection_fill_alpha=1.0, nonselection_fill_color="color",
                        selection_fill_color="color", nonselection_line_color="#ffffff", selection_line_color="#ffffff")
        fig.rect(x="x", y="y", width="w", height=0.99, source=sel_src, fill_color=None, line_color=C.BLUE, line_width=1.6)
        fig.text(x="x", y="y", text="text", source=labels_src, text_align="right", text_baseline="middle",
                 text_font=value(C.MONO), text_font_size="10.5px", text_color="color")
        fig.add_tools(HoverTool(renderers=[rect], tooltips="@label", point_policy="follow_mouse"))
        fig.add_tools(TapTool(renderers=[rect]))
        fig.xaxis.ticker = FixedTicker(ticks=[0, 120, 240, 360, 480, 600, round(dur)])
        fig.xaxis.formatter = CustomJSTickFormatter(code="return tick.toFixed(0) + ' h'")
        fig.outline_line_color = None
        state["rect"] = rect
        state["built_for"] = (cov["source_file"], cov["bins"])

        rail = pn.Column(
            pn.pane.HTML('<div class="card-title" style="margin:12px 10px 2px">Show</div>'), show_ann, show_det, show_rev, show_unrev,
            runs_line,
            pn.pane.HTML('<div class="card-title" style="margin:14px 10px 2px">Verdict</div>'
                         '<div class="mono small muted" style="margin:0 10px">'
                         + " ".join(f'<span class="legend-dot" style="background:{C.VERDICT_COLOUR[v]}"></span>' for v in corpus.VERDICTS)
                         + ' seed · interesting · not · artifact · unsure</div>'),
            *verdict_boxes.values(),
            pn.pane.HTML('<div class="card-title" style="margin:14px 10px 2px">Morphology tag</div>'
                         '<div class="mono small muted" style="margin:2px 10px 4px">no tags in this database</div>'),
            *[pn.widgets.Checkbox(name=f"{t} · 0", value=False, disabled=True, css_classes=["chk"], margin=(1, 10))
              for t in ("sharkfin", "spike-train", "slow-drift", "burst", "plateau", "biphasic")],
            pn.pane.HTML('<hr style="border:none;border-top:1px solid var(--border);margin:10px 10px 0">'), match_line,
            width=290, css_classes=["card"], margin=(8, 20, 8, 0))
        heat = pn.pane.Bokeh(fig, sizing_mode="stretch_width", margin=(4, 10, 8, 10))
        heat_card = pn.Column(title, heat, sizing_mode="stretch_width", css_classes=["card"], margin=(8, 12, 8, 20))
        bar = pn.Row(bottom_bar, cross_btn, open_btn, sizing_mode="stretch_width", css_classes=["card"], margin=(4, 20, 16, 20),
                     styles={"padding": "10px 14px"})
        body[:] = [pn.Row(heat_card, rail, sizing_mode="stretch_width", margin=0), bar]

    def on_tap(attr, old, new):
        if not new or not state["cov"]:
            return
        ri = source.data["row"][new[0]]
        st["channel_id"] = state["cov"]["rows"][ri]["id"]
        redraw(state["cov"])
    source.selected.on_change("indices", ctx.guard("select channel", on_tap))

    def update_bottom():
        cov = state["cov"]
        row = next((r for r in cov["rows"] if r["id"] == st.get("channel_id")), None) if cov else None
        if row is None:
            bottom_bar.object = '<div class="mono small muted" data-testid="corpus-bottom-bar">select a channel row in the map to see its counts</div>'
            open_btn.disabled, open_btn.name = True, "Open →"
            return
        c = row["counts"]
        dis = "—" if (c["annotations"] == 0 or c["detections"] == 0) else f'{c["disagree"]:,}'
        rev = "—" if c.get("reviewed_pct") is None else f'{c["reviewed_pct"]:.0f}'
        bottom_bar.object = (f'<div data-testid="corpus-bottom-bar" style="display:flex;align-items:baseline;gap:18px">'
                             f'<b style="font-size:14px">{esc(row["name"])}</b><span class="mono small muted">{c["annotations"]:,} annotations · '
                             f'{c["detections"]:,} detections · {dis} disagree · {rev} % reviewed</span></div>')
        open_btn.disabled, open_btn.name = False, f'Open {row["name"]} →'
        cross_btn.name = f'Cross-channel from {row["name"]}'

    open_btn.on_click(ctx.guard("Open channel", lambda e: st.get("channel_id") is not None and ctx.navigate(f"explore/signal/{st['channel_id']}")))

    def on_page(delta):
        files = [r["source_file"] for r in recs]
        rec_select.value = files[(files.index(rec_select.value) + delta) % len(files)]
    prev_btn.on_click(ctx.guard("previous recording", lambda e: on_page(-1)))
    next_btn.on_click(ctx.guard("next recording", lambda e: on_page(1)))

    def on_colour(*_):
        st["colour_by"] = colour.value
        st["show"] = {"annotations": show_ann.value, "detections": show_det.value}
        if state["cov"]:
            redraw(state["cov"])
    for w in (colour, show_ann, show_det):
        w.param.watch(ctx.guard("colour by", on_colour), "value")

    def on_refetch(*_):
        st["bins"] = int(bins_select.value)
        compute()
    for w in (bins_select, rec_select, *verdict_boxes.values()):
        w.param.watch(ctx.guard("coverage refetch", on_refetch), "value")

    compute()
    return page


# =========================================================================================
# Explore › Signal — implemented in signalview.py
# =========================================================================================

def signal_page(ctx, channel_id: int):
    from .signalview import signal_page as _page
    return _page(ctx, channel_id)
