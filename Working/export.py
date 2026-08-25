"""
export.py
==========
Two exporters (tickets 45 and 46). A completed run group, or a motif family
in the library, leaves the tool as a folder a thesis chapter can be written
from, without re-running anything.

Run-group export (`export_run_group`, ticket 45)
------------------------------------------------
The export folder contains:

  - manifest.json — ticket 27's manifest schema, imported from
    `Working.manifest` (never restated) and enriched with the per-run
    surrogate block and per-detection adjudications the run-group report
    needs;
  - spans.csv     — one row per span with named columns, so thesis tables
    come out of a spreadsheet rather than a JSON blob;
  - plots/        — a copy of every plot artifact the runs produced.

Library-entry export (`export_library_entry`, ticket 46)
--------------------------------------------------------
The export folder contains:

  - manifest.json — ticket 27's envelope (manifest_version, code_version,
    created_at), imported from `Working.manifest`, with an `entry` block
    carrying the exemplar, members with their edges and distances, scope by
    recording and channel, cross-channel bins, tags, and the recipe hash
    behind each edge;
  - spans.csv     — one row per member span with named columns;
  - plots/        — a copy of the plot artifacts of the run that produced
    the entry's detection, when the entry has one.

Nothing here imports a UI library — headless-test-safe, same as
`Working.manifest`. The manifest schema stays in `Working.manifest`; this
module imports the envelope constants and only adds the fields the exports
need, so the format is not re-declared in a second place (standards rule
5.3).
"""

import csv
import datetime
import json
import os
import shutil

from Working.database import queries as q
from Working.database import runs as R
from Working.database import vocabulary as V
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


# ── library-entry exporter (T46) ─────────────────────────────────────────────

def gather_entry_members(conn, entry):
    """The exemplar first, then every stored member span of one motif family.

    The exemplar itself may or may not have a `motif_member` row yet (a
    freshly promoted entry has none), so it is always represented once from
    the `motif_entry` row; any stored row for the same span is only used to
    recover its member id. Shared with the Library detail surface so the
    export reports exactly the same family the detail view shows.
    """
    exemplar = {
        "id": None,
        "entry_id": entry["id"],
        "recording_id": entry["recording_id"],
        "start_idx": entry["start_idx"],
        "end_idx": entry["end_idx"],
        "is_seed": True,
    }
    members = [exemplar]
    exemplar_key = (entry["recording_id"], entry["start_idx"], entry["end_idx"])
    seen = {exemplar_key}
    for row in R.list_motif_members(conn, entry["id"]):
        key = (row["recording_id"], row["start_idx"], row["end_idx"])
        if key in seen:
            if key == exemplar_key and exemplar["id"] is None:
                exemplar["id"] = row["id"]
            continue
        seen.add(key)
        member = dict(row)
        member["is_seed"] = False
        members.append(member)
    return members


def entry_edges_by_member(conn, entry, members):
    """Map each non-exemplar member id to the edge that connects it to the
    exemplar. `match_span_to_entry` stores (exemplar, candidate) oriented
    edges, so the candidate is the endpoint that is not the exemplar."""
    exemplar_member_id = members[0]["id"]
    member_ids = {m["id"] for m in members if m["id"] is not None}
    edges_by_member = {}
    for edge in R.list_motif_edges(conn, entry["id"]):
        if exemplar_member_id is not None:
            if edge["member_a_id"] == exemplar_member_id:
                candidate_id = edge["member_b_id"]
            elif edge["member_b_id"] == exemplar_member_id:
                candidate_id = edge["member_a_id"]
            else:
                candidate_id = edge["member_a_id"]
        else:
            candidate_id = edge["member_a_id"]
        if candidate_id in member_ids:
            edges_by_member.setdefault(candidate_id, edge)
    return edges_by_member


def _recording_block(conn, recording_id):
    rec = q.get_recording_by_id(conn, recording_id)
    if rec is None:
        return None
    return {
        "source_file": rec["source_file"],
        "channel": rec["channel"],
        "fs": rec["fs"],
        "n_samples": rec["n_samples"],
        "npy_path": rec["npy_path"].replace(os.sep, "/") if rec["npy_path"] else "",
    }


def _edge_block(edge):
    """The manifest form of one motif edge — the distance that produced the
    match plus, when the pair is cross-channel, the lag/correlation/bin."""
    return {
        "edge_id": edge["id"],
        "member_a_id": edge["member_a_id"],
        "member_b_id": edge["member_b_id"],
        "distance_function": edge["distance_function"],
        "threshold": edge["threshold"],
        "distance_value": edge["distance_value"],
        "recipe_hash": edge["recipe_hash"],
        "lag": edge["lag"],
        "waveform_correlation": edge["waveform_correlation"],
        "classification_bin": edge["classification_bin"],
    }


def _entry_scope(conn, members):
    """Distinct (source_file, channel) pairs the family spans, plus counts
    by recording and by channel — the family's footprint for a report."""
    pairs = set()
    for m in members:
        rec = q.get_recording_by_id(conn, m["recording_id"])
        if rec is None:
            continue
        pairs.add((rec["source_file"], rec["channel"]))
    sorted_pairs = sorted(pairs)
    return {
        "recordings": [
            {"source_file": sf, "channel": ch} for sf, ch in sorted_pairs
        ],
        "recording_count": len({sf for sf, _ in sorted_pairs}),
        "channel_count": len({ch for _, ch in sorted_pairs}),
    }


