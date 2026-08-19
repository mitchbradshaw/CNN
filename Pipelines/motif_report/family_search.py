"""
family_search.py
==================
Seeded, cross-channel motif search and cross-scale family comparison —
the "Motif Discovery with a seed" workflow, made repeatable and pointed at
whole channels at once.

Why this needs no matrix profile
--------------------------------
A matrix profile answers "where is every subsequence's nearest neighbour",
which is what you need to DISCOVER motifs with no prior. Searching for a
motif you already have is a different, far cheaper question: one distance
profile of one query against one series, which `stumpy.match` computes by
FFT in a few seconds even on a 2.6M-sample channel. On this machine's own
calibration a fresh whole-channel profile of M2 costs tens of hours, so a
search that insisted on one would be unusable here -- and would be wasted
work regardless, since the seed already fixes what is being looked for.

That also removes the constraint that every channel be profiled at the
same window length. A seed carries its own duration, so channels whose
stored profiles sit at 1, 34 and 50 minutes can still be searched against
each other.

Seed sources (`--seed-source`)
------------------------------
  catalogue    rows of `DATA/catalogue/signal_catalog.xlsx` -- the curated
               exemplars, and the only source carrying a SHAPE NAME
               (`Elements`: sharkfin, halfdome, crestedwave, ridge ...).
               These are what makes a result a statement about a named
               family rather than about an anonymous window.
  annotations  spans with verdict='interesting'. A large, uniform pool
               (mostly 10-minute windows from a bulk import) with no shape
               label attached, so useful as coverage, weak as taxonomy.
  family       seeds discovered by `motif_report.build_families` from a
               stored matrix profile, for channels that have one.
  manual       an explicit --seed-recording/--seed-start-h/--seed-end-h.

Cross-scale comparison (`--cross-scale`)
----------------------------------------
Whether two families at different durations are the same shape is exactly
the question `Working.distances` was written for. `scale_invariant`
resamples both to a common length before z-normalising, so a 20-minute and
a 200-minute sharkfin can register as the same shape; `native_length`
is the control that refuses to reconcile the duration difference. Reporting
both is the point -- a pair that is close under the first and far under the
second is scale-invariantly similar, which is a finding, not an artifact.

Distances are divided by sqrt(n) so they read as RMS z-score difference per
sample and stay comparable across lengths, the same convention
`motif_report` uses for its `--max-distance-norm`.

Examples
--------
    # every catalogue sharkfin, searched across M2_aug CH0, CH2, CH13
    python Pipelines/motif_report/family_search.py \
        --seed-source catalogue --element sharkfin \
        --targets 1,3,14 --out-dir Plots/family_search/sharkfin

    # families discovered from CH0's stored 10-min profile, searched everywhere
    python Pipelines/motif_report/family_search.py \
        --seed-source family --seed-recording 33 --window-min 10 \
        --targets 33,35,46 --out-dir Plots/family_search/ch0_families

    # do the searches, then ask which of the resulting families are the
    # same shape at a different scale
    python Pipelines/motif_report/family_search.py ... --cross-scale
"""

import argparse
import csv
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
from Working.distances import (
    DISTANCE_NATIVE_LENGTH,
    DISTANCE_SCALE_INVARIANT,
    native_length_distance,
    scale_invariant_distance,
)

from Pipelines.motif_report.motif_report import (
    CYCLE_PALETTE,
    SEED_COLOR,
    _apply_report_style,
    build_families,
    load_scale,
    overlay_limits,
    resolve_threshold,
    time_axis,
)


CATALOGUE_PATH = os.path.join("DATA", "catalogue", "signal_catalog.xlsx")

# The catalogue's DATASET column names a recording family, not a file. Both
# M2 sets exist in `recordings` and they are NOT the same data (a window of
# one does not match anywhere in the other), so the mapping has to be
# explicit rather than a prefix guess.
DATASET_TO_SOURCE_FILE = {
    "M2": "M2_concat_fs1.mat",
    "M2_aug": "M2_aug_concat_fs1.mat",
    "M4_aug": "M4_aug_concat_fs1.mat",
}

# Same convention as motif_report: cutoff in units of sqrt(m), so it is
# comparable across seed durations. Looser than the unsupervised default
# because a seed is a hand-picked exemplar rather than the tightest pair in
# the channel -- nothing is guaranteed to sit as close to it.
DEFAULT_SEARCH_DISTANCE_NORM = 0.30

MAX_SEED_MINUTES = 240.0     # a seed longer than this is impractical to search
MAX_MATCHES_PER_CHANNEL = 40


# =========================================================================
#  Seeds
# =========================================================================

