"""
run_drop11_figures.py
======================
drop_motifs11. Reads a finished store and writes figures. Detects nothing,
clusters nothing the run does not already own, and writes to no store.

    python Pipelines/drop_motifs/run_drop11_figures.py
    python Pipelines/drop_motifs/run_drop11_figures.py --species oyster sp385
    python Pipelines/drop_motifs/run_drop11_figures.py --store <dir> --out <dir>

Order is the brief's: sequences first because several figures depend on
them and their counts change the story; then the scale collapse, the
asymmetry, the rose set, the two Section 3 figures; the isolated-pair probe
last, and only if the effect exists.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from Pipelines.drop_motifs import (config11, figures11_s2, figures11_s3,
                                   sequences11, store11, tree10)

DEFAULT_STORE = os.path.join("Plots", "drop_motifs10", "motifs")
DEFAULT_OUT = os.path.join("Plots", "drop_motifs11")

# The cut the start-versus-end panel reports families at. The finer of the
# run's two cuts, deliberately: "these two ends would be called different
# families" is a stronger claim when the clustering had more families to
# choose from, and the coarse cut is reported alongside it in the manifest.
FAMILY_K = tree10.FINE_K


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=DEFAULT_STORE,
                        help="finished drop_motifs store to read")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="directory to write figures into")
    parser.add_argument("--species", nargs="*", default=None,
                        help="subset to plot; default is every species in "
                             "the store")
    parser.add_argument("--include-control", action="store_true",
                        help="include the decimated reishi_1hz rate control "
                             "as if it were a species (off by default: it "
                             "would draw the same organism twice)")
    parser.add_argument("--reference-species", default=None,
                        help="species the others are matched against in "
                             "S2.3; default is the highest median duty cycle")
    parser.add_argument("--only", nargs="*", default=None,
                        help="figure ids to write, e.g. S2_2 S3_1")
    return parser.parse_args(argv)


def wanted(args, figure_id):
    return args.only is None or figure_id in args.only


def main(argv=None):
    args = parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    rows, snippets, store_manifest = store11.load(
        args.store, species=args.species,
        include_control=args.include_control)
    if not rows:
        raise SystemExit(f"no events in {args.store} for the species asked for")

    species = store11.species_in(rows)
    counts = store11.counts_by_species(rows)
    report = {"store": args.store, "out": args.out,
              "species": species, "counts": counts, "n_total": len(rows)}

    # -- the unit check, before any figure uses max_slope -----------------
    report["max_slope_unit"] = store11.MAX_SLOPE_UNIT_NOTE
    report["max_slope_factor"] = store11.MAX_SLOPE_TO_MV_S
    report["peakedness_median"] = {
        name: float(np.median([store11.peakedness(r) for r in rows
                               if r["species"] == name]))
        for name in species}

    # -- S3.0  sequences ---------------------------------------------------
    runs, summary = sequences11.extract(rows)
    candidate_counts = {}
    for key, _, members in sequences11.candidates(rows):
        name = members[0]["species"]
        candidate_counts[name] = candidate_counts.get(name, 0) + 1
    summary["candidate_runs_per_species"] = candidate_counts
    sequences_csv = sequences11.write_csv(
        os.path.join(args.out, "sequences.csv"), runs)
    with open(os.path.join(args.out, "sequences.json"), "w",
              encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, default=config11._jsonable)
    report["sequences"] = summary
    report["sequences_csv"] = sequences_csv

    # -- S2.2  the scale collapse -----------------------------------------
    if wanted(args, "S2_2"):
        report["S2_2"] = figures11_s2.plot_scale_collapse(
            rows, snippets, os.path.join(args.out, "S2_2_scale_collapse.png"),
            store_label=args.store)

    # -- S2.3  the asymmetry ------------------------------------------------
    if wanted(args, "S2_3"):
        report["S2_3"] = figures11_s2.plot_asymmetry(
            rows, snippets, os.path.join(args.out, "S2_3_asymmetry.png"),
            store_label=args.store, reference=args.reference_species)

    # -- S2.1  the rose set --------------------------------------------------
    if wanted(args, "S2_1"):
        report["S2_1"] = figures11_s2.plot_fall_angle(
            rows, os.path.join(args.out, "S2_1_fall_angle.png"),
            store_label=args.store)

    # -- S3.1  three sequences, selected by rule ----------------------------
    if wanted(args, "S3_1"):
        families, cophenetic = figures11_s3._families_of(rows, snippets,
                                                         FAMILY_K)
        report["family_cut"] = {"k": FAMILY_K, "cophenetic": cophenetic}
        report["S3_1"] = {}

        # By rule, never by hand: the longest qualifying run of each of the
        # TWO species that have the longest qualifying runs, plus the
        # longest drifting run of the first of those.
        #
        # Ranking on run length rather than naming reishi and oyster is
        # what makes this survive more data; ranking on run length rather
        # than on duty cycle is what stops it choosing a five-event run.
        # A species whose best run is five events cannot show a morph, and
        # a figure of it would be a figure of nothing - so Lion's mane is
        # absent here today and enters on its own the moment one of its
        # runs is long enough. S3.2 is where every species gets a row.
        ranked = sorted(species,
                        key=lambda n: -(sequences11.longest(runs, n) or
                                        {"n": 0})["n"])
        ranked = [n for n in ranked if sequences11.longest(runs, n)]
        first = ranked[0] if ranked else None
        second = ranked[1] if len(ranked) > 1 else None

        picks = []
        for position, name in enumerate((first, second)):
            if name is None:
                continue
            picks.append((
                sequences11.longest(runs, name),
                f"longest qualifying run of {config11.label_of(name)}, the "
                f"species with the {'longest' if position == 0 else 'second longest'} "
                f"qualifying run in the store"))
        if first is not None:
            picks.append((
                sequences11.most_drifted(runs, first),
                f"longest {config11.label_of(first)} run whose gap drifts "
                f"beyond +/-{sequences11.DRIFT_MARK:.0%}"))
        seen = set()
        for run, rule in picks:
            if run is None or run["sequence_key"] in seen:
                continue
            seen.add(run["sequence_key"])
            path = os.path.join(
                args.out, f"S3_1_sequence_morph_{run['sequence_key']}.png")
            report["S3_1"][run["sequence_key"]] = \
                figures11_s3.plot_sequence_morph(
                    run, snippets, path, store_label=args.store,
                    families=families, family_k=FAMILY_K, selection=rule)

    # -- S3.2  the same morph at different scales ---------------------------
    if wanted(args, "S3_2"):
        report["S3_2"] = figures11_s3.plot_morph_across_scales(
            runs, snippets,
            os.path.join(args.out, "S3_2_morph_across_scales.png"),
            store_label=args.store, summary=summary,
            candidates=candidate_counts)

    # -- S3.3  the probe, last, and dropped if there is no effect -----------
    if wanted(args, "S3_3"):
        narrowest = min(store11.duty_by_species(rows),
                        key=lambda n: store11.duty_by_species(rows)[n]["duty_median"])
        report["S3_3"] = figures11_s3.probe_isolated_pairs(
            rows, narrowest,
            os.path.join(args.out, "S3_3_isolated_pairs.png"),
            store_label=args.store)

    with open(os.path.join(args.out, "run_report.json"), "w",
              encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=config11._jsonable)
    _print_report(report)
    return report


def _print_report(report):
    """Only what the brief asked to be printed."""
    print("max_slope unit")
    print(f"  {report['max_slope_unit']}")
    print("  median peakedness (max/mean slope), a check on the conversion: "
          + ", ".join(f"{name} {value:.2f}"
                      for name, value in report["peakedness_median"].items()))

    summary = report["sequences"]
    print("\nsequences")
    thresholds = summary["thresholds"]
    print(f"  gap cut {thresholds['gap_multiple']}x the group's own median "
          f"interval; runs >= {thresholds['min_run_events']} events; "
          f"CV <= {thresholds['cv_max']} or R2 >= {thresholds['r2_min']}")
    print(f"  {summary['total_runs']} qualifying runs, "
          f"{summary['total_events']} events, from "
          f"{summary['n_candidate_runs']} candidates")
    for name, entry in summary["per_species"].items():
        print(f"  {config11.label_of(name):<12} {entry['runs']:>3} runs, "
              f"{entry['events']:>4} events  |  constant-gap only "
              f"{entry['arm_constant_gap_only']}, trend only "
              f"{entry['arm_trend_only']}, both {entry['arm_both']}"
              f"  |  longest {entry['longest_n']}")
    print(f"  arms overall: constant gap {summary['arm_constant_gap_total']}, "
          f"trend {summary['arm_trend_total']}, trend ALONE "
          f"{summary['arm_trend_only_total']}")
    print("  gap drift (last third / first third of intervals), "
          "constant-gap runs:")
    for name, entry in summary["per_species"].items():
        if not entry["drift_n"]:
            print(f"    {config11.label_of(name):<12} no constant-gap runs")
            continue
        print(f"    {config11.label_of(name):<12} median "
              f"{entry['drift_median']:.2f}, IQR {entry['drift_q1']:.2f}-"
              f"{entry['drift_q3']:.2f}, {entry['high_drift_runs']} of "
              f"{entry['drift_n']} beyond +/-{thresholds['drift_mark']:.0%}")

    if "S2_3" in report:
        block = report["S2_3"]
        print("\nS2.3 matching distance (z RMS, lower = closer)")
        for key in ("forward", "backward"):
            entry = block[key]
            print(f"  {entry['direction']:<44} medoid pairs "
                  f"{entry['median_medoid_distance']:.3f}  |  all "
                  f"{entry['n_events']} events "
                  f"{entry['median_event_coverage']:.3f}")
        print("  within-species baseline: "
              + ", ".join(f"{config11.label_of(k)} {v:.3f}"
                          for k, v in block["within_species_baseline"].items()))

        print("\nduty cycle and absolute fall duration")
        for name, entry in block["duty_cycle"].items():
            print(f"  {config11.label_of(name):<12} duty "
                  f"{entry['duty_median']:.3f} "
                  f"(IQR {entry['duty_q1']:.3f}-{entry['duty_q3']:.3f}, "
                  f"{entry['n_groups']} groups)  |  fall "
                  f"{entry['fall_median_s']:.3g} s  |  interval "
                  f"{entry['iei_median_s']:.3g} s")

    if "S3_3" in report:
        probe = report["S3_3"]
        print("\nS3.3 isolated-event probe")
        name = config11.label_of(probe["species"])
        if "p_two_sided" not in probe:
            print(f"  {name}: not testable - {probe.get('reason')}. "
                  f"No figure written.")
        elif not probe.get("effect"):
            print(f"  {name}: no effect. Depth ratio "
                  f"{probe['observed_ratio']:.2f}x over {probe['n_pairs']} "
                  f"close pairs (< {probe['median_interval_s']:.3g} s apart), "
                  f"two-sided permutation p = {probe['p_two_sided']:.3f} "
                  f"against {probe['n_shuffles']:,} within-pair order "
                  f"shuffles. No figure written.")
        else:
            print(f"  {name}: effect present. Depth ratio "
                  f"{probe['observed_ratio']:.2f}x over {probe['n_pairs']} "
                  f"pairs, p = {probe['p_two_sided']:.3f}. Figure written.")


if __name__ == "__main__":
    main()
