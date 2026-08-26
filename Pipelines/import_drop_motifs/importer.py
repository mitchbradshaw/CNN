"""
importer.py
===========
The third step of the drop-motif library pipeline (ticket 50): turn a
clustering of the tracked seed bundle into shape-first library rows.

The first two steps already exist and are imported, never reimplemented:

    Working.Detection.drop_motifs.store.load_run(bundle_dir)
        reads the bundle unchanged — events table, snippet archive, manifest.
    Working.Detection.drop_motifs.cluster.cluster_events(events, snippets)
        Ward linkage on resampled, z-normalised vectors; returns labels,
        the feature matrix, the linkage, the cophenetic r, and per-cluster
        composition.

This module is only the write step: one `motif_entry` per shape family, one
`motif_member` per imported motif, and the within-family distances as
`motif_edge` rows carrying the distance function, threshold and recipe hash.

The exemplar of a family is the member whose resampled z-normalised
waveform is closest to the family's mean waveform — the shape, not the
loudest or the first.

Provenance: every member row resolves back to a `recordings` row through its
`recording_id` (source_file / channel / fs) plus its sample range. A card
that cannot be traced back to the signal is not evidence.

Idempotent: members are keyed on content (recording, start, end) and the
writers are `get_or_create_*`, so running the importer twice with the same
parameters never duplicates a row.

No plotting library — CLAUDE.md rule 1. Callable from a bare script.
"""

import argparse
import os

import numpy as np

from Working.Detection.drop_motifs import cluster, store
from Working.database import queries as q
from Working.database import runs as R
from Working.database.schema import init_db
from Working.distances import DISTANCE_REGISTRY, DISTANCE_SCALE_INVARIANT

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_BUNDLE_DIR = os.path.join(
    _REPO_ROOT, "DATA", "library_seed", "drop_motifs5", "motifs",
)


def _height_for_n_clusters(Z, n_clusters):
    """The linkage height whose cut produces `n_clusters` flat clusters.

    Cutting a dendrogram at height h yields 1 + (number of merge heights
    greater than h) clusters, so the height that produces k clusters is the
    k-th largest merge height. scipy's `fcluster(..., criterion="maxclust")`
    picks the same value.
    """
    heights = np.sort(Z[:, 2])
    n = len(heights) + 1  # number of observations
    k = int(n_clusters)
    if k >= n:
        return 0.0
    if k <= 1:
        return float(heights[-1]) if len(heights) else 0.0
    idx = n - 1 - k
    return float(heights[idx])


def _exemplar_index(features, labels, cluster_id):
    """Index (into the events list) of the member closest to the family's
    mean waveform, in the resampled z-normalised feature space."""
    mask = labels == cluster_id
    idxs = np.flatnonzero(mask)
    mean_shape = features[mask].mean(axis=0)
    dists = np.linalg.norm(features[mask] - mean_shape, axis=1)
    return int(idxs[int(np.argmin(dists))])


def _ensure_recordings(conn, events):
    """Create (or reuse) one `recordings` row per distinct (source_file,
    channel) in the bundle, returning {(source_file, channel): recording_id}.

    The seed bundle stores absolute indices in the source channel, so
    `n_samples` is taken as the largest snippet end across the events of
    that channel — the smallest value every member's sample range still
    fits inside. `npy_path` names the channel's materialised file; when a
    recording already exists (idempotent on (source_file, channel)), it is
    reused as-is.
    """
    groups = {}
    for e in events:
        key = (e["source_file"], int(e["channel"]))
        groups.setdefault(key, []).append(e)

    mapping = {}
    for (source_file, channel), evs in groups.items():
        fs = float(evs[0]["fs"])
        n_samples = max(int(e["snippet_end_idx"]) for e in evs)
        npy_path = str(source_file)
        mapping[(source_file, channel)] = q.insert_recording(
            conn, source_file, channel, fs, n_samples, 0, npy_path,
        )
    return mapping


