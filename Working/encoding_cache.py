"""
encoding_cache.py
===================
Cache lookup and storage for computed encodings, keyed on recipe hash —
encodings are expensive and the same one gets re-requested constantly.

Path: `DATA/derived/encodings/<recording>/CH<nn>/<encoding_type>/<hash8>.<ext>`
(`.npy` for arrays, `.txt` for strings/SAX symbol sequences rendered as
text, `.json` for anything else JSON-safe). Lives under `derived/` — like
everything else there, a cached encoding is fully regenerable from `raw/` +
code (the recipe hash *is* the reproduction key), so it's just another
`derived/` subfolder rather than a new top-level `DATA/` category.

Before computing, look up by hash: hit -> load from disk (and say so);
miss -> compute, store, register in the `encodings` table.
"""

import json
import os

import numpy as np

from Working.database.runs import get_encoding_by_hash, insert_encoding

ENCODING_ROOT = os.path.join("DATA", "derived", "encodings")


def _ext_for(encoding):
    """Array -> .npy, string -> .txt, anything else JSON-safe -> .json."""
    if isinstance(encoding, np.ndarray):
        return "npy"
    if isinstance(encoding, str):
        return "txt"
    return "json"


def build_encoding_path(source_file, channel, encoding_type, hash8, ext, root=None):
    root = root or ENCODING_ROOT
    stem = os.path.splitext(source_file)[0]
    return os.path.join(root, stem, f"CH{int(channel):02d}", encoding_type, f"{hash8}.{ext}")


def _write_encoding(path, encoding):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(encoding, np.ndarray):
        np.save(path, encoding)
    elif isinstance(encoding, str):
        with open(path, "w") as f:
            f.write(encoding)
    else:
        with open(path, "w") as f:
            json.dump(encoding, f)


def read_encoding_file(path):
    ext = os.path.splitext(path)[1].lstrip(".")
    if ext == "npy":
        return np.load(path, allow_pickle=False)
    if ext == "txt":
        with open(path) as f:
            return f.read()
    with open(path) as f:
        return json.load(f)


def get_or_compute_encoding(conn, recording, encoding_type, hash8, compute_fn, root=None):
    """The cache's core operation.

    Parameters
    ----------
    conn : sqlite3.Connection
    recording : sqlite3.Row
        A `recordings` row (needs `id`, `source_file`, `channel`).
    encoding_type : str
        e.g. "gramian_gasf", "sax_csax" — becomes a path segment.
    hash8 : str
        The recipe's short hash (`Working.recipes.short_hash`) — the cache key.
    compute_fn : callable() -> (encoding_value, span_start, span_end)
        Only called on a cache miss. Takes no arguments — the caller
        closes over whatever it needs (adapter, x, t, params).

    Returns
    -------
    (encoding, hit) : (Any, bool)
        `hit=True` means loaded from disk, not recomputed — the UI uses
        this to say so explicitly rather than silently either way.
    """
    cached = get_encoding_by_hash(conn, hash8)
    if cached is not None:
        return read_encoding_file(cached["path"]), True

    encoding, span_start, span_end = compute_fn()
    ext = _ext_for(encoding)
    path = build_encoding_path(
        recording["source_file"], recording["channel"], encoding_type, hash8, ext, root=root
    )
    _write_encoding(path, encoding)
    insert_encoding(conn, recording["id"], span_start, span_end, encoding_type, hash8, path)
    return encoding, False
