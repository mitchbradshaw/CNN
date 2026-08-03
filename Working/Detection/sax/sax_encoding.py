"""
sax_encoding.py
================
cSAX and pSAX encoders for WindowMatrix objects.

Per-window encoders (add_computed_column-compatible)
-----------------------------------------------------
Factory functions that return a closure accepting one window at a time.
Each window trains its own cutlines from its own PAA distribution.

    wm.add_computed_column("csax", make_csax_encoder(dim_ratio=0.1))
    wm.add_computed_column("psax", make_psax_encoder(dim_ratio=0.1, alphabet_size=8))

Whole-dataset encoders
-----------------------
Run the algorithm once on the entire signal stored in the WindowMatrix,
then partition the resulting global symbol sequence back to each window.
This is the statistically correct approach: a single global normalisation
and a single set of cutlines learned from the full recording's distribution.

    encode_dataset_csax(wm, dim_ratio=0.1)
    encode_dataset_psax(wm, dim_ratio=0.1, alphabet_size=8)

Symbol-to-sample alignment note
---------------------------------
After global encoding, each symbol represents exactly
    samples_per_symbol = data_len_trimmed // total_symbols
consecutive raw samples (PAA guarantees this when data_len % n_symbols == 0,
which csax/psax enforce by trimming).  A window at start_idx receives the
symbols whose PAA segments begin at or after floor(start_idx / sps) and
whose count equals window_samples // sps.  If start_idx is not a multiple
of sps the first assigned symbol may include a few samples before the window
boundary — this is an inherent consequence of global discretisation and is
generally negligible at typical dim_ratio values.
"""

import os
import sys
import numpy as np

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

from .csax_python.csax import csax
from .psax_python.psax import psax


# ──────────────────────────────────────────────────────────────────────────────
#  cSAX
# ──────────────────────────────────────────────────────────────────────────────

def make_csax_encoder(dim_ratio: float = 0.1,
                      normalize: bool = True):
    """
    Build a per-window cSAX encoder for use with WindowMatrix.add_computed_column.

    cSAX learns data-adaptive quantisation cutlines via Mean-Shift clustering
    on the PAA of the signal, then discretises the signal into a symbolic
    sequence.  When called per-window the window trains its own cutlines.

    Parameters
    ----------
    dim_ratio : float
        Dimensionality-reduction ratio: the fraction of samples that are
        condensed into one PAA segment / symbol.
        E.g. dim_ratio=0.1 on a 600-sample window → 60 symbols.
    normalize : bool
        If True (default), z-normalise the window before encoding.

    Returns
    -------
    callable  (window: np.ndarray) -> np.ndarray[int]
        A function that takes one window's raw signal and returns its cSAX
        encoding as a 1-D array of 0-based symbol indices with length
        floor(dim_ratio * len(window)).

    Example
    -------
    >>> encoder = make_csax_encoder(dim_ratio=0.1)
    >>> wm.add_computed_column("csax", encoder)
    """
    def _encode(window: np.ndarray) -> np.ndarray:
        return csax(
            window,
            training_len=len(window),   # window is its own training set
            dim_ratio=dim_ratio,
            normalize=normalize,
        )

    _encode.__name__ = "csax_encoder"
    _encode.__qualname__ = (
        f"make_csax_encoder.<locals>.csax_encoder"
        f"(dim_ratio={dim_ratio}, normalize={normalize})"
    )
    return _encode


# ──────────────────────────────────────────────────────────────────────────────
#  pSAX
# ──────────────────────────────────────────────────────────────────────────────

