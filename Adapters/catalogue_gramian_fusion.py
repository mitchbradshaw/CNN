"""
catalogue_gramian_fusion.py
==============================
Adapter for `Working.Catalogue.gramian.gramian_calc.compute_fusion` — the
RGB combination of GASF (R), GADF (G), and recurrence (B).

*** O(n^2) GUARD ***: same reasoning as the other three Gramian adapters —
`compute_fusion` computes all three underlying n x n matrices internally.
`max_span_samples=5000` caps the worst case at ~200 MB per channel, ~600 MB
for the stacked RGB array.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Catalogue.gramian.gramian_calc import compute_fusion, plot_gramian_suite

MAX_SPAN_SAMPLES = 5000


def _run(x, t, fs, m=3, tau=4):
    return AdapterResult(output_kind="encoding", encoding=compute_fusion(x, m=m, tau=tau))


def _plot(x, t, result, m=3, tau=4):
    return plot_gramian_suite(x, t, m=m, tau=tau)


SPEC = register(AdapterSpec(
    name="catalogue.gramian_fusion",
    display_name="Gramian RGB fusion (GASF+GADF+recurrence)",
    stage="catalogue",
    params=[
        ParamSpec("m", int, 3, "Time-delay embedding dimension (recurrence component)", min=1, max=20),
        ParamSpec("tau", int, 4, "Time-delay embedding lag (recurrence component, samples)", min=1),
    ],
    run=_run,
    output_kind="encoding",
    input_kind="signal",
    plot=_plot,
    max_span_samples=MAX_SPAN_SAMPLES,
    description=(
        f"RGB image: GASF (R), GADF (G), recurrence (B), each scaled to [0,1]. "
        f"O(n^2) — capped at {MAX_SPAN_SAMPLES} samples."
    ),
))
