"""App factory: one Panel session = one ``AppContext`` (source span, chain draft, run manager
handle) and a hash router that swaps the workspace column in place.

Routes (URL hash): ``#explore/corpus``, ``#explore/signal/<channel_id>``, ``#analyse/chain``,
``#analyse/block/<index>``; anything else renders the inert card for that workspace.
"""
from __future__ import annotations

import logging
import traceback

import panel as pn
import param

from .shell import header_pane, inert_page, rail_pane
from .theme import THEME_CSS  # re-exported for run_app.py

log = logging.getLogger("protoB")

_MANAGER = None  # one RunManager per server process (jobs live in memory, like A)


def get_manager(rt):
    global _MANAGER
    if _MANAGER is None:
        from server.runs import RunManager
        _MANAGER = RunManager(rt.db_path, meta_dir=getattr(rt, "meta_dir", None))
    return _MANAGER


class AppContext(param.Parameterized):
    """Per-session state. Mirrors A's state.tsx: the source span handed from Explore to
    Analyse, the chain draft, the last job id — persisted in the URL hash + a dict, not on disk."""
    source = param.Dict(default=None, allow_None=True)          # {recording_id, channel_name, source_file, fs, start_idx, end_idx, label}
    chain = param.Dict(default=None)                            # {name, saved, steps:[{stage,algorithm,params,side_inputs}], lastRunJobId}
    stale_from = param.Integer(default=None, allow_None=True)
    explore = param.Dict(default={"file": "M2_aug_concat_fs1.mat", "channel_id": 4, "view": None, "colour_by": "both"})

    def __init__(self, rt, **kw):
        super().__init__(**kw)
        self.rt = rt
        self.db_path = rt.db_path
        self.manager = get_manager(rt)
        if self.chain is None:
            self.chain = {"name": "mp_threshold", "saved": False, "lastRunJobId": None, "steps": [
                {"stage": "preprocessing", "algorithm": "detrend", "params": {"mode": "rolling_mean", "window_s": 600.0}},
                {"stage": "detection", "algorithm": "matrix_profile", "params": {"window_min": 1.0, "backend": "stump"}},
                {"stage": "detection", "algorithm": "threshold", "params": {"threshold": 8.0}},
            ]}

    def navigate(self, target: str):
        pn.state.location.hash = "#" + target.lstrip("#")


def _parse_hash(h: str):
    h = (h or "").lstrip("#").strip("/")
    parts = [p for p in h.split("/") if p]
    ws = parts[0] if parts else "explore"
    page = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else None
    return ws, page, arg


def _error_card(label: str, exc: BaseException) -> pn.pane.HTML:
    tb = "".join(traceback.format_exception(exc))
    log.error("render error in %s\n%s", label, tb)
    return pn.pane.HTML(f'<div class="error-card" data-testid="render-error"><h3>⚠ {label} failed to render</h3>'
                        f'<div class="mono">{type(exc).__name__}: {exc}</div><pre>{tb}</pre></div>', sizing_mode="stretch_width")


def make_app(rt):
    ctx = AppContext(rt)
    rail = rail_pane("explore")
    content = pn.Column(sizing_mode="stretch_width", margin=0)
    root = pn.Row(rail, content, sizing_mode="stretch_width", margin=0, css_classes=["pb-app"])

    def render(*_):
        ws, page, arg = _parse_hash(pn.state.location.hash)
        rail.object = __import__("app.shell", fromlist=["rail_html"]).rail_html(ws, live_jobs=sum(1 for j in ctx.manager.jobs.values() if j.status == "running"))
        try:
            if ws == "explore":
                from . import explore
                view = explore.signal_page(ctx, int(arg)) if page == "signal" and arg else explore.corpus_page(ctx)
            elif ws == "analyse":
                from . import analyse
                view = analyse.block_page(ctx, int(arg)) if page == "block" and arg else analyse.chain_page(ctx)
            else:
                view = inert_page(ws)
        except Exception as exc:  # loud: never a blank column
            view = pn.Column(header_pane(ws.capitalize(), page or ""), _error_card(f"{ws} workspace", exc), sizing_mode="stretch_width")
        content[:] = [view]

    pn.state.location.param.watch(render, "hash")
    if not pn.state.location.hash:
        pn.state.location.hash = "#explore/corpus"
    else:
        render()
    return root
