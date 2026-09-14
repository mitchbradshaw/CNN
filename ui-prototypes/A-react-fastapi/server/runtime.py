"""Runtime isolation for prototype A (task brief, hard rule 2).

Everything the core could write is redirected under
``ui-prototypes/A-react-fastapi/runtime/<stamp>/`` before any run happens:

* the database — a **copy** of ``DATA/db/annotations.sqlite`` (the
  ``scripts/dev_serve.py`` pattern); every ``execute_recipe`` call and every
  query is pointed at the copy, never at the real file;
* ``Working.config.STEP_CACHE_ROOT`` — an absolute temp directory. The core
  reads it *at call time* inside ``_execute_recipe_with_conn``, so rebinding
  the attribute on ``Working.config`` redirects the step cache without editing
  the core. ``STEP_CACHE_WRITE_THRESHOLD_S`` is lowered to 0.0 so that even
  sub-second steps on a short span are cached and the "suffix re-run hits the
  prefix cache" checklist item is meaningful;
* ``Adapters.detection_matrix_profile.RESULTS_DIR``,
  ``Adapters.preprocessing_window_matrix.RESULTS_DIR`` and
  ``Adapters.catalogue_classifier.MODEL_ROOT`` — the three module-level
  paths the adapters' persist hooks / run bodies read at call time.

``DATA/`` itself is only ever read (``np.load(..., mmap_mode="r")``).
``UI.viewer.session`` (whose ``SESSION_STATE_PATH`` points at the old tree's
``DATA/db/ui_session.json``) is never imported by this server.

Nothing here imports Panel, HoloViews, Bokeh or matplotlib.
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil
import sys

PROTO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # .../A-react-fastapi
REPO_ROOT = os.path.dirname(os.path.dirname(PROTO_DIR))                     # worktree root
REAL_DB = os.path.join(REPO_ROOT, "DATA", "db", "annotations.sqlite")
HELD_OUT_FILE = "M4_aug_concat_fs1.mat"


class Runtime:
    """One throwaway runtime per server start."""

    def __init__(self, stamp: str | None = None):
        stamp = stamp or _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.stamp = stamp
        self.dir = os.path.join(PROTO_DIR, "runtime", stamp)
        self.db_path = os.path.join(self.dir, "annotations.sqlite")
        self.step_cache_root = os.path.join(self.dir, "step_cache")
        self.results_dir = os.path.join(self.dir, "results")
        self.models_dir = os.path.join(self.dir, "models")
        self.log_path = os.path.join(self.dir, "server.log")
        self.exports_dir = os.path.join(self.dir, "exports")

    def setup(self) -> "Runtime":
        if os.getcwd().lower() != REPO_ROOT.lower():
            # recordings.npy_path is repo-relative; the core np.load()s it as-is.
            os.chdir(REPO_ROOT)
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)

        for d in (self.dir, self.step_cache_root, self.results_dir, self.models_dir, self.exports_dir):
            os.makedirs(d, exist_ok=True)

        if not os.path.isfile(REAL_DB):
            raise SystemExit(f"real database not found at {REAL_DB}; is the DATA junction in place?")
        shutil.copyfile(REAL_DB, self.db_path)

        import Working.config as cfg
        cfg.STEP_CACHE_ROOT = self.step_cache_root
        cfg.STEP_CACHE_WRITE_THRESHOLD_S = 0.0

        import Adapters.detection_matrix_profile as _mp
        import Adapters.preprocessing_window_matrix as _wm
        import Adapters.catalogue_classifier as _cc
        _mp.RESULTS_DIR = os.path.join(self.results_dir, "matrix_profile")
        _wm.RESULTS_DIR = os.path.join(self.results_dir, "window_matrix")
        _cc.MODEL_ROOT = self.models_dir
        self.meta_dir = os.path.join(self.dir, "meta")
        os.makedirs(self.meta_dir, exist_ok=True)
        # Critique r1 P0: an adapter executed outside these redirects writes into the real DATA
        # tree. Assert every writable path the adapters read at call time is inside this runtime.
        for label, p in (("STEP_CACHE_ROOT", cfg.STEP_CACHE_ROOT), ("matrix_profile.RESULTS_DIR", _mp.RESULTS_DIR),
                         ("window_matrix.RESULTS_DIR", _wm.RESULTS_DIR), ("classifier.MODEL_ROOT", _cc.MODEL_ROOT)):
            if not os.path.abspath(p).lower().startswith(os.path.abspath(self.dir).lower()):
                raise SystemExit(f"refusing to start: {label} = {p} is outside the runtime dir {self.dir}")
        return self

    def describe(self) -> dict:
        return {
            "repo_root": REPO_ROOT,
            "real_db": REAL_DB,
            "db_copy": self.db_path,
            "step_cache_root": self.step_cache_root,
            "results_dir": self.results_dir,
            "models_dir": self.models_dir,
            "log_path": self.log_path,
            "meta_dir": getattr(self, "meta_dir", None),
            "held_out_file": HELD_OUT_FILE,
            "cwd": os.getcwd(),
        }
