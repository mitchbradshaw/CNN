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

import contextlib
import importlib
import inspect
import os
import pkgutil
import sys
import types as pytypes

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import Working.types as interchange_types
from Adapters.base import (
    OUTPUT_KINDS,
    AdapterResult,
    AdapterSpec,
    SideInputSpec,
)

# The output vocabulary the nineteen shipped adapters were written against,
# named here because the point of the expand phase is that they keep using it.
LEGACY_OUTPUT_KINDS = ("signal", "intervals", "encoding")

# What the PRD ("Chain shape") says a side input may be bound to. Exercised
# through `SideInputSpec` below rather than compared against the constant that
# implements it.
PRD_SOURCE_KINDS = ("root_signal", "earlier_step", "library_exemplar")


def _interchange_type_names():
    """The interchange type names, taken from the module that owns the types
    rather than from the adapter constant under test."""
    return [name.lower() for name in interchange_types.__all__]


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
    for kind in LEGACY_OUTPUT_KINDS:
        assert _spec(output_kind=kind).output_kind == kind


# ── output_kind: interchange types accepted too ─────────────────────────────

def test_output_kind_accepts_the_name_of_every_type_working_types_owns():
    # An adapter may declare its output as any type the type module defines,
    # without `base.py` needing to be edited to learn that type's name.
    for kind in _interchange_type_names():
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


def test_input_kind_accepts_the_name_of_every_type_working_types_owns():
    for kind in _interchange_type_names():
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


def test_side_input_accepts_each_source_kind_the_prd_names():
    for source in PRD_SOURCE_KINDS:
        side = SideInputSpec(name="exemplar", type_kind="signal", sources=[source])
        assert side.sources == [source]


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


def test_the_new_fields_default_to_the_values_the_shipped_adapters_rely_on():
    # The nineteen adapters were written before these fields existed and set
    # none of them, so the defaults are what they get. Anything other than
    # "primary input is the root signal, no side inputs, counts as free"
    # would silently change how every existing step composes and is costed.
    spec = _spec()
    assert spec.input_kind is None
    assert spec.side_inputs == []
    assert spec.estimate is None


# ── the shipped adapters import and register unmodified ────────────────────

@contextlib.contextmanager
def _third_party_gaps_bridged():
    """Stand in for a third-party package this environment cannot import, so
    that what follows measures this ticket's contract and not the state of the
    conda environment.

    `kymatio` is broken against the installed scipy (it imports
    `scipy.special.sph_harm`, which scipy has since removed) — the case
    `Adapters/registry.py`'s docstring names, and the reason
    `discover_adapters()` skips a module rather than failing. The stand-in
    satisfies the import and nothing else: constructing it raises, so no test
    can quietly obtain a fake scattering result from it.
    """
    try:
        importlib.import_module("kymatio.numpy")
        yield
        return
    except Exception:
        pass

    class _Unavailable:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("kymatio is not usable in this environment")

    stub = pytypes.ModuleType("kymatio")
    stub.numpy = pytypes.ModuleType("kymatio.numpy")
    stub.numpy.Scattering1D = _Unavailable
    sys.modules["kymatio"] = stub
    sys.modules["kymatio.numpy"] = stub.numpy
    try:
        yield
    finally:
        del sys.modules["kymatio"], sys.modules["kymatio.numpy"]


def _shipped_adapter_specs():
    """Every adapter module in `Adapters/`, imported for real and mapped to
    the spec it registered.

    The module list comes from the package, not from a list transcribed into
    this file, and the imports are done directly rather than through
    `discover_adapters()` so that a module which fails to import fails this
    test instead of being skipped with a warning.
    """
    import Adapters
    from Adapters.registry import get_adapter

    names = sorted(
        name for _, name, _ in pkgutil.iter_modules(Adapters.__path__)
        if name not in ("base", "registry") and not name.startswith("_")
    )
    specs = {}
    with _third_party_gaps_bridged():
        for name in names:
            module = importlib.import_module(f"Adapters.{name}")
            # KeyError here means the module imported but never registered.
            specs[name] = get_adapter(module.SPEC.name)
    return specs


def test_every_shipped_adapter_registers_without_modification():
    specs = _shipped_adapter_specs()
    assert len(specs) == 20, f"expected the twenty shipped adapters, got {sorted(specs)}"
    # Ticket 08 remaps detection_matrix_profile (encoding -> scores) and
    # preprocessing_window_matrix (encoding -> windowset) to their correct
    # types, and adds detection_threshold, a typed (input_kind='scores')
    # adapter. Ticket 06 remaps the four preprocessing filters (signal ->
    # signal, now with an explicit input_kind) and the three interval
    # detectors (intervals -> spanset) to their typed vocabulary. Ticket 07
    # remaps the nine encoding blocks (signal -> encoding, now with an
    # explicit input_kind). Ticket 43 adds preprocessing_surrogate, a new
    # typed (input_kind='signal', output_kind='signal') adapter. Ticket 09
    # removes detection_entropy entirely: its whole-span scalar fits none of
    # the seven interchange types, so it is out of scope rather than an
    # eighth type. The remaining adapters are untouched by those tickets and
    # still use the legacy vocabulary this test was written to guard.
    remapped_by_ticket_06 = {
        "preprocessing_bandpass", "preprocessing_detrend",
        "preprocessing_highpass", "preprocessing_lowpass",
        "detection_rupture", "detection_spike_v1", "detection_dehshibi_spikes",
    }
    remapped_by_ticket_08 = {"detection_matrix_profile", "preprocessing_window_matrix",
                              "detection_threshold"}
    remapped_by_ticket_07 = {
        "catalogue_gramian_fusion", "catalogue_gramian_gadf",
        "catalogue_gramian_gasf", "catalogue_gramian_recurrence",
        "detection_freq_stft", "detection_sax_csax", "detection_sax_dsax",
        "detection_sax_psax", "detection_wavelet_scattering",
    }
    added_by_ticket_43 = {"preprocessing_surrogate"}
    remapped = (
        remapped_by_ticket_06 | remapped_by_ticket_08 | remapped_by_ticket_07
        | added_by_ticket_43
    )
    for module_name, spec in specs.items():
        if module_name in remapped:
            continue
        assert spec.output_kind in LEGACY_OUTPUT_KINDS, module_name
        assert spec.input_kind is None, module_name
        assert spec.side_inputs == [], module_name
        assert spec.estimate is None, module_name


def test_every_shipped_adapters_declared_params_still_validate():
    # `validate_params` is the seam the run panel and `execute_recipe` both go
    # through; a field added to the spec in the wrong place would show up as a
    # real adapter whose own defaults no longer survive a round trip.
    for module_name, spec in _shipped_adapter_specs().items():
        validated = spec.validate_params({})
        assert set(validated) == {p.name for p in spec.params}, module_name


def test_the_expansion_did_not_drop_a_hook_a_shipped_adapter_declares():
    specs = _shipped_adapter_specs().values()
    for hook in ("recommend", "derive", "persist", "max_span_samples", "plot"):
        owners = sorted(s.name for s in specs if getattr(s, hook) is not None)
        assert owners, f"no shipped adapter declares {hook} any more"


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