def _build_library_entry_manifest(conn, entry):
    """Build the library-entry manifest dict.

    The envelope is ticket 27's — `manifest_version`, `code_version` and
    `created_at`, imported from `Working.manifest` — with an `entry` block
    that carries everything the family report needs: the exemplar, every
    member with its edge (distance, threshold, recipe hash and, when
    cross-channel, the classification bin), the scope by recording and
    channel, the cross-channel bin counts, tags, and the recipe hash behind
    each edge."""
    members = gather_entry_members(conn, entry)
    edges_by_member = entry_edges_by_member(conn, entry, members)
    edges = [_edge_block(e) for e in R.list_motif_edges(conn, entry["id"])]

    bins = {b: 0 for b in ("artifact", "propagation", "independent_recurrence")}
    for e in edges:
        if e["classification_bin"] in bins:
            bins[e["classification_bin"]] += 1

    member_blocks = []
    for m in members:
        block = {
            "member_id": m["id"],
            "is_seed": m["is_seed"],
            "recording": _recording_block(conn, m["recording_id"]),
            "span_start": m["start_idx"],
            "span_end": m["end_idx"],
        }
        if not m["is_seed"]:
            edge = edges_by_member.get(m["id"])
            if edge is not None:
                block["edge"] = _edge_block(edge)
        member_blocks.append(block)

    return {
        "manifest_version": M.MANIFEST_VERSION,
        "code_version": M.get_code_version(),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "entry": {
            "entry_id": entry["id"],
            "label": entry["label"],
            "created_at": entry["created_at"],
            "exemplar": {
                "recording": _recording_block(conn, entry["recording_id"]),
                "span_start": entry["start_idx"],
                "span_end": entry["end_idx"],
            },
            "scope": _entry_scope(conn, members),
            "members": member_blocks,
            "edges": edges,
            "cross_channel_bins": bins,
            "tags": V.get_motif_entry_tags(conn, entry["id"]),
        },
    }


def _write_library_spans_csv(conn, entry, out_dir):
    """One row per member span with named columns, so a thesis table can be
    pasted straight out of a spreadsheet. Members classified as `artifact`
    are written like any other — marked, never dropped."""
    csv_path = os.path.join(out_dir, "spans.csv")
    members = gather_entry_members(conn, entry)
    edges_by_member = entry_edges_by_member(conn, entry, members)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_file", "channel", "start_idx", "end_idx", "is_seed",
            "distance_function", "threshold", "distance_value", "recipe_hash",
            "classification_bin", "lag", "waveform_correlation",
        ])
        for m in members:
            rec = q.get_recording_by_id(conn, m["recording_id"])
            edge = None
            if not m["is_seed"]:
                edge = edges_by_member.get(m["id"])
            writer.writerow([
                rec["source_file"] if rec else "",
                rec["channel"] if rec else "",
                m["start_idx"],
                m["end_idx"],
                int(m["is_seed"]),
                edge["distance_function"] if edge else "",
                edge["threshold"] if edge else "",
                edge["distance_value"] if edge else "",
                edge["recipe_hash"] if edge else "",
                edge["classification_bin"] if edge else "",
                edge["lag"] if edge else "",
                edge["waveform_correlation"] if edge else "",
            ])
    return csv_path


def _copy_entry_plots(conn, entry, out_dir):
    """Copy the plot artifacts of the run that produced the entry's detection
    into a `plots/` subfolder.

    A freshly eye-flagged entry has no detection pointer and therefore no
    plots — the folder still gets its `plots/` directory so the export shape
    is uniform. Artifact paths that no longer exist on disk are returned in
    `plots_missing` rather than failing the export."""
    plots_dir = os.path.join(out_dir, "plots")
    os.makedirs(plots_dir, exist_ok=True)
    copied, missing = [], []
    if entry["detection_id"] is None:
        return copied, missing
    det = R.get_detection(conn, entry["detection_id"])
    if det is None:
        return copied, missing
    run = R.get_run(conn, det["run_id"])
    if run is None:
        return copied, missing

    used_names = set()
    for art in R.list_artifacts(conn, run["id"]):
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
            dest = os.path.join(plots_dir, f"{stem}_{entry['id']}{ext}")
            base = os.path.basename(dest)
        used_names.add(base)
        shutil.copyfile(src, dest)
        copied.append(dest)
    return copied, missing


def export_library_entry(conn, entry_id, out_dir):
    """Export a library entry (a motif family) to `out_dir`.

    The folder contains a manifest (ticket 27's envelope with an `entry`
    block), a spans CSV with one row per member, and a `plots/` copy of the
    plot artifacts of the entry's provenance run (when it has one).

    Parameters
    ----------
    conn : sqlite3.Connection
    entry_id : int
        The `motif_entry` row to export.
    out_dir : str
        The folder to write the manifest, spans CSV and plots into.

    Returns
    -------
    dict — {
        "entry_id": int,
        "out_dir": str,
        "manifest_path": str,
        "spans_csv_path": str,
        "plots_copied": [str, ...],
        "plots_missing": [str, ...],
    }
    """
    entry = R.get_motif_entry(conn, entry_id)
    if entry is None:
        raise ValueError(f"No motif_entry with id={entry_id}")
    os.makedirs(out_dir, exist_ok=True)

    data = _build_library_entry_manifest(conn, entry)
    manifest_path = os.path.join(out_dir, M.MANIFEST_FILENAME)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    spans_csv_path = _write_library_spans_csv(conn, entry, out_dir)
    plots_copied, plots_missing = _copy_entry_plots(conn, entry, out_dir)

    return {
        "entry_id": entry_id,
        "out_dir": out_dir,
        "manifest_path": manifest_path,
        "spans_csv_path": spans_csv_path,
        "plots_copied": plots_copied,
        "plots_missing": plots_missing,
    }
