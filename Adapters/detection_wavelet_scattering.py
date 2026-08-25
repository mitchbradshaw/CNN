"""
detection_wavelet_scattering.py
==================================
Adapter for `Working.Detection.wavelet.scattering_transform.compute_wavelet_scattering`.

`encoding` output kind: `result.Sx` (the coefficient matrix) is what gets
cached/saved; the full `ScatteringResult` (needed for the scalogram plot,
which reads `t_scattering`/`order`/`freq_hz`/etc.) is kept in `meta` rather
than discarded, since `plots.py`'s plot hook needs more than the bare array.

`T` (the averaging scale) is left at kymatio's default (None -> 2**J) —
not exposed as a tunable, since None has a special meaning ParamSpec's
plain numeric range doesn't model cleanly, and the default is rarely
worth overriding independently of J.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Detection.wavelet.scattering_transform import compute_wavelet_scattering
from Working.Detection.wavelet.plot_scattering import plot_scattering_scalogram


def _run(x, t, fs, J=8, Q=8, max_order=2):
    result = compute_wavelet_scattering(x, t, J=J, Q=Q, max_order=max_order)
    return AdapterResult(
        output_kind="encoding", encoding=result.Sx,
        meta={"scattering_result": result,
              "border_effects_flagged": result.border_effects_flagged},
    )


def _plot(x, t, result, J=8, Q=8, max_order=2):
    return plot_scattering_scalogram(result.meta["scattering_result"])


SPEC = register(AdapterSpec(
    name="detection.wavelet_scattering",
    display_name="Wavelet scattering transform",
    stage="detection",
    params=[
        ParamSpec("J", int, 8, "Octaves (scales) in the filter bank", min=1, max=16),
        ParamSpec("Q", int, 8, "Wavelets per octave", min=1, max=32),
        ParamSpec("max_order", int, 2, "Highest scattering order to compute", choices=[1, 2]),
    ],
    run=_run,
    output_kind="encoding",
    input_kind="signal",
    plot=_plot,
    description=(
        "Shift-stable, noise-robust summary of energy across timescales "
        "(kymatio Scattering1D). Requires at least 2**J samples of input."
    ),
))
