"""
_session_isolation.py
=======================
Shared test helper: every test that constructs a `UI.app.ViewerApp`
must not read or write the real session file at
`Working.config.SESSION_STATE_PATH` (Part E9) -- that file is real
persistent UI state, not test fixture data, and a test-created
`ViewerApp` restoring (or overwriting) leftover state from an unrelated
database is exactly the cross-test contamination that broke
tests/test_filters.py and tests/test_ui_selection.py the first time E9
was wired up: a fresh test app picked up a stale filter/tag restriction
saved by a completely different test's database and silently returned
fewer rows than the test expected.

Use as:
    with scratch_session_file():
        app = ViewerApp(db_path=...)
        ...
"""

import os
import tempfile
from contextlib import contextmanager

import UI.app as _appmod


@contextmanager
def scratch_session_file():
    tf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tf.close()
    os.unlink(tf.name)  # start absent, like a real first run
    orig = _appmod.SESSION_STATE_PATH
    _appmod.SESSION_STATE_PATH = tf.name
    try:
        yield tf.name
    finally:
        _appmod.SESSION_STATE_PATH = orig
        if os.path.exists(tf.name):
            os.unlink(tf.name)
