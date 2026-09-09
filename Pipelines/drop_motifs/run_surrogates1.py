"""
run_surrogates1.py
===================
Task 1's grid: 5 channels x 3 generators x N realisations through the
identical detection chain, and the rank-based p that follows.

    python Pipelines/drop_motifs/run_surrogates1.py --n 100

Writes, under `Plots/drop_motifs9_fig2a/nulls_v1/`:

    surrogate_runs/summary.csv      one row per (generator, realisation,
                                    channel), plus the pooled rows
    surrogate_runs/realisations.json    the same table, nested, with every
                                    seed
    NULL_surrogate.json             observed vs null, every p, every N

NOTHING SURROGATE-DERIVED IS PERSISTED AS A SIGNAL. A realisation's
surrogate channels, its detections and its snippets live inside one worker
call and are discarded when it returns; only the summary numbers come
back. No `recordings` row is written, no store is created, and
`DATA/db/annotations.sqlite` is opened read-only, once, to resolve the
five channel paths.

WHY THE WORK IS SPLIT BY (GENERATOR, REALISATION) AND NOT BY CHANNEL
--------------------------------------------------------------------
The family statistics are POOLED - one tree over all five channels'
events, exactly as the shipped figures build one tree over all five
channels' events. A worker that owned one channel could not compute them.
So one job is one whole realisation of one generator: five surrogate
channels, five chains, one pooled tree. That is ~30 s of work, which is
long enough that process startup does not dominate and short enough that
sixteen of them keep every core busy.
"""

import os

# BEFORE numpy, and therefore before the module-level imports below, in
# both the parent and every spawned worker (Windows spawn re-imports this
# module, so setting it here covers them too).
#
# Fourteen worker processes each letting BLAS open sixteen threads is 224
# threads on sixteen cores. Measured: the grid ran at about 2.4x the
# serial rate instead of 14x - 63 minutes rather than 11 - because the
# threads spent their time contending rather than working. Nothing in this
# pipeline has a matrix big enough for threaded BLAS to pay for itself;
# the parallelism that matters is one realisation per process.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np

from Pipelines.drop_motifs import nulls1 as n1

# Populated once per worker process, not once per job: the five channel
# arrays are 12001 floats each and re-reading them 300 times is pointless.
_CACHE = {}


def _context():
    if not _CACHE:
        entries = n1.channel_table()
        _CACHE["entries"] = entries
        _CACHE["signals"] = {e["channel"]: n1.load_channel(e) for e in entries}
        _CACHE["kwargs"] = n1.detect_kwargs()
    return _CACHE


def observed_stats(trim_s=n1.EDGE_TRIM_S):
    """The real store's numbers, on the same trimmed interior the
    surrogates are counted on.

    These are NOT the numbers in `refine_report.json`: those cover the
    whole 1200 s, and the surrogates cannot be counted over the whole
    1200 s because their first and last 50 s carry the FFT wrap-around.
    Both are reported so the difference is visible.
    """
    rows, snippets, _ = n1.load_refined_store()
    n_samples = {}
    for entry in n1.channel_table():
        n_samples[entry["channel"]] = len(n1.load_channel(entry))

    trimmed = []
    per_channel = {}
    for entry in n1.channel_table():
        channel = entry["channel"]
        mine = [r for r in rows if int(r["channel"]) == channel]
        kept = n1.trim_edges(mine, entry["fs"], n_samples[channel], trim_s)
        trimmed.extend(kept)
        per_channel[channel] = {
            "n_untrimmed": len(mine),
            "n_after_floor": len(kept),
            "depth_mv": n1.quartiles(abs(float(r["drop_depth_mv"]))
                                     for r in kept),
            "fall_duration_s": n1.quartiles(float(r["fall_duration_s"])
                                            for r in kept),
            **{"angle_" + k: v
               for k, v in n1.angle_stats(kept, snippets).items()},
        }

    family = n1.cluster_stats_both_modes(trimmed, snippets, cut_heights=None)
    pooled_angles = n1.angle_stats(trimmed, snippets)

    return {
        "n_untrimmed": len(rows),
        "n_after_floor": len(trimmed),
        "trim_s": float(trim_s),
        "per_channel": per_channel,
        "family": family,
        "cut_height_k4": {mode: family[mode]["own_cut_height_k4"]
                          for mode in n1.FEATURE_MODES},
        **{"angle_" + k: v for k, v in pooled_angles.items()},
    }


