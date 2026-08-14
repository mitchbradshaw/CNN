"""
Full implementation of the spike-detection and complexity-analysis pipeline from:

    Dehshibi, M.M. & Adamatzky, A. (2021).
    "Electrical activity of fungi: Spikes detection and complexity analysis."
    BioSystems 203, 104373.  https://doi.org/10.1016/j.biosystems.2021.104373

Pipeline (Section 3):
    Sect 3.1  -- Signal slicing via histogram state transitions
    Sect 3.2  -- Morse-wavelet-based time-localised event detection  (Algorithm 1 & 2)
    Sect 3.3  -- Analytic-signal envelope via DFT  (Algorithm 3)
    Algorithm 4 -- Final spike vs pseudo-spike classification

Every function maps to a numbered step or algorithm in the paper.
Assumptions / approximations are noted where the paper is ambiguous.
"""

from __future__ import annotations

import numpy as np
from numpy.fft import fft, ifft, rfft, irfft, rfftfreq
from scipy.interpolate import CubicSpline
from scipy.signal import find_peaks
from typing import List, Tuple, Optional
import matplotlib.pyplot as plt


# ============================================================
# Paper constants (fixed by the authors)
# ============================================================

# Morse wavelet (Sect. 3.2):
#   symmetry parameter gamma = 3 (Lilly & Olhede 2008 recommendation)
#   time-bandwidth product P^2 = betagamma = 60  ->  beta = 20
GAMMA: float = 3.0
BETA:  float = 20.0

# Scaling factor eta in Eq. (3); set empirically to 240.
ETA: float = 240.0

# Minimum distance (samples) between consecutive local extrema in the
# envelope step (Algorithm 3).  At 1 Hz: n_p = 60 samples = 60 s.
# Also used as the minimum spike duration cutoff in Algorithm 4.
N_P: int = 60

# Algorithm 2: regions shorter than 30 s are discarded before the
# pseudo-spike / spike decision.
MIN_ROI_WAVELET: int = 30

# Algorithm 4: final regions shorter than 60 s are discarded from both
# F_s and F_p.  "minimum spike length was 5 min" -> 60 s at 1 Hz.
MIN_SPIKE_DURATION: int = 60


# ============================================================
# SECTION 3.1 -- Signal slicing (histogram state-level method)
# ============================================================

def estimate_state_levels(
    signal_data: np.ndarray,
    n_bins: int = 100,
) -> Tuple[float, float]:
    """
    Estimate the low-state and high-state levels of the signal using the
    histogram method described in IEEE Std 181-2011, as cited in Sect. 3.1.

    Steps (numbered as in the paper):
    1. Determine min, max, and range of amplitude values.
    2. Sort amplitude values into histogram bins; bin width = range / n_bins.
    3. Identify hb_low, hb_high -- lowest and highest non-zero bin indices.
    4. Divide histogram into lower (hb_low ... mid) and upper (mid ... hb_high)
       sub-histograms, where mid = hb_low + 1/2(hb_high - hb_low).
    5. Calculate the weighted mean of each sub-histogram to obtain state levels.

    Returns
    -------
    low_state  : float   Mean amplitude of the lower sub-histogram.
    high_state : float   Mean amplitude of the upper sub-histogram.
    """
    sig_min, sig_max = float(np.min(signal_data)), float(np.max(signal_data))
    if sig_max == sig_min:
        return sig_min, sig_max

    counts, bin_edges = np.histogram(signal_data, bins=n_bins)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])

    nz = np.flatnonzero(counts)
    hb_low, hb_high = int(nz[0]), int(nz[-1])

    mid = hb_low + (hb_high - hb_low) // 2

    # Lower sub-histogram (steps 4--5)
    lo_w = counts[hb_low : mid + 1].astype(float)
    lo_c = bin_centers[hb_low : mid + 1]
    low_state = float(np.average(lo_c, weights=lo_w)) if lo_w.sum() > 0 else sig_min

    # Upper sub-histogram (steps 4--5)
    hi_w = counts[mid + 1 : hb_high + 1].astype(float)
    hi_c = bin_centers[mid + 1 : hb_high + 1]
    high_state = float(np.average(hi_c, weights=hi_w)) if hi_w.sum() > 0 else sig_max

    return low_state, high_state


def slice_signal(
    signal_data: np.ndarray,
) -> List[Tuple[int, int]]:
    """
    Sect. 3.1 -- Split the recording F(t) into k chunks f_k(t).

    "Each chunk is enclosed between the last negative-going transitions of
    each positive-polarity pulse and the next positive-going transition."

    Implementation:
    * Estimate state levels via estimate_state_levels().
    * Compute the mid-reference = (low_state + high_state) / 2.
    * Identify all falling (negative-going) and rising (positive-going)
      crossings of the mid-reference.
    * Each chunk spans [last falling edge before a pulse, next rising edge],
      capturing the full depolarisation -> repolarisation -> refractory cycle.

    Returns
    -------
    chunks : list of (start_idx, end_idx) pairs (inclusive, global indices).
             If no transitions are found, the entire signal is one chunk.
    """
    low_state, high_state = estimate_state_levels(signal_data)
    mid_ref = (low_state + high_state) / 2.0

    above = (signal_data >= mid_ref).astype(int)
    transitions = np.diff(above)

    rising  = np.flatnonzero(transitions >  0)   # +1: signal crossed upward
    falling = np.flatnonzero(transitions < 0)    # -1: signal crossed downward

    if len(falling) == 0 or len(rising) == 0:
        return [(0, len(signal_data) - 1)]

    chunks: List[Tuple[int, int]] = []
    for fall_idx in falling:
        next_rises = rising[rising > fall_idx]
        if len(next_rises) > 0:
            chunks.append((int(fall_idx), int(next_rises[0])))

    if not chunks:
        chunks = [(0, len(signal_data) - 1)]

    return chunks


# ============================================================
# SECTION 3.2 -- Morse-wavelet-based detection
# ============================================================

def _morse_peak_frequency(beta: float = BETA, gamma: float = GAMMA) -> float:
    """
    Peak (central) angular frequency of the Morse wavelet.

    omega_0 = (beta / gamma)^{1/gamma}   [dimensionless, normalised to 2pi*fs]

    Used to map scales s -> physical frequencies:  f_c = omega_0 / (2pi * s * dt)
    """
    return float((beta / gamma) ** (1.0 / gamma))   # ~ 1.882 for beta=20, gamma=3


def _morse_amplitude_coeff(beta: float = BETA, gamma: float = GAMMA) -> float:
    """
    Real-valued normalisation constant  a_{beta,gamma} = 2*(e*gamma/beta)^{1/gamma}  (Eq. 1).
    """
    return 2.0 * (np.e * gamma / beta) ** (1.0 / gamma)


