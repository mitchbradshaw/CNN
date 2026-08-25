"""
detection_sax_dsax.py
========================
Adapter for `Working.Detection.sax.dsax_python.dsax.dsax` — dSAX encodes
each PAA-aligned segment by its TREND (the rise across the segment)
instead of its mean, into a zero-anchored DOWN/SAME/UP alphabet quantised
by the same Epanechnikov-KDE + Lloyd-Max machinery pSAX uses. Segmentation
is resolved through the shared `segment_plan` exactly as in
`detection_sax_csax.py`/`detection_sax_psax.py`, so all three encoders can
never disagree about what "20 seconds per symbol" means.

`plot` points at `plot_trend_encoding`, NOT the shared
`plot_encoding_matplotlib`, and that is not an oversight. The shared
renderer draws `cutlines_raw` as horizontal amplitude bands behind
`paa_raw`; dSAX's cutlines are a threshold on a RISE, in amplitude per
segment, while `paa_raw` is a level. Drawn on one y axis they are two
quantities of different dimension, and on a real fungal channel (tens of
mV of standing potential against sub-mV excursions) the delta cutlines
collapse to a sliver near zero — a figure that looks like a dSAX bug and
is in fact a category error. The interactive encoding view resolves the
same problem at runtime through `UI.plots.cutline_domain`, which reads the
`cutline_domain` key this encoder declares in its `details`.

See `Working/Detection/sax/dsax_python/IMPLEMENTATION_NOTES.md` for the
method, its prior art, and its measured limitations — in particular 6.3
(MSE-optimal Lloyd-Max is not a noise floor) and 7.3 (untreated drift
swamps a trend encoding), both of which this adapter surfaces through
`delta_diagnostic_rows` below.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.types import Encoding
from Adapters._sax_common import derive_sax_rows, recommend_sax_params, segment_plan

from Working.Detection.sax.dsax_python.dsax import (
    THRESHOLD_MODES, dsax, plot_trend_encoding, trend_diagnostic_rows,
)
from Working.Detection.sax.dsax_python.trend_estimators import TREND_ESTIMATORS

# ── Noise-floor estimation budget (consumed by the run panel's
# "Estimate noise floor" button, defined here rather than in
# `Working/config.py` so every dSAX-specific tuning constant lives beside
# the adapter that owns it and no file outside this feature had to be
# edited to add them).
#
# `surrogate_same_halfwidth` costs `n_surrogates` full-length FFTs. Rather
# than SUBSAMPLE a long span to bound that — which would change the
# magnitude spectrum, and the spectrum IS the null hypothesis, so the
# answer would be quietly wrong — the surrogate COUNT is traded off
# against span length against a fixed total-samples budget. The pooled
# quantile is taken over `n_surrogates x n_segments` deltas, and a long
# span already has many segments, so 8 surrogates of a 2.6M-sample span
# pools far more deltas than 50 surrogates of a 6k one.
NOISE_FLOOR_SAMPLE_BUDGET = 10_000_000
NOISE_FLOOR_MIN_SURROGATES = 8
NOISE_FLOOR_MAX_SURROGATES = 50
# Hard ceiling. At 5M samples even the 8-surrogate floor is ~8 rfft's of
# 5M plus the OLS pass — a few seconds on a worker thread, which is the
# most that is reasonable to make someone wait for a diagnostic.
NOISE_FLOOR_MAX_SAMPLES = 5_000_000
# Above this the learned SAME band is materially narrower than the noise
# floor. 1.5x is where the difference stops being attributable to the
# arbitrariness of alpha and starts changing what the encoding means.
NOISE_FLOOR_RATIO_ALERT = 1.5


def noise_floor_surrogate_count(n_samples):
    """How many surrogates to draw for a span of `n_samples`. See the
    budget comment above for why the count flexes instead of the span."""
    n = max(int(n_samples), 1)
    return int(min(NOISE_FLOOR_MAX_SURROGATES,
                   max(NOISE_FLOOR_MIN_SURROGATES, NOISE_FLOOR_SAMPLE_BUDGET // n)))


def delta_diagnostic_rows(symbols, details):
    """Re-exported from the dsax module so the UI has ONE import for
    everything dSAX-specific it needs, while the computation itself stays
    in `Working/` where a headless SLURM job can print the same warnings
    without importing the adapter layer."""
    return trend_diagnostic_rows(symbols, details)


def _run(x, t, fs, segment_mode="seconds_per_symbol", seconds_per_symbol=20.0,
         samples_per_symbol=20, target_symbol_count=30, dim_ratio=0.05,
         alphabet_size=3, trend_estimator="ols_slope", threshold_mode="learned",
         endpoint_k=1, absolute_threshold=0.0, same_fraction=0.5,
         min_same_halfwidth=0.0, force_symmetric=True, normalize=True):
    params = {
        "segment_mode": segment_mode, "seconds_per_symbol": seconds_per_symbol,
        "samples_per_symbol": samples_per_symbol, "target_symbol_count": target_symbol_count,
        "dim_ratio": dim_ratio,
    }
    plan = segment_plan(segment_mode, params, fs, len(x))
    # `ParamSpec` has no nullable numeric type, and a recipe hash must be
    # JSON-serialisable, so the two optional thresholds are exposed as
    # floats with 0.0 meaning "unset" and translated back to None here.
    # 0.0 is a safe sentinel for both: a zero absolute_threshold would put
    # both cutlines on the origin (rejected by `dsax` anyway) and a zero
    # min_same_halfwidth is a no-op floor, so neither has a meaningful
    # zero value that this steals.
    symbols, details = dsax(
        x, training_len=len(x), dim_ratio=plan["dim_ratio_for_call"],
        alphabet_size=alphabet_size,
        trend_estimator=trend_estimator, threshold_mode=threshold_mode,
        endpoint_k=endpoint_k,
        absolute_threshold=(absolute_threshold if absolute_threshold > 0 else None),
        same_fraction=same_fraction,
        min_same_halfwidth=(min_same_halfwidth if min_same_halfwidth > 0 else None),
        force_symmetric=force_symmetric, normalize=normalize, return_details=True,
    )
    details["segment_plan"] = plan
    # See `detection_sax_psax._run`: `x`/`t` are populated even though
    # output_kind="encoding", because the encoding view needs the exact
    # (possibly preprocessed) array that was actually encoded.
        # The EXACT array that got encoded goes in `meta`, not into a carrier
    # field on the result: it already reflects any upstream preprocessing
    # step the recipe chained in ahead of this one, and the UI's encoding
    # view (Part 6 3b) needs precisely it to draw panel 1 and align the
    # PAA/quantisation panels against it. Recovering it any other way would
    # mean the UI re-deriving which preprocessing ran, from outside the
    # recipe machinery that already knows. `meta` is the right home —
    # `detection.matrix_profile` already carries its `mp`/`mpi`/`t_mp`
    # arrays there — and it keeps `value` the single typed payload.
    return AdapterResult(
        output_kind="encoding",
        value=Encoding(values=symbols, kind="symbolic"),
        meta={"details": details, "encoded_x": x, "encoded_t": t},
    )


def _recommend(x, t, fs):
    return recommend_sax_params(x, t, fs)


def _derive(x, t, fs, params):
    return derive_sax_rows(x, t, fs, params)


def _plot(x, t, result, **params):
    # NOT `plot_encoding_matplotlib` — see the module docstring.
    return plot_trend_encoding(x, t, result.value.values, result.meta["details"])


SPEC = register(AdapterSpec(
    name="detection.sax_dsax",
    display_name="dSAX trend symbolisation",
    stage="detection",
    params=[
        ParamSpec("segment_mode", str, "seconds_per_symbol",
                  "Which control below sets the segment length", choices=[
                      "seconds_per_symbol", "samples_per_symbol",
                      "target_symbol_count", "dim_ratio",
                  ]),
        ParamSpec("seconds_per_symbol", float, 20.0,
                  "Live when segment_mode='seconds_per_symbol'", min=1e-6),
        ParamSpec("samples_per_symbol", int, 20,
                  "Live when segment_mode='samples_per_symbol'", min=2),
        ParamSpec("target_symbol_count", int, 30,
                  "Live when segment_mode='target_symbol_count'", min=2),
        ParamSpec("dim_ratio", float, 0.05,
                  "Live when segment_mode='dim_ratio' — the escape hatch", min=1e-6, max=1.0),
        ParamSpec("alphabet_size", int, 3,
                  "Number of trend symbols; 3 = DOWN/SAME/UP. Odd sizes keep a SAME bin",
                  min=2, max=9),
        ParamSpec("trend_estimator", str, "ols_slope",
                  "How each segment's rise is measured (all in rise-per-segment units)",
                  choices=list(TREND_ESTIMATORS)),
        ParamSpec("threshold_mode", str, "learned",
                  "How the cutlines are chosen", choices=list(THRESHOLD_MODES)),
        ParamSpec("endpoint_k", int, 1,
                  "Median window for trend_estimator='robust_endpoints'", min=1),
        ParamSpec("absolute_threshold", float, 0.0,
                  "Required by threshold_mode='absolute': rise per segment, raw units. "
                  "0 = unset", min=0.0),
        ParamSpec("same_fraction", float, 0.5,
                  "Target SAME occupancy for threshold_mode='quantile' at alphabet_size=3",
                  min=0.01, max=0.99),
        ParamSpec("min_same_halfwidth", float, 0.0,
                  "Floor on the SAME band half-width, in the working delta domain "
                  "(use 'Estimate noise floor' to measure one). 0 = unset", min=0.0),
        ParamSpec("force_symmetric", bool, True,
                  "Fold the cutlines about zero so SAME is anchored at 'no change'"),
        ParamSpec("normalize", bool, True, "Z-normalise the span before encoding"),
    ],
    run=_run,
    output_kind="encoding",
    input_kind="signal",
    plot=_plot,
    description=(
        "dSAX: encodes each PAA-aligned segment by its TREND (rise across the "
        "segment) rather than its mean, into a zero-anchored DOWN/SAME/UP "
        "alphabet quantised by pSAX's KDE + Lloyd-Max machinery. Makes "
        "morphology regex-searchable over the symbol string."
    ),
    recommend=_recommend,
    derive=_derive,
))
