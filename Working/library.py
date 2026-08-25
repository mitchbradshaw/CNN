"""
library.py
===========
The matching half of the shape-first motif library (ticket 36): matching a
candidate span to an exemplar entry writes a `motif_member` (the candidate
span, in whatever recording/channel it came from) and a `motif_edge` (the
distance-carrying relationship between the exemplar's own member and the
candidate's member). Every field the edge needs to reproduce the match is
recorded on the row — distance function name, threshold, distance value,
recipe hash — so a motif family is an object, not a screenshot.

`match_span_to_entry` is the seam the search UI (and tickets 41/46) call;
`search_entry_across_durations` is the search-at-other-scales action on top of
it — sliding the exemplar's shape across a range of durations. The low-level
member/edge rows live in `Working.database.runs`.

Nothing here imports a UI library — callable from a bare script exactly like
the rest of `Working/`.
"""

import numpy as np

from Working.database import queries as q
from Working.database import runs as R
from Working.cross_channel import ARTIFACT, classify_waveforms
from Working.distances import DISTANCE_REGISTRY, DISTANCE_SCALE_INVARIANT


def _load_span(recording, start_idx, end_idx):
    """The raw sample values of one span, read off disk from the recording's
    npy path. A small slice copied out of the mmap so the file handle doesn't
    stay open."""
    x_full = np.load(recording["npy_path"], mmap_mode="r")
    return np.array(x_full[start_idx:end_idx])


def match_span_to_entry(conn, entry_id, recording_id, start_idx, end_idx,
                        threshold, recipe_hash,
                        distance_function=DISTANCE_SCALE_INVARIANT,
                        **distance_params):
    """Match a candidate span to an exemplar entry and persist the match.

    Loads the exemplar's waveform and the candidate's waveform from disk,
    computes the named distance, and if it is within `threshold` writes:

      - a `motif_member` for the candidate span (and, on first match, for the
        exemplar's own span — an edge connects two members), and
      - a `motif_edge` carrying the distance function name, threshold,
        distance value and recipe hash.

    A member may reference any recording and any channel, including one the
    exemplar did not come from.

    Idempotent: re-running the same match with the same recipe_hash returns
    the existing edge rather than writing a duplicate.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open, initialised database connection.
    entry_id : int
        The `motif_entry` the candidate is being matched against.
    recording_id : int
        The recording the candidate span lives in.
    start_idx, end_idx : int
        The candidate span's sample range (channel-local).
    distance_function : str
        One of `Working.distances.DISTANCE_REGISTRY`. Defaults to the primary
        scale-invariant distance.
    threshold : float
        Maximum distance accepted as a match. Required — the value is stored
        on the edge.
    recipe_hash : str
        The recipe that produced this match. Required — stored on the edge so
        the match is reproducible.
    **distance_params
        Forwarded to the named distance function (e.g. `word_length` for the
        symbolic distance). These are recipe parameters and must be captured
        in `recipe_hash` by the caller.

    Returns
    -------
    dict or None
        None when the distance exceeds `threshold` (nothing is persisted).
        Otherwise a dict with the persisted rows' ids and the recorded fields:

        {
            "entry_id": int,
            "exemplar_member_id": int,
            "candidate_member_id": int,
            "edge_id": int,
            "distance_value": float,
            "distance_function": str,
            "threshold": float,
            "recipe_hash": str,
        }
    """
    entry = R.get_motif_entry(conn, entry_id)
    if entry is None:
        raise ValueError(f"No motif_entry with id={entry_id}")

    if threshold is None:
        raise ValueError("threshold is required to persist an edge")
    if recipe_hash is None:
        raise ValueError("recipe_hash is required to persist an edge")

    if distance_function not in DISTANCE_REGISTRY:
        raise ValueError(
            f"Unknown distance_function {distance_function!r}; "
            f"must be one of {sorted(DISTANCE_REGISTRY)}"
        )

    exemplar_rec = q.get_recording_by_id(conn, entry["recording_id"])
    candidate_rec = q.get_recording_by_id(conn, recording_id)
    if candidate_rec is None:
        raise ValueError(f"No recording with id={recording_id}")
    if start_idx < 0 or end_idx > candidate_rec["n_samples"] or end_idx <= start_idx:
        raise ValueError(
            f"Candidate span [{start_idx}, {end_idx}) is outside recording "
            f"{recording_id} (n_samples={candidate_rec['n_samples']})."
        )

    x_exemplar = _load_span(exemplar_rec, entry["start_idx"], entry["end_idx"])
    x_candidate = _load_span(candidate_rec, start_idx, end_idx)

    func = DISTANCE_REGISTRY[distance_function]
    distance_value = func(x_exemplar, x_candidate, **distance_params)

    if distance_value > threshold:
        return None

    exemplar_member_id = R.get_or_create_motif_member(
        conn, entry_id, entry["recording_id"], entry["start_idx"], entry["end_idx"],
    )
    candidate_member_id = R.get_or_create_motif_member(
        conn, entry_id, recording_id, start_idx, end_idx,
    )

    edge_id = R.insert_motif_edge(
        conn, exemplar_member_id, candidate_member_id,
        distance_function=distance_function,
        threshold=threshold,
        distance_value=distance_value,
        recipe_hash=recipe_hash,
    )

    return {
        "entry_id": entry_id,
        "exemplar_member_id": exemplar_member_id,
        "candidate_member_id": candidate_member_id,
        "edge_id": edge_id,
        "distance_value": distance_value,
        "distance_function": distance_function,
        "threshold": threshold,
        "recipe_hash": recipe_hash,
    }


