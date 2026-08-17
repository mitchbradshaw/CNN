"""
test_adapter_spec.py
======================
Ticket 05 — adapter spec expansion (expand phase). `AdapterSpec` gains a
declared `input_kind`, typed `side_inputs`, and an optional runtime
`estimate`; `output_kind` accepts the seven interchange type names (see
`Working.types` / ticket 01) alongside the legacy `signal`/`intervals`/
`encoding` vocabulary, so the nineteen adapters that only know the legacy
vocabulary keep working unmodified. `AdapterResult` gains a `value` field
for a typed object.

This is the "expand" half of an expand/contract migration: nothing here
removes the legacy vocabulary or requires an existing adapter to change.
That happens in later tickets, once `base.py`/`registry.py` unfreeze.

Pure-dataclass contract tests, no database/UI — runnable standalone:
    python tests/test_adapter_spec.py
"""

import inspect
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Adapters.base import (
    OUTPUT_KINDS,
    SOURCE_KINDS,
    TYPE_KINDS,
    AdapterResult,
    AdapterSpec,
    SideInputSpec,
)


def _spec(**overrides):
    """A minimal, otherwise-valid AdapterSpec, e.g. any existing adapter."""
    kwargs = dict(
        name="test.stub",
        display_name="Stub",
        stage="preprocessing",
        params=[],
        run=lambda x, t, fs, **params: AdapterResult(output_kind="signal"),
        output_kind="signal",
    )
    kwargs.update(overrides)
    return AdapterSpec(**kwargs)


# ── output_kind: legacy vocabulary preserved ────────────────────────────────

def test_output_kind_still_accepts_the_legacy_vocabulary():
    for kind in ("signal", "intervals", "encoding"):
        assert _spec(output_kind=kind).output_kind == kind


# ── output_kind: seven interchange types accepted too ───────────────────────

def test_type_kinds_is_exactly_the_seven_interchange_types():
    assert TYPE_KINDS == (
        "signal", "spanset", "windowset", "encoding", "grouping", "model", "scores",
    )


def test_output_kind_accepts_every_type_kind_not_already_in_legacy_vocabulary():
    # 'signal' and 'encoding' already existed in the legacy vocabulary; the
    # other five type names are new territory for output_kind.
    for kind in ("spanset", "windowset", "grouping", "model", "scores"):
        assert _spec(output_kind=kind).output_kind == kind


def test_output_kind_rejects_a_value_outside_the_union():
    try:
        _spec(output_kind="bogus")
        assert False, "expected ValueError"
    except ValueError as e:
        # message must name the valid set so a typo is diagnosable
        for kind in OUTPUT_KINDS:
            assert kind in str(e), f"{kind!r} missing from error message: {e}"


def test_output_kind_union_has_no_duplicates():
    assert len(OUTPUT_KINDS) == len(set(OUTPUT_KINDS))


# ── input_kind ───────────────────────────────────────────────────────────────

def test_input_kind_defaults_to_none_meaning_root_signal():
    assert _spec().input_kind is None


def test_input_kind_accepts_each_of_the_seven_type_names():
    for kind in TYPE_KINDS:
        assert _spec(input_kind=kind).input_kind == kind


def test_input_kind_rejects_a_legacy_only_value():
    # 'intervals' is legacy output vocabulary, not one of the seven types,
    # so it must not be a valid input_kind.
    try:
        _spec(input_kind="intervals")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "intervals" in str(e)


def test_input_kind_rejects_an_unknown_value():
    try:
        _spec(input_kind="bogus")
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── side_inputs ──────────────────────────────────────────────────────────────

def test_side_inputs_default_to_an_empty_list():
    assert _spec().side_inputs == []


def test_side_inputs_carry_a_typed_declaration():
    side = SideInputSpec(
        name="exemplar", type_kind="signal",
        sources=["root_signal", "library_exemplar"],
    )
    spec = _spec(side_inputs=[side])
    assert spec.side_inputs == [side]
    assert spec.side_inputs[0].type_kind == "signal"
    assert spec.side_inputs[0].sources == ["root_signal", "library_exemplar"]


def test_side_input_source_kinds_are_exactly_the_three_named_in_the_prd():
    assert SOURCE_KINDS == ("root_signal", "earlier_step", "library_exemplar")