def _recording_index(conn):
    return {(r["source_file"], r["channel"]): r for r in conn.execute("SELECT * FROM recordings")}


def get_recording(conn, recording_id):
    row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
    if row is None:
        raise SystemExit(f"No recording with id={recording_id}.")
    return row


def linear_residual_fraction(values):
    """How much of a span a straight line does NOT explain: the residual's
    standard deviation after removing the best-fit line, as a fraction of
    the span's own. 0.0 means the span IS a ramp; ~1.0 means a line
    explains nothing about it.

    This exists because of a real and severe failure mode. On a channel
    with strong slow drift -- which M2 has -- the LOWEST matrix-profile
    distances belong to smooth monotonic drift ramps, not to events: after
    z-normalisation any two ramps look nearly identical, so they are each
    other's perfect nearest neighbour. Motif discovery then returns drift
    as its top families, those families match everywhere in every channel,
    and a cross-scale comparison of them reports near-zero distances. All
    of that looks like a spectacular result and means nothing.

    Measured on this repo's data the separation is wide: the top families
    from M2_concat's stored 10/34/50-minute profiles score a median 0.156,
    while the hand-curated catalogue exemplars score a median 0.819.

    Note this is a check on the SEED, not on the search. A low score does
    not mean the span is uninteresting -- a sharkfin is genuinely close to
    a ramp plus a fast fall, and scores lowish -- it means the span cannot
    discriminate, because too much of what a z-normalised distance would
    be matching on is a trend that is everywhere in the recording.
    """
    values = np.asarray(values, dtype=float).ravel()
    if len(values) < 3:
        return 0.0
    sd = values.std()
    if sd == 0:
        return 0.0
    t = np.arange(len(values), dtype=float)
    fit = np.polyval(np.polyfit(t, values, 1), t)
    return float((values - fit).std() / sd)


def make_seed(label, recording, start_idx, end_idx, *, source, elements=None):
    return {
        "label": label,
        "recording_id": recording["id"],
        "source_file": recording["source_file"],
        "channel": recording["channel"],
        "fs": float(recording["fs"]),
        "npy_path": recording["npy_path"],
        "start_idx": int(start_idx),
        "end_idx": int(end_idx),
        "m": int(end_idx) - int(start_idx),
        "source": source,
        "elements": elements or "",
    }


def load_catalogue_seeds(conn, path=CATALOGUE_PATH, *, channels=None, element=None,
                         datasets=None, max_seed_minutes=MAX_SEED_MINUTES, verbose=True):
    """Curated exemplars from the spreadsheet, resolved onto `recordings`.

    Rows whose DATASET has no mapping, whose channel is not imported, or
    whose span falls outside the recording are reported and skipped rather
    than silently dropped -- a catalogue row that cannot be located is a
    data problem worth seeing, not noise to filter.
    """
    import pandas as pd

    df = pd.read_excel(path)
    index = _recording_index(conn)
    seeds, skipped = [], []

    for _, row in df.iterrows():
        dataset = str(row.get("DATASET", "")).strip()
        source_file = DATASET_TO_SOURCE_FILE.get(dataset)
        if datasets and dataset not in datasets:
            continue
        elements = str(row.get("Elements", "") or "").strip()
        if element and element.lower() not in elements.lower():
            continue
        if source_file is None:
            skipped.append((row.get("ID_Number"), f"unmapped DATASET {dataset!r}"))
            continue
        try:
            channel = int(row["Channel"])
        except (TypeError, ValueError):
            skipped.append((row.get("ID_Number"), "no channel"))
            continue
        if channels is not None and channel not in channels:
            continue
        recording = index.get((source_file, channel))
        if recording is None:
            skipped.append((row.get("ID_Number"), f"{source_file} CH{channel} not imported"))
            continue

        fs = float(recording["fs"])
        start_idx = int(round(float(row["StartTime_h"]) * 3600.0 * fs))
        end_idx = int(round(float(row["StopTime_h"]) * 3600.0 * fs))
        if end_idx <= start_idx:
            skipped.append((row.get("ID_Number"), "non-positive span"))
            continue
        if end_idx > recording["n_samples"]:
            skipped.append((row.get("ID_Number"),
                            f"ends at {end_idx} beyond n_samples={recording['n_samples']}"))
            continue
        if (end_idx - start_idx) / fs / 60.0 > max_seed_minutes:
            skipped.append((row.get("ID_Number"),
                            f"{(end_idx - start_idx) / fs / 60.0:.0f} min exceeds "
                            f"--max-seed-minutes={max_seed_minutes:g}"))
            continue

        seeds.append(make_seed(
            f"cat{int(row['ID_Number']):02d} {elements or 'unnamed'}",
            recording, start_idx, end_idx, source="catalogue", elements=elements))

    if verbose:
        print(f"  catalogue: {len(seeds)} usable seed(s), {len(skipped)} skipped")
        for ident, why in skipped[:12]:
            print(f"    skip id={ident}: {why}")
        if len(skipped) > 12:
            print(f"    ... {len(skipped) - 12} more")
    return seeds


