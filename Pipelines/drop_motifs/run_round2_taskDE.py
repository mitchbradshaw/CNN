"""
run_round2_taskDE.py
=====================
Task D (a per-channel noise floor, as a sensitivity result) and Task E
(why CH2 and CH4 fail the AAFT null).

    python Pipelines/drop_motifs/run_round2_taskDE.py

Reads the corrected RAW store - `round2_v1/motifs_raw`, before any floor -
because Task D is about which floor to apply and the refined store has
already had one applied to it. Writes

    round2_v1/TASK_D_floor.json    round2_v1/FLOOR_sensitivity.png
    round2_v1/TASK_E_power.json
    round2_v1/motifs_perchannel/   the per-channel-floored store

Task E's null numbers are READ from `nulls_v1/NULL_surrogate.json`, not
recomputed: the surrogate grid is read-only input to this round.

The per-channel floor is NOT adopted as the headline store. It is reported
as "under a per-channel floor the same comparison gives ...". The global
0.1 mV figure is the operator's statement about the instrument, and
replacing it is a decision about the instrument rather than about an
analysis.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import pinned9

_SNAPSHOT_PATH, PROVENANCE = pinned9.activate()

from Pipelines.drop_motifs import floors2, refine9, round2, round2figs1
from Working.Detection.drop_motifs import motifs5

FS = 10.0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-store", default=round2.RAW_STORE)
    parser.add_argument("--out-dir", default=round2.OUT_DIR)
    parser.add_argument("--multiplier", type=float,
                        default=floors2.MULTIPLIER)
    parser.add_argument("--decode-permutations", type=int, default=1000)
    parser.add_argument("--no-decode", action="store_true")
    args = parser.parse_args(argv)

    out = _Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # The refinement is re-run without its gate, so both floors are applied
    # to identically refined marks and the only difference between the two
    # populations is the floor itself.
    rows, snippets, manifest = motifs5.load_store(args.raw_store)
    refined, refined_snips, report = refine9.refine_store(
        rows, snippets, refine=True, dedup=True, gate=False)
    print(f"raw {len(rows)} -> refined, ungated {len(refined)}")

    noise = floors2.channel_noise(refined, refined_snips)
    floors = floors2.per_channel_floors(noise, fs=FS,
                                        multiplier=args.multiplier)
    print(f"\nper-channel slope noise and the floor it implies "
          f"({args.multiplier} sigma):")
    for channel, entry in noise.items():
        print(f"  CH{channel}  slope sigma "
              f"{entry['median_slope_sigma_mv_per_s']:.4f} mV/s  ->  floor "
              f"{floors[channel]:.4f} mV   (global {floors2.GLOBAL_FLOOR_MV})")

    calibration = {
        str(m): floors2.per_channel_floors(noise, fs=FS, multiplier=m)
        for m in floors2.CALIBRATION}

    global_rows = floors2.apply_floor(refined, None)
    channel_rows = floors2.apply_floor(refined, floors)
    before = floors2.describe(refined, "no floor")
    under_global = floors2.describe(global_rows, "global 0.1 mV")
    under_channel = floors2.describe(channel_rows,
                                     f"per-channel, {args.multiplier} sigma")

    print(f"\n{'':6s}{'no floor':>22s}{'global 0.1 mV':>26s}"
          f"{'per-channel':>26s}")
    for channel in sorted(before["per_channel"]):
        b = before["per_channel"][channel]
        g = under_global["per_channel"].get(channel, {"n": 0,
                                                      "median_depth_mv": float("nan")})
        c = under_channel["per_channel"].get(channel, {"n": 0,
                                                       "median_depth_mv": float("nan")})
        print(f"  CH{channel}  "
              f"{b['n']:5d} @ {b['median_depth_mv']:.3f} mV   "
              f"{g['n']:5d} @ {g['median_depth_mv']:.3f} mV "
              f"({100 * g['n'] / max(b['n'], 1):5.1f}%)   "
              f"{c['n']:5d} @ {c['median_depth_mv']:.3f} mV "
              f"({100 * c['n'] / max(b['n'], 1):5.1f}%)")
    print(f"  amplitude spread  "
          f"{before['amplitude_spread']:.2f}x            "
          f"{under_global['amplitude_spread']:.2f}x                    "
          f"{under_channel['amplitude_spread']:.2f}x")

    # -- the per-channel-floored store, for the decoding re-run ------------
    keep = {r["event_id"] for r in channel_rows}
    store_dir = out / "motifs_perchannel"
    motifs5.write_store(
        str(store_dir), channel_rows,
        refine9.flatten_snippets({k: v for k, v in refined_snips.items()
                                  if k in keep}),
        manifest_extra={
            "kind": "drop_motifs9_round2_perchannel_floor",
            "derived_from": args.raw_store,
            "floor_rule": (f"{args.multiplier} * median slope sigma / fs, "
                           "per channel"),
            "floors_mv": floors,
            "detector_provenance": PROVENANCE,
            "note": ("SENSITIVITY STORE. Not the headline. The global "
                     "0.1 mV floor is the operator's instrument figure."),
            "validated_against_human": False})
    print(f"\nper-channel-floored store -> {store_dir} "
          f"({len(channel_rows)} motifs)")

    figure_d = round2figs1.plot_floor_sensitivity(
        noise, floors, before, under_global, under_channel, calibration,
        out / "FLOOR_sensitivity.png", multiplier=args.multiplier)
    print(f"-> {figure_d}")

    # -- Task B re-run on the per-channel-floored store --------------------
    decode = None
    if not args.no_decode:
        print(f"\nre-running Task B's decoding on the per-channel-floored "
              f"store ({args.decode_permutations} permutations)...")
        subprocess.run(
            [sys.executable, "Pipelines/drop_motifs/run_round2_taskB.py",
             "--store", str(store_dir), "--tag", "_perchannel_floor",
             "--permutations", str(args.decode_permutations)],
            check=True)
        path = out / "TASK_B_decode_perchannel_floor.json"
        if path.is_file():
            decode = json.loads(path.read_text("utf-8"))

    payload_d = {
        "task": "Task D - a per-channel noise floor",
        "status": ("SENSITIVITY RESULT. The global 0.1 mV floor remains the "
                   "headline store."),
        "detector_provenance": PROVENANCE,
        "rule": {
            "formula": "floor_c = multiplier * median_slope_sigma_c / fs",
            "multiplier": float(args.multiplier),
            "why": ("slope sigma is the detector's own noise estimator "
                    "(MAD of the derivative, the units the slope gate is "
                    "measured in); dividing by fs converts a slope noise "
                    "into the depth one sample of pure noise would "
                    "produce, so the quantity compared to a drop depth is "
                    "a depth. 3.0 is the conventional three-sigma "
                    "detection threshold and was fixed before the "
                    "per-channel numbers were computed."),
            "calibration_other_multipliers": calibration,
        },
        "per_channel_slope_noise": noise,
        "floors_mv": floors,
        "global_floor_mv": floors2.GLOBAL_FLOOR_MV,
        "populations": {"no_floor": before, "global": under_global,
                        "per_channel": under_channel},
        "store": str(store_dir),
        "decode_under_per_channel_floor": (
            {"headline": decode["headline"], "verdict": decode["verdict"]}
            if decode else None),
        "figure": figure_d,
    }
    (out / "TASK_D_floor.json").write_text(
        json.dumps(payload_d, indent=2, default=float), encoding="utf-8")

    # ---------------------------------------------------------------- E --
    print("\nTask E - why CH2 and CH4 do not exceed the AAFT null")
    nulls = json.loads(
        _Path(round2.NULLS_V1, "NULL_surrogate.json").read_text("utf-8"))
    detections = nulls["tests"]["detections"]

    notes = {}
    for channel in sorted(noise):
        summary = detections.get(f"CH{channel}", {}).get("aaft")
        if summary is None:
            continue
        population = under_global["per_channel"].get(channel, {})
        note = floors2.power_note(
            channel, summary,
            noise_sigma=noise[channel]["median_slope_sigma_mv_per_s"],
            median_depth=population.get("median_depth_mv", float("nan")),
            n_events=population.get("n", 0), fs=FS)
        notes[f"CH{channel}"] = note
        marker = "  <-- " if note["p"] > 0.05 else "      "
        print(f"{marker}CH{channel}  n = {note['n_events_corrected_store']:4d}  "
              f"depth/noise = {note['snr_proxy_depth_over_noise']:5.1f}x  "
              f"observed {note['observed_detections_round1']:.0f} vs null "
              f"median {note['null_median']:.1f} "
              f"[{note['null_q1']:.0f}-{note['null_q3']:.0f}]  "
              f"p = {note['p']:.4f}")
        if note["p"] > 0.05:
            print(f"          {note['verdict'].upper()}: {note['gloss']}")

    payload_e = {
        "task": "Task E - CH2 and CH4 against the AAFT null",
        "question": ("is 'indistinguishable from coloured noise' or 'too "
                     "few events to tell' the right reading for each?"),
        "null_source": str(_Path(round2.NULLS_V1, "NULL_surrogate.json")),
        "null_is_read_only": True,
        "detector_provenance": PROVENANCE,
        "per_channel": notes,
        "failing_channels": [k for k, v in notes.items() if v["p"] > 0.05],
        "paragraph": _paragraph(notes),
    }
    (out / "TASK_E_power.json").write_text(
        json.dumps(payload_e, indent=2, default=float), encoding="utf-8")
    print(f"\n{payload_e['paragraph']}")
    print(f"\n-> {out}")
    return 0


def _paragraph(notes):
    """Task E as the paragraph the paper needs, built from the numbers."""
    failing = {k: v for k, v in notes.items() if v["p"] > 0.05}
    if not failing:
        return "Every channel exceeds its AAFT null."

    parts = []
    for name, note in sorted(failing.items()):
        parts.append(
            f"{name} is {note['verdict']}: {note['gloss']}")
    passing = [k for k, v in notes.items() if v["p"] <= 0.05]
    return (
        f"{', '.join(sorted(failing))} do not exceed the AAFT "
        f"phase-randomisation null, while {', '.join(sorted(passing))} do. "
        + " ".join(parts)
        + " The distinction matters because the two readings license "
        "different sentences: a channel that is indistinguishable from "
        "coloured noise cannot be rescued by collecting more of it, "
        "whereas one that is merely underpowered can.")


if __name__ == "__main__":
    raise SystemExit(main())
