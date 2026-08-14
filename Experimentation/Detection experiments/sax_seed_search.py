"""
sax_seed_search.py
==================
Seeded motif search over a `multiscale_sax.MultiScaleSAX` pyramid.

Given a motif of interest - a raw sample span on a channel, or a symbol string
typed by hand - find other occurrences of similar structure in the same
channel, in other channels, and at other scales.

Three matchers behind one interface
------------------------------------
"exact"    literal substring search with '?' wildcards and up to `max_hamming`
           substitutions. The speed baseline.
"mindist"  SAX MINDIST lower bound, with the symbol-distance table built from
           the cutlines this encoding actually learned - NOT from Gaussian
           breakpoints (see `symbol_distance_table`).
"edit"     symbol-weighted edit distance, substitution cost taken from the
           same MINDIST table. The symbolic analogue of DTW, and the only one
           of the three that can absorb a time-warped motif.

All three return per-symbol-normalised distances so a threshold means roughly
the same thing at every scale. They are NOT on a common absolute scale with
each other - "exact" counts mismatched symbols, the other two accumulate
cutline-unit distances. Compare matchers by rank and by recall, never by
whose number is smaller.

The lower-bound property
------------------------
MINDIST is only useful if it never exceeds the true distance - that is what
makes it safe for pruning. `verify_mindist_lower_bound` checks this
empirically over thousands of random window pairs and is run by the test
script. If it ever fails, the cutline table is wrong; fix the table rather
than subtracting a fudge factor, because a bound that holds "mostly" prunes
away real matches.

Conventions
-----------
Nothing runs at import time; no plots are saved. Every result carries raw
sample indices, so hits can be plotted against the signal and compared with
matrix-profile or rupture output on equal terms.
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

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

try:
    from numba import njit
    HAVE_NUMBA = True
except ImportError:                                  # pragma: no cover
    HAVE_NUMBA = False

    def njit(*a, **k):                               # type: ignore
        """No-op fallback. The edit matcher still runs, ~100x slower."""
        def deco(f):
            return f
        return deco(a[0]) if a and callable(a[0]) else deco


WILDCARD = -1          # internal representation of a '?' position in a seed

RESULT_COLUMNS = [
    "start_sample", "end_sample", "scale", "offset", "channel",
    "distance", "matcher", "seed_id",
    "distance_raw", "n_symbols", "rank",
]


# ──────────────────────────────────────────────────────────────────────────────
#  Seed
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Seed:
    """
    A motif to search for, as a symbol string plus enough provenance to
    re-encode it at another scale and to exclude its own location from results.

    Attributes
    ----------
    symbols : np.ndarray[int]
        0-based symbol indices; `WILDCARD` (-1) marks a '?' position.
    scale : int
        Samples-per-symbol the seed is currently expressed at.
    start_sample, end_sample : int | None
        The seed's own raw span, half-open. None for a hand-typed string,
        which is why such a seed cannot be re-encoded at another scale.
    channel : int | None
    seed_id : str
    origin : str
        "span" or "string".
    """
    symbols: np.ndarray
    scale: int
    start_sample: int = None
    end_sample: int = None
    channel: int = None
    seed_id: str = "seed"
    origin: str = "string"
    offset: int = 0
    meta: dict = field(default_factory=dict)

    def __len__(self):
        return len(self.symbols)

    @property
    def n_wildcards(self):
        return int(np.count_nonzero(self.symbols == WILDCARD))

    @property
    def span_samples(self):
        """Raw length the seed covers at its current scale."""
        return len(self.symbols) * self.scale

    def __repr__(self):
        body = " ".join("?" if s == WILDCARD else str(int(s)) for s in self.symbols)
        loc = (f"[{self.start_sample}, {self.end_sample})"
               if self.start_sample is not None else "typed")
        return (f"Seed({self.seed_id!r}, sps={self.scale}, w={len(self)}, "
                f"ch={self.channel}, {loc}: {body})")

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_span(cls, msax, start_sample, end_sample, scale,
                  seed_id=None, channel=None):
        """
        Encode a raw sample span at `scale` and use it as the seed.

        The span is encoded with `msax.encode_segment`, i.e. with the cutlines
        already learned for that scale, no retraining. It is deliberately NOT
        read out of the stored offset-0 symbol sequence: an arbitrary span
        rarely starts on the offset-0 PAA grid, and slicing the stored sequence
        would silently shift the seed by up to `scale` samples. Encoding the
        span directly means the seed is exactly the requested samples, and the
        offset sweep is what finds it in the corpus.

        The span is trimmed down to a whole number of symbols; the trimmed
        end is recorded in `end_sample`, never padded.
        """
        start_sample, end_sample = int(start_sample), int(end_sample)
        if end_sample <= start_sample:
            raise ValueError(
                f"end_sample ({end_sample}) must exceed start_sample ({start_sample})."
            )
        if scale not in msax.scale_info:
            raise KeyError(f"Scale {scale} is not in this pyramid ({msax.scales}).")
        if end_sample - start_sample < scale:
            raise ValueError(
                f"Span of {end_sample - start_sample} samples is shorter than one "
                f"symbol at scale {scale}."
            )

        # msax._x is already globally z-normalised, so do not re-apply it.
        seg = msax._x[start_sample:end_sample]
        symbols = msax.encode_segment(seg, scale, apply_global_norm=False)
        used_end = start_sample + len(symbols) * scale

        return cls(
            symbols=np.asarray(symbols, dtype=np.int64),
            scale=int(scale),
            start_sample=start_sample,
            end_sample=int(used_end),
            channel=channel if channel is not None else getattr(msax, "channel", None),
            seed_id=seed_id or f"span_{start_sample}_{end_sample}_sps{scale}",
            origin="span",
        )

    @classmethod
    def from_string(cls, symbols, scale, msax, seed_id=None, channel=None):
        """
        Build a seed from a literal symbol string, e.g. "3 5 6 6 4 2 1 2".

        Accepts whitespace-separated tokens (ints, or '?' for a wildcard), or
        a sequence of ints where -1 means wildcard. Symbols are validated
        against the realised alphabet at `scale`, so a typo that exceeds the
        alphabet fails loudly instead of matching nothing.

        A string seed has no raw span, so it cannot be re-encoded at another
        scale - `search(..., scales=[...])` will refuse. Use `from_span` when
        cross-scale search is wanted.
        """
        if scale not in msax.scale_info:
            raise KeyError(f"Scale {scale} is not in this pyramid ({msax.scales}).")
        alphabet = msax.scale_info[scale]["alphabet_size"]

        if isinstance(symbols, str):
            toks = symbols.replace(",", " ").split()
            parsed = []
            for tok in toks:
                if tok == "?":
                    parsed.append(WILDCARD)
                else:
                    try:
                        parsed.append(int(tok))
                    except ValueError:
                        raise ValueError(
                            f"Unparseable symbol {tok!r} in seed string. Expected "
                            f"integers 0..{alphabet - 1} or '?' for a wildcard."
                        )
            arr = np.asarray(parsed, dtype=np.int64)
        else:
            arr = np.asarray(symbols, dtype=np.int64)

        if arr.size == 0:
            raise ValueError("Seed string is empty.")
        bad = arr[(arr != WILDCARD) & ((arr < 0) | (arr >= alphabet))]
        if bad.size:
            raise ValueError(
                f"Seed contains symbols {np.unique(bad).tolist()} outside the "
                f"realised alphabet 0..{alphabet - 1} at scale {scale}."
            )

        return cls(
            symbols=arr, scale=int(scale),
            channel=channel if channel is not None else getattr(msax, "channel", None),
            seed_id=seed_id or f"string_sps{scale}_w{len(arr)}",
            origin="string",
        )

    def re_encode(self, msax, scale):
        """
        Express this seed at a different scale by re-encoding its RAW span.

        The symbol string is never resampled: a coarse symbol is not the
        average of two fine symbols, it is the symbol of the average, and
        those differ whenever the quantiser is non-linear (which it always is).
        Going back to the samples is the only correct route.
        """
        if int(scale) == self.scale:
            return self
        if self.origin != "span" or self.start_sample is None:
            raise ValueError(
                f"Seed {self.seed_id!r} was typed as a string and has no raw span, "
                f"so it cannot be re-encoded at scale {scale}. Build it with "
                f"Seed.from_span to search across scales."
            )
        out = Seed.from_span(msax, self.start_sample, self.end_sample, scale,
                             seed_id=self.seed_id, channel=self.channel)
        out.meta = dict(self.meta)
        return out


# ──────────────────────────────────────────────────────────────────────────────
#  Symbol distance table (the heart of MINDIST)
# ──────────────────────────────────────────────────────────────────────────────

def symbol_distance_table(msax, scale):
    """
    Build the symbol-distance table from the cutlines this encoding LEARNED.

        d(i, j) = 0                                       if |i - j| <= 1
        d(i, j) = cutlines[max(i,j) - 1] - cutlines[min(i,j)]   otherwise

    Why not the textbook table
    ---------------------------
    Standard SAX builds this from Gaussian breakpoints, because standard SAX
    assumes z-normalised data whose PAA is Gaussian. cSAX and pSAX exist
    precisely because that assumption fails on real data - they learn cutlines
    from the observed PAA distribution. Using Gaussian breakpoints against
    learned cutlines would compute the gap between symbols that were never
    placed there, and the bound would break in both directions: too loose
    where the learned cutlines are dense, and outright violated where they are
    sparse.

    Adjacent symbols get distance 0 because their regions touch: two values in
    neighbouring bins can be arbitrarily close, so any positive distance would
    not be a lower bound.

    Returns
    -------
    np.ndarray (a, a), symmetric, zero diagonal and zero first off-diagonals.
    """
    info = msax.scale_info[int(scale)]
    cut = np.asarray(info["cutlines"], dtype=float)
    a = int(info["alphabet_size"])
    if len(cut) != a - 1:
        raise ValueError(
            f"Scale {scale}: {len(cut)} cutlines for alphabet {a} - expected {a - 1}."
        )

    d = np.zeros((a, a), dtype=float)
    for i in range(a):
        for j in range(a):
            if abs(i - j) > 1:
                d[i, j] = cut[max(i, j) - 1] - cut[min(i, j)]
    if np.any(d < 0):
        raise ValueError(
            f"Scale {scale}: negative symbol distances - cutlines are not ascending."
        )
    return d


def _lowerbound_scale(msax, scale):
    """
    The std the encoder divided by at this scale, which the lower bound must
    be measured against.

    Under `cutline_mode="shared_renormalised"` the symbols quantise
    (paa - mean)/std, so MINDIST bounds the Euclidean distance between windows
    of the signal AFTER that same division. Forgetting the division makes the
    bound look violated by exactly a factor of std, which is a measurement bug,
    not a table bug.
    """
    info = msax.scale_info[int(scale)]
    if not info["renormalised"]:
        return 1.0
    std = float(info["paa_std"])
    return std if std > 1e-12 else 1.0


def mindist(sym_a, sym_b, table, scale):
    """
    MINDIST between two equal-length symbol strings.

        MINDIST = sqrt(n / w) * sqrt( sum_k d(a_k, b_k)^2 )

    with n the raw length (w * scale) and w the symbol length, so
    sqrt(n / w) = sqrt(scale). Wildcards contribute 0.
    """
    a = np.asarray(sym_a, dtype=np.int64)
    b = np.asarray(sym_b, dtype=np.int64)
    if len(a) != len(b):
        raise ValueError(f"MINDIST needs equal lengths; got {len(a)} and {len(b)}.")
    ok = (a != WILDCARD) & (b != WILDCARD)
    sq = float((table[a[ok], b[ok]] ** 2).sum())
    return float(np.sqrt(scale) * np.sqrt(sq))


# ──────────────────────────────────────────────────────────────────────────────
#  Lower-bound verification
# ──────────────────────────────────────────────────────────────────────────────

def verify_mindist_lower_bound(msax, scale, n_pairs=5000, offset=0,
                               random_state=0):
    """
    Check empirically that MINDIST never exceeds the true Euclidean distance.

    Draws `n_pairs` random pairs of equal-length windows from the encoded
    channel, computes MINDIST from the symbol strings and the true Euclidean
    distance from the raw samples, and reports both the violation count and
    the tightness of the bound.

    The true distance is measured on the signal the encoder actually quantised
    - globally z-normalised, then divided by this scale's PAA std where the
    cutline mode renormalises (see `_lowerbound_scale`). It is NOT measured on
    per-window z-normalised data: this encoder normalises globally, so
    per-window normalisation would compare against a series the symbols were
    never derived from, and the bound would fail for that reason alone.

    Returns
    -------
    dict with: scale, n_pairs, w, n_violations, worst_violation, ratio_mean,
    ratio_median, ratio_p95, mindist (array), true_dist (array).

    `ratio_mean` is the tightness: MINDIST / true distance, in (0, 1]. Higher
    is tighter and prunes better; a mean near 0.1 means the bound rejects
    almost nothing and the search degenerates to brute force.
    """
    rng = np.random.default_rng(random_state)
    s = int(scale)
    info = msax.scale_info[s]
    sym = msax.symbols(s, offset)
    table = symbol_distance_table(msax, s)
    sigma = _lowerbound_scale(msax, s)

    # Window length in symbols: long enough to be a realistic motif, short
    # enough that many disjoint windows exist even at the coarsest scale.
    w = int(min(16, max(4, len(sym) // 8)))
    n_windows = len(sym) - w + 1
    if n_windows < 2:
        raise ValueError(f"Scale {s} has too few symbols ({len(sym)}) to verify.")

    head = msax.encodings[(s, int(offset))]["n_dropped_head"]
    i = rng.integers(0, n_windows, size=n_pairs)
    j = rng.integers(0, n_windows, size=n_pairs)

    md = np.empty(n_pairs)
    td = np.empty(n_pairs)
    n_raw = w * s
    for k in range(n_pairs):
        ia, ib = int(i[k]), int(j[k])
        sq = float((table[sym[ia:ia + w], sym[ib:ib + w]] ** 2).sum())
        md[k] = np.sqrt(s) * np.sqrt(sq)

        a0 = head + ia * s
        b0 = head + ib * s
        wa = msax._x[a0:a0 + n_raw] / sigma
        wb = msax._x[b0:b0 + n_raw] / sigma
        td[k] = float(np.linalg.norm(wa - wb))

    # A pair of identical windows has both distances 0; exclude from the ratio
    # so it does not inject 0/0.
    live = td > 1e-12
    ratio = np.where(live, md / np.maximum(td, 1e-300), np.nan)
    violation = md - td
    n_viol = int(np.count_nonzero(violation > 1e-9))

    return {
        "scale": s, "offset": int(offset), "n_pairs": int(n_pairs), "w": w,
        "n_violations": n_viol,
        "worst_violation": float(violation.max()),
        "ratio_mean": float(np.nanmean(ratio)),
        "ratio_median": float(np.nanmedian(ratio)),
        "ratio_p95": float(np.nanpercentile(ratio[~np.isnan(ratio)], 95)),
        "mindist": md, "true_dist": td,
        "paa_std": float(info["paa_std"]), "sigma_used": sigma,
    }


def plot_mindist_bound(results, figsize=(11, 5.0)):
    """
    MINDIST against true Euclidean distance, one panel of scatter plus a
    tightness-by-scale summary. Returns a Figure; saves nothing.

    Every point must lie on or below the y = x line. Points hugging that line
    are a tight bound (good pruning); points near the x-axis are a loose bound
    that will force the search to compute nearly every true distance anyway.

    Parameters
    ----------
    results : list[dict] from `verify_mindist_lower_bound`, one per scale.
    """
    import matplotlib.pyplot as plt

    results = sorted(results, key=lambda r: r["scale"])
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=figsize,
                                  gridspec_kw={"width_ratios": [1.3, 1.0]},
                                  layout="constrained")

    cmap = plt.get_cmap("viridis")
    hi = 0.0
    for k, r in enumerate(results):
        c = cmap(k / max(len(results) - 1, 1))
        # Both axes divided by sqrt(raw window length). Each scale compares
        # windows of w*sps samples, so unnormalised distances grow with scale
        # and the scales separate into clusters that say nothing about the
        # bound. A common positive scaling of both axes leaves y = x exactly
        # where it was, so the check is unchanged and all scales overlay.
        norm = np.sqrt(r["w"] * r["scale"])
        ax.scatter(r["true_dist"] / norm, r["mindist"] / norm, s=3, alpha=0.25,
                   color=c, label=f"sps={r['scale']}", edgecolors="none")
        hi = max(hi, float(np.nanmax(r["true_dist"] / norm)))

    ax.plot([0, hi], [0, hi], "k--", lw=1.2, label="y = x (the bound)")
    ax.set_xlabel("true Euclidean distance / sqrt(window samples)")
    ax.set_ylabel("MINDIST / sqrt(window samples)")
    ax.set_xlim(0, hi * 1.02)
    ax.set_ylim(0, hi * 1.02)
    ax.grid(alpha=0.25, lw=0.5)
    ax.legend(fontsize=7, loc="upper left", markerscale=3, framealpha=0.9)
    total_viol = sum(r["n_violations"] for r in results)
    ax.set_title(
        f"MINDIST lower bound\n"
        f"{sum(r['n_pairs'] for r in results)} pairs, {total_viol} violations"
        + ("  (BOUND HOLDS)" if total_viol == 0 else "  (BOUND VIOLATED)"),
        fontsize=10, loc="left")

    x = np.arange(len(results))
    ax2.bar(x - 0.2, [r["ratio_mean"] for r in results], width=0.38,
            color="#3b6ea5", label="mean MINDIST / true")
    ax2.bar(x + 0.2, [r["ratio_p95"] for r in results], width=0.38,
            color="#9fc0e0", label="95th percentile")
    ax2.set_xticks(x)
    ax2.set_xticklabels([str(r["scale"]) for r in results], fontsize=8)
    ax2.set_xlabel("samples per symbol")
    ax2.set_ylabel("tightness (1.0 = exact)")
    ax2.set_ylim(0, 1.0)
    ax2.grid(axis="y", alpha=0.25, lw=0.5)
    ax2.legend(fontsize=8)
    ax2.set_title("Bound tightness - low means poor pruning", fontsize=10, loc="left")
    return fig


# ──────────────────────────────────────────────────────────────────────────────
#  Matchers
# ──────────────────────────────────────────────────────────────────────────────
#  Each returns (i_start, i_end_inclusive, distance) in SYMBOL units, with
#  `distance` already normalised per symbol.

def match_exact(seed_sym, seq, table, scale, max_hamming=0, chunk=1_000_000,
                **_):
    """
    Literal substring search with wildcards and up to `max_hamming` mismatches.

    Distance returned is mismatches / (non-wildcard symbols), i.e. a mismatch
    rate in [0, 1].

    Brittleness, stated plainly
    ----------------------------
    This matcher compares symbol IDs and nothing else, so it is destroyed by
    anything that shifts the alphabet: re-training the cutlines on a different
    span, a different `cutline_mode`, a different `alphabet_size`, or cSAX
    realising 7 symbols instead of 8. A motif that is one bin high everywhere
    - identical shape, slightly larger amplitude - scores as a total mismatch
    even though MINDIST would call it near-identical. Use it for speed
    baselines and for exact-repeat hunting, not for similarity.
    """
    w = len(seed_sym)
    n_win = len(seq) - w + 1
    if n_win <= 0:
        return _empty_hits()

    keep = np.flatnonzero(seed_sym != WILDCARD)
    if keep.size == 0:
        raise ValueError("Seed is entirely wildcards - every position would match.")
    want = seed_sym[keep]

    starts, dists = [], []
    for lo in range(0, n_win, chunk):
        hi = min(lo + chunk, n_win)
        # sliding_window_view is a view; only the comparison allocates, and
        # only for the non-wildcard columns.
        win = np.lib.stride_tricks.sliding_window_view(seq, w)[lo:hi]
        mism = (win[:, keep] != want[None, :]).sum(axis=1)
        hit = np.flatnonzero(mism <= max_hamming)
        if hit.size:
            starts.append(hit + lo)
            dists.append(mism[hit] / keep.size)

    if not starts:
        return _empty_hits()
    i0 = np.concatenate(starts)
    return i0, i0 + w - 1, np.concatenate(dists).astype(float)


def match_mindist(seed_sym, seq, table, scale, **_):
    """
    MINDIST against every length-w window, at stride 1 symbol.

    Distance returned is sqrt(sum d^2 / w) - the RMS per-symbol symbol
    distance, in cutline units. The unnormalised MINDIST is recovered as
    sqrt(n) * distance, with n = w * scale; `search` carries it as
    `distance_raw`.

    Being a lower bound, this never rejects a true match: anything MINDIST
    calls far away really is far away. The converse does not hold, which is
    why a MINDIST hit list is a candidate set, not an answer.
    """
    w = len(seed_sym)
    n_win = len(seq) - w + 1
    if n_win <= 0:
        return _empty_hits()

    # cost2[k] maps a target symbol to its squared distance from seed[k].
    a = table.shape[0]
    cost2 = np.zeros((w, a), dtype=float)
    for k in range(w):
        if seed_sym[k] != WILDCARD:
            cost2[k] = table[int(seed_sym[k])] ** 2

    win = np.lib.stride_tricks.sliding_window_view(seq, w)
    acc = np.zeros(n_win, dtype=float)
    for k in range(w):                     # w passes, each O(n_win)
        acc += cost2[k][win[:, k]]

    i0 = np.arange(n_win)
    return i0, i0 + w - 1, np.sqrt(acc / w)


@njit(cache=True)
def _subseq_edit_dp(seed, seq, sub, indel):
    """
    Free-start / free-end subsequence edit distance.

    Row 0 is all zeros, so an alignment may begin anywhere in `seq` at no cost;
    the final row therefore holds, for every end position j, the cost of the
    best alignment of the WHOLE seed ending at j. The start index of that
    alignment is propagated alongside, which is what lets the caller report a
    raw sample span for a match whose length differs from the seed's.

    This free-start formulation is why the edit matcher can absorb time warp:
    the match window is not forced to be `len(seed)` symbols long.
    """
    w = seed.shape[0]
    n = seq.shape[0]

    prev = np.zeros(n + 1, dtype=np.float64)
    prev_s = np.empty(n + 1, dtype=np.int64)
    for j in range(n + 1):
        prev_s[j] = j
    cur = np.empty(n + 1, dtype=np.float64)
    cur_s = np.empty(n + 1, dtype=np.int64)

    for i in range(1, w + 1):
        cur[0] = i * indel
        cur_s[0] = 0
        a = seed[i - 1]
        for j in range(1, n + 1):
            b = seq[j - 1]
            c = 0.0 if a < 0 else sub[a, b]
            best = prev[j - 1] + c
            bs = prev_s[j - 1]
            v = prev[j] + indel                 # delete a seed symbol
            if v < best:
                best = v
                bs = prev_s[j]
            v = cur[j - 1] + indel              # insert a target symbol
            if v < best:
                best = v
                bs = cur_s[j - 1]
            cur[j] = best
            cur_s[j] = bs
        for j in range(n + 1):
            prev[j] = cur[j]
            prev_s[j] = cur_s[j]

    return prev, prev_s


def match_edit(seed_sym, seq, table, scale, indel_cost=None, **_):
    """
    Symbol-weighted edit distance: Levenshtein whose substitution cost is
    d(i, j) from the MINDIST table and whose indel cost is a parameter.

    Distance returned is the alignment cost divided by the seed length, so
    seeds of different lengths and different scales are comparable.

    `indel_cost` defaults to the median non-zero entry of the distance table.
    That ties the price of a stretch to the price of a typical substitution,
    at whatever the learned cutlines happen to be: a fixed constant would mean
    something different for every scale and every cutline mode. Lower it to
    tolerate more warp, raise it to demand tighter length agreement.

    This is the slow matcher: O(w * n) per (scale, offset), jitted with numba.
    Without numba it still runs, roughly 100x slower.
    """
    w = len(seed_sym)
    if len(seq) < 1 or w < 1:
        return _empty_hits()

    if indel_cost is None:
        nz = table[table > 0]
        indel_cost = float(np.median(nz)) if nz.size else 1.0

    cost, starts = _subseq_edit_dp(
        np.ascontiguousarray(seed_sym, dtype=np.int64),
        np.ascontiguousarray(seq, dtype=np.int64),
        np.ascontiguousarray(table, dtype=np.float64),
        float(indel_cost),
    )
    # cost[j] is the best alignment ending at symbol j-1; j=0 is the empty
    # prefix and is not a match.
    end_incl = np.arange(1, len(seq) + 1) - 1
    return starts[1:].astype(np.int64), end_incl, cost[1:] / w


def _empty_hits():
    z = np.empty(0, dtype=np.int64)
    return z, z, np.empty(0, dtype=float)


MATCHERS = {
    "exact": match_exact,
    "mindist": match_mindist,
    "edit": match_edit,
}


# ──────────────────────────────────────────────────────────────────────────────
#  Overlap suppression
# ──────────────────────────────────────────────────────────────────────────────

def suppress_overlaps(starts, ends, dists, min_separation, max_keep=None):
    """
    Greedy non-maximum suppression in raw sample units, best score first.

    Without this, one real motif returns as a smear of dozens of near-identical
    hits at stride-1 offsets and crowds every other occurrence out of the
    top-k. Keeping the best-scoring member of each cluster is what turns a
    score curve into a list of events.

    `max_keep` stops the scan once that many hits have been accepted. Because
    candidates are visited in ascending distance, the first `max_keep` accepted
    are exactly the top `max_keep` after suppression - the early exit changes
    the cost, not the answer. Without it this is O(n_candidates * n_kept), and
    n_candidates is every symbol position in the channel.

    Returns the indices to keep, in the order accepted (best first).
    """
    order = np.argsort(dists, kind="stable")
    centres = 0.5 * (np.asarray(starts, dtype=float) + np.asarray(ends, dtype=float))
    kept, kept_centres = [], []
    for idx in order:
        c = centres[idx]
        # Reject if too close to ANY already-accepted hit.
        if any(abs(c - kc) < min_separation for kc in kept_centres):
            continue
        kept.append(int(idx))
        kept_centres.append(c)
        if max_keep is not None and len(kept) >= max_keep:
            break
    return np.asarray(kept, dtype=np.int64)


# ──────────────────────────────────────────────────────────────────────────────
#  Search
# ──────────────────────────────────────────────────────────────────────────────

def sensible_scales(msax, seed_len_samples, min_symbols=8, max_symbols=128):
    """
    Scales at which a seed of this raw length is a workable number of symbols.

    Below `min_symbols` the string is too short to be distinctive - an 8-symbol
    seed over an alphabet of 8 collides by chance. Above `max_symbols` the edit
    matcher's O(w*n) cost stops being worth it and the encoding is, on this
    signal, mostly repeats anyway.
    """
    out = [s for s in msax.scales
           if min_symbols <= seed_len_samples // s <= max_symbols]
    return out or [min(msax.scales, key=lambda s: abs(seed_len_samples // s - 32))]


def search(msax, seed, matcher="mindist", max_results=50, min_separation=None,
           scales=None, offsets="computed", channel=None, exclude_self=True,
           matcher_kwargs=None, threshold=None):
    """
    Slide `seed` along the encoded channel and return the best matches.

    Parameters
    ----------
    msax : MultiScaleSAX
    seed : Seed
    matcher : {"exact", "mindist", "edit"} or callable
    max_results : int
        Cap on returned rows, after suppression, best first.
    min_separation : int, optional
        Minimum separation between hit centres in RAW SAMPLES. Defaults to one
        seed length, which is the weakest setting that stops a single motif
        returning as a smear.
    scales : list[int], optional
        Scales to search. Defaults to the seed's own scale only. Any other
        scale re-encodes the seed from its raw span (see `Seed.re_encode`), so
        a string seed cannot be searched across scales.
    offsets : "computed" | "zero" | sequence
        Phase offsets per scale. "computed" uses every offset the pyramid
        actually holds.
    exclude_self : bool
        Drop hits overlapping the seed's own span on its own channel. Without
        this the seed always returns itself at distance 0 and displaces a real
        result.
    threshold : float, optional
        Keep only hits with normalised distance <= this. Applied before
        `max_results`.

    Returns
    -------
    pandas.DataFrame with columns RESULT_COLUMNS, sorted by distance.
    Empty (but correctly typed) if nothing matched.
    """
    if isinstance(matcher, str):
        if matcher not in MATCHERS:
            raise ValueError(f"matcher must be one of {list(MATCHERS)} or a callable.")
        matcher_name, matcher_fn = matcher, MATCHERS[matcher]
    else:
        matcher_name, matcher_fn = getattr(matcher, "__name__", "custom"), matcher
    matcher_kwargs = dict(matcher_kwargs or {})

    scales = [int(seed.scale)] if scales is None else [int(s) for s in scales]
    channel = channel if channel is not None else getattr(msax, "channel", seed.channel)

    rows = []
    for s in scales:
        if s not in msax.scale_info:
            raise KeyError(f"Scale {s} is not in this pyramid ({msax.scales}).")

        s_seed = seed.re_encode(msax, s)
        w = len(s_seed)
        if w < 2:
            continue
        table = symbol_distance_table(msax, s)

        if offsets == "computed":
            off_list = msax.offsets_for(s)
        elif offsets == "zero":
            off_list = [0]
        else:
            off_list = [int(o) for o in offsets]

        sep = min_separation if min_separation is not None else w * s

        for off in off_list:
            seq = msax.symbols(s, off)
            if len(seq) < w:
                continue
            i0, i1, dist = matcher_fn(s_seed.symbols, seq, table, s,
                                      **matcher_kwargs)
            if i0.size == 0:
                continue

            head = msax.encodings[(s, int(off))]["n_dropped_head"]
            start_sample = head + i0 * s
            end_sample = head + (i1 + 1) * s

            if threshold is not None:
                keep = dist <= threshold
                if not np.any(keep):
                    continue
                i0, i1, dist = i0[keep], i1[keep], dist[keep]
                start_sample, end_sample = start_sample[keep], end_sample[keep]

            # Trivial-match exclusion, on raw samples so it works across
            # scales and offsets where symbol indices are not comparable.
            if (exclude_self and seed.start_sample is not None
                    and (seed.channel is None or channel is None
                         or seed.channel == channel)):
                overlap = ((start_sample < seed.end_sample)
                           & (end_sample > seed.start_sample))
                if np.all(overlap):
                    continue
                i0, i1, dist = i0[~overlap], i1[~overlap], dist[~overlap]
                start_sample, end_sample = start_sample[~overlap], end_sample[~overlap]

            if dist.size == 0:
                continue

            keep = suppress_overlaps(start_sample, end_sample, dist, sep,
                                     max_keep=max_results)
            n_sym = (i1 - i0 + 1)
            for idx in keep[:max_results]:
                rows.append({
                    "start_sample": int(start_sample[idx]),
                    "end_sample": int(end_sample[idx]),
                    "scale": s,
                    "offset": int(off),
                    "channel": channel,
                    "distance": float(dist[idx]),
                    "matcher": matcher_name,
                    "seed_id": seed.seed_id,
                    # sqrt(n) * normalised recovers the textbook MINDIST.
                    "distance_raw": float(dist[idx] * np.sqrt(n_sym[idx] * s))
                                    if matcher_name == "mindist" else float(dist[idx]),
                    "n_symbols": int(n_sym[idx]),
                })

    if not rows:
        return pd.DataFrame({c: pd.Series(dtype=t) for c, t in [
            ("start_sample", "int64"), ("end_sample", "int64"), ("scale", "int64"),
            ("offset", "int64"), ("channel", "object"), ("distance", "float64"),
            ("matcher", "object"), ("seed_id", "object"),
            ("distance_raw", "float64"), ("n_symbols", "int64"), ("rank", "int64")]})

    df = pd.DataFrame(rows)
    # One more suppression pass across scales and offsets: the same event found
    # at sps=16 and sps=32 is one event, not two.
    sep_all = (min_separation if min_separation is not None
               else int(np.median(df["end_sample"] - df["start_sample"])))
    keep = suppress_overlaps(df["start_sample"].to_numpy(),
                             df["end_sample"].to_numpy(),
                             df["distance"].to_numpy(), sep_all,
                             max_keep=max_results)
    df = df.iloc[keep].head(max_results).reset_index(drop=True)
    df["rank"] = np.arange(len(df))
    return df[RESULT_COLUMNS]


def search_channels(msax_by_channel, seed, **kwargs):
    """
    Run `search` over several channels and concatenate, best first.

    Parameters
    ----------
    msax_by_channel : dict {channel_number: MultiScaleSAX}
        One pyramid per channel. They must share `cutline_mode`, `method` and
        `alphabet_size`, or the symbols mean different things per channel and
        the distances are not comparable - this is checked.
    """
    if not msax_by_channel:
        raise ValueError("msax_by_channel is empty.")
    ref = next(iter(msax_by_channel.values()))
    for ch, m in msax_by_channel.items():
        for attr in ("method", "cutline_mode", "alphabet_size"):
            if getattr(m, attr) != getattr(ref, attr):
                raise ValueError(
                    f"Channel {ch} has {attr}={getattr(m, attr)!r} but the first "
                    f"channel has {getattr(ref, attr)!r}. Cross-channel distances "
                    f"are only meaningful when the encodings agree."
                )

    max_results = kwargs.pop("max_results", 50)
    frames = [search(m, seed, channel=ch, max_results=max_results, **kwargs)
              for ch, m in msax_by_channel.items()]
    frames = [f for f in frames if len(f)]
    if not frames:
        return search(ref, seed, max_results=0, **kwargs)

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("distance", kind="stable").head(max_results).reset_index(drop=True)
    df["rank"] = np.arange(len(df))
    return df[RESULT_COLUMNS]


def benchmark_matchers(msax, seed, scales=None, offsets="zero", repeats=1,
                       matcher_kwargs=None):
    """
    Wall-clock cost of each matcher on the same seed and scales.

    The first `edit` call includes numba's JIT compile time; `repeats > 1`
    reports the warm cost, which is the one that matters for a real search.
    """
    scales = scales or [seed.scale]
    matcher_kwargs = matcher_kwargs or {}
    out = []
    for name in MATCHERS:
        ts = []
        n_hits = 0
        for _ in range(max(1, repeats)):
            t0 = time.perf_counter()
            df = search(msax, seed, matcher=name, scales=scales, offsets=offsets,
                        max_results=50,
                        matcher_kwargs=matcher_kwargs.get(name, {}))
            ts.append(time.perf_counter() - t0)
            n_hits = len(df)
        out.append({"matcher": name, "first_s": ts[0], "best_s": min(ts),
                    "n_hits": n_hits, "scales": list(scales)})
    return pd.DataFrame(out)
