"""
import_mp_artifacts.py
========================
One-shot, idempotent backfill: rewrites the legacy matrix-profile `.npz`
artifacts under `Results/Detection/matrix_profile/` into the v2 format
(MATRIX_PROFILE_UI_PROMPT.md §2.2) and registers each as a
`configs`/`runs`/`artifacts` row, so the existing run-tracking machinery
(`Working.database.matrix_profile_store`) can find them exactly like a
live run's output.

Identity resolution (§2.4 step 2) trusts each npz's own embedded
`window_min`/`m`/`fs` scalars when present — confirmed against this
repo's actual 8 legacy files that this is NOT redundant with parsing the
filename: the two oldest files (`0_mp_..._CH0.npz`, `1_mp_..._CH0.npz`)
both lack a `_WIN` token, but their EMBEDDED `window_min` is 5.0 and 10.0
respectively — different scales that happen to share a tokenless
filename. Deriving purely from the filename (or from
`n_samples - len(mp) + 1` against the full channel) would have silently
mislabelled `0_mp_..._CH0.npz` as a ~16,787-minute window; it is in fact a
300-sample (5 min) profile computed over only the first 10,000 samples of
the channel — a short debug/preview run, not a full-channel one. Only
falls back to filename-token / length-derivation when a file genuinely
carries none of `window_min`/`m`/`fs` itself.

Consequently, "two files describe the same logical artifact" (§2.4 step
6, the GPU-flag-prefix case) requires BOTH `window_min` and the profile's
own length to match — matching `window_min` alone is not sufficient, as
the case above demonstrates (same window, very different span coverage).
A run's `span_start`/`span_end` are read from the artifact's own `t_mp`
(when present) rather than assumed to be the whole channel, so a partial-
span legacy run is registered with its true span.

`left_i`/`right_i` are NOT recoverable from the legacy files (the old
pipeline discarded `profile[:, 2:4]` before saving) — written as `-1`
sentinel arrays with `has_chain_indices=False`, so a later chains feature
can tell "no chains available, recompute" from "no chains found".

Safe to re-run: a legacy file already imported (tracked via
`runs.step_timings_json["backfilled_from"]`) is skipped, and an already-
migrated file has already been moved out of the scan directory by the
first run.

Usage:
    python Pipelines/import_mp_artifacts/import_mp_artifacts.py [--db PATH] [--dry-run]
"""

import argparse
import datetime
import json
import os
import re
import shutil

import numpy as np

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database.runs import get_or_create_config, insert_artifact, insert_run, update_run
from Working.database.matrix_profile_store import compute_data_sha1
from Working.recipes import make_recipe
from Pipelines.matrix_profile.run_matrix_profile import build_mp_artifact_path

RESULTS_DIR = os.path.join("Results", "Detection", "matrix_profile")

# `{gpu}_mp_{stem}_CH{ch}[_WIN{n}|_1hr]?.npz` — every legacy filename
# observed under Results/Detection/matrix_profile/ (MATRIX_PROFILE_UI_PROMPT.md
# §2.1's example table) matches this pattern. Only used for (stem, channel,
# gpu) and as a last-resort window hint -- see module docstring.
_FNAME_RE = re.compile(
    r"^(?P<gpu>\d+)_mp_(?P<stem>.+)_CH(?P<ch>\d+)(?:_(?P<win>WIN[\d.]+|1hr))?\.npz$"
)

_ROUND_NDIGITS = 6  # for grouping window_min as a dict key despite float32 roundtrip


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _parse_legacy_filename(filename):
    """(stem, channel, gpu, window_min_hint) from a legacy filename, or
    None if it doesn't match the known pattern at all. `window_min_hint`
    is None when the filename carries no window token."""
    m = _FNAME_RE.match(filename)
    if m is None:
        return None
    win_token = m.group("win")
    if win_token is None:
        window_min_hint = None
    elif win_token == "1hr":
        window_min_hint = 60.0
    else:
        window_min_hint = float(win_token[3:])  # strip "WIN"
    return {
        "stem": m.group("stem"), "channel": int(m.group("ch")),
        "gpu": int(m.group("gpu")), "window_min_hint": window_min_hint,
    }