def one_realisation(generator, realisation, cut_heights):
    """Five surrogate channels through the chain, then the pooled trees.

    Runs in a worker process. Returns only numbers - every array it made
    is unreachable the moment it returns.
    """
    context = _context()
    kwargs = context["kwargs"]
    started = time.time()

    per_channel, pooled_rows, pooled_snippets, seeds = [], [], {}, {}
    for entry in context["entries"]:
        channel = entry["channel"]
        x = context["signals"][channel]
        seed = n1.seed_for(generator, channel, realisation)
        seeds[channel] = seed
        surrogate = n1.make_surrogate(x, entry["fs"], generator, seed)
        before, after, snippets, _ = n1.run_chain(surrogate, entry, kwargs)
        stats = n1.realisation_stats(before, after, snippets, entry,
                                     n_samples=len(x))
        pooled_rows.extend(stats.pop("_rows"))
        pooled_snippets.update(snippets)
        stats["seed"] = seed
        per_channel.append(stats)
        del surrogate, before, after, snippets

    family = n1.cluster_stats_both_modes(pooled_rows, pooled_snippets,
                                         cut_heights=cut_heights)
    pooled_angles = n1.angle_stats(pooled_rows, pooled_snippets)

    result = {
        "generator": generator,
        "realisation": int(realisation),
        "seeds": seeds,
        "seconds": round(time.time() - started, 1),
        "per_channel": per_channel,
        "n_after_floor": sum(c["n_after_floor"] for c in per_channel),
        "n_before_floor": sum(c["n_before_floor"] for c in per_channel),
        "family": family,
        **{"angle_" + k: v for k, v in pooled_angles.items()},
    }
    del pooled_rows, pooled_snippets
    return result


def _job(args):
    generator, realisation, cut_heights = args
    try:
        return one_realisation(generator, realisation, cut_heights)
    except Exception as exc:                                   # noqa: BLE001
        # One unusable realisation must not lose the other ninety-nine.
        # It is recorded as a failure and excluded from every p, and the
        # count of failures is written to the JSON rather than swallowed.
        return {"generator": generator, "realisation": int(realisation),
                "error": repr(exc)}


CSV_FIELDS = [
    "generator", "realisation", "channel", "seed",
    "n_before_floor", "n_after_floor",
    "pass_base", "pass_fine", "pass_sens", "pass_micro",
    "depth_q1_mv", "depth_median_mv", "depth_q3_mv",
    "fall_q1_s", "fall_median_s", "fall_q3_s",
    "angle_n", "angle_median_deg", "rho_depth_vs_angle", "control_b",
    "control_r2",
]
# One pair of family columns per representation - "fall" is the shipped
# one (onset..trough, what ALL_dendrogram.png is built from), "snippet" is
# the whole re-cut snippet. See nulls1.FEATURE_MODES.
for _mode in n1.FEATURE_MODES:
    CSV_FIELDS += [
        "%s_n_clustered" % _mode, "%s_n_dropped_degenerate" % _mode,
        "%s_n_families_at_height" % _mode,
        "%s_n_families_at_height_min5" % _mode,
        "%s_largest_family_at_height" % _mode,
        "%s_within_family_dispersion" % _mode,
        "%s_cophenetic" % _mode, "%s_own_cut_height_k4" % _mode,
    ]


