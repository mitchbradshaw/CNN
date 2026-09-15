"""App factory: one Panel session = one ``AppContext`` (source span, chain draft, run manager
handle) and a hash router that swaps the workspace column in place.

Routes (URL hash): ``#explore/corpus``, ``#explore/signal/<channel_id>``, ``#analyse/chain``,
``#analyse/block/<index>``; anything else renders the inert card for that workspace. A query
inside the hash (``#analyse/chain?throw=1``) is parsed into ``ctx.query``.
"""
from __future__ import annotations

import html
import logging
import traceback

import panel as pn
import param

from . import shell
from .shell import header_pane, inert_page, rail_pane
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


def error_card(label: str, exc: BaseException, testid: str = "render-error") -> pn.pane.HTML:
    tb = "".join(traceback.format_exception(exc))
    log.error("render error in %s\n%s", label, tb)
    return pn.pane.HTML(f'<div class="error-card" data-testid="{testid}"><h3>⚠ {html.escape(label)} failed to render</h3>'
                        f'<div class="mono">{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</div><pre>{html.escape(tb)}</pre></div>',
                        sizing_mode="stretch_width", margin=(12, 20))


def make_app(rt):
    ctx = AppContext(rt)
    rail = rail_pane("explore")
    ctx._rail = rail
    content = pn.Column(sizing_mode="stretch_width", margin=0)
    root = pn.Row(rail, content, sizing_mode="stretch_width", margin=0, css_classes=["pb-app"])

    rendered = {"hash": None}

    def render(*_):
        rendered["hash"] = pn.state.location.hash
        ws, page, arg, query = _parse_hash(pn.state.location.hash)
        ctx.query = query
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
    content[:] = [pn.pane.HTML('<div class="pb-page muted mono">loading…</div>')]
    return root
