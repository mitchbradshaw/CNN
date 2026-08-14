"""
_sax_common.py
================
Shared segmentation-parameter resolution and diagnostics for the cSAX/pSAX
adapters (Part 2, 2026-08) — used by BOTH `detection_sax_csax.py` and
`detection_sax_psax.py` so the two can never resolve the same control to a
different `samples_per_symbol` from each other, and so the run panel's
live, pre-run `derive()` readout can never silently disagree with what a
real run actually does (both call `segment_plan` with the same inputs).

Not an adapter itself — no `AdapterSpec`/`register()` here. Plain numpy
only, importable headlessly like every other `Adapters/`/`Working/` module.

Segmentation controls
----------------------
A researcher thinks in "how much time does one letter cover", not in a
PAA reduction ratio — `dim_ratio=0.1` on a 62,759-sample span silently
produces 6,275 symbols. `segment_mode` picks which of four equivalent
controls is authoritative; `segment_plan` resolves whichever one to a
concrete `samples_per_symbol` / segment count, in ONE place.

Round-trip note
-----------------
`csax()`/`psax()` compute `data_nseg = floor(dim_ratio * data_len)` and
then trim `data_len` down to an exact multiple of `data_nseg`. Passing a
`dim_ratio` derived from `(n_symbols + 0.5) / data_len` reproduces
`n_symbols` exactly through that same floor() (the +0.5 offset absorbs
float rounding of the division without risking flooring one segment
short or over). The requested `samples_per_symbol` and the ACHIEVED one
(`data_len_trimmed // n_symbols`, after trimming) are identical whenever
`n` divides evenly by the requested value, and may differ by a small,
unavoidable amount otherwise (trimming to a whole number of segments is
inherently lossy at the edge) — `segment_plan`'s `achieved_sps` is always
the true, actually-used value; nothing here ever silently substitutes the
requested value for it.
"""

import numpy as np

SEGMENT_MODES = ("seconds_per_symbol", "samples_per_symbol", "target_symbol_count", "dim_ratio")


def resolve_samples_per_symbol(segment_mode, params, fs, n):
    """The samples-per-symbol the LIVE control asks for, before accounting
    for whether `n` divides evenly into it (see `segment_plan`)."""
    if segment_mode == "seconds_per_symbol":
        return max(1, int(round(params["seconds_per_symbol"] * fs)))
    if segment_mode == "samples_per_symbol":
        return max(1, int(round(params["samples_per_symbol"])))
    if segment_mode == "target_symbol_count":
        target = max(1, int(round(params["target_symbol_count"])))
        return max(1, int(round(n / target)))
    if segment_mode == "dim_ratio":
        ratio = params["dim_ratio"]
        return max(1, int(round(1.0 / ratio))) if ratio > 0 else n
    raise ValueError(f"Unknown segment_mode {segment_mode!r} — must be one of {SEGMENT_MODES}")


