"""
scattering_transform.py
========================
Wavelet scattering transform for mycelium bio-electric time-series windows,
built on kymatio's `Scattering1D` (numpy backend — no torch/GPU required).

What a scattering transform is, physically
--------------------------------------------
A plain wavelet transform (e.g. a continuous wavelet transform / scalogram)
convolves the signal with a bank of band-pass wavelets and keeps the raw
(complex or signed) output.  That output still oscillates at the wavelet's
own frequency and is therefore sensitive to small time shifts in the input —
two recordings that are physiologically identical but misaligned by a
fraction of a second can look very different under a plain wavelet transform.

A scattering transform fixes this by cascading three operations:

    1. Convolve with a wavelet filter bank  (same filters as a CWT)
    2. Take the complex modulus  |.|          (discards fast oscillation,
                                                keeps the slowly-varying
                                                envelope/energy)
    3. Convolve with a low-pass filter and subsample (averages the envelope
                                                over a chosen timescale)

Step (1) on its own is the ordinary wavelet transform. Steps (2)-(3) are what
turn it into a *scattering* transform: they produce coefficients that are
locally stable to small time shifts and smooth deformations of the input,
while still summarising how the signal's energy is distributed across
timescales. Re-applying the same three-step cascade to the modulus output of
step (2) yields second-order coefficients, which additionally capture
amplitude-modulation structure (how energy at one timescale itself varies
over a slower timescale) that first-order coefficients and a plain wavelet
transform cannot see.

In short: where a wavelet transform gives you a raw, shift-sensitive
time-frequency picture, scattering coefficients give you a noise-robust,
shift-stable *summary* of energy across timescales — closer to a set of
engineered features than to a reversible transform. This is the reason to
reach for scattering over a plain CWT/DWT when the goal is comparing or
clustering noisy, imperfectly-aligned bio-electric recordings rather than
reconstructing or visually inspecting the raw time-frequency content.

Parameters, in plain terms
---------------------------
J : number of octaves (scales) covered by the filter bank. The largest
    timescale analysed is proportional to 2**J samples. Bigger J -> the
    transform "sees" slower, longer-timescale structure, but also needs a
    longer input signal to do so without edge distortion (see below).
Q : wavelets per octave. Bigger Q -> finer frequency resolution within each
    octave (more, narrower filters), at the cost of more coefficients and
    compute. Q=1 is typical for scattering; larger Q (e.g. 8) is closer to a
    musical/audio-style constant-Q wavelet bank and gives finer detail in the
    scale axis.
max_order : how many times the modulus+lowpass cascade is applied.
    1 = first-order only (closest to a smoothed, shift-stable CWT magnitude).
    2 (default) = also compute second-order coefficients, which add
    amplitude-modulation information at minimal extra conceptual cost -- this
    is the standard choice and rarely needs changing.
T : the averaging (invariance) scale, in samples. This sets how much the
    envelope from step (2) above is smoothed/pooled in step (3). Larger T ->
    coefficients are stable to larger time shifts but have coarser time
    resolution (fewer output columns). Left as None (default), kymatio uses
    T = 2**J, i.e. full averaging at the same scale as the coarsest wavelet.

Input length: short vs. long recordings
------------------------------------------
Recordings in this project vary from short probe windows to multi-hour
concatenated channels, so `compute_wavelet_scattering` is deliberately
generic about input length -- but the underlying transform is not free to
use on arbitrarily short input:

* Hard minimum: the low-pass filter in step (3) needs at least 2**J samples
  of support. Below that, kymatio produces an output with **zero time
  columns** (or, for very short inputs, raises internally) -- i.e. it can
  silently return an empty/unusable result rather than an error. This
  function checks for that case up front and raises ValueError before
  calling kymatio, so a too-short window fails loudly instead of returning
  garbage.
* Soft minimum: even above the hard floor, kymatio's own filter-bank
  construction emits a "signal support is too small to avoid border effects"
  warning when the input isn't comfortably larger than 2**J (empirically,
  well under ~8x). Below that, coefficients are still returned, but the ones
  computed near the start/end of the recording (and any global, large-scale
  coefficients) will be distorted by the reflection padding kymatio uses to
  handle the boundary. This function forwards that condition as a Python
  UserWarning with the concrete numbers for J and your data, and it is also
  recorded on the result as `border_effects_flagged` so it can be checked
  programmatically.
* Long recordings: there is no hard upper limit -- kymatio pads to the next
  power of two internally and runs in roughly linear time in input length.
  For multi-hour recordings, consider whether you actually want scattering
  coefficients over fixed-length windows (matching the windowing convention
  used elsewhere in this repo, e.g. `matrix_profiling`/`gramian`) rather than
  over an entire concatenated recording -- the output time axis and number of
  coefficients change with input length, so windows of different lengths are
  not directly comparable without extra care.

Workflow
--------
    from Working.Preprocessing.manage_data.load_data import load_raw_data
    from Working.Detection.wavelet.scattering_transform import compute_wavelet_scattering
    from Working.Detection.wavelet.plot_scattering import plot_scattering_scalogram

    x, t = load_raw_data("M2_concat_fs1_CH0.npy", fs=1.0)
    result = compute_wavelet_scattering(x, t, J=8, Q=8)
    plot_scattering_scalogram(result)
"""

