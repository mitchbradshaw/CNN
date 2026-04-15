import numpy as np
import scipy.io
import scipy.signal
import glob
import os
import re
import json
import random
import matplotlib.pyplot as py


def stft_log_spectrum(
    x: np.ndarray,
    fs: float,
    window_size: int,
    hop_size: int,
    n_log_bins: int = 64,
    return_2d: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute an STFT over a 1-D signal and aggregate the power spectrum into
    logarithmically spaced frequency bins.

    Log-frequency binning mirrors how the auditory system (and most spectral
    analysis of biological signals) perceives frequency: finer resolution at
    low frequencies, coarser at high.  A uniform FFT on EEG data at fs=1 Hz
    produces 300 bins of equal width; log bins compress the high-frequency
    noise floor and expand the low-frequency content you actually care about.

    Parameters
    ----------
    x            : 1-D np.ndarray   Raw time-series signal.
    fs           : float            Sampling frequency in Hz.
    window_size  : int              STFT window length in samples.
    hop_size     : int              Hop (stride) between successive windows.
    n_log_bins   : int              Number of logarithmically spaced output bins.
                                    Default 64.
    return_2d    : bool             If False (default), return the mean power
                                    across all time frames (shape: [n_log_bins]).
                                    If True, return the full time × log-bin
                                    matrix (shape: [n_frames, n_log_bins]).

    Returns
    -------
    bin_freqs    : np.ndarray       Centre frequency of each log bin (Hz).
                                    Shape: [n_log_bins].
    power        : np.ndarray       Average power per log bin (return_2d=False)
                                    OR power per frame per bin (return_2d=True).

    Raises
    ------
    ValueError   If the signal is shorter than one window.

    Example
    -------
    >>> bin_freqs, avg_power = stft_log_spectrum(signal, fs=1.0,
    ...                                          window_size=300, hop_size=150)
    >>> bin_freqs, power_2d  = stft_log_spectrum(signal, fs=1.0,
    ...                                          window_size=300, hop_size=150,
    ...                                          return_2d=True)
    """
    if len(x) < window_size:
        raise ValueError(
            f"Signal length ({len(x)}) is shorter than window_size ({window_size})."
        )

    # ── STFT ──────────────────────────────────────────────────────────────────
    # scipy.signal.stft handles edge padding, windowing (Hann by default),
    # and efficient batched FFT.  nperseg = window_size sets both the FFT
    # length and the Hann window length.
    freqs, _, Zxx = scipy.signal.stft(
        x,
        fs=fs,
        window="hann",
        nperseg=window_size,
        noverlap=window_size - hop_size,
        boundary=None,        # no padding — avoids artefacts at signal edges
        padded=False,
    )
    # Zxx shape: [n_fft_bins, n_frames]
    # Power spectrum: magnitude squared
    power_stft = np.abs(Zxx) ** 2   # shape: [n_fft_bins, n_frames]

    # ── Log-frequency binning ──────────────────────────────────────────────────
    # Build n_log_bins edges spaced logarithmically from the first non-DC
    # frequency up to Nyquist (fs/2).  The DC bin (0 Hz) is excluded because
    # log(0) is undefined and the DC component dominates biological signals.
    f_min = freqs[freqs > 0][0]   # lowest non-DC frequency
    f_max = freqs[-1]             # Nyquist

    # Log-spaced bin edges: n_log_bins+1 edges → n_log_bins intervals
    bin_edges = np.logspace(np.log10(f_min), np.log10(f_max), n_log_bins + 1)
    bin_freqs = np.sqrt(bin_edges[:-1] * bin_edges[1:])  # geometric centre

    n_frames    = power_stft.shape[1]
    log_power   = np.zeros((n_frames, n_log_bins), dtype=np.float64)

    for b in range(n_log_bins):
        mask = (freqs >= bin_edges[b]) & (freqs < bin_edges[b + 1])
        if mask.any():
            # Mean power across all FFT bins that fall in this log band,
            # then store per frame.  Transpose: power_stft is [bins, frames].
            log_power[:, b] = power_stft[mask, :].mean(axis=0)

    if return_2d:
        return bin_freqs, log_power                 # [n_frames, n_log_bins]
    else:
        return bin_freqs, log_power.mean(axis=0)    # [n_log_bins]


def plot_freq_histogram(x, categories, fs, window_samples, freq_bin_width=None, log_scale=False, skip_dc=True):
    """
    Plot a histogram comparing average frequency power distribution across data categories.

    Parameters
    ----------
    x : np.ndarray
        Raw time-series signal.
    categories : dict[str, np.ndarray]
        Mapping of category name -> array of start sample indices.
        e.g. {"interesting": interesting, "notinteresting": notinteresting}
    fs : float
        Sampling frequency in Hz.
    window_samples : int
        Number of samples per window.
    freq_bin_width : float, optional
        Width of frequency bins in Hz. If None, uses raw FFT resolution.
        With fs=1 Hz and 10-min windows there are ~300 tiny bins — passing
        e.g. 0.02 collapses them into ~25 readable bars.
    log_scale : bool
        If True, plot y-axis on a log scale.
    skip_dc : bool
        If True (default), drop the 0 Hz bin. The DC component (signal mean)
        is almost always orders of magnitude larger than all other frequencies
        and will dominate the plot, making everything else invisible.
    """
    def avg_power_spectrum(start_indices):
        spectra = []
        for idx in start_indices:
            window = x[int(idx):int(idx) + window_samples]
            if len(window) < window_samples:
                continue
            fft_vals = np.fft.rfft(window)
            spectra.append(np.abs(fft_vals) ** 2)
        if not spectra:
            return None, None
        freqs = np.fft.rfftfreq(window_samples, d=1.0 / fs)
        return freqs, np.mean(spectra, axis=0)

    # Compute spectra for all categories
    results = {}
    for name, indices in categories.items():
        freqs, power = avg_power_spectrum(indices)
        if freqs is None:
            print(f"Warning: no valid windows for category '{name}', skipping.")
            continue
        results[name] = (freqs, power)

    if not results:
        print("No data to plot.")
        return

    ref_freqs = next(iter(results.values()))[0]

    # Drop DC bin (index 0, freq=0 Hz) — it dwarfs all other frequencies
    dc_mask = ref_freqs > 0 if skip_dc else np.ones(len(ref_freqs), dtype=bool)
    ref_freqs = ref_freqs[dc_mask]
    results = {name: (freqs[dc_mask], power[dc_mask]) for name, (freqs, power) in results.items()}

    # Optionally re-bin into wider frequency bins
    if freq_bin_width is not None:
        bin_edges = np.arange(ref_freqs[0], ref_freqs[-1] + freq_bin_width, freq_bin_width)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        rebinned = {}
        for name, (freqs, power) in results.items():
            binned = np.array([
                power[(freqs >= bin_edges[j]) & (freqs < bin_edges[j + 1])].mean()
                if np.any((freqs >= bin_edges[j]) & (freqs < bin_edges[j + 1])) else 0.0
                for j in range(len(bin_edges) - 1)
            ])
            rebinned[name] = binned
        plot_freqs = bin_centers
        plot_powers = rebinned
        bar_width = freq_bin_width * 0.8 / len(results)
    else:
        plot_freqs = ref_freqs
        plot_powers = {name: power for name, (_, power) in results.items()}
        raw_res = ref_freqs[1] - ref_freqs[0] if len(ref_freqs) > 1 else 1.0
        bar_width = raw_res * 0.8 / len(results)

    # Plot
    colors = ["steelblue", "tomato", "mediumseagreen", "darkorange", "mediumpurple"]
    n = len(results)
    offsets = np.linspace(-(n - 1) / 2, (n - 1) / 2, n) * bar_width

    fig, ax = py.subplots(figsize=(13, 5))
    for (name, _), offset, color in zip(results.items(), offsets, colors):
        count = len(categories[name])
        ax.bar(
            plot_freqs + offset,
            plot_powers[name],
            width=bar_width,
            label=f"{name} (n={count})",
            alpha=0.8,
            color=color,
        )

    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Average Power" + (" (log)" if log_scale else ""))
    ax.set_title("Average Frequency Distribution by Category")
    if log_scale:
        ax.set_yscale("log")
    ax.legend()
    py.tight_layout()
    py.show()

# ── Frequency-selective filters ───────────────────────────────────────────────
# Factory functions — each returns a fn(w) suitable for add_computed_column.
# All use zero-phase (forward-backward) Butterworth filtering via filtfilt,
# which avoids phase distortion that would shift spike timing.
#
# Example usage:
#   wm.add_computed_column("bandpass_0.01_0.1", make_bandpass_filter(FS, 0.01, 0.1))
#   wm.add_computed_column("lowpass_0.05",      make_lowpass_filter(FS, 0.05))


def make_bandpass_filter(fs, low_hz, high_hz, order=4):
    """
    Factory: returns fn(w) that applies a zero-phase Butterworth bandpass filter.

    Parameters
    ----------
    fs       : float  Sampling frequency (Hz).
    low_hz   : float  Lower cutoff frequency (Hz).
    high_hz  : float  Upper cutoff frequency (Hz).
    order    : int    Filter order (default 4).
    """
    from scipy.signal import butter, filtfilt
    nyq = fs / 2.0
    b, a = butter(order, [low_hz / nyq, high_hz / nyq], btype="band")
    def _bandpass(w):
        return filtfilt(b, a, w.astype(float))
    return _bandpass


def make_lowpass_filter(fs, cutoff_hz, order=4):
    """
    Factory: returns fn(w) that applies a zero-phase Butterworth lowpass filter.

    Parameters
    ----------
    fs         : float  Sampling frequency (Hz).
    cutoff_hz  : float  Cutoff frequency (Hz).
    order      : int    Filter order (default 4).
    """
    from scipy.signal import butter, filtfilt
    nyq = fs / 2.0
    b, a = butter(order, cutoff_hz / nyq, btype="low")
    def _lowpass(w):
        return filtfilt(b, a, w.astype(float))
    return _lowpass


def make_highpass_filter(fs, cutoff_hz, order=4):
    """
    Factory: returns fn(w) that applies a zero-phase Butterworth highpass filter.

    Parameters
    ----------
    fs         : float  Sampling frequency (Hz).
    cutoff_hz  : float  Cutoff frequency (Hz).
    order      : int    Filter order (default 4).
    """
    from scipy.signal import butter, filtfilt
    nyq = fs / 2.0
    b, a = butter(order, cutoff_hz / nyq, btype="high")
    def _highpass(w):
        return filtfilt(b, a, w.astype(float))
    return _highpass

