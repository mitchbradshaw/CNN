"""
_calibration_isolation.py
=========================
Shared test helper: every test that triggers cost calibration must redirect
`cost.CALIBRATION_PATH` away from the real `DATA/db/*_calibration.json`, the
same way `tests/_session_isolation.py` protects the real UI session file.

This replaces two divergent copies of an `_IsolatedCalibration` class that
each did:

    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)          # <-- name released before it is used
    cost.CALIBRATION_PATH = path

Removing the file hands the *name* back to the OS while the test goes on to
use it, and one of the two copies never deleted the file it created. Both are
avoided here by owning a whole temp directory for the duration and pointing
the module at a path inside it: the directory guarantees the name, and the
file is absent-not-empty on entry, which is what `_load_calibration()`
expects.

Use as:

    from tests._calibration_isolation import scratch_calibration

    with scratch_calibration(cost):
        cost.calibrate()
        ...

Several modules can be isolated at once — each gets its own file:

    with scratch_calibration(wm_cost, mp_cost):
        ...
"""

import os
import tempfile
from contextlib import contextmanager


@contextmanager
def scratch_calibration(*cost_modules):
    """Point every given cost module's `CALIBRATION_PATH` at a fresh file in a
    private temp directory, and restore the originals on exit.

    Yields the temp directory path, for tests that want to assert on what was
    written.
    """
    if not cost_modules:
        raise ValueError("scratch_calibration() needs at least one cost module")

    originals = [(m, m.CALIBRATION_PATH) for m in cost_modules]
    tmpdir = tempfile.mkdtemp(prefix="calibration_iso_")
    try:
        for i, mod in enumerate(cost_modules):
            name = getattr(mod, "__name__", "cost").replace(".", "_")
            mod.CALIBRATION_PATH = os.path.join(tmpdir, f"{name}_{i}.json")
        yield tmpdir
    finally:
        for mod, original in originals:
            mod.CALIBRATION_PATH = original
        for entry in os.listdir(tmpdir):
            try:
                os.remove(os.path.join(tmpdir, entry))
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
