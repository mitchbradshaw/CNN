"""
preprocessing_bandpass.py
===========================
Adapter for `Working.Detection.analysis.freq_analysis.make_bandpass_filter`.
See `preprocessing_lowpass.py` for the note on why this factory lives under
`Detection/analysis/` rather than a `Preprocessing/` module.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Detection.analysis.freq_analysis import make_bandpass_filter


def _run(x, t, fs, low_hz=0.01, high_hz=0.1, order=4):
    if low_hz >= high_hz:
        raise ValueError(f"low_hz ({low_hz}) must be < high_hz ({high_hz})")
    filt = make_bandpass_filter(fs, low_hz, high_hz, order=order)
    x_filtered = filt(x)
    return AdapterResult(output_kind="signal", x=x_filtered, t=t)


def _plot(x, t, result, low_hz=0.01, high_hz=0.1, order=4):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(t, x, linewidth=0.5, color="#999999", label="original")
    ax.plot(result.t, result.x, linewidth=0.8, color="mediumseagreen", label="filtered")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.set_title(f"Bandpass filter  [{low_hz:g}, {high_hz:g}]Hz  order={order}")
    ax.legend()
    fig.tight_layout()
    return fig


SPEC = register(AdapterSpec(
    name="preprocessing.bandpass",
    display_name="Bandpass filter (Butterworth)",
    stage="preprocessing",
    params=[
        ParamSpec("low_hz", float, 0.01, "Lower cutoff frequency (Hz)", min=1e-6),
        ParamSpec("high_hz", float, 0.1, "Upper cutoff frequency (Hz)", min=1e-6),
        ParamSpec("order", int, 4, "Filter order", min=1, max=10),
    ],
    run=_run,
    output_kind="signal",
    plot=_plot,
    description=(
        "Zero-phase Butterworth bandpass filter (scipy filtfilt) — keeps only "
        "the frequency band between low_hz and high_hz."
    ),
))
