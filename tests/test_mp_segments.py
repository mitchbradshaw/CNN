"""
test_mp_segments.py
=====================
Tests for Working/Detection/matrix_profiling/segments.py — the three
segment semantics from MATRIX_PROFILE_UI_PROMPT.md §4. The core test
(`test_slice_and_segment_profile_provably_disagree`) constructs a series
where a pattern is unique *within* a segment but repeated *outside* it, so
`slice_channel_profile` (nearest neighbour anywhere) and `segment_profile`
(nearest neighbour within the segment only) must return different
answers — the guard against §4 collapsing back into one code path.

Also exercises Working/Detection/matrix_profiling/cost.py's estimate/
calibration contract (uncalibrated -> None, never a hardcoded fallback).

Run from the project root:
    python tests/test_mp_segments.py
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

from Working.Detection.matrix_profiling import segments as S
from Working.Detection.matrix_profiling import cost


# ── slice_channel_profile ───────────────────────────────────────────────────

def test_slice_channel_profile_matches_manual_slice():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(500)
    m = 10
    profile = stumpy.stump(x, m=m)
    mp = profile[:, 0].astype(np.float32)

    a, b = 50, 120
    out = S.slice_channel_profile(mp, m, a, b)
    expected = mp[a:b - m + 1]
    assert np.array_equal(out, expected)


def test_slice_channel_profile_bounds_checked():
    mp = np.zeros(100, dtype=np.float32)
    m = 10
    n = len(mp) + m - 1  # 109
    try:
        S.slice_channel_profile(mp, m, -1, 50)
        assert False, "expected ValueError for a<0"
    except ValueError:
        pass
    try:
        S.slice_channel_profile(mp, m, 0, n + 1)
        assert False, "expected ValueError for b>n"
    except ValueError:
        pass


def test_slice_channel_profile_empty_when_segment_shorter_than_window():
    mp = np.arange(100, dtype=np.float32)
    m = 10
    out = S.slice_channel_profile(mp, m, 5, 8)  # b-a=3 < m
    assert len(out) == 0


# ── segment_profile ──────────────────────────────────────────────────────────

def test_segment_profile_returns_mp_and_mpi_same_length():
    rng = np.random.default_rng(1)
    x = rng.standard_normal(200)
    m = 8
    result = S.segment_profile(x, m, 20, 100)
    assert len(result["mp"]) == len(result["mpi"])
    assert len(result["mp"]) == (100 - 20) - m + 1


def test_segment_profile_raises_on_too_short_segment():
    x = np.arange(50, dtype=float)
    m = 10
    try:
        S.segment_profile(x, m, 0, 15)  # 15 samples < 2*m
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── the core guard: (1) and (2) provably disagree ───────────────────────────

def test_slice_and_segment_profile_provably_disagree():
    """Construct x such that a pattern (P) occurring once inside a segment
    is UNIQUE within that segment but has a near-identical match OUTSIDE
    it. slice_channel_profile (nearest neighbour anywhere) must therefore
    report a small distance for P's occurrence, while segment_profile
    (nearest neighbour within the segment only) must report a large one
    for the same position.
    """
    rng = np.random.default_rng(42)
    m = 20

    pattern = np.sin(np.linspace(0, 4 * np.pi, m))
    noise_a = rng.standard_normal(150) * 0.05
    noise_b = rng.standard_normal(150) * 0.05

    # Segment: [pattern, noise] -- pattern occurs once, at position 0.
    segment = np.concatenate([pattern, noise_a])
    # Outside the segment (elsewhere in the channel): an almost-identical
    # copy of the pattern, embedded in unrelated noise.
    outside = np.concatenate([noise_b, pattern + rng.standard_normal(m) * 1e-4])

    x = np.concatenate([segment, outside])
    a, b = 0, len(segment)

    profile = stumpy.stump(x, m=m)
    mp = profile[:, 0].astype(np.float32)

    channel_view = S.slice_channel_profile(mp, m, a, b)
    seg_view = S.segment_profile(x, m, a, b)

    # Position 0 (the pattern's start) is the entry of interest in both.
    dist_anywhere = float(channel_view[0])
    dist_within_segment = float(seg_view["mp"][0])

    # Anywhere-in-channel: a near-perfect match exists (outside the segment)
    # -> small distance.
    assert dist_anywhere < 1.0, dist_anywhere
    # Within-segment-only: no match for the pattern exists inside the
    # segment itself (only noise) -> materially larger distance.
    assert dist_within_segment > dist_anywhere + 1.0, (dist_within_segment, dist_anywhere)


# ── seed_matches ─────────────────────────────────────────────────────────────

def test_seed_matches_finds_the_planted_neighbour():
    rng = np.random.default_rng(7)
    m = 15
    pattern = np.sin(np.linspace(0, 4 * np.pi, m))
    x = rng.standard_normal(400) * 0.05
    seed_idx = 30
    other_idx = 300
    x[seed_idx:seed_idx + m] = pattern
    x[other_idx:other_idx + m] = pattern + rng.standard_normal(m) * 1e-4

    matches = S.seed_matches(x, m, seed_idx, k=5)
    found_idxs = {int(row[1]) for row in matches}
    assert other_idx in found_idxs


def test_seed_matches_raises_when_seed_runs_past_end():
    x = np.zeros(50)
    try:
        S.seed_matches(x, 10, seed_idx=45, k=3)
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── cost.py — calibration contract ──────────────────────────────────────────

def test_estimate_seconds_none_when_uncalibrated():
    with tempfile.TemporaryDirectory() as tmp:
        fake_path = os.path.join(tmp, "mp_calibration.json")
        orig = cost.CALIBRATION_PATH
        cost.CALIBRATION_PATH = fake_path
        try:
            assert cost.estimate_seconds(1_000_000, "stump") is None
            assert cost.routing_tier(None) == "unknown"
            assert cost.max_span_samples_for_background() is None
        finally:
            cost.CALIBRATION_PATH = orig


def test_calibrate_then_estimate_is_self_consistent():
    with tempfile.TemporaryDirectory() as tmp:
        fake_path = os.path.join(tmp, "mp_calibration.json")
        orig = cost.CALIBRATION_PATH
        cost.CALIBRATION_PATH = fake_path
        try:
            entry = cost.calibrate("stump", n0=2000)
            assert entry["k"] > 0
            est = cost.estimate_seconds(2000, "stump")
            assert est is not None
            # t_est(n0) should reproduce roughly the calibration's own
            # measured elapsed time (same n, same k by construction).
            assert abs(est - entry["elapsed_s"]) < entry["elapsed_s"] * 0.5 + 0.05
            # A second calibrate() call without force is a no-op (same entry).
            entry2 = cost.calibrate("stump", n0=2000)
            assert entry2 == entry
        finally:
            cost.CALIBRATION_PATH = orig


def test_routing_tier_thresholds():
    from Working.config import MP_BACKGROUND_BUDGET_S, MP_INTERACTIVE_BUDGET_S
    assert cost.routing_tier(MP_INTERACTIVE_BUDGET_S - 1) == "interactive"
    assert cost.routing_tier(MP_INTERACTIVE_BUDGET_S + 1) == "background"
    assert cost.routing_tier(MP_BACKGROUND_BUDGET_S + 1) == "hpc"


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