from __future__ import annotations

import os
import sys
import warnings
from dataclasses import dataclass

import numpy as np
from kymatio.numpy import Scattering1D

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Return type
# ===========================================================================

@dataclass
class ScatteringResult:
    """
    All outputs from `compute_wavelet_scattering`, structured so the
    coefficients can be interpreted later without re-deriving parameters.

    Attributes
    ----------
    Sx : np.ndarray, shape (n_coeffs, n_frames)
        Scattering coefficient matrix. Row i is one coefficient's time
        series (its energy trajectory over the recording); column j is one
        output time frame. Rows with `order >= 1` are non-negative (they are
        the result of a modulus + low-pass averaging cascade). The `order
        == 0` row(s) are the exception: order 0 is just the local average of
        the *raw* signal (low-pass only, no wavelet or modulus applied), so
        it keeps the sign of the input.
    t_scattering : np.ndarray, shape (n_frames,)
        Timestamp (same units as the input `t`) for each column of `Sx`,
        i.e. the centre time of the averaging window each coefficient
        summarises. Spaced `T / fs` apart.
    order : np.ndarray[int], shape (n_coeffs,)
        Scattering order of each row: 0 = the local time-average of the raw
        signal (no wavelet applied), 1 = first-order coefficients, 2 =
        second-order coefficients.
    xi : np.ndarray[float], shape (n_coeffs,)
        Normalised centre frequency (cycles/sample) of the first wavelet
        applied to produce this row. NaN for order-0 rows. For order-2 rows
        this describes only the first (coarser) filter in the cascade, used
        here as a single scalar to group/order coefficients by band; it does
        not capture the second filter's frequency.
    freq_hz : np.ndarray[float], shape (n_coeffs,)
        `xi` converted to Hz using the sampling rate inferred from `t`.
        NaN for order-0 rows.
    j : np.ndarray[float], shape (n_coeffs,)
        Dyadic scale index (octave) of the first wavelet applied. NaN for
        order-0 rows.
    J, Q, max_order : int
        Scattering parameters used to compute this result (see module
        docstring for what each controls).
    T : int
        Actual averaging window, in samples, that was used (== 2**J when the
        caller left `T=None`).
    fs : float
        Sampling rate, in Hz, inferred from the input `t`.
    n_input : int
        Number of samples in the input signal `x`.
    duration_s : float
        Duration of the input signal, in seconds (`n_input / fs`).
    border_effects_flagged : bool
        True if kymatio's own filter-bank construction warned that the input
        is short relative to J (see module docstring, "Input length").
        Coefficients are still returned in this case, but treat the ones
        near the start/end of the recording with caution.
    """

    Sx: np.ndarray
    t_scattering: np.ndarray
    order: np.ndarray
    xi: np.ndarray
    freq_hz: np.ndarray
    j: np.ndarray
    J: int
    Q: int
    max_order: int
    T: int
    fs: float
    n_input: int
    duration_s: float
    border_effects_flagged: bool


# ===========================================================================
# Public entry point
# ===========================================================================

