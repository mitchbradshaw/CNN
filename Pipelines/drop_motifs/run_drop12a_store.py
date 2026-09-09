"""
run_drop12a_store.py
=====================
Task 2. Assemble `Plots/drop_motifs12a/motifs/` - oyster and reishi carried
over from drop_motifs10 unchanged, plus the Lion's mane rows this run
detected - and re-save the region overviews with the events shaded.

    python Pipelines/drop_motifs/run_drop12a_store.py
    python Pipelines/drop_motifs/run_drop12a_store.py --allow-partial

What goes in, and what is left out
-----------------------------------
    oyster        every row from drop_motifs10, unchanged. The 15 catalogue
                  IDs are the complete oyster set; no new detection was run.
    reishi_10hz   every row from drop_motifs10, unchanged.
    lionsmane_10hz  this run's rows, from `by_region/<key>/motifs/`.

    sp385         NOT carried. It is the 1 Hz 4 h excerpt of CH2 that the
                  Lion's mane detections replace - and this run measured
                  exactly where it sits (CH2 15,777,590-15,921,600, r =
                  0.9995), so the replacement is a demonstrated one rather
                  than an assumed one.
    reishi_1hz    NOT carried. It existed only as a rate control against a
                  1 Hz Lion's mane corpus; with Lion's mane at 10 Hz it has
                  no job.

Both retired sets stay in `Plots/drop_motifs10/` untouched. This run writes
a new store and modifies nothing.

Why it refuses a partial Lion's mane
-------------------------------------
A store that says `species = lionsmane` while holding only one of the two
operator-chosen regions is the most expensive kind of wrong: every count,
every floor and every cross-species figure downstream would be computed over
it without any of them being able to tell. `--allow-partial` writes it
anyway and stamps `partial: true` plus the missing regions into the manifest
and into the store's own directory name, so it cannot be mistaken for the
finished article.
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

from Pipelines.drop_motifs import (corpora10, floor10, lionsmane12,  # noqa: E402
                                   regionfigs12)
from Working.Detection.drop_motifs import motifs5  # noqa: E402

OUT = _Path("Plots") / "drop_motifs12a"
SOURCE_STORE = _Path("Plots") / "drop_motifs10"

# The corpora carried forward from drop_motifs10, unchanged.
CARRIED = (corpora10.CORPUS_OYSTER, corpora10.CORPUS_REISHI_10HZ)
# ...and the two the work order retires.
RETIRED = (corpora10.CORPUS_385, corpora10.CORPUS_REISHI_1HZ)


def load_carried(store_dir, log=print):
    """The oyster and reishi rows and their arrays, from drop_motifs10."""
    rows, snippets, _manifest = motifs5.load_store(str(store_dir))
    keep = [r for r in rows if r.get("corpus") in CARRIED]
    dropped = {}
    for row in rows:
        if row.get("corpus") not in CARRIED:
            dropped[row["corpus"]] = dropped.get(row["corpus"], 0) + 1
    arrays = {}
    for row in keep:
        for field, values in (snippets.get(row["event_id"]) or {}).items():
            arrays[f"{row['event_id']}__{field}"] = values
    log(f"  carried {len(keep)} rows from {store_dir}; "
        f"retired {dropped}")
    return keep, arrays, dropped


def load_lionsmane(out_dir, regions, tag="", log=print):
    """This run's Lion's mane rows, per region, and which regions are missing."""
    rows, arrays, present, missing = [], {}, [], []
    for key in regions:
        sub = out_dir / "by_region" / key / f"motifs{tag}"
        if not (sub / "motifs.csv").exists():
            missing.append(key)
            continue
        region_rows, snippets, _manifest = motifs5.load_store(str(sub))
        for row in region_rows:
            for field, values in (snippets.get(row["event_id"]) or {}).items():
                arrays[f"{row['event_id']}__{field}"] = values
        rows.extend(region_rows)
        present.append(key)
        log(f"  region {key}: {len(region_rows)} rows from {sub}")
    return rows, arrays, present, missing


def species_map(rows, lionsmane_rows, summaries):
    """The table the work order asks the manifest to state, with the caveat.

    Every count is counted from the rows in hand. The sampling rate and the
    framing are stated per species because the comparison the whole run
    exists to make depends on them, and the note says which comparisons the
    table does and does not license.
    """
    by_corpus = {}
    for row in rows:
        key = row.get("corpus")
        entry = by_corpus.setdefault(key, {
            "corpus": key, "species": row.get("species"),
            "fs_hz": float(row.get("fs", 0.0)),
            "framing": row.get("framing"), "n_events": 0,
            "channels": set()})
        entry["n_events"] += 1
        entry["channels"].add(int(row["channel"]))
    for entry in by_corpus.values():
        entry["channels"] = sorted(entry["channels"])

    return {
        "by_corpus": by_corpus,
        "retired": {
            "sp385": "the 1 Hz 4 h excerpt of this same Lion's mane "
                     "recording. Measured to lie at CH2 15,777,590-"
                     "15,921,600 (r = 0.9995), so the 10 Hz detections that "
                     "replace it cover the same events and more.",
            "reishi_1hz": "the rate control against a 1 Hz Lion's mane "
                          "corpus; with Lion's mane at 10 Hz it has no job.",
            "both_remain_in": "Plots/drop_motifs10/",
        },
        "what_this_licenses": (
            "Reishi and Lion's mane are now both 10 Hz and both "
            "sliding-window, so a Reishi/Lion's mane comparison is free of "
            "the sampling-rate confound that undermined drop_motifs10's "
            "cross-species result. Oyster remains 1 Hz and span-framed, so "
            "any comparison involving Oyster is NOT."),
        "what_it_does_not_license": (
            "Matching the sampling rate does not match the RESOLUTION. "
            "Reishi's median fall is about 7 samples; Lion's mane region B's "
            "is about 8-11 and region A's events are hundreds of samples "
            "long. drop_motifs10 6.3 measured that n_samples_in_fall ALONE "
            "decodes species at 0.575 against a 0.333 chance, so the "
            "samples-per-fall distribution has to be quoted beside any "
            "species result from this store."),
        "detection_summaries": summaries,
    }


def write_store(out_dir, rows, arrays, extra=None):
    manifest = {
        "kind": "drop_motifs12a",
        "built_from": {
            "carried_unchanged": list(CARRIED),
            "carried_from": str(SOURCE_STORE / "motifs"),
            "detected_here": [lionsmane12.CORPUS],
            "retired": list(RETIRED),
        },
        "floor_sigmas": floor10.FLOOR_SIGMAS,
        "note": "every row carries depth_floor_mv and floor_rule; the floors "
                "differ per corpus and per region by design (floor10)",
    }
    manifest.update(extra or {})
    motifs5.write_store(str(out_dir), rows, arrays, manifest_extra=manifest)
    return out_dir


def resave_overviews(out_dir, rows, id385, log=print):
    """Step 6: the region overviews again, with the detected events shaded."""
    index = {}
    for key, region in lionsmane12.REGIONS.items():
        mine = [r for r in rows
                if int(r["channel"]) == region.channel
                and region.start <= int(r["onset_idx"]) < region.stop]
        if not mine:
            log(f"  region {key}: no events, overview not re-saved")
            continue
        floors = sorted({round(float(r["depth_floor_mv"]), 4) for r in mine})
        path, info = regionfigs12.plot_region(
            region, out_dir / f"{region.key_stem}_overview.png", rows=mine,
            id385=id385 if region.channel == int((id385 or {}).get("channel", -1))
                  else None,
            title=f"{lionsmane12.STEM} — region {key} (CH{region.channel}) "
                  f"— all five channels, {len(mine)} detected events shaded",
            floor_note=f"depth floor {', '.join(f'{f:g}' for f in floors)} mV "
                       f"({mine[0]['floor_rule']}) — quoted with the count, "
                       "because it is derived per region from that region's "
                       "own noise")
        index[key] = {"path": path, "n_events": len(mine), **info}
        log(f"  -> {path}  ({len(mine)} events shaded)")
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--source-store", default=str(SOURCE_STORE))
    parser.add_argument("--regions", nargs="*",
                        default=list(lionsmane12.REGIONS))
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--skip-overviews", action="store_true")
    args = parser.parse_args(argv)

    out = _Path(args.out_dir)
    source = _Path(args.source_store)
    summary = {"written": time.strftime("%Y-%m-%dT%H:%M:%S"), "stores": {}}

    detect_summary = {}
    if (out / "detect_summary.json").exists():
        with open(out / "detect_summary.json", encoding="utf-8") as handle:
            detect_summary = json.load(handle)

    id385 = None
    if (out / "scale_probe.json").exists():
        with open(out / "scale_probe.json", encoding="utf-8") as handle:
            id385 = (json.load(handle).get("verification") or {}).get("id385")

    for tag, label in (("", floor10.RULE_DERIVED),
                       ("_globalfloor", floor10.RULE_GLOBAL)):
        print(f"\n=== floor rule: {label} ===")
        carried, carried_arrays, dropped = load_carried(source / f"motifs{tag}")
        lm_rows, lm_arrays, present, missing = load_lionsmane(
            out, args.regions, tag=tag)

        if missing and not args.allow_partial:
            print(f"  REFUSED: Lion's mane region(s) {missing} not detected. "
                  f"Re-run with --allow-partial to write a store that says so "
                  f"in its own name and manifest.")
            summary["stores"][label] = {"written": False,
                                        "missing_regions": missing}
            continue

        rows = carried + lm_rows
        arrays = dict(carried_arrays)
        arrays.update(lm_arrays)
        partial = bool(missing)
        name = f"motifs{tag}" + ("_PARTIAL" if partial else "")
        target = out / name

        write_store(target, rows, arrays, extra={
            "floor_rule": label,
            "partial": partial,
            "lionsmane_regions_present": present,
            "lionsmane_regions_missing": missing,
            "retired_counts_in_source": dropped,
            "species_map": species_map(rows, lm_rows,
                                       detect_summary),
        })
        print(f"  -> {target}  ({len(rows)} motifs: "
              f"{len(carried)} carried, {len(lm_rows)} Lion's mane)"
              + ("  [PARTIAL]" if partial else ""))
        summary["stores"][label] = {
            "written": True, "path": str(target), "n_motifs": len(rows),
            "n_carried": len(carried), "n_lionsmane": len(lm_rows),
            "partial": partial, "regions_present": present,
            "regions_missing": missing}

        if tag == "" and not args.skip_overviews:
            print("\n  re-saving the region overviews with events shaded")
            summary["overviews"] = resave_overviews(out, lm_rows, id385)

    path = out / "store_summary.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=1, default=str)
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
