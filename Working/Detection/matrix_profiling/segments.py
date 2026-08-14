"""
segments.py
============
Three different quantities that all look like "the matrix profile over a
segment" but answer different questions — MATRIX_PROFILE_UI_PROMPT.md §4.
Naming and separation is deliberate: collapsing these into one code path
is exactly the bug this module exists to prevent (see
`tests/test_mp_segments.py`, which constructs a case where (1) and (2)
provably disagree).

Given a whole-channel profile `mp` (window `m`) and a segment `[a, b)`:

(1) `slice_channel_profile` — nearest neighbour ANYWHERE in the channel,
    for each subsequence starting in the segment. Free, exact, no
    recomputation. The correct backing for "where else does this occur?"
    and for the motif browser's neighbour lists.
(2) `segment_profile` — nearest neighbour WITHIN the segment only. Cheap
    (the segment is small) so always recomputed, never approximated by
    slicing (1). Answers "does this pattern repeat inside this window?"
(3) `seed_matches` — distance from one query window to every position in
    the channel, via `stumpy.match`'s FFT-based search (~O(n log n)). Fast
    enough to run interactively on a full channel.
"""

import numpy as np
import stumpy


def slice_channel_profile(mp, m, a, b):
    """(1) Slice of the whole-channel profile over `[a, b)`.

    `mp[i]` describes the subsequence `x[i : i+m]`, so the entries whose
    subsequence *starts* inside `[a, b)` are `mp[a : b - m + 1]`.

    Raises `ValueError` if `[a, b)` falls outside the profile's domain
    `[0, n)` where `n = len(mp) + m - 1` is the channel length `mp` was
    computed over.
    """
    n = len(mp) + m - 1
    if not (0 <= a < b <= n):
        raise ValueError(f"[a, b)=[{a}, {b}) is outside the channel domain [0, {n}).")
    lo, hi = a, b - m + 1
    if hi <= lo:
        return np.asarray(mp[0:0])
    return np.asarray(mp[lo:hi])


def segment_profile(x, m, a, b):
    """(2) Segment-only profile: `stumpy.stump(x[a:b], m)` — nearest
    neighbour WITHIN the segment for each subsequence in it. Never use
    `slice_channel_profile` as a substitute for this; they answer
    different questions (MATRIX_PROFILE_UI_PROMPT.md §4).

    Returns `{"mp": float32 array, "mpi": int32 array}`, both indexed
    relative to the segment (position 0 = `x[a]`).
    """
    seg = np.asarray(x[a:b])
    if len(seg) < 2 * m:
        raise ValueError(
            f"segment length {len(seg)} is too short for window m={m}; "
            "stumpy needs at least 2*m samples so every subsequence has "
            "somewhere else within the segment to be compared against."
        )
    profile = stumpy.stump(seg, m=m)
    return {
        "mp": np.asarray(profile[:, 0], dtype=np.float32),
        "mpi": np.asarray(profile[:, 1], dtype=np.int32),
    }


def seed_matches(x, m, seed_idx, k, max_distance=None):
    """(3) Seed distance profile: `stumpy.match(Q, x)` for the query window
    `Q = x[seed_idx : seed_idx+m]` — distance from that one query to every
    position in the channel. Fast enough to run interactively on a full
    channel; backs the motif browser's per-group neighbour retrieval.

    Returns an `(n_matches, 2)` array of `[distance, index]` pairs
    (`stumpy.match`'s own closest-first ordering), capped at `k` matches.
    """
    if seed_idx < 0 or seed_idx + m > len(x):
        raise ValueError(f"seed_idx={seed_idx} + m={m} runs past the end of x (len={len(x)}).")
    Q = np.asarray(x[seed_idx:seed_idx + m])
    md = max_distance if max_distance is not None else np.inf
    return stumpy.match(Q, x, max_matches=k, max_distance=md, query_idx=seed_idx)
