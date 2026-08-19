"""
seed_replicas.py
==================
Focused figure: one seed, one channel, and only the matches that are
genuinely SMOOTH replicas of the seed rather than noise with the same
underlying trend.

The problem this solves
-----------------------
z-normalised Euclidean distance cannot tell a clean copy of a shape from a
noisy signal wandering along the same trend. The noise is zero-mean, so
over a long window most of it cancels in the sum of squared differences,
and a jagged span with the right overall drift lands at much the same
distance as a smooth one. Measured on `cat04 crestedwave` against
M2_aug CH0: among 80 matches inside `d/sqrt(m) <= 0.30`, roughness varied
by a factor of **16** (1.6x to 13.0x the seed's) with essentially no
relationship to distance — matches at d=0.260 and d=0.248 sat at 13.0x and
1.6x respectively. Distance simply does not carry this information, so no
threshold on distance can recover it.

The fix is a second, independent axis: how jagged a span is, relative to
the seed.

    roughness(v)      = RMS first difference of the z-normalised span
    roughness_ratio   = roughness(match) / roughness(seed)

A ratio of 1.0 means "exactly as smooth as the seed"; 2.0 means "twice as
jagged". `--max-roughness` (default 2.0) is therefore readable directly as
a claim about the figure: nothing shown is more than twice as jagged as
the exemplar it is supposed to replicate.

This is the same quantity as the complexity term in Batista et al.'s
complexity-invariant distance, used here as a FILTER rather than as a
correction — the aim is to show clean replicas, not to make noisy spans
score better.

The rejected matches are drawn too, in their own panel, so the filter is
visible and arguable rather than a silent cut.

Examples
--------
    python Pipelines/motif_report/seed_replicas.py --element sharkfin
    python Pipelines/motif_report/seed_replicas.py --seed-id 4 --max-roughness 1.8
"""

import argparse
import os
import sys

import numpy as np

from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Working.database.schema import init_db
from Working.distances import z_normalize

from Pipelines.motif_report.motif_report import _apply_report_style, overlay_limits, time_axis
from Pipelines.motif_report.family_search import (
    exemplar_waveform,
    get_recording,
    load_catalogue_seeds,
    load_channel,
    search_seed,
)


DEFAULT_MAX_ROUGHNESS = 2.0
SEED_INDICATOR_COLOR = "#1a1a1a"


def roughness(values):
    """RMS first difference of the z-normalised span.

    z-normalising first makes this independent of amplitude, so it measures
    only how much of the span's variance sits at the sampling frequency —
    i.e. how jagged it is — not how big it is.
    """
    values = np.asarray(values, dtype=float).ravel()
    if len(values) < 2:
        return 0.0
    return float(np.sqrt(np.mean(np.diff(z_normalize(values)) ** 2)))


def split_by_roughness(matches, x, m, seed_values, max_ratio=DEFAULT_MAX_ROUGHNESS):
    """Partition matches into (smooth, noisy), each entry
    `(idx, distance, roughness_ratio)`, ordered by distance."""
    seed_r = roughness(seed_values)
    smooth, noisy = [], []
    for idx, dist in matches:
        span = x[idx:idx + m]
        if len(span) < m:
            continue
        ratio = (roughness(span) / seed_r) if seed_r > 0 else np.inf
        (smooth if ratio <= max_ratio else noisy).append((idx, dist, ratio))
    return smooth, noisy


