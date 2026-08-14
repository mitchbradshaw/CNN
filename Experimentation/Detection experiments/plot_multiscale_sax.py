"""
plot_multiscale_sax.py
======================
Diagnostic plots for a `multiscale_sax.MultiScaleSAX` pyramid.

Every plotting function takes an already-built MultiScaleSAX object and
returns a `matplotlib.figure.Figure`.  Nothing is saved, and `plt.show()` is
not called — that is a deliberate deviation from the older plot helpers in
`Working/` (e.g. `rupture_detect.plot_change_points`), which show-then-return.
Returning a bare Figure keeps these callable from a headless run, from the UI,
and from a loop that builds all five before displaying any.

To save, call `save_figure()` explicitly.  It routes through
`Working.artifacts.save_plot`, so output lands at
``Plots/Detection/multiscale_sax/<recording>_CH<nn>_det_multiscale_sax_<slug>_<hash8>.png``
and traces back to the exact configuration that produced it.

The five plots, and the question each answers
----------------------------------------------
1. `plot_symbol_pyramid`      — at which scale does this structure live?
2. `plot_occupancy_by_scale`  — which scales carry information at all?
3. `plot_transition_matrix`   — is this scale over- or under-sampled?
4. `plot_scale_persistence`   — is the structure genuinely multiscale, or noise?
5. `plot_offset_sensitivity`  — must downstream search sweep phase offsets?

Each plot has a matching pure `*_diagnostics()` function returning the numbers
without building a figure, so the runner can print a table and a test can
assert on it.
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

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap

from Working.artifacts import save_plot
from Working.recipes import make_recipe, short_hash


# Perceptually uniform and monotone in lightness, so a higher symbol index
# reads as a lighter colour without inventing a hue ordering that isn't there.
# cividis is also the safest of the uniform maps under colour-vision deficiency.
DEFAULT_CMAP = "cividis"


# ──────────────────────────────────────────────────────────────────────────────
#  Information-theoretic helpers
# ──────────────────────────────────────────────────────────────────────────────

def entropy_bits(hist) -> float:
    """Shannon entropy of a histogram (counts or probabilities), in bits."""
    h = np.asarray(hist, dtype=float)
    h = h[h > 0]
    if h.size == 0:
        return 0.0
    p = h / h.sum()
    return float(-(p * np.log2(p)).sum())


def normalised_mutual_information(a, b) -> float:
    """
    NMI(a, b) = 2*I(a;b) / (H(a) + H(b)), in [0, 1].

    Matches sklearn's `normalized_mutual_info_score(..., average_method="arithmetic")`;
    implemented here to keep this module's dependencies to numpy + matplotlib,
    consistent with the rest of `Working/Detection/sax` (which ships its own
    Mean-Shift and KDE rather than importing sklearn).

    Returns 0.0 when either sequence is constant — no shared information is
    measurable, which is the honest answer rather than a divide-by-zero.
    """
    a = np.asarray(a).ravel()
    b = np.asarray(b).ravel()
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if n == 0:
        return 0.0

    ua, ia = np.unique(a, return_inverse=True)
    ub, ib = np.unique(b, return_inverse=True)
    if len(ua) < 2 or len(ub) < 2:
        return 0.0

    joint = np.zeros((len(ua), len(ub)), dtype=float)
    np.add.at(joint, (ia, ib), 1.0)
    joint /= n

    pa = joint.sum(axis=1)
    pb = joint.sum(axis=0)
    Ha, Hb = entropy_bits(pa), entropy_bits(pb)
    if Ha <= 0 or Hb <= 0:
        return 0.0

    nz = joint > 0
    mi = float((joint[nz] * np.log2(joint[nz] / np.outer(pa, pb)[nz])).sum())
    return float(2.0 * mi / (Ha + Hb))


# ──────────────────────────────────────────────────────────────────────────────
#  Span / alignment helpers
# ──────────────────────────────────────────────────────────────────────────────

def _hours(samples, fs):
    return np.asarray(samples, dtype=float) / fs / 3600.0


def _span_slice(msax, scale, offset, start_sample, end_sample):
    """
    Symbols covering [start_sample, end_sample) at one (scale, offset), plus
    the sample edges of those symbols.

    Uses `msax.samples_to_symbol_span` rather than re-deriving the arithmetic —
    that method is the module's single sanctioned conversion, and duplicating
    it here is exactly how the two would silently drift apart.

    Returns (i0, i1, symbols, sample_edges) where `sample_edges` has one more
    entry than `symbols`, or None if the span misses this scale entirely.
    """
    e = msax.encodings[(int(scale), int(offset))]
    lo = e["n_dropped_head"]
    hi = lo + e["n_symbols"] * int(scale)
    a, b = max(int(start_sample), lo), min(int(end_sample), hi)
    if b <= a:
        return None
    i0, i1 = msax.samples_to_symbol_span(scale, offset, a, b)
    sym = msax.symbols(scale, offset)[i0:i1 + 1]
    edges = lo + np.arange(i0, i1 + 2) * int(scale)
    return i0, i1, sym, edges


def _discrete_cmap(name, n_levels):
    """A ListedColormap of exactly `n_levels` colours plus a matching norm, so
    symbol indices get crisp blocks and an integer-ticked colorbar."""
    base = plt.get_cmap(name)
    cmap = ListedColormap(base(np.linspace(0.08, 0.95, max(n_levels, 2))))
    norm = BoundaryNorm(np.arange(-0.5, n_levels + 0.5), cmap.N)
    return cmap, norm


# ──────────────────────────────────────────────────────────────────────────────
#  1. Symbol pyramid
# ──────────────────────────────────────────────────────────────────────────────

def plot_symbol_pyramid(msax, start_sample, end_sample, scales=None, offset=0,
                        cmap=DEFAULT_CMAP, max_cells=40000, figsize=None):
    """
    Raw signal above a stack of colour-coded symbol strips, one per scale, all
    on a shared time axis in hours.

    This is the plot that tells you which scale a piece of structure lives at:
    an event that shows as a colour excursion at sps=16 but is invisible at
    sps=1024 is a fast event, and vice versa.  A band of scales that all change
    colour together marks genuinely multiscale structure — cross-check that
    reading against `plot_scale_persistence`.

    Parameters
    ----------
    msax : MultiScaleSAX
    start_sample, end_sample : int
        Half-open sample range, matching the module's index-mapping contract.
    scales : list[int], optional
        Subset of `msax.scales` to draw. Defaults to all of them.
    offset : int
        Which phase offset to draw. Must have been computed.
    cmap : str
        Perceptually uniform, monotone-lightness colormap. Symbol value maps
        to lightness, so the strips stay readable in greyscale.
    max_cells : int
        Fine scales over a long span produce more rectangles than are useful
        or fast to draw. Scales exceeding this are dropped and named in the
        subtitle — dropped visibly, never silently.

    Returns
    -------
    matplotlib.figure.Figure

    Notes
    -----
    When the realised alphabet differs between scales (cSAX discovers its
    alphabet, so it can), a single colour scale spanning the largest alphabet
    is used and the subtitle says so — colours are then only loosely
    comparable between rows. Under `cutline_mode="shared_renormalised"` with
    pSAX the alphabets match and colours are directly comparable.
    """
    scales = list(msax.scales) if scales is None else [int(s) for s in scales]
    for s in scales:
        if s not in msax.scale_info:
            raise KeyError(f"Scale {s} is not in this pyramid ({msax.scales}).")

    start_sample, end_sample = int(start_sample), int(end_sample)
    if end_sample <= start_sample:
        raise ValueError(f"end_sample ({end_sample}) must exceed start_sample ({start_sample}).")

    drawn, dropped = [], []
    for s in sorted(scales):
        got = _span_slice(msax, s, offset, start_sample, end_sample)
        if got is None:
            dropped.append((s, "outside span"))
            continue
        if len(got[2]) > max_cells:
            dropped.append((s, f"{len(got[2])} cells"))
            continue
        drawn.append((s, got))

    if not drawn:
        raise ValueError(
            f"No scale is drawable over [{start_sample}, {end_sample}). "
            f"Either the span is too short for the coarse scales or too long "
            f"for the fine ones (max_cells={max_cells})."
        )

    alphabets = [msax.scale_info[s]["alphabet_size"] for s, _ in drawn]
    n_levels = max(alphabets)
    cm, norm = _discrete_cmap(cmap, n_levels)

    n_rows = len(drawn)
    figsize = figsize or (13, 2.6 + 0.42 * n_rows)
    fig, (ax_sig, ax_pyr) = plt.subplots(
        2, 1, figsize=figsize, sharex=True,
        gridspec_kw={"height_ratios": [2.2, max(2.0, 0.42 * n_rows)], "hspace": 0.08},
    )

    # ── Raw signal ────────────────────────────────────────────────────────────
    seg = msax._x[start_sample:end_sample]
    ax_sig.plot(_hours(np.arange(start_sample, end_sample), msax.fs), seg,
                lw=0.6, color="0.15")
    ax_sig.set_ylabel("signal\n(z-scored)" if msax.normalize else "signal")
    ax_sig.grid(alpha=0.25, lw=0.5)
    ax_sig.margins(x=0)

    # ── Symbol strips ─────────────────────────────────────────────────────────
    for row, (s, (_, _, sym, edges)) in enumerate(drawn):
        y0, y1 = row, row + 0.86
        mesh = ax_pyr.pcolormesh(_hours(edges, msax.fs), [y0, y1],
                                 sym[None, :].astype(float),
                                 cmap=cm, norm=norm, shading="flat")

    info = msax.scale_info
    labels = []
    for s, _ in drawn:
        mins = info[s]["minutes"]
        span = f"{mins * 60:.0f} s" if mins < 1 else f"{mins:.1f} min"
        lab = f"{s}  ({span})"
        if len(set(alphabets)) > 1:
            lab += f"  a={info[s]['alphabet_size']}"
        labels.append(lab)

    ax_pyr.set_yticks([r + 0.43 for r in range(n_rows)])
    ax_pyr.set_yticklabels(labels, fontsize=8)
    ax_pyr.set_ylim(-0.1, n_rows)
    ax_pyr.invert_yaxis()          # finest scale on top, nearest the signal
    ax_pyr.set_ylabel("samples per symbol")
    ax_pyr.set_xlabel("time (hours)")
    ax_pyr.margins(x=0)
    # Clip to the requested view. Coarse symbols legitimately overhang both
    # ends (a 68-min symbol rarely starts on the view boundary); without this
    # the rows end at different x and read as a rendering fault rather than as
    # the boundary effect it is.
    ax_pyr.set_xlim(_hours(start_sample, msax.fs), _hours(end_sample, msax.fs))

    cbar = fig.colorbar(mesh, ax=[ax_sig, ax_pyr], pad=0.012, fraction=0.028,
                        ticks=np.arange(n_levels))
    cbar.set_label("symbol (low → high)", fontsize=9)
    cbar.ax.tick_params(labelsize=8)

    hrs = (end_sample - start_sample) / msax.fs / 3600.0
    sub = (f"{msax.method} | {msax.cutline_mode} | offset {offset} | "
           f"{hrs:.2f} h from sample {start_sample}")
    if dropped:
        sub += "  |  not drawn: " + ", ".join(f"sps={s} ({why})" for s, why in dropped)
    if len(set(alphabets)) > 1:
        sub += "  |  alphabets differ between scales — colours only loosely comparable"
    ax_sig.set_title("Multiscale symbol pyramid\n" + sub, fontsize=10, loc="left")

    return fig


# ──────────────────────────────────────────────────────────────────────────────
#  2. Occupancy by scale
# ──────────────────────────────────────────────────────────────────────────────

def occupancy_diagnostics(msax, offset=0):
    """
    Per-scale symbol occupancy and entropy.

    Returns
    -------
    list[dict] with keys: scale, minutes, alphabet_size, n_symbols, histogram,
    entropy_bits, ceiling_bits, entropy_frac, max_min_ratio, n_symbols_used.
    """
    rows = []
    for s in msax.scales:
        info = msax.scale_info[s]
        off = offset if (s, offset) in msax.encodings else info["offsets"][0]
        h = msax.symbol_histogram(s, off)
        H = entropy_bits(h)
        ceiling = float(np.log2(info["alphabet_size"]))
        rows.append({
            "scale": s,
            "minutes": info["minutes"],
            "alphabet_size": info["alphabet_size"],
            "n_symbols": msax.n_symbols(s, off),
            "histogram": h,
            "entropy_bits": H,
            "ceiling_bits": ceiling,
            "entropy_frac": (H / ceiling) if ceiling > 0 else 0.0,
            "max_min_ratio": msax.occupancy_ratio(s, off),
            "n_symbols_used": int(np.count_nonzero(h)),
        })
    return rows


def plot_occupancy_by_scale(msax, offset=0, cmap="magma", collapse_frac=0.5,
                            figsize=(12, 6.4)):
    """
    Left: symbol-occupancy heatmap (scale on y, symbol on x).
    Right: realised entropy in bits per scale against the log2(alphabet_size)
    ceiling.

    How to read it, and what to do about it
    ---------------------------------------
    The ceiling is the entropy a perfectly-balanced alphabet would reach.
    A scale sitting near the ceiling is using its whole alphabet and is
    carrying information.

    **A scale whose entropy has collapsed toward 0 is not carrying information
    and should be dropped from later stages.** Its symbol sequence is very
    nearly a constant, so every MINDIST against it is ~0 and it will match
    everything indiscriminately — it does not merely add nothing, it actively
    pollutes a cross-scale search with spurious matches while costing full
    compute. `collapse_frac` marks the threshold on the plot; scales below it
    are flagged in the axis labels.

    Note this is a necessary, not sufficient, condition: a scale can show high
    entropy and still be encoding noise. `plot_transition_matrix` and
    `plot_scale_persistence` are what separate those two cases.
    """
    rows = occupancy_diagnostics(msax, offset)
    n_levels = max(r["alphabet_size"] for r in rows)

    # Pad to the widest alphabet so rows line up when cSAX realises different
    # alphabet sizes at different scales.
    grid = np.full((len(rows), n_levels), np.nan)
    for k, r in enumerate(rows):
        grid[k, :len(r["histogram"])] = r["histogram"]

    fig, (ax_h, ax_e) = plt.subplots(
        1, 2, figsize=figsize, sharey=True,
        gridspec_kw={"width_ratios": [1.55, 1.0]},
        layout="constrained",          # tight_layout can't place the colorbars
    )

    im = ax_h.imshow(grid, aspect="auto", cmap=cmap, origin="upper",
                     extent=(-0.5, n_levels - 0.5, len(rows) - 0.5, -0.5))
    ax_h.set_xticks(np.arange(n_levels))
    ax_h.set_xlabel("symbol")
    ax_h.set_ylabel("samples per symbol")

    labels = []
    for r in rows:
        mins = r["minutes"]
        span = f"{mins * 60:.0f}s" if mins < 1 else f"{mins:.0f}m"
        flag = "  ⚠" if r["entropy_frac"] < collapse_frac else ""
        labels.append(f"{r['scale']} ({span}){flag}")
    ax_h.set_yticks(np.arange(len(rows)))
    ax_h.set_yticklabels(labels, fontsize=8)
    # Horizontal, under its own panel: a vertical colorbar here would sit
    # between the two panels and collide with the entropy axis.
    fig.colorbar(im, ax=ax_h, orientation="horizontal", location="bottom",
                 pad=0.02, fraction=0.05, label="fraction of symbols")

    y = np.arange(len(rows))
    ent = [r["entropy_bits"] for r in rows]
    ceil = [r["ceiling_bits"] for r in rows]
    ax_e.barh(y, ent, height=0.62, color="#3b6ea5", label="realised entropy")
    ax_e.plot(ceil, y, "o--", color="0.25", ms=4, lw=1.2,
              label="ceiling = log2(alphabet)")
    # Percentage-of-ceiling inside the bar: outside the bar it collides with
    # the ceiling marker, which sits only a few percent further right.
    for k, r in enumerate(rows):
        ax_e.text(r["entropy_bits"] - 0.05, k, f"{r['entropy_frac'] * 100:.0f}%",
                  va="center", ha="right", fontsize=7.5, color="white")

    thresh = [c * collapse_frac for c in ceil]
    ax_e.plot(thresh, y, ":", color="#b3402f", lw=1.2,
              label=f"collapse threshold ({collapse_frac:.0%} of ceiling)")
    ax_e.set_xlabel("entropy (bits)")
    ax_e.set_xlim(0, max(ceil) * 1.10)
    ax_e.grid(axis="x", alpha=0.25, lw=0.5)
    ax_e.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.06),
                framealpha=0.9)

    collapsed = [r["scale"] for r in rows if r["entropy_frac"] < collapse_frac]
    sub = f"{msax.method} | {msax.cutline_mode} | alphabet {msax.alphabet_size}"
    sub += ("  |  collapsed, drop from later stages: "
            + ", ".join(f"sps={s}" for s in collapsed)) if collapsed else \
           "  |  every scale above the collapse threshold"
    fig.suptitle("Symbol occupancy and information content by scale\n" + sub,
                 fontsize=10, x=0.01, ha="left")
    return fig


# ──────────────────────────────────────────────────────────────────────────────
#  3. Transition matrix
# ──────────────────────────────────────────────────────────────────────────────

def transition_diagnostics(msax, scale, offset=0):
    """
    Consecutive-symbol transition statistics for one scale.

    Returns
    -------
    dict with: scale, minutes, matrix (row-stochastic), self_transition,
    cond_entropy_bits, marginal_entropy_bits, redundancy, nmi_lag1,
    verdict, suggestion.

    `redundancy = 1 - H(next|cur)/H(next)` is the fraction of the next
    symbol's uncertainty that the current symbol removes. It is 0 when
    consecutive symbols are independent and 1 when the sequence is
    deterministic, which is exactly the over/under-sampling axis.
    """
    info = msax.scale_info[int(scale)]
    if (int(scale), int(offset)) not in msax.encodings:
        offset = info["offsets"][0]
    sym = msax.symbols(scale, offset)
    a = info["alphabet_size"]

    counts = np.zeros((a, a), dtype=float)
    if len(sym) > 1:
        np.add.at(counts, (sym[:-1], sym[1:]), 1.0)

    row_sums = counts.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        matrix = np.where(row_sums > 0, counts / np.maximum(row_sums, 1), np.nan)

    total = counts.sum()
    self_tr = float(np.trace(counts) / total) if total > 0 else 0.0

    # H(next | cur) and H(next) from the same pair counts, so the redundancy
    # is exact rather than mixing two different sample sets.
    H_next = entropy_bits(counts.sum(axis=0))
    if total > 0:
        joint = counts / total
        p_cur = joint.sum(axis=1)
        H_cond = 0.0
        for i in range(a):
            if p_cur[i] > 0:
                H_cond += p_cur[i] * entropy_bits(counts[i])
    else:
        H_cond = 0.0
    redundancy = float(1.0 - H_cond / H_next) if H_next > 0 else 0.0

    if self_tr > 0.60:
        verdict = "oversampled"
        suggestion = (f"symbols repeat {self_tr:.0%} of the time - the scale is "
                      f"finer than the structure it is encoding; go COARSER "
                      f"(larger samples-per-symbol / smaller dim_ratio)")
    elif redundancy < 0.05:
        verdict = "undersampled"
        suggestion = (f"consecutive symbols are near-independent "
                      f"(redundancy {redundancy:.3f}) - the encoding at this "
                      f"scale is essentially noise; go FINER (smaller "
                      f"samples-per-symbol / larger dim_ratio)")
    else:
        verdict = "well matched"
        suggestion = (f"self-transition {self_tr:.0%}, redundancy "
                      f"{redundancy:.2f} - structured but not saturated; "
                      f"keep this scale")

    return {
        "scale": int(scale), "offset": int(offset), "minutes": info["minutes"],
        "matrix": matrix, "self_transition": self_tr,
        "cond_entropy_bits": float(H_cond), "marginal_entropy_bits": float(H_next),
        "redundancy": redundancy,
        "nmi_lag1": normalised_mutual_information(sym[:-1], sym[1:]) if len(sym) > 1 else 0.0,
        "verdict": verdict, "suggestion": suggestion,
    }


def plot_transition_matrix(msax, scale, offset=0, cmap="rocket_r", verbose=True,
                           figsize=(6.4, 5.6)):
    """
    Symbol-to-symbol transition probability heatmap, P(next | current).

    Reading the shape
    -----------------
    *Near-diagonal* (most mass on i→i): the scale is OVERSAMPLED. Consecutive
    segments are so similar that the encoding mostly repeats itself, spending
    symbols to say nothing. Move to a coarser samples-per-symbol.

    *Near-uniform* (every row flat): the scale is UNDERSAMPLED. Consecutive
    symbols carry no information about each other, so the encoding is noise
    rather than structure. Move to a finer samples-per-symbol.

    The useful middle is a banded matrix — mass concentrated near, but not on,
    the diagonal, meaning the signal moves smoothly through the alphabet.

    Prints the numeric diagnosis and the suggested direction when
    `verbose=True`; `transition_diagnostics()` returns the same numbers without
    plotting.
    """
    d = transition_diagnostics(msax, scale, offset)
    m = d["matrix"]
    a = m.shape[0]

    try:
        cm = plt.get_cmap(cmap)
    except ValueError:
        cm = plt.get_cmap("magma_r")     # rocket_r ships with seaborn, not mpl

    fig, ax = plt.subplots(figsize=figsize)
    im = ax.imshow(m, cmap=cm, vmin=0, vmax=np.nanmax(m) if np.isfinite(np.nanmax(m)) else 1,
                   origin="upper")
    ax.plot([-0.5, a - 0.5], [-0.5, a - 0.5], color="#2f7fbf", lw=1.0, ls="--",
            alpha=0.8, label="diagonal (self-transition)")

    if a <= 12:
        for i in range(a):
            for j in range(a):
                if np.isfinite(m[i, j]) and m[i, j] >= 0.005:
                    ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center",
                            fontsize=6.5,
                            color="white" if m[i, j] > 0.55 * np.nanmax(m) else "0.2")

    ax.set_xticks(np.arange(a))
    ax.set_yticks(np.arange(a))
    ax.set_xlabel("next symbol")
    ax.set_ylabel("current symbol")
    fig.colorbar(im, ax=ax, pad=0.02, fraction=0.045, label="P(next | current)")
    ax.legend(fontsize=7.5, loc="upper right", framealpha=0.85)

    mins = d["minutes"]
    span = f"{mins * 60:.0f} s" if mins < 1 else f"{mins:.1f} min"
    ax.set_title(
        f"Transition matrix — sps={d['scale']} ({span}), offset {d['offset']}\n"
        f"self-transition {d['self_transition']:.1%} | redundancy "
        f"{d['redundancy']:.3f} | verdict: {d['verdict'].upper()}",
        fontsize=10, loc="left",
    )
    fig.tight_layout()

    if verbose:
        print(f"  [transition] sps={d['scale']:>5} ({span:>8}): "
              f"self={d['self_transition']:.3f} redundancy={d['redundancy']:.3f} "
              f"H(next)={d['marginal_entropy_bits']:.2f}b "
              f"H(next|cur)={d['cond_entropy_bits']:.2f}b -> {d['verdict']}")
        print(f"               {d['suggestion']}")

    return fig


# ──────────────────────────────────────────────────────────────────────────────
#  4. Scale persistence
# ──────────────────────────────────────────────────────────────────────────────

def persistence_diagnostics(msax, start_sample, end_sample, offset=0,
                            n_shuffles=8, random_state=0):
    """
    How well the coarse encoding predicts the fine one, scale by scale.

    For each adjacent pair (s, 2s) the coarse symbol sequence is expanded so
    that each coarse symbol is paired with the two fine symbols nested inside
    it — exact under the dyadic ladder, which is why the ladder is enforced —
    and NMI is computed over that pairing.

    A shuffled baseline is computed by permuting the fine sequence, which
    destroys the temporal correspondence while preserving both marginals. That
    baseline is the finite-sample NMI floor: with a symbols and N pairs, NMI of
    independent sequences is positive, not zero, and at coarse scales N gets
    small enough that the bias is not negligible. Elevation ABOVE the baseline
    is the only part of the curve that means anything.

    Returns list[dict]: fine_scale, coarse_scale, minutes, n_pairs, nmi,
    baseline, baseline_std, excess.
    """
    rng = np.random.default_rng(random_state)
    rows = []
    for fine, coarse in zip(msax.scales[:-1], msax.scales[1:]):
        if coarse != 2 * fine:
            continue                       # non-adjacent ladder rung; skip
        gf = _span_slice(msax, fine, offset, start_sample, end_sample)
        gc = _span_slice(msax, coarse, offset, start_sample, end_sample)
        if gf is None or gc is None:
            continue

        i0f, _, sym_f, _ = gf
        i0c, _, sym_c, _ = gc

        # Coarse symbol j covers fine symbols [2j, 2j+2) at the same offset.
        # Re-anchor the fine slice onto the coarse grid rather than assuming
        # the two slices already start on the same boundary.
        start_f = 2 * i0c - i0f
        if start_f < 0:
            sym_c = sym_c[1:]
            i0c += 1
            start_f = 2 * i0c - i0f
        n_pairs = min(len(sym_c), (len(sym_f) - start_f) // 2)
        if n_pairs < 8:
            continue

        fine_paired = sym_f[start_f:start_f + 2 * n_pairs]
        coarse_paired = np.repeat(sym_c[:n_pairs], 2)

        nmi = normalised_mutual_information(fine_paired, coarse_paired)
        base = [normalised_mutual_information(rng.permutation(fine_paired), coarse_paired)
                for _ in range(n_shuffles)]
        rows.append({
            "fine_scale": fine, "coarse_scale": coarse,
            "minutes": msax.scale_info[fine]["minutes"],
            "n_pairs": int(2 * n_pairs),
            "nmi": nmi,
            "baseline": float(np.mean(base)),
            "baseline_std": float(np.std(base)),
            "excess": float(nmi - np.mean(base)),
        })
    return rows


def plot_scale_persistence(msax, start_sample, end_sample, offset=0,
                           n_shuffles=8, random_state=0, figsize=(9.5, 5.2)):
    """
    NMI between the encoding at scale s and at scale 2s, as a function of s.

    Genuinely multiscale structure — an event with a coherent shape spanning
    several octaves — shows elevated NMI across a BAND of scales: knowing the
    coarse symbol tells you a lot about the fine ones over that whole band.
    Noise does not: its fine and coarse encodings are near-independent, so the
    curve sits on the shuffled baseline.

    Two failure modes the baseline exists to catch: at coarse scales the pair
    count falls to a few hundred, where NMI has a substantial positive
    finite-sample bias, and a scale that has collapsed to one symbol scores
    NMI 0 for lack of variance rather than lack of structure. Read the
    `excess` (NMI minus baseline), never the raw NMI.
    """
    rows = persistence_diagnostics(msax, start_sample, end_sample, offset,
                                   n_shuffles, random_state)
    if not rows:
        raise ValueError(
            f"No adjacent scale pair is measurable over "
            f"[{start_sample}, {end_sample}) — the span is too short. "
            f"Need at least 8 coarse symbols at the coarsest pair."
        )

    x = np.array([r["fine_scale"] for r in rows], dtype=float)
    nmi = np.array([r["nmi"] for r in rows])
    base = np.array([r["baseline"] for r in rows])
    bstd = np.array([r["baseline_std"] for r in rows])

    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(x, nmi, "o-", color="#2f6f4f", lw=1.8, ms=6, label="NMI(scale s, scale 2s)")
    ax.plot(x, base, "s--", color="#9a9a9a", lw=1.2, ms=4, label="shuffled baseline")
    ax.fill_between(x, base - 2 * bstd, base + 2 * bstd, color="#9a9a9a", alpha=0.22,
                    label="baseline ±2σ")
    ax.fill_between(x, base, nmi, where=(nmi > base), color="#2f6f4f", alpha=0.14,
                    label="excess (the part that means something)")

    ax.set_xscale("log", base=2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(v)}" for v in x])
    ax.set_xlabel("fine scale s, samples per symbol  (paired with 2s)")
    ax.set_ylabel("normalised mutual information")
    ax.set_ylim(0, max(1.0, float(nmi.max()) * 1.12))
    ax.grid(alpha=0.25, lw=0.5)
    ax.legend(fontsize=8, loc="best", framealpha=0.9)

    for r, xi, yi in zip(rows, x, nmi):
        ax.annotate(f"n={r['n_pairs']}", (xi, yi), textcoords="offset points",
                    xytext=(0, 9), ha="center", fontsize=6.5, color="0.4")

    peak = max(rows, key=lambda r: r["excess"])
    band = [r["fine_scale"] for r in rows if r["excess"] > 0.5 * peak["excess"]]
    ax.set_title(
        f"Cross-scale persistence — {msax.method} | {msax.cutline_mode}\n"
        f"peak excess {peak['excess']:.3f} at sps={peak['fine_scale']}"
        f"→{peak['coarse_scale']} | elevated band: sps "
        f"{min(band)}–{max(band)}",
        fontsize=10, loc="left",
    )
    fig.tight_layout()
    return fig


# ──────────────────────────────────────────────────────────────────────────────
#  5. Offset sensitivity
# ──────────────────────────────────────────────────────────────────────────────

def offset_diagnostics(msax, scale):
    """
    Pairwise symbol-disagreement rate between the phase offsets of one scale.

    Two offsets are compared index-by-index: symbol i at offset o1 versus
    symbol i at offset o2. That is the question a downstream search actually
    asks — "if my segmentation grid is out of phase, do I get a different
    symbol?" — rather than a comparison of two differently-aligned windows.

    Returns dict: scale, offsets, matrix (n_off x n_off), mean_disagreement
    (off-diagonal), max_disagreement, adjacent_disagreement, verdict, suggestion.
    """
    s = int(scale)
    offs = msax.offsets_for(s)
    if len(offs) < 2:
        raise ValueError(
            f"Scale {s} has only offset(s) {offs}. Rebuild with offsets='all' "
            f"to measure offset sensitivity."
        )

    seqs = [msax.symbols(s, o) for o in offs]
    n = min(len(q) for q in seqs)
    n_off = len(offs)
    m = np.zeros((n_off, n_off))
    for i in range(n_off):
        for j in range(i + 1, n_off):
            d = float(np.mean(seqs[i][:n] != seqs[j][:n]))
            m[i, j] = m[j, i] = d

    off_diag = m[~np.eye(n_off, dtype=bool)]
    adjacent = float(np.mean([m[k, k + 1] for k in range(n_off - 1)]))
    mean_d = float(off_diag.mean())
    max_d = float(off_diag.max())

    # The verdict keys off the WORST pair, not the mean. A search that fixes
    # offset 0 loses recall on motifs sitting at whichever phase disagrees most
    # with it, so the worst pair is the decision-relevant number; the mean just
    # says how typical that is.
    if max_d > 0.35:
        verdict = "sweep required"
        suggestion = (f"up to {max_d:.1%} of symbols change with phase "
                      f"(mean {mean_d:.1%}) - downstream search MUST sweep "
                      f"offsets here, or it will miss the same motif at a "
                      f"different phase")
    elif max_d > 0.15:
        verdict = "sweep advisable"
        suggestion = (f"worst pair disagrees {max_d:.1%} (mean {mean_d:.1%}) - "
                      f"a partial sweep of a few evenly spaced offsets buys "
                      f"most of the recall for a fraction of the cost")
    else:
        verdict = "offsets='zero' is safe"
        suggestion = (f"worst pair disagrees only {max_d:.1%} (mean "
                      f"{mean_d:.1%}) - effectively phase-invariant here; "
                      f"offsets='zero' costs {len(offs)}x less and loses "
                      f"almost nothing")

    return {
        "scale": s, "offsets": offs, "matrix": m,
        "mean_disagreement": mean_d, "max_disagreement": max_d,
        "adjacent_disagreement": adjacent,
        "verdict": verdict, "suggestion": suggestion,
    }


def plot_offset_sensitivity(msax, scale, cmap="viridis", verbose=True,
                            figsize=(6.6, 5.6)):
    """
    Heatmap of pairwise symbol disagreement between phase offsets at one scale.

    A hot matrix means the symbol sequence depends strongly on where the PAA
    grid happens to start, so any downstream motif search has to sweep offsets
    to find the same event at a different phase. A cold matrix means the
    encoding is effectively phase-invariant at this scale, and `offsets="zero"`
    is safe — which makes everything downstream `len(offsets)` times cheaper.

    Expect this to be hottest at fine scales (where a half-segment shift moves
    a large fraction of each segment's content) and to cool as the scale
    coarsens on a drift-dominated signal.
    """
    d = offset_diagnostics(msax, scale)
    m, offs = d["matrix"], d["offsets"]

    fig, ax = plt.subplots(figsize=figsize)
    im = ax.imshow(m, cmap=cmap, vmin=0, vmax=max(d["max_disagreement"], 1e-9),
                   origin="upper")
    if len(offs) <= 16:
        for i in range(len(offs)):
            for j in range(len(offs)):
                if i != j:
                    ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center",
                            fontsize=6,
                            color="white" if m[i, j] < 0.6 * d["max_disagreement"] else "0.1")

    ax.set_xticks(np.arange(len(offs)))
    ax.set_yticks(np.arange(len(offs)))
    ax.set_xticklabels(offs, fontsize=8)
    ax.set_yticklabels(offs, fontsize=8)
    ax.set_xlabel("phase offset (samples)")
    ax.set_ylabel("phase offset (samples)")
    fig.colorbar(im, ax=ax, pad=0.02, fraction=0.045,
                 label="fraction of symbols that differ")

    info = msax.scale_info[int(scale)]
    mins = info["minutes"]
    span = f"{mins * 60:.0f} s" if mins < 1 else f"{mins:.1f} min"
    ax.set_title(
        f"Offset sensitivity — sps={d['scale']} ({span}), {len(offs)} offsets\n"
        f"mean {d['mean_disagreement']:.1%} | adjacent {d['adjacent_disagreement']:.1%} "
        f"| max {d['max_disagreement']:.1%} → {d['verdict'].upper()}",
        fontsize=10, loc="left",
    )
    fig.tight_layout()

    if verbose:
        print(f"  [offsets] sps={d['scale']:>5} ({span:>8}): mean={d['mean_disagreement']:.3f} "
              f"adjacent={d['adjacent_disagreement']:.3f} max={d['max_disagreement']:.3f} "
              f"-> {d['verdict']}")
        print(f"            {d['suggestion']}")

    return fig


# ──────────────────────────────────────────────────────────────────────────────
#  Explicit saving (never automatic)
# ──────────────────────────────────────────────────────────────────────────────

def save_figure(fig, msax, source_file, channel, plot_name,
                recording_id=0, span=None, root="Plots"):
    """
    Save a figure under the repo's artifact naming convention.

    Follows `Working.artifacts` exactly: the figure is described by a recipe,
    the recipe's `short_hash` goes in the filename, and the file lands at
    ``Plots/Detection/multiscale_sax/...``. Two different pyramid
    configurations therefore cannot overwrite each other even if their
    human-readable slugs collide.

    Call this only when a save was explicitly asked for — nothing in this
    module calls it.

    Parameters
    ----------
    fig : matplotlib Figure
    msax : MultiScaleSAX
        Its configuration becomes the recipe params, so the hash covers it.
    source_file : str
        Bare recording filename, e.g. "M2_concat_fs1_CH2.npy".
    channel : int
    plot_name : str
        e.g. "pyramid", "occupancy".
    recording_id : int
        The `recordings` table id if known. 0 is a valid placeholder for
        exploratory work — it just means the hash is not tied to a DB row.
    span : (int, int), optional

    Returns
    -------
    str — the path written.
    """
    params = {
        "plot": plot_name,
        "method": msax.method,
        "cutline_mode": msax.cutline_mode,
        "alphabet_size": int(msax.alphabet_size),
        "scales": [int(s) for s in msax.scales],
        "n_encodings": len(msax.encodings),
        "normalize": bool(msax.normalize),
    }
    recipe = make_recipe(
        recording_id,
        [{"stage": "detection", "algorithm": "multiscale_sax", "params": params}],
        span=span,
    )
    return save_plot(fig, source_file, channel, "detection", "multiscale_sax",
                     params, short_hash(recipe), root=root)
