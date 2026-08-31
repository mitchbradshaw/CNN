"""
figuresets72.py
================
The drop_motifs7.2 figure set.

The one structural difference from `figuresets7` is that the span signal
is threaded through to every drawing call, because 7.2 derives its
millivolt-per-second from the span panel's own geometry and cannot
compute it from the motif table alone.
"""

import json

from Pipelines.drop_motifs.clusterfigs7 import plot_rose
from Pipelines.drop_motifs.clusterfigs72 import plot_dendrogram_page
from Pipelines.drop_motifs.overlays72 import (plot_family_overlay,
                                              plot_span_and_overlays,
                                              span_aspect)
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
        x = span_signal[catalogue_id]
        fs = summary["fs"]
        entry = {"n": len(span_rows), "n_pure": len(pure),
                 "excluded": excluded, "bands": labels}

        entry["overlays"] = plot_span_and_overlays(
            x, fs, int(summary["span_offset"]), span_rows, snippets, summary,
            out_dir / f"{stem}_overlays.png", band_labels=labels)

        entry["overlay"] = plot_family_overlay(
            x, fs, span_rows, snippets, summary,
            out_dir / f"{stem}_overlay.png", band_labels=labels)

        # The dendrogram is locked to the same scale the overlays use, so
        # a motif is the same shape in both figures for the same span.
        aspect, true_ratio, compression = span_aspect(x, fs,
                                                      pure or span_rows)

        path, info = plot_dendrogram_page(
            pure, snippets, out_dir / f"{stem}_dendrogram.png",
            title=f"catalogue ID {catalogue_id} — shape families",
            excluded=excluded, span_aspect=aspect, true_ratio=true_ratio,
            compression=compression)
        entry["dendrogram"], entry["dendrogram_info"] = path, info

        path, info = plot_rose(
            pure, snippets, out_dir / f"{stem}_rose.png",
            title=f"catalogue ID {catalogue_id} — fall gradients",
            excluded=excluded)
        entry["rose"], entry["rose_info"] = path, info

        index[str(catalogue_id)] = entry
        print(f"      figures: {stem} ({len(pure)} pure, {excluded} excluded, "
              f"{len(labels)} band{'s' if len(labels) != 1 else ''}, "
              f"shape {true_ratio:.1f}:1"
              + (f" compressed {compression:.1f}x" if compression > 1.001
                 else " exact") + ")", flush=True)

    (out_dir / "figure_index.json").write_text(
        json.dumps(index, indent=2, default=float), encoding="utf-8")
    return index
