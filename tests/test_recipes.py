"""
test_recipes.py
=================
Tests for Working/recipes.py: canonical-JSON hash stability (dict key
order, numpy-vs-native numeric types, float formatting) and recipe
construction/validation.

Run from the project root:
    python tests/test_recipes.py
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

from Working.recipes import canonical_json, make_recipe, recipe_hash, recipe_summary, short_hash


def _simple_recipe(**param_overrides):
    params = {"cutoff_hz": 0.05, "order": 4}
    params.update(param_overrides)
    return make_recipe(
        1, [{"stage": "preprocessing", "algorithm": "lowpass", "params": params}],
        span=(100, 700),
    )


# ── hash stability ───────────────────────────────────────────────────────────

def test_hash_is_deterministic_for_identical_recipe():
    r = _simple_recipe()
    assert recipe_hash(r) == recipe_hash(_simple_recipe())


def test_hash_ignores_dict_key_insertion_order():
    r1 = make_recipe(1, [{"stage": "preprocessing", "algorithm": "lowpass",
                           "params": {"cutoff_hz": 0.05, "order": 4}}], span=(100, 700))
    r2 = make_recipe(1, [{"stage": "preprocessing", "algorithm": "lowpass",
                           "params": {"order": 4, "cutoff_hz": 0.05}}], span=(100, 700))
    assert recipe_hash(r1) == recipe_hash(r2)


def test_hash_ignores_numpy_vs_native_numeric_types():
    r_native = _simple_recipe(cutoff_hz=0.05, order=4)
    r_numpy = _simple_recipe(cutoff_hz=np.float64(0.05), order=np.int64(4))
    assert recipe_hash(r_native) == recipe_hash(r_numpy)


def test_hash_differs_for_different_param_values():
    r1 = _simple_recipe(cutoff_hz=0.05)
    r2 = _simple_recipe(cutoff_hz=0.06)
    assert recipe_hash(r1) != recipe_hash(r2)


def test_hash_differs_for_different_span():
    r1 = make_recipe(1, [{"stage": "detection", "algorithm": "rupture", "params": {}}], span=(0, 100))
    r2 = make_recipe(1, [{"stage": "detection", "algorithm": "rupture", "params": {}}], span=(0, 200))
    assert recipe_hash(r1) != recipe_hash(r2)


def test_hash_differs_whole_channel_vs_span():
    r1 = make_recipe(1, [{"stage": "detection", "algorithm": "rupture", "params": {}}], span=None)
    r2 = make_recipe(1, [{"stage": "detection", "algorithm": "rupture", "params": {}}], span=(0, 100))
    assert recipe_hash(r1) != recipe_hash(r2)


def test_hash_stable_across_repeated_calls_same_process():
    # Regression guard against any hidden non-determinism (e.g. set iteration
    # order leaking into serialization) across repeated calls.
    r = _simple_recipe()
    hashes = {recipe_hash(r) for _ in range(20)}
    assert len(hashes) == 1


def test_short_hash_is_first_8_chars_of_full_hash():
    r = _simple_recipe()
    assert short_hash(r) == recipe_hash(r)[:8]
    assert len(short_hash(r)) == 8


def test_chained_steps_order_matters_for_hash():
    # Both steps output_kind="signal" and declare no input_kind, so the
    # chain validates in either order (ticket 13, "chain validation") —
    # this test is only about hash order-sensitivity, not chain validity.
    steps_ab = [
        {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
        {"stage": "preprocessing", "algorithm": "highpass", "params": {"cutoff_hz": 0.01}},
    ]
    steps_ba = list(reversed(steps_ab))
    r_ab = make_recipe(1, steps_ab, span=(0, 100))
    r_ba = make_recipe(1, steps_ba, span=(0, 100))
    assert recipe_hash(r_ab) != recipe_hash(r_ba)


def test_canonical_json_has_no_whitespace_variation():
    r = _simple_recipe()
    s = canonical_json(r)
    assert " " not in s
    assert "\n" not in s


def test_canonical_json_rejects_numpy_array_param():
    r = {"recording_id": 1, "span": None, "steps": [
        {"stage": "detection", "algorithm": "x", "params": {"bad": np.array([1, 2, 3])}}
    ]}
    try:
        canonical_json(r)
        assert False, "expected TypeError"
    except TypeError:
        pass


# ── recipe construction / validation ────────────────────────────────────────

def test_make_recipe_rejects_unknown_stage():
    try:
        make_recipe(1, [{"stage": "bogus", "algorithm": "x", "params": {}}])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_make_recipe_rejects_empty_steps():
    try:
        make_recipe(1, [])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_make_recipe_rejects_backwards_span():
    try:
        make_recipe(1, [{"stage": "detection", "algorithm": "x", "params": {}}], span=(100, 50))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_make_recipe_defaults_params_to_empty_dict():
    r = make_recipe(1, [{"stage": "detection", "algorithm": "x"}])
    assert r["steps"][0]["params"] == {}


def test_recipe_summary_format():
    r = make_recipe(1, [
        {"stage": "preprocessing", "algorithm": "lowpass", "params": {}},
        {"stage": "detection", "algorithm": "rupture", "params": {}},
    ])
    assert recipe_summary(r) == "preprocessing.lowpass -> detection.rupture"


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
