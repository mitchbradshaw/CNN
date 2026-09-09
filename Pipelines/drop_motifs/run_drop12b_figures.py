"""
run_drop12b_figures.py
=======================
drop_motifs12b. Reads the store `drop_motifs12a` wrote and REDRAWS the four
figures that failed the round-11 review. It detects nothing, clusters
nothing the run does not already own, and writes to no store.

    python Pipelines/drop_motifs/run_drop12b_figures.py
    python Pipelines/drop_motifs/run_drop12b_figures.py --store <dir> --out <dir>
    python Pipelines/drop_motifs/run_drop12b_figures.py --only S3_1

The order is the work order's, and it is not arbitrary: the smoke test
first, because a drawing rule that is wrong is wrong in every figure; then
sequences, because three figures select from them; then S3.1, which
exercises every one of the nine rules, so if it looks right the rest will.

S2.1 is NOT redrawn. The review passed it. It is regenerated identically
against the new store - which is a redraw only in the sense that the store
underneath it has changed - and `--only` can skip it.
"""

import argparse
import json
import os
import sys

import numpy as np
from matplotlib import pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from Pipelines.drop_motifs import (config11, drawing_rules, figures11_s2,
                                   figures11_s3, figures12b_s2, figures12b_s3,
                                   sequences11, sources12b, store11, tree10)

DEFAULT_STORE = os.path.join("Plots", "drop_motifs12a", "motifs")
DEFAULT_OUT = os.path.join("Plots", "drop_motifs12b")

# The round-11 counts every "against round 11" line in the report compares
# to, read off `Plots/drop_motifs11/sequences.json`. Held here rather than
# re-read so the comparison survives that directory being regenerated.
ROUND11_QUALIFYING = {"oyster": 19, "sp385": 1, "reishi": 98}
ROUND11_CANDIDATES = {"oyster": 39, "sp385": 7, "reishi": 149}

FAMILY_K = tree10.FINE_K

FIGURE_IDS = ("S2_1", "S2_2", "S2_3", "S3_1", "S3_2", "S3_3")

# How many sequences BEYOND the work order's four each species gets. Oyster
# gets more because it is the corpus with the most channel-span groups (15)
# and one figure of it cannot show whether the wander on
# `oyster_id10_ch3_1362824s` is that channel's habit or the species'.
EXTRA_PER_SPECIES = {"oyster": 5}
EXTRA_DEFAULT = 3


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--species", nargs="*", default=None)
    parser.add_argument("--include-control", action="store_true")
    parser.add_argument("--reference-species", default=None)
    parser.add_argument("--only", nargs="*", default=None,
                        help=f"figure ids to write, from {FIGURE_IDS}")
    parser.add_argument("--db", default=sources12b.DB)
    parser.add_argument("--extra-sequences", nargs="*", default=None,
                        metavar="SPECIES=N",
                        help="further S3.1 sequences per species beyond the "
                             "work order's four, e.g. oyster=5 reishi=3; "
                             f"default {EXTRA_PER_SPECIES} and "
                             f"{EXTRA_DEFAULT} for anything else")
    args = parser.parse_args(argv)
    args.extra_sequences = _extra_counts(args.extra_sequences)
    return args


def _extra_counts(pairs):
    """`{species: n}` from `SPECIES=N` arguments, over the defaults."""
    counts = dict(EXTRA_PER_SPECIES)
    for item in pairs or ():
        name, _, value = str(item).partition("=")
        if not _:
            raise SystemExit(f"--extra-sequences wants SPECIES=N, got {item!r}")
        counts[name] = int(value)
    return counts


def wanted(args, figure_id):
    return args.only is None or figure_id in args.only


# ==========================================================================
# step 1 - the smoke test
# ==========================================================================

