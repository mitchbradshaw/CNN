"""
detection_sax_csax.py
========================
Adapter for `Working.Detection.sax.csax_python.csax.csax`, called
directly (not through `make_csax_encoder`, which hides `return_details`)
so the adapter can surface the encoding internals the UI's encoding view
needs (Part 3, 2026-08).

Parameter surface (Part 2, 2026-08 rewrite): `dim_ratio` is no longer the
primary control — see `Adapters._sax_common`'s module docstring for why
and how `segment_mode` resolves to it. cSAX does not take an alphabet
size (Mean-Shift decides it); the realised count is surfaced through
`details["alphabet_size"]` in the run panel's post-run diagnostics
instead of a pre-run control.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Adapters._sax_common import derive_sax_rows, plot_encoding_matplotlib, recommend_sax_params, segment_plan
from Working.Detection.sax.csax_python.csax import csax


def _run(x, t, fs, segment_mode="seconds_per_symbol", seconds_per_symbol=20.0,
         samples_per_symbol=20, target_symbol_count=30, dim_ratio=0.05,
         normalize=True):
    params = {
        "segment_mode": segment_mode, "seconds_per_symbol": seconds_per_symbol,
        "samples_per_symbol": samples_per_symbol, "target_symbol_count": target_symbol_count,
        "dim_ratio": dim_ratio,
    }
    plan = segment_plan(segment_mode, params, fs, len(x))
    symbols, details = csax(
        x, training_len=len(x), dim_ratio=plan["dim_ratio_for_call"],
        normalize=normalize, return_details=True,
    )
    details["segment_plan"] = plan
    # `x`/`t` populated even though output_kind="encoding" (a deliberate,
    # additive deviation from AdapterResult's usual "only the matching
    # kind's fields are populated" convention) — this is the EXACT array
    # that got encoded, already reflecting any upstream preprocessing step
    # the recipe chained in ahead of this one. The UI's encoding view
    # (Part 6 3b) needs precisely this to draw panel 1 and align the PAA/
    # quantisation panels against it; recovering it any other way would
    # mean the UI re-deriving which preprocessing ran, from outside the
    # recipe machinery that already knows.
    return AdapterResult(output_kind="encoding", x=x, t=t, encoding=symbols, meta={"details": details})


def _recommend(x, t, fs):
    return recommend_sax_params(x, t, fs)


def _derive(x, t, fs, params):
    return derive_sax_rows(x, t, fs, params)


def _plot(x, t, result, **params):
    # Part 6 4d: a DELIBERATELY SEPARATE renderer (matplotlib) from the
    # UI's interactive HoloViews encoding view — see
    # `plot_encoding_matplotlib`'s docstring for why the two can't
    # literally share drawing code. Both take the SAME input: the
    # symbol array and the `details` dict this run already computed.
    return plot_encoding_matplotlib(x, t, result.encoding, result.meta["details"])


SPEC = register(AdapterSpec(
    name="detection.sax_csax",
    display_name="cSAX symbolisation",
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
        ParamSpec("normalize", bool, True, "Z-normalise the span before encoding"),
    ],
    run=_run,
    output_kind="encoding",
    input_kind="signal",
    plot=_plot,
    description=(
        "cSAX: data-adaptive quantisation via Mean-Shift clustering on the "
        "windowed PAA, producing a symbolic (integer) sequence."
    ),
    recommend=_recommend,
    derive=_derive,
))
