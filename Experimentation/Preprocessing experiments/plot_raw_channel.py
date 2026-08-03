
# ── Repo-root bootstrap ───────────────────────────────────────────────────────
# Makes `Working.*` / `Pipelines.*` importable when this file is run directly.
# Walks up to the directory containing Working/, so it survives future moves.
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import os
import numpy as np
from Working.Preprocessing.manage_data.load_data import load_raw_data
from Working.Catalogue.gramian.gramian_calc import plot_gramian_suite
from matplotlib import pyplot as py

FOLDER   = "DATA/derived/channels"
FILENAME = "M2_concat_fs1_CH2.npy"
FS       = 1.0   # Hz (matches folder name)

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
x, t = load_raw_data(FILENAME,FS,"VECTOR")
x = x * 1000
t = t / 3600

full = False
# plot channel

if full:
    py.plot(t,x)
    py.xlabel("Time (hr)")
    py.ylabel("Signal (mV)")
    py.show()

else:
    # plot partial
    sthr = 230
    len = 50

    sidx = int(sthr * 3600)
    eidx = int(sidx + len * 60)
    t = t[sidx:eidx]
    x = x[sidx:eidx]

    py.plot(t,x)
    py.xlabel("Time (hr)")
    py.ylabel("Signal (mV)")
    py.show()