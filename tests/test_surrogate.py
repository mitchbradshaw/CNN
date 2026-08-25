"""
test_surrogate.py
===================
Ticket 43 — surrogate generation block.

A signal-to-signal adapter that produces a null (surrogate) version of a
signal, reproducibly from its recipe. The PRD ("Surrogates") requires:
phase randomisation and block shuffling offered as a choice parameter, an
explicit RNG seed among the `ParamSpec` parameters so the recipe hash
reproduces the surrogate exactly, and a phase-randomised surrogate that
preserves the original's power spectrum.

These tests assert the external behaviour the reproducibility claim depends
on: the block declares `Signal -> Signal`, offers both surrogate methods as
a choice, exposes a seed parameter, reproduces a bit-identical surrogate for
a fixed seed, and phase randomisation preserves the power spectrum within a
stated tolerance.

Run from the project root:
    python -m pytest tests/test_surrogate.py -q
"""

import os
import sys

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Adapters.registry import discover_adapters, get_adapter

discover_adapters()

SURROGATE_NAME = "preprocessing.surrogate"

# The two surrogate methods the block must offer as a choice.
SURROGATE_METHODS = ("phase_randomize", "block_shuffle")


def _signal(fs=100.0, n=512):
    """A deterministic signal with a non-flat power spectrum: two sinusoids
    plus a little noise, so the power-spectrum-preservation assertion is
    meaningful."""
    t = np.arange(n) / fs
    rng = np.random.RandomState(1)
    x = (np.sin(2 * np.pi * 5.0 * t)
         + 0.5 * np.sin(2 * np.pi * 13.0 * t)
         + 0.2 * rng.randn(n))
    return x, t, fs


def test_surrogate_declares_signal_to_signal():
    spec = get_adapter(SURROGATE_NAME)
    assert spec.input_kind == "signal"
    assert spec.output_kind == "signal"


def test_surrogate_offers_phase_randomise_and_block_shuffle_choice():
    spec = get_adapter(SURROGATE_NAME)
    method_params = [p for p in spec.params if p.name == "method"]
    assert len(method_params) == 1, "expected exactly one 'method' parameter"
    assert set(SURROGATE_METHODS) <= set(method_params[0].choices)


def test_surrogate_exposes_a_seed_param():
    spec = get_adapter(SURROGATE_NAME)
    assert any(p.name == "seed" for p in spec.params)


def test_fixed_seed_reproduces_bit_identical_surrogate():
    spec = get_adapter(SURROGATE_NAME)
    x, t, fs = _signal()
    for method in SURROGATE_METHODS:
        params = spec.validate_params({"method": method, "seed": 42})
        a = spec.run(x, t, fs, **params)
        b = spec.run(x, t, fs, **params)
        assert np.array_equal(a.x, b.x), method
        assert a.t is not None and b.t is not None, method
        assert a.value.fs == fs, method


def test_phase_randomise_preserves_power_spectrum():
    spec = get_adapter(SURROGATE_NAME)
    x, t, fs = _signal()
    params = spec.validate_params({"method": "phase_randomize", "seed": 7})
    result = spec.run(x, t, fs, **params)
    # Phase randomisation multiplies each FFT bin by a unit-magnitude complex
    # exponential, so the magnitude spectrum (and hence power spectrum) is
    # preserved to floating-point precision. 1e-6 relative tolerance is far
    # looser than the actual error, which is ~1e-14.
    mag_original = np.abs(np.fft.rfft(x))
    mag_surrogate = np.abs(np.fft.rfft(result.x))
    assert np.allclose(mag_original, mag_surrogate, rtol=1e-6, atol=1e-8)