def segment_plan(segment_mode, params, fs, n):
    """Resolve whichever segmentation control is live to everything both
    a real run and the pre-run `derive()` readout need — the ONE place
    this arithmetic lives (see module docstring).

    Returns a dict:
      requested_sps       samples-per-symbol the control asks for
      n_symbols           resulting PAA segment count
      dim_ratio_for_call  the `dim_ratio` to pass into csax()/psax() that
                           reproduces `n_symbols` exactly
      data_len_trimmed    n - (n % n_symbols)
      n_trimmed           n - data_len_trimmed
      achieved_sps        data_len_trimmed // n_symbols — the ACTUAL
                           samples-per-symbol once trimming is accounted
                           for (see module docstring's round-trip note)
      dim_ratio_effective n_symbols / n
    """
    n = int(n)
    requested_sps = resolve_samples_per_symbol(segment_mode, params, fs, n)
    n_symbols = max(1, n // requested_sps)
    dim_ratio_for_call = (n_symbols + 0.5) / n
    data_len_trimmed = n - (n % n_symbols)
    n_trimmed = n - data_len_trimmed
    achieved_sps = data_len_trimmed // n_symbols if n_symbols else 0
    return {
        "requested_sps": requested_sps,
        "n_symbols": n_symbols,
        "dim_ratio_for_call": dim_ratio_for_call,
        "data_len_trimmed": data_len_trimmed,
        "n_trimmed": n_trimmed,
        "achieved_sps": achieved_sps,
        "dim_ratio_effective": n_symbols / n if n else 0.0,
    }


def recommend_sax_params(x, t, fs):
    """Part 2c's recommend() rule: a motif needs roughly 20-40 symbols to
    be distinctive without matching noise; capping at 256 keeps the
    string readable for long browsing spans.

        target_symbols = clip(round(len(x) / 20), 16, 256)
        sps            = max(1, round(len(x) / target_symbols))
        seconds_per_symbol = sps / fs
        preprocess_window_s = clip(span_duration_s / 20,
                                    10*sps/fs, span_duration_s / 4)

    Called fresh whenever the span changes (the run panel re-derives
    parameter defaults per span, never once at startup — Part 4a).
    """
    n = len(x)
    span_duration_s = n / fs
    target_symbols = int(np.clip(round(n / 20), 16, 256))
    sps = max(1, round(n / target_symbols))
    seconds_per_symbol = sps / fs
    preprocess_window_s = float(np.clip(span_duration_s / 20, 10 * sps / fs, span_duration_s / 4))
    return {
        "segment_mode": "seconds_per_symbol",
        "seconds_per_symbol": seconds_per_symbol,
        "samples_per_symbol": sps,
        "target_symbol_count": target_symbols,
        "dim_ratio": 1.0 / sps,
        "preprocess_window_s": preprocess_window_s,
    }


def _format_duration(seconds):
    """Plain-numpy duration formatter, deliberately NOT
    `UI.plots.format_scale_viewed` — `Adapters/` must stay importable
    headlessly (SLURM jobs, `Working.execution.execute_recipe`), so it
    can't depend on anything under `UI/`."""
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.2f} h"


def derive_sax_rows(x, t, fs, params):
    """Part 2d's read-only diagnostic rows — recomputed live as the user
    edits controls, WITHOUT running anything. Shared by both SAX adapters'
    `derive` hooks so they can never report different numbers for the
    same params (see module docstring).

    Returns list[(label, value, severity)], severity in {"", "warn", "error"}.
    """
    n = len(x)
    plan = segment_plan(params["segment_mode"], params, fs, n)
    span_duration_s = n / fs
    n_symbols = plan["n_symbols"]
    achieved_sps = plan["achieved_sps"]
    dropped_pct = 100.0 * plan["n_trimmed"] / n if n else 0.0

    if n_symbols < 2:
        symbols_severity = "error"
        symbols_note = " — cannot form a meaningful string"
    elif n_symbols < 10:
        symbols_severity = "warn"
        symbols_note = " — too short to be distinctive; decrease seconds per symbol"
    elif n_symbols > 2000:
        symbols_severity = "warn"
        symbols_note = " — string will not be human-readable; consider a coarser setting"
    else:
        symbols_severity = ""
        symbols_note = ""

    drop_severity = "warn" if dropped_pct > 1.0 else ""

    sps_seconds = achieved_sps / fs
    sps_label = (
        f"{sps_seconds:.1f} s" if sps_seconds < 90
        else f"{sps_seconds:.1f} s ({_format_duration(sps_seconds)})"
    )
    return [
        ("Span", f"{n:,} samples ({_format_duration(span_duration_s)})", ""),
        ("Samples per symbol", f"{achieved_sps:,}", ""),
        ("Seconds per symbol", sps_label, ""),
        ("Symbols produced", f"{n_symbols:,}{symbols_note}", symbols_severity),
        ("Effective dim_ratio", f"{plan['dim_ratio_effective']:.5g}", ""),
        ("Samples dropped",
         f"{plan['n_trimmed']:,} ({dropped_pct:.2f}% at the end of the span)", drop_severity),
    ]