def load_annotation_seeds(conn, recording_ids, *, verdict="interesting", max_seeds=12,
                          verbose=True):
    """Spans a human marked `interesting`. Spread evenly across each
    recording's list rather than taking the first N, which would otherwise
    return one contiguous clump of whatever was labelled first."""
    seeds = []
    for recording_id in recording_ids:
        recording = get_recording(conn, recording_id)
        rows = conn.execute(
            "SELECT * FROM annotations WHERE recording_id = ? AND verdict = ? "
            "AND deleted_at IS NULL ORDER BY start_idx", (recording_id, verdict)).fetchall()
        if not rows:
            continue
        take = min(max_seeds, len(rows))
        picks = np.linspace(0, len(rows) - 1, take).round().astype(int)
        for k in sorted(set(picks.tolist())):
            row = rows[k]
            seeds.append(make_seed(
                f"ann{row['id']} CH{recording['channel']:02d}",
                recording, row["start_idx"], row["end_idx"],
                source=f"annotation:{verdict}"))
    if verbose:
        print(f"  annotations({verdict}): {len(seeds)} seed(s)")
    return seeds


def load_family_seeds(conn, recording_id, window_min, *, max_distance_norm=0.10,
                      max_seeds=8, verbose=True):
    """Seeds discovered without a prior, from a stored matrix profile —
    `motif_report`'s own family walk, reused rather than reimplemented."""
    recording = get_recording(conn, recording_id)
    scale = load_scale(conn, recording, window_min, verbose=verbose)
    threshold = resolve_threshold(scale["m"], max_distance_norm=max_distance_norm)
    families, _ = build_families(conn, scale, threshold=threshold,
                                 min_separation=scale["m"], verbose=verbose)
    seeds = []
    for rank, fam in enumerate(families[:max_seeds], start=1):
        seeds.append(make_seed(
            f"fam{rank:02d} CH{recording['channel']:02d} {window_min:g}min",
            recording, fam["seed_idx"], fam["seed_idx"] + scale["m"],
            source=f"family:{window_min:g}min"))
    if verbose:
        print(f"  families: {len(seeds)} seed(s) from run over {window_min:g} min")
    return seeds


# =========================================================================
#  Search
# =========================================================================

_CHANNEL_CACHE = {}


def load_channel(npy_path):
    """Channels are re-read for every seed; a search over a dozen seeds
    would otherwise pay the same 20 MB read a dozen times."""
    if npy_path not in _CHANNEL_CACHE:
        _CHANNEL_CACHE[npy_path] = np.asarray(np.load(npy_path, mmap_mode="r"), dtype=np.float64)
    return _CHANNEL_CACHE[npy_path]


def dedupe_matches(matches, min_separation):
    """Keep the best match on each distinct event. `stumpy.match` only
    guarantees its own `m/4` exclusion zone, so without this one event
    returns as several near-identical 'occurrences' -- the same artifact
    `motif_report.enforce_separation` exists to correct."""
    kept = []
    for idx, dist in matches:
        if all(abs(idx - k) >= min_separation for k, _ in kept):
            kept.append((idx, dist))
    return kept


def search_seed(seed, target_recording, *, max_distance_norm=DEFAULT_SEARCH_DISTANCE_NORM,
                max_matches=MAX_MATCHES_PER_CHANNEL, min_separation_frac=1.0,
                exclude_self=True):
    """Every occurrence of `seed`'s waveform in one target channel.

    Returns `{"matches": [(idx, dist), ...], "threshold": float, ...}` with
    matches closest-first. The seed's own span is dropped when the target
    IS the seed's channel, so a seed does not report itself as its own
    best find.
    """
    import stumpy

    q = load_channel(seed["npy_path"])[seed["start_idx"]:seed["end_idx"]]
    target = load_channel(target_recording["npy_path"])
    m = len(q)
    threshold = round(max_distance_norm * float(np.sqrt(m)), 6)

    if m >= len(target):
        return {"matches": [], "threshold": threshold, "m": m,
                "note": f"seed ({m} samples) is longer than the target channel"}
    if not np.all(np.isfinite(q)):
        return {"matches": [], "threshold": threshold, "m": m,
                "note": "seed span contains non-finite samples"}

    same_channel = target_recording["id"] == seed["recording_id"]
    raw = stumpy.match(q, target, max_matches=None, max_distance=float(threshold))
    matches = [(int(i), float(d)) for d, i in raw]

    if exclude_self and same_channel:
        matches = [(i, d) for i, d in matches if abs(i - seed["start_idx"]) >= m]

    matches = dedupe_matches(matches, int(round(min_separation_frac * m)))[:max_matches]
    return {"matches": matches, "threshold": threshold, "m": m, "note": ""}


