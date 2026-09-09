"""
scan_fig2a_motifs.py
=====================
An interactive scanner for a drop_motifs store: one channel on screen at a
time, every detected motif marked on it, and any single motif zoomable.

    python Pipelines/drop_motifs/scan_fig2a_motifs.py

    python Pipelines/drop_motifs/scan_fig2a_motifs.py --store Plots/drop_motifs8/motifs
    python Pipelines/drop_motifs/scan_fig2a_motifs.py --pure-only
    python Pipelines/drop_motifs/scan_fig2a_motifs.py --start 902

Keys
----
    right / left    next / previous CHANNEL
    n / p           next / previous MOTIF on this channel
    a               back to the whole channel (clears the motif zoom)
    d               drops only / rises only / both  (cycles)
    u               show impure motifs too (toggles)
    s               save the current view to a PNG beside the store
    q               quit

Reading the top axis
--------------------
The whole channel, with a tick under every motif onset - **coloured by
scale band, exactly the hues the overlay figures use**, so a family you
picked out of `idNNN_overlays.png` is findable here by colour. Drops point
down, rises point up. Impure motifs are hollow when shown at all.

The bottom axis is the selected motif in context: the detrended trace the
detector actually decided on, the raw trace behind it, and the onset and
trough it found. The window is the stored snippet, so it is the same
extent the overlay figures drew.

Why this is not a Panel surface
-------------------------------
It is a scanning tool for one person at a terminal, not part of the app.
Matplotlib's own event loop is the whole dependency, which is already a
hard dependency of every figure in this package. Nothing under `UI/` is
involved and nothing here is imported by the pipeline.
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import matplotlib.pyplot as plt
import numpy as np

from Working.Detection.drop_motifs import motifs5

DEFAULT_STORE = os.path.join("Plots", "drop_motifs8_fig2a", "motifs")
DEFAULT_DB = os.path.join("DATA", "db", "annotations.sqlite")

# The overlay figures give each scale band its own hue; these are the same
# families in the same order, so a band picked out of idNNN_overlays.png is
# the same colour here.
BAND_COLOURS = ["#2e8b57", "#1f6fb2", "#6a4c93", "#3aa8a0",
                "#3b4cc0", "#b5651d", "#8b2e5a", "#556b2f"]

DIRECTION_MODES = ("both", "drops", "rises")


def load_signals(store_rows, db_path):
    """`{catalogue_id: (samples, fs, label)}` for every span in the store.

    The store carries `recording_id`, not the samples; the samples are read
    back off disk through the `recordings` row so this stays honest about
    where the signal came from rather than caching a second copy.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    wanted = {}
    for row in store_rows:
        wanted.setdefault(int(row["catalogue_id"]), int(row["recording_id"]))

    signals = {}
    for catalogue_id, recording_id in sorted(wanted.items()):
        rec = conn.execute("SELECT * FROM recordings WHERE id = ?",
                           (recording_id,)).fetchone()
        if rec is None:
            print(f"  ! no recording {recording_id} for id{catalogue_id}; "
                  "skipping", file=sys.stderr)
            continue
        x = np.asarray(np.load(rec["npy_path"], mmap_mode="r"), dtype=float)
        signals[catalogue_id] = (
            x * 1000.0,  # the store is in mV; match it.
            float(rec["fs"]),
            f"{rec['source_file']} CH{int(rec['channel'])}",
        )
    conn.close()
    return signals


