"""
matrix_profile_store.py
========================
Thin, headless query layer over the existing `configs`/`runs`/`artifacts`
tables for matrix-profile runs (MATRIX_PROFILE_UI_PROMPT.md §2.3) — no new
tables. A stored MP is already expressible in the schema: a `configs` row
(recipe = one `detection.matrix_profile` step with `window_min=S`), a
`runs` row with `status='completed'` and the span, and an `artifacts` row
of `kind='encoding'`.

`find_completed_run` (`Working.database.runs`) is the underlying reuse
lookup this module builds on; the functions here add the matrix-profile-
specific view on top: "what scales exist for this recording", "is this
artifact stale", "load the v2 npz".
"""

import hashlib
import json

import numpy as np

from Working.config import (
    MP_MAX_WINDOW_SPAN_FRACTION,
    MP_MIN_WINDOW_SAMPLES,
    MP_SCALE_LADDER_MIN,
)
from Working.database.queries import get_recording_by_id

_ISCLOSE_RTOL = 1e-6


def compute_data_sha1(npy_path):
    """SHA1 of the source `.npy` file, streamed in 1 MiB chunks — the
    staleness signal stored in every v2 MP artifact (`data_sha1`)."""
    h = hashlib.sha1()
    with open(npy_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _matrix_profile_config_ids(conn):
    """(config_id, window_min) for every config whose recipe is exactly
    one `detection.matrix_profile` step. Off-ladder windows come back too
    — callers that want ladder-only entries filter by `MP_SCALE_LADDER_MIN`
    themselves (MATRIX_PROFILE_UI_PROMPT.md §1: off-ladder windows stay
    usable via the adapter's own `window_min` param, just not browsable in
    the scale switcher)."""
    out = []
    for row in conn.execute("SELECT id, config_json FROM configs"):
        try:
            recipe = json.loads(row["config_json"])
        except (TypeError, ValueError):
            continue
        steps = recipe.get("steps") or []
        if len(steps) != 1:
            continue
        step = steps[0]
        if step.get("stage") != "detection" or step.get("algorithm") != "matrix_profile":
            continue
        window_min = (step.get("params") or {}).get("window_min")
        if window_min is None:
            continue
        out.append((row["id"], float(window_min)))
    return out


def _load_npz_meta(artifact_path):
    """Read only the small scalar fields out of a v2 npz — never touches
    `mp`/`mpi`/`left_i`/`right_i`, so this stays cheap regardless of the
    profile's length."""
    with np.load(artifact_path, allow_pickle=False) as data:
        return {
            "window_min": float(data["window_min"]),
            "m": int(data["m"]),
            "approx": bool(data["approx"]),
            "backend": str(data["backend"]),
            "elapsed_s": float(data["elapsed_s"]),
            "created_at": str(data["created_at"]),
            "data_sha1": str(data["data_sha1"]),
        }


def list_mp_runs(conn, recording_id, *, include_approx=True):
    """One dict per stored MP artifact for this recording: window_min, m,
    approx, backend, elapsed_s, run_id, artifact_path, created_at, stale.

    `stale` = the artifact's `data_sha1` no longer matches the current
    source `.npy`. Stale rows are always included (never hidden) so the
    caller can grey them out with a recompute action, per §2.3.
    """
    recording = get_recording_by_id(conn, recording_id)
    current_sha1 = compute_data_sha1(recording["npy_path"]) if recording is not None else None

    out = []
    for config_id, _window_min in _matrix_profile_config_ids(conn):
        runs = conn.execute(
            """SELECT * FROM runs WHERE config_id = ? AND recording_id = ?
               AND status = 'completed' ORDER BY id DESC""",
            (config_id, recording_id),
        ).fetchall()
        for run in runs:
            artifacts = conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ? AND kind = 'encoding' "
                "ORDER BY created_at DESC LIMIT 1",
                (run["id"],),
            ).fetchall()
            if not artifacts:
                continue
            artifact = artifacts[0]
            try:
                meta = _load_npz_meta(artifact["path"])
            except (FileNotFoundError, OSError, KeyError):
                continue
            if not include_approx and meta["approx"]:
                continue
            out.append({
                "window_min": meta["window_min"],
                "m": meta["m"],
                "approx": meta["approx"],
                "backend": meta["backend"],
                "elapsed_s": meta["elapsed_s"],
                "run_id": run["id"],
                "artifact_path": artifact["path"],
                "created_at": meta["created_at"],
                "stale": current_sha1 is not None and meta["data_sha1"] != current_sha1,
            })
    return out