def import_drop_motifs(conn, bundle_dir, *, n_clusters=None, height=None,
                       distance_function=DISTANCE_SCALE_INVARIANT,
                       threshold=None,
                       resample_length=cluster.DEFAULT_RESAMPLE_LENGTH):
    """Populate the motif library from a drop-motif seed bundle.

    Reads the bundle with the existing store reader, clusters with the
    existing cluster module, and writes:

      - one `motif_entry` per shape family — the exemplar is the member
        closest to the family's mean waveform;
      - one `motif_member` per imported motif, keyed on (entry, recording,
        start, end) and never duplicated;
      - one `motif_edge` per within-family exemplar->member pair, recording
        the distance function, the clustering threshold, the distance value
        and the recipe hash.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open, initialised database connection.
    bundle_dir : str
        Directory holding the drop-motif store's `events.csv`, `snippets.npz`
        and `manifest.json`.
    n_clusters, height : int, float, optional
        Exactly one of these, or neither (the cluster module's own default
        cut). The two ways to cut a dendrogram: a fixed number of families,
        or a fixed linkage height.
    distance_function : str
        One of `Working.distances.DISTANCE_REGISTRY`, recorded on each edge.
    threshold : float, optional
        The threshold recorded on every edge. Defaults to the linkage height
        that produced the cut.
    resample_length : int
        The common length every waveform is resampled to before clustering
        (the cluster module's `DEFAULT_RESAMPLE_LENGTH`).

    Returns
    -------
    dict
        {"n_entries", "n_members", "n_edges", "n_clusters", "cophenetic_r",
         "threshold", "recipe_hash", "distance_function"}.
    """
    if n_clusters is not None and height is not None:
        raise ValueError("pass exactly one of n_clusters or height")
    if distance_function not in DISTANCE_REGISTRY:
        raise ValueError(
            f"Unknown distance_function {distance_function!r}; must be one "
            f"of {sorted(DISTANCE_REGISTRY)}"
        )

    # A bare `threshold` is the clustering cut: re-clustering at a new
    # threshold regroups without re-ingesting (PIPELINE_PRD Part 2, Library
    # import). When only the threshold is given, use it as the linkage height.
    if height is None and n_clusters is None and threshold is not None:
        height = threshold

    run = store.load_run(bundle_dir)
    events = run["events"]
    if not events:
        raise ValueError(f"no events in bundle at {bundle_dir!r}; nothing to import")
    snippets = run["snippets"]

    cl = cluster.cluster_events(
        events, snippets, n_clusters=n_clusters, height=height,
        n_samples=resample_length,
    )
    labels = cl["labels"]
    features = cl["features"]
    waveforms = cl["waveforms"]
    n_families = cl["n_clusters"]

    if threshold is None:
        threshold = _height_for_n_clusters(cl["linkage"], n_families)
    threshold = float(threshold)

    recipe = {
        "importer": "drop_motifs5",
        "bundle_dir": os.path.abspath(bundle_dir),
        "n_clusters": n_clusters,
        "height": height,
        "threshold": threshold,
        "distance_function": distance_function,
        "resample_length": int(resample_length),
        "method": cl["method"],
    }
    # Register the recipe so the edge's hash resolves back to parameters;
    # the short hash it returns is the identifier recorded on every edge.
    _, recipe_hash = R.get_or_create_config(conn, recipe)

    recording_map = _ensure_recordings(conn, events)

    n_entries = 0
    n_members = 0
    n_edges = 0
    for cluster_id in sorted(set(labels.tolist())):
        exemplar_idx = _exemplar_index(features, labels, cluster_id)
        exemplar_event = events[exemplar_idx]
        rec_id = recording_map[
            (exemplar_event["source_file"], int(exemplar_event["channel"]))]
        start = int(exemplar_event["snippet_start_idx"])
        end = int(exemplar_event["snippet_end_idx"])

        entry_id = R.insert_motif_entry(
            conn, rec_id, start, end, label=f"drop family {int(cluster_id)}",
        )
        n_entries += 1

        exemplar_member_id = R.get_or_create_motif_member(
            conn, entry_id, rec_id, start, end,
        )
        n_members += 1
        exemplar_waveform = waveforms[exemplar_idx]

        distance_func = DISTANCE_REGISTRY[distance_function]
        for idx in np.flatnonzero(labels == cluster_id):
            idx = int(idx)
            if idx == exemplar_idx:
                continue
            event = events[idx]
            member_rec = recording_map[
                (event["source_file"], int(event["channel"]))]
            member_start = int(event["snippet_start_idx"])
            member_end = int(event["snippet_end_idx"])
            member_id = R.get_or_create_motif_member(
                conn, entry_id, member_rec, member_start, member_end,
            )
            n_members += 1

            distance_value = distance_func(exemplar_waveform, waveforms[idx])
            R.insert_motif_edge(
                conn, exemplar_member_id, member_id,
                distance_function=distance_function,
                threshold=threshold,
                distance_value=float(distance_value),
                recipe_hash=recipe_hash,
            )
            n_edges += 1

    return {
        "n_entries": n_entries,
        "n_members": n_members,
        "n_edges": n_edges,
        "n_clusters": n_families,
        "cophenetic_r": cl["cophenetic_r"],
        "threshold": threshold,
        "recipe_hash": recipe_hash,
        "distance_function": distance_function,
    }


def main(argv=None):
    """Headless CLI: `python -m Pipelines.import_drop_motifs --help`."""
    parser = argparse.ArgumentParser(
        prog="import_drop_motifs",
        description="Import the drop-motif seed bundle into the motif library.",
    )
    parser.add_argument("--db", default=None,
                        help="path to the annotations database (created if "
                             "absent; defaults to DATA/db/annotations.sqlite)")
    parser.add_argument("--bundle", default=DEFAULT_BUNDLE_DIR,
                        help="drop-motif store directory (events.csv, "
                             "snippets.npz, manifest.json)")
    parser.add_argument("--n-clusters", type=int, default=None,
                        help="cut the dendrogram into this many shape families")
    parser.add_argument("--height", type=float, default=None,
                        help="cut the dendrogram at this linkage height")
    parser.add_argument("--distance", default=DISTANCE_SCALE_INVARIANT,
                        help="distance function recorded on edges")
    parser.add_argument("--threshold", type=float, default=None,
                        help="threshold recorded on edges (defaults to the "
                             "cut height)")
    args = parser.parse_args(argv)

    conn = init_db(args.db)
    try:
        result = import_drop_motifs(
            conn, args.bundle, n_clusters=args.n_clusters,
            height=args.height, distance_function=args.distance,
            threshold=args.threshold,
        )
        print(
            f"imported {result['n_entries']} families, "
            f"{result['n_members']} members, {result['n_edges']} edges "
            f"(cophenetic r = {result['cophenetic_r']:.3f}, "
            f"threshold = {result['threshold']:.3f}, "
            f"recipe = {result['recipe_hash']})"
        )
        return 0
    finally:
        conn.close()
