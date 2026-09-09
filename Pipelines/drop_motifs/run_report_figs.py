"""
run_report_figs.py
===================
The four figures the written report needs, as vector PDFs in
`Plots/drop_motifs_report/`.

    python Pipelines/drop_motifs/run_report_figs.py
    python Pipelines/drop_motifs/run_report_figs.py --only atlas rose
    python Pipelines/drop_motifs/run_report_figs.py --proofs

| file                  | from                            | drawn by             |
|-----------------------|---------------------------------|----------------------|
| `ATLAS_shapes.pdf`    | `Plots/drop_motifs10/motifs`    | `reportfigs_atlas`   |
| `ROSE_scale.pdf`      | `Plots/drop_motifs12a/motifs_*` | `reportfigs_rose`    |
| `ID001_overlays.pdf`  | catalogue ID 1, re-detected     | `reportfigs_overlays`|
| `ID385_overlays.pdf`  | catalogue ID 385, re-detected   | `reportfigs_overlays`|

Two of the four read a store and two re-run the detector, and the split is
not a choice. `Plots/drop_motifs5/motifs` no longer exists - `Plots/` is
gitignored and that run's store was not kept - so the two overlay figures
re-derive their events from the database. That is cheap (about two seconds
a span) and it is also the honest thing to do, because it means the
figures cannot be describing a store nobody can reproduce.

ID 385 is detected with `bracket_rise_on_separation` ON
--------------------------------------------------------
The default detector misses exactly one drop on this recording: a 9 mV
spike at 0.741 h, five samples wide. Its fall flattens for a single sample,
that flattening encodes as an UP run, and `_fall_limit` then bounds the
trough search two samples into the fall - so the depth measures 1.76 mV
instead of 8.99 and Gate B rejects it. `Detect5Params.bracket_rise_on_separation`
applies the guard the falls branch of that function already carries.

The recording's own rhythm is what says the event is real. Its drops run in
a repeating five-step cycle; without this event the first group has four
steps and a 1214 s gap, and with it that gap is 287 + 927 - the same cycle
every other group has. `--id385-default-detector` draws it the other way
for comparison.

The one other event the option admits is a 2.75 mV transient at 3.905 h,
which belongs to neither of this recording's two drop families and is
excluded by `ID385_MIN_DEPTH_MV`. That exclusion is stated in the figure's
JSON rather than made silently.
"""

import argparse
import dataclasses
import json
import os
import sqlite3
import sys
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import (config11, corpora10,  # noqa: E402
                                   reportfigs_atlas, reportfigs_overlays,
                                   reportfigs_rose, reportstyle, tree10)
from Pipelines.drop_motifs.spans5 import SPANS5, load_span  # noqa: E402
from Working.Detection.drop_motifs import motifs5  # noqa: E402
from Working.Detection.drop_motifs.autoparams import autotune  # noqa: E402
from Working.Detection.drop_motifs.detect5 import (  # noqa: E402
    params_as_dict, window_purity)

OUT = _Path(reportstyle.OUT_DIR)
DB = os.path.join("DATA", "db", "annotations.sqlite")

ATLAS_STORE = os.path.join("Plots", "drop_motifs10", "motifs")
ROSE_STORE = os.path.join("Plots", "drop_motifs12a", "motifs_PARTIAL")

FIGURE_IDS = ("atlas", "rose", "id001", "id385")

# ID 385's two drop populations are separated by a gap with nothing in it:
# fourteen events at 8.77-9.61 mV and ten at 13.48-14.05 mV. The boundary
# is stated here rather than found by the figure, so the split is a claim
# about the recording that a reader can check and move.
ID385_DEPTH_BOUNDARY_MV = 11.5

# Below this an ID 385 detection is not one of those two families. Only the
# 2.75 mV transient at 3.905 h falls here. See the module docstring.
ID385_MIN_DEPTH_MV = 5.0


