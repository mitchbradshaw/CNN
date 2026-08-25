"""
catalogue_gramian_gadf.py
============================
Adapter for `Working.Catalogue.gramian.gramian_calc.compute_GADF`. See
`catalogue_gramian_gasf.py` for the O(n^2) guard and plot-hook notes —
identical reasoning, GADF variant (sine of the angular *difference*
instead of cosine of the sum).
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Catalogue.gramian.gramian_calc import compute_GADF, plot_gramian_suite

MAX_SPAN_SAMPLES = 5000


def _run(x, t, fs):
    return AdapterResult(output_kind="encoding", encoding=compute_GADF(x))


def _plot(x, t, result):
    return plot_gramian_suite(x, t)


SPEC = register(AdapterSpec(
    name="catalogue.gramian_gadf",
    display_name="Gramian Angular Difference Field (GADF)",
    stage="catalogue",
    params=[],
    run=_run,
    output_kind="encoding",
    input_kind="signal",
    plot=_plot,
    max_span_samples=MAX_SPAN_SAMPLES,
    description=(
        f"Image encoding via polar transform + sine outer difference: "
        f"G[i,j] = sin(phi_i - phi_j). O(n^2) — capped at {MAX_SPAN_SAMPLES} samples."
    ),
))