def encoding_diagnostics(symbols, alphabet_size):
    """Part 6 3d's raw numbers — pure math on the symbol array, headless
    and testable independent of anything the run panel renders them into.

    Returns dict: histogram, occupancy_entropy_bits,
    occupancy_entropy_ceiling_bits, occupancy_entropy_fraction,
    self_transition_rate.
    """
    symbols = np.asarray(symbols, dtype=int)
    n = len(symbols)
    alphabet_size = max(int(alphabet_size), 1)
    histogram = np.bincount(symbols, minlength=alphabet_size)[:alphabet_size]
    probs = histogram[histogram > 0] / n if n else np.array([])
    # `+ 0.0` normalises the -0.0 an all-one-symbol string produces:
    # -(1.0 * log2(1.0)) is negative zero, which reports as "-0.00 bits" in
    # every readout and "-0.0" in metrics.json, and entropy is by
    # definition non-negative. `diagnostic_rows` below already worked
    # around this at its own f-string; fixing it at source means the JSON
    # and the display agree. (No test asserted on the -0.0, and -0.0 == 0.0
    # is True, so nothing that compared against 0.0 changes behaviour.)
    entropy_bits = float(-(probs * np.log2(probs)).sum()) + 0.0 if len(probs) else 0.0
    ceiling_bits = float(np.log2(alphabet_size)) if alphabet_size > 1 else 1.0
    if n > 1:
        self_transition_rate = float(np.sum(symbols[1:] == symbols[:-1]) / (n - 1))
    else:
        self_transition_rate = 0.0
    return {
        "histogram": histogram.tolist(),
        "occupancy_entropy_bits": entropy_bits,
        "occupancy_entropy_ceiling_bits": ceiling_bits,
        "occupancy_entropy_fraction": entropy_bits / ceiling_bits if ceiling_bits > 0 else 0.0,
        "self_transition_rate": self_transition_rate,
    }


def diagnostic_rows(symbols, details):
    """Part 6 3d's display-ready rows (label, value, severity) — the
    post-run counterpart to `derive_sax_rows`'s pre-run readout. Takes the
    full `details` dict (as returned by `csax()`/`psax()` under
    `return_details=True`) so it can report the realised alphabet size and
    (for cSAX) the Mean-Shift fallback flag alongside the numeric
    diagnostics, all from ONE call.
    """
    alphabet_size = details["alphabet_size"]
    diag = encoding_diagnostics(symbols, alphabet_size)
    rows = []

    frac = diag["occupancy_entropy_fraction"]
    entropy_severity = "warn" if frac < 0.7 else ""
    entropy_note = (
        " — alphabet has collapsed; most segments landed in one or two symbols; "
        "try a finer seconds-per-symbol, or enable detrending" if entropy_severity else ""
    )
    rows.append((
        "Occupancy entropy",
        f"{diag['occupancy_entropy_bits'] + 0.0:.2f} / {diag['occupancy_entropy_ceiling_bits']:.2f} bits "
        f"({max(frac, 0.0) * 100:.1f}% of ceiling){entropy_note}",
        entropy_severity,
    ))

    rate = diag["self_transition_rate"]
    rate_severity = "warn" if rate > 0.95 else ""
    rate_note = (
        " — consecutive symbols are nearly always the same; this scale is oversampled "
        "and carrying little information; try a coarser seconds-per-symbol" if rate_severity else ""
    )
    rows.append(("Transition self-rate", f"{rate * 100:.1f}%{rate_note}", rate_severity))

    if details.get("fallback_used"):
        rows.append((
            "cSAX fallback",
            "Mean-Shift found fewer than 2 clusters — this run silently fell back to "
            "classic SAX with 10 Gaussian cutlines. The result is not cSAX.",
            "error",
        ))

    rows.append(("Realised alphabet size", f"{alphabet_size}", ""))
    return rows


