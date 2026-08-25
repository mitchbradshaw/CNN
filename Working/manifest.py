"""
manifest.py
============
The single owner of the pipeline manifest schema (T27). A manifest is the
portability payload a headless `Pipelines/run_recipe/run_recipe.py`
invocation writes beside its artifacts on every run — including failed runs —
and the one generic import action reads any manifest at a matching relative
path and reconstructs the local `configs`/`runs`/`detections`/`artifacts`
rows.

This module is the ONLY place the manifest schema is defined. Exporters
(tickets 45/46) import `MANIFEST_VERSION`, `build_manifest` and the run field
names from here rather than re-declaring the format. Nothing here imports a UI
library — the manifest is written on the cluster and read back headlessly.

Schema
------
Top-level JSON object:

    {
        "manifest_version": 1,
        "code_version": "<git short HEAD or 'unknown'>",
        "created_at": "<iso timestamp>",
        "runs": [ { run block } ]
    }

Each run block carries the recipe, its config hash, the recording content
(so local ids never need to line up), the run status, step timings,
detections, artifact paths, and the started/finished timestamps:

    {
        "config_hash": "<8-char short hash>",
        "recipe": { ... the exact recipe dict that was run ... },
        "recording": {
            "source_file": "...", "channel": 0, "fs": 1.0,
            "n_samples": 0, "global_offset": 0, "npy_path": "relative/or/abs.npy"
        },
        "span_start": 0,
        "span_end": 0,
        "status": "completed",
        "started_at": "...", "finished_at": "...",
        "duration_s": 0.0, "error_text": null, "current_step": null,
        "step_timings": { "0": 0.0 },
        "detections": [ { "start_idx": 0, "end_idx": 0, "score": null, "meta_json": null } ],
        "artifacts": [ { "kind": "encoding", "path": "Results/.../foo.npz" } ]
    }

Paths are stored forward-slashed so a manifest written on a Linux cluster
reads correctly on a Windows working tree.
"""

import datetime
import json
import os

from Working.database import queries as q
from Working.database import runs as R

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "manifest.json"
# Where a run with no persisted artifacts gets its manifest (a failed run
# that died before any artifact was written, or a pure-signal recipe).
DEFAULT_MANIFEST_DIR = "Results"


