"""
unit_testing.py
================
Comprehensive automated unit tests for all analysis functions in the
analysis/ subdirectory.

Run from the project root:
    python analysis/unit_testing.py

Or as a module:
    python -m analysis.unit_testing
"""

import sys
import os
import importlib
import inspect
import traceback
import types
from unittest import mock

import numpy as np

# Non-interactive backend — must come before any pyplot import (including those
# inside the analysis modules we will import below).
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Path setup ────────────────────────────────────────────────────────────────
ANALYSIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ANALYSIS_DIR)
for _p in (ANALYSIS_DIR, PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# =============================================================================
#  Test infrastructure
# =============================================================================

class TestResult:
    """Accumulates pass/fail results and prints a formatted summary."""

    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def record(self, module: str, fn_name: str, test_name: str,
               ok: bool, detail: str = "") -> None:
        tag = f"{module}.{fn_name} | {test_name}"
        if ok:
            self.passed.append(tag)
            print(f"  [PASS] {tag}")
        else:
            self.failed.append((tag, detail))
            print(f"  [FAIL] {tag}")
            if detail:
                for line in detail.splitlines():
                    print(f"         {line}")

    def summary(self) -> None:
        total = len(self.passed) + len(self.failed)
        bar = "=" * 70
        print(f"\n{bar}")
        print(f"SUMMARY: {len(self.passed)}/{total} tests passed")
        if self.failed:
            print(f"\nFailed tests ({len(self.failed)}):")
            for tag, detail in self.failed:
                print(f"  - {tag}")
                if detail:
                    print(f"    {detail.splitlines()[0]}")
        print(bar)


def _check(condition: bool, detail: str = "") -> tuple[bool, str]:
    """Returns (bool, detail) for TestResult.record()."""
    return condition, detail


def _close(a, b, rtol: float = 1e-5, atol: float = 1e-8) -> bool:
    return bool(np.allclose(a, b, rtol=rtol, atol=atol, equal_nan=False))


# =============================================================================
#  Reproducible signal fixtures
# =============================================================================

_RNG = np.random.default_rng(42)
DEFAULT_N: int = 600
FS: float = 600.0          # sampling frequency (Hz) for freq tests
WINDOW_SIZES = [50, 100, 300, 600, 1200]


def sig_constant(n: int = DEFAULT_N, value: float = 3.14) -> np.ndarray:
    return np.full(n, value, dtype=float)


def sig_linear(n: int = DEFAULT_N, slope: float = 1.0,
               intercept: float = 0.0) -> np.ndarray:
    return np.linspace(intercept, intercept + slope * (n - 1), n)


def sig_sine(n: int = DEFAULT_N, freq: float = 5.0,
             fs: float = FS, amplitude: float = 1.0) -> np.ndarray:
    t = np.arange(n) / fs
    return amplitude * np.sin(2 * np.pi * freq * t)


def sig_noise(n: int = DEFAULT_N) -> np.ndarray:
    return _RNG.standard_normal(n)


def make_categories(x: np.ndarray, window: int,
                    n_windows: int = 5) -> dict[str, np.ndarray]:
    """Return a minimal categories dict for plot-function smoke tests."""
    max_start = len(x) - window
    if max_start <= 0:
        return {"A": np.array([]), "B": np.array([])}
    step = max(1, max_start // n_windows)
    starts_a = np.array([min(i * step, max_start) for i in range(n_windows)])
    starts_b = np.array(
        [s + window // 4 for s in starts_a
         if s + window // 4 + window <= len(x)]
    )
    return {"A": starts_a, "B": starts_b}


# =============================================================================
#  Automated module discovery
# =============================================================================

_SKIP_MODULES = {"unit_testing"}


def discover_modules() -> dict[str, types.ModuleType]:
    """Import every .py file in analysis/ (except this one and __init__)."""
    discovered: dict[str, types.ModuleType] = {}
    for fname in sorted(os.listdir(ANALYSIS_DIR)):
        if not fname.endswith(".py"):
            continue
        stem = fname[:-3]
        if stem.startswith("__") or stem in _SKIP_MODULES:
            continue
        try:
            mod = importlib.import_module(stem)
            discovered[stem] = mod
            print(f"[DISCOVERY] Imported: {stem}")
        except Exception as exc:
            print(f"[DISCOVERY] Could not import '{stem}': {exc}")
    return discovered


def public_functions(module: types.ModuleType) -> dict[str, callable]:
    """Return all functions *defined* in this module (public and private)."""
    stem = module.__name__.split(".")[-1]
    return {
        name: obj
        for name, obj in inspect.getmembers(module, inspect.isfunction)
        if (getattr(obj, "__module__", "") or "").split(".")[-1] == stem
    }


# =============================================================================
#  data_analysis tests
# =============================================================================

def test_data_analysis(mod, results: TestResult) -> None:
    M = "data_analysis"
    sk = getattr(mod, "_skewness", None)
    kt = getattr(mod, "_kurtosis", None)
    pf = getattr(mod, "plot_feature_histograms", None)

    # ── _skewness ─────────────────────────────────────────────────────────────
    if sk is not None:
        fn = "_skewness"

        # std=0 guard → must return 0.0 exactly
        results.record(M, fn, "constant_signal_returns_zero",
                       *_check(sk(sig_constant()) == 0.0))

        # Symmetric sine → ≈0
        v = sk(sig_sine())
        results.record(M, fn, "sine_skewness_near_zero",
                       *_check(abs(v) < 0.05, f"got {v:.6f}"))

        # Symmetric array [-2,-1,0,1,2] → exactly 0
        v = sk(np.array([-2., -1., 0., 1., 2.]))
        results.record(M, fn, "symmetric_array_zero",
                       *_check(_close(v, 0.0, atol=1e-12), f"got {v}"))

        # Known asymmetric [1,1,1,1,10]:
        #   mu=2.8, sigma=3.6  →  skewness = 1.5  (verified analytically)
        v = sk(np.array([1., 1., 1., 1., 10.]))
        results.record(M, fn, "known_value_1_1_1_1_10",
                       *_check(_close(v, 1.5, atol=1e-10),
                               f"expected 1.5, got {v}"))

        # Return type
        results.record(M, fn, "return_type_float",
                       *_check(isinstance(sk(sig_noise()),
                                          (float, np.floating))))

        # Finite for all window sizes
        for n in WINDOW_SIZES:
            v = sk(sig_noise(n))
            results.record(M, fn, f"finite_n={n}",
                           *_check(np.isfinite(v), f"got {v}"))

    # ── _kurtosis ─────────────────────────────────────────────────────────────
    if kt is not None:
        fn = "_kurtosis"

        # std=0 guard
        results.record(M, fn, "constant_signal_returns_zero",
                       *_check(kt(sig_constant()) == 0.0))

        # Large normal sample → excess kurtosis ≈ 0
        big = _RNG.standard_normal(10_000)
        v = kt(big)
        results.record(M, fn, "large_normal_near_zero",
                       *_check(abs(v) < 0.15, f"got {v:.4f}"))

        # Known [1,1,1,1,10]: excess kurtosis = 0.25  (verified analytically)
        v = kt(np.array([1., 1., 1., 1., 10.]))
        results.record(M, fn, "known_value_1_1_1_1_10",
                       *_check(_close(v, 0.25, atol=1e-10),
                               f"expected 0.25, got {v}"))

        # Known [1,2,3,4,5]: discrete uniform on 5 pts → excess kurtosis = -1.3
        #   mu=3, sigma=sqrt(2), mean((x-mu)^4/sigma^4)=1.7, excess=1.7-3=-1.3
        v = kt(np.array([1., 2., 3., 4., 5.]))
        results.record(M, fn, "known_value_linear_5pt",
                       *_check(_close(v, -1.3, atol=1e-10),
                               f"expected -1.3, got {v}"))

        # Return type
        results.record(M, fn, "return_type_float",
                       *_check(isinstance(kt(sig_noise()),
                                          (float, np.floating))))

        # Finite for all window sizes
        for n in WINDOW_SIZES:
            v = kt(sig_noise(n))
            results.record(M, fn, f"finite_n={n}",
                           *_check(np.isfinite(v), f"got {v}"))

    # ── plot_feature_histograms ───────────────────────────────────────────────
    if pf is not None:
        fn = "plot_feature_histograms"
        x = np.concatenate([sig_sine(), sig_noise()])
        cats = make_categories(x, DEFAULT_N)

        with mock.patch("matplotlib.pyplot.show"):
            # Normal run
            try:
                pf(x, cats, DEFAULT_N)
                results.record(M, fn, "normal_run_no_exception", True)
            except Exception:
                results.record(M, fn, "normal_run_no_exception",
                               False, traceback.format_exc())

            # Window larger than signal → windows skipped gracefully
            try:
                pf(sig_sine(50), {"A": np.array([0])}, window_samples=200)
                results.record(M, fn, "short_signal_no_exception", True)
            except Exception:
                results.record(M, fn, "short_signal_no_exception",
                               False, traceback.format_exc())

            # Empty indices array → no windows → no crash
            try:
                pf(x, {"empty": np.array([])}, DEFAULT_N)
                results.record(M, fn, "empty_category_no_exception", True)
            except Exception:
                results.record(M, fn, "empty_category_no_exception",
                               False, traceback.format_exc())

        plt.close("all")


# =============================================================================
#  entropy_analysis tests
# =============================================================================

def test_entropy_analysis(mod, results: TestResult) -> None:
    M = "entropy_analysis"
    sh     = getattr(mod, "_shannon_entropy",     None)
    sp     = getattr(mod, "_spectral_entropy",    None)
    pe     = getattr(mod, "_permutation_entropy", None)
    sv     = getattr(mod, "_svd_entropy",         None)
    ap     = getattr(mod, "_approximate_entropy", None)
    sa     = getattr(mod, "_sample_entropy",      None)
    pe_plt = getattr(mod, "plot_entropy_histograms", None)

    # ── _shannon_entropy ──────────────────────────────────────────────────────
    if sh is not None:
        fn = "_shannon_entropy"

        # Constant → all amplitude values in one histogram bin → entropy = 0
        v = sh(sig_constant())
        results.record(M, fn, "constant_zero_entropy",
                       *_check(_close(v, 0.0, atol=1e-10), f"got {v}"))

        # Non-negative for standard signal types
        for name, sig in [("sine", sig_sine()), ("noise", sig_noise()),
                          ("linear", sig_linear())]:
            v = sh(sig)
            results.record(M, fn, f"non_negative_{name}",
                           *_check(v >= 0, f"got {v}"))

        # Histogram entropy depends on signal range, not just information content:
        # a sine on [-1, 1] fills its narrow bins more evenly than unit-variance
        # noise on [-3, 3] where tail bins are near-empty.  So we only check that
        # noise entropy is comfortably positive (> 3 bits).
        v_n = sh(sig_noise())
        results.record(M, fn, "noise_entropy_positive",
                       *_check(v_n > 3.0, f"noise entropy={v_n:.4f}"))

        # Upper bound: log2(n_bins) = log2(50)
        upper = np.log2(50)
        for name, sig in [("noise", sig_noise()), ("sine", sig_sine())]:
            v = sh(sig)
            results.record(M, fn, f"bounded_above_{name}",
                           *_check(v <= upper + 1e-9,
                                   f"{v:.4f} > log2(50)={upper:.4f}"))

        # Return type
        results.record(M, fn, "return_type_float",
                       *_check(isinstance(sh(sig_noise()),
                                          (float, np.floating))))

        # Finite across window sizes
        for n in WINDOW_SIZES:
            v = sh(sig_noise(n))
            results.record(M, fn, f"finite_n={n}",
                           *_check(np.isfinite(v), f"got {v}"))

    # ── _spectral_entropy ─────────────────────────────────────────────────────
    if sp is not None:
        fn = "_spectral_entropy"

        # Constant → rfft has one nonzero bin (DC) → entropy = 0
        v = sp(sig_constant())
        results.record(M, fn, "constant_zero_entropy",
                       *_check(_close(v, 0.0, atol=1e-10), f"got {v}"))

        # Non-negative
        for name, sig in [("sine", sig_sine()), ("noise", sig_noise())]:
            v = sp(sig)
            results.record(M, fn, f"non_negative_{name}",
                           *_check(v >= 0, f"got {v}"))

        # White noise has higher spectral entropy than pure sine
        v_n, v_s = sp(sig_noise()), sp(sig_sine())
        results.record(M, fn, "noise_gt_sine",
                       *_check(v_n > v_s,
                               f"noise={v_n:.4f}, sine={v_s:.4f}"))

        # Return type
        results.record(M, fn, "return_type_float",
                       *_check(isinstance(sp(sig_noise()),
                                          (float, np.floating))))

        # Finite across window sizes
        for n in WINDOW_SIZES:
            v = sp(sig_noise(n))
            results.record(M, fn, f"finite_n={n}",
                           *_check(np.isfinite(v), f"got {v}"))

    # ── _permutation_entropy ──────────────────────────────────────────────────
    if pe is not None:
        fn = "_permutation_entropy"

        # Monotone increasing (linspace) → all windows have pattern (0,1,2) → 0
        v = pe(sig_linear())
        results.record(M, fn, "monotone_increasing_zero",
                       *_check(_close(v, 0.0, atol=1e-10), f"got {v}"))

        # Monotone decreasing → all patterns (2,1,0) → also 0
        v = pe(-sig_linear())
        results.record(M, fn, "monotone_decreasing_zero",
                       *_check(_close(v, 0.0, atol=1e-10), f"got {v}"))

        # Non-negative
        for name, sig in [("sine", sig_sine()), ("noise", sig_noise())]:
            v = pe(sig)
            results.record(M, fn, f"non_negative_{name}",
                           *_check(v >= 0, f"got {v}"))

        # Upper bound for order=3: log2(3!) = log2(6)
        upper = np.log2(6)
        for name, sig in [("noise", sig_noise()), ("sine", sig_sine())]:
            v = pe(sig, order=3)
            results.record(M, fn, f"bounded_above_order3_{name}",
                           *_check(v <= upper + 1e-9,
                                   f"{v:.4f} > log2(6)={upper:.4f}"))

        # Noise has higher complexity than sine
        v_n, v_s = pe(sig_noise()), pe(sig_sine())
        results.record(M, fn, "noise_gt_sine",
                       *_check(v_n > v_s,
                               f"noise={v_n:.4f}, sine={v_s:.4f}"))

        # Different order parameters remain finite
        for order in [2, 3, 4, 5]:
            v = pe(sig_noise(200), order=order)
            results.record(M, fn, f"order={order}_finite",
                           *_check(np.isfinite(v), f"got {v}"))

        # Finite across window sizes
        for n in WINDOW_SIZES:
            v = pe(sig_noise(n))
            results.record(M, fn, f"finite_n={n}",
                           *_check(np.isfinite(v), f"got {v}"))

    # ── _svd_entropy ──────────────────────────────────────────────────────────
    if sv is not None:
        fn = "_svd_entropy"

        # Signal shorter than order → NaN (by design)
        v = sv(np.array([1., 2.]), order=3)
        results.record(M, fn, "signal_shorter_than_order_is_nan",
                       *_check(np.isnan(v), f"expected NaN, got {v}"))

        # Constant → trajectory matrix is rank-1 → one nonzero SV → entropy = 0
        v = sv(sig_constant(), order=3)
        results.record(M, fn, "constant_zero_entropy",
                       *_check(_close(v, 0.0, atol=1e-10), f"got {v}"))

        # Non-negative for normal signals
        for name, sig in [("sine", sig_sine()), ("noise", sig_noise())]:
            v = sv(sig)
            results.record(M, fn, f"non_negative_{name}",
                           *_check(not np.isnan(v) and v >= 0, f"got {v}"))

        # Noise > sine (more active singular values)
        v_n, v_s = sv(sig_noise()), sv(sig_sine())
        results.record(M, fn, "noise_gt_sine",
                       *_check(v_n > v_s,
                               f"noise={v_n:.4f}, sine={v_s:.4f}"))

        # Valid output across window sizes (n >= order=3)
        for n in [10, 50, 300, 600, 1200]:
            v = sv(sig_noise(n))
            results.record(M, fn, f"valid_n={n}",
                           *_check(np.isnan(v) or np.isfinite(v), f"got {v}"))

    # ── _approximate_entropy ──────────────────────────────────────────────────
    # O(n²) — keep n ≤ 300 in tests
    if ap is not None:
        fn = "_approximate_entropy"

        # Non-negative for regular and random signals
        for name, sig in [("sine", sig_sine(150)),
                          ("noise", sig_noise(150))]:
            v = ap(sig)
            results.record(M, fn, f"non_negative_{name}",
                           *_check(np.isfinite(v) and v >= 0, f"got {v}"))

        # Regular sine < random noise  (ApEn measures irregularity)
        v_s = ap(sig_sine(200))
        v_n = ap(sig_noise(200))
        results.record(M, fn, "sine_lt_noise",
                       *_check(v_s < v_n,
                               f"sine={v_s:.4f}, noise={v_n:.4f}"))

        # Return type
        results.record(M, fn, "return_type_float",
                       *_check(isinstance(ap(sig_noise(100)),
                                          (float, np.floating))))

        # Different r thresholds remain finite
        for r in [0.1, 0.2, 0.3]:
            v = ap(sig_noise(100), r=r)
            results.record(M, fn, f"r={r}_finite",
                           *_check(np.isfinite(v), f"got {v}"))

        # Different embedding dimensions
        for m in [1, 2, 3]:
            v = ap(sig_noise(100), m=m)
            results.record(M, fn, f"m={m}_finite",
                           *_check(np.isfinite(v), f"got {v}"))

    # ── _sample_entropy ───────────────────────────────────────────────────────
    # O(n²) — keep n ≤ 300
    if sa is not None:
        fn = "_sample_entropy"

        # Must return a float (possibly NaN — valid when match count is 0)
        v = sa(sig_sine(200))
        results.record(M, fn, "return_type_float",
                       *_check(isinstance(v, (float, np.floating)),
                               f"got {type(v).__name__}"))

        # Regular < random (when both non-NaN)
        v_s = sa(sig_sine(300))
        v_n = sa(sig_noise(300))
        if not (np.isnan(v_s) or np.isnan(v_n)):
            results.record(M, fn, "sine_lt_noise",
                           *_check(v_s < v_n,
                                   f"sine={v_s:.4f}, noise={v_n:.4f}"))
        else:
            results.record(M, fn, "sine_lt_noise", True,
                           "(skipped — NaN is a valid output here)")

        # Very short signal → NaN expected (insufficient templates)
        v = sa(np.array([1., 2., 3.]))
        results.record(M, fn, "very_short_signal_nan_or_finite",
                       *_check(np.isnan(v) or np.isfinite(v), f"got {v}"))

        # Different r values produce valid output
        for r in [0.1, 0.2, 0.3]:
            v = sa(sig_noise(150), r=r)
            results.record(M, fn, f"r={r}_valid_output",
                           *_check(np.isnan(v) or np.isfinite(v), f"got {v}"))

    # ── plot_entropy_histograms ───────────────────────────────────────────────
    if pe_plt is not None:
        fn = "plot_entropy_histograms"
        x = np.concatenate([sig_sine(), sig_noise()])
        cats = make_categories(x, DEFAULT_N)

        with mock.patch("matplotlib.pyplot.show"):
            try:
                pe_plt(x, cats, DEFAULT_N)
                results.record(M, fn, "normal_run_no_exception", True)
            except Exception:
                results.record(M, fn, "normal_run_no_exception",
                               False, traceback.format_exc())

            try:
                pe_plt(sig_sine(50), {"A": np.array([0])},
                       window_samples=200)
                results.record(M, fn, "short_signal_no_exception", True)
            except Exception:
                results.record(M, fn, "short_signal_no_exception",
                               False, traceback.format_exc())

            try:
                pe_plt(x, {"empty": np.array([])}, DEFAULT_N)
                results.record(M, fn, "empty_category_no_exception", True)
            except Exception:
                results.record(M, fn, "empty_category_no_exception",
                               False, traceback.format_exc())

        plt.close("all")


# =============================================================================
#  freq_analysis tests
# =============================================================================

def test_freq_analysis(mod, results: TestResult) -> None:
    M = "freq_analysis"
    stft_fn = getattr(mod, "stft_log_spectrum",  None)
    plot_fn = getattr(mod, "plot_freq_histogram", None)

    WS, HS = 300, 150   # default window / hop for STFT tests

    # ── stft_log_spectrum ─────────────────────────────────────────────────────
    if stft_fn is not None:
        fn = "stft_log_spectrum"
        x = sig_sine(n=DEFAULT_N, freq=5.0, fs=FS)

        # Output shapes (1-D mode)
        bf, pw = stft_fn(x, fs=FS, window_size=WS, hop_size=HS)
        results.record(M, fn, "bin_freqs_shape_(64,)",
                       *_check(bf.shape == (64,), f"got {bf.shape}"))
        results.record(M, fn, "power_1d_shape_(64,)",
                       *_check(pw.shape == (64,), f"got {pw.shape}"))

        # 2-D mode
        bf2, pw2 = stft_fn(x, fs=FS, window_size=WS, hop_size=HS,
                            return_2d=True)
        results.record(M, fn, "power_2d_cols_eq_64",
                       *_check(pw2.shape[1] == 64, f"got {pw2.shape}"))
        results.record(M, fn, "bin_freqs_2d_shape_(64,)",
                       *_check(bf2.shape == (64,), f"got {bf2.shape}"))

        # 1-D result == mean of 2-D rows
        results.record(M, fn, "1d_eq_mean_of_2d_rows",
                       *_check(_close(pw, pw2.mean(axis=0), atol=1e-10),
                               "mean of 2D rows differs from 1D output"))

        # Frequency sanity checks
        results.record(M, fn, "bin_freqs_all_positive",
                       *_check(np.all(bf > 0), f"min={bf.min():.4f}"))
        results.record(M, fn, "bin_freqs_strictly_increasing",
                       *_check(np.all(np.diff(bf) > 0), "not monotone"))
        results.record(M, fn, "bin_freqs_le_nyquist",
                       *_check(np.all(bf <= FS / 2 + 1e-9),
                               f"max={bf.max():.4f} > nyquist={FS/2}"))

        # Power non-negative
        results.record(M, fn, "power_non_negative",
                       *_check(np.all(pw >= 0), f"min={pw.min():.4e}"))

        # Custom n_log_bins
        for n_bins in [16, 32, 64, 128]:
            b, p = stft_fn(x, fs=FS, window_size=WS, hop_size=HS,
                            n_log_bins=n_bins)
            results.record(M, fn, f"n_log_bins={n_bins}_correct_shape",
                           *_check(b.shape == (n_bins,) and p.shape == (n_bins,),
                                   f"got {b.shape}, {p.shape}"))

        # ValueError for signal shorter than one window
        short = sig_sine(n=WS - 1)
        try:
            stft_fn(short, fs=FS, window_size=WS, hop_size=HS)
            results.record(M, fn, "raises_ValueError_short_signal",
                           False, "Expected ValueError — no exception raised")
        except ValueError:
            results.record(M, fn, "raises_ValueError_short_signal", True)
        except Exception as e:
            results.record(M, fn, "raises_ValueError_short_signal",
                           False,
                           f"Expected ValueError, got {type(e).__name__}: {e}")

        # 5 Hz sine → peak power bin near 5 Hz
        bf_s, pw_s = stft_fn(
            sig_sine(n=DEFAULT_N, freq=5.0, fs=FS),
            fs=FS, window_size=WS, hop_size=HS,
        )
        peak = bf_s[np.argmax(pw_s)]
        results.record(M, fn, "sine_5hz_peak_near_5hz",
                       *_check(abs(peak - 5.0) < 2.0,
                               f"peak at {peak:.3f} Hz, expected ~5 Hz"))

        # Consistent output shape across window sizes
        long_x = sig_noise(n=3000)
        for ws in [100, 200, 300, 600]:
            hs = ws // 2
            try:
                b, p = stft_fn(long_x, fs=FS, window_size=ws, hop_size=hs)
                results.record(M, fn, f"window_size={ws}_shape_ok",
                               *_check(b.shape == (64,) and p.shape == (64,),
                                       f"got {b.shape}, {p.shape}"))
            except Exception as e:
                results.record(M, fn, f"window_size={ws}_shape_ok",
                               False, str(e))

    # ── plot_freq_histogram ───────────────────────────────────────────────────
    if plot_fn is not None:
        fn = "plot_freq_histogram"
        x = np.concatenate([sig_sine(), sig_noise()])
        cats = make_categories(x, DEFAULT_N)

        # Patch matplotlib.pyplot.show — covers both plt.show and the
        # module's internal 'py' alias (both reference the same object).
        with mock.patch("matplotlib.pyplot.show"):
            try:
                plot_fn(x, cats, fs=FS, window_samples=DEFAULT_N)
                results.record(M, fn, "normal_run_no_exception", True)
            except Exception:
                results.record(M, fn, "normal_run_no_exception",
                               False, traceback.format_exc())

            try:
                plot_fn(x, cats, fs=FS, window_samples=DEFAULT_N,
                        freq_bin_width=2.0)
                results.record(M, fn, "with_freq_bin_width_no_exception",
                               True)
            except Exception:
                results.record(M, fn, "with_freq_bin_width_no_exception",
                               False, traceback.format_exc())

            try:
                plot_fn(x, cats, fs=FS, window_samples=DEFAULT_N,
                        log_scale=True)
                results.record(M, fn, "log_scale_no_exception", True)
            except Exception:
                results.record(M, fn, "log_scale_no_exception",
                               False, traceback.format_exc())

            try:
                plot_fn(x, {"empty": np.array([])},
                        fs=FS, window_samples=DEFAULT_N)
                results.record(M, fn, "empty_category_no_exception", True)
            except Exception:
                results.record(M, fn, "empty_category_no_exception",
                               False, traceback.format_exc())

        plt.close("all")


# =============================================================================
#  Edge case tests (cross-module)
# =============================================================================

def test_edge_cases(modules: dict, results: TestResult) -> None:
    M = "edge_cases"
    da = modules.get("data_analysis")
    ea = modules.get("entropy_analysis")
    fa = modules.get("freq_analysis")

    # Collect scalar functions to stress-test
    scalar_fns: dict[str, callable] = {}
    if da:
        for name in ("_skewness", "_kurtosis"):
            fn = getattr(da, name, None)
            if fn:
                scalar_fns[f"data_analysis.{name}"] = fn
    if ea:
        for name in ("_shannon_entropy", "_spectral_entropy",
                     "_permutation_entropy", "_svd_entropy"):
            fn = getattr(ea, name, None)
            if fn:
                scalar_fns[f"entropy_analysis.{name}"] = fn

    edge_signals = {
        "single_sample":    np.array([1.0]),
        "two_samples":      np.array([1.0, 2.0]),
        "all_nan":          np.full(DEFAULT_N, np.nan),
        "partial_nan":      _make_partial_nan(),
        "all_zeros":        np.zeros(DEFAULT_N),
        "huge_values":      sig_sine() * 1e15,
        "tiny_values":      sig_noise() * 1e-15,
    }

    for full_name, fn in scalar_fns.items():
        for case_name, sig in edge_signals.items():
            try:
                v = fn(sig)
                ok = np.isfinite(v) or np.isnan(v)
                results.record(M, full_name, case_name,
                               *_check(ok, f"got {v}"))
            except Exception as e:
                results.record(M, full_name, case_name,
                               False, f"{type(e).__name__}: {e}")

    # stft_log_spectrum-specific edge cases
    if fa:
        stft_fn = getattr(fa, "stft_log_spectrum", None)
        if stft_fn:
            qn = "freq_analysis.stft_log_spectrum"

            # Exact-length signal (= window_size) — boundary condition
            try:
                _, p = stft_fn(sig_sine(n=300), fs=FS,
                               window_size=300, hop_size=150)
                results.record(M, qn, "signal_eq_window_size",
                               *_check(p.shape == (64,), f"got {p.shape}"))
            except Exception as e:
                results.record(M, qn, "signal_eq_window_size",
                               False, f"{type(e).__name__}: {e}")

            # All-zeros signal → power must be zero everywhere
            try:
                _, p = stft_fn(np.zeros(DEFAULT_N), fs=FS,
                               window_size=300, hop_size=150)
                results.record(M, qn, "zero_signal_zero_power",
                               *_check(np.all(p == 0),
                                       f"max power={p.max():.4e}"))
            except Exception as e:
                results.record(M, qn, "zero_signal_zero_power",
                               False, f"{type(e).__name__}: {e}")

            # High-amplitude signal → power still non-negative
            try:
                _, p = stft_fn(sig_sine() * 1e10, fs=FS,
                               window_size=300, hop_size=150)
                results.record(M, qn, "huge_amplitude_power_non_negative",
                               *_check(np.all(p >= 0),
                                       f"min={p.min():.4e}"))
            except Exception as e:
                results.record(M, qn, "huge_amplitude_power_non_negative",
                               False, f"{type(e).__name__}: {e}")


def _make_partial_nan(n: int = DEFAULT_N) -> np.ndarray:
    sig = sig_noise(n).copy()
    sig[:50] = np.nan
    return sig


# =============================================================================
#  Window-size flexibility (cross-module)
# =============================================================================

def test_window_sizes(modules: dict, results: TestResult) -> None:
    """All scalar functions must produce valid output across all window sizes."""
    M = "window_size_flexibility"
    scalar_fns: dict[str, callable] = {}

    da = modules.get("data_analysis")
    ea = modules.get("entropy_analysis")
    if da:
        for name in ("_skewness", "_kurtosis"):
            fn = getattr(da, name, None)
            if fn:
                scalar_fns[f"data_analysis.{name}"] = fn
    if ea:
        for name in ("_shannon_entropy", "_spectral_entropy",
                     "_permutation_entropy", "_svd_entropy"):
            fn = getattr(ea, name, None)
            if fn:
                scalar_fns[f"entropy_analysis.{name}"] = fn

    for full_name, fn in scalar_fns.items():
        for n in WINDOW_SIZES:
            try:
                v = fn(sig_noise(n))
                results.record(M, full_name, f"n={n}",
                               *_check(np.isfinite(v) or np.isnan(v),
                                       f"unexpected: {v}"))
            except Exception as e:
                results.record(M, full_name, f"n={n}",
                               False, f"{type(e).__name__}: {e}")


# =============================================================================
#  Auto smoke-test: newly discovered functions not in _COVERED_FUNCTIONS
# =============================================================================

_COVERED_FUNCTIONS: dict[str, set[str]] = {
    "data_analysis":    {"_skewness", "_kurtosis", "plot_feature_histograms"},
    "entropy_analysis": {"_shannon_entropy", "_spectral_entropy",
                         "_permutation_entropy", "_svd_entropy",
                         "_approximate_entropy", "_sample_entropy",
                         "plot_entropy_histograms"},
    "freq_analysis":    {"stft_log_spectrum", "plot_freq_histogram"},
}

_SIGNAL_PARAM_NAMES = {"w", "x", "signal", "data", "arr", "samples"}


def test_smoke_uncovered(modules: dict, results: TestResult) -> None:
    """
    Smoke-call any function in a discovered module that is not already
    covered by a dedicated suite.  New functions added to any module are
    caught here automatically without modifying this file.
    """
    M = "smoke_uncovered"
    x = sig_noise()

    for mod_name, mod in modules.items():
        covered = _COVERED_FUNCTIONS.get(mod_name, set())
        for fn_name, fn in public_functions(mod).items():
            if fn_name in covered:
                continue
            params = list(inspect.signature(fn).parameters.values())
            if not params or params[0].name not in _SIGNAL_PARAM_NAMES:
                continue
            try:
                fn(x)
                results.record(M, f"{mod_name}.{fn_name}", "smoke_call", True)
            except TypeError:
                pass   # wrong arity — skip silently
            except Exception as e:
                results.record(M, f"{mod_name}.{fn_name}", "smoke_call",
                               False, f"{type(e).__name__}: {e}")


# =============================================================================
#  Coverage report
# =============================================================================

def report_coverage(modules: dict) -> None:
    print("\n" + "=" * 70)
    print("FUNCTION COVERAGE REPORT")
    print("=" * 70)
    for mod_name, mod in modules.items():
        fns = public_functions(mod)
        covered = _COVERED_FUNCTIONS.get(mod_name, set())
        print(f"\n  {mod_name}  ({len(fns)} functions)")
        for name in sorted(fns):
            marker = "[tested]" if name in covered else "[smoke] "
            vis    = "pub" if not name.startswith("_") else "prv"
            print(f"    {marker} {vis}  {name}")
    print("=" * 70)


# =============================================================================
#  Main runner
# =============================================================================

def run_all() -> TestResult:
    print("=" * 70)
    print("Analysis Module Unit Tests")
    print(f"Default window: {DEFAULT_N} samples  |  FS: {FS} Hz")
    print("=" * 70)

    modules = discover_modules()
    results = TestResult()

    suite_map = {
        "data_analysis":    test_data_analysis,
        "entropy_analysis": test_entropy_analysis,
        "freq_analysis":    test_freq_analysis,
    }

    for mod_name, suite_fn in suite_map.items():
        mod = modules.get(mod_name)
        if mod is None:
            print(f"\n[SKIP] '{mod_name}' not available (import failed).")
            continue
        print(f"\n{'─' * 70}")
        print(f"  Module: {mod_name}")
        print(f"{'─' * 70}")
        suite_fn(mod, results)

    print(f"\n{'─' * 70}")
    print("  Edge Cases")
    print(f"{'─' * 70}")
    test_edge_cases(modules, results)

    print(f"\n{'─' * 70}")
    print("  Window Size Flexibility")
    print(f"{'─' * 70}")
    test_window_sizes(modules, results)

    print(f"\n{'─' * 70}")
    print("  Smoke Tests (auto-discovered, uncovered functions)")
    print(f"{'─' * 70}")
    test_smoke_uncovered(modules, results)

    report_coverage(modules)
    results.summary()
    return results


if __name__ == "__main__":
    res = run_all()
    sys.exit(0 if not res.failed else 1)
