"""
detection_freq_stft.py
=========================
Adapter for `Working.Detection.analysis.freq_analysis.stft_log_spectrum`.

No plotting hook: the only plot function in `freq_analysis.py`
(`plot_freq_histogram`) compares multiple label categories at once, not a
single run's output — doesn't fit the single-run `(x, t, result) -> Figure`
shape, so `plot=None` here rather than forcing a fit.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Detection.analysis.freq_analysis import stft_log_spectrum


def _run(x, t, fs, window_size=300, hop_size=150, n_log_bins=64):
    bin_freqs, power = stft_log_spectrum(
        x, fs=fs, window_size=window_size, hop_size=hop_size,
        n_log_bins=n_log_bins, return_2d=False,
    )
    return AdapterResult(
        output_kind="encoding", encoding=power,
        meta={"bin_freqs": bin_freqs},
    )


SPEC = register(AdapterSpec(
    name="detection.freq_stft",
    display_name="STFT log-frequency spectrum",
    stage="detection",
    params=[
        ParamSpec("window_size", int, 300, "STFT window length (samples)", min=2),
        ParamSpec("hop_size", int, 150, "Hop between successive windows (samples)", min=1),
        ParamSpec("n_log_bins", int, 64, "Number of log-spaced output frequency bins", min=2, max=512),
    ],
    run=_run,
    output_kind="encoding",
    input_kind="signal",
    plot=None,
    description=(
        "STFT power spectrum aggregated into logarithmically spaced frequency "
        "bins (finer resolution at low frequencies, coarser at high)."
    ),
))