def cross_channel_search(conn, seed, target_ids, **kwargs):
    """One seed against many channels. Returns an ordered list of
    `(recording_row, result)` so the caller keeps the requested order."""
    out = []
    for target_id in target_ids:
        target = get_recording(conn, target_id)
        out.append((target, search_seed(seed, target, **kwargs)))
    return out


def search_rows(seed, results):
    """Flat, CSV-shaped record of one seed's search."""
    rows = []
    for target, result in results:
        for rank, (idx, dist) in enumerate(result["matches"], start=1):
            rows.append({
                "seed_label": seed["label"],
                "seed_source": seed["source"],
                "seed_elements": seed["elements"],
                "seed_recording": seed["recording_id"],
                "seed_channel": seed["channel"],
                "seed_start_h": seed["start_idx"] / seed["fs"] / 3600.0,
                "seed_len_min": seed["m"] / seed["fs"] / 60.0,
                "seed_linear_residual": seed.get("linear_residual", float("nan")),
                "target_recording": target["id"],
                "target_source_file": target["source_file"],
                "target_channel": target["channel"],
                "match_rank": rank,
                "match_idx": idx,
                "match_start_h": idx / float(target["fs"]) / 3600.0,
                "distance": dist,
                "distance_norm": dist / float(np.sqrt(result["m"])),
                "threshold": result["threshold"],
            })
    return rows


# =========================================================================
#  Cross-scale family comparison
# =========================================================================

def exemplar_waveform(seed):
    """The seed's own samples -- the family's representative shape."""
    return load_channel(seed["npy_path"])[seed["start_idx"]:seed["end_idx"]]


def cross_scale_matrix(exemplars, metric=DISTANCE_SCALE_INVARIANT):
    """Pairwise distance between family exemplars of possibly different
    durations, normalised by sqrt(n) so the number reads as RMS z-score
    difference per sample rather than growing with length.

    `scale_invariant` resamples both to a common length first, so it can
    call a short and a long instance of the same shape identical.
    `native_length` deliberately cannot, and is the control: a pair close
    under the first and far under the second differs in duration but not
    in shape.
    """
    n = len(exemplars)
    D = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = exemplars[i], exemplars[j]
            if metric == DISTANCE_SCALE_INVARIANT:
                common = max(len(a), len(b))
                d = scale_invariant_distance(a, b) / np.sqrt(common)
            else:
                common = min(len(a), len(b))
                d = native_length_distance(a, b) / np.sqrt(common)
            D[i, j] = D[j, i] = d
    return D


def cluster_order(D):
    """Average-linkage order over the distance matrix, so the heatmap's
    rows and columns put similar families next to each other. Falls back
    to the input order if scipy is unavailable or n < 3."""
    if len(D) < 3:
        return list(range(len(D))), None
    from scipy.cluster.hierarchy import dendrogram, linkage
    from scipy.spatial.distance import squareform
    Z = linkage(squareform(D, checks=False), method="average")
    order = dendrogram(Z, no_plot=True)["leaves"]
    return order, Z


# =========================================================================
#  Plots
# =========================================================================

