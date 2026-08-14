"""
multiscale_sax.py
=================
Multiscale symbolic pyramid over a single channel, built on the repo's
cSAX / pSAX cutline learners.

Motivation
----------
`Working/Detection/sax/sax_encoding.py` encodes a recording at ONE resolution
(one `dim_ratio`).  For a mycelium bio-electric channel (fs = 1 Hz, hundreds of
hours, slow drift-dominated) the interesting structure does not live at one
resolution: a 20-second excursion and a 40-minute drift ramp are both "events",
and a single samples-per-symbol choice can only see one of them.

This module encodes the same channel at a dyadic ladder of resolutions
(2, 4, 8, ... 4096 samples per symbol) and keeps the per-scale quantiser
parameters that a later MINDIST stage needs.

Two things make this more than a for-loop over `dim_ratio`:

1.  **Cutline mode.**  PAA is an averaging operator, so the standard deviation
    of the PAA sequence shrinks roughly as 1/sqrt(samples_per_symbol) for
    noise-like input.  Cutlines learned at a fine scale and applied unchanged
    to a coarse scale therefore put nearly all coarse segments into the middle
    one or two symbols — the coarse scales collapse.  `cutline_mode` is the
    knob that decides what to do about that; see the class docstring.

2.  **Phase offsets.**  PAA at samples-per-symbol s imposes an arbitrary
    segmentation grid with phase 0.  The same waveform occurring at a different
    phase encodes differently.  Sweeping start offsets 0..s-1 (subsampled for
    large s) recovers the alignment-invariant view.

Conventions
-----------
*   Nothing runs at import time; the demo is behind ``if __name__ == "__main__"``.
*   No plots are produced or saved.
*   Symbols are 0-based integer indices, matching `csax()` / `psax()` output.

Scope
-----
Exploratory.  Nothing in `Working/` is modified or imported-and-mutated; this
module only *calls* the existing cutline learners.

Index-mapping contract (read this before using the symbols for anything)
------------------------------------------------------------------------
Symbol ``i`` of ``(scale=s, offset=o)`` covers raw samples::

    [o + i*s,  o + (i+1)*s)          # half-open

``symbol_span_to_samples`` and ``samples_to_symbol_span`` are the ONLY
sanctioned way to convert between the two index spaces.  Do not re-derive the
arithmetic at the call site — an off-by-one here corrupts every downstream
stage silently, because a wrong-but-plausible sample range still produces a
wrong-but-plausible motif.
"""

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

import time
import numpy as np

from Working.Detection.sax.csax_python.normal_cutlines import normal_cutlines
from Working.Detection.sax.csax_python.meanshift.hg_meanshift_cluster import (
    hg_meanshift_cluster,
)
from Working.Detection.sax.psax_python.kde import epanechnikov_kde
from Working.Detection.sax.psax_python.kmeanspp import kmeanspp
from Working.Detection.sax.psax_python.lloydmax import lloydmax


# Matches the `norm_thresh` used by csax()/psax()/timeseries2symbol(): below
# this std we mean-centre only, rather than dividing by a near-zero scale.
NORM_THRESH = 0.001


# ──────────────────────────────────────────────────────────────────────────────
#  Scale-ladder helpers
# ──────────────────────────────────────────────────────────────────────────────

def _is_pow2(n: int) -> bool:
    return isinstance(n, (int, np.integer)) and n >= 1 and (int(n) & (int(n) - 1)) == 0


