"""Loud failure (critique r1 P1). Panel swallows a Python exception raised in a widget callback, a periodic
callback or a Bokeh ``on_change``: it reaches server.log and nothing reaches the browser. Every such entry
point in B is therefore wrapped here, and a failure draws a red card the user can see.

UI-level on purpose (Panel import) — the service layer stays untouched."""
from __future__ import annotations

import functools
import html
import logging
import traceback

import panel as pn

log = logging.getLogger("protoB")


def error_card(label: str, exc: BaseException, testid: str = "render-error", margin=(12, 20)) -> pn.pane.HTML:
    tb = "".join(traceback.format_exception(exc))
    log.error("render error in %s\n%s", label, tb)
    return pn.pane.HTML(f'<div class="error-card" data-testid="{testid}"><h3>⚠ {html.escape(label)} failed</h3>'
                        f'<div class="mono">{html.escape(type(exc).__name__)}: {html.escape(str(exc))}</div><pre>{html.escape(tb)}</pre></div>',
                        sizing_mode="stretch_width", margin=margin)


def guarded(ctx, label: str, fn):
    """Wrap a callback so an exception becomes a visible banner card (+ toast) instead of a log line."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # loud: the browser must see it
            ctx.fail(label, exc)
            return None
    return wrapper
