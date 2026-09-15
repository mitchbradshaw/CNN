"""Prototype B — Panel 1.9.3 + Bokeh 3.9.2, in-process over the untouched core.

    "/c/ProgramData/anaconda3/python.exe" run_app.py [--port 8766]

Reuses prototype A's UI-free service modules (runtime isolation, decimation, the seven-type
serialiser, chain helpers, run manager, corpus queries) by importing ``../A-react-fastapi``
as a package root — so B measures the *frontend* difference only: the same core, the same
seam, a Python-native renderer instead of a JS one. Nothing here is served over HTTP except
Panel's own Bokeh websocket. Every writable path is redirected exactly as in A.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
A_DIR = os.path.join(os.path.dirname(HERE), "A-react-fastapi")
for p in (HERE, A_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from server.runtime import Runtime  # noqa: E402  (A's service layer)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PROTO_B_PORT", "8766")))
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    rt = Runtime().setup()          # chdir to the worktree root, copy the DB, redirect every writable path
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(rt.log_path, encoding="utf-8")])
    log = logging.getLogger("protoB")
    for k, v in rt.describe().items():
        log.info("%s = %s", k, v)
    log.info("the real database is NOT open; every write lands in the copy")

    import panel as pn
    from app.main import make_app, THEME_CSS

    pn.extension(raw_css=[THEME_CSS], notifications=True)
    log.info("serving on http://127.0.0.1:%d", args.port)
    pn.serve(lambda: make_app(rt), port=args.port, address="127.0.0.1", show=args.show,
             allow_websocket_origin=[f"127.0.0.1:{args.port}", f"localhost:{args.port}"],
             title="Underground Brains — prototype B (Panel)", threaded=False)


if __name__ == "__main__":
    main()
