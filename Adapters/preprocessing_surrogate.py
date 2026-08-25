"""
preprocessing_surrogate.py
===========================
Surrogate generation block (ticket 43). A signal-to-signal adapter that
produces a null — a surrogate version of the input signal — reproducibly
from its recipe. See PRD "Surrogates": phase randomisation and block
shuffling offered as a choice parameter, with an explicit RNG seed among
the parameters so the recipe hash reproduces the surrogate exactly.

Phase randomisation (a Fourier surrogate) preserves the original's power
spectrum by construction: each positive-frequency bin is multiplied by a
unit-magnitude complex exponential, so magnitudes are unchanged and the
inverse FFT is a real signal with the same spectrum. Block shuffling
destroys temporal structure while keeping local amplitude statistics.
"""

import numpy as np

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.types import Signal


def _phase_randomise(x, rng):
    """Fourier surrogate: randomise the phases of the original spectrum,
    preserving its magnitudes (and therefore its power spectrum).

    `rfft`/`irfft` keep the signal real by construction; the DC bin and —
    for even-length signals — the Nyquist bin must stay real for the inverse
    transform to be real, so their phases are pinned to zero.
    """
    n = len(x)
    X = np.fft.rfft(x)
    angles = rng.uniform(0.0, 2.0 * np.pi, size=X.shape)
    angles[0] = 0.0            # DC must remain real
    if n % 2 == 0:
        angles[-1] = 0.0       # Nyquist must remain real
    X_rand = X * np.exp(1j * angles)
    return np.fft.irfft(X_rand, n=n)


def _block_shuffle(x, rng, block_s, fs):
    """Shuffle the order of contiguous blocks of length `block_s` seconds.

    The trailing partial block (if any) is left in place so the output has
    exactly the same length as the input. A signal too short to contain two
    full blocks is returned unchanged.
    """
    n = len(x)
    block_len = max(1, int(round(block_s * fs)))
    n_blocks = n // block_len
    if n_blocks <= 1:
        return np.array(x, dtype=float, copy=True)
    perm = rng.permutation(n_blocks)
    blocks = x[: n_blocks * block_len].reshape(n_blocks, block_len)
    shuffled = blocks[perm].reshape(-1)
    remainder = x[n_blocks * block_len:]
    return np.concatenate([shuffled, remainder])


def _run(x, t, fs, method="phase_randomize", seed=0, block_s=1.0):
    rng = np.random.RandomState(seed)
    if method == "phase_randomize":
        x_surrogate = _phase_randomise(x, rng)
    elif method == "block_shuffle":
        x_surrogate = _block_shuffle(x, rng, block_s, fs)
    else:
        raise ValueError(
            f"Unknown surrogate method {method!r}; expected one of "
            f"('phase_randomize', 'block_shuffle')"
        )
    return AdapterResult(
        output_kind="signal", x=x_surrogate, t=t,
        value=Signal(x=x_surrogate, fs=fs),
    )


SPEC = register(AdapterSpec(
    name="preprocessing.surrogate",
    display_name="Surrogate generation",
    stage="preprocessing",
    params=[
        ParamSpec(
            "method", str, "phase_randomize",
            "Surrogate method: phase randomisation preserves the power "
            "spectrum; block shuffling preserves local amplitude statistics",
            choices=["phase_randomize", "block_shuffle"],
        ),
        ParamSpec(
            "seed", int, 0,
            "Random seed — the recipe hash reproduces the surrogate exactly",
            min=0,
        ),
        ParamSpec(
            "block_s", float, 1.0,
            "Block length in seconds for block shuffling", min=1e-6,
        ),
    ],
    run=_run,
    input_kind="signal",
    output_kind="signal",
    description=(
        "Produces a surrogate (null) version of the signal for surrogate "
        "testing. Phase randomisation keeps the power spectrum but destroys "
        "temporal phase structure; block shuffling reorders contiguous "
        "blocks. An explicit seed makes the surrogate reproducible from the "
        "recipe hash."
    ),
))
