"""
run_multiscale_sax.py
=====================
Runnable demo: build a multiscale symbolic pyramid over one real channel and
produce all five diagnostic plots plus the numeric diagnostics behind them.

    python "Experimentation/Detection experiments/run_multiscale_sax.py"
    python "Experimentation/Detection experiments/run_multiscale_sax.py" \
        --channel M2_concat_fs1_CH5.npy --method csax --span 0:200000
    python "Experimentation/Detection experiments/run_multiscale_sax.py" --no-show --save

Loading matches `rupture_testing.py`: a bare filename goes to
`Working.Preprocessing.manage_data.load_data.load_raw_data`, which resolves it
onto wherever the DATA restructure put it ("M2_concat_fs1_CH2.npy" ->
DATA/derived/channels/M2_concat_fs1/CH2.npy). Run from the repo root, since
that resolution is repo-root-relative.

Nothing is saved unless `--save` is passed, and nothing runs at import time.
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

import argparse
import re

import numpy as np
import matplotlib.pyplot as plt

from Working.Preprocessing.manage_data.load_data import load_raw_data

from multiscale_sax import MultiScaleSAX
from plot_multiscale_sax import (
    plot_symbol_pyramid,
    plot_occupancy_by_scale,
    plot_transition_matrix,
    plot_scale_persistence,
    plot_offset_sensitivity,
    occupancy_diagnostics,
    transition_diagnostics,
    persistence_diagnostics,
    offset_diagnostics,
    save_figure,
)

DEFAULT_CHANNEL = "M2_concat_fs1_CH2.npy"
DEFAULT_FS = 1.0   # Hz (matches the fs1 recording folder)

_CH_RE = re.compile(r"_CH(\d+)\.npy$", re.IGNORECASE)


def parse_span(text, n):
    """'START:END' in samples -> (start, end). Blank ends mean the signal's own."""
    if not text:
        return 0, n
    if ":" not in text:
        raise argparse.ArgumentTypeError(
            f"--span must be 'START:END' in samples; got {text!r}"
        )
    lo, hi = text.split(":", 1)
    start = int(lo) if lo.strip() else 0
    end = int(hi) if hi.strip() else n
    start, end = max(0, start), min(n, end)
    if end <= start:
        raise ValueError(f"--span {text!r} is empty after clamping to [0, {n}).")
    return start, end


def rule(title):
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


