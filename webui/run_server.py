"""Start the web UI bridge against a throwaway copy of the database.

    .venv/Scripts/python.exe run_server.py [--port 8765]

Runs with cwd = the repo root (recordings.npy_path is repo-relative) and
redirects every writable path into runtime/<stamp>/ (see server/runtime.py).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from server.runtime import Runtime  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("WEBUI_PORT", "8765")))
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    # Fail loudly on a busy port instead of appearing to start (REPORT §8: old servers linger).
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex((args.host, args.port)) == 0:
            raise SystemExit(f"port {args.port} on {args.host} is already in use; pass --port or set WEBUI_PORT")

    rt = Runtime().setup()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stderr), logging.FileHandler(rt.log_path, encoding="utf-8")])
    log = logging.getLogger("webui")
    for k, v in rt.describe().items():
        log.info("%s = %s", k, v)
    log.info("the real database is NOT open; every write lands in the copy")

    from server.app import create_app
    import uvicorn
    app = create_app(rt)
    log.info("serving on http://%s:%d  (API docs at /api/docs)", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
