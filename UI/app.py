"""
app.py
=======
Panel entry point for the signal viewer + annotation UI.

    panel serve UI/app.py --show
    python UI/app.py

The application itself lives in `UI/viewer/` (the viewer and annotation
surfaces) and `UI/analyse/` (the "Run algorithm" tab). This module is only the
entry point: the repo-root bootstrap that lets `panel serve` find `Working/`,
and the one call that makes the layout servable.

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


create_app().servable(title="Mycelium Signal Viewer")

if __name__ == "__main__":
    pn.serve(create_app, show=True, title="Mycelium Signal Viewer")
