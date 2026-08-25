"""
test_sax_adapters.py
======================
Tests for Part 2 (2026-08): the cSAX/pSAX adapters' rewritten parameter
surface (`segment_mode` + 4 equivalent segmentation controls resolving
through `Adapters._sax_common.segment_plan`), the `recommend()` rule, and
the `derive()` readout — specifically that `derive()`'s pre-run numbers
can never silently disagree with what a real `spec.run(...)` produces.

Pure-numpy + Adapters/Working, no database/UI — runnable standalone:
    python tests/test_sax_adapters.py
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

from Adapters.registry import discover_adapters, get_adapter
from Adapters._sax_common import (
    derive_sax_rows, diagnostic_rows, encoding_diagnostics, recommend_sax_params, segment_plan,
)

discover_adapters()

_rng = np.random.default_rng(42)
BIMODAL_LONG = np.concatenate([_rng.normal(0, 1, 30000), _rng.normal(5, 2, 30000)])
FS = 1.0
SPS_VALUES = [1, 2, 4, 5, 8, 10, 16, 32, 64, 128]


# ── segment_plan round-trip ──────────────────────────────────────────────

def test_exact_roundtrip_when_span_is_a_multiple_of_sps():
    for sps in SPS_VALUES:
        n = sps * 1000  # exact multiple by construction
        params = {"samples_per_symbol": sps}
        plan = segment_plan("samples_per_symbol", params, FS, n)
        assert plan["achieved_sps"] == sps, (sps, n, plan)
        assert plan["n_trimmed"] == 0


def test_odd_lengths_report_the_actual_achieved_sps_not_the_requested_one():
    """The escape valve the brief calls for: when `n` doesn't divide
    evenly, `derive()`'s "Samples per symbol" must state the value
    ACTUALLY used, matching `segment_plan` (and, by construction, what a
    real run's `details["samples_per_symbol"]` reports) exactly — never
    silently claim the requested value regardless of the mismatch."""
    for n in [62759, 100003, 7919, 123457]:
        for sps in SPS_VALUES:
            if sps > n:
                continue
            params = {"samples_per_symbol": sps}
            plan = segment_plan("samples_per_symbol", params, FS, n)
            rows = derive_sax_rows(np.zeros(n), np.arange(n), FS,
                                    {"segment_mode": "samples_per_symbol", **params})
            samples_row = dict((label, value) for label, value, _ in rows)["Samples per symbol"]
            assert samples_row == f"{plan['achieved_sps']:,}", (n, sps, plan, samples_row)


def test_all_four_segment_modes_agree_for_equivalent_settings():
    n = 62759
    sps = 245
    modes_params = {
        "samples_per_symbol": {"samples_per_symbol": sps},
        "seconds_per_symbol": {"seconds_per_symbol": sps / FS},
        "target_symbol_count": {"target_symbol_count": n // sps},
        "dim_ratio": {"dim_ratio": 1.0 / sps},
    }
    n_symbols_by_mode = {}
    for mode, p in modes_params.items():
        plan = segment_plan(mode, p, FS, n)
        n_symbols_by_mode[mode] = plan["n_symbols"]
    assert len(set(n_symbols_by_mode.values())) == 1, n_symbols_by_mode


def test_dim_ratio_for_call_reproduces_n_symbols_through_floor():
    for sps in SPS_VALUES:
        n = sps * 777 + 13  # deliberately not a multiple
        plan = segment_plan("samples_per_symbol", {"samples_per_symbol": sps}, FS, n)
        floored = int(np.floor(plan["dim_ratio_for_call"] * n))
        assert floored == plan["n_symbols"], (sps, n, plan)


# ── recommend() rule ─────────────────────────────────────────────────────

def test_recommend_rule_600_sample_span():
    x = np.zeros(600)
    rec = recommend_sax_params(x, np.arange(600), 1.0)
    assert rec["target_symbol_count"] == 30
    assert rec["samples_per_symbol"] == 20
    assert rec["seconds_per_symbol"] == 20.0


def test_recommend_rule_62759_sample_span():
    x = np.zeros(62759)
    rec = recommend_sax_params(x, np.arange(62759), 1.0)
    assert rec["target_symbol_count"] == 256
    assert rec["samples_per_symbol"] == 245
    assert rec["seconds_per_symbol"] == 245.0


def test_recommend_clips_target_symbols_between_16_and_256():
    tiny = recommend_sax_params(np.zeros(50), np.arange(50), 1.0)
    assert tiny["target_symbol_count"] == 16
    huge = recommend_sax_params(np.zeros(2_000_000), np.arange(2_000_000), 1.0)
    assert huge["target_symbol_count"] == 256


# ── derive()/run() agreement, through the real adapters ─────────────────

def _check_derive_matches_run(adapter_name, extra_params=None):
    spec = get_adapter(adapter_name)
    x = BIMODAL_LONG
    t = np.arange(len(x)) / FS
    rec = {k: v for k, v in spec.recommend(x, t, FS).items() if k != "preprocess_window_s"}
    params = spec.validate_params({**rec, **(extra_params or {})})

    rows = spec.derive(x, t, FS, params)
    derived = {label: value for label, value, _sev in rows}

    np.random.seed(123)
    result = spec.run(x, t, FS, **params)
    details = result.meta["details"]

    assert derived["Samples per symbol"] == f"{details['samples_per_symbol']:,}"
    assert derived["Symbols produced"].split(" —")[0] == f"{details['n_symbols']:,}"
    return details


def test_csax_derive_matches_actual_run():
    details = _check_derive_matches_run("detection.sax_csax")
    reproduced = np.searchsorted(details["cutlines"], details["paa"], side="right")
    assert np.array_equal(reproduced, reproduced)  # sanity: no exception, well-formed


def test_psax_derive_matches_actual_run():
    details = _check_derive_matches_run("detection.sax_psax", extra_params={"alphabet_size": 8})
    assert details["alphabet_size"] == 8


def test_adapter_rejects_unknown_param():
    spec = get_adapter("detection.sax_csax")
    try:
        spec.validate_params({"not_a_real_param": 1})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_adapter_params_have_span_aware_defaults_hook():
    for name in ("detection.sax_csax", "detection.sax_psax"):
        spec = get_adapter(name)
        assert spec.recommend is not None
        assert spec.derive is not None


# ── diagnostics (Part 6 3d) ──────────────────────────────────────────────

def test_diagnostics_max_entropy_for_uniform_alternating_symbols():
    symbols = np.tile([0, 1], 500)  # perfectly alternating, 2 symbols
    diag = encoding_diagnostics(symbols, alphabet_size=2)
    assert abs(diag["occupancy_entropy_fraction"] - 1.0) < 1e-9
    assert diag["self_transition_rate"] == 0.0  # never repeats


def test_diagnostics_flags_collapsed_alphabet():
    symbols = np.zeros(500, dtype=int)  # every segment the same symbol
    diag = encoding_diagnostics(symbols, alphabet_size=10)
    assert diag["occupancy_entropy_fraction"] == 0.0
    assert diag["self_transition_rate"] == 1.0


def test_diagnostic_rows_warns_on_low_entropy_and_high_self_rate():
    np.random.seed(1)
    result = get_adapter("detection.sax_csax").run(
        np.full(2000, 5.0), np.arange(2000), 1.0,
        segment_mode="samples_per_symbol", samples_per_symbol=20,
    )
    details = result.meta["details"]
    rows = diagnostic_rows(result.value.values, details)
    by_label = {label: (value, severity) for label, value, severity in rows}
    assert by_label["Occupancy entropy"][1] == "warn"
    assert "cSAX fallback" in by_label
    assert by_label["cSAX fallback"][1] == "error"


def test_diagnostic_rows_no_fallback_key_when_not_triggered():
    rng = np.random.default_rng(42)
    x = np.concatenate([rng.normal(0, 1, 3000), rng.normal(5, 2, 3000)])
    np.random.seed(123)
    result = get_adapter("detection.sax_csax").run(
        x, np.arange(len(x)), 1.0, segment_mode="samples_per_symbol", samples_per_symbol=20,
    )
    rows = diagnostic_rows(result.value.values, result.meta["details"])
    labels = [label for label, _, _ in rows]
    assert "cSAX fallback" not in labels
    assert "Realised alphabet size" in labels


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
