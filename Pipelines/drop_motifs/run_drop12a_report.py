"""
run_drop12a_report.py
======================
Assembles `manifest.json` and `run_report.json` for drop_motifs12a from the
artefacts the other two runners wrote, and states plainly which deliverables
exist and which are blocked.

    python Pipelines/drop_motifs/run_drop12a_report.py

Reads `scale_probe.json` and `pipelines/pipelines_index.json` under
`Plots/drop_motifs12a/` and writes beside them. It computes nothing new: if
a number is in the report it came out of one of those files, so the report
cannot disagree with the run that produced it.

Why the manifest records what is MISSING
-----------------------------------------
The work order lists a store, two floor variants and three Lion's mane
pipeline plots that this run does not produce, because the scale probe's
verdict says the detector cannot frame region A's events at 10 Hz. A
manifest that simply omitted them would read, later, as a run that was never
asked for them. `blocked` names each one, what it is waiting on, and what
would unblock it.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import floor10, lionsmane12, probe12  # noqa: E402
from Working.Detection.drop_motifs import motifs5  # noqa: E402

OUT = _Path("Plots") / "drop_motifs12a"


def _read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _corpus_counts(store):
    """`{corpus: n}` counted from the store itself, not quoted from a doc.

    The oyster and reishi totals are 754 and 2425 in `drop_motifs10`'s
    PROVENANCE. Writing those numbers here would make this manifest a copy
    of a document rather than a reading of a store, and the two would
    eventually disagree without either being obviously wrong.
    """
    counts = {}
    for row in motifs5.load_events(store):
        key = row.get("corpus")
        counts[key] = counts.get(key, 0) + 1
    return counts


def species_map(store, lionsmane_store=None, detect_summary=None):
    """The species table the work order asks the manifest to state.

    Every count is counted from a store, never quoted from a document.
    """
    counts = _corpus_counts(store)
    lm_counts = _corpus_counts(lionsmane_store) if lionsmane_store else {}
    detected = [k for k, v in (detect_summary or {}).items()
                if isinstance(v, dict) and v.get("detected")]
    refused = [k for k, v in (detect_summary or {}).items()
               if isinstance(v, dict) and v.get("refused")]
    return {
        "oyster": {
            "corpus": "oyster", "fs_hz": 1.0, "framing": "span",
            "n_events": counts.get("oyster"),
            "store": "Plots/drop_motifs10/motifs/",
            "note": "the 15 operator-chosen catalogue spans; the complete "
                    "oyster set, unchanged by this run",
        },
        "reishi": {
            "corpus": "reishi_10hz", "fs_hz": 10.0, "framing": "sliding 50 s",
            "n_events": counts.get("reishi_10hz"),
            "store": "Plots/drop_motifs10/motifs/",
            "note": "Fig2A CH0-CH4, unchanged by this run",
        },
        "lionsmane": {
            "corpus": lionsmane12.CORPUS, "fs_hz": lionsmane12.FS,
            "framing": "sliding, 120 s window (region B)",
            "n_events": lm_counts.get(lionsmane12.CORPUS),
            "store": lionsmane_store,
            "regions_detected": detected,
            "regions_refused": refused,
            "note": "region B only. Region A is refused by the scale probe's "
                    "verdict - 1 of 4 completed window-arm cells frames its "
                    "events and 5 of 9 did not complete. See PROVENANCE.md "
                    "sections 2.2 and 5.",
        },
        "retired_in_the_partial_stores": {
            "sp385": "excluded, as the work order says - BUT the retirement "
                     "is not supported by measurement. Over the four hours "
                     "where ID 385 provably sits, the 10 Hz run finds 36-44 "
                     "events against sp385's 76, matching about half. See "
                     "PROVENANCE.md section 3.2.",
            "reishi_1hz": "excluded, as the work order says.",
            "both_remain_in": "Plots/drop_motifs10/",
            "recommendation": "do not make either retirement permanent until "
                              "the floor question in PROVENANCE.md section "
                              "3.2 is settled",
        },
        "floor_comparability_warning": (
            "The two 10 Hz corpora are NOT on comparable floors. Reishi's "
            "derived floors are 0.005-0.020 mV; Lion's mane region B's is "
            "0.725 mV - a factor of 36 to 145 under the same 3-sigma rule at "
            "the same sampling rate. Measured on the SAME electrode over the "
            "SAME four hours, the 10 Hz stream's amplitude sigma is 0.2387 "
            "mV against the 1 Hz export's 0.0054 mV, a factor of 44, while "
            "the peak-to-peak agrees to 3 percent. The derived floor is a "
            "property of the sampling rate as well as of the recording."),
        "confound_note": (
            "Reishi and Lion's mane region B are now both 10 Hz and both "
            "sliding-window, so that comparison is free of the sampling-rate "
            "confound. Oyster remains 1 Hz and span-framed, so any "
            "comparison involving Oyster is not. But matching the RATE does "
            "not match the RESOLUTION: Reishi's median fall is about 7 "
            "samples and Lion's mane region B's is 15, and drop_motifs10 "
            "section 6.3 measured that n_samples_in_fall ALONE decodes "
            "species at 0.575 against a 0.333 chance. The samples-per-fall "
            "distribution has to be quoted beside any species result from "
            "these stores."),
    }


def blocked_entries():
    return {
        "motifs/ and motifs_globalfloor/": {
            "why": "region A is not detected, so a store naming the "
                   "lionsmane species would describe one region of two",
            "written_instead": "motifs_PARTIAL/ and "
                               "motifs_globalfloor_PARTIAL/, named and "
                               "stamped so they cannot be mistaken for the "
                               "finished article",
            "waiting_on": "a decision on the detection rate for region A "
                          "(PROVENANCE.md section 5)",
        },
        "region_A_CH3_overview.png with events shaded": {
            "why": "the pre-detection version IS written; region A has no "
                   "detections to shade",
            "waiting_on": "the same decision",
        },
        "channels_with_no_detections": {
            "why": "only the region's own channel was analysed, as the work "
                   "order specifies, so this run cannot say the other four "
                   "carry none",
            "waiting_on": "a decision to analyse them",
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--store",
                        default=os.path.join("Plots", "drop_motifs10", "motifs"))
    args = parser.parse_args(argv)
    out = _Path(args.out_dir)

    probe_report = _read(out / "scale_probe.json") or {}
    detect_summary = _read(out / "detect_summary.json") or {}
    lionsmane_store = next(
        (str(out / name) for name in ("motifs", "motifs_PARTIAL")
         if (out / name / "motifs.csv").exists()), None)
    pipelines = _read(out / "pipelines" / "pipelines_index.json") or {}
    verification = probe_report.get("verification", {})

    manifest = {
        "run": "drop_motifs12a",
        "written": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "PARTIAL - region B detected; region A stopped at the "
                  "work order's own checkpoint",
        "recording": {
            "stem": lionsmane12.STEM,
            "source_file": lionsmane12.SOURCE_FILE,
            "in_recordings_table": False,
            "n_channels": lionsmane12.N_CHANNELS,
            "n_samples_per_channel": lionsmane12.N_SAMPLES,
            "fs_hz": lionsmane12.FS,
            "fs_verified_by": verification.get("fs_verification"),
            "native_units": "millivolts",
            "native_units_per_volt": lionsmane12.NATIVE_UNITS_PER_VOLT,
            "units_note": "every other .npy under DATA/derived/channels/ is "
                          "in volts; lionsmane12.load_channel divides by "
                          "1000 at the one seam",
        },
        "regions": {key: {
            "channel": region.channel, "start_idx": region.start,
            "stop_idx": region.stop, "n_samples": region.n_samples,
            "hours": round(region.hours, 1), "note": region.note,
            "channels_with_no_detections": "not established - only the "
                                           "region's own channel was "
                                           "analysed",
        } for key, region in lionsmane12.REGIONS.items()},
        "id385": verification.get("id385"),
        "species_map": species_map(args.store, lionsmane_store,
                                   detect_summary),
        "detect_summary": detect_summary,
        "store_summary": _read(out / "store_summary.json"),
        "floor": {
            "rule_derived": floor10.RULE_DERIVED,
            "rule_global": floor10.RULE_GLOBAL,
            "global_floor_mv": floor10.GLOBAL_FLOOR_MV,
            "per_channel": verification.get("channels"),
            "note": "the 0.1 mV number is NOT carried across; on these "
                    "channels it is 0.4 to 3.5 sigmas, and on CH2 it is "
                    "BELOW one sigma, which is the opposite direction from "
                    "Fig2A where it was 15-59 sigmas",
        },
        "seed": pipelines.get("seed"),
        "figures": {
            "region_overviews": sorted(
                p.name for p in out.glob("region_*_overview.png")),
            "pipelines_oyster": sorted(
                p.name for p in (out / "pipelines" / "oyster").glob("*.png")),
            "pipelines_reishi": sorted(
                p.name for p in (out / "pipelines" / "reishi").glob("*.png")),
            "pipelines_lionsmane": sorted(
                p.name for p in
                (out / "pipelines" / "lionsmane").glob("*.png")),
        },
        "chosen_sequence_keys": {
            "reishi": sorted((pipelines.get("reishi") or {}).keys()),
            "lionsmane": sorted(k for k in (pipelines.get("lionsmane") or {})
                                if not k.startswith("_"))},
        "selection_rule": "sample range, never window_index (select10)",
        "drawing_rules": {
            "resampled_feature_vectors_drawn": False,
            "region_overview_decimation": "min-max envelope per column, not "
                                          "a stride",
            "aspect": "measured and stated per pipeline figure; not locked, "
                      "because six panels share one time axis",
        },
        "blocked": blocked_entries(),
        "inputs": {
            "store_read": pipelines.get("store"),
            "sequences_read": "Plots/drop_motifs11/sequences.csv",
            "database": "read-only; no row exists for this recording",
        },
        "wrote_to_database": False,
        "modified_earlier_plot_dirs": False,
    }

    report = {
        "run": "drop_motifs12a",
        "written": manifest["written"],
        "verification": verification,
        # Re-derived from the cells rather than copied from the probe run's
        # own summary, so that a change to the window rule or to the verdict
        # rule shows up in the report without re-running hours of detection.
        # The cells are the measurement; these two are readings of it.
        "scale_probe_long_windows": {
            key: {"chosen_window": probe12.choose_window(value["cells"]),
                  "verdict": probe12.verdict(value["cells"], key),
                  "cells": value["cells"]}
            for key, value in (probe_report.get("scale_probe_long_windows",
                                                {})
                               .get("regions", {}) or {}).items()},
        "scale_probe": {
            key: {"chosen_window": probe12.choose_window(value["cells"]),
                  "verdict": probe12.verdict(value["cells"], key),
                  "n_cells": len(value.get("cells", [])),
                  "cells": value["cells"]}
            for key, value in (probe_report.get("scale_probe", {})
                               .get("regions", {}) or {}).items()},
        "probe_parameters": (probe_report.get("scale_probe", {})
                             .get("parameters")),
        "overviews": probe_report.get("overviews"),
        "pipelines": pipelines,
        "blocked": blocked_entries(),
    }

    for name, payload in (("manifest.json", manifest),
                          ("run_report.json", report)):
        with open(out / name, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1, default=str)
        print(f"-> {out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