def search_entry_across_durations(conn, entry_id, recording_id, durations,
                                  threshold, recipe_hash,
                                  distance_function=DISTANCE_SCALE_INVARIANT,
                                  **distance_params):
    """Search for members of an exemplar across a range of durations.

    For every duration `d` in `durations` and every start index such that a
    window of length `d` fits in `recording_id`, compute the named distance
    between the window and the exemplar. Whenever it is within `threshold`,
    persist the match as a `motif_member` + `motif_edge` (via
    `match_span_to_entry`) and record the matched span in the returned
    summary.

    This is the "search at other scales" action (PIPELINE_PRD.md, Library):
    the same shape the exemplar defines at one duration is queried at
    durations it was never defined at, so scale-invariance is a testable
    query rather than an assumption. Passing `DISTANCE_NATIVE_LENGTH` as the
    distance runs the unnormalised control — a shape identical under
    resampling but longer/shorter is a large distance under it.

    The exemplar's own span is skipped when it falls inside the search range,
    so re-searching the recording the exemplar came from does not write a
    self-edge.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open, initialised database connection.
    entry_id : int
        The `motif_entry` being searched for.
    recording_id : int
        The recording the search runs over.
    durations : iterable of int
        The candidate durations (sample counts) to search at.
    threshold, recipe_hash, distance_function, **distance_params
        Forwarded to `match_span_to_entry`.

    Returns
    -------
    dict
        {
            "entry_id": int,
            "recording_id": int,
            "distance_function": str,
            "threshold": float,
            "recipe_hash": str,
            "durations": list[int],
            "by_duration": {int: [match_result, ...]},
            "matches": [match_result, ...],
            "matched_spans": [(start_idx, end_idx), ...],
            "recall": int,
        }
        Each match_result is what `match_span_to_entry` returns, augmented
        with `"span"` and `"duration"`.
    """
    entry = R.get_motif_entry(conn, entry_id)
    if entry is None:
        raise ValueError(f"No motif_entry with id={entry_id}")
    rec = q.get_recording_by_id(conn, recording_id)
    if rec is None:
        raise ValueError(f"No recording with id={recording_id}")

    durations = sorted({int(d) for d in durations})
    if not durations:
        raise ValueError("durations must be a non-empty iterable")

    exemplar_span = (entry["recording_id"], entry["start_idx"], entry["end_idx"])
    n_samples = rec["n_samples"]

    by_duration = {}
    matches = []
    matched_spans = []

    for d in durations:
        if d < 1 or d > n_samples:
            continue
        found = []
        for start in range(0, n_samples - d + 1):
            if (recording_id, start, start + d) == exemplar_span:
                continue
            end = start + d
            result = match_span_to_entry(
                conn, entry_id, recording_id, start, end,
                threshold=threshold, recipe_hash=recipe_hash,
                distance_function=distance_function,
                **distance_params,
            )
            if result is not None:
                result = dict(result)
                result["span"] = (start, end)
                result["duration"] = d
                found.append(result)
        by_duration[d] = found
        matches.extend(found)
        matched_spans.extend(r["span"] for r in found)

    return {
        "entry_id": entry_id,
        "recording_id": recording_id,
        "distance_function": distance_function,
        "threshold": threshold,
        "recipe_hash": recipe_hash,
        "durations": durations,
        "by_duration": by_duration,
        "matches": matches,
        "matched_spans": matched_spans,
        "recall": len(matches),
    }