def make_psax_encoder(dim_ratio: float = 0.1,
                      alphabet_size: int = 8,
                      normalize: bool = True):
    """
    Build a per-window pSAX encoder for use with WindowMatrix.add_computed_column.

    pSAX learns data-adaptive quantisation cutlines via Epanechnikov KDE on
    the PAA of the signal, followed by Lloyd-Max optimisation.  When called
    per-window the window trains its own KDE and codebook.

    Parameters
    ----------
    dim_ratio : float
        Dimensionality-reduction ratio: the fraction of samples that are
        condensed into one PAA segment / symbol.
        E.g. dim_ratio=0.1 on a 600-sample window → 60 symbols.
    alphabet_size : int
        Number of distinct symbols in the output (Lloyd-Max codebook size).
    normalize : bool
        If True (default), z-normalise the window before encoding.

    Returns
    -------
    callable  (window: np.ndarray) -> np.ndarray[int]
        A function that takes one window's raw signal and returns its pSAX
        encoding as a 1-D array of 0-based symbol indices with length
        floor(dim_ratio * len(window)).

    Example
    -------
    >>> encoder = make_psax_encoder(dim_ratio=0.1, alphabet_size=8)
    >>> wm.add_computed_column("psax", encoder)
    """
    def _encode(window: np.ndarray) -> np.ndarray:
        return psax(
            window,
            training_len=len(window),   # window is its own training set
            dim_ratio=dim_ratio,
            alphabet_size=alphabet_size,
            normalize=normalize,
        )

    _encode.__name__ = "psax_encoder"
    _encode.__qualname__ = (
        f"make_psax_encoder.<locals>.psax_encoder"
        f"(dim_ratio={dim_ratio}, alphabet_size={alphabet_size}, normalize={normalize})"
    )
    return _encode


# ──────────────────────────────────────────────────────────────────────────────
#  Whole-dataset encoders
# ──────────────────────────────────────────────────────────────────────────────

def _sym_slice(str_out: np.ndarray, start_idx: int,
               window_samples: int, samples_per_sym: int,
               total_syms: int) -> np.ndarray:
    """
    Extract the symbol subsequence that corresponds to one window.

    Parameters
    ----------
    str_out        : full global symbol sequence, shape (total_syms,)
    start_idx      : window start in raw samples
    window_samples : window length in raw samples
    samples_per_sym: raw samples covered by each symbol (data_len_trimmed // total_syms)
    total_syms     : length of str_out

    Returns
    -------
    1-D int array of length  window_samples // samples_per_sym
    """
    sym_start = start_idx // samples_per_sym
    n_syms    = window_samples // samples_per_sym
    sym_end   = min(sym_start + n_syms, total_syms)
    return str_out[sym_start:sym_end]


def encode_dataset_csax(wm,
                        dim_ratio: float = 0.1,
                        training_frac: float = 1.0,
                        normalize: bool = True,
                        column_name: str = "csax",
                        overwrite: bool = False):
    """
    Encode the full signal of a WindowMatrix with cSAX, then assign each
    window its slice of the global symbol sequence.

    A single normalisation and a single Mean-Shift-derived set of cutlines
    are computed from the whole recording, so symbol values are directly
    comparable across windows — unlike the per-window encoder where each
    window calibrates its own cutlines independently.

    Parameters
    ----------
    wm            : WindowMatrix
    dim_ratio     : float
        Dimensionality-reduction ratio.  E.g. 0.1 → one symbol per 10 samples.
        Each window of length W receives  W // round(1 / dim_ratio)  symbols.
    training_frac : float  in (0, 1]
        Fraction of the full signal used to train the Mean-Shift cutlines.
        Default 1.0 uses the entire recording; 0.5 uses the first half.
    normalize     : bool
        If True (default), z-normalise the full signal before encoding.
    column_name   : str
        Name of the column added to the WindowMatrix.  Default "csax".
    overwrite     : bool
        If False (default), skip silently if the column already exists.

    Returns
    -------
    wm  (the same WindowMatrix, for chaining)

    Notes
    -----
    Each cell of the new column holds a 1-D np.ndarray of 0-based integer
    symbol indices.  Windows that extend beyond the encoded signal boundary
    (e.g. a partial window at the end of the recording) are left as NaN;
    a single informational print is emitted listing how many were skipped.

    Example
    -------
    >>> encode_dataset_csax(wm, dim_ratio=0.1, training_frac=0.5)
    >>> wm.get_value(start_idx, "csax")   # → np.ndarray[int]
    """
    if column_name in wm._df.columns and not overwrite:
        return wm

    x = wm._x
    n = len(x)
    training_len = max(1, int(round(training_frac * n)))

    # Replicate csax's trimming arithmetic to find samples_per_sym
    total_syms      = int(np.floor(dim_ratio * n))
    data_len_trimmed = n - (n % total_syms)
    samples_per_sym  = data_len_trimmed // total_syms

    # Single global encoding of the full signal
    str_out = csax(x, training_len=training_len,
                   dim_ratio=dim_ratio, normalize=normalize)

    # Partition into per-window slices; skip boundary windows (→ NaN)
    n_syms_per_win = wm._window_samples // samples_per_sym
    encodings = {}
    skipped = []
    for start_idx in wm._df.index:
        slc = _sym_slice(str_out, int(start_idx),
                         wm._window_samples, samples_per_sym, total_syms)
        if len(slc) < n_syms_per_win:
            skipped.append(start_idx)
        else:
            encodings[start_idx] = slc

    if skipped:
        print(f"[encode_dataset_csax] {len(skipped)} boundary window(s) skipped "
              f"(start_idx {skipped[0]}…{skipped[-1]}): fewer than "
              f"{n_syms_per_win} symbols available → stored as NaN.")

    wm.add_external_column(column_name, encodings, overwrite=overwrite)
    return wm


