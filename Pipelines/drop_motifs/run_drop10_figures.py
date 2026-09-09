"""
run_drop10_figures.py
======================
Task 4's pooled figure set, per corpus as well as pooled, and Task 5's
three result figures.

    python Pipelines/drop_motifs/run_drop10_figures.py
    python Pipelines/drop_motifs/run_drop10_figures.py --only atlas
    python Pipelines/drop_motifs/run_drop10_figures.py --no-per-corpus

ALL_atlas.png is drawn FIRST, because it is the figure the paper most
needs and the one worth having if the run has to stop early.

Every figure gets a JSON beside it carrying every number the figure
states. Task 5's figures are drawn from the JSON `run_drop10_species.py`
wrote, never recomputed here.
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

from Pipelines.drop_motifs import (corpora10, figures10,  # noqa: E402
                                   speciesfigs10, tree10)
from Working.Detection.drop_motifs import motifs5  # noqa: E402

OUT = _Path("Plots") / "drop_motifs10"

CONTROL_NOTE = (
    "Panel 3 is DETECTOR GEOMETRY, not a finding. The tangent slope is the "
    "steepest sample of a fall, and a fall's depth divided by its duration "
    "is its mean slope by definition, so depth and angle are close to "
    "arithmetically linked. drop_motifs9's nulls_v1 settled it by "
    "measurement: the observed Spearman rho of -0.866 was reproduced by a "
    "block-shuffle surrogate at a null median of -0.860, p = 0.248. Any "
    "generator that preserves the local waveform preserves the "
    "relationship, so it is a property of the measurement and not of the "
    "mycelium. Panel 4 is the control it is read against, and panel 5 asks "
    "the same measurement as a between-species question, which is the only "
    "form of it this run can add anything to."
)


def _write(path, info):
    with open(str(path).replace(".png", ".json"), "w",
              encoding="utf-8") as handle:
        json.dump(info, handle, indent=1, default=str)


def draw_set(rows, snippets, out_dir, prefix, label, only=None, log=print,
             trees_by_corpus=None):
    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tree = tree10.build(rows, snippets)
    if tree is None:
        log(f"  ! {label}: too few motifs to cluster")
        return {}
    log(f"  {label}: n={tree['n']} of {tree['n_input']}, "
        f"cophenetic r = {tree['cophenetic']:.4f}")

    index = {}
    wanted = set(only) if only else None

    def want(name):
        return wanted is None or name in wanted

    # ATLAS FIRST - see the module docstring. It takes the PER-CORPUS
    # trees, not the pooled one: "every family medoid from every corpus"
    # is the question, and a pooled coarse cut answers a different one.
    if want("atlas"):
        source = trees_by_corpus or {label: tree}
        path, info = figures10.plot_atlas(
            source, out_dir / f"{prefix}atlas.png",
            title=f"{label} - a small repertoire of relative shapes at "
                  f"wildly different absolute scales")
        if path:
            _write(path, info)
            index["atlas"] = info
            log(f"    -> {path}")

    if want("dendrogram"):
        path, info = figures10.plot_dendrogram(
            tree, out_dir / f"{prefix}dendrogram.png",
            title=f"{label} - pooled shape families, leaves by species")
        if path:
            _write(path, info)
            index["dendrogram"] = info
            log(f"    -> {path}")

    if want("families"):
        path, info = figures10.plot_families(
            tree, out_dir / f"{prefix}families.png",
            title=f"{label} - every motif by family, coarse and fine cut")
        if path:
            _write(path, info)
            index["families"] = info
            log(f"    -> {path}")

    if want("rose"):
        path, info = figures10.plot_rose(
            tree["rows"], out_dir / f"{prefix}rose.png",
            title=f"{label} - fall angle", control_note=CONTROL_NOTE,
            snippets=snippets)
        if path:
            _write(path, info)
            index["rose"] = info
            log(f"    -> {path}")
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(OUT / "motifs"))
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--no-per-corpus", action="store_true")
    parser.add_argument("--no-species-figures", action="store_true")
    args = parser.parse_args(argv)

    out = _Path(args.out_dir)
    rows, snippets, manifest = motifs5.load_store(args.store)
    print(f"store {args.store}: {len(rows)} motifs", flush=True)

    index = {"pooled": {}, "by_corpus": {}, "task5": {}}

    # The per-corpus trees are built first because the pooled atlas is
    # drawn FROM them.
    print("\nper-corpus trees", flush=True)
    trees_by_corpus = {}
    for corpus in corpora10.CORPORA:
        selected = [r for r in rows if r["corpus"] == corpus]
        if len(selected) < 3:
            print(f"  ! {corpus}: {len(selected)} motifs, skipped")
            continue
        built = tree10.build(selected, snippets)
        trees_by_corpus[corpus] = built
        if built:
            print(f"  {corpus}: n={built['n']}, "
                  f"cophenetic r = {built['cophenetic']:.4f}", flush=True)

    print("\npooled", flush=True)
    index["pooled"] = draw_set(rows, snippets, out, "ALL_",
                               "drop_motifs10, all four corpora",
                               only=args.only,
                               trees_by_corpus=trees_by_corpus)

    if not args.no_per_corpus:
        print("\nper corpus", flush=True)
        for corpus, built in trees_by_corpus.items():
            if built is None:
                continue
            selected = [r for r in rows if r["corpus"] == corpus]
            index["by_corpus"][corpus] = draw_set(
                selected, snippets, out / "by_corpus" / corpus, "ALL_",
                f"drop_motifs10, {corpus}", only=args.only,
                trees_by_corpus={corpus: built})

    if not args.no_species_figures:
        print("\nTask 5 figures", flush=True)
        for name, drawer, key in (
                ("SPECIES_vs_RESOLUTION",
                 speciesfigs10.plot_species_vs_resolution,
                 "species_vs_resolution"),
                ("DECODE_species", speciesfigs10.plot_decode_species,
                 "decode"),
                ("TRANSFER_species", speciesfigs10.plot_transfer,
                 "transfer")):
            source = out / f"{name}.json"
            if not source.exists():
                print(f"  ! {source} not found - run "
                      f"run_drop10_species.py first")
                continue
            with open(source, encoding="utf-8") as handle:
                data = json.load(handle)
            titles = {
                "SPECIES_vs_RESOLUTION":
                    "Task 5a/5b - do families mix species, or resolution?",
                "DECODE_species":
                    "Task 5c - is species recoverable from absolute scale, "
                    "from normalised shape, or from neither?",
                "TRANSFER_species":
                    "Task 5d - do shapes learned on one species describe "
                    "events in another?",
            }
            kwargs = {}
            if name == "SPECIES_vs_RESOLUTION":
                fam = out / "FAMILIES_by_species.json"
                if fam.exists():
                    with open(fam, encoding="utf-8") as handle:
                        kwargs["families"] = json.load(handle)
            path, info = drawer(data, out / f"{name}.png", title=titles[name],
                                **kwargs)
            # The figure's JSON is written beside the PNG under a distinct
            # name, so the analysis JSON it was drawn FROM is never
            # overwritten by the figure's own.
            _write(str(out / f"{name}_figure.png"), info)
            index["task5"][key] = info
            print(f"  -> {path}", flush=True)

    with open(out / "figure_index.json", "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=1, default=str)
    print(f"\n-> {out / 'figure_index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
