"""
harness.py
==========
The scratch application under test, and the served-app context manager.

Everything in `tests/ui/` drives a REAL browser against a REAL Panel
server. That is the whole point: the headless construction tests in
`tests/` assert that a pane exists and its `.object` is not `None`, which
is what this codebase added after a broken `DynamicMap` twice rendered as
a silently blank pane. A non-`None` HoloViews object still renders blank
if the Bokeh model it produces throws in the browser, and no Python-side
assertion can see that. Only a browser can.

Two rules this module exists to enforce, both non-negotiable and both
already project policy (`CLAUDE.md`, `UI/README.md`):

1. **Never the real database.** Every served app gets a fresh temp sqlite
   seeded here. `DATA/db/annotations.sqlite` is never opened.
2. **Never the real session file.** `Working.config.SESSION_STATE_PATH`
   holds real persistent UI state; a test app that restores or overwrites
   it is the cross-test contamination `tests/_session_isolation.py` was
   written to stop.

The channel `.npy` files ARE the real ones, opened read-only via mmap.
They are large, immutable inputs — copying them per test would cost
minutes and buy nothing.
"""

import os
import socket
import sys
import tempfile
import time
from contextlib import contextmanager

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# The channel the UI suite drives. Same file the headless suite gates on,
# so "real data present" means the same thing in both places.
REAL_CHANNEL_PATH = os.path.join(
    PROJECT_ROOT, "DATA", "derived", "channels", "M2_aug_concat_fs1", "CH0.npy")
REAL_CHANNEL_PATH_CH1 = os.path.join(
    PROJECT_ROOT, "DATA", "derived", "channels", "M2_aug_concat_fs1", "CH1.npy")
REAL_L = 2_595_600
REAL_FS = 1.0
CENTER = 12_300  # inside the channel, near real annotations


def channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def free_port():
    """Ask the OS for a port rather than incrementing a counter.

    Panel's own testing guide increments a module-level PORT. Under
    `pytest -n auto` that hands the same number to several workers at
    once and one of them dies with EADDRINUSE partway through a run,
    which reads as a flaky UI test rather than as a port collision.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def seed_scratch_db():
    """A fresh sqlite with two channels of one real recording and a
    handful of annotations/reviewed spans near `CENTER`, so every surface
    has something to render. Returns the db path; caller unlinks it."""
    from Working.database.schema import init_db
    from Working.database import queries as q

    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(
        conn, "UITEST_M2_aug_concat_fs1.mat", 0, REAL_FS, REAL_L, 0, REAL_CHANNEL_PATH)
    if os.path.isfile(REAL_CHANNEL_PATH_CH1):
        # A second channel so the cross-channel peek select has a real
        # option to pick — an empty dropdown exercises nothing.
        q.insert_recording(
            conn, "UITEST_M2_aug_concat_fs1.mat", 1, REAL_FS, REAL_L, 0, REAL_CHANNEL_PATH_CH1)
    for i in range(5):
        s = CENTER + i * 100
        q.insert_annotation(conn, rid, s, s + 50, "interesting", source=q.SOURCE_MANUAL_UI)
        q.insert_reviewed_span(conn, rid, s, s + 50, source=q.SOURCE_MANUAL_UI)
    conn.close()
    return tf.name


@contextmanager
def served_app(db_path=None, port=None, timeout=60.0):
    """Serve a `ViewerApp` on a background thread and yield its URL.

    Yields `(url, app)`. The app object is handed back deliberately: a
    test that needs to drive state directly (set a zoom range, select a
    channel) should do it in Python and then ASSERT in the browser,
    rather than simulating a mouse gesture on a Bokeh canvas — canvas
    coordinates are not addressable by Playwright and any test that tries
    is testing the test.
    """
    import panel as pn
    import holoviews as hv
    hv.extension("bokeh")

    from UI.viewer import ViewerApp
    import UI.viewer.session as _sessionmod

    owns_db = db_path is None
    if owns_db:
        db_path = seed_scratch_db()

    # Scratch session file, absent to start, like a real first run.
    sf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    sf.close()
    os.unlink(sf.name)
    orig_session_path = _sessionmod.SESSION_STATE_PATH
    _sessionmod.SESSION_STATE_PATH = sf.name

    port = port or free_port()
    app = ViewerApp(db_path=db_path)
    layout = app.layout()
    server = pn.serve(layout, port=port, threaded=True, show=False,
                      address="127.0.0.1", allow_websocket_origin=[f"127.0.0.1:{port}"])
    try:
        _wait_for_port(port, timeout)
        yield f"http://127.0.0.1:{port}", app
    finally:
        try:
            server.stop()
        except Exception:
            pass
        _sessionmod.SESSION_STATE_PATH = orig_session_path
        if os.path.exists(sf.name):
            os.unlink(sf.name)
        try:
            app.conn.close()
        except Exception:
            pass
        if owns_db and os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except OSError:
                pass  # Windows keeps a handle briefly; the temp dir gets it


def _wait_for_port(port, timeout):
    """Poll until the Bokeh server accepts a connection.

    `time.sleep(0.2)` — what Panel's own docs suggest — is a guess that
    holds on an idle laptop and does not hold on a loaded CI box or under
    `-n auto`. Polling turns a timing-dependent failure into a
    deterministic one.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"Panel server did not come up on port {port} within {timeout}s")