def morse_wavelet_spectrum(
    omega: np.ndarray,
    beta: float = BETA,
    gamma: float = GAMMA,
) -> np.ndarray:
    """
    Morse wavelet in the frequency domain -- Eq. (1):

        Psi_{beta,gamma}(omega) = a_{beta,gamma} * omega^beta * exp(-omega^gamma)    for omega > 0
                    = 1/2 * a_{beta,gamma} * 0^beta * exp(0)    for omega = 0
                    = 0                               for omega < 0

    The wavelet is analytic (one-sided positive-frequency support).

    Parameters
    ----------
    omega : 1-D array of non-negative angular frequencies (dimensionless,
            already scaled by the CWT scale s).
    beta, gamma : Morse parameters  (beta=20, gamma=3 from paper).

    Returns
    -------
    psi : 1-D real array, same length as omega.
    """
    a = _morse_amplitude_coeff(beta, gamma)
    psi = np.zeros(len(omega), dtype=float)

    pos = omega > 0
    psi[pos] = a * (omega[pos] ** beta) * np.exp(-(omega[pos] ** gamma))
    # omega = 0: the formula gives 1/2 * a * 0^beta = 0 for beta > 0; left at 0.

    return psi


def compute_morse_wavelet_transform(
    chunk: np.ndarray,
    scales: Optional[np.ndarray] = None,
    beta: float = BETA,
    gamma: float = GAMMA,
    fs: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Continuous Morse-wavelet transform of one signal chunk -- Eq. (2).

    Computed efficiently via the convolution theorem:

        phi_{beta,gamma}(tau, s) = (1/2pi) integral e^{iomegatau} Psi*_{beta,gamma}(somega) F(omega) domega

    where F(omega) = FFT(f(t)).

    L1 normalisation (1/s, not 1/sqrts) is used as stated in Sect. 3.2:
    "instead, we used 1/s since we define the amplitude of time-located signals."

    Scales
    ------
    If `scales` is None, logarithmically spaced scales are chosen to cover
    the spike-relevant frequency range (0.001--0.4 Hz at fs=1 Hz), corresponding
    to periods of 2.5 s -- 1000 s.  This spans the reported spike durations
    (402 s dominant, range 60 -- ~10^4 s).

    Returns
    -------
    phi    : complex array (n_scales x N), wavelet coefficients.
    scales : 1-D array of the scales actually used.
    """
    N = len(chunk)
    omega_0 = _morse_peak_frequency(beta, gamma)   # ~ 1.882

    # --- Default scales --------------------------------------------------
    if scales is None:
        f_lo = max(1e-3, fs / N)          # lowest resolvable frequency
        f_hi = 0.4 * fs                   # stay well below Nyquist

        # Relationship: f_c [Hz] = omega_0 / (2pi * s * dt),  dt = 1/fs
        s_lo = omega_0 * fs / (2 * np.pi * f_hi)
        s_hi = omega_0 * fs / (2 * np.pi * f_lo)

        n_scales = 64
        scales = np.geomspace(s_lo, s_hi, n_scales)

    n_scales = len(scales)

    # --- FFT of signal (real input -> use rfft for efficiency) ----------
    freqs  = rfftfreq(N, d=1.0 / fs)          # Hz
    omega  = 2.0 * np.pi * freqs              # rad/s
    F      = rfft(chunk)

    phi = np.zeros((n_scales, N), dtype=complex)

    for k, s in enumerate(scales):
        # Scale the angular-frequency axis (dimensionless for the wavelet)
        s_omega = s * omega / fs              # s x omega / (2pi * fs)  ->  dimensionless

        # Morse wavelet at scaled frequencies
        psi_s = morse_wavelet_spectrum(s_omega, beta, gamma)

        # L1 normalisation
        psi_s_norm = psi_s / s

        # Frequency-domain product; Psi is real, so conjugate = itself
        product = psi_s_norm * F

        # IFFT (real) -> time-domain wavelet coefficients for scale k
        coeff = irfft(product, n=N)
        phi[k, :] = coeff

    return phi, scales


def normalise_wavelet_coefficients(
    phi: np.ndarray,
    eta: float = ETA,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Normalise wavelet coefficients per Eq. (3):

        kappa_{beta,gamma}(tau, s)  =  |phi_{beta,gamma}(tau, s)|^^T
        g_{beta,gamma}(tau, s)  =  ( eta * kappa(tau,s) - min_s kappa(tau,s) )
                           / max_s kappa(tau,s)   [then transposed]

    "min_s" and "max_s" denote the minimum/maximum taken per scale (row)
    across all time points, consistent with the paper's statement:
    "the maximum absolute value at each frequency is used for normalisation."

    Zero entries are set to 1 after normalisation (as stated in paper).

    Returns
    -------
    g      : 2-D array (n_scales x N), normalised coefficients.
    g_sum  : 1-D array (N,), Omega(tau) -- sum of g across scales at each time tau.
             This is the quantity on which Algorithm 1 finds local extrema
             (matches Fig. 6 which shows a smooth 1-D time series Omega(tau)).
    """
    kappa = np.abs(phi)                                   # (n_scales x N)

    kappa_min = kappa.min(axis=1, keepdims=True)          # per-scale min
    kappa_max = kappa.max(axis=1, keepdims=True)          # per-scale max

    denom = kappa_max - kappa_min
    denom[denom == 0] = 1.0                               # avoid /0

    g = eta * (kappa - kappa_min) / denom          # Eq. (3): normalise to [0, eta]

    g[g == 0] = 1.0                                       # paper: "set zero entries to 1"

    g_sum = g.sum(axis=0)                                 # Omega(tau)

    return g, g_sum


# ============================================================
# ALGORITHM 1 -- Candidate regions for time-localised events
# ============================================================

def _find_extrema_indices(
    x: np.ndarray,
    epsilon: float,
    kind: str,
) -> np.ndarray:
    """
    Return indices of local maxima or minima of x with prominence >= epsilon.

    The paper defines LocalMaximum as "tau* such that for alltau in (tau*+/-epsilon),
    g(tau*,s) >= g(tau,s)".  We interpret epsilon as a minimum *prominence* of
    the peak, which is the closest standard equivalent in scipy.

    Parameters
    ----------
    x       : 1-D array.
    epsilon : minimum prominence threshold.
    kind    : 'max' or 'min'.
    """
    if kind == 'max':
        idx, _ = find_peaks(x, prominence=epsilon)
    else:
        idx, _ = find_peaks(-x, prominence=epsilon)
    return idx


def algorithm1_detect_candidate_regions(
    g_sum: np.ndarray,
    epsilon_factor: float = 0.05,
) -> List[Tuple[int, int]]:
    """
    Algorithm 1 (paper p. 8): Detecting candidate regions for
    time-localised events.

    Input  : g_{beta,gamma}(tau, s) collapsed to Omega(tau) = Sigma_s g(tau,s) = g_sum.
    Output : B -- list of candidate (start, end) index pairs.

    Steps (directly from the pseudocode):
    2.  epsilon = epsilon_factor x (max(g) - min(g))   [paper: epsilon_factor=0.05]
    3.  max_g <- all LocalMaxima(g, epsilon)
    4.  min_g <- all LocalMinima(g, epsilon)
    5.  U <- sort( min_g U max_g )
    6.  n = card(U)
    7-10. If n = 1 (mod 2):  slack = mean(d consecutive);  append min(U_n+slack, tau_max)
    12. B <- (U_i, U_{i+1})  for all i in {1, 3, ..., n-1}   [1-based indexing in paper]
           = (U[i], U[i+1]) for i in {0, 2, 4, ...}  [0-based in Python]

    Parameters
    ----------
    g_sum          : 1-D array, Omega(tau).
    epsilon_factor : prominence threshold as fraction of Omega range.
                     Paper default: 0.05.  Increase (e.g. to 0.2) when the
                     signal has small oscillations that produce many spurious
                     local extrema in Omega and thus many short ROIs.
    """
    epsilon = epsilon_factor * (g_sum.max() - g_sum.min())

    max_idx = _find_extrema_indices(g_sum, epsilon, 'max')
    min_idx = _find_extrema_indices(g_sum, epsilon, 'min')

    U = np.sort(np.union1d(max_idx, min_idx))
    n = len(U)

    if n == 0:
        return []

    # Step 7-10: odd count -> add one extra entry
    if n % 2 == 1:
        diffs = np.diff(U.astype(float))
        slack = int(np.mean(diffs)) if len(diffs) > 0 else 1
        extra = min(int(U[-1]) + slack, len(g_sum) - 1)
        U = np.append(U, extra)
        n += 1

    # Step 12: pairs at 0-based even indices (= 1-based odd indices in paper)
    B: List[Tuple[int, int]] = []
    for i in range(0, n - 1, 2):
        B.append((int(U[i]), int(U[i + 1])))

    return B


# ============================================================
# ALGORITHM 2 -- Exclude pseudo-spike and inflation regions
# ============================================================

def _spline_local_extrema(
    chunk: np.ndarray,
    kind: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Locate local extrema inside `chunk` via cubic-spline interpolation
    (Hall & Meyer, 1976, as cited in Algorithm 2 comments).

    Fits a CubicSpline to the data, finds roots of its first derivative,
    then classifies each root as a maximum or minimum using the sign of
    the second derivative.

    Returns
    -------
    values  : array of extremum amplitudes.
    indices : corresponding (integer) sample indices within chunk.

    Fallback: if the spline fails or yields no roots, scipy.signal.find_peaks
    is used instead.
    """
    n = len(chunk)
    if n < 4:
        # Not enough points for a cubic spline
        if kind == 'max':
            idx = np.array([int(np.argmax(chunk))])
        else:
            idx = np.array([int(np.argmin(chunk))])
        return chunk[idx], idx

    t = np.arange(n, dtype=float)
    try:
        cs     = CubicSpline(t, chunk)
        d1     = cs.derivative(1)
        d2     = cs.derivative(2)
        roots  = d1.roots()

        # Keep roots strictly inside the signal window
        roots = roots[(roots > 0) & (roots < n - 1)]

        if len(roots) == 0:
            raise ValueError("no roots")

        d2_vals = d2(roots)
        if kind == 'max':
            mask = d2_vals < 0   # local max: d^2/dt^2 < 0
        else:
            mask = d2_vals > 0   # local min: d^2/dt^2 > 0

        if not mask.any():
            # All roots have wrong second derivative; return global extremum
            raise ValueError("no typed extrema from spline")

        roots_sel = roots[mask]
        vals_sel  = cs(roots_sel)
        int_idx   = np.clip(np.round(roots_sel).astype(int), 0, n - 1)

        return vals_sel, int_idx

    except Exception:
        # Fallback: scipy peak finder
        if kind == 'max':
            idx, _ = find_peaks(chunk)
        else:
            idx, _ = find_peaks(-chunk)
        if len(idx) == 0:
            idx = np.array([int(np.argmax(chunk) if kind == 'max'
                               else np.argmin(chunk))])
        return chunk[idx], idx


def algorithm2_exclude_pseudospike_regions(
    B: List[Tuple[int, int]],
    signal_data: np.ndarray,
    min_duration: int = MIN_ROI_WAVELET,
) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    """
    Algorithm 2 (paper p. 12): Exclude pseudo-spike and inflation regions
    from the candidate ROI set B.

    For each region (lb, ub) in B:
      * Skip if duration <= 30 s  ("too short" per footnote 2 / paper text).
      * Extract chunk = f[lb ... ub].
      * Find local minima and maxima of chunk via spline interpolation.
      * If f(minima_global_min) < min(f(lb), f(ub))  OR
           f(maxima_global_max) > max(f(lb), f(ub)):
            -> The chunk truly excursions beyond its endpoints -> candidate spike C.
        Else:
            -> The chunk stays within its endpoints -> pseudo-spike / inflection D.

    The criterion captures the depolarisation / repolarisation structure:
    a real spike MUST reach below the baseline at its boundaries (minima)
    or clearly peak above the boundary level (maxima).

    Returns
    -------
    C : wavelet-based ROIs that pass the spike criterion.
    D : pseudo-spike / inflection regions.
    """
    C: List[Tuple[int, int]] = []
    D: List[Tuple[int, int]] = []

    for (lb, ub) in B:
        if (ub - lb) <= min_duration:
            continue

        chunk   = signal_data[lb : ub + 1]
        f_lb    = float(signal_data[lb])
        f_ub    = float(signal_data[ub])
        bnd_min = min(f_lb, f_ub)
        bnd_max = max(f_lb, f_ub)

        min_vals, _ = _spline_local_extrema(chunk, 'min')
        max_vals, _ = _spline_local_extrema(chunk, 'max')

        if len(min_vals) == 0 or len(max_vals) == 0:
            D.append((lb, ub))
            continue

        # The spike excursion criterion (Algorithm 2 line 10)
        if float(np.min(min_vals)) < bnd_min or float(np.max(max_vals)) > bnd_max:
            C.append((lb, ub))
        else:
            D.append((lb, ub))

    return C, D


# ============================================================
# SECTION 3.3 -- Analytic-signal envelope
# ============================================================

def _second_derivative(x: np.ndarray) -> np.ndarray:
    """
    Discrete Laplacian approximation:  L = d^2f / (4 dt^2)  (Sect. 3.3).

    "the second numerical signal derivation (L = d^2f/4dt^2) was calculated"
    to "highlight effective signal peaks and neutralise inflection regions."

    At dt = 1 s (1 Hz sampling):
        L[n] = (x[n+1] - 2*x[n] + x[n-1]) / 4

    The factor of 4 in the denominator is taken directly from the paper's
    notation; it scales the Laplacian so that it remains in the same
    amplitude order as the original signal derivatives.

    Boundary values are replicated from the nearest interior point.
    """
    L = np.empty_like(x, dtype=float)
    L[1:-1] = (x[2:] - 2.0 * x[1:-1] + x[:-2]) / 4.0
    L[0]    = L[1]
    L[-1]   = L[-2]
    return L


def _analytic_signal_dft(L: np.ndarray) -> np.ndarray:
    """
    Generate the complex-valued analytic signal from a real sequence L[n]
    using the DFT-based approach of Marple (1999), as described in Sect. 3.3
    and Eqs. (4)--(5).

    Steps:
    1.  F[m] = DFT(L[n])                              N-point DFT
    2.  One-sided spectrum Z[m]:
            Z[0]         = F[0]
            Z[1..N/2-1] = 2*F[m]    (double positive frequencies)
            Z[N/2]       = F[N/2]   (Nyquist, for even N)
            Z[N/2+1..]  = 0
    3.  z[n] = IDFT(Z[m])            -> complex analytic signal

    Properties: Re(z[n]) ? L[n];  Im(z[n]) is the Hilbert transform of L[n].
    Both parts are orthogonal (analytic signal condition).

    Returns
    -------
    z : complex 1-D array, same length as L.
    """
    N = len(L)
    F = fft(L)                      # Step 1

    Z = np.zeros(N, dtype=complex)
    Z[0] = F[0]                     # DC component (Step 2)

    if N % 2 == 0:
        Z[1 : N // 2]     = 2.0 * F[1 : N // 2]    # positive freqs x 2
        Z[N // 2]         = F[N // 2]               # Nyquist (unpaired)
        # Z[N//2+1 : ]   = 0  (already zero)
    else:
        Z[1 : (N + 1) // 2] = 2.0 * F[1 : (N + 1) // 2]
        # Z[(N+1)//2 : ] = 0

    z = ifft(Z)                     # Step 3 (Eq. 5)
    return z


def compute_signal_envelope(
    chunk: np.ndarray,
    n_p: int = N_P,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Sect. 3.3 -- Compute the analytic-signal envelope of a chunk.

    Pipeline:
    a. Compute the second derivative L = d^2f / (4dt^2) to suppress slow
       drifts and emphasise rapid transients (spikes).
    b. Compute the complex analytic signal z[n] from L[n] via the DFT
       one-sided spectrum method (Marple 1999; Eqs. 4--5).
    c. Envelope  xi[n] = |z[n]|  (Eq. 6).
    d. Upper envelope xi_H[n]: cubic spline through local maxima of xi,
       separated by at least n_p = 60 samples.
    e. Lower envelope xi_L[n]: cubic spline through local minima of xi.
    f. Mean envelope xi_M[n] = (xi_H + xi_L) / 2  (Algorithm 3 input).

    "We considered n_p = 60 because ... we did not observe any electrical
    potential of spikes shorter than 60 s." (paper footnote 2)

    Returns
    -------
    xi_mean  : 1-D array -- mean envelope xi_M (input to Algorithm 3).
    xi_upper : 1-D array -- upper envelope xi_H.
    xi_lower : 1-D array -- lower envelope xi_L.
    """
    N = len(chunk)
    t = np.arange(N, dtype=float)

    # (a) Second numerical derivative
    L = _second_derivative(chunk)

    # (b) Analytic signal via DFT
    z = _analytic_signal_dft(L)

    # (c) Instantaneous amplitude envelope
    xi = np.abs(z)

    # (d) Upper envelope: spline over local maxima with distance >= n_p
    peak_idx, _ = find_peaks(xi, distance=n_p)
    if len(peak_idx) >= 2:
        x_pk = np.concatenate([[0], peak_idx, [N - 1]])
        y_pk = np.concatenate([[xi[0]], xi[peak_idx], [xi[-1]]])
        order = np.argsort(x_pk)
        xi_upper = CubicSpline(x_pk[order], y_pk[order])(t)
    else:
        xi_upper = np.full(N, xi.max())

    # (e) Lower envelope: spline over local minima with distance >= n_p
    trough_idx, _ = find_peaks(-xi, distance=n_p)
    if len(trough_idx) >= 2:
        x_tr = np.concatenate([[0], trough_idx, [N - 1]])
        y_tr = np.concatenate([[xi[0]], xi[trough_idx], [xi[-1]]])
        order = np.argsort(x_tr)
        xi_lower = CubicSpline(x_tr[order], y_tr[order])(t)
    else:
        xi_lower = np.full(N, xi.min())

    # (f) Mean envelope (Algorithm 3 uses xi_M)
    xi_mean = (xi_upper + xi_lower) / 2.0

    return xi_mean, xi_upper, xi_lower


# ============================================================
# ALGORITHM 3 -- Candidate spike regions from the signal envelope
# ============================================================

def algorithm3_detect_envelope_regions(
    xi_mean:  np.ndarray,
    xi_upper: np.ndarray,
    xi_lower: np.ndarray,
    n_p: int = N_P,
) -> np.ndarray:
    """
    Algorithm 3 (paper p. 15): Detecting candidate spike regions from the
    signal envelope.

    Input  : xi[n] = (xi_H + xi_L) / 2 (xi_mean), n_p = 60.
    Output : R  --  array of shape (n_regions, 3) with columns
                    [ind_min, ind_max, ? = val_max - val_min].

    Steps (from pseudocode):
    2.  xi_M[n] = (xi_H[n] + xi_L[n]) / 2                   (= xi_mean)
    3.  Find local minima of xi_M with min separation n_p.
    4.  Find local maxima of xi_M with min separation n_p.
    5.  j <- index of first local max whose value > value of first local min.
    6-12. Pair each successive local minimum with the next local maximum;
          compute ? = val_max - val_min.
    13. rho = mean(R_3) - std(R_3)
    14. Remove entries where R_3(k) < rho.

    Physical rationale: each (min, max) pair corresponds to a potential
    depolarisation -> peak region of a spike.  The threshold rho eliminates
    weak events that are likely noise.
    """
    xi_M = xi_mean

    # Local minima and maxima of xi_M (min separation = n_p samples)
    min_idx, _ = find_peaks(-xi_M, distance=n_p)
    max_idx, _ = find_peaks( xi_M, distance=n_p)

    if len(min_idx) == 0 or len(max_idx) == 0:
        return np.empty((0, 3), dtype=float)

    val_min = xi_M[min_idx]
    val_max = xi_M[max_idx]

    # Step 5: start from first max that exceeds the first min value
    first_min_val = float(val_min[0])
    j_starts = np.flatnonzero(val_max > first_min_val)
    j = int(j_starts[0]) if len(j_starts) > 0 else 0

    # Steps 6--12: build R
    rows: List[List[float]] = []
    for i in range(len(min_idx)):
        if j >= len(max_idx):
            break
        delta = float(val_max[j] - val_min[i])
        rows.append([float(min_idx[i]), float(max_idx[j]), delta])
        j += 1

    if not rows:
        return np.empty((0, 3), dtype=float)

    R = np.array(rows, dtype=float)

    # Steps 13--14: filter by rho = mean(?) - std(?)
    if R.shape[0] > 1:
        rho  = float(R[:, 2].mean() - R[:, 2].std())
        keep = R[:, 2] >= rho
        R    = R[keep]

    return R


# ============================================================
# ALGORITHM 4 -- Extract final spike and pseudo-spike events
# ============================================================

def _overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    """True if [a0,a1] and [b0,b1] have a non-empty intersection."""
    return not (a1 < b0 or b1 < a0)


def _is_subset(inner0: int, inner1: int, outer0: int, outer1: int) -> bool:
    """True if [inner0,inner1] ? [outer0,outer1]."""
    return outer0 <= inner0 and inner1 <= outer1


def algorithm4_extract_spike_events(
    C: List[Tuple[int, int]],
    D: List[Tuple[int, int]],
    R: np.ndarray,
    min_duration: int = MIN_SPIKE_DURATION,
) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    """
    Algorithm 4 (paper p. 16): Extracting fungi spike and pseudo-spike events.

    Input  : C  -- wavelet-based spike candidates (Algorithm 2).
             D  -- pseudo-spike / inflection candidates (Algorithm 2).
             R  -- envelope-based ROIs, shape (n,3): [start, end, ?] (Algorithm 3).
             min_duration -- minimum region length (60 s); shorter ones discarded.

    Output : F_s -- confirmed spike events.
             F_p -- pseudo-spike events.

    Logic (from paper pseudocode):
    For each envelope ROI chunk_e in R:
        For each wavelet ROI chunk_w in C?D:
            case chunk_e subset chunk_w :
                update chunk_w end to chunk_e end -> F_s  (wavelet validates envelope)
            case chunk_w subset chunk_e :
                chunk_w -> F_p  (wavelet ROI too small; envelope region is broader)
            case partial intersection :
                concatenate both chunks, split at intersection midpoint,
                shorter sub-chunk -> F_p

    Regions < min_duration samples are removed from both F_s and F_p.

    Physical rationale:
    * When the envelope ROI (from second-derivative energy) is fully contained
      inside a wavelet ROI, the wavelet confirms a real spike whose envelope
      sub-region is the active core  ->  true spike F_s.
    * When the wavelet ROI is inside the envelope ROI, the wavelet event is
      too localised to constitute a full spike cycle  ->  pseudo-spike F_p.
    """
    F_s: List[Tuple[int, int]] = []
    F_p: List[Tuple[int, int]] = []

    if R.shape[0] == 0:
        return F_s, F_p

    wavelet_regions = list(C) + list(D)

    for row in R:
        e0, e1 = int(row[0]), int(row[1])   # envelope ROI [chunk_e]

        for (w0, w1) in wavelet_regions:     # wavelet ROI [chunk_w]
            if not _overlaps(e0, e1, w0, w1):
                continue

            # Case 1: chunk_e subset chunk_w  -> update chunk_w end, add to F_s
            if _is_subset(e0, e1, w0, w1):
                F_s.append((w0, e1))

            # Case 2: chunk_w subset chunk_e  -> add chunk_w to F_p
            elif _is_subset(w0, w1, e0, e1):
                F_p.append((w0, w1))

            # Case 3: partial overlap -> split concatenated region at midpoint
            else:
                inter0 = max(e0, w0)
                inter1 = min(e1, w1)
                split  = (inter0 + inter1) // 2    # intersection midpoint

                combined0 = min(e0, w0)
                combined1 = max(e1, w1)

                sub1 = (combined0, split)
                sub2 = (split,     combined1)

                # Shorter sub-chunk -> F_p
                if (split - combined0) <= (combined1 - split):
                    F_p.append(sub1)
                else:
                    F_p.append(sub2)

    # Remove regions shorter than min_duration (Algorithm 4 lines 21-23)
    F_s = [(s, e) for (s, e) in F_s if (e - s) >= min_duration]
    F_p = [(s, e) for (s, e) in F_p if (e - s) >= min_duration]

    return F_s, F_p


# ============================================================
# FULL DETECTION PIPELINE
# ============================================================

def detect_spikes(
    signal_data: np.ndarray,
    fs: float = 1.0,
    scales: Optional[np.ndarray] = None,
    beta:  float = BETA,
    gamma: float = GAMMA,
    eta:   float = ETA,
    n_p:   int   = N_P,
    min_spike_duration: int = MIN_SPIKE_DURATION,
    min_roi_wavelet:    int = MIN_ROI_WAVELET,
    epsilon_factor:     float = 0.05,
) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]], dict]:
    """
    Full unsupervised spike-detection pipeline (Dehshibi & Adamatzky 2021).

    Sequence of operations (mirroring Fig. 3 pipeline diagram):
    1. Sect. 3.1  -- Slice F(t) into chunks based on histogram state transitions.
    2. Per chunk:
        a. Sect. 3.2 -- Morse wavelet transform + Eq. (3) normalisation.
        b. Algorithm 1 -- Candidate ROIs from wavelet coefficients (B).
        c. Algorithm 2 -- Classify B into spike candidates C and pseudo-spikes D.
        d. Sect. 3.3 -- Analytic-signal envelope (second derivative + DFT).
        e. Algorithm 3 -- Candidate ROIs from envelope (R).
        f. Algorithm 4 -- Merge wavelet and envelope ROIs -> F_s (spikes), F_p.
    3. Aggregate across all chunks.

    Parameters
    ----------
    signal_data         : 1-D array of electrical potential (V).
    fs                  : sampling frequency (Hz).  Default 1.0 (1 sample/s).
    scales              : CWT scales; auto-computed if None.
    beta, gamma         : Morse wavelet parameters (beta=20, gamma=3).
    eta                 : Eq. (3) scaling factor (240).
    n_p                 : minimum extrema separation (60 samples at 1 Hz).
    min_spike_duration  : minimum spike length in samples (60).
    min_roi_wavelet     : minimum wavelet-ROI length for Algorithm 2 (30).

    Returns
    -------
    spikes        : list of (start, end) global indices for confirmed spikes.
    pseudo_spikes : list of (start, end) for pseudo-spike events.
    info          : dict with intermediate results keyed by stage name.
    """
    info: dict = {
        'chunks':  [],
        'B':       [],   # Algorithm 1 output (global indices)
        'C':       [],   # Algorithm 2 candidate spikes
        'D':       [],   # Algorithm 2 pseudo-spikes
        'R':       [],   # Algorithm 3 envelope ROIs
    }

    all_spikes:  List[Tuple[int, int]] = []
    all_pseudo:  List[Tuple[int, int]] = []

    # ?? Step 1: slice ??????????????????????????????????????????????????????
    chunks = slice_signal(signal_data)
    info['chunks'] = chunks

    for (c_start, c_end) in chunks:
        chunk_data = signal_data[c_start : c_end + 1]
        N_chunk    = len(chunk_data)

        # Need at least 2*n_p samples to find extrema pairs
        if N_chunk < 2 * n_p:
            continue

        # ?? Step 2a: Morse wavelet transform ??????????????????????????????
        phi, used_scales = compute_morse_wavelet_transform(
            chunk_data, scales=scales, beta=beta, gamma=gamma, fs=fs,
        )
        g, g_sum = normalise_wavelet_coefficients(phi, eta=eta)

        # ?? Step 2b: Algorithm 1 (local indices) -> convert to global ?????
        B_local  = algorithm1_detect_candidate_regions(g_sum, epsilon_factor=epsilon_factor)
        B_global = [(c_start + s, c_start + e) for (s, e) in B_local]
        info['B'].extend(B_global)

        # ?? Step 2c: Algorithm 2 (operates on global signal) ??????????????
        C_global, D_global = algorithm2_exclude_pseudospike_regions(
            B_global, signal_data, min_duration=min_roi_wavelet,
        )
        info['C'].extend(C_global)
        info['D'].extend(D_global)

        # ?? Step 2d: Analytic-signal envelope ?????????????????????????????
        xi_mean, xi_upper, xi_lower = compute_signal_envelope(chunk_data, n_p=n_p)

        # ?? Step 2e: Algorithm 3 (local indices -> convert to global) ??????
        R_local = algorithm3_detect_envelope_regions(xi_mean, xi_upper, xi_lower, n_p=n_p)

        if R_local.shape[0] > 0:
            R_global = R_local.copy()
            R_global[:, 0] += c_start      # shift start indices
            R_global[:, 1] += c_start      # shift end indices
        else:
            R_global = R_local

        info['R'].append(R_global)

        # ?? Step 2f: Algorithm 4 ??????????????????????????????????????????
        chunk_spikes, chunk_pseudo = algorithm4_extract_spike_events(
            C_global, D_global, R_global, min_duration=min_spike_duration,
        )
        all_spikes.extend(chunk_spikes)
        all_pseudo.extend(chunk_pseudo)

    return all_spikes, all_pseudo, info