def _open(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def detect_span(conn, catalogue_id, *, max_passes=3, **overrides):
    """`(x_mv, fs, span_offset, rows, info)` for one catalogue span.

    `run_drop5_report.run_span`'s chain, reduced to what a figure needs and
    with detector overrides threaded through `autotune`. The store rows come
    from `motifs5.rows_and_arrays`, so the indices a figure reads are the
    same absolute indices every other consumer of this package reads.
    """
    spec = SPANS5[catalogue_id]
    row = conn.execute("SELECT * FROM recordings WHERE id = ?",
                       (spec["recording"],)).fetchone()
    if row is None:
        raise SystemExit(f"no recording {spec['recording']} in {DB}")
    x, offset = load_span(row, spec["span"])
    fs = float(row["fs"])

    tuned = autotune(x, fs, max_passes=max_passes, **overrides)
    purity = window_purity(x, fs, tuned.result) if tuned.result else []
    rows, _arrays = motifs5.rows_and_arrays(
        tuned.result, x, purity,
        catalogue_id=catalogue_id, recording_id=spec["recording"], fs=fs,
        source_file=os.path.basename(row["npy_path"]),
        channel=int(row["channel"]), span_offset=offset,
        span_label=f"ID {catalogue_id}", span_key=f"id{catalogue_id:03d}")

    clean = (sum(1 for p in purity if p == 1) / len(purity)) if purity else 0.0
    info = {
        "catalogue_id": catalogue_id,
        "recording_id": spec["recording"],
        "source_file": os.path.basename(row["npy_path"]),
        "span_hours": spec["span"],
        "span_offset": int(offset),
        "fs": fs,
        "n_samples": int(len(x)),
        "n_events": len(rows),
        "n_pure": int(sum(1 for r in rows if r["is_pure"])),
        "window_purity_clean_fraction": float(clean),
        "morphology": tuned.morphology,
        "annotated_n": spec["annotated_n"],
        "detector": "detect5 via autoparams.autotune",
        "detector_overrides": {k: v for k, v in overrides.items()},
        "params": params_as_dict(tuned.params) if tuned.params else {},
    }
    # Millivolts, once, here. The channel on disk is volts and everything
    # in a store is millivolts; doing it at the seam keeps every figure
    # below this on one unit. See DETECTION_AND_FIGURES.md section 2.
    return np.asarray(x, dtype=float) * 1000.0, fs, int(offset), rows, info


def _write(path, payload):
    target = os.path.splitext(str(path))[0] + ".json"
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2,
                  default=reportstyle._jsonable)
    return target


def _proof(out_dir, name, enabled):
    return str(_Path(out_dir) / "proofs" / f"{name}.png") if enabled else None


# ==========================================================================
# the four figures
# ==========================================================================

def draw_atlas(out_dir, *, store=ATLAS_STORE, proofs=False, log=print):
    rows, snippets, _ = motifs5.load_store(store)
    log(f"  store {store}: {len(rows)} motifs")
    trees = {}
    for corpus in corpora10.CORPORA:
        selected = [r for r in rows if r["corpus"] == corpus]
        if len(selected) < 3:
            continue
        trees[corpus] = tree10.build(selected, snippets)
    path, info = reportfigs_atlas.plot_atlas(
        trees, snippets, _Path(out_dir) / "ATLAS_shapes.pdf",
        proof_png=_proof(out_dir, "ATLAS_shapes", proofs),
        cols=10)
    info["store"] = store
    return path, info


def draw_rose(out_dir, *, store=ROSE_STORE, proofs=False, log=print):
    rows, snippets, _ = motifs5.load_store(store)
    # `reishi_1hz` is `reishi_10hz` decimated - the same organism at a
    # second rate - so including it would draw many Reishi events twice and
    # quietly double their weight in the rose. `config11`'s rule.
    rows = [r for r in rows if r["corpus"] not in config11.CONTROL_CORPORA]
    log(f"  store {store}: {len(rows)} motifs after dropping "
        f"{config11.CONTROL_CORPORA}")
    path, info = reportfigs_rose.plot_rose_and_scale(
        rows, snippets, _Path(out_dir) / "ROSE_scale.pdf",
        proof_png=_proof(out_dir, "ROSE_scale", proofs))
    info["store"] = store
    info["excluded_corpora"] = list(config11.CONTROL_CORPORA)
    return path, info


def draw_id001(conn, out_dir, *, proofs=False, log=print):
    x_mv, fs, offset, rows, detection = detect_span(conn, 1)
    log(f"  ID 1: {detection['n_events']} drops, "
        f"{detection['n_pure']} pure, purity "
        f"{detection['window_purity_clean_fraction']:.2f}")
    path, info = reportfigs_overlays.plot_span_and_overlays(
        x_mv, fs, offset, rows, _Path(out_dir) / "ID001_overlays.pdf",
        title="Catalogue ID 1 - a sharkfin train of growing amplitude",
        # Sharkfin: the peak IS the alignment point, and there is no flat
        # stretch before the fall to average over.
        baseline_mode="peak",
        proof_png=_proof(out_dir, "ID001_overlays", proofs))
    info["detection"] = detection
    return path, info


