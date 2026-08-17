"""
test_distances.py
===================
Contract tests for `Working.distances` (T35) — the three named,
recordable-on-an-edge distance functions between two spans' shapes:

  DISTANCE_SCALE_INVARIANT  resample both spans to a common length,
                            z-normalise, Euclidean. The primary distance.
  DISTANCE_SYMBOLIC         SAX minimum-distance (MINDIST) at a fixed
                            word length, via the existing SAX ports.
  DISTANCE_NATIVE_LENGTH    z-normalised Euclidean at native length, no
                            resampling — the unnormalised control.

The test that matters (`test_scale_invariant_is_near_zero_control_is_large`)
asserts the actual research claim: a pair identical in shape but differing
in duration is near-zero under the scale-invariant distance and large
under the control. Every other test hand-verifies one distance against an
independently worked expected value.

Pure-numpy, no database/UI. Runnable standalone:
    python tests/test_distances.py
"""

import inspect
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.distances import (
    DISTANCE_NATIVE_LENGTH,
    DISTANCE_REGISTRY,
    DISTANCE_SCALE_INVARIANT,
    DISTANCE_SYMBOLIC,
    native_length_distance,
    scale_invariant_distance,
    symbolic_distance,
)


# -- the test that matters ---------------------------------------------------

def test_scale_invariant_is_near_zero_control_is_large():
    # Same shape (one full sine cycle), sampled at two very different
    # durations — 50 samples vs. 200 samples.
    t1 = np.linspace(0, 1, 50, endpoint=False)
    t2 = np.linspace(0, 1, 200, endpoint=False)
    shape1 = np.sin(2 * np.pi * t1)
    shape2 = np.sin(2 * np.pi * t2)

    scale_dist = scale_invariant_distance(shape1, shape2)
    native_dist = native_length_distance(shape1, shape2)

    assert scale_dist < 1.0, scale_dist
    assert native_dist > 5.0, native_dist
    assert native_dist > 10 * scale_dist, (scale_dist, native_dist)


# -- named constants, not anonymous callables --------------------------------

def test_named_constants_are_recorded_in_a_registry():
    assert isinstance(DISTANCE_SCALE_INVARIANT, str)
    assert isinstance(DISTANCE_SYMBOLIC, str)
    assert isinstance(DISTANCE_NATIVE_LENGTH, str)
    names = {DISTANCE_SCALE_INVARIANT, DISTANCE_SYMBOLIC, DISTANCE_NATIVE_LENGTH}
    assert len(names) == 3, "the three names must be distinct"
    assert set(DISTANCE_REGISTRY) == names
    assert DISTANCE_REGISTRY[DISTANCE_SCALE_INVARIANT] is scale_invariant_distance
    assert DISTANCE_REGISTRY[DISTANCE_SYMBOLIC] is symbolic_distance
    assert DISTANCE_REGISTRY[DISTANCE_NATIVE_LENGTH] is native_length_distance


# -- hand-computed cases ------------------------------------------------------

def test_scale_invariant_hand_case_same_shape_different_amplitude():
    # [1,2,3] and [2,4,6] are the same shape (scaled by 2), same length ->
    # z-normalising removes the amplitude scale entirely -> distance 0.
    x1 = np.array([1.0, 2.0, 3.0])
    x2 = np.array([2.0, 4.0, 6.0])
    assert np.isclose(scale_invariant_distance(x1, x2), 0.0, atol=1e-9)


def test_native_length_hand_case_reversed_shape():
    # z([1,2,3]) = [-sqrt(3/2), 0, sqrt(3/2)]; z([3,2,1]) is its negation.
    # ||z1 - z2|| = ||[-2*sqrt(3/2), 0, 2*sqrt(3/2)]|| = sqrt(2 * (2*sqrt(3/2))**2)
    #             = sqrt(2 * 4 * 1.5) = sqrt(12) = 2*sqrt(3)
    x1 = np.array([1.0, 2.0, 3.0])
    x2 = np.array([3.0, 2.0, 1.0])
    expected = 2 * np.sqrt(3)
    assert np.isclose(native_length_distance(x1, x2), expected, atol=1e-9)


def test_native_length_truncates_to_the_shorter_span_no_resampling():
    # Different lengths: native-length compares the first min(len) samples
    # of each, unresampled. [1,2,3,4] truncated to 3 is [1,2,3], the same
    # hand case as above once truncated against [3,2,1].
    x1 = np.array([1.0, 2.0, 3.0, 4.0])
    x2 = np.array([3.0, 2.0, 1.0])
    expected = 2 * np.sqrt(3)
    assert np.isclose(native_length_distance(x1, x2), expected, atol=1e-9)


def test_symbolic_hand_case_mindist_between_mirrored_symbol_strings():
    # word_length == len(x) so PAA is the identity; alphabet_size=4 gives
    # cutlines = norm.ppf([.25, .5, .75]). z([-2,-1,1,2]) straddles all
    # three cutlines -> symbols [0,1,2,3]; the mirrored series [2,1,-1,-2]
    # gives symbols [3,2,1,0]. Adjacent-symbol pairs (1,2) contribute 0
    # (MINDIST treats |r-c|<=1 as indistinguishable); the two (0,3)/(3,0)
    # pairs each contribute (cutlines[2] - cutlines[0]).
    from scipy.stats import norm as _norm
    cutlines = _norm.ppf(np.arange(1, 4) / 4.0)
    cell = cutlines[2] - cutlines[0]
    expected = np.sqrt(2 * cell ** 2)

    x1 = np.array([-2.0, -1.0, 1.0, 2.0])
    x2 = np.array([2.0, 1.0, -1.0, -2.0])
    got = symbolic_distance(x1, x2, word_length=4, alphabet_size=4)
    assert np.isclose(got, expected, atol=1e-9), (got, expected)


def test_symbolic_distance_is_zero_for_identical_shape():
    x = np.array([-2.0, -1.0, 1.0, 2.0, 1.5, 0.5])
    assert np.isclose(symbolic_distance(x, x.copy(), word_length=3, alphabet_size=4), 0.0, atol=1e-9)


# -- runner --------------------------------------------------------------

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