def detect_spikes_sliding_window(
    signal_data: np.ndarray,
    fs: float = 1.0,
    window_size: int = 3600,
    step_size: Optional[int] = None,
    verbose: bool = True,
    **kwargs,
) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    """
    Run the Dehshibi & Adamatzky (2021) pipeline across a long recording
    by stepping a fixed-length window through the signal.

    Why this is necessary
    ---------------------
    The pipeline's internal normalisation (Eq. 3, wavelet per-scale min/max)
    and histogram state estimator (Sect. 3.1) both operate relative to the
    amplitude range of the chunk they receive.  When a short spike sits inside
    a multi-hour window the spike energy is negligible relative to the global
    statistics, so it is missed.  The paper's own experiments used ~3000-second
    chunks (Fig. 5).  Processing the recording in appropriately-sized windows
    keeps spike amplitudes significant.

    Parameters
    ----------
    signal_data : 1-D array of electrical potential (V).
    fs          : sampling frequency (Hz).  Default 1.0.
    window_size : number of samples per window.  Default 3600 (= 1 hour at 1 Hz).
    step_size   : number of samples to advance between windows.
                  Default = window_size (no overlap).
                  Use step_size < window_size for overlap -- spikes at window
                  boundaries will then be captured in at least one window.
    verbose     : print progress and per-window counts.  Default True.
    **kwargs    : forwarded to detect_spikes (e.g. n_p, min_spike_duration).

    Returns
    -------
    spikes        : list of (start, end) global sample indices for confirmed spikes.
    pseudo_spikes : list of (start, end) global sample indices for pseudo-spikes.

    Notes
    -----
    * Spike indices are expressed relative to the START of signal_data, so they
      can be used directly to index into the original array.
    * When step_size < window_size, a spike may be detected in two overlapping
      windows.  Duplicates are removed: any two intervals whose overlap exceeds
      half the length of the shorter one are merged into their union.
    """
    if step_size is None:
        step_size = window_size

    N = len(signal_data)
    all_spikes:  List[Tuple[int, int]] = []
    all_pseudo:  List[Tuple[int, int]] = []

    starts = list(range(0, N - window_size + 1, step_size))
    # Capture the final partial window if it is large enough to be informative
    if starts and starts[-1] + window_size < N:
        tail_start = N - window_size
        if tail_start > starts[-1]:
            starts.append(tail_start)

    n_windows = len(starts)
    if verbose:
        print(f"Sliding-window spike detection")
        print(f"  Signal length : {N} samples  ({N / fs / 3600:.1f} h at {fs} Hz)")
        print(f"  Window size   : {window_size} samples  ({window_size / fs / 60:.0f} min)")
        print(f"  Step size     : {step_size} samples  ({step_size / fs / 60:.0f} min)")
        print(f"  Windows       : {n_windows}")
        print()

    for i, w_start in enumerate(starts):
        w_end   = min(w_start + window_size, N)
        chunk   = signal_data[w_start:w_end]

        if verbose:
            pct = 100.0 * (i + 1) / n_windows
            print(f"  [{i+1:4d}/{n_windows}]  samples [{w_start:7d}, {w_end:7d})  "
                  f"({w_start / fs / 3600:.2f} h -- {w_end / fs / 3600:.2f} h) ...",
                  end="", flush=True)

        spikes_local, pseudo_local, _ = detect_spikes(chunk, fs=fs, **kwargs)

        # Convert local indices to global
        spikes_global = [(w_start + s, w_start + e) for (s, e) in spikes_local]
        pseudo_global = [(w_start + s, w_start + e) for (s, e) in pseudo_local]

        all_spikes.extend(spikes_global)
        all_pseudo.extend(pseudo_global)

        if verbose:
            print(f"  {len(spikes_local)} spikes, {len(pseudo_local)} pseudo-spikes")

    # --- Deduplicate overlapping detections from overlapping windows -----------
    def _merge_overlapping(
        regions: List[Tuple[int, int]]
    ) -> List[Tuple[int, int]]:
        """
        Merge any two intervals whose overlap is > 50% of the shorter one.
        Returns a sorted, deduplicated list.
        """
        if not regions:
            return []
        regions = sorted(regions)
        merged = [regions[0]]
        for s, e in regions[1:]:
            ps, pe = merged[-1]
            overlap = max(0, min(pe, e) - max(ps, s))
            shorter = min(pe - ps, e - s)
            if shorter > 0 and overlap / shorter > 0.5:
                merged[-1] = (ps, max(pe, e))   # extend
            else:
                merged.append((s, e))
        return merged

    all_spikes = _merge_overlapping(all_spikes)
    all_pseudo = _merge_overlapping(all_pseudo)

    if verbose:
        print()
        print(f"  Total confirmed spikes  : {len(all_spikes)}")
        print(f"  Total pseudo-spikes     : {len(all_pseudo)}")

    return all_spikes, all_pseudo


