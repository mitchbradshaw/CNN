"""
figuresets5.py
===============
Draws the three requested figure sets from the motif library, per span and
pooled.

    idNNN_overlays.png     span + pure/baselined and all/as-recorded overlays
    idNNN_dendrogram.png   Ward tree over that span's pure motifs
    idNNN_rose.png         fall-gradient rose over that span's pure motifs

    ALL_dendrogram.png     one tree over every pure motif from every span
    ALL_rose.png           one rose over every pure motif, coloured by span

Everything reads the STORE rather than the in-memory detection result, so
the figures and the persisted motif library provably describe the same
windows. A figure drawn from one and a library written from the other is
the class of mistake that produces a plot nobody can reproduce.
"""

import json

from Pipelines.drop_motifs.clusterfigs5 import plot_dendrogram, plot_rose
from Pipelines.drop_motifs.overlays5 import plot_span_and_overlays
from Working.Detection.drop_motifs import motifs5


def draw_all(store_dir, out_dir, span_data, summaries, wanted):
    """Every figure for every span, then the two pooled ones."""
    events, snippets, _ = motifs5.load_store(str(store_dir))
    by_span = {}
    for event in events:
        by_span.setdefault(int(event["catalogue_id"]), []).append(event)

    index = {}
    for catalogue_id in wanted:
        rows = by_span.get(catalogue_id, [])
        if not rows:
            continue
        pure = [r for r in rows if r["is_pure"]]
        excluded = len(rows) - len(pure)
        stem = f"id{catalogue_id:03d}"
        entry = {"n": len(rows), "n_pure": len(pure), "excluded": excluded}

        x, tuned, summary = span_data[catalogue_id]
        span_offset = int(summary["span_offset"])
        entry["overlays"] = plot_span_and_overlays(
            x, summary["fs"], span_offset, rows, snippets, summary,
            out_dir / f"{stem}_overlays.png")

        path, info = plot_dendrogram(
            pure, snippets, out_dir / f"{stem}_dendrogram.png",
            title=f"catalogue ID {catalogue_id} — shape families",
            excluded=excluded)
        entry["dendrogram"] = path
        entry["dendrogram_info"] = info

        path, info = plot_rose(
            pure, snippets, out_dir / f"{stem}_rose.png",
            title=f"catalogue ID {catalogue_id} — fall gradients",
            excluded=excluded)
        entry["rose"] = path
        entry["rose_info"] = info

        index[str(catalogue_id)] = entry
        print(f"      figures: {stem} "
              f"({len(pure)} pure, {excluded} excluded)", flush=True)

    # -- pooled ------------------------------------------------------------
    pure_all = [e for e in events if e["is_pure"]]
    excluded_all = len(events) - len(pure_all)
    pooled = {"n": len(events), "n_pure": len(pure_all),
              "excluded": excluded_all}

    path, info = plot_dendrogram(
        pure_all, snippets, out_dir / "ALL_dendrogram.png",
        title="every span — shape families across all catalogue IDs",
        colour_by_span=True, excluded=excluded_all)
    pooled["dendrogram"] = path
    pooled["dendrogram_info"] = info

    path, info = plot_rose(
        pure_all, snippets, out_dir / "ALL_rose.png",
        title="every span — fall gradients, coloured by catalogue ID",
        colour_by_span=True, excluded=excluded_all)
    pooled["rose"] = path
    pooled["rose_info"] = info

    index["ALL"] = pooled
    (out_dir / "figure_index.json").write_text(
        json.dumps(index, indent=2, default=float), encoding="utf-8")

    print(f"      pooled: {len(pure_all)} pure motifs, "
          f"{excluded_all} excluded", flush=True)
    return index