def _csv_rows(result):
    """Per-channel rows plus one pooled row per realisation.

    The pooled row carries `channel = "POOLED"` and is where every family
    statistic lives - families are only defined over the pooled tree.
    """
    rows = []
    for channel in result.get("per_channel", []):
        rows.append({
            "generator": result["generator"],
            "realisation": result["realisation"],
            "channel": channel["channel"],
            "seed": channel["seed"],
            "n_before_floor": channel["n_before_floor"],
            "n_after_floor": channel["n_after_floor"],
            **{"pass_" + key: channel["per_pass"].get(key, 0)
               for key in ("base", "fine", "sens", "micro")},
            "depth_q1_mv": channel["depth_mv"]["q1"],
            "depth_median_mv": channel["depth_mv"]["median"],
            "depth_q3_mv": channel["depth_mv"]["q3"],
            "fall_q1_s": channel["fall_duration_s"]["q1"],
            "fall_median_s": channel["fall_duration_s"]["median"],
            "fall_q3_s": channel["fall_duration_s"]["q3"],
            "angle_n": channel["angle_n"],
            "angle_median_deg": channel["angle_median_angle_deg"],
            "rho_depth_vs_angle": channel["angle_spearman_rho_depth_vs_angle"],
            "control_b": channel["angle_duration_vs_depth_exponent"],
            "control_r2": channel["angle_duration_vs_depth_r2"],
        })
    family = result.get("family") or {}
    pooled = {
        "generator": result["generator"],
        "realisation": result["realisation"],
        "channel": "POOLED",
        "seed": "",
        "n_before_floor": result.get("n_before_floor"),
        "n_after_floor": result.get("n_after_floor"),
        "angle_n": result.get("angle_n"),
        "angle_median_deg": result.get("angle_median_angle_deg"),
        "rho_depth_vs_angle": result.get("angle_spearman_rho_depth_vs_angle"),
        "control_b": result.get("angle_duration_vs_depth_exponent"),
        "control_r2": result.get("angle_duration_vs_depth_r2"),
    }
    for mode in n1.FEATURE_MODES:
        stats = family.get(mode) or {}
        dropped = stats.get("dropped") or {}
        pooled.update({
            "%s_n_clustered" % mode: stats.get("n"),
            "%s_n_dropped_degenerate" % mode: dropped.get("degenerate"),
            "%s_n_families_at_height" % mode:
                stats.get("n_families_at_height"),
            "%s_n_families_at_height_min5" % mode:
                stats.get("n_families_at_height_min_members"),
            "%s_largest_family_at_height" % mode:
                stats.get("largest_family_at_height"),
            "%s_within_family_dispersion" % mode:
                stats.get("within_family_dispersion"),
            "%s_cophenetic" % mode: stats.get("cophenetic"),
            "%s_own_cut_height_k4" % mode: stats.get("own_cut_height_k4"),
        })
    rows.append(pooled)
    return rows


# ---------------------------------------------------------------------------
# the p-values
# ---------------------------------------------------------------------------

def _collect(results, generator, path):
    """`path` is a dotted accessor into a realisation dict."""
    out = []
    for result in results:
        if result.get("generator") != generator or "error" in result:
            continue
        node = result
        for key in path.split("."):
            if node is None:
                break
            node = node.get(key) if isinstance(node, dict) else None
        out.append(node)
    return out


def _per_channel(results, generator, channel, key):
    out = []
    for result in results:
        if result.get("generator") != generator or "error" in result:
            continue
        for entry in result["per_channel"]:
            if entry["channel"] == channel:
                out.append(entry.get(key))
    return out