# ============================================================
# SECTION 4.2 -- Complexity measures
# ============================================================

def compute_shannon_entropy(
    spike_regions: List[Tuple[int, int]],
    signal_length: int,
) -> float:
    """
    Shannon entropy  H = -Sigma_w (nu(w)/eta) * ln(nu(w)/eta)

    where nu(w) is the count of neighbourhood configuration w (here: unique
    spike durations) and eta = total number of spike events (Sect. 4.2 item 1).
    """
    if not spike_regions:
        return 0.0
    eta    = len(spike_regions)
    durs   = np.array([e - s for (s, e) in spike_regions], dtype=float)
    _, cnts = np.unique(durs, return_counts=True)
    p      = cnts / eta
    return float(-np.sum(p * np.log(p)))           # p > 0 always (counts/total)


def compute_simpsons_diversity(
    spike_regions: List[Tuple[int, int]],
) -> float:
    """
    Simpson's diversity  S = Sigma_w (nu(w)/eta)^2  (Sect. 4.2 item 2).
    Ranges 0 (no diversity) to 1 (infinite diversity; note: inverse of the
    classic Simpson index).
    """
    if not spike_regions:
        return 0.0
    eta    = len(spike_regions)
    durs   = np.array([e - s for (s, e) in spike_regions], dtype=float)
    _, cnts = np.unique(durs, return_counts=True)
    p      = cnts / eta
    return float(np.sum(p ** 2))


