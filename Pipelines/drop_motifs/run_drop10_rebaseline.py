"""
run_drop10_rebaseline.py
=========================
Task 6. Walks the fix ladder over all sixteen catalogue spans and over the
five Fig2A channels, attributes every moved count to one named fix, and
writes `Plots/drop_motifs10/REBASELINE.md` plus its JSON.

    python Pipelines/drop_motifs/run_drop10_rebaseline.py
    python Pipelines/drop_motifs/run_drop10_rebaseline.py --spans 1 3 21 385
    python Pipelines/drop_motifs/run_drop10_rebaseline.py --no-fig2a

Reads `Plots/drop_motifs8/run_summary.json` as the baseline and touches
nothing under any earlier plot directory.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import (corpora10, floor10, passes9,  # noqa: E402
                                   rebaseline10, spans5)

DB = os.path.join("DATA", "db", "annotations.sqlite")
OUT = _Path("Plots") / "drop_motifs10"
DROP8 = os.path.join("Plots", "drop_motifs8", "run_summary.json")
DROP9_RAW = 1736
DROP9_REFINED = 1058


def open_db(path=DB):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def audit_catalogue(conn, span_ids, baseline, log=print):
    out = []
    for catalogue_id, spec in corpora10.catalogue_spans(span_ids):
        rec = conn.execute("SELECT * FROM recordings WHERE id = ?",
                           (spec["recording"],)).fetchone()
        x, offset = spans5.load_span(rec, spec["span"])
        fs = float(rec["fs"])
        started = time.time()

        ladder = rebaseline10.ladder_for_span(
            x, fs, catalogue_id=catalogue_id, recording_id=int(rec["id"]),
            source_file=os.path.basename(rec["npy_path"]),
            channel=int(rec["channel"]), span_offset=offset,
            span_key=f"id{catalogue_id:03d}")
        pass_info = ladder[-1].get("pass_detail") or {}
        up_runs, fall_runs, base_events, finest_up_runs = \
            rebaseline10.up_runs_of(x, fs, pass_info)

        base8 = baseline.get(catalogue_id, {})
        control = ladder[0]
        final = ladder[-1]
        reproduces = (base8.get("n_motifs") == control["n_motifs"])

        # Both brackets, each read at its own scale. See
        # `rebaseline10.up_runs_of` - a four-pass total against the BASE
        # pass's encoding is a comparison between two different scales and
        # is not a test of anything.
        base_holds, base_rule, base_failed = rebaseline10.bracket_holds(
            up_runs, spec.get("annotated_n"), final["base_pass_events"])
        holds, rule, failed = rebaseline10.bracket_holds(
            finest_up_runs, spec.get("annotated_n"), final["n_motifs"])
        row = {
            "catalogue_id": catalogue_id,
            "annotated_n": spec.get("annotated_n"),
            "drop8_n_motifs": base8.get("n_motifs"),
            "drop8_base_events": base8.get("base_pass_events"),
            "control_n_motifs": control["n_motifs"],
            "control_reproduces_drop8": bool(reproduces),
            "drop10_n_motifs": final["n_motifs"],
            "drop10_base_events": final["base_pass_events"],
            "delta_total": (final["n_motifs"] - base8["n_motifs"]
                            if base8.get("n_motifs") is not None else None),
            "moves": rebaseline10.attribute(ladder),
            "base_moves": rebaseline10.attribute(ladder, field="base_pass_events"),
            "up_runs": up_runs,
            "finest_up_runs": finest_up_runs,
            "fall_runs": fall_runs,
            "bracket_holds": holds,
            "bracket_rule": rule,
            "base_bracket_holds": base_holds,
            "base_bracket_rule": base_rule,
            "base_bracket_failed_side": base_failed,
            "bracket_failed_side": failed,
            "encoding_side_holds": bool(finest_up_runs >= final["n_motifs"]),
            "derived_floor_mv": floor10.derived_floor_mv(x),
            "amplitude_sigma_mv": floor10.amplitude_sigma_mv(x),
            "ladder": ladder,
            "seconds": round(time.time() - started, 1),
        }
        out.append(row)
        flag = "" if reproduces else "   ! CONTROL DOES NOT REPRODUCE drop8"
        log(f"  id{catalogue_id:<4} drop8 {str(base8.get('n_motifs')):>4} -> "
            f"control {control['n_motifs']:>4} -> drop10 {final['n_motifs']:>4}"
            f"   base {base8.get('base_pass_events')} -> "
            f"{final['base_pass_events']}   up_runs {up_runs}"
            f"/{finest_up_runs}"
            f"   {row['seconds']}s{flag}")
    return out


def audit_fig2a(conn, log=print):
    """drop_motifs9's 1736 raw / 1058 refined against drop_motifs10's.

    Run at the two ends of the ladder only. The intermediate rungs are
    attributable per span on the catalogue, where a span is one detector
    call; on Fig2A a channel is 47 sliding windows and a per-rung count is
    a sum over 47 independent derivations, so the per-fix attribution is
    reported from the catalogue and the Fig2A numbers are reported as the
    two ends plus the floor.
    """
    out = []
    for catalogue_id, rec in corpora10.fig2a_recordings(conn):
        x = np.asarray(np.load(rec["npy_path"], mmap_mode="r"), dtype=float)
        fs = float(rec["fs"])
        started = time.time()
        rows = {}
        for name, flags in (("drop9_like", rebaseline10.RUNGS[0][1]),
                            ("drop10", rebaseline10.RUNGS[-1][1])):
            over = rebaseline10._overrides(flags)
            kept, arrays, info = passes9.detect_sliding(
                x, fs, catalogue_id=catalogue_id,
                recording_id=int(rec["id"]),
                source_file=os.path.basename(rec["npy_path"]),
                channel=int(rec["channel"]),
                span_label=f"CH{int(rec['channel'])}",
                span_key=f"id{catalogue_id:03d}",
                max_passes=3, fine=True, sensitive=True, micro=True,
                remeasure_depth=(name == "drop10"),
                dedup_scale_by_fs=flags["dedup_units"],
                base_overrides=over, fine_overrides=over,
                sens_overrides=over, micro_overrides=over)
            floor_mv = rebaseline10.floor_for_rung(x, flags)
            rows[name] = {
                "n_raw": int(info["n_before_dedup"]),
                "n_after_dedup": int(info["n_after_dedup"]),
                "n_duplicates_dropped": int(info["n_duplicates_dropped"]),
                "depth_floor_mv": float(floor_mv),
                "n_after_floor": (
                    sum(1 for r in kept
                        if abs(float(r["drop_depth_mv"])) > floor_mv)
                    if floor_mv > 0 else len(kept)),
                "n_after_global_floor": sum(
                    1 for r in kept
                    if abs(float(r["drop_depth_mv"])) > floor10.GLOBAL_FLOOR_MV),
            }
        out.append({"catalogue_id": catalogue_id,
                    "channel": int(rec["channel"]),
                    "amplitude_sigma_mv": floor10.amplitude_sigma_mv(x),
                    "seconds": round(time.time() - started, 1),
                    **{f"{k}_{kk}": vv for k, v in rows.items()
                       for kk, vv in v.items()}})
        log(f"  CH{int(rec['channel'])}  drop9-like raw "
            f"{rows['drop9_like']['n_raw']:>4} -> "
            f"{rows['drop9_like']['n_after_floor']:>4} kept   "
            f"drop10 raw {rows['drop10']['n_raw']:>4} -> "
            f"{rows['drop10']['n_after_floor']:>4} kept  "
            f"({rows['drop10']['n_after_global_floor']} at the global floor)"
            f"   {out[-1]['seconds']}s")
    return out


def human_check(catalogue):
    """The four human-referenced counts, before and after. The headline."""
    out = []
    by_id = {row["catalogue_id"]: row for row in catalogue}
    for cid, ref in rebaseline10.HUMAN_REFERENCED.items():
        row = by_id.get(cid)
        if row is None:
            continue
        after = row["drop10_base_events"]
        out.append({
            "catalogue_id": cid,
            "human_stated": ref["stated"],
            "drop8_base": ref["detected8"],
            "drop8_base_measured": row["drop8_base_events"],
            "drop10_base": after,
            "unchanged": bool(after == ref["detected8"]),
            "delta": (after - ref["detected8"]) if after is not None else None,
        })
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--spans", nargs="*", type=int, default=None)
    parser.add_argument("--no-fig2a", action="store_true")
    parser.add_argument("--out-dir", default=str(OUT))
    args = parser.parse_args(argv)

    out = _Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    conn = open_db(args.db)
    baseline = rebaseline10.load_drop8_baseline(DROP8)

    print("catalogue - the fix ladder, span by span", flush=True)
    catalogue = audit_catalogue(conn, args.spans, baseline)

    fig2a = []
    if not args.no_fig2a:
        print("\nFig2A - the two ends of the ladder, channel by channel",
              flush=True)
        fig2a = audit_fig2a(conn)

    checks = human_check(catalogue)
    report = {
        "human_referenced": checks,
        "catalogue": catalogue,
        "fig2a": fig2a,
        "drop9_reference": {"n_raw": DROP9_RAW, "n_refined": DROP9_REFINED},
        "rungs": [name for name, _ in rebaseline10.RUNGS],
        "fix_of_rung": rebaseline10.FIX_OF_RUNG,
        "floor_sigmas": floor10.FLOOR_SIGMAS,
    }
    path = out / "rebaseline.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1, default=str)
    print(f"\n-> {path}")

    print("\nthe four human-referenced counts")
    for row in checks:
        print(f"  id{row['catalogue_id']:<4} stated {row['human_stated']}  "
              f"drop8 base {row['drop8_base']}  drop10 base {row['drop10_base']}"
              f"   {'unchanged' if row['unchanged'] else 'MOVED'}")

    unexplained = [r for r in catalogue
                   if r["delta_total"] and not r["moves"]]
    if unexplained:
        print("\n! spans whose count moved with no rung to attribute it to:")
        for row in unexplained:
            print(f"    id{row['catalogue_id']}  delta {row['delta_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