def compute_wavelet_scattering(
    x: np.ndarray,
    t: np.ndarray,
    J: int = 8,
    Q: int = 8,
    max_order: int = 2,
    T: int | None = None,
) -> ScatteringResult:
    """
    Compute the wavelet scattering transform of a signal.

    See the module docstring for what scattering coefficients represent
    physically and how this differs from a plain wavelet transform.

    Parameters
    ----------
    x : np.ndarray, shape (n,)
        Raw signal (e.g. bio-electric potential), as returned by
        `manage_data.load_data.load_raw_data`.
    t : np.ndarray, shape (n,)
        Timestamps corresponding to `x`, same length, assumed uniformly
        sampled. Used only to infer the sampling rate and to build
        `t_scattering`; any consistent unit (seconds, samples/fs, etc.) is
        fine.
    J : int
        Number of octaves (scales) in the wavelet filter bank. Larger J
        analyses slower/longer-timescale structure but requires a longer
        input (see module docstring, "Input length"). Default 8.
    Q : int
        Wavelets per octave. Larger Q gives finer frequency resolution at
        the cost of more coefficients and compute. Default 8.
    max_order : int
        Highest scattering order to compute (1 or 2). Default 2 (standard
        choice; adds amplitude-modulation information over order 1).
    T : int, optional
        Averaging (invariance) scale in samples. None (default) uses
        kymatio's default of 2**J -- full averaging at the coarsest
        wavelet's scale.

    Returns
    -------
    ScatteringResult

    Raises
    ------
    ValueError
        If `x` and `t` have mismatched or zero length, or if `x` is too
        short for the requested `J` to produce any output time frames
        (fewer than 2**J samples). This is a hard floor below which kymatio
        would otherwise silently return a zero-length result.

    Warns
    -----
    UserWarning
        If `x` is long enough to produce output but still short relative to
        J, such that kymatio's internal filter-bank check flags border
        (edge/padding) effects. The result is still returned; check
        `result.border_effects_flagged`.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    t = np.asarray(t, dtype=np.float64).ravel()

    if x.shape != t.shape:
        raise ValueError(f"x and t must have the same shape, got {x.shape} and {t.shape}.")
    if x.size < 2:
        raise ValueError("x must have at least 2 samples to infer a sampling rate.")

    n = x.size
    fs = 1.0 / np.median(np.diff(t))

    min_len = 2 ** J
    if n < min_len:
        raise ValueError(
            f"Input has {n} samples, but J={J} requires at least 2**J={min_len} samples "
            f"to produce any scattering coefficients (kymatio's low-pass filter needs "
            f"this much support to average over). At the inferred sampling rate of "
            f"{fs:.3g} Hz that is {min_len / fs:.1f}s of data. Either shorten J or only "
            f"run scattering on windows/recordings at least this long."
        )

    recommended_len = min_len * 8  # empirical safety margin against border-effect warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        scattering = Scattering1D(J=J, shape=n, Q=Q, T=T, max_order=max_order)
        Sx = scattering.scattering(x)
    border_flagged = any("border effects" in str(w.message) for w in caught)

    n_frames = Sx.shape[-1]
    if n_frames == 0:
        raise ValueError(
            f"Scattering produced zero output time frames for n={n} samples, J={J}. "
            f"This should not happen given the 2**J={min_len}-sample floor already "
            f"checked above -- treat this as a bug and inspect the kymatio version."
        )

    if border_flagged:
        warnings.warn(
            f"Input length ({n} samples, {n / fs:.1f}s) is short relative to J={J} "
            f"(2**J={min_len} samples): kymatio flagged border effects in its filter "
            f"bank. Coefficients near the start/end of the signal -- and any large-scale "
            f"(low-order) coefficients -- will be distorted by edge padding rather than "
            f"reflecting genuine signal structure. For cleaner results, prefer inputs of "
            f"at least ~{recommended_len} samples (~{recommended_len / fs:.1f}s), or "
            f"reduce J.",
            UserWarning,
            stacklevel=2,
        )

    meta = scattering.meta()
    order = meta["order"]
    xi = meta["xi"][:, 0]
    j = meta["j"][:, 0]
    freq_hz = xi * fs

    T_actual = 2 ** scattering.log2_T
    t_scattering = t[0] + np.arange(n_frames) * T_actual / fs

    return ScatteringResult(
        Sx=Sx,
        t_scattering=t_scattering,
        order=order,
        xi=xi,
        freq_hz=freq_hz,
        j=j,
        J=J,
        Q=Q,
        max_order=max_order,
        T=T_actual,
        fs=fs,
        n_input=n,
        duration_s=n / fs,
        border_effects_flagged=bool(border_flagged),
    )


# ===========================================================================
# Demo — sanity-check on real project data
# ===========================================================================

if __name__ == "__main__":
    from Working.Preprocessing.manage_data.load_data import load_raw_data

    FILE = "M2_concat_fs1_CH0.npy"
    FS = 1.0

    x, t = load_raw_data(FILE, FS)

    # A ~1.7h slice keeps the demo fast; compute_wavelet_scattering itself
    # places no upper bound on input length (see module docstring).
    n_demo = min(len(x), 6000)
    x, t = x[:n_demo], t[:n_demo]

    print(f"Loaded {FILE}: {len(x):,} samples ({len(x) / FS / 3600:.2f}h @ {FS} Hz)")

    result = compute_wavelet_scattering(x, t, J=8, Q=8)

    print(f"Sx shape: {result.Sx.shape}  (n_coeffs x n_frames)")
    print(f"Orders present: {sorted(set(result.order.tolist()))}")
    print(f"T (averaging, samples): {result.T}  ->  {result.T / result.fs:.1f}s per frame")
    print(f"Border effects flagged: {result.border_effects_flagged}")