def smoke_test(rows, snippets, path):
    """One event per species, drawn under the rules, with its ratio measured.

    The work order's first deliverable and the only one that gates the
    others: a drawing rule that puts the median event outside 1:1 - 3:1 is
    wrong in every figure that imports it, and this catches it in seconds
    rather than after six figures have been rendered.

    The event drawn is the species' MEDIAN event by fall duration, chosen
    by rule so the check is reproducible and so it measures the typical
    case rather than a lucky one.
    """
    config11.apply_style()
    grouped = store11.by_species(rows)
    species = list(grouped)
    resolved = config11.resolve(species)

    fig, axes = plt.subplots(1, max(len(species), 1),
                             figsize=(2.6 * max(len(species), 1) + 0.8, 5.4))
    axes = np.atleast_1d(axes)
    result = {"target": [drawing_rules.MIN_RATIO, drawing_rules.MAX_RATIO],
              "species": {}, "passed": True}

    for ax, name in zip(axes, species):
        own = grouped[name]
        falls = np.array([drawing_rules.fall_duration_s(r) for r in own])
        median_row = own[int(np.argsort(falls)[len(falls) // 2])]

        aspect, ratio, capped = drawing_rules.figure_aspect(own)
        t, y, complete = drawing_rules.framed_trace(median_row, snippets)
        if t is not None:
            ax.axvspan(0.0, drawing_rules.fall_duration_s(median_row),
                       color=resolved[name]["colour"], alpha=0.20, lw=0.0)
            ax.plot(t, y, color=resolved[name]["colour"], lw=1.6)
        drawing_rules.apply_aspect(ax, aspect)
        ax.set_xlabel("time from onset (s)")
        ax.set_ylabel("mV")
        ax.grid(alpha=0.15)
        ok, why = drawing_rules.check_drop_shape(ratio)
        config11.panel_title(ax, f"{resolved[name]['label']}\n{ratio:.2g}:1")
        result["species"][name] = {
            "label": resolved[name]["label"],
            "n": len(own),
            "event_id": median_row["event_id"],
            "drop_depth_mv": abs(float(median_row["drop_depth_mv"])),
            "fall_duration_s": drawing_rules.fall_duration_s(median_row),
            "aspect_seconds_per_mv": float(aspect),
            "median_event_drawn_ratio": float(ratio),
            "aspect_capped": bool(capped),
            "frame_complete": bool(complete),
            "passed": bool(ok),
            "note": why,
        }
        result["passed"] = result["passed"] and ok

    for ax in axes[len(species):]:
        ax.set_axis_off()
    fig.suptitle("Drawing-rules smoke test - the median event of each species",
                 fontsize=config11.FS_SUPTITLE)
    config11.footer(fig, "", len(rows),
                    extra="rule 9: a drop must look like a drop; the median "
                          "event is targeted at "
                          f"{drawing_rules.TARGET_RATIO}:1 "
                          f"height-to-width")
    config11.save(fig, path)
    config11.write_manifest(path, result)
    return result


# ==========================================================================
# S3.1 selection
# ==========================================================================

def s3_1_picks(runs, species):
    """`[(run, rule)]` - the four sequences the work order names.

    By rule and by species, never by hand:
      - the longest qualifying Reishi run
      - the longest qualifying Oyster run
      - a Reishi run with gap drift beyond +/-20%
      - the longest qualifying Lion's mane run, new this round

    A species that has no qualifying run is skipped and the skip is
    reported, which is the honest form of "should now exist".
    """
    wants = [("reishi", sequences11.longest,
              "longest qualifying run of Reishi"),
             ("oyster", sequences11.longest,
              "longest qualifying run of Oyster"),
             ("reishi", sequences11.most_drifted,
              f"longest Reishi run whose gap drifts beyond "
              f"+/-{sequences11.DRIFT_MARK:.0%}"),
             ("lionsmane", sequences11.longest,
              "longest qualifying run of Lion's mane"),
             ("sp385", sequences11.longest,
              "longest qualifying run of Lion's mane (retired 1 Hz corpus)")]

    picks, seen, missing = [], set(), []
    for name, chooser, rule in wants:
        if name not in species:
            continue
        run = chooser(runs, name)
        if run is None:
            missing.append(rule)
            continue
        if run["sequence_key"] in seen:
            continue
        seen.add(run["sequence_key"])
        picks.append((run, rule))
    return picks, missing


def s3_1_extras(runs, species, already, per_species=None, default=EXTRA_DEFAULT):
    """`[(run, rule)]` - further sequences per species, still by rule.

    Longest first, but taken ROUND-ROBIN across (catalogue_id, channel)
    groups before any group is revisited. Ranking on length alone is what a
    naive "next longest" does, and on this store it would spend all five
    Oyster figures on catalogue ID 10 - the one channel whose runs are
    longest - so the extra figures would say nothing the first one did not.
    Round-robin spends them on different channels first, which is the only
    reason to draw more than one.

    `already` is the set of keys the work order's own four took, so nothing
    is drawn twice.
    """
    per_species = dict(per_species or EXTRA_PER_SPECIES)
    picks = []
    for name in species:
        want = int(per_species.get(name, default))
        own = [run for run in runs
               if run["species"] == name
               and run["sequence_key"] not in already]
        if want <= 0 or not own:
            continue

        groups = {}
        for run in sorted(own, key=lambda r: (-r["n"], r["cv_interval"],
                                              r["sequence_key"])):
            groups.setdefault(store11.group_key(run["rows"][0]), []).append(run)
        # Groups in order of their own longest run, so the first pass over
        # them is still "the longest runs", one per channel.
        order = sorted(groups, key=lambda key: (-groups[key][0]["n"], str(key)))

        taken = []
        while len(taken) < want and any(groups[key] for key in order):
            for key in order:
                if len(taken) >= want:
                    break
                if groups[key]:
                    taken.append(groups[key].pop(0))
        label = config11.label_of(name)
        for rank, run in enumerate(taken, start=1):
            picks.append((run, (
                f"further {label} run {rank} of {len(taken)}, by length "
                f"round-robin across channel-span groups; this one is "
                f"catalogue ID {run['catalogue_id']} CH{run['channel']}, "
                f"{run['n']} events")))
    return picks


# ==========================================================================
# main
# ==========================================================================

def main(argv=None):
    args = parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    rows, snippets, _store_manifest = store11.load(
        args.store, species=args.species,
        include_control=args.include_control)
    if not rows:
        raise SystemExit(f"no events in {args.store} for the species asked for")

    species = store11.species_in(rows)
    counts = store11.counts_by_species(rows)
    report = {"store": args.store, "out": args.out, "run": "drop_motifs12b",
              "species": species, "counts": counts, "n_total": len(rows),
              "drawing_rules": {
                  "frame_pre_onset_falls": drawing_rules.PRE_ONSET_FALLS,
                  "frame_post_trough_falls": drawing_rules.POST_TROUGH_FALLS,
                  "normalised_axis": [drawing_rules.PHASE_LO,
                                      drawing_rules.PHASE_HI],
                  "target_ratio": drawing_rules.TARGET_RATIO,
                  "ratio_band": [drawing_rules.MIN_RATIO,
                                 drawing_rules.MAX_RATIO],
                  "waterfall_offset_fraction": drawing_rules.OFFSET_FRACTION,
                  "max_traces": drawing_rules.MAX_TRACES,
              }}

    # -- 1  the smoke test -------------------------------------------------
    report["smoke"] = smoke_test(
        rows, snippets, os.path.join(args.out, "smoke_drawing_rules.png"))

    # -- 2  sequence extraction on the new store ---------------------------
    runs, summary = sequences11.extract(rows)
    candidate_counts = {}
    for _key, _median, members in sequences11.candidates(rows):
        name = members[0]["species"]
        candidate_counts[name] = candidate_counts.get(name, 0) + 1
    summary["candidate_runs_per_species"] = candidate_counts
    summary["round11_qualifying_per_species"] = ROUND11_QUALIFYING
    summary["round11_candidates_per_species"] = ROUND11_CANDIDATES
    sequences11.write_csv(os.path.join(args.out, "sequences.csv"), runs)
    with open(os.path.join(args.out, "sequences.json"), "w",
              encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, default=config11._jsonable)
    report["sequences"] = summary

    sources = sources12b.Sources(args.db)

    # -- 3  S3.1, first, because it exercises every rule --------------------
    if wanted(args, "S3_1"):
        families, cophenetic = figures11_s3._families_of(rows, snippets,
                                                         FAMILY_K)
        report["family_cut"] = {"k": FAMILY_K, "cophenetic": cophenetic}
        picks, missing = s3_1_picks(runs, species)
        picks += s3_1_extras(runs, species,
                             {run["sequence_key"] for run, _rule in picks},
                             per_species=args.extra_sequences)
        report["S3_1"] = {}
        report["S3_1_not_drawn"] = missing
        report["S3_1_extra_per_species"] = args.extra_sequences
        for run, rule in picks:
            path = os.path.join(
                args.out, f"S3_1_sequence_morph_{run['sequence_key']}.png")
            report["S3_1"][run["sequence_key"]] = \
                figures12b_s3.plot_sequence_morph(
                    run, snippets, path, sources=sources,
                    store_label=args.store, families=families,
                    family_k=FAMILY_K, selection=rule)

    # -- 4  S2.2, then S2.3 -------------------------------------------------
    if wanted(args, "S2_2"):
        report["S2_2"] = figures12b_s2.plot_scale_collapse(
            rows, snippets, os.path.join(args.out, "S2_2_scale_collapse.png"),
            store_label=args.store)

    if wanted(args, "S2_3"):
        report["S2_3"] = figures12b_s2.plot_asymmetry(
            rows, snippets, os.path.join(args.out, "S2_3_asymmetry.png"),
            store_label=args.store, reference=args.reference_species)

    # -- 5  S3.2 ------------------------------------------------------------
    if wanted(args, "S3_2"):
        report["S3_2"] = figures12b_s3.plot_morph_across_scales(
            runs, snippets,
            os.path.join(args.out, "S3_2_morph_across_scales.png"),
            store_label=args.store, summary=summary,
            candidates=candidate_counts)

    # -- 6  S3.3, dropped if the effect is absent ---------------------------
    if wanted(args, "S3_3"):
        duty = store11.duty_by_species(rows)
        narrowest = min(duty, key=lambda n: duty[n]["duty_median"])
        report["S3_3"] = figures12b_s3.probe_isolated_pairs(
            rows, narrowest,
            os.path.join(args.out, "S3_3_isolated_pairs.png"),
            store_label=args.store)

    # -- S2.1, untouched by the review: regenerated, not redesigned ---------
    if wanted(args, "S2_1"):
        report["S2_1"] = figures11_s2.plot_fall_angle(
            rows, os.path.join(args.out, "S2_1_fall_angle.png"),
            store_label=args.store)

    sources.close()

    # A `--only` run MERGES into the report rather than replacing it. A
    # re-run of one figure otherwise deletes every other figure's block from
    # `run_report.json` while leaving its PNG on disk, so the directory ends
    # up holding six figures and a report describing one - and the report is
    # what a reader checks the figures against.
    report_path = os.path.join(args.out, "run_report.json")
    if args.only and os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as handle:
            merged = json.load(handle)
        merged.update(report)
        report = merged
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=config11._jsonable)
    _print_report(report)
    return report


def _print_report(report):
    """Only what the work order asked to be printed."""
    smoke = report.get("smoke", {})
    print("drawn height-to-width of the median event, from the smoke test")
    print(f"  target band {smoke.get('target')}")
    for name, entry in smoke.get("species", {}).items():
        flag = "" if entry["passed"] else "   ** OUTSIDE THE BAND **"
        print(f"  {entry['label']:<14} {entry['median_event_drawn_ratio']:.2f}:1"
              f"   ({entry['drop_depth_mv']:.3g} mV over "
              f"{entry['fall_duration_s']:.3g} s, n = {entry['n']:,}){flag}")
    for key in ("S2_2", "S3_1", "S3_2"):
        block = report.get(key)
        if not block:
            continue
        if key == "S2_2":
            named = [(e["label"], e) for e in block["species"].values()]
        elif key == "S3_1":
            named = list(block.items())
        else:
            named = [(e["sequence_key"], e) for e in block["rows"]]
        for name, entry in named:
            print(f"  {key} {name:<34} "
                  f"{entry['median_event_drawn_ratio']:.2f}:1"
                  f"{'' if entry['drop_shape_ok'] else '   ** ' + entry['drop_shape_note'] + ' **'}")

    summary = report.get("sequences", {})
    if summary:
        print("\nqualifying sequences on the new store, against round 11")
        for name, entry in summary["per_species"].items():
            was = summary["round11_qualifying_per_species"].get(name)
            print(f"  {config11.label_of(name):<14} {entry['runs']:>4} runs "
                  f"({entry['events']:,} events, longest {entry['longest_n']})"
                  f"  |  round 11: {was if was is not None else 'not in that store'}"
                  f"  |  of {summary['candidate_runs_per_species'].get(name, 0)}"
                  f" candidates")
        for name in summary["round11_qualifying_per_species"]:
            if name not in summary["per_species"]:
                # By STORE KEY, not by label: `sp385` and `lionsmane` are
                # both labelled "Lion's mane" - they are the same organism -
                # so a label-only line reads as the species appearing twice.
                print(f"  {name:<14} {'-':>4}       |  round 11: "
                      f"{summary['round11_qualifying_per_species'][name]}"
                      f"  |  not in this store")
    if report.get("S3_1_not_drawn"):
        print("  not drawn: " + "; ".join(report["S3_1_not_drawn"]))

    block = report.get("S2_3")
    if block:
        print("\nS2.3 median matching distance (z RMS, lower = closer)")
        for key in ("forward", "backward"):
            entry = block[key]
            print(f"  {entry['direction']:<46} medoid pairs "
                  f"{entry['median_medoid_distance']:.3f}  |  all "
                  f"{entry['n_events']:,} events "
                  f"{entry['median_event_coverage']:.3f}")
        print("\nduty cycle and absolute fall duration, on the new store")
        for name, entry in block["duty_cycle"].items():
            print(f"  {config11.label_of(name):<14} duty "
                  f"{entry['duty_median']:.4f} "
                  f"(IQR {entry['duty_q1']:.4f}-{entry['duty_q3']:.4f}, "
                  f"{entry['n_groups']} groups)  |  fall "
                  f"{entry['fall_median_s']:.3g} s  |  interval "
                  f"{entry['iei_median_s']:.4g} s")

    probe = report.get("S3_3")
    if probe:
        print("\nS3.3 isolated-event probe")
        name = config11.label_of(probe["species"])
        if "p_two_sided" not in probe:
            print(f"  {name}: not testable - {probe.get('reason')}. "
                  f"No figure written.")
        elif not probe.get("effect"):
            print(f"  {name}: no effect over {probe['n_pairs']:,} close pairs "
                  f"(< {probe['median_interval_s']:.3g} s apart), depth ratio "
                  f"{probe['observed_ratio']:.2f}x, two-sided permutation "
                  f"p = {probe['p_two_sided']:.3f}. No figure written.")
        else:
            print(f"  {name}: effect present over {probe['n_pairs']:,} pairs, "
                  f"depth ratio {probe['observed_ratio']:.2f}x, "
                  f"p = {probe['p_two_sided']:.3f}. Figure written.")

    flagged = [key for key in FIGURE_IDS
               if isinstance(report.get(key), dict)
               and report[key].get("flagged")]
    print("\nfigures flagged as unexplainable in three sentences: "
          + (", ".join(flagged) if flagged else "none"))


if __name__ == "__main__":
    main()
