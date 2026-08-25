"""
test_t06_adapter_remap.py
===========================
Ticket 06 — adapter remap batch A: signal and interval blocks.

The seven adapters whose types are a straight rename declare their new
types — `Signal -> Signal` for the four preprocessing adapters, `Signal ->
SpanSet` for the three detection adapters — and each `run` returns an
`AdapterResult` populating both the legacy field and the new typed `value`.
No adapter in this batch declares a side-input or an estimator (other
tickets' work).

Run from the project root:
    python tests/test_t06_adapter_remap.py
"""

import inspect
import os
import sys

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Adapters.base import AdapterResult
from Adapters.registry import discover_adapters, get_adapter
from Working.types import Signal, SpanSet

discover_adapters()

PREPROCESSING_ADAPTERS = (
    "preprocessing.bandpass",
    "preprocessing.detrend",
    "preprocessing.highpass",
    "preprocessing.lowpass",
)

DETECTION_ADAPTERS = (
    "detection.rupture",
    "detection.spike_v1",
    "detection.dehshibi_spikes",
)


def _signal(fs=100.0, n=200):
    """A step signal: clean half-zero/half-one, cheap and deterministic."""
    x = np.concatenate([np.zeros(n // 2), np.ones(n // 2)])
    t = np.arange(n) / fs
    return x, t, fs


def test_preprocessing_adapters_declare_signal_to_signal():
    for name in PREPROCESSING_ADAPTERS:
        spec = get_adapter(name)
        assert spec.input_kind == "signal", name
        assert spec.output_kind == "signal", name
        assert spec.side_inputs == [], name
        assert spec.estimate is None, name


def test_detection_adapters_declare_signal_to_spanset():
    for name in DETECTION_ADAPTERS:
        spec = get_adapter(name)
        assert spec.input_kind == "signal", name
        assert spec.output_kind == "spanset", name
        assert spec.side_inputs == [], name
        assert spec.estimate is None, name


def test_preprocessing_run_populates_the_typed_value():
    """Ticket 10 removed the `x`/`t` carrier fields this test used to assert
    alongside `value`. A preprocessing block preserves the sample count —
    `Working.execution` refuses one that does not, because the chain's time
    axis is the span's and a `Signal` carries no absolute offset to rebuild
    a different one from."""
    x, t, fs = _signal()
    for name in PREPROCESSING_ADAPTERS:
        spec = get_adapter(name)
        params = spec.validate_params({})
        result = spec.run(x, t, fs, **params)
        assert isinstance(result, AdapterResult), name
        assert isinstance(result.value, Signal), name
        assert result.value.fs == fs, name
        assert len(result.value.x) == len(x), name


def test_detection_run_populates_the_typed_value():
    """Ticket 10 removed the `intervals` carrier this test used to assert
    alongside `value`; the SpanSet was always the real payload."""
    x, t, fs = _signal()
    for name in DETECTION_ADAPTERS:
        spec = get_adapter(name)
        params = spec.validate_params({})
        result = spec.run(x, t, fs, **params)
        assert isinstance(result, AdapterResult), name
        assert isinstance(result.value, SpanSet), name
        assert len(result.value.starts) == len(result.value.ends), name


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
