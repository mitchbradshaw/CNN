"""
materialize_channels.py
========================
One-time (but resumable) extraction of each channel in every
`DATA/raw/*.mat` recording to its own `.npy` file, and a matching row in
the `recordings` table.

Recordings are concatenated end-to-end: a channel's global start offset in
the source vector is `channel_index * L`, where `L` is derived from the
file (never assumed) as `total_samples // n_channels`, after verifying
`total_samples % n_channels == 0`. If it doesn't divide evenly, the file is
skipped and reported rather than silently mis-split.

Handles both plain (`scipy.io.loadmat`) and v7.3/HDF5 (`h5py`) `.mat` files.
Original dtype is preserved — no float32 downcast.

Idempotent / resumable: a channel already on disk with the expected length
is left alone; only missing or wrong-length channels are (re)written.

Usage
-----
    python Pipelines/materialize_channels/materialize_channels.py
    python Pipelines/materialize_channels/materialize_channels.py --status
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import argparse
import glob
import os
import re

import numpy as np
import scipy.io

from Working.Preprocessing.manage_data.load_data import RAW_DIR, CHANNEL_DIR
from Working.database.schema import init_db
from Working.database.queries import insert_recording, list_recordings

N_CHANNELS = 16
_FS_RE = re.compile(r"_fs(\d+(?:\.\d+)?)$", re.IGNORECASE)


def _derive_fs(stem):
    """Derive sample rate from a filename stem, e.g. 'M2_aug_concat_fs2' -> 2.0."""
    m = _FS_RE.search(stem)
    if not m:
        raise ValueError(
            f"Could not derive fs from filename '{stem}' (expected a '_fs<N>' suffix)."
        )
    return float(m.group(1))


def _load_mat_vector(path):
    """Load the single data vector out of a .mat file, raveled to 1-D.

    Tries `scipy.io.loadmat` first (plain/v5-v7 .mat). Falls back to
    `h5py` for v7.3/HDF5 .mat files, which `scipy.io.loadmat` cannot read
    (it raises NotImplementedError).
    """
    try:
        mat = scipy.io.loadmat(path)
        keys = [k for k in mat.keys() if not k.startswith("__")]
        if len(keys) != 1:
            raise ValueError(
                f"Expected exactly one data variable in '{path}', found {keys}."
            )
        return mat[keys[0]].ravel()
    except NotImplementedError:
        import h5py
        with h5py.File(path, "r") as f:
            keys = [k for k in f.keys() if not k.startswith("#")]
            if len(keys) != 1:
                raise ValueError(
                    f"Expected exactly one data variable in '{path}' (HDF5), found {keys}."
                )
            # MATLAB v7.3 stores arrays column-major/transposed relative to
            # how scipy.io.loadmat returns them; ravel collapses either way
            # since these are 1-D (or Nx1) vectors.
            return f[keys[0]][()].ravel()


def detect_channel_count(path):
    """Best-effort suggested channel count for a new file — always
    user-confirmable, never assumed. A CSV's column count is a real
    signal (each column is plausibly one channel); a .mat file's flat
    vector carries no such information, so it just suggests this
    project's established convention (16) as a starting point.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        import pandas as pd
        first_rows = pd.read_csv(path, header=None, nrows=5)
        if first_rows.shape[1] > 1:
            return first_rows.shape[1]
    return N_CHANNELS


def _load_mat_channels(path, n_channels):
    vector = _load_mat_vector(path)
    total = vector.shape[0]
    if total % n_channels != 0:
        raise ValueError(
            f"total_samples={total} is not evenly divisible by n_channels={n_channels} "
            f"({total} % {n_channels} = {total % n_channels})."
        )
    L = total // n_channels
    return [vector[i * L:(i + 1) * L] for i in range(n_channels)]


def _load_csv_channels(path, n_channels):
    import pandas as pd
    df = pd.read_csv(path, header=None)
    if df.shape[1] == 1:
        vector = df.iloc[:, 0].to_numpy()
        total = len(vector)
        if total % n_channels != 0:
            raise ValueError(
                f"total_samples={total} is not evenly divisible by n_channels={n_channels} "
                f"({total} % {n_channels} = {total % n_channels})."
            )
        L = total // n_channels
        return [vector[i * L:(i + 1) * L] for i in range(n_channels)]
    if df.shape[1] != n_channels:
        raise ValueError(
            f"CSV has {df.shape[1]} columns but n_channels={n_channels} was requested "
            "(one column per channel expected when the CSV isn't single-column)."
        )
    return [df.iloc[:, i].to_numpy() for i in range(n_channels)]


