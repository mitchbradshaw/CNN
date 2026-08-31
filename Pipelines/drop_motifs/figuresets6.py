"""
figuresets6.py
===============
Every figure for every span, then the pooled pair.

    idNNN_overlays.png     span + one overlay row per (direction, band)
    idNNN_overlay.png      the family overlay alone, larger
    idNNN_dendrogram.png   full-page tree / leaves / families
    idNNN_rose.png         fall gradients, one segment per motif

    ALL_dendrogram.png     one tree over every pure motif
    ALL_rose.png           one rose over every pure motif

Everything reads the STORE rather than an in-memory detection result, so
the figures and the persisted library provably describe the same windows.
A figure drawn from one and a library written from the other is the class
of mistake that produces a plot nobody can reproduce.
"""

import json

from Pipelines.drop_motifs.clusterfigs6 import plot_dendrogram_page, plot_rose
from Pipelines.drop_motifs.overlays6 import (plot_family_overlay,
                                             plot_span_and_overlays)
from Working.Detection.drop_motifs import motifs5


def draw_all(store_dir, out_dir, summaries, wanted, span_signal):
    rows, snippets, _ = motifs5.load_store(str(store_dir))
    by_span = {}
    for row in rows:
        by_span.setdefault(int(row["catalogue_id"]), []).append(row)
    by_id = {int(s["catalogue_id"]): s for s in summaries
             if isinstance(s.get("catalogue_id"), int)}

    index = {}
    for catalogue_id in wanted:
        span_rows = by_span.get(catalogue_id, [])
        if not span_rows:
            continue
        summary = by_id[catalogue_id]
        labels = summary.get("scale_band_labels", [])
        pure = [r for r in span_rows if int(r["is_pure"])]
        excluded = len(span_rows) - len(pure)
        stem = f"id{catalogue_id:03d}"
        entry = {"n": len(span_rows), "n_pure": len(pure),
                 "excluded": excluded, "bands": labels}

        entry["overlays"] = plot_span_and_overlays(
            span_signal[catalogue_id], summary["fs"],
            int(summary["span_offset"]), span_rows, snippets, summary,
            out_dir / f"{stem}_overlays.png", band_labels=labels)

        entry["overlay"] = plot_family_overlay(
            span_rows, snippets, summary, out_dir / f"{stem}_overlay.png",
            band_labels=labels)

        path, info = plot_dendrogram_page(
            pure, snippets, out_dir / f"{stem}_dendrogram.png",
            title=f"catalogue ID {catalogue_id} — shape families",
            excluded=excluded)
        entry["dendrogram"], entry["dendrogram_info"] = path, info

        path, info = plot_rose(
            pure, snippets, out_dir / f"{stem}_rose.png",
            title=f"catalogue ID {catalogue_id} — fall gradients",
            excluded=excluded)
        entry["rose"], entry["rose_info"] = path, info

        index[str(catalogue_id)] = entry
        print(f"      figures: {stem} ({len(pure)} pure, "
              f"{excluded} excluded, {len(labels)} band"
              f"{'s' if len(labels) != 1 else ''})", flush=True)

    pure_all = [r for r in rows if int(r["is_pure"])]
    excluded_all = len(rows) - len(pure_all)
    pooled = {"n": len(rows), "n_pure": len(pure_all), "excluded": excluded_all}

    path, info = plot_dendrogram_page(
        pure_all, snippets, out_dir / "ALL_dendrogram.png",
        title="every span — shape families across all catalogue IDs",
        excluded=excluded_all)
    pooled["dendrogram"], pooled["dendrogram_info"] = path, info

    path, info = plot_rose(
        pure_all, snippets, out_dir / "ALL_rose.png",
        title="every span — fall gradients",
        excluded=excluded_all)
    pooled["rose"], pooled["rose_info"] = path, info

    index["ALL"] = pooled
    (out_dir / "figure_index.json").write_text(
        json.dumps(index, indent=2, default=float), encoding="utf-8")
    print(f"      pooled: {len(pure_all)} pure motifs, "
          f"{excluded_all} excluded", flush=True)
    return index
