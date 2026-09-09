"""
run_refine9.py
===============
Apply `refine9` to the drop_motifs9 store and redraw the pooled figures, so
the effect of each correction is a difference between two runs rather than
an assertion.

    python Pipelines/drop_motifs/run_refine9.py
    python Pipelines/drop_motifs/run_refine9.py --min-depth-mv 0.05
    python Pipelines/drop_motifs/run_refine9.py --no-gate      # marks + dedup only

Writes `Plots/drop_motifs9_fig2a/refined_v2/`:

    motifs/              the refined store
    ALL_dendrogram.png   two cuts, coarse and fine
    ALL_families.png     the atlas, both cuts
    ALL_rose.png         the four-panel rose
    refine_report.json   exactly what each stage changed

The drop_motifs9 store it reads is left untouched, so the two are
comparable side by side and this can be re-run with different thresholds
without losing the original.
"""

import argparse
import json
import os
import sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import clusterfigs9 as cf9
from Pipelines.drop_motifs import refine9
from Working.Detection.drop_motifs import motifs5

DEFAULT_STORE = os.path.join("Plots", "drop_motifs9_fig2a", "motifs")
DEFAULT_OUT = os.path.join("Plots", "drop_motifs9_fig2a", "refined_v2")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT)
    parser.add_argument("--min-depth-mv", type=float,
                        default=refine9.MIN_DROP_DEPTH_MV)
    parser.add_argument("--max-families", type=int, default=8)
    parser.add_argument("--fine-families", type=int, default=None)
    parser.add_argument("--no-refine", action="store_true")
    parser.add_argument("--no-dedup", action="store_true")
    parser.add_argument("--no-gate", action="store_true")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args(argv)

    rows, snippets, manifest = motifs5.load_store(args.store)
    print(f"{len(rows)} motifs in {args.store}")

    rows, snippets, report = refine9.refine_store(
        rows, snippets, min_depth_mv=args.min_depth_mv,
        refine=not args.no_refine, dedup=not args.no_dedup,
        gate=not args.no_gate)

    print("\nrefinement:")
    for key in ("n_in", "onset_moved", "trough_moved", "refine_refused",
                "n_duplicates_dropped", "duplicate_reasons",
                "n_below_noise_floor", "n_out"):
        if key in report:
            print(f"  {key:<24} {report[key]}")

    out_dir = _Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    store_dir = out_dir / "motifs"
    motifs5.write_store(
        str(store_dir), rows, refine9.flatten_snippets(snippets),
        manifest_extra={
            "kind": "drop_motifs9_refined_v2",
            "detector": "detect5 + passes9 + refine9 (marks, dedup, floor)",
            "derived_from": args.store,
            "min_depth_mv": float(args.min_depth_mv),
            "refine_report": report,
            "validated_against_human": False,
        })
    print(f"\nrefined store -> {store_dir}  ({len(rows)} motifs)")

    index = {}
    if not args.no_figures and rows:
        tree = cf9.build_tree(rows, snippets, max_families=args.max_families,
                              fine_families=args.fine_families)
        if tree is None:
            print("  ! too few motifs to cluster")
        else:
            print(f"  tree: {tree['k']} coarse / {tree['fine_k']} fine "
                  f"families, cophenetic r = {tree['cophenetic']:.3f}")
            path, info = cf9.plot_dendrogram(
                rows, snippets, out_dir / "ALL_dendrogram.png",
                title="drop_motifs9 + refine9 — pooled shape families",
                tree=tree)
            index["dendrogram"] = {"path": path, **(info or {})}
            print(f"  -> {path}")

            path, info = cf9.plot_family_atlas(
                rows, snippets, out_dir / "ALL_families.png",
                title="drop_motifs9 + refine9 — every motif by shape family",
                tree=tree)
            index["atlas"] = {"path": path, **(info or {})}
            print(f"  -> {path}")

        path, info = cf9.plot_rose(
            rows, snippets, out_dir / "ALL_rose.png",
            title="drop_motifs9 + refine9 — fall gradients by channel "
                  "and drop height")
        index["rose"] = {"path": path, **(info or {})}
        print(f"  -> {path}")
        if info and "spearman_rho_depth_vs_angle" in info:
            print(f"\n  HEIGHT vs SLOPE: rho = "
                  f"{info['spearman_rho_depth_vs_angle']:+.3f}, "
                  f"n = {info['n']}")
            # ASCII here on purpose: this line goes to a Windows console
            # whose default codepage cannot encode the proportional sign.
            print(f"  CONTROL: duration ~ depth^"
                  f"{info['duration_vs_depth_exponent']:.3f}"
                  f"  (r2 = {info['duration_vs_depth_r2']:.3f})")

    (out_dir / "refine_report.json").write_text(
        json.dumps({"refine": report, "figures": index},
                   indent=2, default=float), encoding="utf-8")
    print(f"\n-> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
