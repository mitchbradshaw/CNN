"""Block page (frame chain-7b, Threshold to spans; generic for every other block): toolbar with
‹ full chain, a chain ribbon with this block highlighted, the block's process + output, a Parameters
panel generated from the adapter's param specs, the null card, and an Unapplied changes footer with
Revert and Re-run (which stays on this page and polls the in-process job).

The draggable cut: Bokeh has no draggable annotation, so the handle is a one-point ColumnDataSource
edited by a ``PointDrawTool`` (add disabled, drag only). A CustomJS moves the ``Span`` line and the
histogram's cut as the source changes; Python's ``source.on_change('data')`` writes
``params.threshold``, snaps the handle back onto its x position and marks this block (and
everything downstream) stale."""
from __future__ import annotations

import copy
import html
import logging

import numpy as np
import panel as pn
from bokeh.models import ColumnDataSource, CustomJS, Label, PointDrawTool, Range1d, Span

from server import chain as chain_mod

from . import charts as C
from . import debug
from . import renderer
from . import runstate as RS
from .analyse import source_payload, start_run

log = logging.getLogger("protoB.block")
esc = html.escape


def block_page(ctx, index: int):
    steps = ctx.chain["steps"]
    if not 0 <= index < len(steps):
        return pn.Column(ctx.header("Analyse", f"Block {index + 1:02d}", "no such block"),
                         pn.pane.HTML(f'<div class="pb-page"><div class="error-card"><h3>The chain has {len(steps)} blocks; there is no block {index + 1:02d}</h3></div></div>'),
                         sizing_mode="stretch_width", margin=0)
    return BlockView(ctx, index).page


