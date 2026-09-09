"""
run_round2_store.py
====================
Round 2, Task A steps 1-2: re-detect and re-refine with the key-collision
fix in place, and report what the 22 all-zero motifs turned into.

    python Pipelines/drop_motifs/run_round2_store.py

Writes `Plots/drop_motifs9_fig2a/round2_v1/`:

    motifs_raw/          the re-detected store (the fixed equivalent of
                         `Plots/drop_motifs9_fig2a/motifs`)
    motifs/              the refined store   (of `refined_v2/motifs`)
    TASK_A_store.json    what changed, event by event where it matters

`nulls_v1/` and `refined_v2/` are read-only inputs and are not touched.

THE DETECTOR IS PINNED, AND WHY THAT IS NOT OPTIONAL
-----------------------------------------------------
drop_motifs10 is being written against `passes6`, `passes7`, `passes9`,
`detect5`, `motifs5` and `cluster` in this same checkout. Three runs of
this command over one evening produced 1736, then 1676, then 2463 raw
motifs, purely because the shared files changed underneath it. None of
those differences are round 2's.

So this run does not import the working tree's detector. `pinned9.activate`
builds a snapshot - tracked modules from the commit the shipped store was
built at, untracked ones from the tree with drop_motifs10's own isolation
switches off - applies round 2's key fix to THAT, and puts it ahead of the
working tree on `sys.path`. Nothing in the working tree is edited, stashed
or reverted; drop_motifs10's author keeps their files.

`_check_against_shipped` is what makes the pin a fact rather than a hope.
The key fix changes which ARRAY a surviving row carries and cannot change
how many rows survive - the cross-window dedup ranks on framing and onset
and never looks at a key - so the re-detected per-channel counts must equal
the shipped `run_summary.json` EXACTLY. They do: 312 / 405 / 391 / 323 /
305, with per-pass composition matching too, and zero length mismatches.
Any drift is a hard stop, not a store.

The detector parameters are the shipped ones, read out of the shipped
`run_summary.json` rather than retyped: 50 s windows at 50% overlap,
`max_passes=3`, fine + sensitive + micro, drops only, then
`refine9.refine_store(min_depth_mv=0.1)`.
"""