def compute_space_filling(
    spike_regions: List[Tuple[int, int]],
    signal_length: int,
) -> float:
    """
    Space filling  D = (# non-zero entries in W) / (total signal length)
                     = (union of spike samples) / signal_length  (Sect. 4.2 item 3).

    The union is used rather than a raw sum so that overlapping spike regions
    (which Algorithm 4 can produce when multiple envelope ROIs are subsets of
    the same wavelet window) are counted only once -- matching the binary
    spike-train definition in the paper.
    """
    if not spike_regions:
        return 0.0
    # Build union of intervals to avoid counting overlapping regions twice
    sorted_regions = sorted(spike_regions, key=lambda r: r[0])
    union_samples = 0
    cur_start, cur_end = sorted_regions[0]
    for s, e in sorted_regions[1:]:
        if s <= cur_end:               # overlapping or adjacent -- extend
            cur_end = max(cur_end, e)
        else:                          # gap -- commit current interval
            union_samples += cur_end - cur_start
            cur_start, cur_end = s, e
    union_samples += cur_end - cur_start
    return union_samples / signal_length


def compute_expressiveness(H: float, D: float) -> float:
    """
    Expressiveness  E = H / D  (Sect. 4.2 item 4).
    Reflects the 'economy of diversity' -- entropy normalised by density.
    """
    return 0.0 if D == 0.0 else H / D