def plot_seed_replicas(seed, target, smooth, noisy, *, max_ratio=DEFAULT_MAX_ROUGHNESS,
                       lw_scale=1.0, font_scale=1.0, figsize=(17.0, 9.2), max_draw=30):
    """One seed, one channel, three questions: what is the seed, where do
    its clean replicas sit, and what did the roughness filter throw away."""
    import matplotlib as mpl
    import matplotlib.pyplot as plt

    _apply_report_style(lw_scale, font_scale)
    fig = plt.figure(figsize=figsize)
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.55], width_ratios=[1.0, 2.35, 1.0],
                          left=0.05, right=0.912, top=0.885, bottom=0.085,
                          wspace=0.26, hspace=0.36)

    fs = float(target["fs"])
    x = load_channel(target["npy_path"])
    m = seed["m"]
    q = np.asarray(exemplar_waveform(seed), dtype=float)
    t_win = np.arange(m) / fs / 60.0

    drawn = smooth[:max_draw]
    dists = [d for _, d, _ in drawn]
    norm = mpl.colors.Normalize(
        vmin=min(dists) / np.sqrt(m) if dists else 0.0,
        vmax=max(dists) / np.sqrt(m) if dists else 1.0)
    cmap = mpl.colormaps["viridis"]

    # ── Row 0: the channel, with kept and rejected marked differently ────
    ax_sig = fig.add_subplot(gs[0, :])
    t_full, t_label, t_div = time_axis(len(x), fs)
    x_mv = x * 1000.0
    ax_sig.plot(t_full, x_mv, linewidth=0.7 * lw_scale, color="#3b5f8a", alpha=0.8)
    lo, hi = float(x_mv.min()), float(x_mv.max())
    span = hi - lo
    bar = max(m / fs / t_div, 0.005 * (t_full[-1] - t_full[0]))
    for idx, _d, _r in noisy:
        ax_sig.add_patch(plt.Rectangle((idx / fs / t_div - bar / 2, lo), bar, span,
                                       facecolor="#c9c9c9", edgecolor="none", alpha=0.75))
    for idx, dist, _r in drawn:
        c = cmap(norm(dist / np.sqrt(m)))
        ax_sig.add_patch(plt.Rectangle((idx / fs / t_div - bar / 2, lo), bar, span,
                                       facecolor=c, edgecolor="none", alpha=0.95))
        ax_sig.plot([idx / fs / t_div], [hi + 0.05 * span], marker="v",
                    markersize=9 * lw_scale, color=c, markeredgewidth=0)
    t_seed = seed["start_idx"] / seed["fs"] / t_div
    if target["id"] == seed["recording_id"]:
        ax_sig.plot([t_seed], [hi + 0.05 * span], marker="v", markersize=13 * lw_scale,
                    color=SEED_INDICATOR_COLOR, markeredgewidth=0)
    ax_sig.set_xlim(t_full[0], t_full[-1])
    ax_sig.set_ylim(lo - 0.03 * span, hi + 0.15 * span)
    ax_sig.set_xlabel(t_label)
    ax_sig.set_ylabel("amplitude (mV)")
    ax_sig.set_title(
        f"{target['source_file']} CH{target['channel']:02d}   —   "
        f"{len(smooth)} smooth replica(s) in colour, {len(noisy)} rejected as noisy in grey",
        fontsize=11.5)

    # ── Row 1 left: the seed on its own ──────────────────────────────────
    ax_seed = fig.add_subplot(gs[1, 0])
    ax_seed.plot(t_win, q * 1000.0, color=SEED_INDICATOR_COLOR,
                 linewidth=2.6 * lw_scale, solid_capstyle="round")
    ax_seed.set_title(f"SEED — {seed['label']}\n"
                      f"CH{seed['channel']:02d} @ {seed['start_idx'] / seed['fs'] / 3600.0:.2f} h  "
                      f"({m / fs / 60.0:.1f} min)  roughness {roughness(q):.4f}",
                      fontsize=10)
    ax_seed.set_xlabel("time within seed (minutes)")
    ax_seed.set_ylabel("amplitude (mV)")

    # ── Row 1 middle: the kept replicas, z-normalised ────────────────────
    ax_ov = fig.add_subplot(gs[1, 1])
    stacked = []
    for idx, dist, ratio in drawn:
        z = z_normalize(x[idx:idx + m])
        stacked.append(z)
        ax_ov.plot(t_win, z, color=cmap(norm(dist / np.sqrt(m))),
                   linewidth=1.9 * lw_scale, alpha=0.85, zorder=3, solid_capstyle="round")
    if len(stacked) >= 3:
        arr = np.asarray(stacked)
        mu, sd = arr.mean(axis=0), arr.std(axis=0)
        ax_ov.fill_between(t_win, mu - sd, mu + sd, color="0.55", alpha=0.20,
                           zorder=1, linewidth=0, label="replicas: mean +/- 1 SD")
        stacked.extend([mu - sd, mu + sd])
    # The seed is a reference line here, not a trace competing with the
    # replicas -- dotted and semi-transparent, deliberately behind them.
    zq = z_normalize(q)
    ax_ov.plot(t_win, zq, color=SEED_INDICATOR_COLOR, linewidth=2.4 * lw_scale,
               linestyle=":", alpha=0.5, zorder=2, label="seed (reference)")
    stacked.append(zq)
    if stacked:
        ax_ov.set_ylim(*overlay_limits(stacked))
    ax_ov.set_xlim(float(t_win[0]), float(t_win[-1]))
    ax_ov.set_xlabel("time within window (minutes)")
    ax_ov.set_ylabel("z-score")
    ax_ov.set_title(f"smooth replicas only  (roughness <= {max_ratio:g}x the seed)"
                    + (f", showing {len(drawn)} of {len(smooth)}" if len(smooth) > len(drawn) else ""),
                    fontsize=11.5)
    ax_ov.legend(fontsize=8.5, loc="best", framealpha=0.85, handlelength=2.2)

    cax = fig.add_axes([0.945, 0.085, 0.011, 0.42])
    fig.colorbar(mpl.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax
                 ).set_label("distance to seed / sqrt(m)", fontsize=9.5)

    # ── Row 1 right: what the filter removed ─────────────────────────────
    ax_rej = fig.add_subplot(gs[1, 2])
    if noisy:
        rej_stack = []
        for idx, _dist, _ratio in noisy[:max_draw]:
            z = z_normalize(x[idx:idx + m])
            rej_stack.append(z)
            ax_rej.plot(t_win, z, color="#b03a2e", linewidth=0.9 * lw_scale,
                        alpha=0.45, zorder=2)
        ax_rej.plot(t_win, zq, color=SEED_INDICATOR_COLOR, linewidth=2.2 * lw_scale,
                    linestyle=":", alpha=0.6, zorder=3)
        rej_stack.append(zq)
        ax_rej.set_ylim(*overlay_limits(rej_stack))
        worst = max(r for _, _, r in noisy)
        ax_rej.set_title(f"rejected as noisy ({len(noisy)})\n"
                         f"roughness up to {worst:.1f}x the seed", fontsize=10)
    else:
        ax_rej.text(0.5, 0.5, "nothing rejected", ha="center", va="center",
                    transform=ax_rej.transAxes)
        ax_rej.set_title("rejected as noisy (0)", fontsize=10)
    ax_rej.set_xlim(float(t_win[0]), float(t_win[-1]))
    ax_rej.set_xlabel("time within window (minutes)")
    ax_rej.set_ylabel("z-score")

    fig.suptitle(
        f"Smooth replicas of {seed['label']} in "
        f"{target['source_file'].split('.')[0]} CH{target['channel']:02d}",
        fontsize=14, y=0.955)
    return fig


