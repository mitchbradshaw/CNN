"""Analyse workspace: chain_page(ctx) (frames chain-1 + states 1d/1e/1f/1h) and block_page(ctx, index)
(frame chain-7b, implemented in blockpage.py).

The chain page is one ``ChainView`` per render: a toolbar, a Source row and one row per step, each row
= a left panel (number, name, badge, signature, caption, icons) + the row's plot from the single
dispatch seam ``renderer.render``. All rows share ONE ``Range1d`` (the time axis) and one crosshair
``Span`` overlay. Runs are in-process: ``RunManager.start`` → a worker thread; this page polls the job
object every 200 ms with ``pn.state.add_periodic_callback`` (no transport) and rebuilds only the rows
whose signature changed. Cancel is ``manager.cancel(job)`` (cooperative, between steps)."""
from __future__ import annotations

import copy
import html
import json
import logging
import os
import time

import numpy as np
import panel as pn
from bokeh.models import CustomJSTickFormatter, Range1d, Span

from server import chain as chain_mod
from server import corpus

from . import charts as C
from . import debug
from . import renderer
from . import runstate as RS

log = logging.getLogger("protoB.analyse")
esc = html.escape

ROW_H = 112
LEFT_W = 250
BADGE_LABEL = {"new": "new", "cached": "cached", "computed": "✓ computed", "stale": "stale", "running": "running", "waiting": "waiting", "failed": "failed",
               "blocked": "blocked", "cancelled": "cancelled", "invalid": "invalid", "error": "render error"}


def badge_html(row: dict, testid: str) -> str:
    st = row["status"]
    cls = {"waiting": "running", "error": "failed"}.get(st, st)
    t = row.get("timing")
    txt = BADGE_LABEL[st]
    title = ""
    if st == "cached" and row.get("cache_only"):
        txt += " · not loaded"
        title = "this step's result is in the core's step cache, but no run of this chain on this span is attached to the page · Run reads it back in ~0 s"
    elif st in ("cached", "computed") and t is not None:
        txt += f" · {RS.fmt_timing(t)}"
        title = (f"core step time {t:.3f} s" + (" — 0.0 is the core's own prefix-cache hit signal" if t == 0 else "")) if row.get("timing_is_core") else f"wall {t:.3f} s"
    return f'<span class="badge {cls}" data-testid="{testid}" title="{esc(title)}">{esc(txt)}</span>'


def source_payload(ctx, src: dict, px: int = 1200) -> dict:
    conn = corpus.connect(ctx.db_path)
    try:
        rec = corpus.recording_row(conn, src["recording_id"])
        if rec is None or rec["held_out"]:
            raise PermissionError(f"{src.get('source_file')} is held out (spec §0 D6); the chain refuses it as a source")
        fs = float(rec["fs"])
        if int(src["end_idx"]) - int(src["start_idx"]) <= 0:    # critique r1 P1: say it, never a numpy reduction traceback
            raise ValueError(f"the source span is empty ({int(src['end_idx']) - int(src['start_idx'])} samples) · send a span of at least 30 s from Explore")
        w = corpus.window(conn, rec, src["start_idx"] / fs, src["end_idx"] / fs, px)
    finally:
        conn.close()
    env = w["envelope"]
    v = np.asarray([np.nan if a is None else a for a in env["v"]], dtype=float)
    fin = v[np.isfinite(v)]
    return {"type": "signal", "envelope": env, "y_range": [float(fin.min()), float(fin.max())] if fin.size else None,
            "n": int(src["end_idx"] - src["start_idx"]), "fs": fs, "summary": f"{src['end_idx'] - src['start_idx']:,} samples · {fs:g} Hz"}


def start_run(ctx, v: dict):
    """Returns (job, None) or (None, reason). Mirrors A's POST /api/runs checks."""
    if not v.get("ok"):
        return None, "chain is invalid"
    if v.get("held_out"):
        return None, "the source is held out"
    if v.get("recipe_error"):
        return None, v["recipe_error"]
    if v.get("over_ceiling"):
        o = v["over_ceiling"][0]
        return None, (f"stage {o['index'] + 1:02d} ({o['name']}) exceeds its local ceiling of {o['max_span_samples']:,} samples "
                      f"(span is {v['n_samples']:,}); shorten the span or route it to HPC (out of slice scope)")
    job = ctx.manager.start(v["recipe"], v["recording"], px=1200)
    ctx.chain = dict(ctx.chain, lastRunJobId=job.id)
    ctx.job_ids.append(job.id)
    ctx.stale_from = None
    debug.event("run_started", job_id=job.id, steps=[RS.step_name(s) for s in v["recipe"]["steps"]])
    try:
        ctx.sync_hash()        # the job id goes into the URL so a reload re-attaches (critique r1 P1)
    except Exception:
        log.exception("sync_hash failed")
    return job, None


