"""
app.py
=======
Panel entry point for the signal viewer + annotation UI.

    panel serve UI/serve.py --show
    python UI/app.py

The application itself lives in `UI/viewer/` (the viewer and annotation
surfaces) and `UI/analyse/` (the "Run algorithm" tab). This module is only the
entry point: the repo-root bootstrap that lets `panel serve` find `Working/`,
and the factory that builds the layout.

**Importing this module must not build the application.** It used to end with a
bare `create_app().servable(...)` at module scope, so `import UI.app` opened the
database and mmap'd a channel `.npy`. Every test file that imported it then
failed at *collection* whenever that data was absent — before its own skip
guards could run — which is how run-20260816-1943 quarantined an innocent T01
and put 36 tickets into BLOCKED_UPSTREAM, and why the orchestrator had to
junction 317 MB of real recordings into every worktree just to make `import`
succeed. The servable call now lives in `UI/serve.py`, which is the one module
whose import is *meant* to have that side effect.

Panel/HoloViews/Bokeh are imported here and under `UI/` only — everything in
`Working/`, `Adapters/` and `Pipelines/` stays headless, which is what allows
the core to run on the cluster and under pytest without a display.
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import panel as pn

from UI.viewer import ViewerApp


def create_app():
    return ViewerApp().layout()


if __name__ == "__main__":
    pn.serve(create_app, show=True, title="Mycelium Signal Viewer")