class BlockView:
    def __init__(self, ctx, index):
        self.ctx, self.i = ctx, index
        self.src, self.is_example = RS.source_of(ctx)
        fs = float(self.src.get("fs") or 1)
        self.x_range = Range1d(self.src["start_idx"] / fs / 3600, self.src["end_idx"] / fs / 3600)
        self.poll = None
        self._guard = False
        self.thr_src = None
        self.spec = RS.catalog()[RS.step_name(self.step)]
        self.back = pn.widgets.Button(name="‹ full chain", css_classes=["btn-link", "t-back"], width=100, margin=(6, 0))
        self.back.on_click(lambda e: ctx.navigate("analyse/chain"))
        self.chips = pn.pane.HTML("", margin=(4, 4))
        self.rerun = pn.widgets.Button(name="↻ Re-run", css_classes=["btn-primary", "t-rerun"], width=160, margin=(4, 3))
        self.rerun.on_click(self.on_rerun)
        self.ribbon = pn.Row(sizing_mode="stretch_width", margin=(6, 20, 4, 20), css_classes=["card"], styles={"padding": "6px 8px"})
        self.process = pn.Column(sizing_mode="stretch_width", css_classes=["card"], margin=(6, 12, 6, 20))
        self.params = pn.Column(width=340, css_classes=["card"], margin=(6, 20, 6, 0))
        self.null_card = pn.pane.HTML(
            '<div class="card-title">This parameter against the null</div><div class="waits" style="height:90px;margin-top:8px;padding:0 10px;text-align:center">'
            'no surrogate runs in this slice (the surrogate toggle is off) · a sweep of this parameter against its null would be drawn here</div>',
            width=340, css_classes=["card"], margin=(6, 20, 6, 0), styles={"padding": "10px 12px"})
        self.footer = pn.pane.HTML("", sizing_mode="stretch_width", margin=0)
        self.revert = pn.widgets.Button(name="Revert", css_classes=["btn", "t-revert"], width=90, margin=(0, 4))
        self.revert.on_click(self.on_revert)
        self.rerun2 = pn.widgets.Button(name="↻ Re-run", css_classes=["btn-primary", "t-rerun2"], width=170, margin=(0, 4))
        self.rerun2.on_click(self.on_rerun)
        self.widgets: dict = {}
        sub = "set the cut against the scores · spans are what the next stage receives" if self.is_threshold() else "settings and output together"
        self.page = pn.Column(
            ctx.header("Analyse", f"{index + 1:02d} {self.spec['page_name']}", sub),
            pn.Row(self.back, self.chips, pn.layout.HSpacer(), self.rerun, sizing_mode="stretch_width", margin=(8, 20, 0, 20)),
            self.ribbon,
            pn.Row(self.process, pn.Column(self.params, self.null_card, width=360, margin=0), sizing_mode="stretch_width", margin=0),
            pn.Row(self.footer, self.revert, self.rerun2, sizing_mode="stretch_width", css_classes=["card"], margin=(6, 20, 24, 20),
                   styles={"padding": "10px 14px"}),
            sizing_mode="stretch_width", margin=0, css_classes=["block-page"])
        ctx.on_leave(self.stop_poll)
        self.build_params()
        self.build_process()
        self.refresh()
        job = self.job()
        if job is not None and job.status == "running":
            self.start_poll()

    # ---------------------------------------------------------------- state --
    @property
    def step(self):
        return self.ctx.chain["steps"][self.i]

    def is_threshold(self):
        return RS.step_name(self.step) == "detection.threshold"

    def job(self):
        return RS.job_for_source(self.ctx.manager.jobs.get(self.ctx.chain.get("lastRunJobId")), self.src)

    def applied_params(self):
        job = self.job()
        if job is None or self.i >= len(job.recipe["steps"]):
            return None
        s = job.recipe["steps"][self.i]
        return (s.get("params") or {}) if RS.step_name(s) == RS.step_name(self.step) else None

    def current_params(self):
        try:
            return chain_mod.validated_params(self.step)
        except (ValueError, KeyError) as e:
            return {"__error__": str(e), **(self.step.get("params") or {})}

    def set_param(self, name, value):
        steps = copy.deepcopy(self.ctx.chain["steps"])
        steps[self.i]["params"] = dict(steps[self.i].get("params") or {}, **{name: value})
        self.ctx.chain = dict(self.ctx.chain, steps=steps, saved=False)
        if self.job() is not None:
            cur = self.ctx.stale_from
            self.ctx.stale_from = self.i if cur is None else min(cur, self.i)
        debug.event("param", step=self.i, name=name, value=value, stale_from=self.ctx.stale_from)
        self.refresh()

    # ---------------------------------------------------------------- params --
    def build_params(self):
        items = [pn.pane.HTML(f'<div class="card-title" style="margin:10px 12px 0">Parameters</div>'
                              f'<div class="mono small muted" style="margin:2px 12px 6px">generated from {esc(self.spec["name"])}\'s param specs</div>')]
        params = self.step.get("params") or {}
        for p in self.spec["params"]:
            val = params.get(p["name"], p["default"])
            common = dict(name=p["name"], css_classes=["sel-mono", f"t-param-{p['name']}"], margin=(2, 12), sizing_mode="stretch_width")
            if p["choices"]:
                w = pn.widgets.Select(options=list(p["choices"]), value=val if val in p["choices"] else p["default"], **common)
            elif p["type"] == "bool":
                w = pn.widgets.Checkbox(value=bool(val), **dict(common, css_classes=["chk", f"t-param-{p['name']}"]))
            elif p["type"] == "int":
                w = (pn.widgets.IntSlider(start=int(p["min"]), end=int(p["max"]), value=int(val), **common)
                     if p["min"] is not None and p["max"] is not None else pn.widgets.IntInput(value=int(val), **common))
            elif p["type"] == "float":
                w = (pn.widgets.FloatSlider(start=float(p["min"]), end=float(p["max"]), value=float(val), step=(p["max"] - p["min"]) / 100, **common)
                     if p["min"] is not None and p["max"] is not None else pn.widgets.FloatInput(value=float(val), **common))
            else:
                w = pn.widgets.TextInput(value=str(val), **common)
            marker = pn.pane.HTML("", margin=(0, 12, 4, 12))
            self.widgets[p["name"]] = (w, marker, p)

            def on_change(e, pname=p["name"]):
                if self._guard:
                    return
                if pname == "threshold" and self.thr_src is not None:
                    self._guard = True
                    try:
                        self.thr_src.data = dict(x=[self.handle_x], y=[float(e.new)])
                        self.cut.location = self.hist_cut.location = float(e.new)
                    finally:
                        self._guard = False
                self.set_param(pname, e.new)
            w.param.watch(on_change, "value")
            items += [w, marker]
        if not self.spec["params"]:
            items.append(pn.pane.HTML('<div class="mono small muted" style="margin:4px 12px">this block has no parameters</div>'))
        self.params.objects = items

    def paint_markers(self):
        cur = self.step.get("params") or {}
        for name, (w, marker, p) in self.widgets.items():
            v = cur.get(name, p["default"])
            marker.object = ('<span class="mono small" style="color:#15794f">= default</span>' if v == p["default"]
                             else f'<span class="mono small muted">default {esc(str(p["default"]))}'
                                  f'{" · min " + str(p["min"]) if p["min"] is not None else ""}{" · max " + str(p["max"]) if p["max"] is not None else ""}</span>')

    # ---------------------------------------------------------------- process --
    def build_process(self):
        job = self.job()
        payload = job.payloads.get(self.i) if (job is not None and self.applied_params() is not None) else None
        upstream = job.payloads.get(self.i - 1) if (job is not None and self.i > 0) else None
        self.thr_src = None
        if self.is_threshold() and upstream is not None and upstream.get("type") == "scores":
            self.process.objects = self.threshold_process(upstream, payload)
            return
        title = pn.pane.HTML(f'<div class="card-title" style="margin:10px 14px 0">{esc(self.spec["page_name"])} · output</div>'
                             f'<div class="mono small muted" style="margin:2px 14px 6px">{esc(self.spec["signature"])} · {esc(self.spec["description"][:160])}</div>')
        if payload is None:
            body = pn.pane.HTML('<div class="waits" style="height:220px;margin:0 14px 14px">no result for this block yet · Re-run to see its output</div>',
                                sizing_mode="stretch_width")
        else:
            ghost = None
            if payload.get("type") in ("signal", "spanset"):
                ghost = next((job.payloads[k] for k in range(self.i - 1, -1, -1) if job.payloads.get(k, {}).get("type") == "signal"), None)
                if ghost is None:
                    try:
                        ghost = source_payload(self.ctx, self.src)
                    except Exception:
                        ghost = None
            info = {}
            body = pn.Column(renderer.render(payload, self.x_range, 260, ghost=ghost, info=info), sizing_mode="stretch_width", margin=(0, 14, 14, 14))
        self.process.objects = [title, body]

    def threshold_process(self, scores, spans):
        thr = float((self.step.get("params") or {}).get("threshold", 0.0))
        x, y = C.env_xy(scores["envelope"])
        lo, hi = scores.get("value_range") or [0.0, 1.0]
        f = C.base_figure(height=280, x_range=self.x_range, y_range=Range1d(*C.padded(min(lo, thr), max(hi, thr), 0.1)), grid=True)
        C.time_axis(f)
        f.min_border_left, f.min_border_right, f.min_border_top = 44, 12, 6
        f.line(x, y, line_color=C.INK, line_width=1)
        self.handle_x = self.x_range.start + (self.x_range.end - self.x_range.start) * 0.97
        self.thr_src = ColumnDataSource(dict(x=[self.handle_x], y=[thr]))
        self.cut = Span(location=thr, dimension="width", line_color=C.ORANGE, line_width=1.5)
        f.add_layout(self.cut)
        lab = Label(x=self.x_range.start, y=thr, text=f"cut {thr:g} · drag the handle", text_font=C.MONO, text_font_size="10px",
                    text_color=C.ORANGE, x_offset=6, y_offset=4)
        f.add_layout(lab)
        handle = f.scatter("x", "y", source=self.thr_src, size=14, marker="square", fill_color=C.ORANGE, line_color="#ffffff", line_width=2)
        tool = PointDrawTool(renderers=[handle], add=False, drag=True, num_objects=1, description="drag the cut")
        f.add_tools(tool)
        f.toolbar.active_tap = tool
        f.toolbar.active_drag = tool
        hist = scores.get("histogram") or {"counts": [], "edges": [0, 1]}
        edges = np.asarray(hist["edges"], dtype=float)
        counts = np.asarray(hist["counts"], dtype=float)
        h = C.base_figure(height=190, x_range=Range1d(*C.padded(min(edges.min(), thr), max(edges.max(), thr), 0.04)),
                          y_range=Range1d(0, (counts.max() if counts.size else 1) * 1.12), grid=False, y_axis=False)
        h.min_border_left, h.min_border_bottom = 12, 20
        if counts.size:
            h.quad(left=edges[:-1], right=edges[1:], bottom=0, top=counts, fill_color="#9db9e8", line_color="#ffffff")
        self.hist_cut = Span(location=thr, dimension="height", line_color=C.ORANGE, line_width=1.5)
        h.add_layout(self.hist_cut)
        strip = C.base_figure(height=34, x_range=self.x_range, y_range=Range1d(0, 1), grid=False, x_axis=False, y_axis=False)
        strip.min_border_left, strip.min_border_right = 44, 12
        n_spans = 0
        rows = ""
        if spans and spans.get("type") == "spanset":
            s0 = [v / 3600 for v in spans["start_s"]]
            s1 = [v / 3600 for v in spans["end_s"]]
            n_spans = len(s0)
            if s0:
                strip.quad(left=s0, right=s1, bottom=0.2, top=0.8, fill_color=C.GREEN, line_color=None)
            sc = spans.get("scores") or [None] * n_spans
            rows = "".join(f'<tr><td>{a / 3600:.3f} h</td><td>{b - a:.0f} s</td><td>{("%.3f" % s) if isinstance(s, (int, float)) else "–"}</td></tr>'
                           for a, b, s in list(zip(spans["start_s"], spans["end_s"], sc))[:12])
        self.preview = pn.pane.HTML("", sizing_mode="stretch_width", margin=(0, 14, 6, 14))
        self.thr_src.js_on_change("data", CustomJS(args=dict(src=self.thr_src, cut=self.cut, hc=self.hist_cut, lab=lab), code="""
            const y = src.data.y[0]; cut.location = y; hc.location = y; lab.y = y; lab.text = 'cut ' + y.toFixed(3);
        """))
        self.scores_env = y
        self.thr_fig = f

        def on_drag(attr, old, new):
            if self._guard:
                return
            ny = round(float(new["y"][0]), 3)
            self._guard = True
            try:
                if abs(new["x"][0] - self.handle_x) > 1e-12 or new["y"][0] != ny:
                    self.thr_src.data = dict(x=[self.handle_x], y=[ny])     # snap: the cut only moves vertically
                self.cut.location = self.hist_cut.location = ny
                lab.text = f"cut {ny:g}"
                if "threshold" in self.widgets:
                    self.widgets["threshold"][0].value = ny
            finally:
                self._guard = False
            self.set_param("threshold", ny)
        self.thr_src.on_change("data", on_drag)
        pn.state.cache["block_fig"] = self   # geometry for the smoke test's drag (read by debug.snapshot)
        return [
            pn.pane.HTML(f'<div style="margin:10px 14px 0"><b>Scores with the cut</b> <span class="mono small muted" style="margin-left:10px">'
                         f'{esc(RS.page_name(self.ctx.chain["steps"][self.i - 1]))} output · drag the orange handle · the parameter is written on release</span></div>'),
            pn.pane.Bokeh(f, sizing_mode="stretch_width", margin=(2, 10, 0, 10)),
            pn.pane.HTML('<div class="mono small muted" style="margin:0 14px">spans (last run)</div>'),
            pn.pane.Bokeh(strip, sizing_mode="stretch_width", margin=(0, 10, 4, 10)),
            self.preview,
            pn.Row(pn.Column(pn.pane.HTML('<div style="margin:6px 14px 0"><b>Scores histogram</b> <span class="mono small muted">same cut</span></div>'),
                             pn.pane.Bokeh(h, sizing_mode="stretch_width", margin=(0, 10, 10, 10)), sizing_mode="stretch_width", margin=0),
                   pn.pane.HTML(f'<div style="margin:6px 14px 0"><b>Spans produced</b> <span class="mono small muted">{n_spans} · last run</span>'
                                f'<table class="mono small" style="margin-top:6px;width:100%"><tr class="muted"><td>start</td><td>duration</td><td>peak score</td></tr>'
                                f'{rows or "<tr><td colspan=3 class=muted>none</td></tr>"}</table></div>', width=330),
                   sizing_mode="stretch_width", margin=0),
        ]

    def geometry(self) -> dict:
        """Where the handle is in canvas pixels (the browser syncs inner_width/height back to Python)."""
        f = self.thr_fig
        out = {"y_start": f.y_range.start, "y_end": f.y_range.end, "x_start": f.x_range.start, "x_end": f.x_range.end,
               "handle_x": self.handle_x, "handle_y": self.thr_src.data["y"][0], "border_right": f.min_border_right, "border_top": f.min_border_top}
        for k in ("inner_width", "inner_height", "outer_width", "outer_height"):
            try:
                out[k] = getattr(f, k)
            except Exception:
                out[k] = None
        return out

    def paint_preview(self):
        if self.thr_src is None:
            return
        thr = float((self.step.get("params") or {}).get("threshold", 0.0))
        yy = np.nan_to_num(self.scores_env, nan=-np.inf)
        above = yy > thr
        crossings = int(np.sum(above[1:] & ~above[:-1]) + (1 if above.size and above[0] else 0))
        self.preview.object = (f'<div class="mono small" data-testid="threshold-preview">cut <b>{thr:g}</b> · ≈ {crossings} run{"s" if crossings != 1 else ""} above '
                               f'the cut in the displayed envelope (preview) · Re-run for the core\'s spans</div>')

    # ---------------------------------------------------------------- refresh --
    def refresh(self):
        job = self.job()
        v = RS.validate_full(self.ctx, self.ctx.chain["steps"])
        rows = RS.derive_rows(self.ctx.chain["steps"], job, self.ctx.stale_from, v)
        items = [pn.pane.HTML('<span class="mono small muted" style="padding:8px 6px 0 4px;display:inline-block">chain</span>', margin=0)]
        src_btn = pn.widgets.Button(name="● Source · cached", css_classes=["btn"], width=140, margin=(2, 3))
        src_btn.on_click(lambda e: self.ctx.navigate("analyse/chain"))
        items.append(src_btn)
        for k, (s, r) in enumerate(zip(self.ctx.chain["steps"], rows)):
            b = pn.widgets.Button(name=f"{k + 1:02d} {RS.page_name(s)} · {r['status']}", width=250, margin=(2, 3),
                                  css_classes=["btn-primary" if k == self.i else "btn", f"t-ribbon-{k + 1}"])
            b.on_click(lambda e, k=k: self.ctx.navigate(f"analyse/block/{k}"))
            items.append(b)
        self.ribbon.objects = items
        s = self.src
        fs = float(s.get("fs") or 1)
        est = v.get("estimate")
        self.chips.object = (f'<span class="chip" data-testid="chain-name">{esc(self.ctx.chain["name"])} <span class="muted">{"saved" if self.ctx.chain.get("saved") else "unsaved"}</span></span> '
                             f'<span class="chip blue">∿ Signal · {esc(s.get("channel_name", "?"))} · {s["start_idx"] / fs / 3600:.2f}–{s["end_idx"] / fs / 3600:.2f} h</span> '
                             f'<span class="chip grey">null · off</span> <span class="chip amber">≈ {RS.fmt_timing(est["total_s"]) if est else "–"} · local</span>')
        stale = self.ctx.stale_from
        running = job is not None and job.status == "running"
        k = stale if stale is not None else self.i
        label = "■ Cancel" if running else (f"↻ Re-run from {k + 1:02d}" if job is not None else "▶ Run chain")
        for b in (self.rerun, self.rerun2):
            b.name = label
            b.disabled = (not v.get("ok_to_run")) and not running
        applied = self.applied_params()
        cur = self.current_params()
        if "__error__" in cur:
            txt = f'<b style="color:#b3262b">Invalid parameter</b><div class="mono small" style="color:#b3262b">{esc(cur["__error__"])}</div>'
        elif applied is None:
            txt = '<b data-testid="unapplied">No run yet for this block</b><div class="mono small muted">Re-run executes the chain on the database copy and stays on this page</div>'
        else:
            changes = [f"{n} {applied.get(n)!r} → {cur.get(n)!r}" for n in cur if applied.get(n) != cur.get(n)]
            txt = (f'<b data-testid="unapplied">Unapplied changes · {len(changes)}</b><div class="mono small" style="color:#a05e00">{esc(" · ".join(changes))} · '
                   f'{self.i + 1:02d} and downstream are stale</div>' if changes else
                   '<b data-testid="unapplied">No unapplied changes</b><div class="mono small muted">this block matches its last run</div>')
        if running:
            txt += f'<div class="mono small" style="color:var(--blue-600)">running job {job.id} · {job.snapshot()["elapsed_s"]:.1f} s</div>'
        elif job is not None and job.status == "failed":
            txt += (f'<div class="mono small" style="color:#b3262b">last run failed at {((job.error or {}).get("step") or 0) + 1:02d}: '
                    f'{esc(str((job.error or {}).get("message", ""))[:200])}</div>')
        self.footer.object = f'<div data-testid="block-footer">{txt}</div>'
        self.revert.disabled = applied is None or cur == applied
        self.paint_markers()
        self.paint_preview()
        debug.put("block", {"index": self.i, "name": self.spec["name"], "threshold": (self.step.get("params") or {}).get("threshold"),
                            "stale_from": self.ctx.stale_from, "rerun_label": label, "has_handle": self.thr_src is not None,
                            "statuses": [r["status"] for r in rows], "job": job.id if job is not None else None,
                            "job_status": job.status if job is not None else None,
                            "step_timings": job.step_timings if job is not None else None})

    # ---------------------------------------------------------------- actions --
    def on_revert(self, _=None):
        applied = self.applied_params()
        if applied is None:
            return
        steps = copy.deepcopy(self.ctx.chain["steps"])
        steps[self.i]["params"] = copy.deepcopy(applied)
        self.ctx.chain = dict(self.ctx.chain, steps=steps)
        self.ctx.stale_from = None
        self._guard = True
        try:
            for name, (w, _m, p) in self.widgets.items():
                if name in applied:
                    w.value = applied[name]
            if self.thr_src is not None and "threshold" in applied:
                self.thr_src.data = dict(x=[self.handle_x], y=[float(applied["threshold"])])
                self.cut.location = self.hist_cut.location = float(applied["threshold"])
        finally:
            self._guard = False
        self.refresh()

    def on_rerun(self, _=None):
        job = self.job()
        if job is not None and job.status == "running":
            self.ctx.manager.cancel(job)
            return
        v = RS.validate_full(self.ctx, self.ctx.chain["steps"])
        job, why = start_run(self.ctx, v)
        if job is None:
            self.ctx.toast(why, "error")
            return
        self.refresh()
        self.start_poll()
        self.ctx.refresh_chrome()

    def start_poll(self):
        if self.poll is None:
            self.poll = pn.state.add_periodic_callback(self.tick, period=200)

    def stop_poll(self):
        if self.poll is not None:
            try:
                self.poll.stop()
            except Exception:
                pass
            self.poll = None

    def tick(self):
        job = self.job()
        if job is None or job.status != "running":
            self.stop_poll()
            self.build_process()
            self.refresh()
            self.ctx.refresh_chrome()
            return
        self.refresh()