def _lz76_complexity(s: str) -> float:
    """
    Lempel-Ziv 76 (Kaspar & Schuster 1987) complexity of a binary string.

    Returns the normalised complexity c / b(n) where b(n) = n / log_2(n).
    This is the version used in the paper's cross-channel LZ measure (Table 2).
    """
    n = len(s)
    if n <= 1:
        return 0.0

    i, k, l     = 0, 1, 1
    k_max, c    = 1, 1

    while True:
        if (i + k - 1 < n) and (l + k - 1 < n) and s[i + k - 1] == s[l + k - 1]:
            k += 1
            if l + k > n:
                c += 1
                break
        else:
            if k > k_max:
                k_max = k
            i += 1
            if i == l:
                c += 1
                l += k_max
                if l + 1 > n:
                    break
                i, k, k_max = 0, 1, 1
            else:
                k = 1

    b_n = n / np.log2(n)
    return c / b_n


def compute_lempel_ziv_complexity(
    spike_regions: List[Tuple[int, int]],
    signal_length: int,
) -> float:
    """
    Lempel-Ziv complexity of the binary spike train (Sect. 4.2 item 5).

    The binary string encodes '1' during spike windows and '0' elsewhere.
    The Kaspar-Schuster (1987) algorithm is applied (normalised LZ76).

    Note: the paper's Table 2 reports a PNG-compression-ratio proxy for LZ
    (ratio of barcode image size to signal image size) but also uses the
    Kaspar-Schuster formula for the binary string.  This function implements
    the latter, which is directly applicable without image files.
    """
    spike_train = np.zeros(signal_length, dtype=int)
    for (s, e) in spike_regions:
        spike_train[max(0, s) : min(signal_length, e + 1)] = 1

    binary_str = ''.join(spike_train.astype(str))
    return _lz76_complexity(binary_str)


