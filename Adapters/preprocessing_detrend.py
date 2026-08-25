"""
preprocessing_detrend.py
==========================
Adapter for `Working.Preprocessing.detrend.make_detrend_filter`. Added
2026-08: Stage 3's benchmark found preprocessing dominated every matcher
choice for the SAX encoding view (recall 0.22 raw vs 0.85 detrended), so
it needed to be reachable from the UI as its own step, not baked into the
SAX adapter itself — see `Adapters._sax_common` / the run panel's
`_on_run` for how "Preprocessing (applied first)" prepends this as a real
recipe step ahead of a SAX run, so the recipe hash (and therefore Run
History) reflects it honestly.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Preprocessing.detrend import make_detrend_filter
from Working.types import Signal


def _run(x, t, fs, mode="rolling_mean", window_s=600.0):
    filt = make_detrend_filter(fs, mode=mode, window_s=window_s)
    x_detrended = filt(x)
    return AdapterResult(
        output_kind="signal", x=x_detrended, t=t,
        value=Signal(x=x_detrended, fs=fs),
    )


def _plot(x, t, result, mode="rolling_mean", window_s=600.0):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(t, x, linewidth=0.5, color="#999999", label="original")
    ax.plot(result.t, result.x, linewidth=0.8, color="mediumseagreen", label="detrended")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")
    ax.set_title(f"Detrend  mode={mode}  window={window_s:g}s")
    ax.legend()
    fig.tight_layout()
    return fig


SPEC = register(AdapterSpec(
    name="preprocessing.detrend",
    display_name="Detrend",
    stage="preprocessing",
    params=[
        ParamSpec("mode", str, "rolling_mean", "Detrending method", choices=[
            "rolling_mean", "rolling_z", "linear",
        ]),
        ParamSpec("window_s", float, 600.0,
                  "Rolling-window width in seconds (ignored for mode='linear')", min=1.0),
    ],
    run=_run,
    input_kind="signal",
    output_kind="signal",
    plot=_plot,
    description=(
        "Removes a slow trend — a centred rolling mean (optionally "
        "normalised to a rolling z-score), or a single least-squares "
        "line over the whole span. The single biggest lever on SAX "
        "encoding quality for slowly-drifting channels."
    ),
))
