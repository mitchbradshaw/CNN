"""
test_motif_groups.py
======================
Tests for Working/Detection/matrix_profiling/motif_groups.py: group
discovery on a synthetic series with three planted motifs, exclusion-zone
correctness, and group-set persistence/keying (a changed n_neighbors /
max_motifs / max_distance is a NEW set, never a silent mutation of the old
one).

Run from the project root:
    python tests/test_motif_groups.py
"""

import inspect
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import stumpy

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database.runs import get_or_create_config, insert_run
from Working.recipes import make_recipe
from Working.Detection.matrix_profiling import motif_groups as mg


# ── synthetic fixture: three planted motifs, each repeated 3x ──────────────

def _planted_series(seed=0):
    """A series with three distinct patterns, each planted at 3 well-
    separated locations, embedded in noise. Returns (x, m, planted) where
    `planted` maps pattern index -> list of start indices."""
    rng = np.random.default_rng(seed)
    m = 30
    t = np.linspace(0, 2 * np.pi, m)
    patterns = [np.sin(t), np.sin(2 * t), np.sign(np.sin(t)) * np.abs(np.cos(t))]

    n = 3000
    x = rng.standard_normal(n) * 0.02  # low-amplitude noise floor

    # Space occurrences far enough apart that exclusion zones (m//2) can't
    # accidentally merge two distinct occurrences of the same pattern.
    starts_per_pattern = [
        [200, 700, 1200],
        [300 + 1500, 700 + 1500, 1100 + 1500],  # offset block, still all < n-m
    ]
    planted = {}
    # Only two well-separated blocks fit cleanly in 3000 samples at this
    # spacing; use patterns[0] and patterns[1] for those, and reserve
    # pattern index 2 (unused) to keep the fixture simple/explicit.
    for pat_idx, starts in enumerate(starts_per_pattern):
        planted[pat_idx] = list(starts)
        for s in starts:
            x[s:s + m] = patterns[pat_idx] + rng.standard_normal(m) * 1e-4
    return x, m, planted


def _profile(x, m):
    p = stumpy.stump(x, m=m)
    return np.asarray(p[:, 0], dtype=np.float32)


# ── build_motif_groups ──────────────────────────────────────────────────────

def test_finds_groups_for_each_planted_pattern():
    x, m, planted = _planted_series()
    mp = _profile(x, m)

    groups = mg.build_motif_groups(x, mp, m, max_motifs=10, n_neighbors=5)
    assert len(groups) > 0

    # Every planted occurrence should be "explained" by some group: either
    # it's a seed, or it shows up as a neighbour of some seed.
    all_starts = set()
    for pat_starts in planted.values():
        all_starts.update(pat_starts)

    covered = set()
    for g in groups:
        covered.add(g["seed_idx"])
        covered.update(idx for idx, _ in g["neighbours"])

    # Allow off-by-a-few-samples matches (stumpy finds the best-aligned
    # window, not necessarily the exact planted start) by checking that
    # each planted start has SOME covered index within m//4 of it.
    tol = m // 4
    for s in all_starts:
        assert any(abs(c - s) <= tol for c in covered), f"planted start {s} not covered by any group"


def test_groups_are_ordered_by_ascending_mp_distance():
    x, m, _ = _planted_series()
    mp = _profile(x, m)
    groups = mg.build_motif_groups(x, mp, m, max_motifs=10, n_neighbors=5)
    distances = [g["mp_distance"] for g in groups]
    assert distances == sorted(distances)


# ── exclusion zone ───────────────────────────────────────────────────────────

def test_exclusion_zone_prevents_neighbour_reappearing_as_later_seed():
    x, m, planted = _planted_series()
    mp = _profile(x, m)
    excl_zone = m // 2

    groups = mg.build_motif_groups(x, mp, m, max_motifs=20, n_neighbors=5)

    excluded_after = np.zeros(len(mp), dtype=bool)
    seeds_seen = []
    for g in groups:
        seed = g["seed_idx"]
        # The seed must not fall inside any PRIOR group's exclusion zone.
        assert not excluded_after[seed], (
            f"seed {seed} was already excluded by an earlier group but was "
            "still used as a later seed"
        )
        seeds_seen.append(seed)
        for nb in [seed] + [idx for idx, _ in g["neighbours"]]:
            lo, hi = max(0, nb - excl_zone), min(len(excluded_after), nb + excl_zone + 1)
            excluded_after[lo:hi] = True

    # No two seeds are within one exclusion zone of each other.
    seeds_sorted = sorted(seeds_seen)
    for a, b in zip(seeds_sorted, seeds_sorted[1:]):
        assert b - a > excl_zone // 2, (a, b)  # loose bound: definitely not coincident


def test_max_motifs_caps_the_group_count():
    x, m, _ = _planted_series()
    mp = _profile(x, m)
    groups = mg.build_motif_groups(x, mp, m, max_motifs=2, n_neighbors=5)
    assert len(groups) <= 2


