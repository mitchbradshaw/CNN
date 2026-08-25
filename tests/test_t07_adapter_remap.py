"""
test_t07_adapter_remap.py
===========================
Ticket 07 — adapter remap batch B: encoding blocks.

The nine adapters that genuinely produce an image or symbolic representation
declare their new types: `Signal -> Encoding`, with no behavioural change.
Unlike ticket 06, `run` is NOT required to populate `AdapterResult.value` —
the encoders' `run` functions are untouched; only the spec's declared types
change. The three SAX adapters keep their span-aware `recommend`/`derive`
hooks intact, and the four Gramian adapters keep their O(n^2) span-length
guard (`max_span_samples`) enforced by `execute_recipe` before `run`.

Run from the project root:
    python tests/test_t07_adapter_remap.py
"""

import contextlib
import importlib
import inspect
import os
import shutil
import sys
import tempfile
import types as pytypes

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Adapters.base import TYPE_KINDS
from Adapters.registry import discover_adapters, get_adapter

# The nine encoding blocks, by registry name.
ENCODING_ADAPTERS = (
    "catalogue.gramian_gasf",
    "catalogue.gramian_gadf",
    "catalogue.gramian_recurrence",
    "catalogue.gramian_fusion",
    "detection.sax_csax",
    "detection.sax_psax",
    "detection.sax_dsax",
    "detection.wavelet_scattering",
    "detection.freq_stft",
)

# The four Gramian adapters consume a whole span (O(n^2) image), so they
# declare a span-length ceiling enforced by execute_recipe before run.
GRAMIAN_ADAPTERS = (
    "catalogue.gramian_gasf",
    "catalogue.gramian_gadf",
    "catalogue.gramian_recurrence",
    "catalogue.gramian_fusion",
)

# The three SAX adapters keep their span-aware recommend/derive hooks.
SAX_ADAPTERS = (
    "detection.sax_csax",
    "detection.sax_psax",
    "detection.sax_dsax",
)


@contextlib.contextmanager
def _kymatio_gap_bridged():
    """Stand in for the broken kymatio install (see test_adapter_spec.py's
    `_third_party_gaps_bridged`) so `detection.wavelet_scattering` registers
    and the test can assert on its declared types. Constructing the stub
    raises, so no test can quietly obtain a fake scattering result from it."""
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


def _get_encoding_specs():
    """Every encoding block's AdapterSpec. `discover_adapters()` is called
    again under the kymatio bridge so the wavelet adapter — skipped by the
    module-load discovery because kymatio is broken — is registered too."""
    specs = {}
    with _kymatio_gap_bridged():
        discover_adapters()
        for name in ENCODING_ADAPTERS:
            specs[name] = get_adapter(name)
    return specs


def test_all_nine_declare_encoding_output_and_explicit_input():
    specs = _get_encoding_specs()
    assert "encoding" in TYPE_KINDS  # Encoding is one of the seven types
    for name, spec in specs.items():
        assert spec.output_kind == "encoding", name
        assert spec.output_kind in TYPE_KINDS, name
        assert spec.input_kind == "signal", name
        assert spec.input_kind in TYPE_KINDS, name


def test_sax_adapters_keep_recommend_span_aware_and_derive_readout():
    specs = _get_encoding_specs()
    x = np.zeros(600)
    t = np.arange(600)
    for name in SAX_ADAPTERS:
        spec = specs[name]
        assert spec.recommend is not None, name
        assert spec.derive is not None, name
        rec = spec.recommend(x, t, 1.0)
        # Span-aware: a 600-sample span recommends ~30 symbols, not a fixed
        # default — this is the behaviour that must survive the remap.
        assert rec["target_symbol_count"] == 30, (name, rec)
        params = {k: v for k, v in rec.items() if k != "preprocess_window_s"}
        rows = spec.derive(x, t, 1.0, spec.validate_params(params))
        labels = {label for label, _value, _sev in rows}
        assert {"Samples per symbol", "Symbols produced"} <= labels, name


def test_gramian_adapters_keep_max_span_samples_enforced():
    from Working.database.schema import init_db
    from Working.database import queries as q
    from Working.execution import RecipeExecutionError, execute_recipe
    from Working.recipes import make_recipe

    specs = _get_encoding_specs()
    for name in GRAMIAN_ADAPTERS:
        spec = specs[name]
        assert spec.max_span_samples is not None, name
        n = spec.max_span_samples + 1
        algorithm = name.split(".", 1)[1]  # "gramian_gasf" etc.
        tmpdir = tempfile.mkdtemp(prefix="t07_test_")
        try:
            npy_path = os.path.join(tmpdir, "CH0.npy")
            np.save(npy_path, np.zeros(n))
            db_path = os.path.join(tmpdir, "test.sqlite")
            conn = init_db(db_path)
            q.insert_recording(conn, "fake.mat", 0, 1.0, n, 0, npy_path)
            conn.close()

            recipe = make_recipe(1, [
                {"stage": "catalogue", "algorithm": algorithm, "params": {}},
            ])
            try:
                execute_recipe(recipe, db_path=db_path)
                assert False, f"{name}: expected a too-long span to be refused"
            except RecipeExecutionError as e:
                assert "max_span_samples" in str(e), (name, e)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


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
