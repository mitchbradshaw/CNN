"""Process-wide evidence the smoke test reads over ``GET /b/debug`` (it runs in another process,
so it cannot see ``pn.state.cache`` directly). Pages write here; nothing here is read back by
the app. Keys: ``zoom_stats`` (per-viewport refetch timings), ``heatmap`` (renderer row counts of
the coverage map), ``rows`` (per chain row: payload type + glyph row counts), ``events``."""
from __future__ import annotations

import threading
import time

import panel as pn

_LOCK = threading.Lock()


def put(key: str, value):
    with _LOCK:
        pn.state.cache[key] = value


def append(key: str, value, cap: int = 500):
    with _LOCK:
        lst = pn.state.cache.setdefault(key, [])
        lst.append(value)
        del lst[:-cap]


def event(msg: str, **kw):
    append("events", dict(kw, msg=msg, ts=time.time()), cap=200)


def snapshot(rt) -> dict:
    with _LOCK:
        cache = {k: v for k, v in pn.state.cache.items() if k in ("zoom_stats", "heatmap", "rows", "events", "block", "signal", "last_export")}
    out = dict(cache)
    out["runtime"] = rt.describe()
    bv = pn.state.cache.get("block_fig")
    if bv is not None:
        try:
            out["block_geometry"] = bv.geometry()
        except Exception as e:  # pragma: no cover
            out["block_geometry_error"] = str(e)
    try:
        from .main import get_manager
        m = get_manager(rt)
        out["jobs"] = [{"job_id": j.id, "status": j.status, "step_timings": j.step_timings,
                        "steps": [{k: s.get(k) for k in ("status", "elapsed_s", "cached", "kind", "summary")} for s in j.steps]}
                       for j in m.jobs.values()]
    except Exception as e:  # pragma: no cover
        out["jobs_error"] = str(e)
    return out
