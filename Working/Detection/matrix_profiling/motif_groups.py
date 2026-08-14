"""
motif_groups.py
=================
Precomputed motif GROUP list for the motif browser (slide 27,
MATRIX_PROFILE_UI_PROMPT.md §6.1) — the same seed-and-exclude algorithm as
`plot_motif_slideshow` in `plot_matrix_profile.py`, split out so it can run
ONCE (with a progress readout) and be persisted, rather than re-walking
`argsort(mp)` + calling `stumpy.match` per slide every time a tab opens.
`build_motif_groups` deliberately reproduces that function's exclusion
logic exactly (`excl_zone = m // 2`, seed and every returned neighbour
excluded from being a future seed) so the browser reproduces the same
slides. It deviates from `stumpy.motifs`, whose default `cutoff` is
`np.nanmax(...)`-derived rather than `inf` and whose exclusion accounting
differs — see the brief for the caveat if a future change wants to switch
to `stumpy.motifs` for speed.

Persistence: each group becomes one `detections` row against the MP's
`run_id` (`start_idx=seed_idx`, `end_idx=seed_idx+m`, `score=mp_distance`,
`meta_json` carrying the neighbour list and the group-set's own key). The
group SET is keyed by `(run_id, n_neighbors, max_motifs, max_distance)` —
changing any of those is a NEW set, computed fresh and stored alongside,
never silently recomputed on every parameter nudge and never conflated
with a prior set for the same run.
"""

import json

import numpy as np
import stumpy

from Working.database.runs import insert_detection, list_detections


def build_motif_groups(x, mp, m, *, max_motifs, n_neighbors, max_distance=None, on_progress=None):
    """Walk `mp` in ascending order (most similar first). For each
    not-yet-excluded, finite-valued position, retrieve its `n_neighbors`
    nearest matches via `stumpy.match`, record the group, then exclude the
    seed and every returned neighbour (± `m // 2` samples) from being a
    future seed.

    Parameters
    ----------
    x : array — the full channel the profile `mp` was computed over.
    mp : array — the matrix profile (whole-channel).
    m : int — window length in samples.
    max_motifs : int — stop after this many groups.
    n_neighbors : int — neighbours to retrieve per group.
    max_distance : float, optional — passed through to `stumpy.match`;
        `None` means no cutoff (`np.inf`).
    on_progress : callable(n_found, max_motifs), optional — called after
        each group is recorded.

    Returns
    -------
    list[dict]: `[{"seed_idx", "mp_distance", "neighbours": [(idx, dist), ...]}, ...]`
    """
    mp = np.asarray(mp, dtype=float)
    excl_zone = m // 2
    excluded = np.zeros(len(mp), dtype=bool)
    order = np.argsort(mp)
    max_d = max_distance if max_distance is not None else np.inf

    groups = []
    for pos in order:
        pos = int(pos)
        if excluded[pos] or not np.isfinite(mp[pos]):
            continue

        Q = x[pos:pos + m]
        try:
            matches = stumpy.match(Q, x, max_matches=n_neighbors, max_distance=max_d, query_idx=pos)
        except Exception:
            continue

        neighbours = [(int(matches[k, 1]), float(matches[k, 0])) for k in range(len(matches))]
        groups.append({"seed_idx": pos, "mp_distance": float(mp[pos]), "neighbours": neighbours})

        for nb in [pos] + [idx for idx, _ in neighbours]:
            lo = max(0, nb - excl_zone)
            hi = min(len(excluded), nb + excl_zone + 1)
            excluded[lo:hi] = True

        if on_progress is not None:
            on_progress(len(groups), max_motifs)
        if len(groups) >= max_motifs:
            break

    return groups


def persist_motif_groups(conn, run_id, groups, m, *, n_neighbors, max_motifs, max_distance=None):
    """Write each group as one `detections` row against `run_id`.
    Returns the list of inserted `detection_id`s, in the same order as
    `groups` (rank 0 = most significant / lowest MP distance)."""
    detection_ids = []
    for rank, g in enumerate(groups):
        meta = {
            "neighbours": [[idx, dist] for idx, dist in g["neighbours"]],
            "n_neighbors": n_neighbors, "max_motifs": max_motifs,
            "max_distance": max_distance, "rank": rank,
        }
        detection_id = insert_detection(
            conn, run_id, g["seed_idx"], g["seed_idx"] + m,
            score=g["mp_distance"], meta_json=json.dumps(meta),
        )
        detection_ids.append(detection_id)
    return detection_ids


def find_motif_group_set(conn, run_id, *, n_neighbors, max_motifs, max_distance=None):
    """Look for an existing persisted group set for this exact
    `(run_id, n_neighbors, max_motifs, max_distance)` key.

    Returns the matching `detections` rows ordered by their stored `rank`,
    or `None` if this exact combination has never been computed for this
    run — changing ANY of the three params is a new set, never silently
    reused, mutated, or conflated with another set for the same run.
    """
    matching = []
    for row in list_detections(conn, run_id):
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if (meta.get("n_neighbors") == n_neighbors and meta.get("max_motifs") == max_motifs
                and meta.get("max_distance") == max_distance and "rank" in meta):
            matching.append((meta["rank"], row))
    if not matching:
        return None
    matching.sort(key=lambda pair: pair[0])
    return [row for _, row in matching]


def _group_from_detection_row(row):
    meta = json.loads(row["meta_json"])
    return {
        "seed_idx": row["start_idx"], "mp_distance": row["score"],
        "neighbours": [(int(idx), float(dist)) for idx, dist in meta["neighbours"]],
        "detection_id": row["id"],
    }


def get_or_build_motif_groups(conn, run_id, x, mp, m, *, n_neighbors, max_motifs,
                               max_distance=None, on_progress=None, force=False):
    """Reuse a persisted group set if one exists for this exact
    `(run_id, n_neighbors, max_motifs, max_distance)` key; otherwise
    compute it (`build_motif_groups`) and persist it
    (`persist_motif_groups`). `force=True` recomputes and appends a new
    set even if one already exists (never overwrites the old one in
    place — see module docstring).

    Returns `(groups, reused)` — `groups` is a list of dicts each also
    carrying `"detection_id"`.
    """
    if not force:
        existing = find_motif_group_set(
            conn, run_id, n_neighbors=n_neighbors, max_motifs=max_motifs, max_distance=max_distance,
        )
        if existing is not None:
            return [_group_from_detection_row(row) for row in existing], True

    groups = build_motif_groups(
        x, mp, m, max_motifs=max_motifs, n_neighbors=n_neighbors,
        max_distance=max_distance, on_progress=on_progress,
    )
    detection_ids = persist_motif_groups(
        conn, run_id, groups, m,
        n_neighbors=n_neighbors, max_motifs=max_motifs, max_distance=max_distance,
    )
    for g, detection_id in zip(groups, detection_ids):
        g["detection_id"] = detection_id
    return groups, False