def draw_id385(conn, out_dir, *, proofs=False, default_detector=False,
               log=print):
    overrides = {} if default_detector else {
        "bracket_rise_on_separation": True}
    x_mv, fs, offset, rows, detection = detect_span(conn, 385, **overrides)

    kept = [r for r in rows
            if abs(float(r["drop_depth_mv"])) >= ID385_MIN_DEPTH_MV]
    dropped = [{"event_id": r["event_id"], "onset_h": float(r["onset_h"]),
                "drop_depth_mv": float(r["drop_depth_mv"])}
               for r in rows if r not in kept]
    log(f"  ID 385: {detection['n_events']} drops, {len(kept)} in the two "
        f"families, {len(dropped)} below {ID385_MIN_DEPTH_MV} mV")

    path, info = reportfigs_overlays.plot_span_and_overlays(
        x_mv, fs, offset, kept, _Path(out_dir) / "ID385_overlays.pdf",
        title="Catalogue ID 385 - two families of trough spike, and the "
              "intervals between them",
        # Trough: the pre-drop level is genuinely flat, so an average over
        # it beats any single sample.
        baseline_mode="pre_mean",
        depth_boundary_mv=ID385_DEPTH_BOUNDARY_MV,
        family_labels={"shallow": "shallow family (~9 mV)",
                       "deep": "deep family (~13.7 mV)"},
        interval_strip=True,
        show_overlays=False,
        proof_png=_proof(out_dir, "ID385_overlays", proofs))
    info["detection"] = detection
    info["excluded_below_mv"] = ID385_MIN_DEPTH_MV
    info["excluded_events"] = dropped
    return path, info


# ==========================================================================

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--db", default=DB)
    parser.add_argument("--atlas-store", default=ATLAS_STORE)
    parser.add_argument("--rose-store", default=ROSE_STORE)
    parser.add_argument("--only", nargs="*", default=None,
                        help=f"figures to draw, from {FIGURE_IDS}")
    parser.add_argument("--proofs", action="store_true",
                        help="also write a PNG of each figure under "
                             "proofs/, for checking the layout")
    parser.add_argument("--id385-default-detector", action="store_true",
                        help="draw ID 385 without "
                             "bracket_rise_on_separation, which misses the "
                             "0.741 h drop")
    args = parser.parse_args(argv)

    out_dir = _Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(args.only) if args.only else set(FIGURE_IDS)
    unknown = wanted - set(FIGURE_IDS)
    if unknown:
        raise SystemExit(f"unknown figure ids: {sorted(unknown)}")

    index, conn = {}, None
    try:
        if wanted & {"id001", "id385"}:
            conn = _open(args.db)

        if "atlas" in wanted:
            print("ATLAS_shapes", flush=True)
            path, info = draw_atlas(out_dir, store=args.atlas_store,
                                    proofs=args.proofs)
            _write(path, info)
            index["atlas"] = info
            print(f"  -> {path}", flush=True)

        if "rose" in wanted:
            print("ROSE_scale", flush=True)
            path, info = draw_rose(out_dir, store=args.rose_store,
                                   proofs=args.proofs)
            _write(path, info)
            index["rose"] = info
            print(f"  -> {path}", flush=True)

        if "id001" in wanted:
            print("ID001_overlays", flush=True)
            path, info = draw_id001(conn, out_dir, proofs=args.proofs)
            _write(path, info)
            index["id001"] = info
            print(f"  -> {path}", flush=True)

        if "id385" in wanted:
            print("ID385_overlays", flush=True)
            path, info = draw_id385(
                conn, out_dir, proofs=args.proofs,
                default_detector=args.id385_default_detector)
            _write(path, info)
            index["id385"] = info
            print(f"  -> {path}", flush=True)
    finally:
        if conn is not None:
            conn.close()

    # Rule 1 is checked rather than trusted, and it is checked HERE as well
    # as inside each figure so a run cannot end green with a stray 6 pt
    # colorbar label on one plate.
    offenders = {name: info["type_sizes_outside_band"]
                 for name, info in index.items()
                 if info.get("type_sizes_outside_band")}
    if offenders:
        print("\n! type outside the 8-10 pt band:", flush=True)
        for name, items in offenders.items():
            for item in items:
                print(f"    {name}: {item['fontsize']} pt  "
                      f"{item['text']!r}", flush=True)

    with open(out_dir / "figure_index.json", "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2, default=reportstyle._jsonable)
    print(f"\n-> {out_dir / 'figure_index.json'}")
    return 1 if offenders else 0


if __name__ == "__main__":
    raise SystemExit(main())