def compute_kolmogorov_complexity(
    spike_regions: List[Tuple[int, int]],
    signal_length: int,
) -> float:
    """
    Kolmogorov complexity approximated via Kaspar-Schuster (1987) LZ76
    algorithm on the binary spike train (Sect. 4.2).

    In the paper this is distinct from the PNG-based LZ complexity: it is
    the raw normalised LZ76 value multiplied by ln(2) to convert bit-based
    normalisation to nats, matching the reported range 11x10-^4 -- 57x10-^4.
    """
    lz = compute_lempel_ziv_complexity(spike_regions, signal_length)
    return lz * np.log(2)          # convert from bits to nats


def compute_pci(lz: float, H: float) -> float:
    """
    Perturbation Complexity Index  PCI = LZ / H  (Sect. 4.2 item 6).

    Returns nan when H = 0 (only one spike, or all spikes same duration),
    since PCI is undefined for a degenerate entropy.
    """
    return float('nan') if abs(H) < 1e-10 else lz / H


def compute_all_complexity_measures(
    spike_regions: List[Tuple[int, int]],
    signal_length: int,
) -> dict:
    """
    Compute the full suite of complexity measures from Sect. 4.2.

    Returns a dict with keys:
        n_spikes, shannon_entropy, simpsons_diversity, space_filling,
        expressiveness, lz_complexity, kolmogorov, pci
    """
    H   = compute_shannon_entropy(spike_regions, signal_length)
    S   = compute_simpsons_diversity(spike_regions)
    D   = compute_space_filling(spike_regions, signal_length)
    E   = compute_expressiveness(H, D)
    LZ  = compute_lempel_ziv_complexity(spike_regions, signal_length)
    K   = compute_kolmogorov_complexity(spike_regions, signal_length)
    PCI = compute_pci(LZ, H)

    return {
        'n_spikes':          len(spike_regions),
        'shannon_entropy':   H,
        'simpsons_diversity': S,
        'space_filling':     D,
        'expressiveness':    E,
        'lz_complexity':     LZ,
        'kolmogorov':        K,
        'pci':               PCI,
    }


