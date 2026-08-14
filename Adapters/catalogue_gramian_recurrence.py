"""
catalogue_gramian_recurrence.py
==================================
Adapter for `Working.Catalogue.gramian.gramian_calc.compute_recurrence`.

*** O(n^2) GUARD ***: `compute_recurrence` calls `cdist(Y, Y)` where `Y` has
roughly `n - (m-1)*tau` rows — an n x n distance matrix, same worst case as
GASF/GADF. `max_span_samples=5000` caps this at ~200 MB. See
`catalogue_gramian_gasf.py` for the shared reasoning and the plot-hook note.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Catalogue.gramian.gramian_calc import compute_recurrence, plot_gramian_suite

MAX_SPAN_SAMPLES = 5000


def _run(x, t, fs, m=3, tau=4):
    return AdapterResult(output_kind="encoding", encoding=compute_recurrence(x, m=m, tau=tau))


def _plot(x, t, result, m=3, tau=4):
    return plot_gramian_suite(x, t, m=m, tau=tau)


SPEC = register(AdapterSpec(
    name="catalogue.gramian_recurrence",
    display_name="Recurrence plot",
    stage="catalogue",
    params=[
        ParamSpec("m", int, 3, "Time-delay embedding dimension", min=1, max=20),
        ParamSpec("tau", int, 4, "Time-delay embedding lag (samples)", min=1),
    ],
    run=_run,
    output_kind="encoding",
    plot=_plot,
    max_span_samples=MAX_SPAN_SAMPLES,
    description=(
        f"Recurrence plot via time-delay embedding + pairwise distance. "
        f"O(n^2) — capped at {MAX_SPAN_SAMPLES} samples."
    ),
))
