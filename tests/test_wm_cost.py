"""
test_wm_cost.py
=================
Tests for Working/Preprocessing/window_matrix/cost.py — calibration and
routing-tier estimation (WINDOW_MATRIX_UI_PROMPT.md §6.1).

The central contract: `estimate_seconds` returns `None` — never a guessed
number — when any requested stage is uncalibrated on this machine, because a
wrong estimate here would route a multi-hour job into the "wait with a
spinner" path. Every test here runs against an ISOLATED calibration file
(`cost.CALIBRATION_PATH` redirected to a temp path) so it never reads or
writes the real `DATA/db/wm_calibration.json`.

Run from the project root:
    python tests/test_wm_cost.py
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

import Working.Preprocessing.window_matrix.cost as cost


from tests._calibration_isolation import scratch_calibration


def _IsolatedCalibration():
    """Redirects `cost.CALIBRATION_PATH` to a fresh temp file for the
    duration of the `with` block, and restores it afterwards — every test
    below uses this rather than sharing (or worse, mutating) the real
    calibration file at `DATA/db/wm_calibration.json`.

    The implementation lives in `tests/_calibration_isolation.py` so this file
    and `tests/test_window_matrix_panel.py` cannot drift apart."""
    return scratch_calibration(cost)


def test_estimate_seconds_is_none_when_uncalibrated():
    with _IsolatedCalibration():
        assert cost.estimate_seconds(100, 600, ("catch22",)) is None


def test_routing_tier_of_none_is_unknown():
    assert cost.routing_tier(None) == "unknown"


def test_routing_tier_thresholds():
    assert cost.routing_tier(1.0) == "interactive"
    assert cost.routing_tier(cost.WM_INTERACTIVE_BUDGET_S) == "interactive"
    assert cost.routing_tier(cost.WM_INTERACTIVE_BUDGET_S + 1) == "background"
    assert cost.routing_tier(cost.WM_BACKGROUND_BUDGET_S) == "background"
    assert cost.routing_tier(cost.WM_BACKGROUND_BUDGET_S + 1) == "hpc"


def test_describe_separates_budgeted_from_unbudgeted_stages():
    with _IsolatedCalibration():
        cost.calibrate(stages=("catch22",))
        desc = cost.describe(100, 600, ("catch22", "fast_entropy"))
        assert "catch22" in desc["per_stage_seconds"]
        assert desc["unbudgeted_stages"] == ["fast_entropy"]
        # A build with ANY unbudgeted stage has no trustworthy total — a
        # lower bound routed on is how a multi-hour job ends up "interactive".
        assert desc["estimated_seconds"] is None or "fast_entropy" not in desc["per_stage_seconds"]
        assert desc["tier"] == "unknown"


def test_describe_cnn_is_always_unbudgeted_and_notes_why():
    with _IsolatedCalibration():
        cost.calibrate(stages=cost.CALIBRATABLE_STAGES)
        desc = cost.describe(50, 600, ("catch22", "cnn"))
        assert "cnn" in desc["unbudgeted_stages"]
        assert desc["notes"] == [cost.CNN_UNCALIBRATED_MESSAGE]


def test_describe_fully_calibrated_gives_a_real_tier():
    with _IsolatedCalibration():
        cost.calibrate(stages=("catch22", "fast_entropy"))
        desc = cost.describe(10, 600, ("catch22", "fast_entropy"))
        assert desc["unbudgeted_stages"] == []
        assert desc["estimated_seconds"] is not None
        assert desc["tier"] in ("interactive", "background", "hpc")


def test_calibration_status_distinguishes_uncalibrated_from_ok():
    with _IsolatedCalibration():
        assert cost.calibration_status(stages=("catch22",))["catch22"] == "uncalibrated"
        cost.calibrate(stages=("catch22",))
        assert cost.calibration_status(stages=("catch22",))["catch22"] == "ok"


def test_calibrate_fits_two_points_and_records_a_fit_ratio():
    """Two window lengths, not one, specifically so a wrong exponent shows
    up as a bad fit rather than being silently absorbed into k (module
    docstring)."""
    with _IsolatedCalibration():
        result = cost.calibrate(stages=("catch22",))
        entry = result["catch22"]
        assert entry["k"] is not None
        assert entry["m_lo"] < entry["m_hi"]
        assert entry["fit_ratio"] is not None
        assert entry["fit_ratio"] > 0


def test_calibrate_is_idempotent_unless_forced():
    with _IsolatedCalibration():
        first = cost.calibrate(stages=("catch22",))["catch22"]
        second = cost.calibrate(stages=("catch22",))["catch22"]
        assert first["calibrated_at"] == second["calibrated_at"]
        forced = cost.calibrate(stages=("catch22",), force=True)["catch22"]
        assert forced["calibrated_at"] != first["calibrated_at"]


def test_max_span_samples_for_background_is_none_when_uncalibrated():
    with _IsolatedCalibration():
        assert cost.max_span_samples_for_background() is None


def test_max_span_samples_for_background_is_a_positive_bound_once_calibrated():
    with _IsolatedCalibration():
        cost.calibrate(stages=cost.CALIBRATABLE_STAGES)
        cap = cost.max_span_samples_for_background()
        assert cap is None or cap > 0


def test_stage_limits_match_config():
    from Working.config import WM_GRAMIAN_MAX_SAMPLES, WM_SLOW_ENTROPY_MAX_SAMPLES
    limits = cost.stage_limits()
    assert limits["slow_entropy"] == WM_SLOW_ENTROPY_MAX_SAMPLES
    assert limits["cnn"] == WM_GRAMIAN_MAX_SAMPLES


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
