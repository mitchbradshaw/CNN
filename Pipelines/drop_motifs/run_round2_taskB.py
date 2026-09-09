"""
run_round2_taskB.py
====================
Task B: how well can you recover which electrode an event came from, from
amplitude alone, from normalised shape alone, and from both?

    python Pipelines/drop_motifs/run_round2_taskB.py
    python Pipelines/drop_motifs/run_round2_taskB.py --permutations 200

Reads `round2_v1/motifs` - the corrected store from `run_round2_store.py` -
and writes

    round2_v1/TASK_B_decode.json
    round2_v1/DECODE_channel.png

No new detection and no surrogates. Everything here is a re-reading of the
store Task A already produced, which is what makes it cheap enough to be
the headline.

`--store` points this at a different store, which is how Task D re-runs the
same decoding on the per-channel-floored population without a second copy
of this file.
"""

import argparse
import json
import sys
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# The pin goes first - see run_round2_taskA.py for why. `cluster.py` builds
# the shape representation this task decodes, and drop_motifs10 has edited
# it in the working tree.
from Pipelines.drop_motifs import pinned9

_SNAPSHOT_PATH, PROVENANCE = pinned9.activate()

from Pipelines.drop_motifs import decode2, round2, round2figs1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=round2.STORE)
    parser.add_argument("--out-dir", default=round2.OUT_DIR)
    parser.add_argument("--permutations", type=int,
                        default=decode2.N_PERMUTATIONS)
    parser.add_argument("--tag", default="",
                        help="suffix for the output names, for Task D")
    args = parser.parse_args(argv)

    rows, shape, amplitude, channel, waveforms, info = round2.load(args.store)
    print(f"store: {args.store}")
    print(f"  n = {info['n_clustered']}, per channel "
          f"{info['n_per_channel']}")
    print(f"  amplitude features: {round2.AMPLITUDE_LABELS}")
    print(f"  shape features: {shape.shape[1]}-point z-normalised\n")

    models = decode2.classifiers()
    results, chance = {}, {}
    for representation in decode2.REPRESENTATIONS:
        X = decode2.build(representation, shape, amplitude)
        results[representation] = {}
        for name, model in models.items():
            entry = decode2.decode(X, channel, model,
                                   n_permutations=args.permutations)
            results[representation][name] = entry
            floor = " (at the permutation floor)" if entry["at_p_floor"] \
                else ""
            print(f"  {representation:9s} {name:20s} "
                  f"balanced accuracy {entry['balanced_accuracy'] * 100:5.1f}%"
                  f"   null median "
                  f"{entry['null_median'] * 100:4.1f}%   "
                  f"p = {max(entry['p_permutation'], entry['p_floor']):.4f}"
                  f"{floor}")
        if not chance:
            chance = {"nominal": 1.0 / len(set(channel.tolist())),
                      "realised": decode2.chance_baseline(X, channel)}

    sentence, verdict = decode2.headline(results)
    print(f"\n{sentence}")
    print(f"VERDICT: {verdict['verdict'].upper()} - {verdict['gloss']}")
    print(f"  shape's margin above chance is "
          f"{verdict['shape_margin_as_fraction_of_amplitude_margin'] * 100:.0f}% "
          f"of amplitude's (falsification threshold: "
          f"{verdict['falsification_threshold'] * 100:.0f}%)")

    # Which channels the confusion actually separates. The headline is one
    # number over five electrodes and it hides the shape of the answer -
    # CH2 in particular is the quiet channel and its recall is the thing a
    # reviewer will ask about.
    best_amplitude = max(results["amplitude"],
                         key=lambda m: results["amplitude"][m]
                         ["balanced_accuracy"])
    entry = results["amplitude"][best_amplitude]
    print(f"\n  per-channel recall from amplitude ({best_amplitude}):")
    for label, recall in zip(entry["confusion_labels"],
                             entry["per_class_recall"]):
        print(f"    CH{label}  {recall * 100:5.1f}%")

    out = _Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = args.tag
    figure = round2figs1.plot_decode(
        results, sentence, verdict, chance,
        out / f"DECODE_channel{tag}.png")
    print(f"\n-> {figure}")

    payload = {
        "task": "Task B - channel decodability",
        "claim": ("absolute amplitude carries the recording site; "
                  "normalised geometry does not"),
        "detector_provenance": PROVENANCE,
        "store": info,
        "design": {
            "folds": decode2.N_FOLDS,
            "scoring": decode2.SCORING,
            "class_weight": "balanced",
            "n_permutations": args.permutations,
            "seed": decode2._seed(),
            "seed_rule": ("round 2 uses SEED_BASE + 100*channel + "
                          "realisation; Task B's randomness is not per "
                          "channel so it takes SEED_BASE itself"),
            "amplitude_features": list(round2.AMPLITUDE_FEATURES),
            "shape_features": int(shape.shape[1]),
        },
        "chance": chance,
        "results": results,
        "headline": sentence,
        "verdict": verdict,
        "figure": figure,
    }
    path = out / f"TASK_B_decode{tag}.json"
    path.write_text(json.dumps(payload, indent=2, default=float),
                    encoding="utf-8")
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