class ChainView:
    def __init__(self, ctx):
        self.ctx = ctx
        self.src, self.is_example = RS.source_of(ctx)
        fs = float(self.src.get("fs") or 1.0)
        self.t0_h, self.t1_h = self.src["start_idx"] / fs / 3600, self.src["end_idx"] / fs / 3600
        self.x_range = Range1d(self.t0_h, self.t1_h)
        self.hover = Span(dimension="height", line_color="#9ca3af", line_width=1, line_dash="dashed")
        self.row_cache: dict = {}
        self.v = None
        self.v_key = None
        self.poll = None
        self.running_panes: dict[int, pn.pane.HTML] = {}
        self.undo_steps = None
        self.throw = ctx.query.get("throw") == "1"
        self.uncaught = ctx.query.get("uncaught") == "1"
        self.throw_row = ctx.query.get("throw") == "row"      # loud-failure evidence: step row 02's renderer raises (caught per row)
        pm = str(ctx.query.get("poll_ms", "200"))
        self.poll_ms = max(50, int(pm)) if pm.isdigit() else 200   # test affordance: a slow poll makes a stale "■ Cancel" reproducible
        self.run_mode = "run"              # what the Run button is SHOWING: run | cancel (critique r1 P0 stale-cancel)
        self.run_mode_prev = "run"
        self.run_mode_at = 0.0
        self.rows_col = pn.Column(sizing_mode="stretch_width", margin=0)
        self.notice = pn.Row(sizing_mode="stretch_width", margin=0)
        self.popover = pn.Column(visible=False, width=560, css_classes=["popover"], margin=(0, 20, 6, 0), styles={"padding": "10px 12px"})
        self.modal_holder = pn.Column(margin=0)
        self._build_toolbar()
        self._build_footer()
        self.page = pn.Column(ctx.header("Analyse", "Chain", "build here · open a block to tune it"), self.toolbar,
                              pn.Row(pn.layout.HSpacer(), self.popover, sizing_mode="stretch_width", margin=0),
                              self.notice, self.rows_col, self.footer, self.modal_holder,
                              sizing_mode="stretch_width", margin=0, css_classes=["chain-page"])
        ctx.on_leave(self.stop_poll)
        self.refresh()
        job = self.job()
        if job is not None and job.status == "running":
            self.start_poll()

    # ------------------------------------------------------------------ state --
    @property
    def steps(self) -> list[dict]:
        return self.ctx.chain["steps"]

    def job(self):
        return RS.job_for_source(self.ctx.manager.jobs.get(self.ctx.chain.get("lastRunJobId")), self.src)

    def validation(self, force=False):
        job = self.job()
        key = (json.dumps(self.steps, sort_keys=True, default=str), json.dumps(self.src, sort_keys=True), job.status if job else None,
               job.id if job else None)
        if force or key != self.v_key:
            self.v = RS.validate_full(self.ctx, self.steps)
            self.v_key = key
        return self.v

    def set_steps(self, steps: list[dict], stale_from: int | None):
        self.ctx.chain = dict(self.ctx.chain, steps=steps, saved=False)
        if stale_from is not None and self.job() is not None:
            cur = self.ctx.stale_from
            self.ctx.stale_from = stale_from if cur is None else min(cur, stale_from)
        self.refresh()

    # ------------------------------------------------------------------ toolbar --
    def _build_toolbar(self):
        self.name_chip = pn.pane.HTML("", margin=(4, 4))
        self.source_chip = pn.pane.HTML("", margin=(4, 4))
        self.surrogate = pn.widgets.Switch(value=False, disabled=True, width=36, margin=(10, 2, 0, 10))
        self.estimate_chip = pn.pane.HTML("", margin=(4, 4))
        self.history_btn = pn.widgets.Button(name="History", css_classes=["btn", "t-history"], width=80, margin=(4, 3))
        self.import_btn = pn.widgets.Button(name="Import", css_classes=["btn"], width=76, margin=(4, 3))
        self.save_btn = pn.widgets.Button(name="Save template", css_classes=["btn"], width=120, margin=(4, 3))
        self.run_btn = pn.widgets.Button(name="Run chain", css_classes=["btn-primary"], width=150, margin=(4, 3))
        self.run_btn_classes = ["t-run"]
        self.run_reason = pn.pane.HTML("", margin=(0, 20, 0, 0), sizing_mode="stretch_width")
        g = self.ctx.guard
        self.history_btn.on_click(g("History", lambda e: self.toggle_popover("history")))
        self.import_btn.on_click(g("Import", lambda e: self.toggle_popover("import")))
        self.save_btn.on_click(g("Save template", self.save_template))
        self.run_btn.on_click(g("Run / Cancel", self.on_run))
        self.toolbar = pn.Column(
            pn.Row(self.name_chip, self.source_chip, pn.layout.HSpacer(), self.surrogate,
                   pn.pane.HTML('<span class="mono small muted" title="surrogate nulls are not in this slice">surrogate · off</span>', margin=(12, 8, 0, 2)),
                   self.estimate_chip, self.history_btn, self.import_btn, self.save_btn, self.run_btn,
                   sizing_mode="stretch_width", margin=(10, 20, 0, 20)),
            self.run_reason, sizing_mode="stretch_width", margin=0)

    def update_toolbar(self, v, rows):
        c = self.ctx.chain
        self.name_chip.object = (f'<span class="chip" data-testid="chain-name">{esc(c["name"])} '
                                 f'<span class="muted">{"saved" if c.get("saved") else "unsaved"}</span></span>')
        s = self.src
        fs = float(s.get("fs") or 1)
        lab = f'Signal span · {esc(s.get("channel_name", "?"))} · {s["start_idx"] / fs / 3600:.2f}–{s["end_idx"] / fs / 3600:.2f} h'
        self.source_chip.object = (f'<span class="chip blue" data-testid="source-chip" title="{esc(str(s))}">∿ {lab}</span>')
        est = v.get("estimate")
        job = self.job()
        stale = self.ctx.stale_from
        if est:
            all_cached = stale is None and bool(rows) and all(r["status"] == "cached" for r in rows)
            tail = f"{stale + 1:02d} → {len(self.steps):02d}" if stale is not None else ("all cached" if all_cached else "full run")
            cls = "amber" if v.get("over_ceiling") else "grey"      # amber only when it needs attention (critique r1 P2)
            est_txt = ("0 s" if all_cached else "no core estimate" if not est.get("total_s") else "≤ " + RS.fmt_timing(est["total_s"]) + " core est.")
            self.estimate_chip.object = (f'<span class="chip {cls}" data-testid="estimate-chip" title="the core cost model\'s upper estimate, not a measurement">'
                                         f'{est_txt} · {tail}</span>')
        else:
            self.estimate_chip.object = '<span class="chip grey">≈ – </span>'
        running = job is not None and job.status == "running"
        n_invalid = sum(1 for j in v.get("junctions", []) if not j["ok"])
        reason = ""
        self.run_btn.css_classes = ["btn-primary", "t-run"]
        if running and job.cancel_event.is_set():
            self.run_btn.name, self.run_btn.disabled = "■ Cancelling…", True
            self.run_btn.css_classes = ["btn-danger", "t-run"]
            reason = "cancel requested · stops before the next step"
        elif running:
            self.run_btn.name, self.run_btn.disabled = "■ Cancel", False
            self.run_btn.css_classes = ["btn-danger", "t-run"]
            cur = job.current_step
            reason = f'running {cur + 1 if cur is not None else 1:02d} of {job.n_steps:02d} · cancel is checked between steps, never mid-step'
        elif not self.steps:
            self.run_btn.name, self.run_btn.disabled, reason = "Run chain", True, "add a stage to run"
        elif n_invalid:
            self.run_btn.name, self.run_btn.disabled = "Run chain", True
            reason = f'{n_invalid} invalid junction{"s" if n_invalid > 1 else ""} · fix the red junction to run'
        elif v.get("held_out"):
            self.run_btn.name, self.run_btn.disabled, reason = "Run chain", True, "the source is held out (M4)"
        elif v.get("recipe_error"):
            self.run_btn.name, self.run_btn.disabled, reason = "Run chain", True, v["recipe_error"]
        elif v.get("over_ceiling"):
            o = v["over_ceiling"][0]
            self.run_btn.name, self.run_btn.disabled = "Run chain", True
            reason = f'stage {o["index"] + 1:02d} exceeds its local ceiling of {o["max_span_samples"]:,} samples (span {v["n_samples"]:,}) · route to HPC (out of slice scope)'
        elif job is not None and job.status == "failed" and stale is None:
            k = (job.error or {}).get("step") or 0
            self.run_btn.name, self.run_btn.disabled = f"↻ Retry from {k + 1:02d}", False
            reason = f"failed at {k + 1:02d}" + ((" · 01 cached" if k == 1 else f" · 01–{k:02d} cached") if k else "")
        elif stale is not None and job is not None:
            self.run_btn.name, self.run_btn.disabled = f"↻ Re-run from {stale + 1:02d}", False
        else:
            self.run_btn.name, self.run_btn.disabled = "▶ Run chain", False
        mode = "cancel" if running else "run"
        if mode != self.run_mode:
            self.run_mode_prev, self.run_mode, self.run_mode_at = self.run_mode, mode, time.time()
        note = ('no span sent from Explore · using the example span (CH4_A2 · 276.4–278.4 h)' if self.is_example else "")
        self.run_reason.object = (f'<div class="mono small" style="display:flex;justify-content:space-between;min-height:14px;margin-left:20px">'
                                  f'<span class="muted">{esc(note)}</span><span data-testid="run-reason" style="color:#b3262b">{esc(reason)}</span></div>')

    # ------------------------------------------------------------------ actions --
    def on_run(self, _=None):
        job = self.job()
        live = job is not None and job.status in ("running", "queued")
        # FIX (critique r1 P0): a click is read by what the button was SHOWING. A click that lands on a "■ Cancel"
        # the 200 ms poll has not repainted yet (or within 600 ms of it turning back into Run) must never start a
        # second run — that wrote duplicate detections.
        showed_cancel = self.run_mode == "cancel" or (self.run_mode_prev == "cancel" and time.time() - self.run_mode_at < 0.6)
        if live:
            ok = self.ctx.manager.cancel(job) if job.status == "running" else False
            self.ctx.toast("cancel requested · the core checks it before the next step" if ok else "the run is queued · cancel it once it starts")
            debug.event("cancel", job_id=job.id, accepted=ok)
            self.refresh()
            return
        if showed_cancel:
            self.ctx.toast("run already finished · nothing was cancelled and no new run was started", "warning", 4000)
            debug.event("stale_cancel", job_id=job.id if job is not None else None, status=job.status if job is not None else None)
            self.refresh()
            return
        v = self.validation(force=True)
        job, why = start_run(self.ctx, v)
        if job is None:
            self.ctx.toast(why, "error")
            return
        self.row_cache.clear()
        self.refresh()
        self.start_poll()
        self.ctx.refresh_chrome()

    def start_poll(self):
        if self.poll is None:
            self.poll = pn.state.add_periodic_callback(self.tick, period=self.poll_ms)

    def stop_poll(self):
        if self.poll is not None:
            try:
                self.poll.stop()
            except Exception:
                pass
            self.poll = None

    def tick(self):
        try:
            self._tick()
        except Exception as exc:     # critique r1 P1: a failing poll stops and says so, never a frozen "running"
            self.stop_poll()
            from .main import error_card
            self.notice.objects = [error_card("run poll (this page stopped following the job; reload to re-attach)", exc, testid="poll-error", margin=(4, 20))]

    def _tick(self):
        job = self.job()
        if job is None:
            self.stop_poll()
            return
        self.refresh()
        for i, pane in self.running_panes.items():
            s = job.steps[i] if i < len(job.steps) else None
            if s and s["status"] == "running" and s.get("started_at"):
                pane.object = self._running_html(i, time.time() - s["started_at"])
        if job.status != "running":
            self.stop_poll()
            self.ctx.refresh_chrome()
            if job.status == "failed":
                self.ctx.toast(f"run failed at {(job.error or {}).get('step', 0) + 1:02d}: {(job.error or {}).get('message', '')[:140]}", "error", 6000)

    def save_template(self, _=None):
        from Working.database.runs import save_template
        conn = corpus.connect(self.ctx.db_path)
        try:
            name = f'{self.ctx.chain["name"]}_{time.strftime("%H%M%S")}'
            tid = save_template(conn, name, self.steps)
        finally:
            conn.close()
        self.ctx.chain = dict(self.ctx.chain, saved=True)
        self.ctx.toast(f"template '{name}' saved (id {tid}) · written to the throwaway database copy", "success")
        self.refresh()

    def toggle_popover(self, which):
        if self.popover.visible and getattr(self, "_pop", None) == which:
            self.popover.visible = False
            return
        self._pop = which
        items = []
        if which == "history":
            job_rows = [j for j in self.ctx.manager.jobs.values() if j.recording["id"] == self.src["recording_id"]]
            items.append(pn.pane.HTML(f'<div class="card-title" data-testid="history-popover">Run history · {esc(self.src.get("channel_name", ""))}</div>'
                                      f'<div class="mono small muted">live jobs in this server process, then runs in the database copy</div>'))
            for j in sorted(job_rows, key=lambda j: -j.id)[:6]:
                items.append(self._history_row(f'job {j.id} · {j.status} · {", ".join(RS.page_name(s) for s in j.recipe["steps"])}',
                                               f'{RS.fmt_timing(j.snapshot()["elapsed_s"])} · recipe {j.config_hash or "–"}', j.recipe))
            for d in RS.history(self.ctx, self.src["recording_id"], limit=10):
                when = str(d.get("started_at") or d.get("created_at") or "")[:16]
                items.append(self._history_row(f'#{d["id"]} · {d["status"]} · {", ".join(x.split(".")[1] for x in d["steps"]) or "recipe unreadable"}',
                                               f'{when} · {d["n_detections"]} detections', d.get("recipe")))
        else:
            items.append(pn.pane.HTML('<div class="card-title" data-testid="import-popover">Import a template</div>'
                                      '<div class="mono small muted">replaces the chain\'s stages; the source stays</div>'))
            for t in RS.templates(self.ctx):
                b = pn.widgets.Button(name="Import", css_classes=["btn"], width=70, margin=(2, 4))
                b.css_classes = ["btn", "t-import-" + t["id"].split(":")[-1]]
                b.on_click(self.ctx.guard("Import template", lambda e, t=t: self.apply_steps(t["steps"], t["name"].split(" ·")[0])))
                items.append(pn.Row(pn.pane.HTML(f'<div class="mono small" style="padding-top:6px">{esc(t["name"])}'
                                                 f'{"" if t["builtin"] else " <span class=muted>· saved</span>"}</div>', sizing_mode="stretch_width"),
                                    b, sizing_mode="stretch_width", margin=0))
        close = pn.widgets.Button(name="close", css_classes=["btn-link"], width=60, margin=(0, 0))
        close.on_click(self.ctx.guard("close", lambda e: setattr(self.popover, "visible", False)))
        self.popover.objects = items + [close]
        self.popover.visible = True

    def _history_row(self, title, sub, recipe):
        b = pn.widgets.Button(name="Apply to source", css_classes=["btn"], width=130, margin=(2, 4),
                              disabled=recipe is None, description=None if recipe else "recipe unreadable")
        if recipe is not None:
            b.on_click(self.ctx.guard("Apply to source", lambda e: self.apply_steps([{"stage": s["stage"], "algorithm": s["algorithm"], "params": s.get("params") or {},
                                                    "side_inputs": s.get("side_inputs") or {}} for s in recipe["steps"]], None)))
        return pn.Row(pn.pane.HTML(f'<div class="mono small" style="padding-top:2px">{esc(title)}</div><div class="mono small muted">{esc(sub)}</div>',
                                   sizing_mode="stretch_width"), b, sizing_mode="stretch_width", margin=(2, 0))

    def apply_steps(self, steps, name):
        self.popover.visible = False
        self.ctx.chain = dict(self.ctx.chain, steps=copy.deepcopy(steps), saved=False, **({"name": name} if name else {}))
        self.ctx.stale_from = 0 if self.job() is not None else None
        self.row_cache.clear()
        self.refresh()
        self.ctx.toast("stages replaced · the source is unchanged")

    def delete_step(self, i):
        self.undo_steps = copy.deepcopy(self.steps)
        name = RS.page_name(self.steps[i])
        steps = [s for k, s in enumerate(self.steps) if k != i]
        undo = pn.widgets.Button(name="Undo", css_classes=["btn"], width=70, margin=(0, 6))
        undo.on_click(self.ctx.guard("Undo", lambda e: (self.set_steps(self.undo_steps, i), setattr(self.notice, "objects", []))))
        self.notice.objects = [pn.pane.HTML(f'<div class="mono small" style="padding:7px 0 0 20px">{i + 1:02d} {esc(name)} deleted</div>'), undo]
        self.set_steps(steps, i)

    def duplicate_step(self, i):
        steps = copy.deepcopy(self.steps)
        steps.insert(i + 1, copy.deepcopy(steps[i]))
        self.set_steps(steps, i + 1)

    def insert_step(self, position, name, open_settings=False):
        spec = RS.catalog()[name]
        step = {"stage": spec["stage"], "algorithm": spec["algorithm"], "params": {}, "side_inputs": {}}
        steps = copy.deepcopy(self.steps)
        steps.insert(position, step)
        self.modal_holder.objects = []
        self.set_steps(steps, position)
        self.ctx.toast(f"inserted {spec['page_name']} at {position + 1:02d}")
        if open_settings:
            self.ctx.navigate(f"analyse/block/{position}")

    def open_insert(self, position):
        from .modal import insert_modal
        self.modal_holder.objects = [insert_modal(self, position)]

    # ------------------------------------------------------------------ rows --
    def _running_html(self, i, elapsed):
        return (f'<div data-testid="running-{i + 1}" style="padding:4px 2px"><div class="runbar"></div>'
                f'<div class="mono small" style="margin-top:6px;color:var(--blue-600)">running · {RS.page_name(self.steps[i])} · {elapsed:.1f} s elapsed · '
                f'the core reports per step, so this bar is indeterminate</div></div>')

    def _icons(self, i):
        b_set = pn.widgets.Button(name="⚙", css_classes=["icon-btn", "on"], width=26, margin=(0, 2), description="open settings (block page)")
        b_byp = pn.widgets.Button(name="⊘", css_classes=["icon-btn"], width=26, margin=(0, 2), disabled=True, description="bypass · not in this slice")
        b_dup = pn.widgets.Button(name="⧉", css_classes=["icon-btn"], width=26, margin=(0, 2), description="duplicate")
        b_del = pn.widgets.Button(name="✕", css_classes=["icon-btn"], width=26, margin=(0, 2), description="delete")
        g = self.ctx.guard
        b_set.on_click(g(f"open settings {i + 1:02d}", lambda e: self.ctx.navigate(f"analyse/block/{i}")))
        b_dup.on_click(g(f"duplicate {i + 1:02d}", lambda e: self.duplicate_step(i)))
        b_del.on_click(g(f"delete {i + 1:02d}", lambda e: self.delete_step(i)))
        for b, k in ((b_set, "settings"), (b_dup, "duplicate"), (b_del, "delete")):
            b.css_classes = b.css_classes + [f"t-{k}-step-{i + 1}"]
        return pn.Row(b_set, b_byp, b_dup, b_del, margin=(6, 0, 0, 0))

    def _ghost_for(self, i, rows, src_payload):
        for k in range(i - 1, -1, -1):
            p = rows[k]["payload"]
            if p and p.get("type") == "signal":
                return p
        return src_payload

    def _plot(self, i, row, rows, src_payload, info):
        st = row["status"]
        job = self.job()
        if st == "running":
            pane = pn.pane.HTML(self._running_html(i, time.time() - (row.get("started_at") or time.time())), sizing_mode="stretch_width",
                                height=ROW_H - 10, margin=0)
            self.running_panes[i] = pane
            info["type"] = "running"
            return pane
        if st == "waiting":
            k = job.current_step if job is not None and job.current_step is not None and job.current_step < i else i - 1
            info["type"] = "waiting"
            return pn.pane.HTML(f'<div class="waits" style="height:{ROW_H - 12}px" data-testid="waits-{i + 1}">⌛ waits for {k + 1:02d} · last result hidden</div>',
                                sizing_mode="stretch_width", margin=0)
        if st == "failed" and job is not None:
            return self._error_card(i, job, info)
        if st in ("cancelled", "blocked", "new", "invalid") or row["payload"] is None:
            msg = {"cancelled": "cancelled · the core checks cancel between steps; this step never started",
                   "blocked": "blocked · an earlier step failed, so this one never ran",
                   "invalid": f"invalid junction · {row.get('invalid_reason') or ''}",
                   "new": "not run yet · Run chain to see this block's result"}.get(st, "no result")
            if st == "cached" and row.get("cache_only"):
                msg = "in the step cache · no run attached to this view · Run chain reads it back in ~0 s"
            if row.get("over_ceiling"):
                msg = "over the local ceiling for this span · would route to HPC (out of slice scope)"
            info["type"] = st
            return pn.pane.HTML(f'<div class="waits" style="height:{ROW_H - 12}px">{esc(msg)}</div>', sizing_mode="stretch_width", margin=0)
        payload = row["payload"]
        ghost = self._ghost_for(i, rows, src_payload) if payload.get("type") in ("signal", "spanset") else None
        view = renderer.render(payload, self.x_range, ROW_H - 8, ghost=ghost, info=info)
        self._link(view)
        if st == "stale":
            return pn.Column(pn.pane.HTML('<span class="chip amber" style="height:20px;font-size:10.5px" data-testid="stale-pill">◷ last run shown · stale</span>',
                                          margin=(0, 0, 2, 0)),
                             pn.Column(view, styles={"opacity": "0.5"}, sizing_mode="stretch_width", margin=0),
                             sizing_mode="stretch_width", margin=0)
        return view

    def _link(self, view):
        from bokeh.models import CrosshairTool
        for obj in ([view] if not hasattr(view, "objects") else view.objects):
            fig = getattr(obj, "object", None)
            if fig is not None and hasattr(fig, "x_range") and fig.x_range is self.x_range:
                fig.add_tools(CrosshairTool(overlay=self.hover, dimensions="height"))

    def _error_card(self, i, job, info):
        err = job.error or {}
        el = job.steps[i].get("elapsed_s") or 0
        view_log = pn.widgets.Button(name="View log", css_classes=["btn"], width=90, margin=(0, 4))
        open_set = pn.widgets.Button(name="Open settings", css_classes=["btn"], width=120, margin=(0, 4))
        retry = pn.widgets.Button(name=f"↻ Retry {i + 1:02d}", css_classes=["btn-primary"], width=110, margin=(0, 4))
        log_pane = pn.pane.HTML("", visible=False, sizing_mode="stretch_width", margin=0)

        def show_log(e):
            log_pane.object = f'<pre class="mono" style="font-size:10.5px;max-height:220px;overflow:auto;white-space:pre-wrap;color:#7f1d1d">{esc(chr(10).join(job.log_lines) or err.get("traceback") or "no log lines")}</pre>'
            log_pane.visible = not log_pane.visible
        view_log.on_click(self.ctx.guard("View log", show_log))
        open_set.on_click(self.ctx.guard("Open settings", lambda e: self.ctx.navigate(f"analyse/block/{i}")))
        retry.on_click(self.ctx.guard("Retry", self.on_run))
        info["type"] = "failed"
        return pn.Column(
            pn.pane.HTML(f'<div data-testid="error-card"><div style="font-weight:600;color:#b3262b">{i + 1:02d} {esc(RS.page_name(self.steps[i]))} failed after {el:.1f} s</div>'
                         f'<div class="mono small" style="margin-top:3px">{esc(str(err.get("message", "")))[:400]}</div>'
                         f'<div class="mono small muted" style="margin-top:3px">adapter {esc(str(err.get("adapter") or RS.step_name(self.steps[i])))} · recipe {esc(str(job.config_hash or "–"))}'
                         f'{" · db run #" + str(job.db_run_id) if job.db_run_id else ""} · traceback in log</div></div>', sizing_mode="stretch_width", margin=(0, 0, 4, 0)),
            pn.Row(view_log, open_set, retry, margin=0), log_pane,
            sizing_mode="stretch_width", margin=0, styles={"background": "#fff7f7", "border-radius": "8px", "padding": "8px 10px"})

    # Row geometry (horizontal): card margin 20 + 1 px border | left column LEFT_W, margin 12/6 | plot column margin 4/12.
    # The footer axis is built through _frame() too, so its plot frame lines up with every row's (critique r1 P1).
    def _frame(self, left_objs, plot, *, vpad=8, css=("card",), styles=None):
        left = pn.Column(*left_objs, width=LEFT_W, margin=(vpad, 6, vpad, 12))
        return pn.Row(left, pn.Column(plot, sizing_mode="stretch_width", margin=(vpad, 12, vpad, 4)), sizing_mode="stretch_width",
                      css_classes=list(css), margin=(0, 20), styles=styles or {})

    def _row(self, label_num, title, badge, sig, caption, icons, plot, testid, failed=False, invalid=False):
        head = pn.pane.HTML(f'<div class="row-left" data-testid="{testid}"><h4><span class="num">{label_num}</span>{esc(title)}</h4>'
                            f'<div style="margin-top:4px">{badge}<span class="sig">{esc(sig)}</span></div>'
                            f'<div class="cap" data-testid="{testid}-caption">{esc(caption)}</div></div>', sizing_mode="stretch_width", margin=0)
        # the failed/invalid outline is drawn as an inset shadow so the border width (and the plot frame) never shifts
        styles = {"box-shadow": "inset 0 0 0 1.5px #e5484d", "border-color": "#e5484d"} if (failed or invalid) else {}
        return self._frame([head] + ([icons] if icons is not None else []), plot, styles=styles)

    def _pill(self, position, label="+ insert"):
        b = pn.widgets.Button(name=label, css_classes=["pill-insert", f"t-insert-{position}"], width=150 if "end" in label else 90, margin=(3, 0))
        b.on_click(self.ctx.guard("insert stage", lambda e: self.open_insert(position)))
        return pn.Row(pn.layout.HSpacer(), b, pn.layout.HSpacer(), sizing_mode="stretch_width", margin=0)

    def _junction(self, i, j):
        comp = chain_mod.compatible_at(self.steps, i)
        first = next((r["name"] for r in comp["rows"] if r["ok"]), None)
        prev = f'{i:02d} {RS.page_name(self.steps[i - 1])}' if i > 0 else "Source"
        exp = chain_mod.TYPE_LABEL.get(j["expected"], j["expected"])
        prod = chain_mod.TYPE_LABEL.get(j["producing"], j["producing"])
        items = [pn.pane.HTML(f'<span class="junction" data-testid="junction-error">⊗ {i + 1:02d} {esc(RS.page_name(self.steps[i]))} needs {esc(str(exp))} · '
                              f'{esc(prev)} emits {esc(str(prod))}</span>', margin=(4, 6))]
        if first:
            b = pn.widgets.Button(name=f"+ Insert {RS.catalog()[first]['page_name']} here", css_classes=["btn"], width=260, margin=(2, 4))
            b.on_click(self.ctx.guard("insert stage", lambda e: self.insert_step(i, first)))
            items.append(b)
        show = pn.widgets.Button(name="Show blocks that fit", css_classes=["btn"], width=160, margin=(2, 4))
        show.on_click(self.ctx.guard("show blocks that fit", lambda e: self.open_insert(i)))
        items.append(show)
        return pn.Row(pn.layout.HSpacer(), *items, pn.layout.HSpacer(), sizing_mode="stretch_width", margin=(4, 0))

    def refresh(self):
        v = self.validation()
        job = self.job()
        rows = RS.derive_rows(self.steps, job, self.ctx.stale_from, v)
        self.update_toolbar(v, rows)
        self.running_panes = {k: p for k, p in self.running_panes.items() if k < len(rows) and rows[k]["status"] == "running"}
        objs = []
        debug_rows = []
        # ---- source row ----
        skey = ("source", json.dumps(self.src, sort_keys=True), self.throw)
        if skey not in self.row_cache:
            info = {}
            try:
                if self.throw:
                    raise RuntimeError("deliberate render failure (?throw=1) inside the first row's renderer")
                sp = source_payload(self.ctx, self.src)
                plot = renderer.render(sp, self.x_range, ROW_H - 8, info=info)
                self._link(plot)
            except Exception as exc:
                if self.uncaught:
                    raise
                from .main import error_card
                sp = None
                plot = error_card("Source row renderer", exc)
                info = {"type": "render-error"}
            fs = float(self.src.get("fs") or 1)
            dur = (self.src["end_idx"] - self.src["start_idx"]) / fs
            cap = f'{esc(self.src.get("label") or "signal span")} · {dur / 60:.1f} min · {fs:g} Hz' if dur < 3 * 3600 else f'{dur / 3600:.1f} h · {fs:g} Hz'
            self.row_cache[skey] = (self._row("●", "Source", badge_html({"status": "cached"}, "row-badge-0"), "— → Signal", cap, None, plot, "chain-row-0"),
                                    sp, info)
        src_row, src_payload, src_info = self.row_cache[skey]
        objs.append(src_row)
        debug_rows.append(dict(src_info, index=-1, status="cached"))
        objs.append(self._pill(0))
        # ---- step rows ----
        for i, (step, row) in enumerate(zip(self.steps, rows)):
            j = v["junctions"][i] if i < len(v.get("junctions", [])) else None
            if j is not None and not j["ok"]:
                objs.append(self._junction(i, j))
            spec = RS.catalog().get(RS.step_name(step), {})
            payload = row["payload"]
            sig = (i, RS.step_name(step), json.dumps(step.get("params"), sort_keys=True, default=str), row["status"],
                   id(payload), row.get("timing"), row.get("invalid_reason"), row.get("over_ceiling"),
                   job.id if job is not None else None, len(self.steps), job.current_step if job is not None else None)
            cached = self.row_cache.get(("step", i))
            if cached is None or cached[0] != sig or row["status"] == "running":
                if cached is not None and cached[0] == sig and row["status"] == "running":
                    objs.append(cached[1]); debug_rows.append(cached[2]); objs.append(self._pill(i + 1, "+ insert · end of chain" if i == len(self.steps) - 1 else "+ insert"))
                    continue
                info = {}
                try:     # critique r1 P1: every step row's renderer is caught per row, not only the Source row's
                    if self.throw_row and i == 1:
                        raise RuntimeError("deliberate render failure (?throw=row) inside step row 02's renderer")
                    plot = self._plot(i, row, rows, src_payload, info)
                except Exception as exc:
                    if self.uncaught:
                        raise
                    from .main import error_card
                    plot = error_card(f"{i + 1:02d} {RS.page_name(step)} renderer", exc, margin=0)
                    info = {"type": "render-error", "error": f"{type(exc).__name__}: {exc}"}
                caption = (payload.get("summary") if payload and row["status"] in ("cached", "stale") else None) or RS.param_caption(step)
                badge = badge_html(row, f"row-badge-{i + 1}")
                view = self._row(f"{i + 1:02d}", spec.get("page_name", RS.step_name(step)), badge, spec.get("signature", "?"), caption,
                                 self._icons(i), plot, f"chain-row-{i + 1}", failed=row["status"] == "failed", invalid=row["status"] == "invalid")
                info.update(index=i, status=row["status"], badge=BADGE_LABEL[row["status"]], timing=row.get("timing"))
                self.row_cache[("step", i)] = (sig, view, info)
            objs.append(self.row_cache[("step", i)][1])
            debug_rows.append(self.row_cache[("step", i)][2])
            objs.append(self._pill(i + 1, "+ insert · end of chain" if i == len(self.steps) - 1 else "+ insert"))
        for k in [k for k in self.row_cache if k[0] == "step" and k[1] >= len(self.steps)]:
            del self.row_cache[k]
        self.rows_col.objects = objs
        self.update_footer(v, rows, job)
        debug.put("rows", {"steps": [RS.step_name(s) for s in self.steps], "rows": debug_rows, "stale_from": self.ctx.stale_from,
                           "job": job.id if job is not None else None, "job_status": job.status if job is not None else None,
                           "step_timings": job.step_timings if job is not None else None, "run_label": self.run_btn.name,
                           "run_disabled": self.run_btn.disabled, "junctions_invalid": sum(1 for j in v.get("junctions", []) if not j["ok"])})

    # ------------------------------------------------------------------ footer --
    def _build_footer(self):
        ax = C.base_figure(height=26, x_range=self.x_range, y_range=Range1d(0, 1), grid=False, y_axis=False)
        ax.min_border_left = ax.min_border_right = renderer.LEFT_BORDER
        ax.min_border_top, ax.min_border_bottom = 0, 18
        ax.outline_line_color = None
        C.time_axis(ax)
        self.footer_text = pn.pane.HTML("", sizing_mode="stretch_width", margin=0)
        self.export_btn = pn.widgets.Button(name="⤓ Export run", css_classes=["btn"], width=120, margin=(0, 4))
        self.export_btn.on_click(self.ctx.guard("Export run", self.export))
        handoff1 = pn.widgets.Button(name="→ Analyse events", css_classes=["btn"], width=150, margin=(0, 4), disabled=True, description="not in this slice")
        self.handoff2 = pn.widgets.Button(name="→ Pass to Review", css_classes=["btn-primary"], width=170, margin=(0, 4), disabled=True,
                                          description="Review is outside this slice")
        self.axis_pane = pn.pane.Bokeh(ax, sizing_mode="stretch_width", margin=0)
        self.footer = pn.Column(
            self._frame([pn.pane.HTML('<div class="mono small muted" style="padding-top:4px" data-testid="shared-axis">all rows share this time axis</div>',
                                      sizing_mode="stretch_width", margin=0)], self.axis_pane, vpad=0, css=("card", "axis-row")),
            pn.Row(self.footer_text, self.export_btn, handoff1, self.handoff2, sizing_mode="stretch_width", css_classes=["card"],
                   margin=(4, 20, 24, 20), styles={"padding": "10px 14px"}),
            sizing_mode="stretch_width", margin=0)

    def update_footer(self, v, rows, job):
        chip, kind = RS.terminal_wording(v.get("terminal_kind"), v.get("terminal_label"))
        self.handoff2.name = "→ Pass to Review"
        n_invalid = sum(1 for j in v.get("junctions", []) if not j["ok"])
        if n_invalid:
            line = '<b>Chain is invalid</b><div class="mono small muted">fix the red junction · validation runs on every edit</div>'
        elif job is None:
            line = '<b>No run yet</b><div class="mono small muted">Run chain executes the untouched core against the database copy</div>'
        elif job.status == "running":
            line = f'<b>Running · job {job.id}</b><div class="mono small muted">{job.snapshot()["elapsed_s"]:.1f} s · recipe {job.config_hash}</div>'
        elif job.status == "failed":
            k = (job.error or {}).get("step")
            line = (f'<b>No result</b><div class="mono small muted">job {job.id}{" · db run #" + str(job.db_run_id) if job.db_run_id else ""} failed at '
                    f'{(k or 0) + 1:02d} · nothing was written to detections</div>')
        elif job.status == "cancelled":
            line = f'<b>Cancelled</b><div class="mono small muted">job {job.id} · steps after the cancel never started</div>'
        else:
            last = job.payloads.get(job.n_steps - 1) or {}
            core = sum((job.step_timings or {}).values())
            line = (f'<b>last run · {esc(last.get("summary", "done"))}</b><div class="mono small muted">job {job.id} · db run #{job.db_run_id} · '
                    f'{job.detections_written or 0} written to detections · {RS.fmt_timing(core) or "0 s"} core · '
                    f'{job.snapshot()["elapsed_s"]:.1f} s wall · no null (surrogate off)</div>')
            if last.get("type") == "spanset":
                self.handoff2.name = f'→ Pass {last.get("n", 0)} to Review'
        self.footer_text.object = (f'<div style="display:flex;gap:18px;align-items:center" data-testid="footer-terminal">'
                                   f'<span class="chip {kind}">{esc(chip)}</span><div style="border-left:1px solid var(--border);padding-left:16px">{line}</div></div>')
        self.export_btn.disabled = job is None or job.status == "running" or bool(n_invalid)

    def export(self, _=None):
        job = self.job()
        if job is None:
            return
        path = RS.export_job(self.ctx, job)
        debug.put("last_export", {"path": path, "job_id": job.id})
        self.ctx.toast(f"exported run to exports/{os.path.basename(path)}", "success", 6000)


def chain_page(ctx):
    return ChainView(ctx).page


def block_page(ctx, index: int):
    from .blockpage import block_page as _bp
    return _bp(ctx, index)