def expand_scales(scales) -> list:
    """
    Normalise the `scales` argument into a sorted list of dyadic samples-per-symbol.

    Accepted forms
    --------------
    tuple (min_sps, max_sps)
        Expanded to the dyadic ladder min, 2*min, 4*min, ..., max.
        Both endpoints must be powers of two.  e.g. ``(2, 4096)`` → 12 scales.
    list / array of int
        Taken literally.  Every entry must be a power of two.
    int
        A single scale.

    Why dyadic is enforced
    ----------------------
    Every coarse symbol must span an exact integer number of fine symbols, so
    that a coarse-scale region can be refined to a fine-scale region with no
    fractional segments.  Powers of two guarantee this for *every* pair of
    scales in the ladder, not just adjacent ones.

    Returns
    -------
    list[int] — ascending, unique.
    """
    if isinstance(scales, (int, np.integer)):
        scales = [int(scales)]
    elif isinstance(scales, tuple):
        if len(scales) != 2:
            raise ValueError(
                f"A tuple `scales` means (min_sps, max_sps) and must have length 2; "
                f"got length {len(scales)}. Pass a *list* for an explicit ladder."
            )
        lo, hi = int(scales[0]), int(scales[1])
        if not (_is_pow2(lo) and _is_pow2(hi)):
            raise ValueError(f"(min_sps, max_sps) = ({lo}, {hi}): both must be powers of two.")
        if lo > hi:
            raise ValueError(f"(min_sps, max_sps) = ({lo}, {hi}): min must not exceed max.")
        scales = [lo << k for k in range(int(np.log2(hi // lo)) + 1)]
    else:
        scales = [int(s) for s in scales]

    bad = [s for s in scales if not _is_pow2(s) or s < 2]
    if bad:
        raise ValueError(
            f"Scales must be dyadic (2, 4, 8, ... 4096) and >= 2; offending values: {bad}. "
            f"Non-dyadic scales break exact coarse->fine symbol nesting."
        )
    return sorted(set(int(s) for s in scales))


def resolve_offsets(sps: int, offsets, max_offsets: int) -> np.ndarray:
    """
    Decide which phase offsets to compute for one scale.

    Parameters
    ----------
    sps         : int   samples per symbol for this scale.
    offsets     : "all" | "zero" | explicit sequence of int
    max_offsets : int   cap applied when offsets == "all".

    Returns
    -------
    np.ndarray[int] — ascending offsets in [0, sps).

    Notes
    -----
    "all" is capped and evenly spaced rather than truncated: at sps=4096 the
    full sweep is 4096 encodings of the whole channel, which is not affordable.
    Evenly spaced offsets sample the phase circle uniformly, so the worst-case
    residual misalignment is sps / (2 * n_offsets) samples instead of sps / 2.
    """
    if isinstance(offsets, str):
        if offsets == "zero":
            return np.array([0], dtype=int)
        if offsets == "all":
            n = min(int(sps), int(max_offsets))
            return np.unique(np.linspace(0, sps, n, endpoint=False).astype(int))
        raise ValueError(f"offsets must be 'all', 'zero', or a sequence; got {offsets!r}")

    off = np.unique(np.asarray(offsets, dtype=int))
    if off.min() < 0 or off.max() >= sps:
        raise ValueError(f"Explicit offsets must lie in [0, {sps}); got {off.tolist()}")
    return off


# ──────────────────────────────────────────────────────────────────────────────
#  PAA and symbol mapping
# ──────────────────────────────────────────────────────────────────────────────

def _paa(x: np.ndarray, sps: int, offset: int = 0):
    """
    Piecewise aggregate approximation at a fixed samples-per-symbol and phase.

    Equivalent to ``ts_paa(x[offset:trim], n_seg)`` on the exactly-divisible
    branch, but expressed directly as a reshape so the segment boundaries are
    visible at the call site (this is the arithmetic the index mapping must
    agree with).

    Returns
    -------
    paa           : np.ndarray (n_symbols,)
    n_dropped_tail: int — samples discarded from the end to reach a multiple of
                    sps.  Never padded: padding would invent signal.
    """
    seg = x[offset:]
    n_symbols = len(seg) // sps
    if n_symbols == 0:
        raise ValueError(
            f"Scale sps={sps} with offset={offset} leaves {len(seg)} samples — "
            f"fewer than one full symbol. Drop this scale or use a longer signal."
        )
    n_used = n_symbols * sps
    paa = seg[:n_used].reshape(n_symbols, sps).mean(axis=1)
    return paa, int(len(seg) - n_used)


def _map_to_symbols(values: np.ndarray, cutlines: np.ndarray) -> np.ndarray:
    """
    Map values to 0-based symbol indices given ascending cutlines.

    Identical to `timeseries2symbol._map_to_string` minus its 1-based offset:
    that helper counts how many of ``[-inf] + cutlines`` are <= v, which is
    ``1 + #{cutlines <= v}``; ``searchsorted(..., side='right')`` is exactly
    ``#{cutlines <= v}``.  Using searchsorted keeps this O(n log a) instead of
    building the O(n * a) comparison matrix, which matters at 1e6 samples.
    """
    return np.searchsorted(cutlines, values, side="right").astype(int)


def _renormalise(values: np.ndarray, mean: float, std: float) -> np.ndarray:
    """z-renormalise, degrading to mean-centring when the scale is degenerate."""
    if std > NORM_THRESH:
        return (values - mean) / std
    return values - mean


# ──────────────────────────────────────────────────────────────────────────────
#  Cutline learners (thin wrappers over the Working/ implementations)
# ──────────────────────────────────────────────────────────────────────────────

def _learn_cutlines_csax(paa: np.ndarray, alphabet_size: int):
    """
    cSAX cutlines: Mean-Shift cluster centres on the PAA distribution.

    Mirrors `csax()`: shrink the Gaussian bandwidth until at least two clusters
    appear, take cutlines as the midpoints between sorted centres, and fall
    back to Gaussian-equiprobable cutlines if clustering still degenerates.

    Deviation from `csax()`: the fallback uses `normal_cutlines(alphabet_size)`
    rather than a hard-coded `normal_cutlines(10)`, so a degenerate scale still
    produces the alphabet the caller asked for.

    Returns
    -------
    cutlines, representatives, realised_alphabet_size, fallback_used
    """
    multi_factor = 1.0
    clust_cent, _, _ = hg_meanshift_cluster(paa, "gaussian", multi_factor)
    while clust_cent.shape[1] < 2 and multi_factor > 0.5:
        multi_factor /= 2
        clust_cent, _, _ = hg_meanshift_cluster(paa, "gaussian", multi_factor)

    if clust_cent.shape[1] > 1:
        centres = np.sort(clust_cent[0])
        cutlines = centres[:-1] + np.diff(centres) / 2
        return cutlines, centres, len(centres), False

    cutlines = normal_cutlines(alphabet_size)
    reps = _empirical_representatives(paa, cutlines)
    return cutlines, reps, alphabet_size, True


def _learn_cutlines_psax(paa: np.ndarray, alphabet_size: int):
    """
    pSAX cutlines: Epanechnikov KDE of the PAA distribution + Lloyd-Max.

    Mirrors `psax()`, including its npoints<=1000 KDE grid cap (the KDE builds
    an npoints x n_paa matrix, so an uncapped grid exhausts memory on long
    recordings).

    Returns
    -------
    cutlines, representatives, realised_alphabet_size, fallback_used
    """
    if np.std(paa) <= NORM_THRESH:
        # Degenerate (e.g. constant signal): KDE/Lloyd-Max have nothing to fit.
        cutlines = normal_cutlines(alphabet_size)
        return cutlines, _empirical_representatives(paa, cutlines), alphabet_size, True

    f, x = epanechnikov_kde(paa, npoints=min(len(paa), 1000))
    _, init_codewords = kmeanspp(paa, alphabet_size)
    codewords, cutlines = lloydmax(f, x, alphabet_size, init=np.sort(init_codewords))
    return np.asarray(cutlines, float), np.asarray(codewords, float), alphabet_size, False


def _empirical_representatives(values: np.ndarray, cutlines: np.ndarray) -> np.ndarray:
    """
    Per-symbol representative value = mean of the training values in that bin.

    Used when the learner does not hand back a codebook (the cSAX fallback
    path).  Empty bins take the bin's own midpoint so MINDIST stays monotone.
    """
    cutlines = np.asarray(cutlines, float)
    alphabet = len(cutlines) + 1
    sym = _map_to_symbols(values, cutlines)
    reps = np.empty(alphabet, dtype=float)
    edges = np.concatenate([[values.min() if len(values) else -1.0],
                            cutlines,
                            [values.max() if len(values) else 1.0]])
    for a in range(alphabet):
        members = values[sym == a]
        reps[a] = members.mean() if members.size else (edges[a] + edges[a + 1]) / 2.0
    return reps


# ──────────────────────────────────────────────────────────────────────────────
#  MultiScaleSAX
# ──────────────────────────────────────────────────────────────────────────────

class MultiScaleSAX:
    """
    A dyadic multiscale symbolic pyramid over one channel.

    Parameters
    ----------
    x : array-like
        Raw single-channel signal.
    fs : float
        Sample rate in Hz.  Only used to report the physical duration of each
        scale — no resampling happens.
    method : {"psax", "csax"}
        Cutline learner.  "psax" = KDE + Lloyd-Max (fixed alphabet size).
        "csax" = Mean-Shift (alphabet size is *discovered*, so the realised
        alphabet can differ from `alphabet_size`; check `scale_info`).
    scales : tuple | list | int
        Dyadic samples-per-symbol ladder.  ``(2, 4096)`` expands to the full
        ladder; a list is taken literally.  See `expand_scales`.
    alphabet_size : int
        Requested number of symbols.  Honoured exactly by pSAX; treated as an
        upper hint by cSAX.
    cutline_mode : {"per_scale", "shared_renormalised", "shared_raw"}
        The central design decision of this module.

        "per_scale"
            Each scale learns its own cutlines from its own PAA distribution.
            Each scale is optimally quantised in isolation, but symbol 5 at
            sps=8 and symbol 5 at sps=512 mean unrelated things — symbols are
            NOT comparable across scales, and cross-scale MINDIST is invalid.

        "shared_renormalised"
            Cutlines are learned once, at the finest scale, from that scale's
            *z-renormalised* PAA.  At every other scale the PAA is z-renormalised
            using THAT scale's own mean and std before the shared cutlines are
            applied.  A symbol then means "how extreme is this segment relative
            to the spread of segments at its own scale", which is the same
            statement at every scale — so symbols become comparable across
            scales, and cross-scale MINDIST is meaningful.

        "shared_raw"
            The naive version: learn once at the finest scale and apply the raw
            cutlines everywhere with no renormalisation.  Provided ONLY as the
            documented failure case (see multiscale_sax_tests.py, variance
            test): PAA averaging shrinks the spread as ~1/sqrt(sps), so coarse
            scales collapse into the middle symbols.  Do not use for analysis.
    offsets : "all" | "zero" | sequence of int
        Phase offsets per scale.  "all" is capped at `max_offsets` and evenly
        spaced.  Cutlines are learned ONCE per scale and shared across that
        scale's offsets — re-learning per offset would make offsets
        incomparable, which defeats the point of the sweep.
    numerosity_reduction : bool
        If True, additionally store the run-length-collapsed sequence.  The
        full sequence is always kept, so the index mapping stays exact.
    max_offsets : int
        Cap for offsets="all".  Default 16.
    normalize : bool
        z-normalise the whole signal once before any PAA, matching the global
        normalisation `csax()` / `psax()` perform.
    max_train_points : int
        Cutline learners are trained on at most this many PAA points, uniformly
        subsampled.  This is a hard requirement, not a nicety: Mean-Shift is
        ~O(n^2) and the pSAX KDE allocates a (1000 x n_paa) matrix, so at
        sps=2 on a 1e6-sample channel (5e5 PAA points) an untrained cap means
        minutes of compute and ~4 GB of allocation per scale.
    random_state : int | None
        Seeds numpy's global RNG before training.  Both Mean-Shift (random seed
        points) and k-means++ (random init) draw from the global RNG in the
        Working/ implementations, so this is the only way to make them
        reproducible without modifying Working/.

    Attributes
    ----------
    scales : list[int]
    scale_info : dict[int, dict]
        Per scale: ``sps, seconds, minutes, cutlines, cutlines_raw,
        representatives, representatives_raw, paa_mean, paa_std,
        alphabet_size, renormalised, fallback_used, n_train_points, offsets``.
        Stage 3 (MINDIST) reads this.  The ``*_raw`` variants are mapped back
        into that scale's own PAA units; the plain variants live in whatever
        units the cutlines act on (renormalised units under
        "shared_renormalised", PAA units otherwise).
    encodings : dict[(scale, offset), dict]
        Per encoding: ``symbols, n_symbols, offset, n_dropped_head,
        n_dropped_tail`` and, under numerosity reduction, ``nr_symbols,
        nr_run_lengths, nr_run_starts``.
    timings : dict
        Wall-clock seconds for ``train`` and ``encode``.

    Example
    -------
    >>> ms = MultiScaleSAX(x, fs=1.0, method="psax", scales=(2, 4096),
    ...                    cutline_mode="shared_renormalised", offsets="zero")
    >>> ms.symbols(1024)[:10]
    >>> ms.symbol_span_to_samples(1024, 0, 5, 9)
    """

    _MODES = ("per_scale", "shared_renormalised", "shared_raw")

    def __init__(self, x, fs, method="psax", scales=(2, 4096), alphabet_size=8,
                 cutline_mode="per_scale", offsets="all",
                 numerosity_reduction=False, max_offsets=16,
                 normalize=True, max_train_points=20000, random_state=None):

        if method not in ("psax", "csax"):
            raise ValueError(f"method must be 'psax' or 'csax'; got {method!r}")
        if cutline_mode not in self._MODES:
            raise ValueError(f"cutline_mode must be one of {self._MODES}; got {cutline_mode!r}")

        self.fs = float(fs)
        self.method = method
        self.alphabet_size = int(alphabet_size)
        self.cutline_mode = cutline_mode
        self.numerosity_reduction = bool(numerosity_reduction)
        self.max_offsets = int(max_offsets)
        self.normalize = bool(normalize)
        self.max_train_points = int(max_train_points)
        self.random_state = random_state

        x = np.asarray(x, dtype=float).ravel()
        self.n_samples = len(x)

        # Global z-normalisation, once, matching csax()/psax().  Stored so that
        # encode_segment() can put a new segment on the same footing.
        self.x_mean = float(x.mean())
        self.x_std = float(x.std())
        if self.normalize:
            self._x = _renormalise(x, self.x_mean, self.x_std)
        else:
            self._x = x

        self.scales = expand_scales(scales)
        too_long = [s for s in self.scales if s > self.n_samples]
        if too_long:
            raise ValueError(
                f"Scales {too_long} exceed the signal length ({self.n_samples} samples)."
            )

        self.scale_info = {}
        self.encodings = {}
        self.timings = {}

        if self.random_state is not None:
            np.random.seed(self.random_state)

        t0 = time.perf_counter()
        self._train()
        t1 = time.perf_counter()
        self._encode_all(offsets)
        t2 = time.perf_counter()
        self.timings = {"train": t1 - t0, "encode": t2 - t1, "total": t2 - t0}

    # ── Training ──────────────────────────────────────────────────────────────

    def _subsample(self, paa: np.ndarray) -> np.ndarray:
        """Uniformly thin a PAA sequence down to `max_train_points` for training."""
        if len(paa) <= self.max_train_points:
            return paa
        idx = np.linspace(0, len(paa) - 1, self.max_train_points).astype(int)
        return paa[np.unique(idx)]

    def _learn(self, train_paa: np.ndarray):
        if self.method == "csax":
            return _learn_cutlines_csax(train_paa, self.alphabet_size)
        return _learn_cutlines_psax(train_paa, self.alphabet_size)

    def _train(self):
        """
        Populate `scale_info`: per-scale PAA statistics plus the cutlines that
        will be applied to that scale.

        Under the shared modes the learner runs exactly once, on the finest
        scale; every scale still records its own PAA mean/std, because those
        are what "shared_renormalised" applies at encode time and what a later
        MINDIST needs to map symbols back into physical units.
        """
        shared = self.cutline_mode in ("shared_renormalised", "shared_raw")
        renorm = self.cutline_mode == "shared_renormalised"

        shared_cutlines = None
        shared_reps = None
        shared_alphabet = None
        shared_fallback = None

        for sps in self.scales:
            # Offset 0 defines each scale's reference statistics.  All offsets
            # of a scale then share these, so offsets stay mutually comparable.
            paa, _ = _paa(self._x, sps, 0)
            paa_mean = float(paa.mean())
            paa_std = float(paa.std())

            train_src = _renormalise(paa, paa_mean, paa_std) if renorm else paa
            train_paa = self._subsample(train_src)

            if not shared or shared_cutlines is None:
                cutlines, reps, alphabet, fallback = self._learn(train_paa)
                if shared:
                    shared_cutlines, shared_reps = cutlines, reps
                    shared_alphabet, shared_fallback = alphabet, fallback
            else:
                cutlines, reps = shared_cutlines, shared_reps
                alphabet, fallback = shared_alphabet, shared_fallback

            # Map cutlines/representatives back into this scale's own PAA units.
            # Under "shared_renormalised" the stored cutlines live in
            # renormalised units, so undo the renormalisation to get the
            # physical thresholds this scale actually applies.
            if renorm and paa_std > NORM_THRESH:
                cutlines_raw = np.asarray(cutlines, float) * paa_std + paa_mean
                reps_raw = np.asarray(reps, float) * paa_std + paa_mean
            elif renorm:
                cutlines_raw = np.asarray(cutlines, float) + paa_mean
                reps_raw = np.asarray(reps, float) + paa_mean
            else:
                cutlines_raw = np.asarray(cutlines, float)
                reps_raw = np.asarray(reps, float)

            self.scale_info[sps] = {
                "sps": sps,
                "seconds": sps / self.fs,
                "minutes": sps / self.fs / 60.0,
                "cutlines": np.asarray(cutlines, float),
                "cutlines_raw": cutlines_raw,
                "representatives": np.asarray(reps, float),
                "representatives_raw": reps_raw,
                "paa_mean": paa_mean,
                "paa_std": paa_std,
                "alphabet_size": int(alphabet),
                "renormalised": renorm,
                "fallback_used": bool(fallback),
                "n_train_points": int(len(train_paa)),
                "offsets": None,          # filled in by _encode_all
            }

    # ── Encoding ──────────────────────────────────────────────────────────────

    def _encode_all(self, offsets):
        for sps in self.scales:
            info = self.scale_info[sps]
            off_list = resolve_offsets(sps, offsets, self.max_offsets)
            info["offsets"] = off_list.tolist()

            for off in off_list:
                paa, dropped_tail = _paa(self._x, sps, int(off))

                if info["renormalised"]:
                    # Deliberately the SCALE's statistics (from offset 0), not
                    # this offset's own: using per-offset statistics would make
                    # the offsets of one scale incomparable with each other.
                    vals = _renormalise(paa, info["paa_mean"], info["paa_std"])
                else:
                    vals = paa

                sym = _map_to_symbols(vals, info["cutlines"])

                entry = {
                    "symbols": sym,
                    "n_symbols": int(len(sym)),
                    "offset": int(off),
                    "n_dropped_head": int(off),
                    "n_dropped_tail": int(dropped_tail),
                }
                if self.numerosity_reduction:
                    nr_sym, nr_len, nr_start = _run_length_collapse(sym)
                    entry["nr_symbols"] = nr_sym
                    entry["nr_run_lengths"] = nr_len
                    entry["nr_run_starts"] = nr_start
                self.encodings[(sps, int(off))] = entry

    # ── Accessors ─────────────────────────────────────────────────────────────

    def _entry(self, scale: int, offset: int = 0) -> dict:
        key = (int(scale), int(offset))
        if key not in self.encodings:
            avail = sorted(o for s, o in self.encodings if s == int(scale))
            if not avail:
                raise KeyError(
                    f"Scale {scale} was not encoded. Available scales: {self.scales}"
                )
            raise KeyError(
                f"Offset {offset} was not computed for scale {scale}. "
                f"Computed offsets: {avail} (offsets='all' is capped at "
                f"max_offsets={self.max_offsets})."
            )
        return self.encodings[key]

    def symbols(self, scale: int, offset: int = 0) -> np.ndarray:
        """Full (non-collapsed) symbol sequence for one (scale, offset)."""
        return self._entry(scale, offset)["symbols"]

    def n_symbols(self, scale: int, offset: int = 0) -> int:
        return self._entry(scale, offset)["n_symbols"]

    def offsets_for(self, scale: int) -> list:
        """Offsets actually computed for this scale (may be a subsample of 0..s-1)."""
        return list(self.scale_info[int(scale)]["offsets"])

    def dropped(self, scale: int, offset: int = 0) -> tuple:
        """(head, tail) samples excluded for this encoding. Nothing is ever padded."""
        e = self._entry(scale, offset)
        return e["n_dropped_head"], e["n_dropped_tail"]

    # ── Index mapping — the only sanctioned conversion ────────────────────────

    def symbol_span_to_samples(self, scale: int, offset: int, i: int, j: int) -> tuple:
        """
        Symbol span -> raw sample range.

        Parameters
        ----------
        i, j : int
            Symbol indices, **inclusive** on both ends (symbols i..j).

        Returns
        -------
        (start_sample, end_sample) — **half-open**: samples [start, end).
        So a single symbol i gives (o + i*s, o + (i+1)*s), a range of length s.

        Raises on out-of-range indices rather than clipping: a silently clipped
        span is the exact failure this method exists to prevent.
        """
        s, o = int(scale), int(offset)
        e = self._entry(s, o)
        i, j = int(i), int(j)
        if i < 0 or j < i or j >= e["n_symbols"]:
            raise IndexError(
                f"symbol span ({i}, {j}) out of range for scale {s} offset {o} "
                f"with {e['n_symbols']} symbols (need 0 <= i <= j < n_symbols)."
            )
        return o + i * s, o + (j + 1) * s

    def samples_to_symbol_span(self, scale: int, offset: int,
                               start_sample: int, end_sample: int) -> tuple:
        """
        Raw sample range -> symbol span.

        Parameters
        ----------
        start_sample, end_sample : int
            **Half-open** sample range [start, end), matching the output of
            `symbol_span_to_samples`.

        Returns
        -------
        (i, j) — **inclusive** symbol indices for the smallest symbol span that
        fully covers the requested samples, clamped to the encoded range.

        Round-trip guarantee
        --------------------
        ``samples_to_symbol_span(*symbol_span_to_samples(s, o, i, j))`` returns
        ``(i, j)`` exactly, for every valid i <= j.  The reverse round-trip is
        an outward rounding (a sample range that starts mid-symbol expands to
        the enclosing symbol), which is the correct direction for a covering
        span but is NOT an identity — do not assume it is.
        """
        s, o = int(scale), int(offset)
        e = self._entry(s, o)
        start_sample, end_sample = int(start_sample), int(end_sample)
        if end_sample <= start_sample:
            raise ValueError(
                f"end_sample ({end_sample}) must exceed start_sample ({start_sample}); "
                f"the range is half-open [start, end)."
            )
        if end_sample <= o or start_sample >= o + e["n_symbols"] * s:
            raise IndexError(
                f"Sample range [{start_sample}, {end_sample}) lies outside the encoded "
                f"span [{o}, {o + e['n_symbols'] * s}) for scale {s} offset {o}."
            )
        i = (start_sample - o) // s
        j = -(-(end_sample - o) // s) - 1          # ceil-div then to inclusive
        i = max(0, int(i))
        j = min(e["n_symbols"] - 1, int(j))
        return i, j

    # ── Numerosity-reduction mapping ──────────────────────────────────────────

    def nr_run_to_symbol_span(self, scale: int, offset: int, r: int) -> tuple:
        """
        Run index (in the collapsed sequence) -> inclusive symbol span in the
        FULL sequence, so that the mapping in `symbol_span_to_samples` still
        applies after numerosity reduction.
        """
        e = self._entry(scale, offset)
        if "nr_symbols" not in e:
            raise KeyError(
                "Numerosity reduction was not enabled "
                "(construct with numerosity_reduction=True)."
            )
        r = int(r)
        if r < 0 or r >= len(e["nr_symbols"]):
            raise IndexError(f"Run {r} out of range ({len(e['nr_symbols'])} runs).")
        start = int(e["nr_run_starts"][r])
        return start, start + int(e["nr_run_lengths"][r]) - 1

    def nr_run_to_samples(self, scale: int, offset: int, r: int) -> tuple:
        """Run index -> half-open raw sample range."""
        i, j = self.nr_run_to_symbol_span(scale, offset, r)
        return self.symbol_span_to_samples(scale, offset, i, j)

    # ── Re-encoding an arbitrary segment ──────────────────────────────────────

    def encode_segment(self, x_segment, scale: int, renormalise: str = "scale",
                       apply_global_norm: bool = True) -> np.ndarray:
        """
        Encode a raw segment with an already-learned scale, without retraining.

        Stage 3 needs this to re-encode a seed subsequence at a *different*
        scale from the one it was found at.

        Parameters
        ----------
        x_segment : array-like
            Raw samples, in the same units as the signal passed to __init__.
        scale : int
            Must be one of the trained scales.
        renormalise : {"scale", "segment"}
            Only consulted under cutline_mode="shared_renormalised".
            "scale"   — use the corpus statistics for that scale (default).
                        Correct for asking "how extreme is this segment
                        compared to the rest of the recording".
            "segment" — use the segment's own mean/std.  Only appropriate for a
                        shape-only comparison; on a short seed these statistics
                        are noisy and will distort the symbols.
        apply_global_norm : bool
            Apply the stored whole-signal z-normalisation first.  Leave True
            unless the segment is already normalised.

        Returns
        -------
        np.ndarray[int] — 0-based symbols, length len(x_segment) // scale.
        The tail is trimmed, never padded.
        """
        s = int(scale)
        if s not in self.scale_info:
            raise KeyError(f"Scale {s} was not trained. Trained scales: {self.scales}")
        if renormalise not in ("scale", "segment"):
            raise ValueError(f"renormalise must be 'scale' or 'segment'; got {renormalise!r}")

        info = self.scale_info[s]
        seg = np.asarray(x_segment, dtype=float).ravel()
        if len(seg) < s:
            raise ValueError(
                f"Segment of {len(seg)} samples is shorter than one symbol at scale {s}."
            )

        if apply_global_norm and self.normalize:
            seg = _renormalise(seg, self.x_mean, self.x_std)

        paa, _ = _paa(seg, s, 0)

        if info["renormalised"]:
            if renormalise == "scale":
                vals = _renormalise(paa, info["paa_mean"], info["paa_std"])
            else:
                vals = _renormalise(paa, float(paa.mean()), float(paa.std()))
        else:
            vals = paa

        return _map_to_symbols(vals, info["cutlines"])

    # ── Reporting ─────────────────────────────────────────────────────────────

    def symbol_histogram(self, scale: int, offset: int = 0,
                         normalise: bool = True) -> np.ndarray:
        """Symbol occupancy at one (scale, offset), length = realised alphabet."""
        info = self.scale_info[int(scale)]
        h = np.bincount(self.symbols(scale, offset), minlength=info["alphabet_size"])
        h = h.astype(float)
        return h / h.sum() if normalise and h.sum() else h

    def occupancy_ratio(self, scale: int, offset: int = 0) -> float:
        """
        max/min symbol-bin ratio.  Large values mean the alphabet is barely
        being used at this scale — the collapse signature.  inf if some symbol
        is never emitted.
        """
        h = self.symbol_histogram(scale, offset, normalise=True)
        return float(h.max() / h.min()) if h.min() > 0 else float("inf")

    def describe(self) -> str:
        """Human-readable table of the pyramid. Returns a string; prints nothing."""
        lines = [
            f"MultiScaleSAX  method={self.method}  cutline_mode={self.cutline_mode}  "
            f"alphabet={self.alphabet_size}  fs={self.fs} Hz  n={self.n_samples} samples "
            f"({self.n_samples / self.fs / 3600:.1f} h)",
            f"{'sps':>6} {'secs':>8} {'mins':>8} {'n_sym':>9} {'alpha':>6} "
            f"{'paa_std':>9} {'offs':>5} {'drop_tail':>10} {'max/min':>9}",
        ]
        for s in self.scales:
            info = self.scale_info[s]
            o0 = info["offsets"][0]
            e = self.encodings[(s, o0)]
            lines.append(
                f"{s:>6} {info['seconds']:>8.1f} {info['minutes']:>8.2f} "
                f"{e['n_symbols']:>9} {info['alphabet_size']:>6} "
                f"{info['paa_std']:>9.4f} {len(info['offsets']):>5} "
                f"{e['n_dropped_tail']:>10} {self.occupancy_ratio(s, o0):>9.2f}"
            )
        lines.append(
            f"train {self.timings['train']:.2f}s  encode {self.timings['encode']:.2f}s  "
            f"total {self.timings['total']:.2f}s"
        )
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"MultiScaleSAX(method={self.method!r}, cutline_mode={self.cutline_mode!r}, "
            f"scales={self.scales}, alphabet_size={self.alphabet_size}, "
            f"n_encodings={len(self.encodings)})"
        )


# ──────────────────────────────────────────────────────────────────────────────
#  Numerosity reduction
# ──────────────────────────────────────────────────────────────────────────────

def _run_length_collapse(sym: np.ndarray):
    """
    Collapse runs of identical symbols.

    Returns
    -------
    nr_symbols   : one symbol per run
    nr_lengths   : run length, in symbols of the full sequence
    nr_starts    : index into the full sequence where each run begins

    `nr_starts` and `nr_lengths` are what keep the index mapping exact after
    collapsing: run r covers full-sequence symbols
    ``[nr_starts[r], nr_starts[r] + nr_lengths[r])``.
    """
    sym = np.asarray(sym)
    if len(sym) == 0:
        z = np.array([], dtype=int)
        return z, z, z
    starts = np.concatenate([[0], np.flatnonzero(np.diff(sym)) + 1])
    lengths = np.diff(np.concatenate([starts, [len(sym)]]))
    return sym[starts], lengths.astype(int), starts.astype(int)


# ──────────────────────────────────────────────────────────────────────────────
#  Demo
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MultiScaleSAX demo / benchmark.")
    parser.add_argument("--channel", default="DATA/derived/channels/M2_concat_fs1/CH2.npy",
                        help="Path to a 1-D .npy channel, relative to the repo root.")
    parser.add_argument("--fs", type=float, default=1.0)
    parser.add_argument("--method", default="psax", choices=["psax", "csax"])
    parser.add_argument("--mode", default="shared_renormalised",
                        choices=list(MultiScaleSAX._MODES))
    parser.add_argument("--offsets", default="zero", choices=["zero", "all"])
    args = parser.parse_args()

    path = _REPO_ROOT / args.channel
    if not path.exists():
        raise SystemExit(f"Channel not found: {path}")

    signal = np.load(path)
    ms = MultiScaleSAX(signal, fs=args.fs, method=args.method, scales=(2, 4096),
                       alphabet_size=8, cutline_mode=args.mode,
                       offsets=args.offsets, random_state=0)
    print(ms.describe())