def _read_artifact_meta(path):
    """Everything derivable from the npz itself, without any recording
    lookup: `mp_len`, embedded `window_min`/`m`/`fs` (None if the file
    doesn't carry them), and the span start implied by `t_mp[0]` (None if
    `t_mp` is absent)."""
    with np.load(path) as data:
        keys = set(data.files)
        meta = {"mp_len": len(data["mp"])}
        if {"window_min", "m", "fs"}.issubset(keys):
            meta["window_min"] = float(data["window_min"])
            meta["m"] = int(data["m"])
            meta["fs"] = float(data["fs"])
        else:
            meta["window_min"] = meta["m"] = meta["fs"] = None
        if "t_mp" in keys and len(data["t_mp"]) > 0:
            meta["t_start"] = float(data["t_mp"][0])
        else:
            meta["t_start"] = None
        meta["finite_fraction"] = (
            float(np.isfinite(data["mp"]).sum()) / meta["mp_len"] if meta["mp_len"] else 0.0
        )
    return meta


def _derive_window_min(mp_len, recording, filename):
    """Last resort, when a file carries no embedded window_min/m/fs AND no
    filename `_WIN` token: derive `m` from `n_samples - len(mp) + 1`
    against the recording's FULL length, and REPORT it (§2.4 step 2)
    rather than writing it silently. Only correct if the artifact in fact
    spans the whole channel -- flagged loudly because that assumption is
    exactly what turned out to be wrong for one of this repo's own legacy
    files (see module docstring)."""
    m = recording["n_samples"] - mp_len + 1
    window_min = m / recording["fs"] / 60.0
    print(
        f"  [confirm] {filename}: no embedded window_min and no _WIN token. "
        f"Derived m={m} samples ({window_min:g} min at fs={recording['fs']}) "
        f"assuming this profile spans the FULL channel "
        f"(n_samples={recording['n_samples']}) - len(mp)({mp_len}) + 1. "
        "Verify with --dry-run before trusting this for a short/partial-span "
        "legacy run."
    )
    return window_min, m


def _resolve_identity(filename, path, parsed, recording):
    """Full identity for one legacy file: window_min/m/fs (embedded >
    filename token > length-derived, in that priority), the finite
    fraction (for duplicate resolution), and the span this profile
    actually covers (from `t_mp[0]` when available, else assumed to start
    at 0)."""
    meta = _read_artifact_meta(path)
    window_min, source = meta["window_min"], "embedded"
    m, fs = meta["m"], meta["fs"] if meta["fs"] is not None else recording["fs"]

    if window_min is None:
        window_min = parsed["window_min_hint"]
        source = "filename" if window_min is not None else source
    if window_min is None:
        window_min, m = _derive_window_min(meta["mp_len"], recording, filename)
        source = "derived"
    if m is None:
        m = int(round(window_min * 60 * fs))

    n_samples_in_span = meta["mp_len"] + m - 1
    span_start = int(round(meta["t_start"] * fs)) if meta["t_start"] is not None else 0
    span_end = span_start + n_samples_in_span

    return {
        "window_min": window_min, "m": m, "fs": fs, "mp_len": meta["mp_len"],
        "span_start": span_start, "span_end": span_end,
        "finite_fraction": meta["finite_fraction"], "source": source,
    }


