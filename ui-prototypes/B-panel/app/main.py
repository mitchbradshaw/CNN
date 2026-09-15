"""App factory: one Panel session = one ``AppContext`` (source span, chain draft, run manager
handle) and a hash router that swaps the workspace column in place.

Routes (URL hash): ``#explore/corpus``, ``#explore/signal/<channel_id>``, ``#analyse/chain``,
``#analyse/block/<index>``; anything else renders the inert card for that workspace. A query
inside the hash (``#analyse/chain?throw=1``) is parsed into ``ctx.query``.
"""
from __future__ import annotations

import html
import logging

import panel as pn
import param

from . import shell
from .shell import header_pane, inert_page, rail_pane
from .guard import error_card, guarded  # noqa: F401  (error_card re-exported: pages import it from here)
from .theme import THEME_CSS  # re-exported for run_app.py

log = logging.getLogger("protoB")

_MANAGER = None  # one RunManager per server process (jobs live in memory, like A)

EXAMPLE_SOURCE = {"recording_id": 4, "channel_name": "CH4_A2", "source_file": "M2_aug_concat_fs1.mat", "fs": 1.0,
                  "start_idx": 995040, "end_idx": 1002240, "label": "example span"}


def get_manager(rt):
    global _MANAGER
    if _MANAGER is None:
        from server.runs import RunManager
        _MANAGER = RunManager(rt.db_path, meta_dir=getattr(rt, "meta_dir", None))
    return _MANAGER


