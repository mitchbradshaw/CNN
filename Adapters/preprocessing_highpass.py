"""
preprocessing_highpass.py
===========================
Adapter for `Working.Detection.analysis.freq_analysis.make_highpass_filter`.
See `preprocessing_lowpass.py` for the note on why this factory lives under
`Detection/analysis/` rather than a `Preprocessing/` module.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Detection.analysis.freq_analysis import make_highpass_filter
from Working.types import Signal


def _run(x, t, fs, cutoff_hz=0.01, order=4):
    filt = make_highpass_filter(fs, cutoff_hz, order=order)
    x_filtered = filt(x)
    return AdapterResult(
        output_kind="signal",
        value=Signal(x=x_filtered, fs=fs),
    )


def _plot(x, t, result, cutoff_hz=0.01, order=4):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(t, x, linewidth=0.5, color="#999999", label="original")
    ax.plot(t, result.value.x, linewidth=0.8, color="tomato", label="filtered")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.set_title(f"Highpass filter  cutoff={cutoff_hz:g}Hz  order={order}")
    ax.legend()
    fig.tight_layout()
    return fig


SPEC = register(AdapterSpec(
    name="preprocessing.highpass",
    display_name="Highpass filter (Butterworth)",
    stage="preprocessing",
    params=[
        ParamSpec("cutoff_hz", float, 0.01, "Cutoff frequency (Hz)", min=1e-6),
        ParamSpec("order", int, 4, "Filter order", min=1, max=10),
    ],
    run=_run,
    input_kind="signal",
    output_kind="signal",
    plot=_plot,
    description=(
        "Zero-phase Butterworth highpass filter (scipy filtfilt) — attenuates "
        "everything below the cutoff frequency (removes slow drift)."
    ),
))