def _already_imported(conn, recording_id, legacy_filename):
    rows = conn.execute(
        "SELECT step_timings_json FROM runs WHERE recording_id = ? AND status = 'completed'",
        (recording_id,),
    ).fetchall()
    for row in rows:
        try:
            timings = json.loads(row["step_timings_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if timings.get("backfilled_from") == legacy_filename:
            return True
    return False


def _import_one(conn, results_dir, filename, path, source_file, channel, identity, gpu,
                 path_suffix=None):
    """Rewrite one resolved legacy file into v2 format and register it.
    Returns (run_id, v2 artifact path).

    `path_suffix`, when given, is appended to the v2 filename ahead of the
    extension — used only when this artifact's (recording, window_min)
    collides with ANOTHER artifact covering a different span (the v2
    naming convention has no span component, so two same-scale,
    different-span legacy runs would otherwise silently overwrite each
    other on disk; see module docstring)."""
    with np.load(path) as data:
        mp = np.asarray(data["mp"], dtype=np.float32)
        mpi = np.asarray(data["mpi"], dtype=np.int32)
    left_i = -np.ones(len(mp), dtype=np.int32)
    right_i = -np.ones(len(mp), dtype=np.int32)

    recording = q.get_recording(conn, source_file, channel)
    npy_path = recording["npy_path"]
    sha1 = compute_data_sha1(npy_path) if os.path.isfile(npy_path) else ""

    recipe = make_recipe(recording["id"], [
        {"stage": "detection", "algorithm": "matrix_profile",
         "params": {"window_min": float(identity["window_min"])}},
    ], span=None)
    config_id, config_hash = get_or_create_config(conn, recipe)
    run_id = insert_run(conn, config_id, recording["id"],
                         identity["span_start"], identity["span_end"], status="running")

    out_path = build_mp_artifact_path(source_file, channel, identity["window_min"],
                                       out_dir=results_dir)
    if path_suffix:
        root, ext = os.path.splitext(out_path)
        out_path = f"{root}_{path_suffix}{ext}"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    np.savez_compressed(
        out_path,
        mp=mp, mpi=mpi, left_i=left_i, right_i=right_i,
        m=np.int32(identity["m"]), fs=np.float32(identity["fs"]),
        window_min=np.float32(identity["window_min"]),
        n_samples=np.int64(recording["n_samples"]),  # length of the SOURCE CHANNEL, not the span
        source_file=str(source_file), channel=int(channel),
        recording_id=int(recording["id"]), data_sha1=str(sha1),
        config_hash=str(config_hash), approx=False,
        approx_percentage=np.float32(1.0), has_chain_indices=False,
        backend=("legacy_gpu_stump" if gpu else "legacy_stump"),
        stumpy_version="unknown (backfilled)",
        created_at=_now_iso(), elapsed_s=np.float32(-1.0),
    )

    update_run(conn, run_id, status="completed", finished_at=_now_iso(), duration_s=0.0,
               step_timings_json=json.dumps({
                   "backfilled_from": filename, "window_min_source": identity["source"],
               }))
    insert_artifact(conn, run_id, kind="encoding", path=out_path)
    return run_id, out_path


def backfill(db_path=None, results_dir=RESULTS_DIR, dry_run=False):
    """Scan `results_dir` for legacy `.npz` artifacts, rewrite each into v2
    format, register `configs`/`runs`/`artifacts` rows, and move the
    original into `results_dir/_legacy/`.

    Returns {"imported": [...], "skipped": [...], "duplicates_resolved": [...]}.
    """
    conn = init_db(db_path)
    summary = {"imported": [], "skipped": [], "duplicates_resolved": []}

    if not os.path.isdir(results_dir):
        return summary

    resolved = []  # (filename, path, parsed, recording, identity)
    for filename in sorted(os.listdir(results_dir)):
        path = os.path.join(results_dir, filename)
        if not filename.endswith(".npz") or filename.startswith("mp_v2_") or not os.path.isfile(path):
            continue
        parsed = _parse_legacy_filename(filename)
        if parsed is None:
            print(f"  [skip] {filename}: does not match the known legacy naming pattern.")
            summary["skipped"].append(filename)
            continue

        source_file = f"{parsed['stem']}.mat"
        recording = q.get_recording(conn, source_file, parsed["channel"])
        if recording is None:
            print(f"  [skip] {filename}: no matching row in `recordings` for "
                  f"source_file={source_file!r} channel={parsed['channel']} -- cannot "
                  "register a run without a recording_id.")
            summary["skipped"].append(filename)
            continue

        identity = _resolve_identity(filename, path, parsed, recording)
        resolved.append((filename, path, parsed, recording, identity))

    # Group by TRUE logical identity: same recording, same window_min, AND
    # the same profile length -- matching window_min alone is not enough
    # (see module docstring: two of this repo's real legacy files share a
    # window_min but cover very different spans).
    by_identity = {}
    for filename, path, parsed, recording, identity in resolved:
        key = (recording["id"], round(identity["window_min"], _ROUND_NDIGITS), identity["mp_len"])
        by_identity.setdefault(key, []).append((filename, path, parsed, recording, identity))

    # Detect v2-PATH collisions: the naming convention (§2.2) has no span
    # component, so two identity groups that share (recording, window_min)
    # but differ in mp_len (a short/partial-span run at the same scale as
    # a full-channel one -- exactly the case found in this repo's own
    # legacy data, see module docstring) would otherwise silently
    # overwrite each other on disk. The largest-span group keeps the
    # canonical (unsuffixed) path; every other one gets a span-qualified
    # filename so nothing is lost or overwritten.
    scale_groups = {}
    for (recording_id, window_min, mp_len) in by_identity:
        scale_groups.setdefault((recording_id, window_min), []).append(mp_len)
    needs_suffix = {
        (recording_id, window_min, mp_len)
        for (recording_id, window_min), mp_lens in scale_groups.items()
        if len(mp_lens) > 1
        for mp_len in mp_lens if mp_len != max(mp_lens)
    }

    for key in sorted(by_identity, key=lambda k: (k[0], k[1], k[2])):
        group = by_identity[key]
        _, window_min, mp_len = key

        chosen = group[0]
        if len(group) > 1:
            group_sorted = sorted(group, key=lambda g: g[4]["finite_fraction"], reverse=True)
            best_name = group_sorted[0][0]
            others = ", ".join(f"{n} ({i['finite_fraction']:.1%} finite)"
                                for n, _, _, _, i in group_sorted[1:])
            print(f"  [duplicate] recording={key[0]} WIN{window_min:g} (mp_len={mp_len}): "
                  f"{len(group)} files describe the same logical artifact "
                  f"({', '.join(n for n, _, _, _, _ in group_sorted)}). Keeping {best_name} "
                  f"({group_sorted[0][4]['finite_fraction']:.1%} finite mp), discarding {others}.")
            summary["duplicates_resolved"].append({
                "kept": best_name, "discarded": [n for n, _, _, _, _ in group_sorted[1:]],
            })
            chosen = group_sorted[0]
            discarded = group_sorted[1:]
        else:
            discarded = []

        filename, path, parsed, recording, identity = chosen

        if _already_imported(conn, recording["id"], filename):
            print(f"  [skip] {filename}: already imported.")
            summary["skipped"].append(filename)
            continue

        path_suffix = None
        if key in needs_suffix:
            path_suffix = f"span{identity['span_start']}-{identity['span_end']}"
            print(f"  [collision] {filename}: same recording+window_min as another artifact "
                  f"but a different span (mp_len={mp_len} here vs a larger one at this scale) "
                  "-- the v2 naming convention has no span component, so importing this under "
                  f"the canonical name would silently overwrite it. Using a span-qualified "
                  f"filename instead (suffix '{path_suffix}').")

        if dry_run:
            suffix_note = f"_{path_suffix}" if path_suffix else ""
            print(f"  [dry-run] would import {filename} (window_min={identity['window_min']:g} "
                  f"from {identity['source']}, span=[{identity['span_start']}, "
                  f"{identity['span_end']})) -> mp_v2_{parsed['stem']}_CH{parsed['channel']}_"
                  f"WIN{identity['window_min']:g}min{suffix_note}.npz")
            continue

        source_file = f"{parsed['stem']}.mat"
        run_id, out_path = _import_one(conn, results_dir, filename, path, source_file,
                                        parsed["channel"], identity, parsed["gpu"],
                                        path_suffix=path_suffix)

        legacy_dir = os.path.join(results_dir, "_legacy")
        os.makedirs(legacy_dir, exist_ok=True)
        for moved_filename, moved_path in [(filename, path)] + [(n, p) for n, p, _, _, _ in discarded]:
            legacy_dest = os.path.join(legacy_dir, moved_filename)
            if os.path.exists(moved_path) and not os.path.exists(legacy_dest):
                shutil.move(moved_path, legacy_dest)

        print(f"  [import] {filename} -> {out_path} (run_id={run_id})")
        summary["imported"].append({"legacy": filename, "v2": out_path, "run_id": run_id})

    conn.close()
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Backfill legacy matrix-profile .npz artifacts into the v2 format."
    )
    parser.add_argument("--db", default=None, help="Path to the sqlite DB (default: DATA/db/annotations.sqlite)")
    parser.add_argument("--results-dir", default=RESULTS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = backfill(db_path=args.db, results_dir=args.results_dir, dry_run=args.dry_run)
    print(f"\nImported {len(summary['imported'])}, skipped {len(summary['skipped'])}, "
          f"duplicate groups resolved {len(summary['duplicates_resolved'])}.")


if __name__ == "__main__":
    main()
