"""
run_drop10_casestudies.py
==========================
Task 3. The v3 figure triple - pipeline, clustering, fall angle - for a
small, deliberately unalike selection from every corpus, plus the rate
comparison.

    python Pipelines/drop_motifs/run_drop10_casestudies.py
    python Pipelines/drop_motifs/run_drop10_casestudies.py --corpora oyster
    python Pipelines/drop_motifs/run_drop10_casestudies.py --only-rate

The selection, and why each one is in it
----------------------------------------
    reishi_10hz   CH1 win36, CH2 win33, CH4 win05 - the three v3 used, for
                  continuity with `example_case_studies_v3`
    oyster        ID 3  long falls, 86-236 s, a single family
                  ID 29 two duration-separated families in one span
                  ID 22 two time scales at once - the case a single
                        derived period cannot serve
    sp385         ID 385, the whole recording
    reishi_1hz    one window matching one of the reishi three, drawn
                  beside its 10 Hz counterpart

RATE_COMPARISON.png is the clearest statement in the run of what the
sampling rate does to a waveform: the SAME physical events, at 10 Hz and
at 1 Hz, on one page.

Selection is BY SAMPLE RANGE everywhere. See `select10` - `window_index`
is not a selector and using it undercounted every window in v2.
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from matplotlib import pyplot as plt  # noqa: E402

from Pipelines.drop_motifs import (casestudy9, corpora10, passes9,  # noqa: E402
                                   select10, spans5, style10, tree10)
from Working.Detection.drop_motifs import motifs5  # noqa: E402

OUT = _Path("Plots") / "drop_motifs10"
DB = os.path.join("DATA", "db", "annotations.sqlite")

REISHI_WINDOWS = ((1, 36), (2, 33), (4, 5))
OYSTER_SPANS = (3, 29, 22)
RATE_WINDOW = (1, 36)          # the pair drawn on RATE_COMPARISON.png


def open_db(path=DB):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _as_int(value, default=-1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _family_map(rows, snippets):
    """`{event_id: family}` from the pooled tree, so a case study's colours
    mean the same thing they mean on `ALL_dendrogram.png`."""
    tree = tree10.build(rows, snippets)
    if tree is None:
        return {}
    return {r["event_id"]: int(lab)
            for r, lab in zip(tree["rows"], tree["coarse"])}


def _triple(kept, snippets, replay, x_channel, out_dir, stem, label,
            family_of, log=print):
    entry = {"n_raw": len(replay["rows"]), "n_kept": len(kept),
             "kept": [{"onset_idx": int(r["onset_idx"]),
                       "onset_s": int(r["onset_idx"]) / float(r["fs"]),
                       "depth_mv": abs(float(r["drop_depth_mv"])),
                       "n_samples_in_fall": int(r["n_samples_in_fall"]),
                       # Span-framed corpora have no window, and the
                       # store writes that as an empty CSV cell rather
                       # than as a number.
                       "stored_window": _as_int(r.get("window_index"), -1)}
                      for r in kept]}
    path, info = casestudy9.plot_pipeline(
        replay, x_channel, out_dir / f"{stem}_01_pipeline.png",
        title=f"drop_motifs10 - {label}", family_of=family_of,
        kept_ids={r["event_id"] for r in kept})
    entry["pipeline"] = {"path": path, **(info or {})}
    log(f"    -> {path}")

    if len(kept) >= 3:
        path, info = casestudy9.plot_clustering(
            kept, snippets, out_dir / f"{stem}_02_clustering.png",
            title=f"{stem} - how the clustering measures these "
                  f"{len(kept)} motifs", family_of=family_of)
        entry["clustering"] = {"path": path, **(info or {})}
        log(f"    -> {path}")
    else:
        log(f"    ({len(kept)} motifs; clustering panel skipped)")

    path, info = casestudy9.plot_fall_angle(
        kept, snippets, out_dir / f"{stem}_03_fall_angle.png",
        title=f"{stem} - how a fall becomes an angle, and where the depth "
              "is measured")
    entry["fall_angle"] = {"path": path, **(info or {})}
    log(f"    -> {path}")
    return entry


def do_sliding(conn, rows, snippets, family_of, corpus, windows, out_dir,
               decimate=False, log=print):
    """The Fig2A corpora - one case study per window, selected by range."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    for channel, window in windows:
        catalogue_id = corpora10.FIG2A_CATALOGUE_BASE + channel
        rec = conn.execute(
            "SELECT * FROM recordings WHERE source_file = ? AND channel = ?",
            (corpora10.FIG2A_SOURCE, channel)).fetchone()
        if rec is None:
            log(f"  ! no recording for CH{channel}")
            continue
        x = np.asarray(np.load(rec["npy_path"], mmap_mode="r"), dtype=float)
        fs = float(rec["fs"])
        if decimate:
            x, fs = corpora10.decimate_to(x, fs, target_fs=1.0,
                                          factor=corpora10.DECIMATION_FACTOR)
        start, end = passes9.window_bounds(len(x), fs, passes9.DEFAULT_WINDOW_S,
                                           passes9.DEFAULT_OVERLAP)[window]

        kept = sorted(select10.in_sample_range(
            [r for r in rows
             if r["corpus"] == corpus and int(r["channel"]) == channel],
            start, end), key=lambda r: int(r["onset_idx"]))
        if not kept:
            log(f"  ! {corpus} CH{channel} win{window:02d} holds no motifs")
            continue

        stem = f"CH{channel}_win{window:02d}"
        log(f"\n  === {corpus} {stem}: {start / fs:.0f}-{end / fs:.0f} s "
            f"-> {len(kept)} motifs ===")
        replay = casestudy9.replay_window(
            x, fs, start, end, catalogue_id=catalogue_id,
            recording_id=int(rec["id"]),
            source_file=os.path.basename(rec["npy_path"]),
            channel=channel, span_key=f"id{catalogue_id:03d}",
            span_label=f"{corpora10.FIG2A_SOURCE} CH{channel}")
        index[stem] = _triple(
            kept, snippets, replay, x, out_dir, stem,
            f"{corpus} CH{channel}, {start / fs:.0f}-{end / fs:.0f} s "
            f"@ {fs:g} Hz", family_of, log=log)
        index[stem].update(channel=channel, window=window, fs=fs,
                           seconds=[start / fs, end / fs])
    return index


