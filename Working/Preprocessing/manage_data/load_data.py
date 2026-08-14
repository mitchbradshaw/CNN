"""
load_data.py
=============
Loading of source recordings, derived per-channel splits, subsamples and
window label-index files.

Data layout
-----------
    DATA/raw/                              immutable source .mat recordings
    DATA/derived/channels/<rec>/CH<n>.npy  per-channel splits
    DATA/derived/subsamples/               cut-down .mat subsamples
    DATA/derived/windows/<scale>_fs<fs>/   labelled window datasets

Filename resolution
-------------------
`load_raw_data` still takes the same **bare filename** it always has, e.g.
"M2_concat_fs1_CH2.npy" or "0.01_percent_M2_concat_fs1.mat". `resolve_data_path`
maps that name onto wherever the file now lives, so every existing call site
keeps working after the DATA restructure. Passing an explicit relative or
absolute path also works and bypasses resolution.
"""

import numpy as np
import scipy.io
import glob
import os
import re

# ── Repo-root-relative data roots ────────────────────────────────────────────
DATA_ROOT   = "DATA"
RAW_DIR     = os.path.join(DATA_ROOT, "raw")
DERIVED_DIR = os.path.join(DATA_ROOT, "derived")
CHANNEL_DIR = os.path.join(DERIVED_DIR, "channels")
SUBSAMPLE_DIR = os.path.join(DERIVED_DIR, "subsamples")
WINDOW_DIR  = os.path.join(DERIVED_DIR, "windows")

_CH_RE = re.compile(r"^(?P<rec>.+)_CH(?P<ch>\d+)\.npy$", re.IGNORECASE)


def window_root(timescale, fs):
    """Path to the window dataset root for a given scale and sample rate.

    e.g. window_root(10, 1.0) -> "DATA/derived/windows/10min_fs1.0"
    """
    return os.path.join(WINDOW_DIR, f"{timescale:g}min_fs{fs}")


def resolve_data_path(filename):
    """
    Map a bare data filename onto its location in the DATA tree.

    Resolution order:
      1. An explicit path that already exists (returned unchanged)
      2. Per-channel split   "<rec>_CH<n>.npy" -> derived/channels/<rec>/CH<n>.npy
      3. Source recording                      -> raw/<filename>
      4. Subsample                             -> derived/subsamples/<filename>
      5. Recursive glob under DATA/ as a last resort

    Raises FileNotFoundError listing every location tried.
    """
    if os.path.exists(filename):
        return filename

    tried = []

    m = _CH_RE.match(os.path.basename(filename))
    if m:
        p = os.path.join(CHANNEL_DIR, m.group("rec"), f"CH{m.group('ch')}.npy")
        if os.path.exists(p):
            return p
        tried.append(p)

    for base in (RAW_DIR, SUBSAMPLE_DIR, DATA_ROOT):
        p = os.path.join(base, os.path.basename(filename))
        if os.path.exists(p):
            return p
        tried.append(p)

    hits = glob.glob(os.path.join(DATA_ROOT, "**", os.path.basename(filename)),
                     recursive=True)
    if hits:
        return hits[0]

    raise FileNotFoundError(
        f"Could not locate data file '{filename}'. Tried:\n  "
        + "\n  ".join(tried)
        + f"\n  (and a recursive glob under {DATA_ROOT}/)"
    )


def load_start_indices(folder_name):
    # function returns the three arrays stored in the label folder for folder_name
    # in order: array of interesting, not interesting and flag starting indexes
    # from .mat files formatted as [folder_name]_interesting_..., [folder_name]_notinteresting_..., [folder_name]_flag
    # variable in .mat file containing indexes is called idx_vec
    # also derive fs from file name and return that number too

    def find_and_load(keyword):
        # Label files live in DATA/derived/windows/<scale>min_fs<fs>/labels/.
        # fs is not known until we read a filename, so glob across scales.
        scale = folder_name.removesuffix("min")
        pattern = os.path.join(WINDOW_DIR, f"{scale}min_fs*", "labels",
                               f"{folder_name}_{keyword}_*.mat")
        matches = glob.glob(pattern)
        if not matches:
            raise FileNotFoundError(f"No file found matching: {pattern}")
        mat = scipy.io.loadmat(matches[0])
        return mat["idx_vec"].flatten(), matches[0]

    interesting, path_i = find_and_load("interesting")
    notinteresting, _ = find_and_load("notinteresting")
    flag, path_f = find_and_load("flag")

    # Extract fs from filename, e.g. "10min_interesting_fs_1.00.mat" -> 1.00
    fs_match = re.search(r"fs_(\d+(?:\.\d+)?)", os.path.basename(path_i))
    fs = float(fs_match.group(1)) if fs_match else None

    return interesting, notinteresting, flag, fs


def load_raw_data(filename, fs, matname="x"):
    # returns the time-series data x stored in filename
    # also returns t, the time points based on sampling freq fs
    # supports .mat and .npy files, determined from the filename extension
    path = resolve_data_path(filename)
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".npy":
        x = np.load(path).flatten()
    elif ext == ".mat":
        x = scipy.io.loadmat(path)[matname].flatten()
    else:
        raise ValueError(f"Unsupported file type '{ext}' for '{filename}'. Expected .mat or .npy.")

    t = np.arange(len(x)) / fs
    return x, t


def cut_raw_data(filename, fs, percent, matname="x"):
    # cuts a larger dataset to the first specified 'percent'age and saves the
    # smaller dataset to DATA/derived/subsamples/ (it is derived, not source)
    mat = scipy.io.loadmat(resolve_data_path(filename))
    x = mat[matname].flatten()
    t = np.arange(len(x)) / fs

    cut = int(np.floor(percent * len(x)))
    x = x[:cut]
    t = t[:cut]

    filename = f"{percent}_percent_{os.path.basename(filename)}"

    os.makedirs(SUBSAMPLE_DIR, exist_ok=True)
    scipy.io.savemat(os.path.join(SUBSAMPLE_DIR, filename), {matname: x})
    return x, t