import importlib.util
import json
import os
import sqlite3
import sys
import time
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _pin():
    """Activate the pinned detector BEFORE anything imports it.

    Loaded by path rather than by `from Pipelines.drop_motifs import
    pinned9`, because that import would create the `Pipelines.drop_motifs`
    package from the working tree first and every later import would come
    from there - which is the exact mixture this module exists to avoid.
    """
    spec = importlib.util.spec_from_file_location(
        "_pinned9", _REPO_ROOT / "Pipelines" / "drop_motifs" / "pinned9.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path, provenance = module.activate()
    return module, path, provenance


pinned9, _SNAPSHOT_PATH, PROVENANCE = _pin()

import numpy as np

from Pipelines.drop_motifs import passes7, passes9, refine9
from Working.Detection.drop_motifs import motifs5

DB = os.path.join("DATA", "db", "annotations.sqlite")
SOURCE_FILE = "Fig2A_dt0p1.csv"
SHIPPED = os.path.join("Plots", "drop_motifs9_fig2a")
OUT = os.path.join(SHIPPED, "round2_v1")
CATALOGUE_ID_BASE = 900


def _shipped_params():
    summary = json.loads(_Path(SHIPPED, "run_summary.json").read_text("utf-8"))
    first = summary["channels"][0]
    return float(first["window_s"]), float(first["overlap"])


def _switches():
    """drop_motifs10's isolation switches, kept only where they exist.

    A switch is dropped when the pinned module predates it - the pinned
    `passes7` has no `dedup_scale_by_fs` because at that commit the fs
    scaling does not exist, so there is nothing to switch off. Passing it
    anyway would be swallowed by a `**kwargs` and read as if it had been
    honoured.
    """
    import inspect

    signatures = {
        "passes9.detect_sliding": set(
            inspect.signature(passes9.detect_sliding).parameters),
        "passes7.detect_multiscale": set(
            inspect.signature(passes7.detect_multiscale).parameters),
    }
    used, absent = {}, {}
    for switch, entry in pinned9.SWITCH_PINS.items():
        if switch in signatures[entry["owner"]]:
            used[switch] = entry["value"]
        else:
            absent[switch] = (
                f"not present on the pinned {entry['owner']} - the "
                "correction it disables postdates the pinned commit")
    return used, absent


def _check_against_shipped(per_channel):
    """The re-detected raw counts must equal the shipped ones, exactly."""
    summary = json.loads(_Path(SHIPPED, "run_summary.json").read_text("utf-8"))
    shipped = {int(c["channel"]): int(c["n_motifs"])
               for c in summary["channels"]}
    passes = {int(c["channel"]): dict(c["per_pass_kept"])
              for c in summary["channels"]}
    got = {int(c["channel"]): int(c["n_motifs"]) for c in per_channel}
    got_passes = {int(c["channel"]): dict(c["per_pass_kept"])
                  for c in per_channel}

    drift = {ch: {"shipped": shipped.get(ch), "got": got.get(ch)}
             for ch in sorted(shipped) if shipped.get(ch) != got.get(ch)}
    if drift:
        raise SystemExit(
            "STOP: the re-detected store does not reproduce the shipped "
            f"counts. {drift}. The key fix cannot move a count, so an "
            "unpinned drop_motifs10 change is still active. Do not build "
            "round 2 on this store.")

    pass_drift = {ch: {"shipped": passes[ch], "got": got_passes[ch]}
                  for ch in sorted(passes)
                  if {k: int(v) for k, v in passes[ch].items()}
                  != {k: int(v) for k, v in got_passes[ch].items()}}
    return {"shipped_per_channel": shipped, "reproduced": True,
            "per_pass_matches": not pass_drift,
            "per_pass_drift": pass_drift}


def main():
    switches, absent = _switches()
    print(f"pinned detector: {_SNAPSHOT_PATH}")
    print(f"  {len(PROVENANCE['pinned_to_commit'])} modules from commit "
          f"{PROVENANCE['commit']}, "
          f"{len(PROVENANCE['from_working_tree'])} from the working tree "
          f"(never committed)")
    for key, entry in PROVENANCE["constant_pins"].items():
        print(f"  {key}: {entry['was']} -> {entry['pinned_to']}  "
              f"({entry['why']})")
    for switch, value in switches.items():
        print(f"  {pinned9.SWITCH_PINS[switch]['owner']}({switch}={value})")
    for switch, why in absent.items():
        print(f"  {switch}: not applicable - {why}")
    fixes = sorted({w for entry in PROVENANCE["pinned_to_commit"].values()
                    for w in (entry.get("key_fix") or ())})
    print("  round 2 key fix applied to the snapshot:")
    for what in fixes:
        print(f"    - {what}")

    window_s, overlap = _shipped_params()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    recordings = conn.execute(
        "SELECT id, channel, npy_path, fs FROM recordings "
        "WHERE source_file = ? ORDER BY channel", (SOURCE_FILE,)).fetchall()

    all_rows, all_arrays, per_channel = [], {}, []
    print()
    for rec in recordings:
        channel = int(rec["channel"])
        catalogue_id = CATALOGUE_ID_BASE + channel
        x = np.asarray(np.load(rec["npy_path"], mmap_mode="r"), dtype=float)
        started = time.time()
        rows, arrays, info = passes9.detect_sliding(
            x, float(rec["fs"]), catalogue_id=catalogue_id,
            recording_id=int(rec["id"]),
            source_file=os.path.basename(rec["npy_path"]), channel=channel,
            window_s=window_s, overlap=overlap,
            span_label=f"{SOURCE_FILE} CH{channel}",
            span_key=f"id{catalogue_id:03d}",
            max_passes=3, fine=True, sensitive=True, micro=True,
            **switches)
        all_rows.extend(rows)
        all_arrays.update(arrays)
        per_channel.append({
            "channel": channel, "catalogue_id": catalogue_id,
            "recording_id": int(rec["id"]), "n_motifs": len(rows),
            "seconds": round(time.time() - started, 1),
            **{k: v for k, v in info.items() if k != "per_window"}})
        print(f"  CH{channel}: {len(rows)} motifs "
              f"({round(time.time() - started, 1)} s)")

    reproduction = _check_against_shipped(per_channel)
    print(f"\nreproduces the shipped per-channel counts exactly: "
          f"{reproduction['shipped_per_channel']}")
    print(f"per-pass composition matches too: "
          f"{reproduction['per_pass_matches']}")

    # -- the invariant the whole round exists to restore --------------------
    bad = [r["event_id"] for r in all_rows
           if len(all_arrays[f"{r['event_id']}__detrended_mv"])
           != int(r["snippet_end_idx"]) - int(r["snippet_start_idx"])]
    print(f"length mismatches in the re-detected store: {len(bad)} "
          f"(shipped: 208 of 1736)")

    raw_dir = _Path(OUT, "motifs_raw")
    raw_dir.parent.mkdir(parents=True, exist_ok=True)
    motifs5.write_store(str(raw_dir), all_rows, all_arrays, manifest_extra={
        "kind": "drop_motifs9_round2_raw",
        "detector": "detect5 + passes9 (sliding window, drops only), pinned",
        "source_file": SOURCE_FILE,
        "window_s": window_s, "overlap": overlap,
        "key_format": "id{cat}_r{rec}_{pass}_{onset}_w{window}",
        "fix": "motif_key carries the window index",
        "detector_provenance": PROVENANCE,
        "switches_applied": switches,
        "switches_not_applicable": absent,
        "reproduces_shipped_counts": reproduction,
        "n_length_mismatch": len(bad),
        "per_channel": per_channel,
        "validated_against_human": False})
    print(f"raw store -> {raw_dir}  ({len(all_rows)} motifs)")

    rows, snippets, manifest = motifs5.load_store(str(raw_dir))
    rows, snippets, report = refine9.refine_store(
        rows, snippets, min_depth_mv=refine9.MIN_DROP_DEPTH_MV)
    flat = refine9.flatten_snippets(snippets)
    bad_ref = [r["event_id"] for r in rows
               if len(flat[f"{r['event_id']}__detrended_mv"])
               != int(r["snippet_end_idx"]) - int(r["snippet_start_idx"])]
    print(f"\nrefinement: {report['n_in']} -> {report['n_out']}  "
          f"(dedup {report['n_duplicates_dropped']}, "
          f"floor {report['n_below_noise_floor']})")
    print(f"length mismatches in the refined store: {len(bad_ref)} "
          f"(shipped: 30 of 1058)")

    store_dir = _Path(OUT, "motifs")
    motifs5.write_store(str(store_dir), rows, flat, manifest_extra={
        "kind": "drop_motifs9_round2_refined",
        "detector": "detect5 + passes9 + refine9 (marks, dedup, floor)",
        "derived_from": str(raw_dir),
        "min_depth_mv": float(refine9.MIN_DROP_DEPTH_MV),
        "detector_provenance": PROVENANCE,
        "refine_report": report,
        "n_length_mismatch": len(bad_ref),
        "validated_against_human": False})
    print(f"refined store -> {store_dir}  ({len(rows)} motifs)")

    # -- what happened to the 22 -------------------------------------------
    old_rows, old_snips, _ = motifs5.load_store(
        os.path.join(SHIPPED, "refined_v2", "motifs"))
    old_bad = []
    for r in old_rows:
        arrays = old_snips.get(r["event_id"])
        if arrays is None:
            continue
        got = len(arrays["detrended_mv"])
        want = int(r["snippet_end_idx"]) - int(r["snippet_start_idx"])
        if got != want:
            start = int(r["snippet_start_idx"])
            onset = int(np.clip(int(r["onset_idx"]) - start, 0, got - 1))
            trough = int(np.clip(int(r["trough_idx"]) - start, onset + 1, got))
            old_bad.append({
                "event_id": r["event_id"], "channel": int(r["channel"]),
                "onset_idx": int(r["onset_idx"]),
                "stored_len": got, "claimed_len": want,
                "wave_len": max(trough - onset, 2),
                "one_sample_fall": bool((trough - onset) < 2)})

    # An event is "recovered" when the corrected store holds a drop at the
    # same PLACE on the same channel, carrying a waveform of two samples or
    # more. Place, not key, and place with a tolerance:
    #
    #   - the key changed by construction, so it cannot be the identity;
    #   - `onset_idx` cannot be the identity exactly either. These 30 rows
    #     are precisely the ones refine9 refined against the WRONG array,
    #     so their stored onset is a mark placed on a trace that was not
    #     theirs. The corrected run refines the same detection against its
    #     own trace and lands somewhere else.
    #
    # The tolerance is the shipped snippet's own claimed length - the
    # window the detector framed the event in. A corrected drop inside that
    # window is the same drop; one outside it is a different event.
    # Ambiguity is reported rather than resolved.
    by_channel = {}
    for r in rows:
        by_channel.setdefault(int(r["channel"]), []).append(r)

    recovered, lost, n_ambiguous = [], [], 0
    for entry in old_bad:
        tolerance = max(int(entry["claimed_len"]), 4)
        near = [r for r in by_channel.get(entry["channel"], ())
                if abs(int(r["onset_idx"]) - entry["onset_idx"]) <= tolerance]
        record = dict(entry)
        record["match_tolerance_samples"] = tolerance
        record["n_candidates_in_window"] = len(near)
        if len(near) > 1:
            n_ambiguous += 1
        if not near:
            record["fate"] = "no drop at this place in the corrected store"
            lost.append(record)
            continue
        match = min(near, key=lambda r: abs(int(r["onset_idx"])
                                            - entry["onset_idx"]))
        start = int(match["snippet_start_idx"])
        onset = int(match["onset_idx"]) - start
        trough = int(match["trough_idx"]) - start
        record["new_event_id"] = match["event_id"]
        record["new_onset_idx"] = int(match["onset_idx"])
        record["onset_moved_by"] = int(match["onset_idx"]) - entry["onset_idx"]
        record["new_wave_len"] = int(trough - onset)
        record["new_depth_mv"] = float(match["drop_depth_mv"])
        record["fate"] = ("recovered" if trough - onset >= 2
                          else "still a one-sample fall")
        (recovered if trough - onset >= 2 else lost).append(record)

    zeros = [e for e in old_bad if e["one_sample_fall"]]
    n_rec = sum(1 for e in recovered if e["one_sample_fall"])
    n_lost = sum(1 for e in lost if e["one_sample_fall"])
    print(f"\nshipped refined store: {len(old_bad)} length-mismatched rows, "
          f"{len(zeros)} of them one-sample (the all-zero vectors)")
    print(f"  recovered with a real waveform: {n_rec} of {len(zeros)}")
    print(f"  unrecoverable:                  {n_lost} of {len(zeros)}")
    print(f"  ambiguous matches (>1 corrected drop in the window): "
          f"{n_ambiguous}")
    for entry in lost:
        if entry["one_sample_fall"]:
            print(f"    CH{entry['channel']} onset {entry['onset_idx']}: "
                  f"{entry['fate']}")

    _Path(OUT, "TASK_A_store.json").write_text(json.dumps({
        "detector_provenance": PROVENANCE,
        "switches_applied": switches,
        "switches_not_applicable": absent,
        "reproduces_shipped_counts": reproduction,
        "shipped": {
            "raw_store": os.path.join(SHIPPED, "motifs"),
            "refined_store": os.path.join(SHIPPED, "refined_v2", "motifs"),
            "n_refined": len(old_rows),
            "n_length_mismatch": len(old_bad),
            "n_one_sample_fall": len(zeros)},
        "corrected": {
            "raw_store": str(raw_dir), "refined_store": str(store_dir),
            "n_raw": len(all_rows), "n_refined": len(rows),
            "n_length_mismatch_raw": len(bad),
            "n_length_mismatch_refined": len(bad_ref),
            "refine_report": report,
            "per_channel": per_channel},
        "the_22": {
            "n_one_sample_fall": len(zeros),
            "n_recovered": n_rec,
            "n_unrecoverable": n_lost,
            "n_ambiguous_matches": n_ambiguous,
            "match_rule": ("same channel, onset within the shipped row's own "
                           "claimed snippet length; nearest wins"),
            "recovered": [e for e in recovered if e["one_sample_fall"]],
            "unrecoverable": [e for e in lost if e["one_sample_fall"]]},
        "all_mismatched_rows": old_bad,
    }, indent=2, default=float), encoding="utf-8")
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