def test_side_input_rejects_an_unknown_type_kind():
    try:
        SideInputSpec(name="exemplar", type_kind="bogus", sources=["root_signal"])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_side_input_rejects_an_unknown_source():
    try:
        SideInputSpec(name="exemplar", type_kind="signal", sources=["bogus"])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_side_input_rejects_an_empty_source_list():
    try:
        SideInputSpec(name="exemplar", type_kind="signal", sources=[])
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── estimate ─────────────────────────────────────────────────────────────────

def test_estimate_defaults_to_none_meaning_free():
    assert _spec().estimate is None


def test_estimate_accepts_a_callable_returning_predicted_seconds():
    spec = _spec(estimate=lambda x, t, fs, **params: 12.5)
    assert spec.estimate(None, None, 1.0) == 12.5


# ── AdapterResult.value ──────────────────────────────────────────────────────

def test_adapter_result_value_defaults_to_none():
    result = AdapterResult(output_kind="signal")
    assert result.value is None


def test_adapter_result_value_carries_a_typed_object_alongside_untouched_fields():
    from Working.types import Signal
    import numpy as np

    sig = Signal(x=np.array([1.0, 2.0, 3.0]), fs=1.0)
    result = AdapterResult(output_kind="signal", x=sig.x, t=None, value=sig)
    assert result.value is sig
    assert result.x is sig.x
    assert result.intervals is None
    assert result.encoding is None


# ── untouched surface: recommend / derive / persist / max_span_samples /
#    plot / validate_params ─────────────────────────────────────────────────

def test_validate_params_behaviour_is_unchanged():
    from Adapters.base import ParamSpec

    spec = _spec(params=[ParamSpec(name="cutoff", type=float, default=5.0, min=0.0)])
    assert spec.validate_params({})["cutoff"] == 5.0
    assert spec.validate_params({"cutoff": 10.0})["cutoff"] == 10.0
    try:
        spec.validate_params({"not_a_real_param": 1})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_recommend_derive_persist_max_span_samples_plot_still_accepted_and_default_none():
    spec = _spec()
    assert spec.recommend is None
    assert spec.derive is None
    assert spec.persist is None
    assert spec.max_span_samples is None
    assert spec.plot is None

    marker = object()
    spec = _spec(
        recommend=lambda x, t, fs: {"cutoff": 1.0},
        derive=lambda x, t, fs, params: [("rows", 1, "")],
        persist=lambda *a, **k: "path",
        max_span_samples=100,
        plot=lambda x, t, result, **params: marker,
    )
    assert spec.recommend(None, None, 1.0) == {"cutoff": 1.0}
    assert spec.derive(None, None, 1.0, {}) == [("rows", 1, "")]
    assert spec.persist() == "path"
    assert spec.max_span_samples == 100
    assert spec.plot(None, None, None) is marker


# ── all nineteen existing adapters import and register unmodified ──────────

_EXPECTED_ADAPTER_NAMES = {
    "catalogue.gramian_fusion",
    "catalogue.gramian_gadf",
    "catalogue.gramian_gasf",
    "catalogue.gramian_recurrence",
    "detection.dehshibi_spikes",
    "detection.entropy",
    "detection.freq_stft",
    "detection.matrix_profile",
    "detection.rupture",
    "detection.sax_csax",
    "detection.sax_dsax",
    "detection.sax_psax",
    "detection.spike_v1",
    "detection.wavelet_scattering",
    "preprocessing.bandpass",
    "preprocessing.detrend",
    "preprocessing.highpass",
    "preprocessing.lowpass",
    "preprocessing.window_matrix",
}


def test_all_nineteen_existing_adapters_register_without_modification():
    from Adapters.registry import discover_adapters

    specs = discover_adapters()
    registered = {s.name for s in specs}
    missing = _EXPECTED_ADAPTER_NAMES - registered
    # `registry.discover_adapters()` skips (with a warning, not a hard
    # failure) a module whose *third-party* import is broken in this
    # environment — e.g. kymatio against a newer scipy, exactly the case
    # `Adapters/registry.py`'s own docstring names. That is a pre-existing
    # environment gap, not a regression from this ticket, so only that
    # specific known gap is tolerated here.
    assert missing <= {"detection.wavelet_scattering"}, \
        f"adapters failed to register for an unexpected reason: {missing}"
    for spec in specs:
        if spec.name in _EXPECTED_ADAPTER_NAMES:
            # none of the nineteen were touched by this ticket, so their
            # output_kind must still be drawn from the legacy vocabulary.
            assert spec.output_kind in ("signal", "intervals", "encoding"), spec.name
            assert spec.input_kind is None, spec.name
            assert spec.side_inputs == [], spec.name
            assert spec.estimate is None, spec.name


# ── runner ───────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
