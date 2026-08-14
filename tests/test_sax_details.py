"""
test_sax_details.py
=====================
Tests for Part 1 (2026-08): `return_details=False` must be byte-identical
to the pre-existing `csax()`/`psax()` output, and `return_details=True`'s
extra `details` dict must describe the ACTUAL decision that produced
`str_out` — not a plausible-looking reconstruction. The `_requantise_*`
tests are the important ones: they re-run `_map_to_string`'s own logic
by hand (`np.searchsorted`) against `details["paa"]`/`["cutlines"]` and
must reproduce `str_out` exactly, proving those two arrays are genuinely
the ones the algorithm used, not `training_paa` (a similar-but-distinct
array — see `csax.py`'s module docstring for why the two differ).

Both `csax()` and `psax()` consume `np.random` (Mean-Shift's random seed
point, k-means++'s random init) — every pair of calls being compared here
reseeds `np.random` identically immediately beforehand so the comparison
is meaningful rather than flaky.

Pure-numpy, no database/UI — runnable standalone:
    python tests/test_sax_details.py
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

from Working.Detection.sax.csax_python.csax import csax
from Working.Detection.sax.psax_python.psax import psax

# Bimodal, well-separated data -- reliably gives cSAX's Mean-Shift >= 2
# clusters (no fallback) so the "normal" path's cutlines/representatives
# are non-degenerate.
_rng = np.random.default_rng(42)
BIMODAL = np.concatenate([_rng.normal(0, 1, 3000), _rng.normal(5, 2, 3000)])
DIM_RATIO = 1 / 20  # 300 symbols out of 6000
CONSTANT = np.full(2000, 5.0)  # forces cSAX's Mean-Shift fallback


def _requantise(details):
    """The exact hand-rolled equivalent of `_map_to_string`'s decision,
    via `np.searchsorted` -- see module docstring."""
    return np.searchsorted(details["cutlines"], details["paa"], side="right")


# ── cSAX ─────────────────────────────────────────────────────────────────

def test_csax_return_details_false_is_byte_identical():
    np.random.seed(123)
    bare = csax(BIMODAL, len(BIMODAL), DIM_RATIO, normalize=True, return_details=False)
    np.random.seed(123)
    detailed, _ = csax(BIMODAL, len(BIMODAL), DIM_RATIO, normalize=True, return_details=True)
    assert np.array_equal(bare, detailed), "return_details=True changed str_out"


def test_csax_cutlines_shape_and_ascending():
    np.random.seed(123)
    _, details = csax(BIMODAL, len(BIMODAL), DIM_RATIO, normalize=True, return_details=True)
    assert len(details["cutlines"]) == details["alphabet_size"] - 1
    assert np.all(np.diff(details["cutlines"]) > 0), "cutlines must be strictly ascending"


def test_csax_paa_length_matches_n_symbols():
    np.random.seed(123)
    _, details = csax(BIMODAL, len(BIMODAL), DIM_RATIO, normalize=True, return_details=True)
    assert len(details["paa"]) == details["n_symbols"]


def test_csax_symbol_indices_in_range():
    np.random.seed(123)
    str_out, details = csax(BIMODAL, len(BIMODAL), DIM_RATIO, normalize=True, return_details=True)
    assert str_out.min() >= 0
    assert str_out.max() < details["alphabet_size"]


def test_csax_requantising_paa_against_cutlines_reproduces_str_out():
    """The important one -- proves `paa`/`cutlines` are what actually
    produced `str_out`, not a reconstruction (see module docstring)."""
    np.random.seed(123)
    str_out, details = csax(BIMODAL, len(BIMODAL), DIM_RATIO, normalize=True, return_details=True)
    assert np.array_equal(_requantise(details), str_out)


def test_csax_raw_units_round_trip():
    np.random.seed(123)
    _, details = csax(BIMODAL, len(BIMODAL), DIM_RATIO, normalize=True, return_details=True)
    assert details["norm_std"] is not None
    paa_back = (details["paa_raw"] - details["norm_mean"]) / details["norm_std"]
    cutlines_back = (details["cutlines_raw"] - details["norm_mean"]) / details["norm_std"]
    assert np.allclose(paa_back, details["paa"])
    assert np.allclose(cutlines_back, details["cutlines"])


def test_csax_no_normalize_has_no_norm_constants():
    np.random.seed(123)
    _, details = csax(BIMODAL, len(BIMODAL), DIM_RATIO, normalize=False, return_details=True)
    assert details["norm_mean"] is None
    assert details["norm_std"] is None
    assert np.array_equal(details["paa_raw"], details["paa"])
    assert np.array_equal(details["cutlines_raw"], details["cutlines"])


def test_csax_fallback_path_is_flagged_and_still_reproducible():
    np.random.seed(5)
    str_out, details = csax(CONSTANT, len(CONSTANT), DIM_RATIO, normalize=True, return_details=True)
    assert details["fallback_used"] is True
    assert details["alphabet_size"] == 10
    assert len(details["cutlines"]) == 9
    assert len(details["representatives"]) == 10
    assert np.array_equal(_requantise(details), str_out)


def test_csax_samples_dropped_accounting():
    # A length that does NOT divide evenly at this dim_ratio, to exercise
    # n_trimmed > 0.
    data = BIMODAL[:5977]
    np.random.seed(123)
    _, details = csax(data, len(data), DIM_RATIO, normalize=True, return_details=True)
    assert details["data_len_trimmed"] + details["n_trimmed"] == len(data)
    assert details["samples_per_symbol"] == details["data_len_trimmed"] // details["n_symbols"]


# ── pSAX ─────────────────────────────────────────────────────────────────

def test_psax_return_details_false_is_byte_identical():
    np.random.seed(99)
    bare = psax(BIMODAL, len(BIMODAL), DIM_RATIO, alphabet_size=8, normalize=True, return_details=False)
    np.random.seed(99)
    detailed, _ = psax(BIMODAL, len(BIMODAL), DIM_RATIO, alphabet_size=8, normalize=True, return_details=True)
    assert np.array_equal(bare, detailed)


def test_psax_cutlines_shape_and_ascending():
    np.random.seed(99)
    _, details = psax(BIMODAL, len(BIMODAL), DIM_RATIO, alphabet_size=8, normalize=True, return_details=True)
    assert len(details["cutlines"]) == details["alphabet_size"] - 1 == 7
    assert np.all(np.diff(details["cutlines"]) > 0)


def test_psax_paa_length_matches_n_symbols():
    np.random.seed(99)
    _, details = psax(BIMODAL, len(BIMODAL), DIM_RATIO, alphabet_size=8, normalize=True, return_details=True)
    assert len(details["paa"]) == details["n_symbols"]


def test_psax_symbol_indices_in_range():
    np.random.seed(99)
    str_out, details = psax(BIMODAL, len(BIMODAL), DIM_RATIO, alphabet_size=8, normalize=True, return_details=True)
    assert str_out.min() >= 0
    assert str_out.max() < details["alphabet_size"]


def test_psax_requantising_paa_against_cutlines_reproduces_str_out():
    np.random.seed(99)
    str_out, details = psax(BIMODAL, len(BIMODAL), DIM_RATIO, alphabet_size=8, normalize=True, return_details=True)
    assert np.array_equal(_requantise(details), str_out)


def test_psax_raw_units_round_trip():
    np.random.seed(99)
    _, details = psax(BIMODAL, len(BIMODAL), DIM_RATIO, alphabet_size=8, normalize=True, return_details=True)
    paa_back = (details["paa_raw"] - details["norm_mean"]) / details["norm_std"]
    cutlines_back = (details["cutlines_raw"] - details["norm_mean"]) / details["norm_std"]
    assert np.allclose(paa_back, details["paa"])
    assert np.allclose(cutlines_back, details["cutlines"])


def test_psax_representatives_length_matches_alphabet():
    np.random.seed(99)
    _, details = psax(BIMODAL, len(BIMODAL), DIM_RATIO, alphabet_size=8, normalize=True, return_details=True)
    assert len(details["representatives"]) == details["alphabet_size"] == 8
    assert np.all(np.diff(details["representatives"]) >= 0), "representatives should be sorted"


# ── runner ───────────────────────────────────────────────────────────────

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