def build_parser():
    p = argparse.ArgumentParser(
        description="Seed, channel, and only its smooth replicas.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--db", default=None)
    p.add_argument("--target", type=int, default=1,
                   help="recording id to search in (default 1 = M2_aug CH0)")
    p.add_argument("--seed-id", type=int, action="append", default=None,
                   help="catalogue ID_Number; repeatable. Default: the sharkfin and "
                        "crestedwave exemplars (2 and 4)")
    p.add_argument("--element", default=None, help="instead of --seed-id, match on Elements")
    p.add_argument("--max-roughness", type=float, default=DEFAULT_MAX_ROUGHNESS,
                   help="keep matches no more than this many times as jagged as the seed")
    p.add_argument("--max-distance-norm", type=float, default=0.30)
    p.add_argument("--max-matches", type=int, default=250,
                   help="cap BEFORE the roughness filter")
    p.add_argument("--max-draw", type=int, default=30, help="traces drawn per panel")
    p.add_argument("--linewidth", type=float, default=1.0)
    p.add_argument("--font-scale", type=float, default=1.0)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--formats", default="png,pdf")
    p.add_argument("--out-dir", default=os.path.join("Plots", "seed_replicas"))
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(args.out_dir, exist_ok=True)
    conn = init_db(args.db)
    try:
        seeds = load_catalogue_seeds(conn, datasets=["M2_aug"], element=args.element,
                                     max_seed_minutes=200, verbose=False)
        if args.element is None:
            wanted = args.seed_id or [2, 4]
            want = {f"cat{i:02d}" for i in wanted}
            seeds = [s for s in seeds if s["label"].split()[0] in want]
        if not seeds:
            raise SystemExit("No catalogue seeds matched.")
        target = get_recording(conn, args.target)
    finally:
        conn.close()

    print(f"target: {target['source_file']} CH{target['channel']:02d} (id={target['id']})")
    for seed in seeds:
        result = search_seed(seed, target, max_distance_norm=args.max_distance_norm,
                             max_matches=args.max_matches)
        x = load_channel(target["npy_path"])
        q = exemplar_waveform(seed)
        smooth, noisy = split_by_roughness(result["matches"], x, result["m"], q,
                                           max_ratio=args.max_roughness)
        print(f"\n{seed['label']}  ({seed['m'] / seed['fs'] / 60.0:.1f} min, "
              f"roughness {roughness(q):.4f})")
        print(f"  {len(result['matches'])} match(es) within d/sqrt(m) <= {args.max_distance_norm:g}"
              f"  ->  {len(smooth)} smooth, {len(noisy)} rejected as noisy")
        if smooth:
            print(f"  kept roughness ratio: {min(r for _,_,r in smooth):.2f} "
                  f"to {max(r for _,_,r in smooth):.2f}")
            print(f"  kept distance range : {min(d for _,d,_ in smooth) / np.sqrt(result['m']):.3f} "
                  f"to {max(d for _,d,_ in smooth) / np.sqrt(result['m']):.3f}")

        fig = plot_seed_replicas(seed, target, smooth, noisy, max_ratio=args.max_roughness,
                                 lw_scale=args.linewidth, font_scale=args.font_scale,
                                 max_draw=args.max_draw)
        stem = "replicas_" + "".join(
            c if c.isalnum() or c in "-_" else "_" for c in seed["label"])
        for fmt in (f.strip() for f in args.formats.split(",") if f.strip()):
            path = os.path.join(args.out_dir, f"{stem}.{fmt}")
            fig.savefig(path, dpi=args.dpi)
        plt.close(fig)
        print(f"  -> {os.path.join(args.out_dir, stem)}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