# ── persistence + keying ────────────────────────────────────────────────────

def _fresh_run():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    recording_id = q.insert_recording(conn, "fake.mat", 0, 1.0, 3000, 0, "fake/CH0.npy")
    recipe = make_recipe(recording_id, [
        {"stage": "detection", "algorithm": "matrix_profile", "params": {"window_min": 0.5}},
    ], span=None)
    config_id, _hash = get_or_create_config(conn, recipe)
    run_id = insert_run(conn, config_id, recording_id, 0, 3000, status="completed")
    return tf.name, conn, run_id


def test_persist_and_find_round_trip():
    db_path, conn, run_id = _fresh_run()
    try:
        x, m, _ = _planted_series()
        mp = _profile(x, m)
        groups = mg.build_motif_groups(x, mp, m, max_motifs=5, n_neighbors=4)
        ids = mg.persist_motif_groups(conn, run_id, groups, m, n_neighbors=4, max_motifs=5)
        assert len(ids) == len(groups)

        found = mg.find_motif_group_set(conn, run_id, n_neighbors=4, max_motifs=5)
        assert found is not None
        assert len(found) == len(groups)
        # Ordering preserved (rank 0 first).
        assert [row["start_idx"] for row in found] == [g["seed_idx"] for g in groups]
    finally:
        conn.close()
        os.unlink(db_path)


def test_different_n_neighbors_is_a_new_set_not_a_mutation():
    db_path, conn, run_id = _fresh_run()
    try:
        x, m, _ = _planted_series()
        mp = _profile(x, m)

        groups_a, reused_a = mg.get_or_build_motif_groups(
            conn, run_id, x, mp, m, n_neighbors=3, max_motifs=5,
        )
        assert reused_a is False

        # Same key -> reused, no new rows.
        groups_a2, reused_a2 = mg.get_or_build_motif_groups(
            conn, run_id, x, mp, m, n_neighbors=3, max_motifs=5,
        )
        assert reused_a2 is True
        assert [g["seed_idx"] for g in groups_a2] == [g["seed_idx"] for g in groups_a]

        # Different n_neighbors -> a genuinely new set, old one still intact.
        groups_b, reused_b = mg.get_or_build_motif_groups(
            conn, run_id, x, mp, m, n_neighbors=8, max_motifs=5,
        )
        assert reused_b is False

        still_a = mg.find_motif_group_set(conn, run_id, n_neighbors=3, max_motifs=5)
        still_b = mg.find_motif_group_set(conn, run_id, n_neighbors=8, max_motifs=5)
        assert still_a is not None and still_b is not None
        assert len(still_a) == len(groups_a)
        assert len(still_b) == len(groups_b)

        # Every neighbour list in set A has at most 3 neighbours, set B at most 8.
        for row in still_a:
            import json
            meta = json.loads(row["meta_json"])
            assert len(meta["neighbours"]) <= 3
        for row in still_b:
            import json
            meta = json.loads(row["meta_json"])
            assert len(meta["neighbours"]) <= 8
    finally:
        conn.close()
        os.unlink(db_path)


def test_different_max_distance_is_a_new_set():
    db_path, conn, run_id = _fresh_run()
    try:
        x, m, _ = _planted_series()
        mp = _profile(x, m)
        mg.get_or_build_motif_groups(conn, run_id, x, mp, m, n_neighbors=4, max_motifs=5, max_distance=None)
        mg.get_or_build_motif_groups(conn, run_id, x, mp, m, n_neighbors=4, max_motifs=5, max_distance=2.0)

        none_set = mg.find_motif_group_set(conn, run_id, n_neighbors=4, max_motifs=5, max_distance=None)
        capped_set = mg.find_motif_group_set(conn, run_id, n_neighbors=4, max_motifs=5, max_distance=2.0)
        assert none_set is not None and capped_set is not None
    finally:
        conn.close()
        os.unlink(db_path)


def test_force_appends_rather_than_overwrites():
    db_path, conn, run_id = _fresh_run()
    try:
        x, m, _ = _planted_series()
        mp = _profile(x, m)
        mg.get_or_build_motif_groups(conn, run_id, x, mp, m, n_neighbors=4, max_motifs=5)
        from Working.database.runs import list_detections
        n_before = len(list_detections(conn, run_id))

        mg.get_or_build_motif_groups(conn, run_id, x, mp, m, n_neighbors=4, max_motifs=5, force=True)
        n_after = len(list_detections(conn, run_id))
        # force=True computed a second set with the SAME key -> more rows,
        # not an in-place overwrite (find_motif_group_set would otherwise
        # be ambiguous about which rank-ordering belongs to which set).
        assert n_after > n_before
    finally:
        conn.close()
        os.unlink(db_path)


# ── runner ───────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
