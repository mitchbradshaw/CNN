"""
run_drop10_species.py
======================
Task 5, in the order the brief requires: 5b before 5a, then 5c, then 5d.

    python Pipelines/drop_motifs/run_drop10_species.py
    python Pipelines/drop_motifs/run_drop10_species.py --tasks 5b 5c
    python Pipelines/drop_motifs/run_drop10_species.py --permutations 1000

5b runs first because whether family membership tracks species is not
worth reading until it is known whether it tracks samples per event.

Writes JSON only; `run_drop10_figures.py` draws from these files, so a
figure can never state a number this run did not compute.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import corpora10, species10, tree10  # noqa: E402
from Working.Detection.drop_motifs import motifs5  # noqa: E402

OUT = _Path("Plots") / "drop_motifs10"
STORE = OUT / "motifs"


def subset(rows, corpora):
    keep = set(corpora)
    return [r for r in rows if r["corpus"] in keep]


def _tree_for(rows, snippets, label, log=print):
    tree = tree10.build(rows, snippets)
    if tree is None:
        log(f"  ! {label}: too few motifs to cluster")
        return None
    log(f"  {label}: n={tree['n']} (of {tree['n_input']}), "
        f"cophenetic r = {tree['cophenetic']:.4f}, dropped={tree['dropped']}")
    return tree


def task_5b(rows, snippets, permutations, log=print):
    """The confound control. Species against samples-per-event."""
    out = {}
    for name, corpora in (
            ("pooled_all", corpora10.CORPORA),
            ("matched_rate", corpora10.MATCHED_RATE_SUBSET),
            ("oyster_vs_sp385", corpora10.MATCHED_RATE_CLEAN_PAIR)):
        selected = subset(rows, corpora)
        tree = _tree_for(selected, snippets, name, log=log)
        if tree is None:
            continue
        block = {"n": tree["n"], "cophenetic": tree["cophenetic"],
                 "corpora": list(corpora), "dropped": tree["dropped"]}
        for cut in ("coarse", "fine"):
            block[cut] = species10.resolution_vs_species(
                tree["rows"], tree[cut], n=permutations,
                group=1 if cut == "coarse" else 3)
            v_species = block[cut]["species"]["cramers_v"]
            v_samples = block[cut]["samples_per_event"]["cramers_v"]
            log(f"    {cut:6s} V(species)={v_species:.4f} "
                f"p={block[cut]['species']['permutation_p']:.4f}   "
                f"V(samples)={v_samples:.4f} "
                f"p={block[cut]['samples_per_event']['permutation_p']:.4f}   "
                f"{'SAMPLES DOMINATES' if v_samples > v_species else 'species dominates'}")

        log("    decoding samples-per-event from the normalised shape...")
        block["decode_samples_from_shape"] = species10.decode_samples_from_shape(
            tree["features"], tree["rows"], group=5)
        d = block["decode_samples_from_shape"]
        if "balanced_accuracy" in d:
            log(f"      balanced accuracy {d['balanced_accuracy']:.3f} "
                f"(chance {d['chance']:.3f}, p={d['permutation_p']:.4f})")
        out[name] = block

    # The direct comparison the brief asks for: family composition three
    # ways, so the paper knows which pooling to quote.
    out["three_poolings"] = {}
    for name, corpora in (
            ("with_10hz_reishi", (corpora10.CORPUS_OYSTER, corpora10.CORPUS_385,
                                  corpora10.CORPUS_REISHI_10HZ)),
            ("with_1hz_reishi", corpora10.MATCHED_RATE_SUBSET),
            ("with_both", corpora10.CORPORA)):
        selected = subset(rows, corpora)
        tree = _tree_for(selected, snippets, name, log=log)
        if tree is None:
            continue
        out["three_poolings"][name] = {
            "corpora": list(corpora),
            "n": tree["n"],
            "cophenetic": tree["cophenetic"],
            "coarse": tree10.family_table(tree["rows"], tree["coarse"],
                                          "species"),
            "fine": tree10.family_table(tree["rows"], tree["fine"], "species"),
            "families": [tree10.summarise_family(tree["rows"], tree["coarse"], f)
                         for f in sorted(set(tree["coarse"].tolist()))],
        }
    return out


def task_5c(rows, snippets, permutations, log=print):
    """Species decodability. The headline."""
    out = {}
    for name, corpora in (("matched_rate", corpora10.MATCHED_RATE_SUBSET),
                          ("pooled_all", corpora10.CORPORA)):
        selected = subset(rows, corpora)
        tree = _tree_for(selected, snippets, name, log=log)
        if tree is None:
            continue
        log(f"    decoding species, {permutations} permutations per "
            f"representation...")
        started = time.time()
        block = species10.decode_species(tree["features"], tree["rows"],
                                         group=20, n_permutations=permutations)
        for rep, result in block.items():
            if "balanced_accuracy" not in result:
                log(f"      {rep:18s} {result.get('error')}")
                continue
            log(f"      {rep:18s} {result['balanced_accuracy']:.3f} "
                f"(chance {result['chance']:.3f}, null median "
                f"{result['null_median']:.3f}, p={result['permutation_p']:.4f}, "
                f"n={result['n']})")
        out[name] = {"corpora": list(corpora), "n": tree["n"],
                     "representations": block,
                     "seconds": round(time.time() - started, 1)}
    return out


def task_5a(rows, snippets, permutations, log=print):
    """Do families mix species? Read only after 5b."""
    out = {}
    for name, corpora in (
            ("pooled_all", corpora10.CORPORA),
            ("oyster_vs_sp385", corpora10.MATCHED_RATE_CLEAN_PAIR),
            ("oyster_vs_reishi_1hz", (corpora10.CORPUS_OYSTER,
                                      corpora10.CORPUS_REISHI_1HZ))):
        selected = subset(rows, corpora)
        tree = _tree_for(selected, snippets, name, log=log)
        if tree is None:
            continue
        block = {"corpora": list(corpora), "n": tree["n"],
                 "cophenetic": tree["cophenetic"]}
        for cut in ("coarse", "fine"):
            block[cut] = species10.permutation_v(
                tree[cut], [r["species"] for r in tree["rows"]],
                n=permutations, group=30)
            block[f"{cut}_families"] = [
                tree10.summarise_family(tree["rows"], tree[cut], f)
                for f in sorted(set(tree[cut].tolist()))]
            log(f"    {cut:6s} V={block[cut]['cramers_v']:.4f} "
                f"(null median {block[cut]['null_median_v']:.4f}, "
                f"p={block[cut]['permutation_p']:.4f}), "
                f"{len(block[cut]['enriched'])} cells with |z|>2")
        out[name] = block
    return out


def task_5d(rows, snippets, permutations, log=print):
    """Leave-one-species-out family transfer."""
    out = {}
    for name, corpora in (("matched_rate", corpora10.MATCHED_RATE_SUBSET),
                          ("pooled_all", corpora10.CORPORA)):
        selected = subset(rows, corpora)
        tree = _tree_for(selected, snippets, name, log=log)
        if tree is None:
            continue
        by_species, waves_by_species = {}, {}
        for row, feature, wave in zip(tree["rows"], tree["features"],
                                      tree["waveforms"]):
            by_species.setdefault(row["species"], []).append(feature)
            waves_by_species.setdefault(row["species"], []).append(wave)
        by_species = {k: np.vstack(v) for k, v in by_species.items()}

        matrix = species10.species_matrix(by_species, n=permutations)
        for a in matrix["species"]:
            line = []
            for b in matrix["species"]:
                cell = matrix["matrix"][a][b]
                line.append(f"{b}={cell.get('ari', float('nan')):.3f}")
            log(f"    {a:8s} " + "  ".join(line))

        surrogate = {}
        for a in matrix["species"]:
            for b in matrix["species"]:
                if a == b:
                    continue
                surrogate[f"{a}->{b}"] = species10.transfer_against_surrogate(
                    by_species[a], waves_by_species[b], group=40,
                    n_surrogates=100)
        medoid_index = tree10.medoids(
            tree["features"], np.asarray([
                {s: i for i, s in enumerate(sorted(by_species))}[r["species"]]
                for r in tree["rows"]]))
        out[name] = {"corpora": list(corpora), "n": tree["n"],
                     "ari_matrix": matrix, "surrogate": surrogate,
                     "species_medoid_feature_index": medoid_index}
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(STORE))
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--tasks", nargs="*",
                        default=["5b", "5c", "5a", "5d"])
    parser.add_argument("--permutations", type=int,
                        default=species10.N_PERMUTATIONS)
    parser.add_argument("--decode-permutations", type=int,
                        default=species10.N_DECODE_PERMUTATIONS)
    args = parser.parse_args(argv)

    out = _Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows, snippets, manifest = motifs5.load_store(args.store)
    print(f"store {args.store}: {len(rows)} motifs, "
          f"floor rule {manifest.get('floor_rule')}", flush=True)

    runners = {
        "5b": ("SPECIES_vs_RESOLUTION", task_5b, args.permutations),
        "5c": ("DECODE_species", task_5c, args.decode_permutations),
        "5a": ("FAMILIES_by_species", task_5a, args.permutations),
        "5d": ("TRANSFER_species", task_5d, args.decode_permutations),
    }
    for key in args.tasks:
        name, runner, permutations = runners[key]
        print(f"\n=== Task {key} -> {name}.json ===", flush=True)
        started = time.time()
        result = runner(rows, snippets, permutations)
        result["_meta"] = {
            "task": key, "store": args.store,
            "n_store": len(rows), "permutations": permutations,
            "seed_formula": "SEED_BASE + 100*group + index",
            "seed_base": species10.SEED_BASE,
            "seconds": round(time.time() - started, 1),
        }
        path = out / f"{name}.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=1, default=str)
        print(f"-> {path}  ({result['_meta']['seconds']}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
