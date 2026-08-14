"""
preprocessing_lowpass.py
=========================
Adapter for `Working.Detection.analysis.freq_analysis.make_lowpass_filter`.

Note on placement: this function lives under `Detection/analysis/`, not
anywhere under `Preprocessing/` — there is no resampling or detrending
function anywhere in the repo, and filtering (smoothing) turned out to be
the only preprocessing-shaped operation that exists, misfiled next to the
frequency-analysis code. Flagged during the Part 1 module survey; not
moved here (moving `Working/` code wasn't asked for), just wrapped where it is.

`make_lowpass_filter` is a factory — it returns `fn(w)`, not a direct
`(x, t, params) -> (x, t)` call. That adaptation happens entirely here.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Detection.analysis.freq_analysis import make_lowpass_filter


def _run(x, t, fs, cutoff_hz=0.05, order=4):
    filt = make_lowpass_filter(fs, cutoff_hz, order=order)
    x_filtered = filt(x)
    return AdapterResult(output_kind="signal", x=x_filtered, t=t)


def _plot(x, t, result, cutoff_hz=0.05, order=4):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(t, x, linewidth=0.5, color="#999999", label="original")
    ax.plot(result.t, result.x, linewidth=0.8, color="steelblue", label="filtered")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.set_title(f"Lowpass filter  cutoff={cutoff_hz:g}Hz  order={order}")
    ax.legend()
    fig.tight_layout()
    return fig


SPEC = register(AdapterSpec(
    name="preprocessing.lowpass",
    display_name="Lowpass filter (Butterworth)",
    stage="preprocessing",
    params=[
        ParamSpec("cutoff_hz", float, 0.05, "Cutoff frequency (Hz)", min=1e-6),
        ParamSpec("order", int, 4, "Filter order", min=1, max=10),
    ],
    run=_run,
    output_kind="signal",
    plot=_plot,
    description=(
        "Zero-phase Butterworth lowpass filter (scipy filtfilt) — attenuates "
        "everything above the cutoff frequency."
    ),
))