class AppContext(param.Parameterized):
    """Per-session state. Mirrors A's state.tsx: the source span handed from Explore to
    Analyse, the chain draft, the last job id — held in this object, not on disk."""
    source = param.Dict(default=None, allow_None=True)          # {recording_id, channel_name, source_file, fs, start_idx, end_idx, label}
    chain = param.Dict(default=None)                            # {name, saved, steps:[{stage,algorithm,params,side_inputs}], lastRunJobId}
    stale_from = param.Integer(default=None, allow_None=True)
    explore = param.Dict(default={"file": "M2_aug_concat_fs1.mat", "channel_id": 4, "view": None, "colour_by": "both"})

    def __init__(self, rt, **kw):
        super().__init__(**kw)
        self.rt = rt
        self.db_path = rt.db_path
        self.manager = get_manager(rt)
        self.query: dict = {}
        self.job_ids: list[int] = []            # jobs started in this browser session
        self.applied_params: dict = {}          # block page: params as of the last run, for Revert
        self._header = None
        self._rail = None
        self._ws = "explore"
        self._page_cleanup: list = []           # periodic callbacks to stop on navigation
        self.banner = pn.Column(sizing_mode="stretch_width", margin=0)   # loud-failure cards for callbacks (guard.py)
        self.route = ("explore", "", None)
        if self.chain is None:
            self.chain = {"name": "mp_threshold", "saved": False, "lastRunJobId": None, "steps": [
                {"stage": "preprocessing", "algorithm": "detrend", "params": {"mode": "rolling_mean", "window_s": 600.0}},
                {"stage": "detection", "algorithm": "matrix_profile", "params": {"window_min": 1.0, "backend": "stump"}},
                {"stage": "detection", "algorithm": "threshold", "params": {"threshold": 8.0}},
            ]}

    # ---- navigation + chrome ------------------------------------------------------------
    def navigate(self, target: str):
        pn.state.location.hash = "#" + target.lstrip("#")

    def live_jobs(self) -> int:
        return sum(1 for j in self.manager.jobs.values() if j.status == "running")

    def need_you(self) -> int:
        return sum(1 for jid in self.job_ids if (j := self.manager.jobs.get(jid)) is not None and j.status == "failed")

    def header(self, workspace: str, page: str, subtitle: str = "") -> pn.pane.HTML:
        pane = header_pane(workspace, page, subtitle, self.need_you())
        self._header = (pane, workspace, page, subtitle)
        return pane

    def refresh_chrome(self):
        """Header chip "N need you" and rail "Jobs · N" are live counts; pages call this when a job changes."""
        if self._header:
            pane, ws, pg, sub = self._header
            pane.object = shell.header_html(ws, pg, sub, self.need_you())
        if self._rail is not None:
            self._rail.object = shell.rail_html(self._ws, live_jobs=self.live_jobs())

    def on_leave(self, fn):
        self._page_cleanup.append(fn)

    # ---- loud failure (critique r1 P1) ----------------------------------------------------
    def fail(self, label: str, exc: BaseException):
        card = error_card(label, exc, testid="callback-error", margin=(8, 20))
        close = pn.widgets.Button(name="dismiss", css_classes=["btn-link"], width=70, margin=(0, 20))
        row = pn.Column(card, close, sizing_mode="stretch_width", margin=0)
        close.on_click(lambda e: self.banner.remove(row) if row in self.banner.objects else None)
        self.banner.objects = [row] + list(self.banner.objects)[:2]
        self.toast(f"{label} failed: {type(exc).__name__}: {str(exc)[:160]}", "error", 8000)

    def guard(self, label: str, fn):
        return guarded(self, label, fn)

    # ---- URL state (critique r1 P1: reload / second tab) -----------------------------------
    STATE_KEYS = ("rid", "s0", "s1", "job")

    def state_query(self) -> dict:
        q = {}
        if self.source:
            q.update(rid=str(int(self.source["recording_id"])), s0=str(int(self.source["start_idx"])), s1=str(int(self.source["end_idx"])))
        jid = (self.chain or {}).get("lastRunJobId")
        if jid is not None:
            q["job"] = str(int(jid))
        return q

    def hydrate(self, query: dict):
        """Rebuild the session's source span and run link from the hash query. Jobs live in this server
        process, so a reload (or a second tab) re-attaches to a running or completed job."""
        try:
            if all(k in query for k in ("rid", "s0", "s1")):
                rid, s0, s1 = int(query["rid"]), int(query["s0"]), int(query["s1"])
                cur = self.source or {}
                if (cur.get("recording_id"), cur.get("start_idx"), cur.get("end_idx")) != (rid, s0, s1):
                    from server import corpus
                    conn = corpus.connect(self.db_path)
                    try:
                        rec = corpus.recording_row(conn, rid)
                    finally:
                        conn.close()
                    if rec is not None:
                        self.source = {"recording_id": rid, "channel_name": rec["name"], "source_file": rec["source_file"], "fs": float(rec["fs"]),
                                       "start_idx": s0, "end_idx": s1, "label": "span from URL"}
                        self.stale_from = None
            if "job" in query:
                jid = int(query["job"])
                job = self.manager.jobs.get(jid)
                if job is not None and jid != self.chain.get("lastRunJobId"):
                    steps = [{"stage": st["stage"], "algorithm": st["algorithm"], "params": dict(st.get("params") or {}),
                              **({"side_inputs": st["side_inputs"]} if st.get("side_inputs") else {})} for st in job.recipe["steps"]]
                    same = [(a["stage"], a["algorithm"]) for a in self.chain["steps"]] == [(b["stage"], b["algorithm"]) for b in steps]
                    self.chain = dict(self.chain, lastRunJobId=jid, **({} if same else {"steps": steps, "name": f"job {jid} chain", "saved": False}))
                    self.stale_from = None
                    if jid not in self.job_ids:
                        self.job_ids.append(jid)
        except (ValueError, TypeError) as e:
            log.warning("ignoring malformed state in the URL hash %r: %s", query, e)

    def sync_hash(self):
        """Write source span + last job into the hash query of analyse pages, without re-rendering."""
        ws, page, arg = self.route
        if ws != "analyse":
            return
        keep = {k: v for k, v in self.query.items() if k not in self.STATE_KEYS}
        q = dict(keep, **self.state_query())
        path = "/".join(x for x in (ws, page, None if arg is None else str(arg)) if x)
        new = "#" + path + ("?" + "&".join(f"{k}={v}" for k, v in q.items()) if q else "")
        if pn.state.location is not None and pn.state.location.hash != new:
            self.query = q
            pn.state.location.hash = new

    def toast(self, msg: str, kind: str = "info", ms: int = 3500):
        try:
            getattr(pn.state.notifications, kind if kind in ("info", "success", "warning", "error") else "info")(msg, duration=ms)
        except Exception:  # notifications need pn.extension(notifications=True)
            log.info("toast: %s", msg)


