"""
sax_detection.py
================
Turns seeded SAX motif search into a detection algorithm with calibrated
significance, so a hit is reportable as "this recurrence is stronger than X% of
what the null model produces" rather than "this was in the top 10".

Built on stage 3's conclusions (see `run_seed_search.py`), which are carried
into the defaults here rather than left as advice:

*   **`exact` is dropped.** It was neither the fastest matcher nor the most
    selective, and it is invalidated by any change to the cutlines.
*   **The default matcher is a cascade**: `mindist` generates candidates, then
    `edit` re-ranks the survivors. MINDIST is a verified lower bound (0
    violations in 40,000 pairs), so it never discards a true match; `edit` had
    the best F1 and by far the best decoy rejection (0.2 vs 2.3 decoy hits).
*   **The ladder is capped at sps <= 128** (`MAX_DETECT_SPS`). Above that the
    bound's tightness falls under 0.3 and MINDIST prunes essentially nothing.
*   **Preprocessing dominates matcher choice.** Detrending moved synthetic
    recall from 0.22 to 0.85. Nothing here detrends for you - it is a
    stage-1 decision - but `detect` warns when a seed uses so little of the
    alphabet that the encoding is describing drift rather than shape.

The one non-negotiable
----------------------
Surrogates are encoded through the SAME `MultiScaleSAX` object with the SAME
learned cutlines and the SAME per-scale renormalisation constants. Re-training
the quantiser on each surrogate would test the encoder's adaptability, not the
signal's structure, and would produce a null that is far too permissive.
`encode_like` enforces this with an assertion rather than a comment.

Statistical shape
-----------------
Hits are non-overlapping by construction (`suppress_overlaps`), which is what
makes them approximately independent tests and therefore a sane family for
Benjamini-Hochberg.

Per-hit p-values are empirical and add-one corrected, computed against the
POOLED hit distances from all surrogates. That pool is large (tens of
thousands), so the arithmetic floor `NullModel.p_floor` is tiny - but the pool
comes from only `n_surrogates` INDEPENDENT realisations. Pooling estimates the
bulk of the null CDF well; in the far tail it rests on a handful of surrogates.
`NullModel.p_resolution` (= 1/n_surrogates) is therefore the value below which a
reported p is arithmetic rather than evidence, and `detect` flags every hit
under it as `p_below_resolution`. Quote those as "p < 1/N", never as an exact
figure. Raising `n_surrogates` is the only thing that lowers the resolution.

Nothing runs at import time; no plots are saved.
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
if str(_Path(__file__).resolve().parent) not in _sys.path:
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

import copy
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from multiscale_sax import _paa, _map_to_symbols, _renormalise, NORM_THRESH
from sax_seed_search import (
    Seed, search, suppress_overlaps, symbol_distance_table,
    match_mindist, _subseq_edit_dp, WILDCARD,
)

# Stage-3 finding: MINDIST tightness falls from ~0.47 at sps 8-32 to 0.06 at
# sps 1024, so coarse scales prune nothing and only add false positives.
MAX_DETECT_SPS = 128

# Below this fraction of the alphabet, the seed is encoding drift level rather
# than shape (stage 3: a raw real-data seed used 1 of 8 symbols).
MIN_ALPHABET_FRAC = 0.5

# Phase offsets used for BOTH the observed search and the null. Stage 2
# measured offset sensitivity on the real channel at 0.2%-3.1% worst-pair
# symbol disagreement for every sps <= 128 ("offsets='zero' is safe"), so the
# full sweep costs 8x for a difference that does not exist in this range. The
# null is 200 searches, so that 8x is the difference between 9 minutes and 1
# minute per null. Raise it only alongside evidence that phase matters at the
# scales being searched - and if you do, the null must use the same setting or
# the two distance distributions are not comparable.
DEFAULT_OFFSETS = "zero"

CACHE_DIR = _Path(__file__).resolve().parent / ".null_cache"


# ──────────────────────────────────────────────────────────────────────────────
#  Surrogate generators
# ──────────────────────────────────────────────────────────────────────────────

def fourier_surrogate(x, rng):
    """
    Phase-randomised (FT) surrogate: preserves the power spectrum exactly,
    destroys all phase relationships.

    The right first null for a drift-dominated channel. White noise would be a
    trivial null - a matcher could score zero false hits on it purely by
    preferring smooth things - whereas this keeps the smoothness and removes
    only the structure.

    Its weakness is that the output is Gaussianised: the amplitude
    distribution is not preserved, so a signal with a skewed or heavy-tailed
    marginal gets a null that is easier to beat than it should be. Use
    `iaaft_surrogate` when that matters.
    """
    x = np.asarray(x, dtype=float).ravel()
    n = len(x)
    mu = x.mean()
    f = np.fft.rfft(x - mu)
    ph = rng.uniform(0, 2 * np.pi, len(f))
    ph[0] = 0.0
    if n % 2 == 0:
        ph[-1] = 0.0
    out = np.fft.irfft(np.abs(f) * np.exp(1j * ph), n=n)
    return out + mu


def iaaft_surrogate(x, rng, n_iter=100, tol=1e-3):
    """
    Iterative Amplitude Adjusted Fourier Transform surrogate.

    Preserves BOTH the power spectrum and the exact amplitude distribution, by
    alternately imposing the target spectrum and re-imposing the target rank
    order. The stricter null: structure that survives it cannot be explained by
    the signal's spectrum or its marginal distribution alone.

    Convergence
    -----------
    Stops when the RELATIVE SPECTRUM ERROR falls below `tol`, i.e. when the
    output's power spectrum matches the target to that precision. `n_iter` is
    a cap, not a target.

    An earlier version stopped when the rank ordering stopped changing; on
    these channels that never happens - measured on a 120k-sample detrended
    signal, 66,482 of 120,000 ranks were still moving at iteration 100 - so it
    silently ran the full 100 iterations every time and cost 54 minutes across
    200 surrogates. Spectrum error, by contrast, reaches 0.011 by iteration 20
    and 0.0007 by iteration 50, so the default `tol` converges in roughly 40.

    The realised count is exposed as `iaaft_surrogate.last_iters`; if it
    equals `n_iter`, the surrogate did NOT converge and its spectrum is only
    approximate.

    Reference: Schreiber & Schmitz (1996), Phys. Rev. Lett. 77, 635.
    """
    x = np.asarray(x, dtype=float).ravel()
    n = len(x)
    sorted_x = np.sort(x)
    target_amp = np.abs(np.fft.rfft(x))
    target_norm = np.linalg.norm(target_amp)

    # Start from a random shuffle, as in the original formulation.
    y = rng.permutation(x)
    iters = 0
    for iters in range(1, n_iter + 1):
        # Impose the target power spectrum, keep the current phases.
        f = np.fft.rfft(y)
        y = np.fft.irfft(target_amp * np.exp(1j * np.angle(f)), n=n)
        # Impose the target amplitude distribution, keep the current ranks.
        # This step is exact, so the marginal is preserved at every iteration -
        # only the spectrum is approached iteratively.
        y = sorted_x[np.argsort(np.argsort(y))]
        if target_norm > 0:
            err = np.linalg.norm(np.abs(np.fft.rfft(y)) - target_amp) / target_norm
            if err < tol:
                break
    iaaft_surrogate.last_iters = iters
    return y


iaaft_surrogate.last_iters = 0


def block_bootstrap(x, rng, block_length=3600):
    """
    Circular moving-block bootstrap: preserves structure up to `block_length`,
    destroys everything longer.

    This is the null that answers a specific question - "is this recurrence
    longer-range than L?" - rather than "is there any structure at all".
    Sweeping `block_length` and watching where a detection stops being
    significant localises the timescale its evidence actually lives at.

    Blocks are drawn with wraparound so every sample has equal probability of
    starting a block; without that, samples near the end are systematically
    under-represented.

    `block_length` must be well BELOW the span of the motif being tested. At
    or above it, a single block can contain an intact copy of the motif, so the
    null contains the very thing the test is looking for and nothing can ever
    reach significance. Measured on the synthetic benchmark: a 600-sample motif
    tested against L=600 blocks gave 0 significant hits where the Fourier null
    gave 10. `detect` warns when the ratio is unsafe.
    """
    x = np.asarray(x, dtype=float).ravel()
    n = len(x)
    L = int(max(1, min(block_length, n)))
    n_blocks = int(np.ceil(n / L))
    starts = rng.integers(0, n, size=n_blocks)
    idx = (starts[:, None] + np.arange(L)[None, :]) % n
    return x[idx.ravel()[:n]]


SURROGATES = {
    "fourier": fourier_surrogate,
    "iaaft": iaaft_surrogate,
    "block": block_bootstrap,
}


def make_surrogate(x, kind, rng, **kwargs):
    """Dispatch to a surrogate generator by name."""
    if kind not in SURROGATES:
        raise ValueError(f"surrogate must be one of {list(SURROGATES)}; got {kind!r}")
    return SURROGATES[kind](x, rng, **kwargs)


# ──────────────────────────────────────────────────────────────────────────────
#  Encoding a surrogate through the ALREADY-LEARNED quantiser
# ──────────────────────────────────────────────────────────────────────────────

def encode_like(msax, x_new, check=True):
    """
    Encode a new signal through `msax`'s already-learned quantiser.

    Reuses, without recomputation:
      * the global z-normalisation constants (`x_mean`, `x_std`),
      * every scale's cutlines,
      * every scale's PAA mean and std (the renormalisation constants under
        `cutline_mode="shared_renormalised"`),
      * the exact set of phase offsets computed per scale.

    Why every one of those matters
    -------------------------------
    Re-training on each surrogate would ask "can the encoder adapt to this
    signal?", to which the answer is always yes, and the resulting null would
    be far too permissive - every surrogate would look as well-encoded as the
    real data and nothing would ever reach significance. Even reusing the
    cutlines but recomputing `paa_std` per surrogate would silently
    re-normalise the null onto the real data's scale.

    `check=True` asserts afterwards that none of the learned parameters moved.

    Returns a shallow clone of `msax` that responds to `symbols`,
    `scale_info`, `offsets_for`, and the index-mapping methods exactly as the
    original does.
    """
    x_new = np.asarray(x_new, dtype=float).ravel()

    sur = copy.copy(msax)
    # Deep-copy scale_info so the encode loop below cannot mutate the real
    # pyramid's recorded offsets; the learned VALUES inside are then checked
    # for equality rather than identity.
    sur.scale_info = copy.deepcopy(msax.scale_info)
    sur.encodings = {}
    sur.n_samples = len(x_new)
    sur._x = (_renormalise(x_new, msax.x_mean, msax.x_std)
              if msax.normalize else x_new)

    for s in msax.scales:
        info = sur.scale_info[s]
        for off in info["offsets"]:
            paa, dropped_tail = _paa(sur._x, s, int(off))
            if info["renormalised"]:
                # The REAL data's statistics, deliberately - see docstring.
                vals = _renormalise(paa, info["paa_mean"], info["paa_std"])
            else:
                vals = paa
            sym = _map_to_symbols(vals, info["cutlines"])
            sur.encodings[(s, int(off))] = {
                "symbols": sym, "n_symbols": int(len(sym)), "offset": int(off),
                "n_dropped_head": int(off), "n_dropped_tail": int(dropped_tail),
            }

    if check:
        assert_same_quantiser(msax, sur)
    return sur


def assert_same_quantiser(a, b):
    """
    Assert two pyramids share an identical learned quantiser.

    Factored out of `encode_like` so the guard itself is unit-testable: a check
    that has never been seen to fail is not known to work, and this one is the
    only thing standing between a valid null and a null that silently tests the
    encoder instead of the signal.

    Raises AssertionError naming the first parameter that differs.
    """
    assert list(a.scales) == list(b.scales), (
        f"quantiser mismatch: scale ladders differ, {a.scales} vs {b.scales}")
    for s in a.scales:
        ia, ib = a.scale_info[s], b.scale_info[s]
        assert np.array_equal(ia["cutlines"], ib["cutlines"]), (
            f"quantiser mismatch: cutlines differ at sps={s}. A surrogate must "
            f"go through the SAME quantiser, or the null tests the encoder's "
            f"adaptability rather than the signal's structure.")
        assert ia["paa_mean"] == ib["paa_mean"], (
            f"quantiser mismatch: paa_mean differs at sps={s} "
            f"({ia['paa_mean']} vs {ib['paa_mean']}). Recomputing the "
            f"renormalisation constants per surrogate re-scales the null onto "
            f"the real data.")
        assert ia["paa_std"] == ib["paa_std"], (
            f"quantiser mismatch: paa_std differs at sps={s} "
            f"({ia['paa_std']} vs {ib['paa_std']}).")
        assert ia["alphabet_size"] == ib["alphabet_size"], (
            f"quantiser mismatch: alphabet size differs at sps={s}.")
        assert list(ia["offsets"]) == list(ib["offsets"]), (
            f"quantiser mismatch: offset set differs at sps={s}.")
    assert a.x_mean == b.x_mean and a.x_std == b.x_std, (
        "quantiser mismatch: global normalisation constants differ.")


# ──────────────────────────────────────────────────────────────────────────────
#  The cascade matcher (stage 3's recommendation, made concrete)
# ──────────────────────────────────────────────────────────────────────────────

def _edit_distance_to_windows(seed_sym, seq, table, starts, lengths, indel_cost):
    """
    Weighted edit distance between the seed and a specific set of candidate
    windows, normalised by seed length.

    Used by the cascade re-ranker. Running the full free-start DP over the
    whole channel again would defeat the purpose of having pruned; this pays
    O(w * window) per surviving candidate instead of O(w * n).
    """
    out = np.empty(len(starts), dtype=float)
    w = len(seed_sym)
    for k, (i0, L) in enumerate(zip(starts, lengths)):
        lo = max(0, int(i0))
        hi = min(len(seq), lo + int(L))
        window = seq[lo:hi]
        if len(window) == 0:
            out[k] = np.inf
            continue
        cost, _ = _subseq_edit_dp(
            np.ascontiguousarray(seed_sym, dtype=np.int64),
            np.ascontiguousarray(window, dtype=np.int64),
            np.ascontiguousarray(table, dtype=np.float64),
            float(indel_cost))
        out[k] = float(cost[1:].min()) / w
    return out


def cascade_hits(msax, seed, scale, offset, n_candidates=2000, rerank_k=200,
                 indel_cost=None, min_separation=None, slack=0.5):
    """
    MINDIST candidate generation followed by weighted-edit re-ranking.

    Stage 1 scores every window with MINDIST - a verified lower bound, so no
    true match is lost - and suppresses overlaps. Stage 2 re-scores the best
    `rerank_k` survivors with the edit distance, over a window widened by
    `slack` so a time-warped occurrence still fits inside the re-ranked span.

    Returns (start_sym, end_sym, distance) with distance on the EDIT scale for
    re-ranked candidates. Candidates beyond `rerank_k` keep their MINDIST rank
    but are returned with distance = inf, because mixing two distance scales in
    one column would make every threshold meaningless.
    """
    seq = msax.symbols(scale, offset)
    w = len(seed)
    if len(seq) < w:
        z = np.empty(0, dtype=np.int64)
        return z, z, np.empty(0, dtype=float)

    table = symbol_distance_table(msax, scale)
    if indel_cost is None:
        nz = table[table > 0]
        indel_cost = float(np.median(nz)) if nz.size else 1.0

    i0, i1, md = match_mindist(seed.symbols, seq, table, scale)
    if i0.size == 0:
        return i0, i1, md

    head = msax.encodings[(scale, int(offset))]["n_dropped_head"]
    sep = min_separation if min_separation is not None else w * scale
    keep = suppress_overlaps(head + i0 * scale, head + (i1 + 1) * scale, md, sep,
                             max_keep=n_candidates)
    i0, i1, md = i0[keep], i1[keep], md[keep]

    n_re = min(rerank_k, len(i0))
    order = np.argsort(md, kind="stable")[:n_re]
    win_len = int(np.ceil(w * (1.0 + slack)))
    ed = _edit_distance_to_windows(seed.symbols, seq, table,
                                   i0[order], np.full(n_re, win_len), indel_cost)

    dist = np.full(len(i0), np.inf)
    dist[order] = ed
    return i0, i1, dist


# ──────────────────────────────────────────────────────────────────────────────
#  Hit generation (real or surrogate), one entry point so the null matches
# ──────────────────────────────────────────────────────────────────────────────

def _hits_one(msax, seed_by_scale, scales, matcher, n_candidates, rerank_k,
              indel_cost, offsets="computed"):
    """
    Run one search across scales and return a tidy frame.

    `seed_by_scale` is pre-built from the REAL pyramid. This is the trap this
    function exists to close: `search()` calls `Seed.re_encode`, which would
    re-encode the seed from the SURROGATE's samples and silently replace the
    motif being tested with whatever noise sits at those indices. The seed must
    be fixed; only the corpus varies.
    """
    frames = []
    for s in scales:
        sd = seed_by_scale[s]
        # Explicit string handling: `list("all")` silently yields
        # ['a','l','l'], which then fails deep inside the index mapping with a
        # message that names neither this function nor the offending argument.
        if isinstance(offsets, str):
            if offsets in ("computed", "all"):
                offs = msax.offsets_for(s)
            elif offsets == "zero":
                offs = [0]
            else:
                raise ValueError(
                    f"offsets must be 'computed', 'all', 'zero', or a sequence "
                    f"of ints; got {offsets!r}")
        else:
            offs = [int(o) for o in offsets]
        for off in offs:
            if matcher == "cascade":
                i0, i1, dist = cascade_hits(msax, sd, s, off,
                                            n_candidates=n_candidates,
                                            rerank_k=rerank_k,
                                            indel_cost=indel_cost)
                ok = np.isfinite(dist)
                i0, i1, dist = i0[ok], i1[ok], dist[ok]
            else:
                df = search(msax, sd, matcher=matcher, scales=[s],
                            offsets=[off], max_results=n_candidates,
                            exclude_self=False,
                            matcher_kwargs={"indel_cost": indel_cost}
                            if matcher == "edit" else {})
                if df.empty:
                    continue
                head = msax.encodings[(s, int(off))]["n_dropped_head"]
                i0 = ((df["start_sample"].to_numpy() - head) // s)
                i1 = ((df["end_sample"].to_numpy() - head) // s) - 1
                dist = df["distance"].to_numpy()
            if len(i0) == 0:
                continue
            head = msax.encodings[(s, int(off))]["n_dropped_head"]
            frames.append(pd.DataFrame({
                "start_sample": head + i0 * s,
                "end_sample": head + (i1 + 1) * s,
                "scale": s, "offset": int(off), "distance": dist,
            }))
    if not frames:
        return pd.DataFrame(columns=["start_sample", "end_sample", "scale",
                                     "offset", "distance"])
    return pd.concat(frames, ignore_index=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Null distribution
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class NullModel:
    """Empirical null for one (seed, scales, matcher, surrogate) combination."""
    hit_distances: np.ndarray       # pooled, all hits over all surrogates
    best_distances: np.ndarray      # per-surrogate minimum
    per_scale: dict                 # scale -> pooled distances at that scale
    n_surrogates: int
    surrogate: str
    matcher: str
    scales: list
    seed_id: str
    seconds: float = 0.0
    meta: dict = field(default_factory=dict)

    @property
    def p_floor(self):
        """
        Arithmetic floor of the per-hit empirical p-value: 1/(n_pooled + 1).

        Per-hit p-values are computed against the POOLED hit distances, so this
        is small - but see `p_resolution`, which is the number that should
        actually govern belief.
        """
        return 1.0 / (len(self.hit_distances) + 1)

    @property
    def p_resolution(self):
        """
        The p-value below which this null cannot be trusted: 1/n_surrogates.

        The pooled hit distances number in the tens of thousands, but they come
        from only `n_surrogates` INDEPENDENT realisations. Pooling estimates the
        bulk of the null CDF well; in the far tail the estimate rests on a
        handful of surrogates, so a reported p of 1e-4 from 25 surrogates is
        arithmetic, not evidence. `detect` flags hits below this as
        `p_below_resolution` and the writeup should not quote them as exact.

        Raise `n_surrogates` to push this down - it is the only thing that does.
        """
        return 1.0 / max(self.n_surrogates, 1)

    @property
    def p_floor_best(self):
        """Floor for a test against `best_distances`: 1/(n_surrogates + 1)."""
        return 1.0 / (self.n_surrogates + 1)

    def __repr__(self):
        return (f"NullModel(seed={self.seed_id!r}, {self.surrogate}, "
                f"{self.matcher}, N={self.n_surrogates} surrogates, "
                f"{len(self.hit_distances)} pooled hits, "
                f"p_floor={self.p_floor:.2e}, "
                f"trust floor={self.p_resolution:.4f})")


def _code_fingerprint():
    """
    Hash of the source of every function that determines a null's contents.

    The cache key covers parameters and learned cutlines, but a cached null is
    equally invalidated by editing the SEARCH, and nothing about the parameters
    changes when you do. This was not hypothetical: two runs of this file with
    identical arguments produced 152 vs 158 hits and differing pooled-null
    sizes purely because the matcher had been edited in between, and a
    parameter-only key would have served the stale null instead of rebuilding.

    Hashing the source catches that automatically, at the cost of invalidating
    the cache on cosmetic edits too - the right trade when the alternative is
    silently mixing a new search with an old null.
    """
    import inspect
    src = []
    for fn in (_hits_one, cascade_hits, _edit_distance_to_windows,
               match_mindist, _subseq_edit_dp, encode_like, suppress_overlaps,
               fourier_surrogate, iaaft_surrogate, block_bootstrap):
        try:
            src.append(inspect.getsource(fn))
        except (OSError, TypeError):
            # A jitted or C-level callable may have no retrievable source;
            # fall back to its qualified name so the key stays stable.
            src.append(getattr(fn, "__qualname__", repr(fn)))
    return hashlib.sha256("".join(src).encode("utf-8")).hexdigest()[:12]


_CODE_FINGERPRINT = None


def _null_key(msax, seed, scales, matcher, surrogate, n_surrogates, extra=""):
    global _CODE_FINGERPRINT
    if _CODE_FINGERPRINT is None:
        _CODE_FINGERPRINT = _code_fingerprint()
    h = hashlib.sha256()
    h.update(_CODE_FINGERPRINT.encode())
    h.update(np.ascontiguousarray(seed.symbols).tobytes())
    h.update(str([int(s) for s in scales]).encode())
    h.update(f"{matcher}|{surrogate}|{n_surrogates}|{extra}".encode())
    h.update(f"{msax.method}|{msax.cutline_mode}|{msax.alphabet_size}".encode())
    h.update(f"{msax.x_mean:.12g}|{msax.x_std:.12g}|{msax.n_samples}".encode())
    for s in scales:
        h.update(np.ascontiguousarray(msax.scale_info[s]["cutlines"]).tobytes())
    return h.hexdigest()[:16]


def build_null(msax, seed_by_scale, scales, matcher="cascade",
               surrogate="fourier", n_surrogates=200, n_candidates=2000,
               rerank_k=200, indel_cost=None, random_state=0, n_jobs=1,
               cache=True, cache_dir=None, surrogate_kwargs=None,
               progress=False, offsets=DEFAULT_OFFSETS):
    """
    Empirical null: run the identical search over `n_surrogates` surrogates.

    Every surrogate is encoded via `encode_like`, so the quantiser is frozen
    and only the signal varies. The seed is likewise frozen - see `_hits_one`.

    Caching is on by default and keyed by the seed symbols, scales, matcher,
    surrogate type, surrogate count, and the learned cutlines themselves. Change
    any of those and you get a fresh null rather than a stale one; this is the
    expensive step (200 searches) and it is the one most likely to be silently
    reused after a parameter change.

    `n_jobs > 1` uses threads. Surrogate generation is FFT-bound and the
    MINDIST scan is numpy fancy-indexing, both of which release the GIL, so
    threads help; the jitted edit DP does not, so the cascade scales worse than
    plain `mindist`. Measured speedups are reported by the runner rather than
    assumed here.
    """
    surrogate_kwargs = dict(surrogate_kwargs or {})
    cache_dir = _Path(cache_dir) if cache_dir else CACHE_DIR
    key = _null_key(msax, seed_by_scale[scales[0]], scales, matcher, surrogate,
                    n_surrogates,
                    extra=f"{sorted(surrogate_kwargs.items())}|{offsets}")
    path = cache_dir / f"null_{key}.npz"

    if cache and path.exists():
        d = np.load(path, allow_pickle=True)
        return NullModel(
            hit_distances=d["hit_distances"], best_distances=d["best_distances"],
            per_scale={int(k): v for k, v in d["per_scale"].item().items()},
            n_surrogates=int(d["n_surrogates"]), surrogate=str(d["surrogate"]),
            matcher=str(d["matcher"]), scales=[int(s) for s in d["scales"]],
            seed_id=str(d["seed_id"]), seconds=float(d["seconds"]),
            meta={"cached": True, "path": str(path)})

    x_raw = msax._x * msax.x_std + msax.x_mean if msax.normalize else msax._x
    t0 = time.perf_counter()

    def _one(i):
        rng = np.random.default_rng(random_state + 1000 * i)
        xs = make_surrogate(x_raw, surrogate, rng, **surrogate_kwargs)
        sur = encode_like(msax, xs, check=(i == 0))       # assert once, cheaply
        return _hits_one(sur, seed_by_scale, scales, matcher, n_candidates,
                         rerank_k, indel_cost, offsets=offsets)

    if n_jobs and n_jobs > 1:
        with ThreadPoolExecutor(max_workers=n_jobs) as ex:
            frames = list(ex.map(_one, range(n_surrogates)))
    else:
        frames = []
        for i in range(n_surrogates):
            frames.append(_one(i))
            if progress and (i + 1) % 25 == 0:
                print(f"      surrogate {i+1}/{n_surrogates} "
                      f"({time.perf_counter()-t0:.0f}s)")

    pooled, best, per_scale = [], [], {int(s): [] for s in scales}
    for f in frames:
        if f.empty:
            best.append(np.inf)
            continue
        d = f["distance"].to_numpy()
        pooled.append(d)
        best.append(float(d.min()))
        for s in scales:
            sub = f.loc[f["scale"] == s, "distance"].to_numpy()
            if sub.size:
                per_scale[int(s)].append(sub)

    null = NullModel(
        hit_distances=np.concatenate(pooled) if pooled else np.empty(0),
        best_distances=np.asarray(best, dtype=float),
        per_scale={s: (np.concatenate(v) if v else np.empty(0))
                   for s, v in per_scale.items()},
        n_surrogates=int(n_surrogates), surrogate=surrogate, matcher=matcher,
        scales=[int(s) for s in scales],
        seed_id=seed_by_scale[scales[0]].seed_id,
        seconds=time.perf_counter() - t0,
        meta={"cached": False, "path": str(path),
              "surrogate_kwargs": surrogate_kwargs})

    if cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path, hit_distances=null.hit_distances,
            best_distances=null.best_distances,
            per_scale=np.array(null.per_scale, dtype=object),
            n_surrogates=null.n_surrogates, surrogate=null.surrogate,
            matcher=null.matcher, scales=np.array(null.scales),
            seed_id=null.seed_id, seconds=null.seconds)
    return null


# ──────────────────────────────────────────────────────────────────────────────
#  Significance
# ──────────────────────────────────────────────────────────────────────────────

def empirical_p(distances, null_distances):
    """
    Add-one corrected left-tailed empirical p-value: the fraction of null hits
    at least as GOOD (as small) as each observed distance.

        p = (1 + #{null <= d}) / (1 + N_null)

    The add-one is not cosmetic: without it a hit better than every surrogate
    reports p = 0, which is a claim the experiment cannot support. With it the
    floor is 1/(N+1), which is the honest resolution limit of N surrogates.
    """
    null_sorted = np.sort(np.asarray(null_distances, dtype=float))
    n = len(null_sorted)
    if n == 0:
        return np.full(len(distances), np.nan)
    below = np.searchsorted(null_sorted, np.asarray(distances, float), side="right")
    return (1.0 + below) / (1.0 + n)


def null_z(distances, null_distances):
    """
    Signed z-score against the null. NEGATIVE means better (closer) than the
    null average, which is the direction of evidence.

    Reported alongside the empirical p because the p-value saturates at its
    floor: once several hits all sit below every surrogate, only the z
    distinguishes them.
    """
    null_distances = np.asarray(null_distances, dtype=float)
    if null_distances.size < 2:
        return np.full(len(distances), np.nan)
    mu, sd = float(null_distances.mean()), float(null_distances.std())
    if sd <= 0:
        return np.full(len(distances), np.nan)
    return (np.asarray(distances, float) - mu) / sd


def benjamini_hochberg(p, alpha=0.05):
    """
    Benjamini-Hochberg step-up FDR.

    Returns (q_values, rejected, critical_p). `q` is the standard monotone
    step-up adjustment; `critical_p` is the largest p that was rejected, i.e.
    the detection threshold this search actually used - which is the number to
    report, because it varies with how many hits were tested.

    BH assumes independence or positive regression dependence. Hits here are
    non-overlapping by construction, which is not proof of independence but is
    the reason this is defensible rather than arbitrary; overlapping windows
    would be strongly positively dependent and would need BY instead.
    """
    p = np.asarray(p, dtype=float)
    m = len(p)
    if m == 0:
        return np.empty(0), np.empty(0, dtype=bool), np.nan
    order = np.argsort(p, kind="stable")
    ranked = p[order]
    q_sorted = np.minimum.accumulate((ranked * m / np.arange(1, m + 1))[::-1])[::-1]
    q_sorted = np.clip(q_sorted, 0, 1)
    q = np.empty(m, dtype=float)
    q[order] = q_sorted
    rejected = q <= alpha
    critical_p = float(ranked[rejected[order]].max()) if rejected.any() else np.nan
    return q, rejected, critical_p


# ──────────────────────────────────────────────────────────────────────────────
#  Detection
# ──────────────────────────────────────────────────────────────────────────────

DETECT_COLUMNS = ["start_sample", "end_sample", "scale", "offset", "channel",
                  "distance", "z", "p_value", "q_value", "significant",
                  "p_below_resolution", "rank", "matcher", "surrogate", "seed_id"]


def seed_alphabet_fraction(msax, seed):
    """Fraction of the realised alphabet the seed actually uses."""
    a = msax.scale_info[seed.scale]["alphabet_size"]
    sym = seed.symbols[seed.symbols != WILDCARD]
    return float(np.count_nonzero(np.bincount(sym, minlength=a))) / a


def detect(msax, seed, matcher="cascade", alpha=0.05, scales=None,
           surrogate="fourier", n_surrogates=200, n_candidates=2000,
           rerank_k=200, indel_cost=None, random_state=0, n_jobs=1,
           cache=True, exclude_self=True, null=None, warn=True,
           surrogate_kwargs=None, progress=False, offsets=DEFAULT_OFFSETS):
    """
    Significant recurrences of `seed` across a whole channel.

    Parameters
    ----------
    matcher : {"cascade", "mindist", "edit"}
        Default "cascade" = MINDIST candidates re-ranked by weighted edit
        distance, which is stage 3's recommendation. "exact" is deliberately
        not offered.
    alpha : float
        Target FDR after Benjamini-Hochberg.
    scales : list[int], optional
        Defaults to every scale up to `MAX_DETECT_SPS` at which the seed is
        between 8 and 128 symbols.
    surrogate : {"fourier", "iaaft", "block"}
    null : NullModel, optional
        Pre-built null; skips the expensive step.

    Returns
    -------
    (DataFrame[DETECT_COLUMNS], NullModel)

    Notes
    -----
    The p-value floor is 1/(n_surrogates + 1). With the default 200 that is
    0.005, so a search returning thousands of hits cannot produce a
    BH-significant result at small alpha unless many hits share the floor -
    raise `n_surrogates` if the q-values bottom out.
    """
    if matcher == "exact":
        raise ValueError(
            "The 'exact' matcher was dropped after stage 3: it was neither the "
            "fastest nor the most selective, and any change to the cutlines "
            "invalidates every stored seed string. Use 'cascade' (default), "
            "'mindist', or 'edit'.")

    seed_len = (seed.end_sample - seed.start_sample) if seed.start_sample is not None \
        else len(seed) * seed.scale
    if scales is None:
        scales = [s for s in msax.scales
                  if s <= MAX_DETECT_SPS and 8 <= seed_len // s <= 128]
        if not scales:
            scales = [min(msax.scales, key=lambda s: abs(seed_len // s - 32))]
    scales = sorted(int(s) for s in scales)

    # Freeze the seed at every scale, from the REAL pyramid, before any
    # surrogate exists.
    seed_by_scale = {s: seed.re_encode(msax, s) for s in scales}

    if warn:
        bl = (surrogate_kwargs or {}).get("block_length")
        if surrogate == "block" and bl is not None and bl >= 0.5 * seed_len:
            print(f"  [warn] block_length={bl} is >= half the seed span "
                  f"({seed_len}). A single block can then contain the motif "
                  f"itself, so the null includes what you are testing for and "
                  f"nothing will reach significance. Use block_length well "
                  f"below {seed_len // 2}.")
        for s in scales:
            frac = seed_alphabet_fraction(msax, seed_by_scale[s])
            if frac < MIN_ALPHABET_FRAC:
                print(f"  [warn] seed uses {frac:.0%} of the alphabet at sps={s}. "
                      f"Stage 3 finding: below ~50% the encoding is describing "
                      f"drift level rather than shape, and hits will be flat "
                      f"regions at a similar baseline. Detrend first.")
                break

    if null is None:
        null = build_null(msax, seed_by_scale, scales, matcher=matcher,
                          surrogate=surrogate, n_surrogates=n_surrogates,
                          n_candidates=n_candidates, rerank_k=rerank_k,
                          indel_cost=indel_cost, random_state=random_state,
                          n_jobs=n_jobs, cache=cache,
                          surrogate_kwargs=surrogate_kwargs, progress=progress,
                          offsets=offsets)

    # The observed search MUST use the same offsets as the null, or the two
    # distance distributions are not comparable.
    obs = _hits_one(msax, seed_by_scale, scales, matcher, n_candidates,
                    rerank_k, indel_cost, offsets=offsets)
    if obs.empty:
        return pd.DataFrame(columns=DETECT_COLUMNS), null

    if exclude_self and seed.start_sample is not None:
        overlap = ((obs["start_sample"] < seed.end_sample)
                   & (obs["end_sample"] > seed.start_sample))
        obs = obs.loc[~overlap].reset_index(drop=True)
        if obs.empty:
            return pd.DataFrame(columns=DETECT_COLUMNS), null

    # Collapse across scales and offsets: the same event found at sps=16 and
    # sps=32 is one recurrence, not two. Done before the p-values so the
    # multiple-testing family is events, not (event x scale) duplicates.
    sep = int(np.median(obs["end_sample"] - obs["start_sample"]))
    keep = suppress_overlaps(obs["start_sample"].to_numpy(),
                             obs["end_sample"].to_numpy(),
                             obs["distance"].to_numpy(), sep)
    obs = obs.iloc[keep].reset_index(drop=True)

    # ── Power guard ───────────────────────────────────────────────────────────
    # A null with no spread cannot separate anything, so every p-value comes
    # back at 1.0 and the result reads as a clean negative when in fact no test
    # was performed. This happens whenever the encoding is degenerate: measured
    # on M2_aug CH2 detrended, 90% of symbols were a single value and the seed
    # was 32/37 that same symbol, so every observed AND surrogate distance was
    # exactly 0.0. "Nothing significant" and "no test had power" must never be
    # reported as the same thing.
    null_spread = float(np.std(null.hit_distances)) if len(null.hit_distances) else 0.0
    obs_unique = int(pd.Series(obs["distance"]).nunique())
    degenerate = (null_spread <= 1e-12) or (obs_unique <= 1)
    if degenerate:
        frac = seed_alphabet_fraction(msax, seed_by_scale[scales[0]])
        msg = (f"DEGENERATE TEST at scales {scales}: null distance spread "
               f"{null_spread:.3g}, {obs_unique} distinct observed distance(s), "
               f"seed uses {frac:.0%} of the alphabet. Every p-value will be "
               f"1.0 because the statistic cannot separate anything - this is "
               f"NO POWER, not a negative result. Do not report it as evidence "
               f"of absence. Fix the encoding first (rolling_z preprocessing "
               f"raised the realised alphabet from 38% to 100% on this "
               f"channel); see MIN_ALPHABET_FRAC.")
        if warn:
            print(f"  [ERROR] {msg}")

    obs["p_value"] = empirical_p(obs["distance"].to_numpy(), null.hit_distances)
    obs["z"] = null_z(obs["distance"].to_numpy(), null.hit_distances)
    q, rejected, crit = benjamini_hochberg(obs["p_value"].to_numpy(), alpha)
    obs["q_value"] = q
    obs["significant"] = rejected
    # Flag hits whose p-value is finer than the null's independent resolution
    # (1/n_surrogates). They are not wrong, but their exact value is not
    # supported by the number of surrogates actually run.
    obs["p_below_resolution"] = obs["p_value"] < null.p_resolution
    obs["channel"] = getattr(msax, "channel", seed.channel)
    obs["matcher"] = matcher
    obs["surrogate"] = surrogate
    obs["seed_id"] = seed.seed_id

    obs = obs.sort_values(["q_value", "distance"], kind="stable").reset_index(drop=True)
    obs["rank"] = np.arange(len(obs))
    obs.attrs["critical_p"] = crit
    obs.attrs["p_floor"] = null.p_floor
    obs.attrs["p_resolution"] = null.p_resolution
    obs.attrs["alpha"] = alpha
    obs.attrs["n_tested"] = len(obs)
    obs.attrs["n_below_resolution"] = int(obs["p_below_resolution"].sum())
    # Callers MUST check this before reporting a null finding.
    obs.attrs["degenerate"] = bool(degenerate)
    obs.attrs["null_spread"] = null_spread
    obs.attrs["n_distinct_distances"] = obs_unique
    return obs[DETECT_COLUMNS], null


def scale_signature(msax, seed, matcher="cascade", alpha=0.05, scales=None,
                    surrogate="fourier", n_surrogates=200, n_jobs=1,
                    cache=True, offsets=DEFAULT_OFFSETS, **kwargs):
    """
    Per-scale detection summary - the "scale signature" of a seed.

    A structure significant at ONE scale is a different finding from one
    significant across a BAND of scales: the first is a feature of a particular
    resolution (and is often an artefact of where the PAA grid happens to
    average), the second is genuinely multiscale and much harder to explain
    away. This surfaces that distinction directly rather than leaving it to be
    inferred from a hit list.

    Returns a DataFrame: scale, minutes, n_hits, n_significant, frac_covered,
    best_p, best_z, median_distance.

    `frac_covered` is the fraction of the recording spanned by significant
    recurrences at that scale. A high value is a warning, not a triumph: if 40%
    of the channel is "significant", the seed is matching background.
    """
    seed_len = (seed.end_sample - seed.start_sample) if seed.start_sample is not None \
        else len(seed) * seed.scale
    if scales is None:
        scales = [s for s in msax.scales
                  if s <= MAX_DETECT_SPS and 8 <= seed_len // s <= 128]
    rows = []
    for s in sorted(scales):
        df, null = detect(msax, seed, matcher=matcher, alpha=alpha, scales=[s],
                          surrogate=surrogate, n_surrogates=n_surrogates,
                          n_jobs=n_jobs, cache=cache, warn=False,
                          offsets=offsets, **kwargs)
        sig = df[df["significant"]] if len(df) else df
        covered = int((sig["end_sample"] - sig["start_sample"]).sum()) if len(sig) else 0
        rows.append({
            "scale": s,
            "minutes": msax.scale_info[s]["minutes"],
            "n_symbols": len(seed.re_encode(msax, s)),
            "n_hits": len(df),
            "n_significant": len(sig),
            "frac_covered": covered / max(msax.n_samples, 1),
            "best_p": float(df["p_value"].min()) if len(df) else np.nan,
            "best_z": float(df["z"].min()) if len(df) else np.nan,
            "median_distance": float(df["distance"].median()) if len(df) else np.nan,
            "p_floor": null.p_floor,
            "p_resolution": null.p_resolution,
        })
    out = pd.DataFrame(rows)
    n_sig_scales = int((out["n_significant"] > 0).sum())
    out.attrs["signature"] = (
        "none" if n_sig_scales == 0 else
        "single-scale" if n_sig_scales == 1 else
        f"band ({n_sig_scales}/{len(out)} scales)")
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  Plots  (return Figures; nothing is saved)
# ──────────────────────────────────────────────────────────────────────────────

def plot_significance_by_scale(sig_df, seed_id="", figsize=(11, 4.6)):
    """
    Scale signature for one seed: significant-recurrence count and best
    p-value against scale, with the p-value floor marked.

    The floor line matters - a curve sitting on it is reporting "better than
    every surrogate I generated", not "p = 0.005 exactly", and the only way to
    push it lower is more surrogates.
    """
    import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(1, 2, figsize=figsize, layout="constrained")

    x = np.arange(len(sig_df))
    a1.bar(x - 0.2, sig_df["n_hits"], width=0.38, color="#c9d6e4", label="hits tested")
    a1.bar(x + 0.2, sig_df["n_significant"], width=0.38, color="#3b6ea5",
           label="significant (BH)")
    a1.set_xticks(x)
    a1.set_xticklabels([f"{int(s)}\n{m:.0f}m" for s, m in
                        zip(sig_df["scale"], sig_df["minutes"])], fontsize=8)
    a1.set_xlabel("samples per symbol")
    a1.set_ylabel("recurrences")
    a1.legend(fontsize=8)
    a1.grid(axis="y", alpha=0.25, lw=0.5)
    a1.set_title(f"Scale signature{': ' + seed_id if seed_id else ''}"
                 f"  [{sig_df.attrs.get('signature', '')}]", fontsize=10, loc="left")

    a2.plot(x, sig_df["best_p"], "o-", color="#2f6f4f", lw=1.8, label="best p")
    res = float(sig_df["p_resolution"].iloc[0]) if len(sig_df) else np.nan
    a2.axhline(res, color="#b3402f", ls="--", lw=1.2,
               label=f"null resolution 1/N = {res:.4f}\n(below this: not evidence)")
    a2.axhline(0.05, color="0.5", ls=":", lw=1.0, label="alpha = 0.05")
    a2.set_yscale("log")
    a2.set_xticks(x)
    a2.set_xticklabels([str(int(s)) for s in sig_df["scale"]], fontsize=8)
    a2.set_xlabel("samples per symbol")
    a2.set_ylabel("p-value (log)")
    a2.legend(fontsize=8)
    a2.grid(alpha=0.25, lw=0.5)
    a2.set_title("Best p-value by scale", fontsize=10, loc="left")
    return fig


def plot_detection_timeline(msax, hits, null, seed=None, fs=None,
                            figsize=(13.5, 6.0)):
    """
    Channel-wide timeline: signal on top, every tested recurrence below with
    the null band shaded and significant hits marked.

    The shaded band is the 5th-95th percentile of the null hit distances. A hit
    inside it is indistinguishable from what a spectrum-matched surrogate
    produces, however good its raw distance looks.
    """
    import matplotlib.pyplot as plt
    fs = fs or msax.fs
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=figsize, sharex=True,
                                  gridspec_kw={"height_ratios": [2.0, 1.5]},
                                  layout="constrained")

    hrs = np.arange(msax.n_samples) / fs / 3600.0
    ax.plot(hrs, msax._x, lw=0.35, color="0.3")
    sig = hits[hits["significant"]] if len(hits) else hits
    for _, h in sig.iterrows():
        ax.axvspan(h["start_sample"] / fs / 3600, h["end_sample"] / fs / 3600,
                   color="#2f6f4f", alpha=0.35)
    if seed is not None and seed.start_sample is not None:
        ax.axvspan(seed.start_sample / fs / 3600, seed.end_sample / fs / 3600,
                   color="#b3402f", alpha=0.5)
        ax.text(seed.start_sample / fs / 3600, ax.get_ylim()[1], " seed",
                fontsize=8, color="#b3402f", va="top")
    ax.set_ylabel("signal (z)")
    ax.margins(x=0)
    ax.set_title(
        f"Seeded recurrences - {len(sig)}/{len(hits)} significant at "
        f"BH alpha={hits.attrs.get('alpha', 0.05)} "
        f"({null.matcher}, {null.surrogate} null, N={null.n_surrogates})",
        fontsize=10, loc="left")

    if len(null.hit_distances):
        lo, hi = np.percentile(null.hit_distances, [5, 95])
        ax2.axhspan(lo, hi, color="0.75", alpha=0.45,
                    label="null 5th-95th percentile")
        ax2.axhline(float(np.median(null.hit_distances)), color="0.4", ls="--",
                    lw=1.0, label="null median")
    if len(hits):
        c = 0.5 * (hits["start_sample"] + hits["end_sample"]) / fs / 3600
        ax2.scatter(c[~hits["significant"]], hits.loc[~hits["significant"], "distance"],
                    s=10, color="0.55", label="not significant", zorder=3)
        if len(sig):
            cs = 0.5 * (sig["start_sample"] + sig["end_sample"]) / fs / 3600
            ax2.scatter(cs, sig["distance"], s=34, color="#2f6f4f",
                        edgecolors="k", linewidths=0.4, label="significant", zorder=4)
    ax2.set_xlabel("time (hours)")
    ax2.set_ylabel(f"{null.matcher} distance")
    ax2.legend(fontsize=8, loc="upper right", framealpha=0.9)
    ax2.grid(alpha=0.25, lw=0.5)
    ax2.margins(x=0)
    return fig


def plot_vs_matrix_profile(msax, hits, mp, m, fs=None, top_k=10,
                           figsize=(13.5, 6.4)):
    """
    Seeded recurrences overlaid on the stumpy matrix profile.

    Matrix profile finds the most-repeated subsequences with no seed at all, so
    agreement is genuine corroboration by an independent method. Disagreement
    is not automatically failure - a seeded search answers "where else does
    THIS occur", which is a different question from "what repeats most" - but
    it does mean the seeded result has no external support.
    """
    import matplotlib.pyplot as plt
    fs = fs or msax.fs
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=figsize, sharex=True,
                                  gridspec_kw={"height_ratios": [1.9, 1.4]},
                                  layout="constrained")

    hrs = np.arange(msax.n_samples) / fs / 3600.0
    ax.plot(hrs, msax._x, lw=0.35, color="0.3")
    sig = hits[hits["significant"]] if len(hits) else hits
    for _, h in sig.iterrows():
        ax.axvspan(h["start_sample"] / fs / 3600, h["end_sample"] / fs / 3600,
                   color="#2f6f4f", alpha=0.35)
    motif_idx = matrix_profile_motifs(mp, m, top_k=top_k)
    for i in motif_idx:
        ax.axvspan(i / fs / 3600, (i + m) / fs / 3600, color="#c07a1f", alpha=0.30)
    ax.set_ylabel("signal (z)")
    ax.margins(x=0)
    ax.set_title(f"Seeded recurrences (green) vs top-{top_k} matrix-profile "
                 f"motifs (orange), m={m} samples", fontsize=10, loc="left")

    ax2.plot(hrs[:len(mp)], mp, lw=0.5, color="#3b6ea5")
    for i in motif_idx:
        ax2.plot(i / fs / 3600, mp[i], "v", color="#c07a1f", ms=7)
    ax2.set_ylabel("matrix profile")
    ax2.set_xlabel("time (hours)")
    ax2.grid(alpha=0.25, lw=0.5)
    ax2.margins(x=0)
    return fig


def matrix_profile_motifs(mp, m, top_k=10, exclusion=None):
    """
    Top-k matrix-profile motif start indices with a trivial-match exclusion
    zone, greedily from the lowest profile value up.

    Without the exclusion zone the top k are all neighbours of one motif -
    exactly the smearing that `suppress_overlaps` handles on the seeded side,
    so both methods must be de-duplicated the same way before their overlap
    means anything.
    """
    mp = np.asarray(mp, dtype=float)
    exclusion = exclusion if exclusion is not None else m
    order = np.argsort(mp)
    picked = []
    for i in order:
        if not np.isfinite(mp[i]):
            continue
        if all(abs(int(i) - j) >= exclusion for j in picked):
            picked.append(int(i))
        if len(picked) >= top_k:
            break
    return picked
