"""
detection_sax_psax.py
========================
Adapter for `Working.Detection.sax.psax_python.psax.psax`, called
directly (not through `make_psax_encoder`, which hides `return_details`)
— see `detection_sax_csax.py` for the shared reasoning on the parameter
rewrite (Part 2, 2026-08) and why `segment_mode` replaces `dim_ratio` as
the primary control. Unlike cSAX, pSAX DOES take an explicit
`alphabet_size` (Lloyd-Max codebook size), which it always achieves
exactly (no fallback path).
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Adapters._sax_common import derive_sax_rows, plot_encoding_matplotlib, recommend_sax_params, segment_plan
from Working.Detection.sax.psax_python.psax import psax


def _run(x, t, fs, segment_mode="seconds_per_symbol", seconds_per_symbol=20.0,
         samples_per_symbol=20, target_symbol_count=30, dim_ratio=0.05,
         alphabet_size=8, normalize=True):
    params = {
        "segment_mode": segment_mode, "seconds_per_symbol": seconds_per_symbol,
        "samples_per_symbol": samples_per_symbol, "target_symbol_count": target_symbol_count,
        "dim_ratio": dim_ratio,
    }
    plan = segment_plan(segment_mode, params, fs, len(x))
    symbols, details = psax(
        x, training_len=len(x), dim_ratio=plan["dim_ratio_for_call"],
        alphabet_size=alphabet_size, normalize=normalize, return_details=True,
    )
    details["segment_plan"] = plan
    # See `detection_sax_csax._run`'s comment: `x`/`t` are populated even
    # though output_kind="encoding" — the UI's encoding view (Part 6 3b)
    # needs the exact (possibly-preprocessed) array that got encoded.
    return AdapterResult(output_kind="encoding", x=x, t=t, encoding=symbols, meta={"details": details})


def _recommend(x, t, fs):
    return recommend_sax_params(x, t, fs)


def _derive(x, t, fs, params):
    return derive_sax_rows(x, t, fs, params)


def _plot(x, t, result, **params):
    # See `Adapters.detection_sax_csax._plot` — identical reasoning.
    return plot_encoding_matplotlib(x, t, result.encoding, result.meta["details"])


SPEC = register(AdapterSpec(
    name="detection.sax_psax",
    display_name="pSAX symbolisation",
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
                  "Live when segment_mode='samples_per_symbol'", min=1),
        ParamSpec("target_symbol_count", int, 30,
                  "Live when segment_mode='target_symbol_count'", min=2),
        ParamSpec("dim_ratio", float, 0.05,
                  "Live when segment_mode='dim_ratio' — the escape hatch", min=1e-6, max=1.0),
        ParamSpec("alphabet_size", int, 8, "Number of distinct symbols (Lloyd-Max codebook size)",
                  min=2, max=64),
        ParamSpec("normalize", bool, True, "Z-normalise the span before encoding"),
    ],
    run=_run,
    output_kind="encoding",
    plot=_plot,
    description=(
        "pSAX: data-adaptive quantisation via Epanechnikov KDE + Lloyd-Max "
        "optimisation on the windowed PAA, producing a symbolic sequence."
    ),
    recommend=_recommend,
    derive=_derive,
))
