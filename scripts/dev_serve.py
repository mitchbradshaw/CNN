"""
dev_serve.py
============
Boot the app on a known port, against a THROWAWAY COPY of the real
database, so a browser — yours or an agent's — can look at it.

    python scripts/dev_serve.py
    python scripts/dev_serve.py --port 5007 --empty

Why this exists rather than `panel serve UI/serve.py --show`: that command
opens `DATA/db/annotations.sqlite` and `DATA/db/ui_session.json`, the real
ones. An agent driving a browser will click Delete, will save an
annotation, will reorder something — that is what exercising a UI means —
and the project's never-touch-the-real-DB rule exists because those
writes are not recoverable. This copies the database to a temp file first
and points the session state at a temp file too, so every such write lands
somewhere disposable and the real data is opened read-once, at startup.

The copy is real data, so what you see on screen is representative:
real recordings, real annotations, real row counts. It is discarded when
you stop the server.

Use with `chrome-devtools` or `playwright` MCP (see `.mcp.json`): start
this, then point the browser at the URL it prints.
"""

import argparse
import atexit
import os
import shutil
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

REAL_DB = os.path.join(_REPO_ROOT, "DATA", "db", "annotations.sqlite")


def _scratch_db(empty):
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", prefix="devserve-", delete=False)
    tf.close()
    atexit.register(lambda: os.path.exists(tf.name) and os.unlink(tf.name))
    if empty or not os.path.isfile(REAL_DB):
        from Working.database.schema import init_db
        init_db(tf.name).close()
        print(f"[dev_serve] empty scratch database at {tf.name}")
    else:
        shutil.copyfile(REAL_DB, tf.name)
        print(f"[dev_serve] copied {REAL_DB}\n[dev_serve]     -> {tf.name} (throwaway)")
    return tf.name


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=5006)
    ap.add_argument("--empty", action="store_true",
                    help="start from an empty schema instead of a copy of the real database")
    ap.add_argument("--show", action="store_true", help="open a browser window too")
    args = ap.parse_args()

    import panel as pn
    import holoviews as hv
    hv.extension("bokeh")

    import UI.viewer.session as _sessionmod
    from UI.viewer import ViewerApp

    sf = tempfile.NamedTemporaryFile(suffix=".json", prefix="devserve-session-", delete=False)
    sf.close()
    os.unlink(sf.name)  # absent to start, like a first run
    atexit.register(lambda: os.path.exists(sf.name) and os.unlink(sf.name))
    _sessionmod.SESSION_STATE_PATH = sf.name

    db_path = _scratch_db(args.empty)
    app = ViewerApp(db_path=db_path)

    print(f"[dev_serve] session state at {sf.name} (throwaway)")
    print(f"[dev_serve] serving on http://127.0.0.1:{args.port}")
    print("[dev_serve] the real database is NOT open; nothing you click here can reach it.")
    pn.serve(app.layout(), port=args.port, show=args.show,
             address="127.0.0.1", allow_websocket_origin=[f"127.0.0.1:{args.port}",
                                                          f"localhost:{args.port}"],
             title="Mycelium Signal Viewer (dev)")


if __name__ == "__main__":
    main()