def _set_motif_edge_classification(conn, edge_id, lag, waveform_correlation,
                                   classification_bin):
    """Write the cross-channel classification onto an existing motif edge.

    `R.insert_motif_edge` is deliberately idempotent and therefore cannot
    update a duplicate key, so the classification action needs this single
    UPDATE path for edges the search/matching seam has already created.
    """
    conn.execute(
        """UPDATE motif_edge
           SET lag = ?, waveform_correlation = ?, classification_bin = ?
           WHERE id = ?""",
        (lag, waveform_correlation, classification_bin, edge_id),
    )
    conn.commit()


def classify_cross_channel_edges(conn, entry_id):
    """Classify and persist every cross-channel edge of one motif family.

    A pair is cross-channel when both member spans live in recordings with the
    same `source_file` but different `channel` — the same acquisition seen on
    two electrodes. For each such edge, the lag is the cross-correlation peak
    and the waveform identity is the correlation at that lag, computed by
    `Working.cross_channel.classify_waveforms`, then written back onto the
    edge.

    Returns
    -------
    list[dict]
        One dict per classified edge, in `list_motif_edges` order, with the
        persisted `edge_id`, `member_a_id`, `member_b_id`, `lag`,
        `waveform_correlation` and `classification_bin`.
    """
    results = []
    for edge in R.list_motif_edges(conn, entry_id):
        member_a = R.get_motif_member(conn, edge["member_a_id"])
        member_b = R.get_motif_member(conn, edge["member_b_id"])
        recording_a = q.get_recording_by_id(conn, member_a["recording_id"])
        recording_b = q.get_recording_by_id(conn, member_b["recording_id"])

        if (recording_a["source_file"] != recording_b["source_file"]
                or recording_a["channel"] == recording_b["channel"]):
            continue

        x_a = _load_span(recording_a, member_a["start_idx"], member_a["end_idx"])
        x_b = _load_span(recording_b, member_b["start_idx"], member_b["end_idx"])
        lag, waveform_correlation, classification_bin = classify_waveforms(x_a, x_b)

        _set_motif_edge_classification(
            conn, edge["id"], lag, waveform_correlation, classification_bin,
        )
        results.append({
            "edge_id": edge["id"],
            "member_a_id": edge["member_a_id"],
            "member_b_id": edge["member_b_id"],
            "lag": lag,
            "waveform_correlation": waveform_correlation,
            "classification_bin": classification_bin,
        })

    return results


def recurrence_count(conn, entry_id):
    """Recurrence count for a motif family, with artifact edges excluded.

    An edge classified as `artifact` is a shared-ground recording error, not a
    finding, so it contributes nothing to this count.
    """
    return sum(
        1 for edge in R.list_motif_edges(conn, entry_id)
        if edge["classification_bin"] != ARTIFACT
    )