def _parse_hash(h: str):
    h = (h or "").lstrip("#")
    query = {}
    if "?" in h:
        h, qs = h.split("?", 1)
        for kv in qs.split("&"):
            if kv:
                k, _, v = kv.partition("=")
                query[k] = v
    parts = [p for p in h.strip("/").split("/") if p]
    ws = parts[0] if parts else "explore"
    page = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else None
    return ws, page, arg, query


def make_app(rt):
    ctx = AppContext(rt)
    rail = rail_pane("explore")
    ctx._rail = rail
    content = pn.Column(sizing_mode="stretch_width", margin=0)
    root = pn.Row(rail, pn.Column(ctx.banner, content, sizing_mode="stretch_width", margin=0), sizing_mode="stretch_width", margin=0,
                  css_classes=["pb-app"])

    rendered = {"hash": None, "key": None}

    def render(*_):
        rendered["hash"] = pn.state.location.hash
        ws, page, arg, query = _parse_hash(pn.state.location.hash)
        key = (ws, page, arg, tuple(sorted((k, v) for k, v in query.items() if k not in ctx.STATE_KEYS)))
        state = {k: v for k, v in query.items() if k in ctx.STATE_KEYS}
        if key == rendered["key"] and state == ctx.state_query():
            ctx.query = query          # our own sync_hash wrote the state keys: nothing to rebuild
            return
        rendered["key"] = key
        ctx.query = query
        ctx.route = (ws, page, arg)
        ctx.banner.objects = []
        if ws == "analyse":
            ctx.hydrate(query)
        for fn in ctx._page_cleanup:
            try:
                fn()
            except Exception:
                log.exception("page cleanup failed")
        ctx._page_cleanup = []
        ctx._ws = ws
        ctx._header = None
        rail.object = shell.rail_html(ws, live_jobs=ctx.live_jobs())
        uncaught = query.get("uncaught") == "1"      # loud-failure evidence: behave exactly as if this try/except were absent
        try:
            if ws == "explore":
                from . import explore
                view = explore.signal_page(ctx, int(arg)) if page == "signal" and arg else explore.corpus_page(ctx)
            elif ws == "analyse":
                from . import analyse
                view = analyse.block_page(ctx, int(arg)) if page == "block" and arg is not None else analyse.chain_page(ctx)
            else:
                view = inert_page(ws)
        except Exception as exc:  # loud: never a blank column
            if uncaught:
                raise
            view = pn.Column(header_pane(ws.capitalize(), page or ""), error_card(f"{ws} workspace", exc), sizing_mode="stretch_width")
        content[:] = [view]
        try:
            ctx.sync_hash()
        except Exception:
            log.exception("sync_hash failed")

    pn.state.location.param.watch(render, "hash")

    def first():
        # FRICTION: the browser's hash reaches the server as a property patch from the client-side
        # Location model, and that patch can arrive AFTER onload fires. Setting a default hash here
        # immediately clobbers a deep link (#analyse/chain became #explore/corpus), so wait a beat.
        def decide():
            if not pn.state.location.hash:
                pn.state.location.hash = "#explore/corpus"
            elif not rendered["hash"]:
                render()
        if pn.state.location.hash:
            if not rendered["hash"]:
                render()
        else:
            pn.state.curdoc.add_timeout_callback(decide, 500)
    pn.state.onload(first)
    # critique r1 P2: Escape closes an open pn.Modal. A11yDialog only hears keydown inside its (shadow-DOM) dialog, and focus
    # never lands there, so a document-level listener clicks the open dialog's own close button (which syncs open=False).
    try:
        from bokeh.models import CustomJS
        pn.state.curdoc.js_on_event("document_ready", CustomJS(code="""
            if (window.__pbEscape) return;
            window.__pbEscape = true;
            const deep = (root, sel, out) => { if (!root || !root.querySelectorAll) return out; out.push(...root.querySelectorAll(sel));
                for (const el of root.querySelectorAll('*')) if (el.shadowRoot) deep(el.shadowRoot, sel, out); return out; };
            document.addEventListener('keydown', (e) => {
                if (e.key !== 'Escape') return;
                for (const d of deep(document, '.dialog-container', [])) {
                    if (d.style.display !== 'none') { const b = d.querySelector('.pnx-dialog-close'); if (b) b.click(); }
                }
            });
        """))
    except Exception:
        log.exception("could not install the Escape handler")
    content[:] = [pn.pane.HTML('<div class="pb-page muted mono">loading…</div>')]
    return root
