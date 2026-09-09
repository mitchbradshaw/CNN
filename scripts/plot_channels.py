"""
plot_channels.py
=================
Interactive matplotlib viewer over every channel of one materialized
recording (`DATA/derived/channels/<name>/CH*.npy`), stacked on a shared,
zoomable/pannable time axis.

The underlying recordings run into the tens of millions of samples, so
this never renders full resolution: each channel is memory-mapped (no
full-file load) and only the samples visible in the current x-range are
pulled and min/max-decimated to a fixed pixel budget. Zooming or panning
(matplotlib's normal toolbar, or scroll-to-zoom) re-decimates from the
mmap on every `xlim_changed`, so panning to any point in a 26-day
recording and zooming into a single spike both stay fast.

Usage
-----
    python scripts/plot_channels.py MJu26a
    python scripts/plot_channels.py L_LM_Jul_26_J_raw
    python scripts/plot_channels.py L_LM_Jul_26_J_raw --points 4000
"""

import argparse
import json
import os
import sys

import numpy as np
import matplotlib.pyplot as plt

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANNEL_ROOT = os.path.join(_REPO_ROOT, "DATA", "derived", "channels")


def _minmax_decimate(mmap_arr, i0, i1, target_points):
    """Return (x_idx, y) covering samples [i0, i1) of a 1-D mmap array,
    min/max-decimated to about `target_points` so spikes inside a bin
    survive instead of being averaged away."""
    i0 = max(0, i0)
    i1 = min(mmap_arr.shape[0], i1)
    n = i1 - i0
    if n <= 0:
        return np.array([]), np.array([])
    bins = max(1, min(target_points // 2, n))
    if n <= target_points:
        idx = np.arange(i0, i1)
        return idx, mmap_arr[i0:i1]

    edges = np.linspace(i0, i1, bins + 1, dtype=np.int64)
    xs = np.empty(bins * 2, dtype=np.int64)
    ys = np.empty(bins * 2, dtype=mmap_arr.dtype)
    for b in range(bins):
        lo, hi = edges[b], max(edges[b] + 1, edges[b + 1])
        chunk = mmap_arr[lo:hi]
        amin = lo + int(np.argmin(chunk))
        amax = lo + int(np.argmax(chunk))
        first, second = (amin, amax) if amin <= amax else (amax, amin)
        xs[2 * b], xs[2 * b + 1] = first, second
        ys[2 * b], ys[2 * b + 1] = mmap_arr[first], mmap_arr[second]
    return xs, ys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="Name of the derived-channels folder, e.g. MJu26a")
    parser.add_argument("--points", type=int, default=6000,
                         help="Approx. rendered points per channel per redraw (default 6000)")
    args = parser.parse_args()

    ds_dir = os.path.join(CHANNEL_ROOT, args.dataset)
    if not os.path.isdir(ds_dir):
        available = sorted(d for d in os.listdir(CHANNEL_ROOT) if os.path.isdir(os.path.join(CHANNEL_ROOT, d)))
        print(f"No such dataset dir: {ds_dir}\nAvailable: {available}", file=sys.stderr)
        sys.exit(1)

    manifest_path = os.path.join(ds_dir, "manifest.json")
    manifest = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)

    ch_files = sorted(
        (f for f in os.listdir(ds_dir) if f.startswith("CH") and f.endswith(".npy")),
        key=lambda f: int(f[2:-4]),
    )
    if not ch_files:
        print(f"No CH*.npy files found in {ds_dir}", file=sys.stderr)
        sys.exit(1)

    channels = [np.load(os.path.join(ds_dir, f), mmap_mode="r") for f in ch_files]
    n_samples = channels[0].shape[0]
    fs = manifest.get("fs")
    fs_note = manifest.get("fs_note")

    fig, axes = plt.subplots(len(channels), 1, sharex=True, figsize=(14, 2 * len(channels)))
    if len(channels) == 1:
        axes = [axes]

    lines = []
    for ax, ch_arr, fname in zip(axes, channels, ch_files):
        (line,) = ax.plot([], [], linewidth=0.6)
        lines.append(line)
        ax.set_ylabel(fname[:-4])
        ax.set_xlim(0, n_samples)

    xlabel = f"sample index (fs={fs} Hz)" if fs else "sample index (fs unknown)"
    axes[-1].set_xlabel(xlabel)
    title = manifest.get("source_file", args.dataset)
    if fs_note:
        title += "  [fs inferred — see manifest.json]"
    fig.suptitle(title)

    _redrawing = {"busy": False}

    def redraw(ax_trigger):
        if _redrawing["busy"]:
            return
        _redrawing["busy"] = True
        try:
            x0, x1 = axes[0].get_xlim()
            i0, i1 = int(np.floor(x0)), int(np.ceil(x1))
            for line, ch_arr in zip(lines, channels):
                xs, ys = _minmax_decimate(ch_arr, i0, i1, args.points)
                line.set_data(xs, ys)
                ax = line.axes
                if ys.size:
                    pad = 0.05 * (ys.max() - ys.min() + 1e-9)
                    ax.set_ylim(ys.min() - pad, ys.max() + pad)
            fig.canvas.draw_idle()
        finally:
            _redrawing["busy"] = False

    axes[0].callbacks.connect("xlim_changed", redraw)
    redraw(axes[0])

    print(f"Loaded {len(channels)} channels, {n_samples:,} samples each, from {ds_dir}")
    if fs_note:
        print(f"NOTE: {fs_note}")
    print("Use the matplotlib toolbar (or scroll wheel, if mplcursors-style zoom is bound) to pan/zoom.")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
