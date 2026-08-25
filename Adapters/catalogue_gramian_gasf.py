"""
catalogue_gramian_gasf.py
============================
Adapter for `Working.Catalogue.gramian.gramian_calc.compute_GASF`.

*** O(n^2) GUARD ***: GASF is `cos(outer(phi, phi))` — an n x n matrix for
an n-sample span. `max_span_samples=5000` below caps the worst case at
5000^2 * 8 bytes = 200 MB; `Working.execution.execute_recipe` checks this
declared limit against the span length *before* calling `run` and refuses
with a clear message rather than hanging or OOM-ing on a whole-channel span.

`plot_gramian_suite` (the only plotting function in `gramian_calc.py`)
always renders all four encodings (GASF/GADF/recurrence/fusion) together —
used as-is here rather than writing a GASF-only variant, since seeing the
other three alongside is genuinely useful context, not a mismatch.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Catalogue.gramian.gramian_calc import compute_GASF, plot_gramian_suite

MAX_SPAN_SAMPLES = 5000


def _run(x, t, fs):
    return AdapterResult(output_kind="encoding", encoding=compute_GASF(x))


def _plot(x, t, result):
    return plot_gramian_suite(x, t)


SPEC = register(AdapterSpec(
    name="catalogue.gramian_gasf",
    display_name="Gramian Angular Summation Field (GASF)",
    stage="catalogue",
    params=[],
    run=_run,
    output_kind="encoding",
    input_kind="signal",
    plot=_plot,
    max_span_samples=MAX_SPAN_SAMPLES,
    description=(
        f"Image encoding via polar transform + cosine outer sum: G[i,j] = "
        f"cos(phi_i + phi_j). O(n^2) — capped at {MAX_SPAN_SAMPLES} samples."
    ),
))