class Scanner:
    def __init__(self, rows, snippets, signals, out_dir, pure_only=False):
        self.snippets = snippets
        self.signals = signals
        self.out_dir = _Path(out_dir)
        self.pure_only = pure_only
        self.show_impure = not pure_only
        self.direction = "both"

        self.by_span = {}
        for row in rows:
            self.by_span.setdefault(int(row["catalogue_id"]), []).append(row)
        for span_rows in self.by_span.values():
            span_rows.sort(key=lambda r: int(r["onset_idx"]))

        self.spans = [s for s in sorted(self.by_span) if s in signals]
        if not self.spans:
            raise SystemExit("no span in the store has a readable signal.")
        self.span_i = 0
        self.motif_i = None

        self.fig, (self.ax_span, self.ax_zoom) = plt.subplots(
            2, 1, figsize=(15, 8.5),
            gridspec_kw=dict(height_ratios=[2, 1], hspace=0.32))
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.draw()

    # -- what is currently visible -----------------------------------------

    @property
    def span(self):
        return self.spans[self.span_i]

    def visible(self):
        """The motifs on this channel that pass the direction/purity filters."""
        out = []
        for row in self.by_span[self.span]:
            if not int(row["is_pure"]) and not self.show_impure:
                continue
            sign = 1 if float(row.get("signal_sign", 1)) > 0 else -1
            if self.direction == "drops" and sign < 0:
                continue
            if self.direction == "rises" and sign > 0:
                continue
            out.append(row)
        return out

    # -- drawing ------------------------------------------------------------

    def draw(self):
        self.ax_span.clear()
        self.ax_zoom.clear()
        x, fs, label = self.signals[self.span]
        rows = self.visible()
        t = np.arange(len(x)) / fs

        self.ax_span.plot(t, x, lw=0.6, color="#333333", zorder=1)
        span_lo, span_hi = float(np.min(x)), float(np.max(x))
        pad = 0.08 * (span_hi - span_lo or 1.0)
        tick = span_lo - pad * 0.35

        for row in rows:
            onset = int(row["onset_idx"])
            if onset >= len(t):
                continue
            band = int(float(row.get("scale_band", 0) or 0))
            colour = BAND_COLOURS[band % len(BAND_COLOURS)]
            up = float(row.get("signal_sign", 1)) > 0
            pure = bool(int(row["is_pure"]))
            self.ax_span.plot(
                [t[onset]], [tick], marker="v" if up else "^",
                markersize=5, color=colour if pure else "none",
                markeredgecolor=colour, markeredgewidth=0.9, zorder=3)

        if self.motif_i is not None and rows:
            row = rows[self.motif_i]
            onset = int(row["onset_idx"])
            if onset < len(t):
                self.ax_span.axvline(t[onset], color="#d62728", lw=1.1,
                                     alpha=0.85, zorder=4)

        self.ax_span.set_ylim(span_lo - pad, span_hi + pad)
        self.ax_span.set_xlim(t[0], t[-1])
        self.ax_span.set_xlabel("time in recording (s)")
        self.ax_span.set_ylabel("amplitude (mV, raw)")

        n_all = len(self.by_span[self.span])
        n_pure = sum(int(r["is_pure"]) for r in self.by_span[self.span])
        n_rise = sum(1 for r in self.by_span[self.span]
                     if float(r.get("signal_sign", 1)) < 0)
        self.ax_span.set_title(
            f"id{self.span}  —  {label}   "
            f"[channel {self.span_i + 1} of {len(self.spans)}]\n"
            f"{n_all} motifs, {n_pure} pure, {n_rise} rises   ·   "
            f"showing {len(rows)} ({self.direction}"
            f"{', pure only' if not self.show_impure else ''})   ·   "
            f"{len(x)} samples at {fs:g} Hz = {len(x) / fs:.1f} s",
            fontsize=10)

        self.draw_zoom(rows)
        self.fig.canvas.draw_idle()

    def draw_zoom(self, rows):
        if self.motif_i is None or not rows:
            self.ax_zoom.text(
                0.5, 0.5,
                "n / p  select a motif      ← →  change channel\n"
                "d  direction     u  impure     a  whole channel     "
                "s  save     q  quit",
                ha="center", va="center", fontsize=11, color="#555555",
                transform=self.ax_zoom.transAxes)
            self.ax_zoom.set_xticks([])
            self.ax_zoom.set_yticks([])
            return

        row = rows[self.motif_i]
        snippet = self.snippets.get(row["event_id"])
        if snippet is None:
            self.ax_zoom.text(0.5, 0.5, f"no snippet for {row['event_id']}",
                              ha="center", va="center",
                              transform=self.ax_zoom.transAxes)
            return

        raw = np.asarray(snippet["raw_mv"], dtype=float)
        det = np.asarray(snippet["detrended_mv"], dtype=float)
        band = int(float(row.get("scale_band", 0) or 0))
        colour = BAND_COLOURS[band % len(BAND_COLOURS)]
        fs = float(row["fs"])

        # `t_s` is ABSOLUTE time in the recording (`motifs5` builds it as
        # `(arange(start, end) + span_offset) / fs`), and so is `onset_idx`.
        # The axis here is time FROM ONSET, so the onset time comes off both.
        t_rel = np.asarray(snippet["t_s"], dtype=float) - int(row["onset_idx"]) / fs

        self.ax_zoom.plot(t_rel, raw - np.median(raw), lw=0.9, color="#999999",
                          label="raw (median removed)")
        self.ax_zoom.plot(t_rel, det, lw=1.6, color=colour, label="detrended")
        self.ax_zoom.axvline(0.0, color="#444444", ls="--", lw=0.9)

        trough_t = (int(row["trough_idx"]) - int(row["onset_idx"])) / fs
        self.ax_zoom.axvline(trough_t, color="#d62728", ls=":", lw=1.1)

        self.ax_zoom.set_xlabel("time from onset (s)")
        self.ax_zoom.set_ylabel("mV")
        self.ax_zoom.legend(fontsize=8, loc="best", frameon=False)
        self.ax_zoom.set_title(
            f"motif {self.motif_i + 1} of {len(rows)}   ·   "
            f"{row['event_id']}   ·   pass {row['pass_key']}   ·   "
            f"{'drop' if float(row.get('signal_sign', 1)) > 0 else 'rise'}"
            f"   ·   band {band}   ·   "
            f"depth {abs(float(row['drop_depth_mv'])):.3g} mV   ·   "
            f"fall {float(row['fall_duration_s']):.3g} s "
            f"({float(row['fall_duration_s']) * fs:.0f} samples)   ·   "
            f"{'PURE' if int(row['is_pure']) else 'impure'}"
            f"   ·   onset sample {int(row['onset_idx'])}",
            fontsize=9)

    # -- keys ---------------------------------------------------------------

    def on_key(self, event):
        rows = self.visible()
        key = event.key

        if key == "q":
            plt.close(self.fig)
            return
        elif key == "right":
            self.span_i = (self.span_i + 1) % len(self.spans)
            self.motif_i = None
        elif key == "left":
            self.span_i = (self.span_i - 1) % len(self.spans)
            self.motif_i = None
        elif key == "n" and rows:
            self.motif_i = 0 if self.motif_i is None else \
                (self.motif_i + 1) % len(rows)
        elif key == "p" and rows:
            self.motif_i = len(rows) - 1 if self.motif_i is None else \
                (self.motif_i - 1) % len(rows)
        elif key == "a":
            self.motif_i = None
        elif key == "d":
            i = DIRECTION_MODES.index(self.direction)
            self.direction = DIRECTION_MODES[(i + 1) % len(DIRECTION_MODES)]
            self.motif_i = None
        elif key == "u":
            if self.pure_only:
                print("  --pure-only was given; 'u' is disabled.")
                return
            self.show_impure = not self.show_impure
            self.motif_i = None
        elif key == "s":
            self.out_dir.mkdir(parents=True, exist_ok=True)
            suffix = "" if self.motif_i is None else f"_m{self.motif_i:04d}"
            path = self.out_dir / f"scan_id{self.span}{suffix}.png"
            self.fig.savefig(path, dpi=150, bbox_inches="tight")
            print(f"  saved {path}")
            return
        else:
            return

        self.draw()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--pure-only", action="store_true",
                        help="hide impure motifs and disable the 'u' toggle")
    parser.add_argument("--start", type=int, default=None,
                        help="catalogue id to open on, e.g. 902")
    parser.add_argument("--save-dir", default=None,
                        help="where 's' writes (default: beside the store)")
    args = parser.parse_args(argv)

    rows, snippets, manifest = motifs5.load_store(args.store)
    if not rows:
        raise SystemExit(f"no motifs in {args.store}")
    if args.pure_only:
        rows = [r for r in rows if int(r["is_pure"])]

    print(f"{len(rows)} motifs from {args.store} "
          f"({manifest.get('kind', 'unknown kind')})")
    signals = load_signals(rows, args.db)

    save_dir = args.save_dir or _Path(args.store).parent / "scans"
    scanner = Scanner(rows, snippets, signals, save_dir,
                      pure_only=args.pure_only)

    if args.start is not None:
        if args.start not in scanner.spans:
            raise SystemExit(f"--start {args.start} is not in "
                             f"{scanner.spans}")
        scanner.span_i = scanner.spans.index(args.start)
        scanner.draw()

    print("keys:  ← → channel   n/p motif   a whole   d direction"
          "   u impure   s save   q quit")
    plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