def get_code_version():
    """Short identifier for the code that produced a manifest. Uses git HEAD
    when available (a cluster job runs from a synced worktree); 'unknown'
    otherwise — writing a manifest must never fail because git is absent."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode("ascii").strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def _to_portable(path):
    """Normalize a path to forward slashes for the JSON manifest, so the file
    is portable across the cluster (Linux) and the researcher's working tree
    (Windows)."""
    return path.replace(os.sep, "/") if path else path


def _native_path(path):
    """Convert a forward-slashed manifest path back to native separators for
    storage in the local database."""
    return os.path.normpath(path) if path else path


def _step_timings_from_run(run):
    raw = run["step_timings_json"]
    return json.loads(raw) if raw else {}


# ── writer ───────────────────────────────────────────────────────────────────

def build_manifest(conn, run_ids):
    """Build a manifest dict for the given run ids.

    Parameters
    ----------
    conn : sqlite3.Connection
    run_ids : list[int]
        One or more runs to describe. `run_recipe.py` writes a single run; an
        exporter can fan several sibling runs into one manifest.

    Returns
    -------
    dict — the manifest schema described in the module docstring.
    """
    runs = []
    for run_id in run_ids:
        run = R.get_run(conn, run_id)
        if run is None:
            raise ValueError(f"No run with id={run_id}")
        config = R.get_config(conn, run["config_id"])
        recipe = json.loads(config["config_json"])
        recording = q.get_recording_by_id(conn, run["recording_id"])
        if recording is None:
            raise ValueError(
                f"Run {run_id} references missing recording {run['recording_id']}"
            )

        runs.append({
            "config_hash": config["config_hash"],
            "recipe": recipe,
            "recording": {
                "source_file": recording["source_file"],
                "channel": recording["channel"],
                "fs": recording["fs"],
                "n_samples": recording["n_samples"],
                "global_offset": recording["global_offset"],
                "npy_path": _to_portable(recording["npy_path"]),
            },
            "span_start": run["span_start"],
            "span_end": run["span_end"],
            "status": run["status"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "duration_s": run["duration_s"],
            "error_text": run["error_text"],
            "current_step": run["current_step"],
            "step_timings": _step_timings_from_run(run),
            "detections": [
                {
                    "start_idx": d["start_idx"],
                    "end_idx": d["end_idx"],
                    "score": d["score"],
                    "meta_json": d["meta_json"],
                }
                for d in R.list_detections(conn, run_id)
            ],
            "artifacts": [
                {"kind": a["kind"], "path": _to_portable(a["path"])}
                for a in R.list_artifacts(conn, run_id)
            ],
        })

    return {
        "manifest_version": MANIFEST_VERSION,
        "code_version": get_code_version(),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "runs": runs,
    }


def manifest_path_for_run(conn, run_id, out_dir=None):
    """Where the manifest for `run_id` should be written.

    With an explicit `out_dir`, that directory. Otherwise the directory of the
    run's first artifact — "beside its artifacts" — falling back to
    `DEFAULT_MANIFEST_DIR` for a run with no persisted artifact (e.g. a failed
    run that never wrote one)."""
    if out_dir is None:
        artifacts = R.list_artifacts(conn, run_id)
        if artifacts:
            out_dir = os.path.dirname(artifacts[0]["path"]) or DEFAULT_MANIFEST_DIR
        else:
            out_dir = DEFAULT_MANIFEST_DIR
    return os.path.join(out_dir, MANIFEST_FILENAME)


def write_manifest(conn, run_ids, out_dir=None):
    """Write the manifest JSON for `run_ids` and return its path (portable,
    forward-slashed).

    Without `out_dir`, the path is derived by `manifest_path_for_run` for the
    first run (the `run_recipe.py` case always has exactly one run). A
    multi-run export should pass an explicit `out_dir`."""
    data = build_manifest(conn, run_ids)
    path = manifest_path_for_run(conn, run_ids[0], out_dir=out_dir)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return _to_portable(path)


def resolve_run_id_for_recipe(conn, recipe):
    """Find the most recent run row for a recipe, regardless of status.

    Used by `run_recipe.py`'s failure path to locate the run row
    `execute_recipe` left behind (already marked failed) so a manifest can
    still be written. Returns None if no run row exists for the recipe."""
    config_id, _ = R.get_or_create_config(conn, recipe)
    recording_id = recipe.get("recording_id")
    if recording_id is None:
        return None
    row = conn.execute(
        "SELECT id FROM runs WHERE config_id = ? AND recording_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (config_id, recording_id),
    ).fetchone()
    return row["id"] if row is not None else None


# ── import ───────────────────────────────────────────────────────────────────

def _find_run_by_key(conn, config_id, recording_id, span_start, span_end):
    """Any run row (completed or failed) for the same (config, recording,
    span) — the natural key that makes a manifest import idempotent."""
    return conn.execute(
        """SELECT id FROM runs
           WHERE config_id = ? AND recording_id = ? AND span_start = ? AND span_end = ?
           LIMIT 1""",
        (config_id, recording_id, span_start, span_end),
    ).fetchone()


def import_manifest(conn, manifest_path):
    """Read a manifest JSON and reconstruct the local rows it describes:
    recordings (by content), configs, runs, detections and artifacts.

    Idempotent: a run already present for the same (config, recording, span)
    is skipped, so importing the same manifest twice never duplicates runs or
    detections.

    Parameters
    ----------
    conn : sqlite3.Connection
    manifest_path : str
        Path to a manifest JSON.

    Returns
    -------
    dict — {
        "imported_runs": list[int],
        "skipped_runs": list[int],
        "recordings_created": list[int],
        "imported_detections": int,
        "imported_artifacts": int,
    }
    """
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    if data.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError(
            f"Unsupported manifest_version={data.get('manifest_version')!r}; "
            f"this build understands version {MANIFEST_VERSION}."
        )

    summary = {
        "imported_runs": [],
        "skipped_runs": [],
        "recordings_created": [],
        "imported_detections": 0,
        "imported_artifacts": 0,
    }

    for run_data in data.get("runs", []):
        rec_info = run_data.get("recording") or {}
        source_file = rec_info.get("source_file")
        channel = rec_info.get("channel")
        if source_file is None or channel is None:
            raise ValueError(
                "Manifest run is missing a recording block (source_file/channel)."
            )

        recording = q.get_recording(conn, source_file, channel)
        if recording is None:
            recording_id = q.insert_recording(
                conn, source_file, channel,
                rec_info.get("fs", 1.0),
                rec_info.get("n_samples", 0),
                rec_info.get("global_offset", 0),
                _native_path(rec_info.get("npy_path", "")),
            )
            summary["recordings_created"].append(recording_id)
        else:
            recording_id = recording["id"]

        recipe = run_data.get("recipe")
        if recipe is None:
            raise ValueError("Manifest run is missing a recipe block.")
        config_id, config_hash = R.get_or_create_config(conn, recipe)
        if run_data.get("config_hash") and config_hash != run_data["config_hash"]:
            raise ValueError(
                f"Manifest config_hash {run_data['config_hash']!r} does not match "
                f"the recomputed hash {config_hash!r} for the embedded recipe."
            )

        span_start = run_data.get("span_start", 0)
        span_end = run_data.get("span_end", 0)

        existing = _find_run_by_key(conn, config_id, recording_id, span_start, span_end)
        if existing is not None:
            summary["skipped_runs"].append(existing["id"])
            continue

        run_id = R.insert_run(
            conn, config_id, recording_id, span_start, span_end,
            status=run_data.get("status", "completed"),
            started_at=run_data.get("started_at"),
        )
        update_fields = {}
        if "finished_at" in run_data:
            update_fields["finished_at"] = run_data["finished_at"]
        if "duration_s" in run_data:
            update_fields["duration_s"] = run_data["duration_s"]
        if "error_text" in run_data:
            update_fields["error_text"] = run_data["error_text"]
        if "step_timings" in run_data:
            update_fields["step_timings_json"] = json.dumps(run_data["step_timings"])
        if "current_step" in run_data:
            update_fields["current_step"] = run_data["current_step"]
        if update_fields:
            R.update_run(conn, run_id, **update_fields)

        for det in run_data.get("detections", []):
            R.insert_detection(
                conn, run_id,
                det["start_idx"], det["end_idx"],
                score=det.get("score"), meta_json=det.get("meta_json"),
                commit=False,
            )
            summary["imported_detections"] += 1
        conn.commit()

        for art in run_data.get("artifacts", []):
            R.insert_artifact(conn, run_id, kind=art["kind"],
                              path=_native_path(art["path"]))
            summary["imported_artifacts"] += 1

        summary["imported_runs"].append(run_id)

    return summary
