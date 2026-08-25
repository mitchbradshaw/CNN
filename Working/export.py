"""
export.py
==========
Run-group exporter (ticket 45). A completed run group leaves the tool as a
folder a thesis chapter can be written from, without re-running anything.

The export folder contains:

  - manifest.json — ticket 27's manifest schema, imported from
    `Working.manifest` (never restated) and enriched with the per-run
    surrogate block and per-detection adjudications the run-group report
    needs;
  - spans.csv     — one row per span with named columns, so thesis tables
    come out of a spreadsheet rather than a JSON blob;
  - plots/        — a copy of every plot artifact the runs produced.

Nothing here imports a UI library — headless-test-safe, same as
`Working.manifest`. The manifest schema stays in `Working.manifest`; this
module imports `build_manifest` and only adds the fields the export needs,
so the format is not re-declared in a second place (standards rule 5.3).
"""

import csv
import json
import os
import shutil

from Working.database import queries as q
from Working.database import runs as R
from Working import manifest as M


def _run_ids_for_group(conn, run_group_id):
    runs = R.list_run_group_runs(conn, run_group_id)
    if not runs:
        raise ValueError(f"Run group {run_group_id} has no runs")
    return [r["id"] for r in runs]


def _surrogate_block(conn, run):
    """The surrogate control for `run`, or None if it has none.

    A run with no surrogate control is stated explicitly as `null` in the
    manifest, so a missing control is visible in the export rather than
    silently absent (PRD "Surrogates"). The surrogate run is found through
    the `runs.surrogate_of_run_id` pointer: a surrogate run S of an original
    run A carries `S.surrogate_of_run_id = A.id`."""
    row = conn.execute(
        "SELECT * FROM runs WHERE surrogate_of_run_id = ? ORDER BY id LIMIT 1",
        (run["id"],),
    ).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["id"],
        "status": row["status"],
        "detection_count": len(R.list_detections(conn, row["id"])),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_s": row["duration_s"],
    }


def _adjudication_for_detection(conn, detection_id):
    """The adjudication block for a detection, or None if unadjudicated."""
    row = conn.execute(
        "SELECT * FROM adjudications WHERE detection_id = ?",
        (detection_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "verdict": row["verdict"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def _enrich_manifest(conn, data, run_ids):
    """Augment ticket 27's manifest dict with the per-run surrogate block and
    per-detection adjudications.

    The base run fields are exactly what `Working.manifest.build_manifest`
    produced; this only adds the two fields the run-group report needs, so
    the manifest schema stays ticket 27's, imported not restated. Detection
    blocks are matched back to their rows by order: `build_manifest` and
    `R.list_detections` both iterate detections ordered by `start_idx`."""
    runs = [R.get_run(conn, rid) for rid in run_ids]
    for run_data, run in zip(data["runs"], runs):
        run_data["surrogate"] = _surrogate_block(conn, run)
        det_rows = R.list_detections(conn, run["id"])
        for det_data, det_row in zip(run_data["detections"], det_rows):
            det_data["adjudication"] = _adjudication_for_detection(conn, det_row["id"])
    return data


def _write_spans_csv(conn, run_ids, out_dir):
    """Write one row per detection span with named columns, so a thesis table
    can be pasted straight out of a spreadsheet."""
    csv_path = os.path.join(out_dir, "spans.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["run_id", "source_file", "channel", "start_idx",
                         "end_idx", "score", "verdict", "surrogate_run_id"])
        for run_id in run_ids:
            run = R.get_run(conn, run_id)
            rec = q.get_recording_by_id(conn, run["recording_id"])
            surrogate = _surrogate_block(conn, run)
            surrogate_run_id = surrogate["run_id"] if surrogate else ""
            for det in R.list_detections(conn, run_id):
                adj = _adjudication_for_detection(conn, det["id"])
                writer.writerow([
                    run_id,
                    rec["source_file"] if rec else "",
                    rec["channel"] if rec else "",
                    det["start_idx"],
                    det["end_idx"],
                    det["score"],
                    adj["verdict"] if adj else "",
                    surrogate_run_id,
                ])
    return csv_path


def _copy_plots(conn, run_ids, out_dir):
    """Copy every plot artifact into a `plots/` subfolder.

    Two runs can legitimately produce same-named plots; the second keeps its
    basename with the run id appended. Artifact paths that no longer exist on
    disk are returned in `plots_missing` rather than failing the export — a
    thesis folder is still worth writing when one plot is gone."""
    plots_dir = os.path.join(out_dir, "plots")
    os.makedirs(plots_dir, exist_ok=True)
    copied, missing = [], []
    used_names = set()
    for run_id in run_ids:
        for art in R.list_artifacts(conn, run_id):
            if art["kind"] != "plot":
                continue
            src = art["path"]
            if not os.path.isfile(src):
                missing.append(src)
                continue
            base = os.path.basename(src)
            dest = os.path.join(plots_dir, base)
            if base in used_names:
                stem, ext = os.path.splitext(base)
                dest = os.path.join(plots_dir, f"{stem}_{run_id}{ext}")
                base = os.path.basename(dest)
            used_names.add(base)
            shutil.copyfile(src, dest)
            copied.append(dest)
    return copied, missing


def export_run_group(conn, run_group_id, out_dir):
    """Export a completed run group to `out_dir`.

    Parameters
    ----------
    conn : sqlite3.Connection
    run_group_id : int
        The `run_groups` row to export.
    out_dir : str
        The folder to write the manifest, spans CSV and plots into.

    Returns
    -------
    dict — {
        "run_group_id": int,
        "run_ids": [int, ...],
        "out_dir": str,
        "manifest_path": str,
        "spans_csv_path": str,
        "plots_copied": [str, ...],
        "plots_missing": [str, ...],
    }
    """
    run_ids = _run_ids_for_group(conn, run_group_id)
    os.makedirs(out_dir, exist_ok=True)

    data = _enrich_manifest(conn, M.build_manifest(conn, run_ids), run_ids)
    manifest_path = os.path.join(out_dir, M.MANIFEST_FILENAME)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    spans_csv_path = _write_spans_csv(conn, run_ids, out_dir)
    plots_copied, plots_missing = _copy_plots(conn, run_ids, out_dir)

    return {
        "run_group_id": run_group_id,
        "run_ids": run_ids,
        "out_dir": out_dir,
        "manifest_path": manifest_path,
        "spans_csv_path": spans_csv_path,
        "plots_copied": plots_copied,
        "plots_missing": plots_missing,
    }