def do_spans(conn, rows, snippets, family_of, corpus, span_ids, out_dir,
             log=print):
    """The catalogue corpora - one case study per span, passed whole."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    for catalogue_id, spec in corpora10.catalogue_spans(span_ids):
        rec = conn.execute("SELECT * FROM recordings WHERE id = ?",
                           (spec["recording"],)).fetchone()
        x, offset = spans5.load_span(rec, spec["span"])
        fs = float(rec["fs"])
        kept = sorted(select10.in_sample_range(
            [r for r in rows
             if r["corpus"] == corpus
             and int(r["catalogue_id"]) == catalogue_id],
            offset, offset + len(x)), key=lambda r: int(r["onset_idx"]))
        if not kept:
            log(f"  ! id{catalogue_id} holds no motifs")
            continue

        stem = f"id{catalogue_id:03d}"
        log(f"\n  === {corpus} {stem}: {len(x)} samples @ {fs:g} Hz "
            f"-> {len(kept)} motifs ===")
        replay = casestudy9.replay_window(
            x, fs, 0, len(x), catalogue_id=catalogue_id,
            recording_id=int(rec["id"]),
            source_file=os.path.basename(rec["npy_path"]),
            channel=int(rec["channel"]), span_key=stem,
            span_label=f"catalogue ID {catalogue_id}")
        # `replay_window` indexes the channel from 0, and a span already
        # starts at `offset` in the recording, so the rows it returns are
        # in SPAN coordinates. The store's rows are absolute. Only the
        # store's rows are drawn on figures 2 and 3, so the two never mix.
        index[stem] = _triple(
            kept, snippets, replay, x, out_dir, stem,
            f"catalogue ID {catalogue_id} ({spec.get('expect')}), "
            f"{len(x)} samples @ {fs:g} Hz", family_of, log=log)
        index[stem].update(catalogue_id=catalogue_id, fs=fs,
                           annotated_n=spec.get("annotated_n"),
                           note=spec.get("note"))
    return index


def rate_comparison(conn, rows, snippets, out_path, *, channel, window,
                    log=print):
    """The same physical events at 10 Hz and at 1 Hz, on one page.

    The clearest possible statement of what the sampling rate does to a
    waveform, and the figure the whole confound control exists to make
    legible. Left column 10 Hz, right column 1 Hz, the same seconds on
    both, and the motifs each arm actually detected marked on each.
    """
    style10.apply_style()
    rec = conn.execute(
        "SELECT * FROM recordings WHERE source_file = ? AND channel = ?",
        (corpora10.FIG2A_SOURCE, channel)).fetchone()
    x10 = np.asarray(np.load(rec["npy_path"], mmap_mode="r"), dtype=float)
    x1, fs1 = corpora10.decimate_to(x10, 10.0, target_fs=1.0,
                                    factor=corpora10.DECIMATION_FACTOR)

    start10, end10 = passes9.window_bounds(
        len(x10), 10.0, passes9.DEFAULT_WINDOW_S,
        passes9.DEFAULT_OVERLAP)[window]
    start1, end1 = passes9.window_bounds(
        len(x1), fs1, passes9.DEFAULT_WINDOW_S,
        passes9.DEFAULT_OVERLAP)[window]

    arms = [
        ("reishi_10hz", x10, 10.0, start10, end10),
        ("reishi_1hz", x1, fs1, start1, end1),
    ]
    fig, axes = plt.subplots(3, 2, figsize=(11.7, 8.6), squeeze=False)
    info = {"channel": channel, "window": window, "arms": {}}

    for col, (corpus, x, fs, start, end) in enumerate(arms):
        kept = sorted(select10.in_sample_range(
            [r for r in rows
             if r["corpus"] == corpus and int(r["channel"]) == channel],
            start, end), key=lambda r: int(r["onset_idx"]))
        t = np.arange(start, end) / fs
        seconds = [start / fs, end / fs]

        ax = axes[0][col]
        ax.plot(t, x[start:end] * 1000.0, color=style10.CORPUS_COLOUR[corpus],
                lw=style10.style7.LW_TRACE)
        ax.set_title(f"{corpus}  -  {end - start} samples of the same "
                     f"{seconds[1] - seconds[0]:.0f} s", fontsize=10)
        ax.set_ylabel("mV")
        for row in kept:
            ax.axvline(int(row["onset_idx"]) / fs,
                       color=style10.style7.RULE_COLOUR, lw=0.7, alpha=0.55)
        style10.readable_grey(fig, ax)

        # the same trace, sample markers visible
        ax = axes[1][col]
        mid = start + (end - start) // 2
        lo, hi = mid - int(round(5 * fs)), mid + int(round(5 * fs))
        ax.plot(np.arange(lo, hi) / fs, x[lo:hi] * 1000.0,
                color=style10.CORPUS_COLOUR[corpus],
                marker="o", markersize=2.6, lw=style10.style7.LW_TRACE)
        ax.set_title(f"10 s of it, every sample drawn  "
                     f"({hi - lo} samples)", fontsize=9)
        ax.set_ylabel("mV")
        style10.readable_grey(fig, ax)

        # the detected events' own samples-per-fall
        ax = axes[2][col]
        samples = [int(r["n_samples_in_fall"]) for r in kept]
        if samples:
            ax.hist(samples, bins=range(1, max(samples) + 2),
                    color=style10.CORPUS_COLOUR[corpus], alpha=0.8)
        ax.set_xlabel("samples in the fall")
        ax.set_ylabel("events")
        ax.set_title(f"{len(kept)} motifs detected here; median "
                     f"{int(np.median(samples)) if samples else 0} samples "
                     f"per fall", fontsize=9)
        style10.readable_grey(fig, ax)

        info["arms"][corpus] = {
            "fs": fs, "seconds": seconds,
            "n_samples_in_window": int(end - start),
            "n_motifs": len(kept),
            "median_samples_in_fall": (float(np.median(samples))
                                       if samples else None),
            "onsets_s": [int(r["onset_idx"]) / fs for r in kept],
            "depths_mv": [abs(float(r["drop_depth_mv"])) for r in kept],
        }

    fig.suptitle(
        f"RATE COMPARISON - Fig2A CH{channel}, window {window}: the same "
        f"physical events at 10 Hz and at 1 Hz\n"
        "A feature vector is 200 points resampled from the event's own "
        "samples. This is what the resample is given.",
        fontsize=11)
    fig.subplots_adjust(top=0.86, hspace=0.48, wspace=0.22)
    fig.savefig(str(out_path), dpi=200, facecolor="white")
    plt.close(fig)
    log(f"    -> {out_path}")
    return str(out_path), info


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--store", default=str(OUT / "motifs"))
    parser.add_argument("--out-dir", default=str(OUT / "case_studies"))
    parser.add_argument("--corpora", nargs="*", default=list(corpora10.CORPORA))
    parser.add_argument("--only-rate", action="store_true")
    args = parser.parse_args(argv)

    conn = open_db(args.db)
    out = _Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows, snippets, _ = motifs5.load_store(args.store)
    print(f"store: {len(rows)} motifs", flush=True)

    index = {}
    if not args.only_rate:
        family_of = _family_map(rows, snippets)
        print(f"pooled families: {len(set(family_of.values()))}", flush=True)

        if corpora10.CORPUS_REISHI_10HZ in args.corpora:
            print("\n[reishi_10hz]", flush=True)
            index["reishi_10hz"] = do_sliding(
                conn, rows, snippets, family_of, corpora10.CORPUS_REISHI_10HZ,
                REISHI_WINDOWS, out / "reishi_10hz")
        if corpora10.CORPUS_REISHI_1HZ in args.corpora:
            print("\n[reishi_1hz]", flush=True)
            index["reishi_1hz"] = do_sliding(
                conn, rows, snippets, family_of, corpora10.CORPUS_REISHI_1HZ,
                (RATE_WINDOW,), out / "reishi_1hz", decimate=True)
        if corpora10.CORPUS_OYSTER in args.corpora:
            print("\n[oyster]", flush=True)
            index["oyster"] = do_spans(
                conn, rows, snippets, family_of, corpora10.CORPUS_OYSTER,
                OYSTER_SPANS, out / "oyster")
        if corpora10.CORPUS_385 in args.corpora:
            print("\n[sp385]", flush=True)
            index["sp385"] = do_spans(
                conn, rows, snippets, family_of, corpora10.CORPUS_385,
                corpora10.SP385_SPAN_IDS, out / "sp385")

    print("\n[RATE_COMPARISON]", flush=True)
    path, info = rate_comparison(conn, rows, snippets,
                                 out / "RATE_COMPARISON.png",
                                 channel=RATE_WINDOW[0], window=RATE_WINDOW[1])
    index["rate_comparison"] = {"path": path, **info}
    with open(out / "RATE_COMPARISON.json", "w", encoding="utf-8") as handle:
        json.dump(info, handle, indent=1, default=str)

    with open(out / "case_study_index.json", "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=1, default=str)
    print(f"\n-> {out / 'case_study_index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