def plot_seed_search(seed, results, *, lw_scale=1.0, font_scale=1.0, max_overlay=12,
                     figsize=None):
    """The slide's layout, generalised to several target channels at once.

    Left column, spanning full height: the seed waveform itself.
    Then one row per target channel: the whole channel with every match
    marked, and the matches overlaid z-normalised against the seed.
    """
    import matplotlib.pyplot as plt

    _apply_report_style(lw_scale, font_scale)
    k = max(len(results), 1)
    figsize = figsize or (19.0, 2.0 + 2.9 * k)
    fig = plt.figure(figsize=figsize)
    gs = fig.add_gridspec(k, 3, width_ratios=[1.05, 2.5, 1.55],
                          left=0.045, right=0.985, top=0.90, bottom=0.075,
                          wspace=0.22, hspace=0.45)

    fs = seed["fs"]
    q = exemplar_waveform(seed) * 1000.0
    t_q = np.arange(len(q)) / fs / 60.0

    ax_seed = fig.add_subplot(gs[:, 0])
    ax_seed.plot(t_q, q, color=SEED_COLOR, linewidth=2.6 * lw_scale, solid_capstyle="round")
    ax_seed.set_title(f"SEED  {seed['label']}\n"
                      f"{seed['source_file']} CH{seed['channel']:02d} @ "
                      f"{seed['start_idx'] / fs / 3600.0:.2f} h  "
                      f"({seed['m'] / fs / 60.0:.1f} min)", fontsize=10.5)
    ax_seed.set_xlabel("time within seed (minutes)")
    ax_seed.set_ylabel("amplitude (mV)")

    total = 0
    for r, (target, result) in enumerate(results):
        matches = result["matches"]
        total += len(matches)
        x = load_channel(target["npy_path"])
        t_full, t_label, t_div = time_axis(len(x), float(target["fs"]))
        x_mv = x * 1000.0
        m = result["m"]

        colours = [CYCLE_PALETTE[i % len(CYCLE_PALETTE)] for i in range(len(matches))]

        ax_sig = fig.add_subplot(gs[r, 1])
        ax_sig.plot(t_full, x_mv, linewidth=0.7 * lw_scale, color="#3b5f8a", alpha=0.8)
        lo, hi = float(x_mv.min()), float(x_mv.max())
        span = hi - lo
        width = m / float(target["fs"]) / t_div
        # A 17-minute match inside a 721-hour channel is 0.04% of the axis
        # and renders as a hairline. Widen the drawn patch to a visible
        # floor -- the marker is a locator here, not a measurement, and the
        # true extent is on the overlay panel beside it.
        draw_width = max(width, 0.006 * (t_full[-1] - t_full[0]))
        for c, (idx, _d) in zip(colours, matches):
            t0 = idx / float(target["fs"]) / t_div
            ax_sig.add_patch(plt.Rectangle((t0 - draw_width / 2.0, lo), draw_width, span,
                                           facecolor=c, edgecolor="none", alpha=0.55))
            ax_sig.plot([t0], [hi + 0.05 * span], marker="v",
                        markersize=9 * lw_scale, color=c, markeredgewidth=0)
        same = target["id"] == seed["recording_id"]
        if same:
            t_seed = seed["start_idx"] / fs / t_div
            ax_sig.add_patch(plt.Rectangle((t_seed - draw_width / 2.0, lo), draw_width, span,
                                           facecolor=SEED_COLOR, edgecolor="none", alpha=0.85))
            ax_sig.plot([t_seed], [hi + 0.05 * span], marker="v", markersize=12 * lw_scale,
                        color=SEED_COLOR, markeredgewidth=0)
        ax_sig.set_ylim(lo - 0.03 * span, hi + 0.14 * span)
        ax_sig.set_xlim(t_full[0], t_full[-1])
        ax_sig.set_xlabel(t_label)
        ax_sig.set_ylabel("amplitude (mV)")
        note = f"  [{result['note']}]" if result.get("note") else ""
        ax_sig.set_title(f"{target['source_file']} CH{target['channel']:02d}"
                         f"{'  (seed channel)' if same else ''}   —   "
                         f"{len(matches)} match(es) at d/sqrt(m) <= "
                         f"{result['threshold'] / np.sqrt(m):.2f}{note}", fontsize=10.5)

        ax_ov = fig.add_subplot(gs[r, 2])
        stacked = []
        qz = _znorm(exemplar_waveform(seed))
        t_rel = np.linspace(0.0, seed["m"] / fs / 60.0, len(qz))
        ax_ov.plot(t_rel, qz, color=SEED_COLOR, linewidth=2.6 * lw_scale,
                   zorder=6, label="seed")
        stacked.append(qz)
        for c, (idx, dist) in list(zip(colours, matches))[:max_overlay]:
            snippet = x[idx:idx + m]
            if len(snippet) < m:
                continue
            z = _znorm(snippet)
            stacked.append(z)
            ax_ov.plot(np.linspace(0.0, m / float(target["fs"]) / 60.0, len(z)), z,
                       color=c, linewidth=1.5 * lw_scale, alpha=0.75,
                       label=f"d={dist / np.sqrt(m):.3f}")
        if stacked:
            ax_ov.set_ylim(*overlay_limits(stacked))
        ax_ov.set_xlabel("time within window (minutes)")
        ax_ov.set_ylabel("z-score")
        ax_ov.set_title("seed vs matches, z-normalised", fontsize=10.5)
        if 0 < len(matches) <= 8:
            ax_ov.legend(fontsize=7.5, loc="best", framealpha=0.85, handlelength=1.2)

    fig.suptitle(f"Seeded cross-channel search — {seed['label']}   "
                 f"({total} match(es) across {len(results)} channel(s))",
                 fontsize=13.5, y=0.975)
    return fig


