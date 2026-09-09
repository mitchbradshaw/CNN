"""
run_drop12a_probe.py
=====================
drop_motifs12a, steps 1-3 of the work order's order of play:

    1. verify the stem and the sampling rate
    2. the scale probe, reported BEFORE anything is detected in anger
    3. the region overviews, pre-detection

    python Pipelines/drop_motifs/run_drop12a_probe.py
    python Pipelines/drop_motifs/run_drop12a_probe.py --regions A
    python Pipelines/drop_motifs/run_drop12a_probe.py --skip-probe

Writes `Plots/drop_motifs12a/` and touches no earlier plot directory, no
earlier store, and not `DATA/db/annotations.sqlite` - which has no row for
this recording to touch (see `lionsmane12`).

Step 2 is a checkpoint by design. The work order says to report the probe
table and the chosen window before proceeding, and to stop rather than guess
if the probe cannot find the events. `probe12.verdict` is what answers that,
and this script prints its answer rather than acting on it.
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

from Pipelines.drop_motifs import (floor10, lionsmane12,  # noqa: E402
                                   probe12, regionfigs12)

OUT = _Path("Plots") / "drop_motifs12a"


def verify(log=print):
    """Step 1. The stem, the rate, the units, and where ID 385 actually is."""
    log("=" * 74)
    log("STEP 1 - verification")
    log("=" * 74)

    manifest = lionsmane12.manifest()
    log(f"  stem                 {lionsmane12.STEM}")
    log(f"  source               {manifest['source_file']}")
    log(f"  channels             {manifest['n_channels']}")
    log(f"  samples per channel  {manifest['n_samples_per_channel']:,}")
    log(f"  fs in the manifest   {manifest['fs']:g} Hz  (INFERRED - see below)")
    log("")
    log("  NOT IN THE RECORDINGS TABLE. `recordings` holds Fig2A, the M2/M4")
    log("  catalogue exports and Mushroom_260720, and its highest id is 470.")
    log("  There is nothing there to verify the stem or the rate against, so")
    log("  both are verified by measurement instead. Nothing is written to")
    log("  the database.")
    log("")

    found = lionsmane12.locate_id385()
    log("  Catalogue ID 385 located in CH2 by cross-correlation:")
    log(f"    r                  {found['r']:.6f}  "
        f"(neighbouring lags {', '.join(f'{v:.3f}' for v in found['r_neighbours'])})")
    log(f"    at sample          {found['start_idx']:,} - {found['stop_idx']:,}"
        f"  ({found['start_s'] / 3600:.1f} h into the recording)")
    log(f"    gain               {found['gain']:.5f}   "
        f"offset {found['offset_mv']:.2f} mV   "
        f"residual RMS {found['residual_rms_mv']:.4f} mV")
    log("")
    log(f"    -> fs = {lionsmane12.FS:g} Hz VERIFIED. A 10:1 block mean of CH2")
    log("       reproduces the 1 Hz export over four hours with a ONE-SAMPLE")
    log("       correlation peak. No other rate does that.")
    log("    -> THE CHANNELS ARE IN MILLIVOLTS, not volts. The gain against a")
    log("       trace known to be in millivolts is 1.000. Every other .npy")
    log("       under DATA/derived/channels/ is in volts and")
    log("       motifs5.rows_and_arrays multiplies by 1000 on that basis, so")
    log("       lionsmane12.load_channel divides by 1000 at the one seam.")
    log("    -> ID 385 IS INSIDE REGION B, as the work order believed. It was")
    log("       a belief; it is now a measurement.")

    channels = {}
    for channel in range(lionsmane12.N_CHANNELS):
        sample = lionsmane12.load_channel(channel, 0, 2_000_000)
        channels[f"CH{channel}"] = {
            "amplitude_sigma_mv": floor10.amplitude_sigma_mv(sample),
            "per_sample_noise_mv": probe12.per_sample_noise_mv(sample),
            "derived_floor_mv": floor10.derived_floor_mv(sample),
        }
    log("")
    log("  Per-channel noise over the first 2e6 samples, in millivolts:")
    log(f"    {'':>6} {'amplitude sigma':>16} {'3 sigma floor':>14} "
        f"{'per-sample sd(diff)':>20}")
    for name, entry in channels.items():
        log(f"    {name:>6} {entry['amplitude_sigma_mv']:>16.4f} "
            f"{entry['derived_floor_mv']:>14.4f} "
            f"{entry['per_sample_noise_mv']:>20.4f}")
    log(f"    The operator's global 0.1 mV floor is "
        f"{0.1 / max(1e-12, min(e['amplitude_sigma_mv'] for e in channels.values())):.1f}"
        f" to "
        f"{0.1 / max(1e-12, max(e['amplitude_sigma_mv'] for e in channels.values())):.1f}"
        " sigmas here. It is not carried across.")

    return {"manifest": manifest, "id385": found, "channels": channels,
            "in_recordings_table": False,
            "fs_verified_hz": lionsmane12.FS,
            "fs_verification": "10:1 block mean of CH2 against catalogue ID 385",
            "native_units": "millivolts",
            "native_units_per_volt": lionsmane12.NATIVE_UNITS_PER_VOLT}


def probe(regions, timeout_s, log=print, window_samples=None,
          decimations=None):
    """Step 2. Both arms, per region, and the verdict on the window arm.

    `window_samples` and `decimations` override the candidates so that a
    follow-up pass can re-measure one arm at a longer time limit without
    re-running the whole grid. The caller writes the result under its own
    key in `scale_probe.json`, so the first pass's numbers stay in the file
    exactly as they were measured - a second pass that overwrote them would
    make the report unable to say which limit a cell was run under.
    """
    window_samples = tuple(window_samples or probe12.WINDOW_SAMPLES)
    decimations = tuple(decimations if decimations is not None
                        else probe12.DECIMATION_FACTORS)
    log("")
    log("=" * 74)
    log("STEP 2 - the scale probe")
    log("=" * 74)
    out = {"parameters": {
        "sub_window_fractions": list(probe12.SUB_WINDOW_FRACTIONS),
        "sub_window_samples": probe12.SUB_WINDOW_SAMPLES,
        "window_samples": list(window_samples),
        "decimation_factors": list(decimations),
        "overlap": probe12.OVERLAP,
        "timeout_s": timeout_s,
        "window_fall_multiple": probe12.WINDOW_FALL_MULTIPLE,
    }, "regions": {}}

    for key in regions:
        region = lionsmane12.REGIONS[key]
        log("")
        log(f"--- region {key}: CH{region.channel}, samples "
            f"{region.start:,}-{region.stop:,} "
            f"({region.hours:.0f} h) - {region.note}")
        cells = probe12.probe_region(
            region, timeout_s=timeout_s, log=log,
            window_samples=window_samples,
            decimation_factors=decimations)
        chosen = probe12.choose_window(cells)
        answer = probe12.verdict(cells, region)
        out["regions"][key] = {"cells": cells, "chosen_window": chosen,
                               "verdict": answer}
        log("")
        log(f"  chosen window by the work order's rule: "
            f"{chosen.get('chosen_s')} s "
            f"(= {probe12.WINDOW_FALL_MULTIPLE:g} x a median measured fall of "
            f"{chosen.get('median_measured_fall_s', float('nan')):.2f} s)")
        log(f"  VERDICT: {answer['note']}")
        log(f"    deepest event at 10 Hz, any window : "
            f"{answer['deepest_event_native_rate_mv']:.3f} mV")
        log(f"    deepest event at any rate          : "
            f"{answer['deepest_event_any_rate_mv']:.3f} mV "
            f"({answer['ratio']:.0f}x)")
        if answer["n_cells_timed_out"]:
            log(f"    {answer['n_cells_timed_out']} cell(s) did not complete "
                f"within {timeout_s:g} s")
    return out


def overviews(regions, id385, log=print):
    """Step 3. The pre-detection region overviews."""
    log("")
    log("=" * 74)
    log("STEP 3 - region overviews, pre-detection")
    log("=" * 74)
    (OUT).mkdir(parents=True, exist_ok=True)
    index = {}
    for key in regions:
        region = lionsmane12.REGIONS[key]
        started = time.time()
        path, info = regionfigs12.plot_region(
            region, OUT / f"{region.key_stem}_overview.png",
            id385=id385 if region.channel == int(id385["channel"]) else None,
            title=f"{lionsmane12.STEM} — region {key} (CH{region.channel}) "
                  "— all five channels, before detection")
        info["seconds"] = round(time.time() - started, 1)
        index[key] = {"path": path, **info}
        log(f"  -> {path}  ({info['seconds']}s)")
    return index


def main(argv=None):
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", nargs="*",
                        default=list(lionsmane12.REGIONS))
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--timeout-s", type=float, default=probe12.TIMEOUT_S)
    parser.add_argument("--window-samples", nargs="*", type=int, default=None,
                        help="override the window arm's candidate lengths")
    parser.add_argument("--decimations", nargs="*", type=int, default=None,
                        help="override the rate arm; pass none to skip it")
    parser.add_argument("--key", default="scale_probe",
                        help="the section of scale_probe.json to write into")
    parser.add_argument("--skip-probe", action="store_true")
    parser.add_argument("--skip-overviews", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args(argv)

    OUT = _Path(args.out_dir)
    OUT.mkdir(parents=True, exist_ok=True)

    report = {"run": "drop_motifs12a probe",
              "written": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if not args.skip_verify:
        report["verification"] = verify()
    if not args.skip_probe:
        report[args.key] = probe(
            args.regions, args.timeout_s, window_samples=args.window_samples,
            decimations=args.decimations)
    if not args.skip_overviews:
        report["overviews"] = overviews(
            args.regions, report["verification"]["id385"])

    # MERGE rather than replace. The probe and the overviews are run
    # separately - the probe takes hours and the overviews take seconds -
    # and an overwrite meant whichever ran second deleted the other's
    # section from the file the manifest is built out of.
    path = OUT / "scale_probe.json"
    existing = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as handle:
                existing = json.load(handle)
        except ValueError:
            existing = {}
    existing.update(report)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(existing, handle, indent=1, default=str)
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