def find_mp(conn, recording_id, window_min, *, require_exact=False):
    """The best available stored MP for (recording, window_min): prefers a
    fresh exact artifact, then a fresh approximate one, then a stale one —
    but a stale result is still returned WITH `stale=True`, never silently
    dropped; callers decide whether to still use it. Returns None on a
    total miss.

    `require_exact=True` skips `approx` artifacts entirely, so an
    approximate profile can never be silently substituted where an exact
    one was requested.
    """
    candidates = [
        r for r in list_mp_runs(conn, recording_id, include_approx=not require_exact)
        if np.isclose(r["window_min"], window_min, rtol=_ISCLOSE_RTOL)
    ]
    if require_exact:
        candidates = [r for r in candidates if not r["approx"]]
    if not candidates:
        return None
    fresh = [r for r in candidates if not r["stale"]]
    fresh_exact = [r for r in fresh if not r["approx"]]
    if fresh_exact:
        return fresh_exact[0]
    if fresh:
        return fresh[0]
    return candidates[0]


def ladder_status(conn, recording_id, fs, n_samples):
    """One row per `MP_SCALE_LADDER_MIN` entry — what the scale switcher
    renders directly. `state` is one of:

    - "available" — a fresh, exact artifact exists.
    - "approx"    — a fresh, approximate (scrump) artifact exists.
    - "stale"     — an artifact exists but the source `.npy` has changed.
    - "missing"   — never computed; offer a Compute button.
    - "invalid"   — this window cannot exist for this span/fs at all
                    (`m < MP_MIN_WINDOW_SAMPLES` or too little of the span
                    survives the exclusion zone) — explain why, no Compute
                    button (MATRIX_PROFILE_UI_PROMPT.md §1).
    """
    runs = list_mp_runs(conn, recording_id, include_approx=True)
    try:
        from Working.Detection.matrix_profiling.cost import estimate_seconds
    except ImportError:
        estimate_seconds = None

    out = []
    for window_min in MP_SCALE_LADDER_MIN:
        m = int(round(window_min * 60 * fs))
        row = {"window_min": window_min, "m": m}

        if m < MP_MIN_WINDOW_SAMPLES:
            row.update(
                state="invalid",
                reason=(f"window is {m} sample(s) at fs={fs}; stumpy "
                        f"requires at least {MP_MIN_WINDOW_SAMPLES}."),
                est_seconds=None, run_id=None,
            )
            out.append(row)
            continue
        if m > n_samples // MP_MAX_WINDOW_SPAN_FRACTION:
            row.update(
                state="invalid",
                reason=(f"window is {m} samples; span is only {n_samples} "
                        "samples, leaving too little outside the exclusion "
                        "zone to match against."),
                est_seconds=None, run_id=None,
            )
            out.append(row)
            continue

        matching = [r for r in runs if np.isclose(r["window_min"], window_min, rtol=_ISCLOSE_RTOL)]
        fresh = [r for r in matching if not r["stale"]]
        fresh_exact = [r for r in fresh if not r["approx"]]
        est_seconds = estimate_seconds(n_samples, "stump") if estimate_seconds is not None else None

        if fresh_exact:
            row.update(state="available", reason=None, est_seconds=None,
                       run_id=fresh_exact[0]["run_id"])
        elif fresh:
            row.update(state="approx", reason=None, est_seconds=None,
                       run_id=fresh[0]["run_id"])
        elif matching:
            row.update(state="stale",
                       reason="source data changed since this artifact was computed.",
                       est_seconds=est_seconds, run_id=matching[0]["run_id"])
        else:
            row.update(state="missing", reason=None, est_seconds=est_seconds, run_id=None)
        out.append(row)
    return out


def load_mp(artifact_path, *, mmap=True):
    """Load a v2 MP artifact as a plain dict of arrays/scalars.

    `mmap=True` (default) attempts `mmap_mode='r'` — cheap even when
    several scales are open at once for comparison, since a 1M-sample
    profile is ~4 MB per array. `savez_compressed` archives can't actually
    be memory-mapped (numpy will raise), so this transparently falls back
    to a normal in-memory load in that (the normal, for this repo's
    artifacts) case.
    """
    if mmap:
        try:
            with np.load(artifact_path, mmap_mode="r", allow_pickle=False) as data:
                return {key: data[key] for key in data.files}
        except Exception:
            pass
    with np.load(artifact_path, allow_pickle=False) as data:
        return {key: data[key] for key in data.files}
