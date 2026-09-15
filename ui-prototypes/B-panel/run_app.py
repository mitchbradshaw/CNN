"""Prototype B — Panel 1.9.3 + Bokeh 3.9.2, in-process over the untouched core.

    "/c/ProgramData/anaconda3/python.exe" run_app.py [--port 8766]

Reuses prototype A's UI-free service modules (runtime isolation, decimation, the seven-type
serialiser, chain helpers, run manager, corpus queries) by importing ``../A-react-fastapi``
as a package root — so B measures the *frontend* difference only: the same core, the same
seam, a Python-native renderer instead of a JS one. Nothing here is served over HTTP except
Panel's own Bokeh websocket and one read-only JSON debug route (``/b/debug``) the
out-of-process smoke test reads. Every writable path is redirected exactly as in A, but the
runtime directory itself lives under ``B-panel/runtime/<stamp>/`` (A's ``Runtime`` object,
with its paths re-pointed before ``setup()``), so B never writes into A's folder.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
A_DIR = os.path.join(os.path.dirname(HERE), "A-react-fastapi")
for p in (HERE, A_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from server.runtime import Runtime  # noqa: E402  (A's service layer)


def make_runtime() -> Runtime:
    rt = Runtime()
    rt.dir = os.path.join(HERE, "runtime", rt.stamp)
    rt.db_path = os.path.join(rt.dir, "annotations.sqlite")
    rt.step_cache_root = os.path.join(rt.dir, "step_cache")
    rt.results_dir = os.path.join(rt.dir, "results")
    rt.models_dir = os.path.join(rt.dir, "models")
    rt.log_path = os.path.join(rt.dir, "server.log")
    rt.exports_dir = os.path.join(rt.dir, "exports")
    return rt.setup()   # chdir to the worktree root, copy the DB, redirect + assert every writable path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PROTO_B_PORT", "8766")))
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    rt = make_runtime()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(rt.log_path, encoding="utf-8")])
    log = logging.getLogger("protoB")
    for k, v in rt.describe().items():
        log.info("%s = %s", k, v)
    log.info("the real database is NOT open; every write lands in the copy")

    def _warm():  # STUMPY's numba JIT otherwise costs ~30 s on the first matrix-profile run
        try:
            import numpy as np
            import stumpy
            stumpy.stump(np.random.default_rng(0).standard_normal(256), 8)
            log.info("stumpy JIT warm")
        except Exception as e:  # pragma: no cover
            log.warning("stumpy warm-up skipped: %s", e)
    threading.Thread(target=_warm, daemon=True, name="stumpy-warm").start()

    import panel as pn
    from tornado.web import RequestHandler
    from app.main import make_app, THEME_CSS

    class DebugHandler(RequestHandler):
        """Read-only: what the Python side rendered (renderer row counts, zoom timings, runtime paths)."""
        def get(self):
            from app import debug
            self.set_header("Content-Type", "application/json")
            self.write(json.dumps(debug.snapshot(rt), default=str))

    pn.extension("modal", raw_css=[THEME_CSS], notifications=True)
    log.info("serving on http://127.0.0.1:%d", args.port)
    pn.serve(lambda: make_app(rt), port=args.port, address="127.0.0.1", show=args.show,
             allow_websocket_origin=[f"127.0.0.1:{args.port}", f"localhost:{args.port}"],
             title="Underground Brains — prototype B (Panel)", threaded=False,
             extra_patterns=[(r"/b/debug", DebugHandler)])


if __name__ == "__main__":
    main()
