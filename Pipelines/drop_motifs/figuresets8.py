"""
figuresets8.py
===============
Every figure for every span, then the pooled pair.

    idNNN_overlays.png     span on top, one centred row per family
    idNNN_overlay.png      the family panels alone, larger
    idNNN_dendrogram.png   A4, ranked tree, families on it at the cut
    idNNN_rose.png         gradients; falls below the axis, rises above
    ALL_dendrogram.png     one tree over every pure motif, two cuts drawn
    ALL_rose.png           one rose over every pure motif, coloured by span

Three settings distinguish this from `figuresets73`:

  `orient_rises_as_drops=False`   a rise is drawn as a rise
  `locker=style8.span_locked_aspect`   the height cap falls as the true
                                  ratio gets further out of reach
  the pooled pair is drawn again  (7.2 and 7.3 had dropped it)
"""

import json

from Pipelines.drop_motifs import style8
from Pipelines.drop_motifs.clusterfigs73 import plot_dendrogram_page
from Pipelines.drop_motifs.clusterfigs8 import (plot_pooled_dendrogram_page,
                                                plot_rose)
from Pipelines.drop_motifs.overlays72 import span_aspect
from Pipelines.drop_motifs.overlays73 import (plot_family_overlay,
                                              plot_span_and_overlays)
from Working.Detection.drop_motifs import motifs5

ORIENT = dict(orient_rises_as_drops=False)


def draw_all(store_dir, out_dir, summaries, wanted, span_signal):
    rows, snippets, _ = motifs5.load_store(str(store_dir))
    by_span = {}
    for row in rows:
        by_span.setdefault(int(row["catalogue_id"]), []).append(row)
    by_id = {int(s["catalogue_id"]): s for s in summaries
             if isinstance(s.get("catalogue_id"), int)}

    index, pure_all = {}, []
    for catalogue_id in wanted:
        span_rows = by_span.get(catalogue_id, [])
        if not span_rows:
            continue
        summary = by_id[catalogue_id]
        labels = summary.get("scale_band_labels", [])
        pure = [r for r in span_rows if int(r["is_pure"])]
        excluded = len(span_rows) - len(pure)
        pure_all.extend(pure)
        stem = f"id{catalogue_id:03d}"
        x = span_signal[catalogue_id]
        fs = summary["fs"]
        entry = {"n": len(span_rows), "n_pure": len(pure),
                 "excluded": excluded, "bands": labels,
                 "n_rises": sum(1 for r in span_rows
                                if int(r.get("signal_sign", 1)) < 0)}

        entry["overlays"] = plot_span_and_overlays(
            x, fs, int(summary["span_offset"]), span_rows, snippets, summary,
            out_dir / f"{stem}_overlays.png", band_labels=labels,
            locker=style8.span_locked_aspect, **ORIENT)

        entry["overlay"] = plot_family_overlay(
            x, fs, span_rows, snippets, summary,
            out_dir / f"{stem}_overlay.png", band_labels=labels,
            locker=style8.span_locked_aspect, **ORIENT)

        aspect, true_ratio, compression = span_aspect(
            x, fs, pure or span_rows, locker=style8.span_locked_aspect)

        path, info = plot_dendrogram_page(
            pure, snippets, out_dir / f"{stem}_dendrogram.png",
            title=f"catalogue ID {catalogue_id} — shape families",
            excluded=excluded, span_aspect=aspect, true_ratio=true_ratio,
            compression=compression, **ORIENT)
        entry["dendrogram"], entry["dendrogram_info"] = path, info

        path, info = plot_rose(
            pure, snippets, out_dir / f"{stem}_rose.png",
            title=f"catalogue ID {catalogue_id} — gradients",
            excluded=excluded)
        entry["rose"], entry["rose_info"] = path, info

        index[str(catalogue_id)] = entry
        print(f"      figures: {stem} ({len(pure)} pure, {excluded} excluded, "
              f"{entry['n_rises']} rises, {len(labels)} band"
              f"{'s' if len(labels) != 1 else ''}, shape {true_ratio:.1f}:1"
              + (f" compressed {compression:.1f}x" if compression > 1.001
                 else " exact") + ")", flush=True)

    if len(pure_all) >= 6:
        excluded_all = len(rows) - len(pure_all)
        pooled = {"n": len(rows), "n_pure": len(pure_all),
                  "excluded": excluded_all}

        path, info = plot_pooled_dendrogram_page(
            pure_all, snippets, out_dir / "ALL_dendrogram.png",
            title="every span — pooled shape families",
            excluded=excluded_all)
        pooled["dendrogram"], pooled["dendrogram_info"] = path, info

        path, info = plot_rose(
            pure_all, snippets, out_dir / "ALL_rose.png",
            title="every span — pooled gradients",
            excluded=excluded_all, colour_by="span")
        pooled["rose"], pooled["rose_info"] = path, info

        index["ALL"] = pooled
        print(f"      pooled: {len(pure_all)} pure motifs over "
              f"{len(index) - 1} spans", flush=True)

    (out_dir / "figure_index.json").write_text(
        json.dumps(index, indent=2, default=float), encoding="utf-8")
    return index
