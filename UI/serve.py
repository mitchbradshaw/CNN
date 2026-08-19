"""
serve.py
========
The `panel serve` entry point.

    panel serve UI/serve.py --show

This module exists so that exactly one module in the repo builds the
application at import time, and it is a module nothing imports by accident.

`UI/app.py` used to end with a bare `create_app().servable(...)`, which meant
`import UI.app` constructed a whole `ViewerApp`, opened the database and mmap'd
the first recording's channel `.npy`. The cost of that was paid three times
over:

- Ten test files import the app package. With the database empty or the channel
  data absent they failed at **collection**, before their own
  `_channel_available()` skip guards could run. That is the mechanism that
  quarantined an innocent T01 in run-20260816-1943 and put 36 tickets into
  `BLOCKED_UPSTREAM`, and the same mechanism made an empty channel directory
  read as "505 passed" in run-20260817-1157.
- It forced the orchestrator to junction 317 MB of real recordings into every
  worktree purely so that `import` would succeed, which is the only reason the
  writable-recordings isolation tradeoff in `ORCHESTRATOR_SPEC.md §Isolation`
  had to be accepted at all.
- It is very likely why `tests/_session_isolation.py` had to exist.

Raised in `FOLLOWUPS.md` on 2026-08-16 and again as a blocker on 2026-08-17.

`UI/app.py` is now importable without side effects: it defines `create_app()`
and builds nothing. Anything that wants a running application either serves
this module or calls `pn.serve(create_app, ...)` itself.
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
# Duplicated from app.py rather than imported, because the import that would
# fetch it is the very thing that needs the path to already be set.
import sys as _sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from UI.app import create_app

create_app().servable(title="Mycelium Signal Viewer")