def materialize_arbitrary_file(conn, path, n_channels, fs, progress_callback=None):
    """Materialize a user-supplied .mat or .csv file with an explicitly
    confirmed channel count and fs (no assumptions), atomically.

    Every channel is written to a staging directory first; only once *all*
    of them (plus the manifest) have succeeded is the staging directory
    swapped into place with a single atomic `os.replace`, and only then are
    `recordings` rows committed. A failure partway through leaves neither
    orphaned `.npy` files in the final location nor dangling DB rows — the
    staging directory is removed and nothing is registered.

    Parameters
    ----------
    path : str
        Path to the source .mat or .csv file (read-only).
    n_channels, fs : as confirmed/overridden by the caller (e.g. the UI),
        never silently assumed.
    progress_callback : callable(done, total), optional

    Returns
    -------
    dict summary: stem, n_channels, fs, n_samples, dtype
    """
    import datetime
    import json
    import shutil

    stem = os.path.splitext(os.path.basename(path))[0]
    source_file = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()

    if ext == ".mat":
        channels = _load_mat_channels(path, n_channels)
    elif ext == ".csv":
        channels = _load_csv_channels(path, n_channels)
    else:
        raise ValueError(f"Unsupported file type '{ext}'; expected .mat or .csv.")

    lengths = {ch.shape[0] for ch in channels}
    if len(lengths) != 1:
        raise ValueError(f"Channels have inconsistent lengths: {sorted(lengths)}")
    L = lengths.pop()
    dtype = channels[0].dtype

    final_dir = os.path.join(CHANNEL_DIR, stem)
    staging_dir = os.path.join(CHANNEL_DIR, f".staging_{stem}_{os.getpid()}")
    if os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    try:
        for i, chunk in enumerate(channels):
            np.save(os.path.join(staging_dir, f"CH{i}.npy"), chunk)
            if progress_callback:
                progress_callback(i + 1, n_channels)

        manifest = {
            "source_file": source_file,
            "n_channels": n_channels,
            "fs": fs,
            "n_samples_per_channel": L,
            "dtype": str(dtype),
            "imported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with open(os.path.join(staging_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

        if os.path.isdir(final_dir):
            shutil.rmtree(final_dir)
        os.replace(staging_dir, final_dir)
    except Exception:
        if os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir)
        raise

    for i in range(n_channels):
        insert_recording(
            conn, source_file=source_file, channel=i, fs=fs, n_samples=L,
            global_offset=i * L,
            npy_path=os.path.join(final_dir, f"CH{i}.npy").replace(os.sep, "/"),
            commit=False,
        )
    conn.commit()

    return {"stem": stem, "n_channels": n_channels, "fs": fs, "n_samples": L, "dtype": str(dtype)}


def _materialize_one(conn, mat_path):
    stem = os.path.splitext(os.path.basename(mat_path))[0]
    source_file = os.path.basename(mat_path)
    fs = _derive_fs(stem)

    vector = _load_mat_vector(mat_path)
    total = vector.shape[0]
    dtype = vector.dtype

    if total % N_CHANNELS != 0:
        print(
            f"[SKIP] {source_file}: total_samples={total} is not evenly divisible "
            f"by {N_CHANNELS} channels ({total} % {N_CHANNELS} = {total % N_CHANNELS}). "
            "Channel split would be invalid — not proceeding."
        )
        return

    L = total // N_CHANNELS
    print(f"{source_file}: total_samples={total}  n_channels={N_CHANNELS}  L={L}  dtype={dtype}  fs={fs}")

    out_dir = os.path.join(CHANNEL_DIR, stem)
    os.makedirs(out_dir, exist_ok=True)

    for ch in range(N_CHANNELS):
        npy_path = os.path.join(out_dir, f"CH{ch}.npy")
        global_offset = ch * L

        needs_write = True
        if os.path.isfile(npy_path):
            existing = np.load(npy_path, mmap_mode="r")
            if existing.shape[0] == L and existing.dtype == dtype:
                needs_write = False
            existing = None  # release mmap handle

        if needs_write:
            chunk = vector[global_offset:global_offset + L]
            np.save(npy_path, chunk)
            print(f"  [write] CH{ch} -> {npy_path}")
        else:
            print(f"  [skip]  CH{ch} already materialized ({npy_path})")

        insert_recording(
            conn,
            source_file=source_file,
            channel=ch,
            fs=fs,
            n_samples=L,
            global_offset=global_offset,
            npy_path=npy_path.replace(os.sep, "/"),
            commit=False,
        )
    conn.commit()


def materialize_all(raw_dir=None, db_path=None):
    """Materialize every `.mat` recording under `raw_dir` (default
    `DATA/raw`) and record it in the `recordings` table."""
    raw_dir = raw_dir or RAW_DIR
    conn = init_db(db_path)
    mat_files = sorted(glob.glob(os.path.join(raw_dir, "*.mat")))
    if not mat_files:
        print(f"No .mat files found in {raw_dir!r}.")
        return conn
    for mat_path in mat_files:
        _materialize_one(conn, mat_path)
    return conn


def _print_status(db_path=None):
    conn = init_db(db_path)
    rows = list_recordings(conn)
    if not rows:
        print("No recordings materialized yet.")
        return
    by_file = {}
    for r in rows:
        by_file.setdefault(r["source_file"], []).append(r)
    for source_file, recs in sorted(by_file.items()):
        recs.sort(key=lambda r: r["channel"])
        L = recs[0]["n_samples"]
        print(f"{source_file}: {len(recs)} channels, fs={recs[0]['fs']}, L={L}, "
              f"total={L * len(recs)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true",
                         help="Print what has already been materialized and exit.")
    args = parser.parse_args()

    if args.status:
        _print_status()
        return

    materialize_all()


if __name__ == "__main__":
    main()