def encode_dataset_psax(wm,
                        dim_ratio: float = 0.1,
                        alphabet_size: int = 8,
                        training_frac: float = 1.0,
                        normalize: bool = True,
                        column_name: str = "psax",
                        overwrite: bool = False):
    """
    Encode the full signal of a WindowMatrix with pSAX, then assign each
    window its slice of the global symbol sequence.

    A single normalisation and a single KDE + Lloyd-Max codebook are computed
    from the whole recording, so symbol values are directly comparable across
    windows.

    Parameters
    ----------
    wm            : WindowMatrix
    dim_ratio     : float
        Dimensionality-reduction ratio.  E.g. 0.1 → one symbol per 10 samples.
    alphabet_size : int
        Number of distinct symbols (Lloyd-Max codebook size).
    training_frac : float  in (0, 1]
        Fraction of the full signal used to train the KDE and codebook.
        Default 1.0 uses the entire recording.
    normalize     : bool
        If True (default), z-normalise the full signal before encoding.
    column_name   : str
        Name of the column added to the WindowMatrix.  Default "psax".
    overwrite     : bool
        If False (default), skip silently if the column already exists.

    Returns
    -------
    wm  (the same WindowMatrix, for chaining)

    Notes
    -----
    Each cell of the new column holds a 1-D np.ndarray of 0-based integer
    symbol indices.  Windows that extend beyond the encoded signal boundary
    (e.g. a partial window at the end of the recording) are left as NaN;
    a single informational print is emitted listing how many were skipped.

    Example
    -------
    >>> encode_dataset_psax(wm, dim_ratio=0.1, alphabet_size=8)
    >>> wm.get_value(start_idx, "psax")   # → np.ndarray[int]
    """
    if column_name in wm._df.columns and not overwrite:
        return wm

    x = wm._x
    n = len(x)
    training_len = max(1, int(round(training_frac * n)))

    # Replicate psax's trimming arithmetic to find samples_per_sym
    total_syms       = int(np.floor(dim_ratio * n))
    data_len_trimmed = n - (n % total_syms)
    samples_per_sym  = data_len_trimmed // total_syms

    # Single global encoding of the full signal
    str_out = psax(x, training_len=training_len,
                   dim_ratio=dim_ratio, alphabet_size=alphabet_size,
                   normalize=normalize)

    # Partition into per-window slices; skip boundary windows (→ NaN)
    n_syms_per_win = wm._window_samples // samples_per_sym
    encodings = {}
    skipped = []
    for start_idx in wm._df.index:
        slc = _sym_slice(str_out, int(start_idx),
                         wm._window_samples, samples_per_sym, total_syms)
        if len(slc) < n_syms_per_win:
            skipped.append(start_idx)
        else:
            encodings[start_idx] = slc

    if skipped:
        print(f"[encode_dataset_psax] {len(skipped)} boundary window(s) skipped "
              f"(start_idx {skipped[0]}…{skipped[-1]}): fewer than "
              f"{n_syms_per_win} symbols available → stored as NaN.")

    wm.add_external_column(column_name, encodings, overwrite=overwrite)
    return wm