def _znorm(values):
    values = np.asarray(values, dtype=np.float64)
    sd = values.std()
    return (values - values.mean()) / sd if sd > 0 else values - values.mean()


def plot_cross_scale(D, labels, lengths_min, *, metric_name="scale-invariant",
                     lw_scale=1.0, font_scale=1.0, control=None):
    """Dendrogram + reordered distance heatmap over family exemplars.

    Reading it: a dark off-diagonal block is a set of families that are the
    same shape. When `control` (the native-length matrix) is supplied, the
    third panel shows control minus scale-invariant -- large positive
    entries are exactly the pairs that are the same shape at different
    durations, which is the question this figure exists to answer.
    """
    import matplotlib.pyplot as plt

    _apply_report_style(lw_scale, font_scale)
    order, Z = cluster_order(D)
    n = len(order)
    ncols = 3 if control is not None else 2
    fig = plt.figure(figsize=(6.2 + 5.4 * ncols, max(5.0, 0.42 * n + 3.0)))
    gs = fig.add_gridspec(1, ncols, width_ratios=[1.0] + [1.35] * (ncols - 1),
                          left=0.035, right=0.965, top=0.86, bottom=0.22, wspace=0.55)

    ax_d = fig.add_subplot(gs[0, 0])
    if Z is not None:
        from scipy.cluster.hierarchy import dendrogram
        # No leaf labels here: the heatmap beside it labels the same rows in
        # the same order, and drawing both collides them in the gutter.
        dendrogram(Z, orientation="left", ax=ax_d, no_labels=True,
                   color_threshold=0.7 * float(Z[:, 2].max()))
        # `orientation="left"` places leaf 0 at the BOTTOM, while imshow puts
        # row 0 at the TOP. Without this the two panels run in opposite
        # directions and reading across them pairs the wrong families.
        ax_d.invert_yaxis()
        ax_d.set_xlabel(f"{metric_name} distance / sqrt(n)")
    else:
        ax_d.axis("off")
    ax_d.set_title("family exemplars, average linkage", fontsize=11)
    ax_d.grid(False)

    tick_labels = [f"{labels[i]}  [{lengths_min[i]:.0f}m]" for i in order]

    def _heat(ax, M, title, cmap, vmin=None, vmax=None):
        R = M[np.ix_(order, order)]
        im = ax.imshow(R, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
        ax.set_xticks(range(n), tick_labels, rotation=90, fontsize=7.5 * font_scale)
        ax.set_yticks(range(n), tick_labels, fontsize=7.5 * font_scale)
        ax.set_title(title, fontsize=11)
        ax.grid(False)
        fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
        return R

    _heat(fig.add_subplot(gs[0, 1]), D,
          f"{metric_name} distance / sqrt(n)\n(dark = same shape)", "viridis_r")

    if control is not None:
        diff = control - D
        lim = float(np.abs(diff).max()) or 1.0
        _heat(fig.add_subplot(gs[0, 2]), diff,
              "native-length minus scale-invariant\n(bright = same shape, different duration)",
              "RdBu_r", vmin=-lim, vmax=lim)

    fig.suptitle("Cross-scale family comparison (Working/distances.py)", fontsize=13.5, y=0.965)
    return fig


# =========================================================================
#  CLI
# =========================================================================

def write_csv(rows, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not rows:
        return None
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _int_list(value):
    return [int(v) for v in str(value).split(",") if str(v).strip()]


def build_parser():
    p = argparse.ArgumentParser(
        description="Seeded cross-channel motif search and cross-scale family comparison.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    p.add_argument("--db", default=None)
    p.add_argument("--targets", default="1,3,14",
                   help="recording ids to search IN, comma separated")
    p.add_argument("--out-dir", default=os.path.join("Plots", "family_search"))

    s = p.add_argument_group("seeds")
    s.add_argument("--seed-source", default="catalogue",
                   choices=["catalogue", "annotations", "family", "manual"])
    s.add_argument("--element", default=None,
                   help="catalogue only: keep seeds whose Elements contains this (e.g. sharkfin)")
    s.add_argument("--datasets", default=None,
                   help="catalogue only: comma-separated DATASET values to keep")
    s.add_argument("--seed-channels", default=None,
                   help="catalogue only: comma-separated channel numbers to take seeds from")
    s.add_argument("--seed-recording", type=int, default=None,
                   help="family/manual: recording the seed comes from")
    s.add_argument("--window-min", type=float, default=10.0, help="family: profile scale")
    s.add_argument("--family-specs", default=None,
                   help="family: 'recording:window_min' pairs, comma separated "
                        "(e.g. 33:10,35:50,46:34). Lets each channel contribute families "
                        "at the scale its stored profile actually uses, which is what makes "
                        "the cross-scale comparison meaningful.")
    s.add_argument("--seed-start-h", type=float, default=None, help="manual")
    s.add_argument("--seed-end-h", type=float, default=None, help="manual")
    s.add_argument("--max-seeds", type=int, default=12)
    s.add_argument("--max-seed-minutes", type=float, default=MAX_SEED_MINUTES)
    s.add_argument("--min-linear-residual", type=float, default=0.35,
                   help="reject seeds a straight line already explains (0 disables). "
                        "Guards against a drifting channel's matrix profile returning "
                        "smooth drift ramps as its top motifs, which then match everywhere")

    f = p.add_argument_group("search")
    f.add_argument("--max-distance-norm", type=float, default=DEFAULT_SEARCH_DISTANCE_NORM,
                   help="match cutoff in units of sqrt(m)")
    f.add_argument("--max-matches", type=int, default=MAX_MATCHES_PER_CHANNEL)
    f.add_argument("--min-separation-frac", type=float, default=1.0)
    f.add_argument("--include-self", action="store_true",
                   help="do not drop the seed's own span from its own channel's matches")

    x = p.add_argument_group("cross-scale")
    x.add_argument("--cross-scale", action="store_true",
                   help="also emit the exemplar distance matrix and dendrogram")

    o = p.add_argument_group("figure")
    o.add_argument("--linewidth", type=float, default=1.0)
    o.add_argument("--font-scale", type=float, default=1.0)
    o.add_argument("--dpi", type=int, default=180)
    o.add_argument("--formats", default="png,pdf")
    o.add_argument("--no-plots", action="store_true", help="CSV only")
    return p


def filter_trivial_seeds(seeds, min_residual, *, verbose=True):
    """Drop seeds a straight line already explains. Rejected seeds are
    listed with their score rather than silently removed -- on a drifting
    channel the rejects ARE the matrix profile's top families, and that is
    the single most useful thing this run can tell you."""
    kept, dropped = [], []
    for seed in seeds:
        seed["linear_residual"] = linear_residual_fraction(exemplar_waveform(seed))
        (kept if seed["linear_residual"] >= min_residual else dropped).append(seed)
    if verbose and dropped:
        print(f"  {len(dropped)} seed(s) rejected as drift-dominated "
              f"(linear residual < {min_residual:g}):")
        for seed in sorted(dropped, key=lambda s: s["linear_residual"]):
            print(f"    {seed['linear_residual']:.3f}  {seed['label']}")
    return kept


def collect_seeds(conn, args):
    if args.seed_source == "catalogue":
        return load_catalogue_seeds(
            conn, channels=_int_list(args.seed_channels) if args.seed_channels else None,
            element=args.element,
            datasets=[d.strip() for d in args.datasets.split(",")] if args.datasets else None,
            max_seed_minutes=args.max_seed_minutes)[:args.max_seeds]
    if args.seed_source == "annotations":
        return load_annotation_seeds(conn, _int_list(args.targets), max_seeds=args.max_seeds)
    if args.seed_source == "family":
        if args.family_specs:
            specs = []
            for chunk in args.family_specs.split(","):
                recording_id, _, window = chunk.partition(":")
                if not window:
                    raise SystemExit(f"--family-specs entry {chunk!r} is not recording:window_min")
                specs.append((int(recording_id), float(window)))
        elif args.seed_recording is not None:
            specs = [(args.seed_recording, args.window_min)]
        else:
            raise SystemExit("--seed-source family needs --seed-recording or --family-specs")
        seeds = []
        for recording_id, window_min in specs:
            seeds.extend(load_family_seeds(conn, recording_id, window_min,
                                           max_seeds=args.max_seeds))
        return seeds
    if args.seed_start_h is None or args.seed_end_h is None or args.seed_recording is None:
        raise SystemExit("--seed-source manual needs --seed-recording, --seed-start-h, --seed-end-h")
    recording = get_recording(conn, args.seed_recording)
    fs = float(recording["fs"])
    return [make_seed("manual", recording, round(args.seed_start_h * 3600 * fs),
                      round(args.seed_end_h * 3600 * fs), source="manual")]


def main(argv=None):
    args = build_parser().parse_args(argv)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    target_ids = _int_list(args.targets)
    os.makedirs(args.out_dir, exist_ok=True)

    conn = init_db(args.db)
    try:
        print(f"seed source: {args.seed_source}")
        seeds = collect_seeds(conn, args)
        if args.min_linear_residual > 0:
            seeds = filter_trivial_seeds(seeds, args.min_linear_residual)
        if not seeds:
            print("No usable seeds. If everything was rejected as drift-dominated, the "
                  "channel's motifs at this scale are trend, not events -- detrend first, "
                  "or use a shorter window.")
            return 1
        targets = [get_recording(conn, t) for t in target_ids]
        print(f"targets: " + ", ".join(
            f"{t['source_file'].split('.')[0]} CH{t['channel']:02d} (id={t['id']})" for t in targets))
        print(f"{len(seeds)} seed(s) x {len(targets)} channel(s)\n")

        all_rows, exemplars, labels, lengths = [], [], [], []
        saturated_seeds = []
        for n, seed in enumerate(seeds, start=1):
            results = cross_channel_search(
                conn, seed, target_ids,
                max_distance_norm=args.max_distance_norm,
                max_matches=args.max_matches,
                min_separation_frac=args.min_separation_frac,
                exclude_self=not args.include_self)
            rows = search_rows(seed, results)
            all_rows.extend(rows)

            found = " ".join(
                f"CH{t['channel']:02d}:{len(r['matches'])}" for t, r in results)
            # A seed that saturates the cap in EVERY channel has not found a
            # family, it has found something ubiquitous -- an edge, a step, a
            # ramp. The linear-residual guard catches ramps but not edges (a
            # step is not a line, so it scores high), and this catches what
            # that misses, empirically and for free.
            saturated = all(len(r["matches"]) >= args.max_matches for _, r in results)
            if saturated:
                found += "   <- NON-DISCRIMINATING (capped everywhere)"
            print(f"  [{n:>2}/{len(seeds)}] {seed['label']:<34} "
                  f"{seed['m'] / seed['fs'] / 60.0:>7.1f} min  "
                  f"res={seed.get('linear_residual', float('nan')):.2f}   {found}")

            if saturated:
                saturated_seeds.append(seed["label"])
            exemplars.append(exemplar_waveform(seed))
            labels.append(seed["label"])
            lengths.append(seed["m"] / seed["fs"] / 60.0)

            if not args.no_plots:
                fig = plot_seed_search(seed, results, lw_scale=args.linewidth,
                                       font_scale=args.font_scale)
                stem = "search_" + "".join(
                    ch if ch.isalnum() or ch in "-_" else "_" for ch in seed["label"])
                for fmt in formats:
                    fig.savefig(os.path.join(args.out_dir, f"{stem}.{fmt}"), dpi=args.dpi)
                plt.close(fig)

        if saturated_seeds:
            print(f"\n  WARNING: {len(saturated_seeds)} seed(s) hit --max-matches in every "
                  "channel, so their match counts are lower bounds and their 'families' are "
                  "probably a ubiquitous feature (edge/step/ramp) rather than a shape:")
            for label in saturated_seeds:
                print(f"    {label}")

        csv_path = write_csv(all_rows, os.path.join(args.out_dir, "matches.csv"))
        print(f"\n{len(all_rows)} match row(s) -> {csv_path}")

        if args.cross_scale and len(exemplars) >= 2:
            print("\ncross-scale comparison over the seed exemplars ...")
            D = cross_scale_matrix(exemplars, DISTANCE_SCALE_INVARIANT)
            control = cross_scale_matrix(exemplars, DISTANCE_NATIVE_LENGTH)
            np.savetxt(os.path.join(args.out_dir, "cross_scale_distance.csv"), D,
                       delimiter=",", header=",".join(labels), comments="")
            pairs = [(D[i, j], control[i, j], i, j)
                     for i in range(len(D)) for j in range(i + 1, len(D))]
            pairs.sort()
            print("  closest pairs by scale-invariant distance:")
            for d, c, i, j in pairs[:10]:
                print(f"    {d:.3f}  (native {c:.3f})  {labels[i]} [{lengths[i]:.0f}m]"
                      f"  vs  {labels[j]} [{lengths[j]:.0f}m]")
            if not args.no_plots:
                fig = plot_cross_scale(D, labels, lengths, control=control,
                                       lw_scale=args.linewidth, font_scale=args.font_scale)
                for fmt in formats:
                    fig.savefig(os.path.join(args.out_dir, f"cross_scale.{fmt}"), dpi=args.dpi)
                plt.close(fig)
                print(f"  -> {os.path.join(args.out_dir, 'cross_scale.png')}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
