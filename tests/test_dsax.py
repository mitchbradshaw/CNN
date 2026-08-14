"""
test_dsax.py
=============
Contract and invariant tests for dSAX (`Working.Detection.sax.dsax_python`).

The single most important test in this file is
`test_requantising_deltas_against_cutlines_reproduces_str_out` — the direct
analogue of `test_sax_details.py::test_csax_requantising_paa_against_cutlines_
reproduces_str_out`. It re-runs the quantisation decision by hand against
`details["deltas"]` and `details["cutlines"]` and must reproduce `str_out`
exactly, proving those two arrays are genuinely what produced the output
rather than a plausible-looking reconstruction. Every other key in
`details` is only as trustworthy as that one assertion makes it.

The second cluster of tests exists because of a specific, easy-to-miss
trap: a delta is a DIFFERENCE, so a normalisation offset cancels out of it.
`deltas_raw = deltas * delta_scale` with NO `+ norm_mean`, while
`paa_raw = paa * norm_std + norm_mean` — two genuinely different conversion
rules living in the same dict. `test_delta_raw_round_trip_excludes_the_mean`
asserts the wrong rule would give a different answer, so the right rule
cannot be "accidentally" right on data whose mean happens to be zero.

`threshold_mode="learned"` consumes `np.random` via `kmeanspp`, exactly as
`psax()` does, so every pair of calls being compared here reseeds
`np.random` identically immediately beforehand — the same discipline
`test_sax_details.py` follows.

Pure-numpy, no database/UI, ASCII-only output (the repo's Windows console
is cp1252 — see BASELINE.md). Runnable standalone:
    python tests/test_dsax.py
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

from Adapters._sax_common import (SEGMENT_MODES, diagnostic_rows,
                                  encoding_diagnostics, segment_plan)
from Working.Detection.sax.dsax_python.dsax import (SYMBOL_NAMES, dsax,
                                                    dsax_letters,
                                                    plot_trend_encoding)
from Working.Detection.sax.dsax_python.trend_estimators import (
    TREND_ESTIMATORS, surrogate_same_halfwidth)

# A drifting, noisy, NON-zero-mean series. The non-zero mean is deliberate:
# it is what makes the delta-vs-level conversion tests able to tell the two
# rules apart at all (on zero-mean data both rules agree, so the tests
# would pass while proving nothing).
_rng = np.random.default_rng(42)
_n = 6000
DRIFTY = (
    50.0                                                # standing DC offset
    + 3.0 * np.sin(2 * np.pi * np.arange(_n) / 900.0)   # slow morphology
    + _rng.normal(0, 0.4, _n)                           # noise
)
DIM_RATIO = (300 + 0.5) / _n     # 300 symbols out of 6000, sps = 20
SEED = 20260809


def _encode(data=None, dim_ratio=None, seed=SEED, **kwargs):
    """One seeded `dsax(..., return_details=True)` call. Seeding here rather
    than in each test keeps every comparison in this file honest by default
    (see module docstring)."""
    data = DRIFTY if data is None else data
    dim_ratio = DIM_RATIO if dim_ratio is None else dim_ratio
    np.random.seed(seed)
    return dsax(data, len(data), dim_ratio, return_details=True, **kwargs)


def _raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc:
        return True
    except Exception as e:                      # noqa: BLE001 - deliberate
        raise AssertionError(f"expected {exc.__name__}, got {e!r}")
    raise AssertionError(f"expected {exc.__name__}, nothing was raised")


# -- the core invariants ---------------------------------------------------

def test_return_details_false_is_byte_identical():
    np.random.seed(SEED)
    bare = dsax(DRIFTY, len(DRIFTY), DIM_RATIO, return_details=False)
    np.random.seed(SEED)
    detailed, _ = dsax(DRIFTY, len(DRIFTY), DIM_RATIO, return_details=True)
    assert np.array_equal(bare, detailed), "return_details=True changed str_out"


def test_requantising_deltas_against_cutlines_reproduces_str_out():
    """THE test: proves `deltas`/`cutlines` are what actually produced
    `str_out` (see module docstring). Run across every threshold mode so a
    mode-specific reporting bug cannot hide behind the default."""
    cases = [
        dict(threshold_mode="learned"),
        dict(threshold_mode="quantile", same_fraction=0.4),
        dict(threshold_mode="absolute", absolute_threshold=0.05, normalize=False),
        dict(threshold_mode="learned", alphabet_size=5),
        dict(threshold_mode="learned", force_symmetric=False),
    ]
    for kwargs in cases:
        str_out, details = _encode(**kwargs)
        by_hand = np.searchsorted(details["cutlines"], details["deltas"], side="right")
        assert np.array_equal(by_hand, str_out), f"requantisation mismatch for {kwargs}"


def test_cutlines_ascending_and_correct_length():
    for alphabet_size in (2, 3, 4, 5, 8):
        _, details = _encode(alphabet_size=alphabet_size)
        cutlines = details["cutlines"]
        assert len(cutlines) == alphabet_size - 1, f"k={alphabet_size}"
        assert details["alphabet_size"] == alphabet_size
        if len(cutlines) > 1:
            assert np.all(np.diff(cutlines) > 0), \
                f"cutlines must be STRICTLY ascending, got {cutlines}"


def test_lengths_and_symbol_range_agree():
    str_out, details = _encode(alphabet_size=5)
    assert len(details["deltas"]) == details["n_symbols"] == len(str_out)
    assert len(details["seg_slope"]) == details["n_symbols"]
    assert len(details["paa"]) == details["n_symbols"]
    assert len(details["segment_starts"]) == details["n_symbols"]
    assert len(details["segment_ends"]) == details["n_symbols"]
    assert str_out.min() >= 0
    assert str_out.max() < details["alphabet_size"]


def test_samples_dropped_accounting():
    """Mirrors `test_csax_samples_dropped_accounting`, using a length that
    does NOT divide evenly so `n_trimmed > 0` is actually exercised."""
    data = DRIFTY[:5977]
    _, details = _encode(data=data, dim_ratio=(300 + 0.5) / len(data))
    assert details["data_len_trimmed"] + details["n_trimmed"] == len(data)
    assert details["samples_per_symbol"] == \
        details["data_len_trimmed"] // details["n_symbols"]
    assert details["n_trimmed"] > 0, "test data was meant to divide unevenly"


def test_segment_bounds_tile_the_trimmed_span():
    _, details = _encode()
    starts = details["segment_starts"]
    ends = details["segment_ends"]
    sps = details["samples_per_symbol"]
    assert starts[0] == 0
    assert ends[-1] == details["data_len_trimmed"]
    assert np.array_equal(ends - starts, np.full(len(starts), sps))
    assert np.array_equal(starts[1:], ends[:-1]), "segments must tile without gaps"


# -- the two conversion rules, which are DIFFERENT -------------------------

def test_delta_raw_round_trip_excludes_the_mean():
    _, details = _encode()
    scale = details["delta_scale"]
    mean = details["norm_mean"]
    assert scale is not None and mean is not None
    assert abs(mean) > 1.0, "DRIFTY must have a large non-zero mean for this test to bite"
    assert np.array_equal(details["deltas_raw"], details["deltas"] * scale), \
        "deltas_raw must be a pure rescaling"
    # The explicitly-wrong rule must give an explicitly different answer,
    # so a passing test above cannot be a coincidence of the data.
    wrong = details["deltas"] * scale + mean
    assert not np.allclose(details["deltas_raw"], wrong), \
        "norm_mean must NOT appear in the delta conversion"
    assert np.array_equal(details["cutlines_raw"], details["cutlines"] * scale)


def test_paa_raw_round_trip_includes_the_mean():
    """The counterpart: levels DO take the offset. Together with the test
    above this pins down that the two rules are genuinely distinct."""
    _, details = _encode()
    expected = details["paa"] * details["norm_std"] + details["norm_mean"]
    assert np.allclose(details["paa_raw"], expected)
    assert not np.allclose(details["paa_raw"], details["paa"] * details["norm_std"])


def test_no_normalize_has_no_norm_constants():
    _, details = _encode(normalize=False)
    assert details["norm_mean"] is None
    assert details["norm_std"] is None
    assert details["delta_scale"] is None
    assert np.array_equal(details["deltas_raw"], details["deltas"])
    assert np.array_equal(details["cutlines_raw"], details["cutlines"])
    assert np.array_equal(details["paa_raw"], details["paa"])
    assert np.array_equal(details["representatives_raw"], details["representatives"])


def test_degenerate_variance_guard_keeps_delta_scale_at_one():
    """psax's `std < 0.001` branch mean-subtracts only; dSAX mirrors it, so
    `delta_scale` must be exactly 1.0 there rather than a near-zero divisor
    that would blow the deltas up."""
    nearly_constant = 5.0 + np.linspace(0, 1e-5, 4000)
    _, details = _encode(data=nearly_constant, dim_ratio=(200 + 0.5) / 4000)
    assert details["delta_scale"] == 1.0
    assert details["norm_std"] == 1.0
    assert np.isclose(details["norm_mean"], nearly_constant.mean())


# -- determinism -----------------------------------------------------------

def test_same_seed_gives_identical_output():
    a, da = _encode()
    b, db = _encode()
    assert np.array_equal(a, b)
    assert np.array_equal(da["cutlines"], db["cutlines"])
    assert np.array_equal(da["deltas"], db["deltas"])


def test_rng_free_modes_need_no_seed_at_all():
    """`absolute` and `quantile` must touch no RNG - which is what makes the
    engineered exact-string tests trustworthy."""
    for kwargs in (dict(threshold_mode="absolute", absolute_threshold=0.05, normalize=False),
                   dict(threshold_mode="quantile")):
        np.random.seed(1)
        a = dsax(DRIFTY, len(DRIFTY), DIM_RATIO, **kwargs)
        np.random.seed(999)
        b = dsax(DRIFTY, len(DRIFTY), DIM_RATIO, **kwargs)
        assert np.array_equal(a, b), f"{kwargs} depends on np.random"


# -- symmetry / zero anchoring --------------------------------------------

def test_force_symmetric_folds_the_cutlines_about_zero():
    _, details = _encode(force_symmetric=True, alphabet_size=5)
    cutlines = details["cutlines"]
    assert np.allclose(cutlines, -cutlines[::-1]), \
        f"force_symmetric must give a mirror-image cutline set, got {cutlines}"
    assert details["zero_symbol"] == 2, "the middle bin must contain delta = 0"


def test_even_alphabet_puts_a_cutline_exactly_on_zero():
    """Documented consequence of the folding rule: an even alphabet has no
    SAME bin, only a boundary at zero."""
    _, details = _encode(force_symmetric=True, alphabet_size=4)
    cutlines = details["cutlines"]
    assert np.isclose(cutlines[1], 0.0, atol=1e-12), \
        f"self-paired middle cutline must land on 0, got {cutlines}"


def test_force_symmetric_false_reports_the_asymmetry():
    """Asymmetric cutlines are allowed and scientifically interesting; the
    requirement is that `zero_symbol` makes them visible, not silent."""
    _, details = _encode(force_symmetric=False, alphabet_size=3)
    assert details["force_symmetric"] is False
    assert details["zero_symbol"] == int(
        np.searchsorted(details["cutlines"], 0.0, side="right"))


def test_min_same_halfwidth_widens_but_never_narrows():
    _, base = _encode(alphabet_size=3)
    base_half = (base["cutlines"][1] - base["cutlines"][0]) / 2.0

    wide = base_half * 3.0
    _, widened = _encode(alphabet_size=3, min_same_halfwidth=wide)
    assert widened["min_same_halfwidth_applied"] is True
    assert widened["cutlines"][0] <= -wide + 1e-12
    assert widened["cutlines"][1] >= wide - 1e-12
    assert widened["same_fraction_observed"] > base["same_fraction_observed"]

    narrow = base_half / 3.0
    _, unchanged = _encode(alphabet_size=3, min_same_halfwidth=narrow)
    assert np.allclose(unchanged["cutlines"], base["cutlines"]), \
        "a floor below the learned band must be a no-op, not an override"


def test_surrogate_same_halfwidth_is_positive_and_seed_reproducible():
    a = surrogate_same_halfwidth(DRIFTY, 20, n_surrogates=8, random_state=7)
    b = surrogate_same_halfwidth(DRIFTY, 20, n_surrogates=8, random_state=7)
    c = surrogate_same_halfwidth(DRIFTY, 20, n_surrogates=8, random_state=8)
    assert a > 0
    assert a == b, "same random_state must give the same half-width"
    assert a != c, "a different random_state must actually change the draw"


# -- error handling --------------------------------------------------------

def test_value_errors():
    n = 2000
    x = DRIFTY[:n]
    # sps < 2: one symbol per sample leaves no rise to measure.
    _raises(ValueError, dsax, x, n, 0.9)
    # n_symbols < 2: not a string.
    _raises(ValueError, dsax, x, n, 1.0 / n)
    _raises(ValueError, dsax, x, n, 1e-9)
    # absolute mode is a 3-symbol construction by definition.
    _raises(ValueError, dsax, x, n, 0.05, alphabet_size=5,
            threshold_mode="absolute", absolute_threshold=1.0)
    _raises(ValueError, dsax, x, n, 0.05, threshold_mode="absolute")
    _raises(ValueError, dsax, x, n, 0.05, threshold_mode="absolute",
            absolute_threshold=-1.0)
    # unknown enums
    _raises(ValueError, dsax, x, n, 0.05, trend_estimator="magic")
    _raises(ValueError, dsax, x, n, 0.05, threshold_mode="magic")
    _raises(ValueError, dsax, x, n, 0.05, alphabet_size=1)
    _raises(ValueError, dsax, x, n, 0.05, threshold_mode="quantile", same_fraction=1.5)


def test_every_declared_estimator_runs():
    for estimator in TREND_ESTIMATORS:
        str_out, details = _encode(trend_estimator=estimator)
        assert details["trend_estimator"] == estimator
        assert len(str_out) == details["n_symbols"]
        # sps here is 20, below the 200-point Theil-Sen subsampling cap.
        assert details["theil_sen_subsampled"] is False


def test_theil_sen_flags_its_own_subsampling():
    """A long segment must report that the slope it returned came from a
    thinned fit, not from the full O(sps^2) one."""
    _, details = _encode(dim_ratio=(20 + 0.5) / _n, trend_estimator="theil_sen")
    assert details["samples_per_symbol"] > 200
    assert details["theil_sen_subsampled"] is True


# -- letters ---------------------------------------------------------------

def test_dsax_letters_three_symbol_alphabet():
    assert dsax_letters([0, 1, 2, 2, 1, 0], 3) == "DSUUSD"
    assert SYMBOL_NAMES[3] == ("DOWN", "SAME", "UP")
    assert SYMBOL_NAMES[5][2] == "SAME"


def test_dsax_letters_five_symbol_alphabet():
    """CHANGED 2026-08-10 by DSAX_UI_PROMPT.md Phase E, which mandates a
    single-character k=5 scheme. This previously asserted "abcde" (the
    repo-wide a/b/c fallback). Case encodes MAGNITUDE and the letter
    encodes direction, so `[Dd]` matches any fall, `[Uu]` any rise, and a
    case-insensitive k=3 pattern still matches at k=5. Flagged in
    UI_INTEGRATION_NOTES.md as an intentional expectation change, not a
    weakened test - see `dsax.SYMBOL_LETTERS`."""
    assert dsax_letters([0, 1, 2, 3, 4], 5) == "dDSUu"
    assert len(set("dDSUu")) == 5, "the k=5 letters must be mutually distinct"


def test_dsax_letters_undeclared_alphabets_use_the_repo_convention():
    """Only sizes with a declared mnemonic get one; everything else falls
    back to a/b/c rather than inventing a scheme. Every EVEN size is
    deliberately in this group - an even alphabet has no SAME bin, so a
    D/S/U-shaped mnemonic would be misleading there."""
    assert dsax_letters([0, 1, 2, 3], 4) == "abcd"
    assert dsax_letters([0, 1, 2, 3, 4, 5, 6], 7) == "abcdefg"


def test_dsax_letters_length_matches_symbols():
    str_out, details = _encode()
    assert len(dsax_letters(str_out, details["alphabet_size"])) == details["n_symbols"]


# -- representatives -------------------------------------------------------

def test_representatives_are_sorted_and_sized():
    for kwargs in (dict(threshold_mode="learned"),
                   dict(threshold_mode="quantile"),
                   dict(threshold_mode="absolute", absolute_threshold=0.05, normalize=False)):
        _, details = _encode(alphabet_size=3, **kwargs)
        reps = details["representatives"]
        assert len(reps) == 3, kwargs
        assert np.all(np.diff(reps) > 0), f"representatives must ascend, got {reps} for {kwargs}"


# -- integration with the existing shared code (read-only use of it) -------

def test_segment_plan_round_trips_through_dsax():
    """`segment_plan` must resolve a control to exactly the segmentation
    dSAX then produces, for every mode including ones that divide unevenly
    - the same guarantee `_sax_common` already gives cSAX/pSAX."""
    fs = 1.0
    checked = 0
    for n in (6000, 5977, 4096, 3001):
        data = DRIFTY[:n]
        for segment_mode in SEGMENT_MODES:
            for value in (20, 37, 100):
                params = {
                    "segment_mode": segment_mode,
                    "seconds_per_symbol": float(value),
                    "samples_per_symbol": int(value),
                    "target_symbol_count": max(2, n // value),
                    "dim_ratio": 1.0 / value,
                }
                plan = segment_plan(segment_mode, params, fs, n)
                if plan["n_symbols"] < 2 or plan["achieved_sps"] < 2:
                    continue
                _, details = _encode(data=data, dim_ratio=plan["dim_ratio_for_call"],
                                     threshold_mode="quantile")
                assert details["n_symbols"] == plan["n_symbols"], \
                    f"{segment_mode}/{value}/n={n}: {details['n_symbols']} != {plan['n_symbols']}"
                assert details["samples_per_symbol"] == plan["achieved_sps"], \
                    f"{segment_mode}/{value}/n={n}: sps mismatch"
                assert details["data_len_trimmed"] == plan["data_len_trimmed"]
                assert details["n_trimmed"] == plan["n_trimmed"]
                checked += 1
    assert checked >= 30, f"only {checked} segment_plan combinations were exercised"


def test_encoding_diagnostics_on_a_three_symbol_alphabet():
    ceiling = np.log2(3)
    assert abs(ceiling - 1.585) < 0.001

    all_same = np.ones(300, dtype=int)
    diag = encoding_diagnostics(all_same, 3)
    assert np.isclose(diag["occupancy_entropy_ceiling_bits"], ceiling)
    assert diag["occupancy_entropy_bits"] == 0.0
    assert diag["self_transition_rate"] == 1.0

    rng = np.random.default_rng(3)
    balanced = rng.integers(0, 3, 3000)
    diag = encoding_diagnostics(balanced, 3)
    assert diag["occupancy_entropy_bits"] > 1.3


def test_all_same_string_trips_the_existing_entropy_warn_path():
    """A dead channel must be *reported* as collapsed by the shared
    diagnostics, not silently pass as a valid encoding."""
    constant = np.full(4000, 5.0)
    str_out, details = _encode(data=constant, dim_ratio=(200 + 0.5) / 4000)
    assert np.all(str_out == 1), "a constant signal must encode as all-SAME"
    rows = diagnostic_rows(str_out, details)
    entropy_row = [r for r in rows if r[0] == "Occupancy entropy"][0]
    assert entropy_row[2] == "warn", f"expected a warn severity, got {entropy_row}"
    transition_row = [r for r in rows if r[0] == "Transition self-rate"][0]
    assert transition_row[2] == "warn"


def test_discover_adapters_registers_dsax():
    """Promoted 2026-08-10 (DSAX_UI_PROMPT.md Phase A): the adapter moved
    from `Working/.../adapter_draft.py` to `Adapters/detection_sax_dsax.py`
    and now self-registers at import like every other adapter, so it
    appears in the run panel's algorithm list. This assertion is the
    INVERSE of the one it replaces - see UI_INTEGRATION_NOTES.md."""
    from Adapters.registry import discover_adapters
    names = [spec.name for spec in discover_adapters()]
    assert "detection.sax_dsax" in names, \
        "the dSAX adapter must be auto-discovered now that it is promoted"
    assert "detection.sax_psax" in names, "sanity: discovery itself must be working"


def test_adapter_spec_is_well_formed():
    """The registered spec round-trips its own params."""
    from Adapters.detection_sax_dsax import SPEC

    assert SPEC.name == "detection.sax_dsax"
    assert SPEC.stage == "detection"
    assert SPEC.output_kind == "encoding"
    assert callable(SPEC.run) and callable(SPEC.plot)
    assert callable(SPEC.recommend) and callable(SPEC.derive)

    defaults = SPEC.validate_params()
    assert defaults["alphabet_size"] == 3
    assert defaults["trend_estimator"] == "ols_slope"
    assert defaults["threshold_mode"] == "learned"
    # round-trip: validated params must survive re-validation unchanged
    assert SPEC.validate_params(defaults) == defaults
    _raises(ValueError, SPEC.validate_params, {"not_a_param": 1})
    _raises(ValueError, SPEC.validate_params, {"trend_estimator": "magic"})
    _raises(ValueError, SPEC.validate_params, {"alphabet_size": 99})


def test_adapter_run_and_derive_actually_work():
    from Adapters.detection_sax_dsax import SPEC

    fs = 1.0
    x = DRIFTY[:3000]
    t = np.arange(len(x)) / fs
    params = SPEC.validate_params({"segment_mode": "samples_per_symbol",
                                   "samples_per_symbol": 20})
    np.random.seed(SEED)
    result = SPEC.run(x, t, fs, **params)
    assert result.output_kind == "encoding"
    assert len(result.encoding) == 150
    assert result.meta["details"]["samples_per_symbol"] == 20
    assert "segment_plan" in result.meta["details"]

    rows = SPEC.derive(x, t, fs, params)
    assert any(label == "Symbols produced" for label, _, _ in rows)
    assert set(SPEC.recommend(x, t, fs)) >= {"segment_mode", "seconds_per_symbol"}


def test_adapter_zero_sentinels_mean_unset():
    """The float-0.0-means-None sentinel must not be mistaken for a real
    threshold - a 0.0 absolute_threshold would otherwise raise."""
    from Adapters.detection_sax_dsax import SPEC

    fs = 1.0
    x = DRIFTY[:3000]
    t = np.arange(len(x)) / fs
    params = SPEC.validate_params({"segment_mode": "samples_per_symbol",
                                   "samples_per_symbol": 20,
                                   "absolute_threshold": 0.0,
                                   "min_same_halfwidth": 0.0})
    np.random.seed(SEED)
    result = SPEC.run(x, t, fs, **params)
    assert result.meta["details"]["threshold_mode"] == "learned"
    assert result.meta["details"]["min_same_halfwidth_applied"] is False


# -- plotting (headless) ---------------------------------------------------

def test_plot_trend_encoding_writes_a_file_headlessly():
    import tempfile

    str_out, details = _encode(dim_ratio=(30 + 0.5) / _n)
    t = np.arange(len(DRIFTY), dtype=float)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "nested", "dsax.png")
        fig = plot_trend_encoding(DRIFTY, t, str_out, details, path=path)
        assert os.path.exists(path) and os.path.getsize(path) > 1000
        assert len(fig.axes) == 4
        import matplotlib.pyplot as plt
        plt.close(fig)


# -- runner ----------------------------------------------------------------

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