def compute_tests(observed, results):
    """Every rank p the figure states.

    Direction is chosen per statistic and stated, because "one-sided" is
    only meaningful once the alternative is named:

      detections            greater - a real repertoire should give MORE
                            events than noise with the same spectrum.
      families at height    LESS - the limited-repertoire claim is that
                            real events fall into FEWER, larger families
                            than surrogate events do. If they do not, the
                            p is large and the claim fails, which is the
                            result either way.
      dispersion            LESS - real families should be TIGHTER.
      rho, b                two directions are meaningless here; what is
                            being asked is whether the null REPRODUCES the
                            observed value, so both tails are reported and
                            the honest reading is "is the observed value
                            inside the null's range".
    """
    tests = {"detections": {}, "family": {}, "geometry": {}}

    for generator in n1.GENERATORS:
        tests["detections"].setdefault("pooled", {})[generator] = n1.rank_p(
            observed["n_after_floor"],
            _collect(results, generator, "n_after_floor"), greater=True)
        for channel in range(5):
            tests["detections"].setdefault(
                "CH%d" % channel, {})[generator] = n1.rank_p(
                    n1.channel_entry(observed["per_channel"],
                                     channel)["n_after_floor"],
                    _per_channel(results, generator, channel, "n_after_floor"),
                    greater=True)

        for mode in n1.FEATURE_MODES:
            node = tests["family"].setdefault(mode, {})
            node.setdefault("n_families_at_height", {})[generator] = n1.rank_p(
                observed["family"][mode]["n_families_at_height_min_members"],
                _collect(results, generator,
                         "family.%s.n_families_at_height_min_members" % mode),
                greater=False)
            node.setdefault("within_family_dispersion", {})[generator] = \
                n1.rank_p(
                    observed["family"][mode]["within_family_dispersion"],
                    _collect(results, generator,
                             "family.%s.within_family_dispersion" % mode),
                    greater=False)
            node.setdefault("cophenetic", {})[generator] = n1.rank_p(
                observed["family"][mode]["cophenetic"],
                _collect(results, generator, "family.%s.cophenetic" % mode),
                greater=True)

        # rho is negative; "more negative than observed" is the tail that
        # would say the null out-correlates the data, so `greater=False`.
        tests["geometry"].setdefault("spearman_rho", {})[generator] = n1.rank_p(
            observed["angle_spearman_rho_depth_vs_angle"],
            _collect(results, generator, "angle_spearman_rho_depth_vs_angle"),
            greater=False)
        tests["geometry"].setdefault("control_b", {})[generator] = n1.rank_p(
            observed["angle_duration_vs_depth_exponent"],
            _collect(results, generator, "angle_duration_vs_depth_exponent"),
            greater=False)
    return tests


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=100,
                        help="realisations per generator")
    parser.add_argument("--workers", type=int, default=0,
                        help="0 = cpu_count() - 2")
    parser.add_argument("--out-dir", default=str(n1.OUT_DIR))
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    runs_dir = out_dir / "surrogate_runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    print("observed (real store, trimmed to the interior) ...", flush=True)
    observed = observed_stats()
    cut_heights = observed["cut_height_k4"]
    print("  %d of %d refined motifs survive the %g s edge trim"
          % (observed["n_after_floor"], observed["n_untrimmed"],
             observed["trim_s"]))
    for mode in n1.FEATURE_MODES:
        stats = observed["family"][mode]
        print("  [%s] n=%d (%d degenerate dropped), k=4 cut height %.4f, "
              "dispersion %.4f, families >=%d members at that height: %d, "
              "cophenetic %.3f"
              % (mode, stats["n"], stats["dropped"]["degenerate"],
                 stats["own_cut_height_k4"],
                 stats["within_family_dispersion"], n1.MIN_FAMILY_MEMBERS,
                 stats["n_families_at_height_min_members"],
                 stats["cophenetic"]))
    print("  rho(depth, angle) = %+.3f, control b = %.3f"
          % (observed["angle_spearman_rho_depth_vs_angle"],
             observed["angle_duration_vs_depth_exponent"]), flush=True)

    workers = args.workers or max(1, (os.cpu_count() or 4) - 2)
    jobs = [(generator, realisation, cut_heights)
            for generator in n1.GENERATORS
            for realisation in range(args.n)]

    # Time one job before committing to the grid, and say so out loud -
    # a three-hour run started by accident at 9 pm is the failure mode
    # this print exists to prevent.
    print("\ntiming one realisation ...", flush=True)
    started = time.time()
    probe = one_realisation(n1.GENERATORS[0], 0, cut_heights)
    per_job = time.time() - started
    total = per_job * len(jobs) / workers
    print("  one realisation = %.1f s (%d detections pooled)"
          % (per_job, probe["n_after_floor"]))
    print("  %d jobs / %d workers  ->  ~%.0f min wall clock"
          % (len(jobs), workers, total / 60.0), flush=True)
    if args.estimate_only:
        return 0

    results = [probe]
    remaining = [j for j in jobs if not (j[0] == n1.GENERATORS[0] and j[1] == 0)]
    started = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_job, job) for job in remaining]
        for done, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if done % 10 == 0 or done == len(futures):
                elapsed = time.time() - started
                print("  %d/%d  (%.1f min elapsed, ~%.1f min left)"
                      % (done, len(futures), elapsed / 60.0,
                         elapsed / done * (len(futures) - done) / 60.0),
                      flush=True)

    failures = [r for r in results if "error" in r]
    results = [r for r in results if "error" not in r]
    results.sort(key=lambda r: (r["generator"], r["realisation"]))
    print("\n%d realisations, %d failed" % (len(results), len(failures)))

    with open(runs_dir / "summary.csv", "w", newline="",
              encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        for result in results:
            writer.writerows(_csv_rows(result))
    (runs_dir / "realisations.json").write_text(
        json.dumps(n1.jsonable({"realisations": results,
                                "failures": failures}), indent=1),
        encoding="utf-8")

    tests = compute_tests(observed, results)
    payload = {
        "task": "Task 1 - surrogate nulls",
        "claim": ("the detected event population is not what this chain "
                  "returns from noise with the same spectrum, nor from "
                  "signal with the same waveforms in shuffled order"),
        "n_realisations_per_generator": int(args.n),
        "n_realisations_completed": {
            g: sum(1 for r in results if r["generator"] == g)
            for g in n1.GENERATORS},
        "n_failures": len(failures),
        "generators": {g: n1.GENERATOR_LABELS[g] for g in n1.GENERATORS},
        "block_seconds": n1.BLOCK_SECONDS,
        # The underscore-prefixed provenance keys are renamed here,
        # because `n1.jsonable` strips leading-underscore keys on the way
        # to disk (they are internal to `run_chain`, which filters them
        # out before calling the detector) - and the note about where
        # max_passes came from is exactly the kind of assumption that must
        # survive into the file rather than only into the code.
        "detect_kwargs": {
            (k.lstrip("_") if k.startswith("_") else k): v
            for k, v in n1.detect_kwargs().items()},
        "min_depth_mv": n1.MIN_DEPTH_MV,
        "edge_handling": {
            "method": "discard",
            "trim_s": n1.EDGE_TRIM_S,
            "note": ("the first and last 50 s of every surrogate AND of "
                     "every real channel are excluded from the counts, "
                     "because an FFT surrogate is circular and its "
                     "channel-boundary join is a step discontinuity the "
                     "detector would call a drop. No taper is applied: a "
                     "taper would alter the spectrum the surrogate exists "
                     "to preserve."),
        },
        "seed_rule": ("20260902 + 1000*generator_index + 10*channel + "
                      "realisation, generator_index over %r"
                      % (n1.GENERATORS,)),
        "seeds": {g: {("CH%d" % c): [n1.seed_for(g, c, r)
                                     for r in range(args.n)]
                      for c in range(5)} for g in n1.GENERATORS},
        "observed": observed,
        "tests": tests,
        "cut_height_k4_from_real_tree": cut_heights,
        "min_family_members": n1.MIN_FAMILY_MEMBERS,
        "feature_modes": {
            "fall": ("onset..trough only - what clusterfigs7._waveform_of "
                     "slices, and therefore what the shipped "
                     "ALL_dendrogram.png and every quoted family count are "
                     "built from"),
            "snippet": ("the whole re-cut snippet: 1.2 falls of approach, "
                        "the fall, 1.8 falls of recovery - strictly more "
                        "shape information"),
        },
    }
    (out_dir / "NULL_surrogate.json").write_text(
        json.dumps(n1.jsonable(payload), indent=1), encoding="utf-8")

    print("\n%-34s %10s %10s %8s" % ("statistic", "observed", "null med", "p"))
    for generator in n1.GENERATORS:
        print("--- %s" % n1.GENERATOR_LABELS[generator])
        lines = [("detections (pooled)",
                  tests["detections"]["pooled"][generator])]
        for mode in n1.FEATURE_MODES:
            lines += [
                ("families at fixed height [%s]" % mode,
                 tests["family"][mode]["n_families_at_height"][generator]),
                ("within-family dispersion [%s]" % mode,
                 tests["family"][mode]["within_family_dispersion"][generator]),
            ]
        lines += [("rho(depth, angle)",
                   tests["geometry"]["spearman_rho"][generator]),
                  ("control b", tests["geometry"]["control_b"][generator])]
        for name, node in lines:
            print("  %-32s %10.4g %10.4g %8s"
                  % (name, node["observed"] if node["observed"] is not None
                     else float("nan"),
                     node["null_median"] if node["null_median"] is not None
                     else float("nan"),
                     ("%.4f" % node["p"]) if node["p"] is not None else "-"))

    print("\n-> %s" % (out_dir / "NULL_surrogate.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
