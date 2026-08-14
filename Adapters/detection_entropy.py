"""
detection_entropy.py
=======================
Adapter for the entropy measures in
`Working.Detection.analysis.entropy_analysis` — one adapter covering all
six, selected via a `measure` choice parameter, rather than six near-
identical adapter files.

Note on the wrapped functions: `entropy_analysis.py`'s only *public*
function is `plot_entropy_histograms`, a multi-category comparison plot
that doesn't fit a single-run adapter. The actual computations are the
leading-underscore "private" functions (`_shannon_entropy`, etc.) — the
only real entry points for a single window, imported here despite the
underscore (flagged during the Part 1 survey as a minor interface smell,
not a bug worth changing `Working/` for).

Each measure takes a different subset of extra parameters (`n_bins` for
shannon, `m`/`r` for approximate/sample, `order` for permutation/svd,
nothing extra for spectral). All are exposed together rather than
conditionally, since `ParamSpec` doesn't model "parameter X only applies
when measure=Y" — the irrelevant ones are simply ignored for a given choice.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Detection.analysis.entropy_analysis import (
    _approximate_entropy,
    _permutation_entropy,
    _sample_entropy,
    _shannon_entropy,
    _spectral_entropy,
    _svd_entropy,
)

_MEASURES = {
    "shannon": lambda w, n_bins, m, r, order: _shannon_entropy(w, n_bins=n_bins),
    "approximate": lambda w, n_bins, m, r, order: _approximate_entropy(w, m=m, r=r),
    "sample": lambda w, n_bins, m, r, order: _sample_entropy(w, m=m, r=r),
    "spectral": lambda w, n_bins, m, r, order: _spectral_entropy(w),
    "permutation": lambda w, n_bins, m, r, order: _permutation_entropy(w, order=order),
    "svd": lambda w, n_bins, m, r, order: _svd_entropy(w, order=order),
}


def _run(x, t, fs, measure="shannon", n_bins=50, m=2, r=0.2, order=3):
    value = _MEASURES[measure](x, n_bins, m, r, order)
    return AdapterResult(output_kind="encoding", encoding=float(value), meta={"measure": measure})


SPEC = register(AdapterSpec(
    name="detection.entropy",
    display_name="Entropy measure",
    stage="detection",
    params=[
        ParamSpec("measure", str, "shannon", "Entropy measure",
                  choices=list(_MEASURES)),
        ParamSpec("n_bins", int, 50, "Histogram bins (shannon only)", min=2),
        ParamSpec("m", int, 2, "Embedding dimension (approximate/sample only)", min=1),
        ParamSpec("r", float, 0.2, "Tolerance, as a fraction of signal std (approximate/sample only)", min=0.0),
        ParamSpec("order", int, 3, "Embedding order (permutation/svd only)", min=1),
    ],
    run=_run,
    output_kind="encoding",
    plot=None,
    description=(
        "One of six entropy measures (shannon, approximate, sample, spectral, "
        "permutation, svd) computed on the span as a single scalar."
    ),
))