# ============================================================
# VISUALISATION (Figs. 9 & 14 style)
# ============================================================

def plot_spike_detection(
    signal_data: np.ndarray,
    spikes: List[Tuple[int, int]],
    pseudo_spikes: List[Tuple[int, int]],
    fs: float = 1.0,
    title: str = "Spike Detection -- Dehshibi & Adamatzky 2021",
) -> plt.Figure:
    """
    Plot the signal with detected spike regions overlaid.

    Spike regions  : alternately orange / violet  (Fig. 9 convention).
    Pseudo-spikes  : alternately blue / cyan.
    """
    t = np.arange(len(signal_data)) / fs

    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(t, signal_data, color='black', linewidth=0.5, label='Signal')

    spike_colors  = ['orange', 'violet']
    pseudo_colors = ['blue',   'cyan'  ]

    for i, (s, e) in enumerate(spikes):
        ax.axvspan(t[s], t[min(e, len(t) - 1)],
                   alpha=0.4, color=spike_colors[i % 2],
                   label='Spike' if i == 0 else '_')

    for i, (s, e) in enumerate(pseudo_spikes):
        ax.axvspan(t[s], t[min(e, len(t) - 1)],
                   alpha=0.3, color=pseudo_colors[i % 2],
                   label='Pseudo-spike' if i == 0 else '_')

    ax.set_xlabel('Time (sec)')
    ax.set_ylabel('Amplitude (V)')
    ax.set_title(title)
    ax.legend(loc='upper right', fontsize=8)
    fig.tight_layout()
    return fig


# ============================================================
# SELF-TEST  (end-to-end validation on synthetic data)
# ============================================================

if __name__ == '__main__':
    np.random.seed(42)

    # ?? Synthetic signal matching paper parameters ?????????????????????????
    # Duration: 3000 s  (a single 3000-s chunk, as used in Fig. 5).
    # Sampling: 1 Hz  (1 sample/second, per paper Sect. 2).
    # Amplitude scale: ~21 mV baseline with 1 mV spike excursion.

    N   = 3000
    fs  = 1.0
    t   = np.arange(N, dtype=float)

    # Slowly drifting baseline (mimics Fig. 1 slow DC drift)
    baseline = 0.021 + 5e-4 * np.sin(2 * np.pi * t / 1500.0)

    # Low-amplitude Gaussian noise (SNR ~ 20 dB)
    noise = np.random.normal(0.0, 8e-5, N)

    signal_data = baseline + noise

    def _add_spike(sig: np.ndarray, t0: int, length: int = 402) -> np.ndarray:
        """
        Inject an action-potential-like spike at sample t0 with the
        canonical structure described in Fig. 1(d):
            depolarisation -> repolarisation -> refractory period.
        Dominant duration ~ 402 s matches the paper's finding.
        """
        dep  = length // 4           # depolarisation ramp
        rep  = length // 4           # repolarisation ramp
        ref  = length - dep - rep    # refractory tail

        tt = t0
        amp = 1e-3                   # 1 mV peak-to-peak (paper range 0.5--6 mV)

        # Depolarisation: linear rise
        end = min(tt + dep, len(sig))
        sig[tt:end] += amp * np.linspace(0.0, 1.0, end - tt)
        tt = end

        # Repolarisation: linear fall past baseline
        end = min(tt + rep, len(sig))
        sig[tt:end] += amp * np.linspace(1.0, -0.2, end - tt)
        tt = end

        # Refractory: slow exponential return to baseline
        end = min(tt + ref, len(sig))
        sig[tt:end] += (-0.2 * amp) * np.exp(
            -3.0 * np.linspace(0.0, 1.0, end - tt)
        )
        return sig

    # Inject three spikes at well-separated positions (duration 402 s each)
    signal_data = _add_spike(signal_data, t0=200)
    signal_data = _add_spike(signal_data, t0=1100)
    signal_data = _add_spike(signal_data, t0=2300)

    print("=" * 60)
    print("Dehshibi & Adamatzky (2021) -- spike detection pipeline")
    print(f"Signal: {N} samples at {fs} Hz")
    print("=" * 60)

    spikes, pseudo_spikes, info = detect_spikes(
        signal_data,
        fs=fs,
        n_p=N_P,
        min_spike_duration=MIN_SPIKE_DURATION,
        min_roi_wavelet=MIN_ROI_WAVELET,
    )

    print(f"\nChunks found   : {len(info['chunks'])}")
    print(f"Wavelet B ROIs : {len(info['B'])}")
    print(f"Algorithm 2 C  : {len(info['C'])}  (spike candidates)")
    print(f"Algorithm 2 D  : {len(info['D'])}  (pseudo-spike candidates)")
    n_env = sum(r.shape[0] for r in info['R'] if r.shape[0] > 0)
    print(f"Envelope R ROIs: {n_env}")
    print(f"\nDetected spikes       : {len(spikes)}")
    for i, (s, e) in enumerate(spikes):
        print(f"  Spike {i+1}: [{s} s, {e} s]  duration={e - s} s")
    print(f"Detected pseudo-spikes: {len(pseudo_spikes)}")

    # ?? Complexity analysis ????????????????????????????????????????????????
    if spikes:
        metrics = compute_all_complexity_measures(spikes, N)
        print("\nComplexity measures (Sect. 4.2):")
        for k, v in metrics.items():
            if isinstance(v, float):
                print(f"  {k:<22s}: {v:.6f}")
            else:
                print(f"  {k:<22s}: {v}")

    # ?? Visualisation ?????????????????????????????????????????????????????
    fig = plot_spike_detection(signal_data, spikes, pseudo_spikes, fs=fs)
    plt.show()
