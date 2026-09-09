"""
run_drop12a_detect.py
======================
Task 1's production run: detect over one or both Lion's mane regions with
the window the scale probe chose, under both floor rules.

    python Pipelines/drop_motifs/run_drop12a_detect.py --regions B
    python Pipelines/drop_motifs/run_drop12a_detect.py --regions B --window-s 120

Writes `Plots/drop_motifs12a/by_region/<key>/motifs[_globalfloor]/` and, when
every region in `lionsmane12.REGIONS` has been detected, the pooled
Lion's mane sub-store. It does NOT write the top-level `motifs/`; that is
`run_drop12a_store.py`'s job, because the pooled store also carries oyster
and reishi and must not exist in a half-built state.

The window comes from the probe, and the run refuses without it
----------------------------------------------------------------
`--window-s` is read from `scale_probe.json`'s verdict for the region unless
it is given explicitly, and a region whose verdict says the native rate does
NOT frame its events is refused rather than run. That is the work order's
own instruction - "if the probe finds nothing at any candidate length, stop
and say so rather than proceeding with a guess" - made executable, so the
decision cannot be lost by someone re-running this script later.

`--force` overrides the refusal, and prints what it is overriding.

Everything else follows the Reishi run exactly
-----------------------------------------------
50% overlap, the four drop passes, no inverted pass, cross-window dedup on
the best-framed rule, then the depth re-measurement. That is
`passes9.detect_sliding` with `detect10`'s parameterisation, called with one
addition: `base_offset`, because a region is a slice of a channel and the
store's indices have to be absolute in the channel. See `passes9`.
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

from Pipelines.drop_motifs import (corpora10, detect10, floor10,  # noqa: E402
                                   lionsmane12, passes7, passes9, probe12)
from Working.Detection.drop_motifs import motifs5  # noqa: E402

OUT = _Path("Plots") / "drop_motifs12a"


def window_from_probe(region_key, probe_path, log=print):
    """`(window_s, verdict)` for one region, out of `scale_probe.json`.

    Re-derives both from the recorded cells rather than reading the summary
    the probe run wrote, so a change to either rule is picked up without
    re-running hours of detection.
    """
    with open(probe_path, encoding="utf-8") as handle:
        report = json.load(handle)
    section = (report.get("scale_probe") or {}).get("regions") or {}
    if region_key not in section:
        raise SystemExit(f"{probe_path} has no probe for region {region_key}")
    cells = section[region_key]["cells"]
    chosen = probe12.choose_window(cells)
    answer = probe12.verdict(cells, region_key)
    return chosen, answer


def detect_region(region, window_s, *, floor_rule, log=print):
    """One region, one floor rule. `(rows, arrays, summary)`."""
    region = lionsmane12.REGIONS[region] if isinstance(region, str) else region
    started = time.time()
    x, offset = lionsmane12.load_region(region)

    def progress(done, total):
        if done % 250 == 0 or done == total:
            log(f"      window {done}/{total} "
                f"({time.time() - started:.0f}s elapsed)")

    rows, arrays, info = passes9.detect_sliding(
        x, lionsmane12.FS,
        catalogue_id=region.catalogue_id,
        recording_id=lionsmane12.RECORDING_ID,
        source_file=lionsmane12.SOURCE_FILE,
        channel=region.channel,
        window_s=float(window_s), overlap=detect10.OVERLAP,
        span_label=f"{lionsmane12.STEM} {region.label}",
        span_key=region.key_stem,
        max_passes=detect10.MAX_PASSES,
        fine=detect10.PASSES["fine"],
        sensitive=detect10.PASSES["sensitive"],
        micro=detect10.PASSES["micro"],
        # A region is a SLICE. Without this every index in the store is
        # short by `region.start` and points at the wrong part of the
        # recording while looking perfectly well-formed.
        base_offset=offset,
        progress=progress)

    labelled = [corpora10.label_row(r, corpus=lionsmane12.CORPUS,
                                    species=lionsmane12.SPECIES,
                                    framing=corpora10.FRAMING_SLIDING,
                                    fs=lionsmane12.FS) for r in rows]
    # The floor is derived from THIS REGION's own noise, as drop_motifs10
    # derives it per span and per channel - not from the whole channel and
    # not from the recording. The two regions are on different electrodes
    # with an order of magnitude between their noise (CH2 0.257 mV against
    # CH3 0.044 mV), so one floor for both would be the same accidental
    # per-corpus tuning `floor10` exists to avoid.
    floor_mv, rule = floor10.floor_for(x, rule=floor_rule)
    kept, rejected = floor10.apply_floor(labelled, floor_mv, rule=rule)

    keep_ids = {r["event_id"] for r in kept}
    arrays = {k: v for k, v in arrays.items() if k.split("__")[0] in keep_ids}

    summary = dict(
        region=region.key, channel=region.channel,
        catalogue_id=region.catalogue_id,
        recording_id=lionsmane12.RECORDING_ID,
        source_file=lionsmane12.SOURCE_FILE,
        corpus=lionsmane12.CORPUS, species=lionsmane12.SPECIES,
        framing=corpora10.FRAMING_SLIDING, fs=lionsmane12.FS,
        region_start_idx=region.start, region_stop_idx=region.stop,
        n_samples=int(len(x)), hours=round(region.hours, 2),
        window_s=float(window_s),
        window_samples=int(round(float(window_s) * lionsmane12.FS)),
        overlap=detect10.OVERLAP,
        n_before_floor=len(labelled), n_after_floor=len(kept),
        n_below_floor=len(rejected),
        depth_floor_mv=floor_mv, floor_rule=rule,
        amplitude_sigma_mv=floor10.amplitude_sigma_mv(x),
        per_sample_noise_mv=probe12.per_sample_noise_mv(x),
        per_pass_kept={k: sum(1 for r in kept if r["pass_key"] == k)
                       for k in passes7.PASS_ORDER},
        seconds=round(time.time() - started, 1))
    # `info` repeats `window_s` and `overlap`, which are already set above
    # from what was ASKED for rather than from what the detector resolved.
    # Splatting it in raised `dict() got multiple values for window_s` after
    # the detection had already run - fifteen minutes of work thrown away by
    # a name collision in the reporting. Merged rather than splatted, and
    # the keys set above win.
    for key, value in info.items():
        if key != "per_window":
            summary.setdefault(key, value)
    summary["n_windows_detail"] = len(info["per_window"])
    return kept, arrays, summary


def write(out_dir, rows, arrays, extra=None):
    manifest = {
        "kind": "drop_motifs12a",
        "detector": "detect5 + passes9 sliding, drops only, four passes",
        "corpus": lionsmane12.CORPUS, "species": lionsmane12.SPECIES,
        "fs": lionsmane12.FS,
        "recording_stem": lionsmane12.STEM,
        "recording_id": lionsmane12.RECORDING_ID,
        "recording_id_note": "a SENTINEL, not a recordings.id - this "
                             "recording has no row in the recordings table",
        "native_units": "millivolts (divided by 1000 on load)",
        "indices": "absolute in the channel (passes9 base_offset)",
        "max_passes": detect10.MAX_PASSES,
        "overlap": detect10.OVERLAP,
        "passes": detect10.PASSES,
        "floor_sigmas": floor10.FLOOR_SIGMAS,
        "validated_against_human": False,
    }
    manifest.update(extra or {})
    motifs5.write_store(str(out_dir), rows, arrays, manifest_extra=manifest)
    return out_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regions", nargs="*", default=["B"])
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--window-s", type=float, default=None,
                        help="override the window the probe chose")
    parser.add_argument("--floor-rule", default=None,
                        choices=[floor10.RULE_DERIVED, floor10.RULE_GLOBAL])
    parser.add_argument("--force", action="store_true",
                        help="run a region whose probe verdict refuses it")
    args = parser.parse_args(argv)

    out = _Path(args.out_dir)
    probe_path = out / "scale_probe.json"
    rules = ([args.floor_rule] if args.floor_rule
             else [floor10.RULE_DERIVED, floor10.RULE_GLOBAL])
    index = {}

    for key in args.regions:
        region = lionsmane12.REGIONS[key]
        chosen, answer = window_from_probe(key, probe_path)
        window_s = args.window_s or chosen.get("chosen_s")

        print(f"\n=== region {key}: CH{region.channel}, "
              f"{region.n_samples:,} samples ({region.hours:.0f} h)")
        print(f"  probe verdict: {answer['note']}")
        print(f"  probe window : {chosen.get('chosen_s')} s"
              + (f"   OVERRIDDEN to {window_s} s" if args.window_s else ""))

        if not answer["window_arm_measures_the_events"] and not args.force:
            print(f"  REFUSED. The probe says the native rate does not frame "
                  f"region {key}'s events consistently. Re-run with --force "
                  f"only if that has been decided deliberately; see "
                  f"PROVENANCE.md.")
            index[key] = {"detected": False, "refused": True,
                          "verdict": answer, "chosen_window": chosen}
            continue
        if not window_s:
            print("  REFUSED. The probe chose no window.")
            index[key] = {"detected": False, "refused": True,
                          "verdict": answer, "chosen_window": chosen}
            continue

        entry = {"detected": True, "verdict": answer,
                 "chosen_window": chosen, "window_s": float(window_s),
                 "stores": {}}
        for rule in rules:
            tag = "" if rule == floor10.RULE_DERIVED else "_globalfloor"
            print(f"  -- floor rule {rule}")
            rows, arrays, summary = detect_region(region, window_s,
                                                  floor_rule=rule)
            sub = out / "by_region" / key / f"motifs{tag}"
            write(sub, rows, arrays,
                  extra={"region": key, "window_s": float(window_s),
                         "floor_rule": rule,
                         "depth_floor_mv": summary["depth_floor_mv"]})
            print(f"     -> {sub}  ({len(rows)} motifs from "
                  f"{summary['n_before_dedup']} raw, "
                  f"{summary['n_below_floor']} below a "
                  f"{summary['depth_floor_mv']:.4f} mV floor, "
                  f"{summary['seconds']}s)")
            entry["stores"][rule] = {"path": str(sub), **summary}
        index[key] = entry

    path = out / "detect_summary.json"
    existing = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as handle:
                existing = json.load(handle)
        except ValueError:
            existing = {}
    existing.update(index)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(existing, handle, indent=1, default=str)
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