def pick_varied_view(msax, width_samples, scale, n_candidates=200):
    """
    Choose the `width_samples` window whose symbol sequence at `scale` uses the
    most of the alphabet, breaking ties on entropy.

    Purely a display choice for the pyramid demo: on a drift-dominated channel
    most windows sit inside one or two symbols of the global distribution, so
    an arbitrary window renders as a flat colour block that demonstrates
    nothing. This finds a window where the encoding is actually doing work.
    It selects nothing and asserts nothing about the science.
    """
    sym = msax.symbols(scale, 0)
    per_win = max(1, width_samples // scale)
    if per_win >= len(sym):
        return 0, min(width_samples, msax.n_samples)

    starts = np.linspace(0, len(sym) - per_win, min(n_candidates, len(sym) - per_win + 1))
    best, best_key = 0, (-1, -1.0)
    for i in starts.astype(int):
        w = sym[i:i + per_win]
        counts = np.bincount(w, minlength=msax.scale_info[scale]["alphabet_size"])
        p = counts[counts > 0] / counts.sum()
        key = (int(np.count_nonzero(counts)), float(-(p * np.log2(p)).sum()))
        if key > best_key:
            best_key, best = key, i
    v0 = int(best) * scale
    return v0, min(v0 + width_samples, msax.n_samples)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Multiscale SAX pyramid + diagnostics on one real channel.")
    p.add_argument("--channel", default=DEFAULT_CHANNEL,
                   help=f"Bare recording filename (default: {DEFAULT_CHANNEL}).")
    p.add_argument("--fs", type=float, default=DEFAULT_FS, help="Sample rate in Hz.")
    p.add_argument("--span", default=None,
                   help="'START:END' in samples to encode. Default: whole channel.")
    p.add_argument("--method", default="psax", choices=["psax", "csax"],
                   help="Cutline learner (default: psax).")
    p.add_argument("--cutline-mode", default="shared_renormalised",
                   choices=["per_scale", "shared_renormalised", "shared_raw"],
                   help="Default shared_renormalised: symbols comparable across scales.")
    p.add_argument("--scales", default="2:4096",
                   help="'MIN:MAX' dyadic samples-per-symbol (default 2:4096).")
    p.add_argument("--alphabet", type=int, default=8)
    p.add_argument("--offsets", default="all", choices=["all", "zero"])
    p.add_argument("--max-offsets", type=int, default=16)
    p.add_argument("--view", default=None,
                   help="'START:END' in samples for the pyramid plot. "
                        "Default: a --view-hours window at the middle of the span.")
    p.add_argument("--view-hours", type=float, default=8.0,
                   help="Length of the pyramid window in hours (default 8).")
    p.add_argument("--transition-scale", type=int, default=None,
                   help="Scale for the transition-matrix plot (default: mid-ladder).")
    p.add_argument("--offset-scale", type=int, default=None,
                   help="Scale for the offset-sensitivity plot (default: mid-ladder).")
    p.add_argument("--save", action="store_true",
                   help="Write the figures under Plots/ via Working.artifacts.")
    p.add_argument("--save-root", default="Plots",
                   help="Root for --save (default Plots/). Point elsewhere to "
                        "try the naming convention without writing into the repo.")
    p.add_argument("--no-show", action="store_true",
                   help="Build the figures without opening a window.")
    args = p.parse_args(argv)

    # ── Load ──────────────────────────────────────────────────────────────────
    rule(f"LOAD  {args.channel}  (fs={args.fs} Hz)")
    x, t = load_raw_data(args.channel, args.fs)
    start, end = parse_span(args.span, len(x))
    x = x[start:end]
    print(f"  {len(x)} samples  ({len(x) / args.fs / 3600:.2f} h)"
          f"  span [{start}, {end})")
    print(f"  raw range [{x.min():.4g}, {x.max():.4g}]  mean {x.mean():.4g}  "
          f"std {x.std():.4g}")
    lag1 = float(np.corrcoef(x[:-1], x[1:])[0, 1])
    print(f"  lag-1 autocorrelation {lag1:.6f}"
          f"{'   (drift-dominated: PAA will barely reduce variance)' if lag1 > 0.99 else ''}")

    lo, hi = (int(v) for v in args.scales.split(":"))

    # ── Encode ────────────────────────────────────────────────────────────────
    rule(f"ENCODE  method={args.method}  cutline_mode={args.cutline_mode}  "
         f"offsets={args.offsets}")
    msax = MultiScaleSAX(x, fs=args.fs, method=args.method, scales=(lo, hi),
                         alphabet_size=args.alphabet,
                         cutline_mode=args.cutline_mode, offsets=args.offsets,
                         max_offsets=args.max_offsets, random_state=0)
    print(msax.describe())

    # Mid-ladder defaults, so the single-scale plots land somewhere informative
    # rather than at an extreme of the range.
    mid = msax.scales[len(msax.scales) // 2]
    trans_scale = args.transition_scale or mid
    off_scale = args.offset_scale or mid

    # Pyramid view window. Default picks the most symbolically varied window
    # rather than the middle of the recording: on a drift-dominated channel an
    # arbitrary window sits inside one or two symbols of the global
    # distribution and the pyramid comes out a single flat colour, which says
    # nothing about the encoding. Pass --view to override.
    if args.view:
        v0, v1 = parse_span(args.view, len(x))
        how = "explicit --view"
    else:
        width = min(int(args.view_hours * 3600 * args.fs), len(x))
        v0, v1 = pick_varied_view(msax, width, mid)
        how = f"auto-selected (most varied {args.view_hours:g} h at sps={mid})"
    print(f"\n  pyramid view: samples [{v0}, {v1})  "
          f"({(v1 - v0) / args.fs / 3600:.2f} h)  {how}")

    figs = {}

    # ── 1. Symbol pyramid ─────────────────────────────────────────────────────
    rule("PLOT 1  Symbol pyramid - which scale does the structure live at?")
    figs["pyramid"] = plot_symbol_pyramid(msax, v0, v1)
    print(f"  drawn over [{v0}, {v1}) at offset 0")

    # ── 2. Occupancy by scale ─────────────────────────────────────────────────
    rule("PLOT 2  Occupancy and entropy by scale - which scales carry information?")
    figs["occupancy"] = plot_occupancy_by_scale(msax)
    occ = occupancy_diagnostics(msax)
    print(f"  {'sps':>6} {'span':>9} {'n_sym':>8} {'alpha':>6} {'used':>5} "
          f"{'H(bits)':>8} {'ceiling':>8} {'H/ceil':>7} {'max/min':>8}")
    for r in occ:
        span = f"{r['minutes'] * 60:.0f}s" if r["minutes"] < 1 else f"{r['minutes']:.1f}m"
        ratio = r["max_min_ratio"]
        print(f"  {r['scale']:>6} {span:>9} {r['n_symbols']:>8} "
              f"{r['alphabet_size']:>6} {r['n_symbols_used']:>5} "
              f"{r['entropy_bits']:>8.3f} {r['ceiling_bits']:>8.3f} "
              f"{r['entropy_frac']:>7.3f} "
              f"{('inf' if not np.isfinite(ratio) else f'{ratio:.2f}'):>8}")
    weak = [r["scale"] for r in occ if r["entropy_frac"] < 0.5]
    print(f"  -> collapsed scales to drop from later stages: "
          f"{weak if weak else 'none'}")

    # ── 3. Transition matrix ──────────────────────────────────────────────────
    rule(f"PLOT 3  Transition matrix at sps={trans_scale} - over- or under-sampled?")
    figs["transition"] = plot_transition_matrix(msax, trans_scale)
    print("\n  Full ladder:")
    print(f"  {'sps':>6} {'span':>9} {'self':>7} {'redund':>8} "
          f"{'H(next)':>8} {'H(nxt|cur)':>11}  verdict")
    for s in msax.scales:
        d = transition_diagnostics(msax, s)
        span = f"{d['minutes'] * 60:.0f}s" if d["minutes"] < 1 else f"{d['minutes']:.1f}m"
        print(f"  {s:>6} {span:>9} {d['self_transition']:>7.3f} "
              f"{d['redundancy']:>8.3f} {d['marginal_entropy_bits']:>8.3f} "
              f"{d['cond_entropy_bits']:>11.3f}  {d['verdict']}")

    # ── 4. Scale persistence ──────────────────────────────────────────────────
    rule("PLOT 4  Cross-scale persistence - genuinely multiscale, or noise?")
    figs["persistence"] = plot_scale_persistence(msax, 0, len(x))
    pers = persistence_diagnostics(msax, 0, len(x))
    print(f"  {'s -> 2s':>12} {'n_pairs':>9} {'NMI':>7} {'baseline':>9} "
          f"{'2sd':>7} {'excess':>8}")
    for r in pers:
        pair = f"{r['fine_scale']} -> {r['coarse_scale']}"
        print(f"  {pair:>12} "
              f"{r['n_pairs']:>9} {r['nmi']:>7.3f} {r['baseline']:>9.3f} "
              f"{2 * r['baseline_std']:>7.3f} {r['excess']:>8.3f}")
    if pers:
        peak = max(pers, key=lambda r: r["excess"])
        band = [r["fine_scale"] for r in pers if r["excess"] > 0.5 * peak["excess"]]
        print(f"  -> peak excess {peak['excess']:.3f} at sps="
              f"{peak['fine_scale']}->{peak['coarse_scale']}; "
              f"elevated band sps {min(band)}-{max(band)}")

    # ── 5. Offset sensitivity ─────────────────────────────────────────────────
    rule(f"PLOT 5  Offset sensitivity at sps={off_scale} - must search sweep phase?")
    if args.offsets == "zero":
        print("  SKIPPED: built with offsets='zero', so there is nothing to compare.")
        print("  Re-run with --offsets all to measure phase sensitivity.")
    else:
        figs["offsets"] = plot_offset_sensitivity(msax, off_scale)
        print("\n  Full ladder:")
        print(f"  {'sps':>6} {'span':>9} {'n_off':>6} {'mean':>7} {'adjacent':>9} "
              f"{'max':>7}  verdict")
        for s in msax.scales:
            if len(msax.offsets_for(s)) < 2:
                continue
            d = offset_diagnostics(msax, s)
            info = msax.scale_info[s]
            span = (f"{info['minutes'] * 60:.0f}s" if info["minutes"] < 1
                    else f"{info['minutes']:.1f}m")
            print(f"  {s:>6} {span:>9} {len(d['offsets']):>6} "
                  f"{d['mean_disagreement']:>7.3f} {d['adjacent_disagreement']:>9.3f} "
                  f"{d['max_disagreement']:>7.3f}  {d['verdict']}")

    # ── Save / show ───────────────────────────────────────────────────────────
    if args.save:
        rule("SAVE")
        m = _CH_RE.search(args.channel)
        channel_no = int(m.group(1)) if m else 0
        if not m:
            print(f"  note: no _CH<n> in {args.channel!r}; filing under CH00.")
        for name, fig in figs.items():
            path = save_figure(fig, msax, args.channel, channel_no, name,
                               span=(start, end), root=args.save_root)
            print(f"  {name:>12} -> {path}")

    if not args.no_show:
        plt.show()

    return msax, figs


if __name__ == "__main__":
    main()