def _letter(i):
    """Duplicated from `UI.plots.symbol_to_letter` deliberately, not
    imported — `Adapters/` must stay importable headlessly (SLURM jobs),
    so it cannot depend on anything under `UI/`. Keep the two in sync if
    either changes; both are 4 lines."""
    i = int(i)
    if i < 26:
        return chr(ord("a") + i)
    i -= 26
    return chr(ord("a") + i // 26) + chr(ord("a") + i % 26)


def plot_encoding_matplotlib(x, t, symbols, details, letter_threshold=120):
    """Part 6 4d: `AdapterSpec.plot`'s matplotlib-Figure contract for both
    SAX adapters — a DELIBERATELY SEPARATE renderer from the UI's
    interactive HoloViews encoding view (`UI.plots.build_encoding_panels`),
    sharing only its INPUT (`symbols`/`details`), not any drawing code —
    `Adapters/` cannot import `UI/` (headless-cluster contract) so the two
    views cannot literally share a renderer the way `build_peek_curve`/
    the main curve do. Draws the WHOLE span; letters only if
    `n_symbols <= letter_threshold`, matching the interactive view's rule.
    """
    import matplotlib
    import matplotlib.pyplot as plt

    x = np.asarray(x, dtype=float)
    t = np.asarray(t, dtype=float)
    symbols = np.asarray(symbols, dtype=int)
    sps = int(details["samples_per_symbol"])
    n_symbols = int(details["n_symbols"])
    alphabet_size = int(details["alphabet_size"])
    paa_raw = np.asarray(details["paa_raw"], dtype=float)
    cutlines_raw = np.asarray(details["cutlines_raw"], dtype=float)

    idx = np.minimum(np.arange(n_symbols + 1) * sps, len(t) - 1)
    seg_t = t[idx]
    cmap = matplotlib.colormaps["viridis"].resampled(max(alphabet_size, 2))
    colors = [cmap(i) for i in range(alphabet_size)]

    fig, axes = plt.subplots(4, 1, figsize=(14, 11), sharex=True,
                              gridspec_kw={"height_ratios": [2, 2, 2.5, 0.6]})

    axes[0].plot(t, x, linewidth=0.4, color="#1f4e8c")
    axes[0].set_ylabel("amplitude")
    axes[0].set_title("Encoded signal")

    axes[1].plot(t, x, linewidth=0.3, color="#bbbbbb")
    for i in range(n_symbols):
        axes[1].plot([seg_t[i], seg_t[i + 1]], [paa_raw[i], paa_raw[i]], color="#d62728", linewidth=2)
    axes[1].set_ylabel("amplitude")
    axes[1].set_title("PAA (red) over signal (grey)")

    ax = axes[2]
    y_lo, y_hi = float(np.min(paa_raw)), float(np.max(paa_raw))
    pad = (y_hi - y_lo) * 0.1 or 1.0
    y_extent = (y_lo - pad, y_hi + pad)
    edges = [y_extent[0]] + list(cutlines_raw) + [y_extent[1]]
    for sym, (blo, bhi) in enumerate(zip(edges[:-1], edges[1:])):
        ax.axhspan(blo, bhi, color=colors[sym % len(colors)], alpha=0.35)
    for c in cutlines_raw:
        ax.axhline(c, color="#333333", linewidth=1, linestyle="--")
    step_x, step_y = [], []
    for i in range(n_symbols):
        step_x += [seg_t[i], seg_t[i + 1]]
        step_y += [paa_raw[i], paa_raw[i]]
    ax.plot(step_x, step_y, color="black", linewidth=1.2)
    ax.set_ylim(*y_extent)
    ax.set_ylabel("amplitude")
    ax.set_title("Quantisation — PAA vs. learned cutlines")

    ax = axes[3]
    show_letters = n_symbols <= letter_threshold
    for i in range(n_symbols):
        ax.axvspan(seg_t[i], seg_t[i + 1], color=colors[symbols[i] % len(colors)])
        if show_letters:
            ax.text((seg_t[i] + seg_t[i + 1]) / 2, 0.5, _letter(symbols[i]),
                     ha="center", va="center", fontsize=7, color="white")
    ax.set_yticks([])
    ax.set_xlim(t[0], t[-1])
    ax.set_xlabel("time (s)")
    ax.set_title("Symbol strip")

    fig.tight_layout()
    return fig
