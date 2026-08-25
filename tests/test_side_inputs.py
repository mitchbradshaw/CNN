"""
test_side_inputs.py
=====================
Ticket 14 — side-input resolution. `Working.side_inputs.resolve_side_inputs`
turns a step's binding map into the typed values its adapter's `run` needs
(one per declared `Adapters.base.SideInputSpec`), and
`Working.execution.execute_recipe` calls it before running each step that
declares any.

Run from the project root:
    python tests/test_side_inputs.py
"""

import inspect
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Adapters.base import AdapterResult, AdapterSpec, SideInputSpec
from Adapters.registry import get_adapter, register
from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.execution import RecipeExecutionError, execute_recipe
from Working.recipes import make_recipe
from Working.side_inputs import SideInputResolutionError, resolve_side_inputs, typed_step_value
from Working.types import Signal, SpanSet


def _spec(side_inputs, name="test.side_input_probe", run=None):
    """A minimal, unregistered AdapterSpec for exercising `resolve_side_inputs`
    directly, without going through the real adapter registry."""
    return AdapterSpec(
        name=name, display_name=name, stage="detection", params=[],
        run=run or (lambda x, t, fs, **params: AdapterResult(
            output_kind="signal", value=Signal(x=x, fs=fs))),
        output_kind="signal",
        side_inputs=side_inputs,
    )


def _db_with_recording(source_file="rec.mat", channel=0, n_samples=1000, fs=1.0):
    """A fresh sqlite db with one recording backed by a synthetic .npy
    (values == sample index, so a resolved slice is checkable by value)."""
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    npy_tf = tempfile.NamedTemporaryFile(suffix=".npy", delete=False)
    npy_tf.close()
    np.save(npy_tf.name, np.arange(n_samples, dtype=float))
    q.insert_recording(conn, source_file, channel, fs, n_samples, 0, npy_tf.name)
    return conn, tf.name, npy_tf.name


# ── resolve_side_inputs: root_signal ────────────────────────────────────────

def test_root_signal_binding_resolves_to_the_chain_root_signal():
    spec = _spec([SideInputSpec(name="sig", type_kind="signal", sources=["root_signal"])])
    root = Signal(x=np.array([1.0, 2.0]), fs=2.0)
    resolved = resolve_side_inputs(
        None, spec, {"sig": {"source_kind": "root_signal"}},
        root_signal=root, step_results={},
    )
    assert resolved == {"sig": root}


# ── resolve_side_inputs: earlier_step ───────────────────────────────────────

def test_earlier_step_binding_resolves_to_the_referenced_steps_value():
    spec = _spec([SideInputSpec(name="ref", type_kind="signal", sources=["earlier_step"])])
    value = Signal(x=np.array([3.0]), fs=1.0)
    resolved = resolve_side_inputs(
        None, spec, {"ref": {"source_kind": "earlier_step", "step_index": 0}},
        root_signal=None, step_results={0: value},
    )
    assert resolved == {"ref": value}


def test_earlier_step_binding_raises_naming_the_side_input_if_unresolved():
    spec = _spec([SideInputSpec(name="ref", type_kind="signal", sources=["earlier_step"])])
    try:
        resolve_side_inputs(
            None, spec, {"ref": {"source_kind": "earlier_step", "step_index": 0}},
            root_signal=None, step_results={},
        )
        assert False, "expected SideInputResolutionError"
    except SideInputResolutionError as e:
        assert "ref" in str(e)


# ── resolve_side_inputs: library_exemplar ───────────────────────────────────

def test_library_exemplar_binding_resolves_to_a_signal_sliced_from_its_recording():
    conn, db_path, npy_path = _db_with_recording(n_samples=1000, fs=10.0)
    try:
        spec = _spec([SideInputSpec(name="exemplar", type_kind="signal", sources=["library_exemplar"])])
        binding = {
            "source_kind": "library_exemplar", "entry_id": 1,
            "source_file": "rec.mat", "channel": 0,
            "start_idx": 100, "end_idx": 110,
        }
        resolved = resolve_side_inputs(
            conn, spec, {"exemplar": binding}, root_signal=None, step_results={},
        )
        value = resolved["exemplar"]
        assert isinstance(value, Signal)
        assert value.fs == 10.0
        assert np.array_equal(value.x, np.arange(100, 110, dtype=float))
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(npy_path)


def test_library_exemplar_binding_raises_naming_the_side_input_for_an_unknown_recording():
    conn, db_path, npy_path = _db_with_recording()
    try:
        spec = _spec([SideInputSpec(name="exemplar", type_kind="signal", sources=["library_exemplar"])])
        binding = {
            "source_kind": "library_exemplar", "entry_id": 1,
            "source_file": "nope.mat", "channel": 0,
            "start_idx": 0, "end_idx": 10,
        }
        try:
            resolve_side_inputs(conn, spec, {"exemplar": binding}, root_signal=None, step_results={})
            assert False, "expected SideInputResolutionError"
        except SideInputResolutionError as e:
            assert "exemplar" in str(e)
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(npy_path)


def test_library_exemplar_binding_raises_naming_the_side_input_for_a_span_outside_the_recording():
    conn, db_path, npy_path = _db_with_recording(n_samples=100)
    try:
        spec = _spec([SideInputSpec(name="exemplar", type_kind="signal", sources=["library_exemplar"])])
        binding = {
            "source_kind": "library_exemplar", "entry_id": 1,
            "source_file": "rec.mat", "channel": 0,
            "start_idx": 90, "end_idx": 200,
        }
        try:
            resolve_side_inputs(conn, spec, {"exemplar": binding}, root_signal=None, step_results={})
            assert False, "expected SideInputResolutionError"
        except SideInputResolutionError as e:
            assert "exemplar" in str(e)
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(npy_path)


# ── resolve_side_inputs: binding shape errors ───────────────────────────────

def test_raises_naming_the_side_input_when_a_declared_side_input_has_no_binding():
    spec = _spec([SideInputSpec(name="exemplar", type_kind="signal", sources=["root_signal"])])
    try:
        resolve_side_inputs(None, spec, {}, root_signal=None, step_results={})
        assert False, "expected SideInputResolutionError"
    except SideInputResolutionError as e:
        assert "exemplar" in str(e)


def test_raises_when_the_bound_source_kind_is_not_one_the_side_input_allows():
    spec = _spec([SideInputSpec(name="exemplar", type_kind="signal", sources=["library_exemplar"])])
    try:
        resolve_side_inputs(
            None, spec, {"exemplar": {"source_kind": "root_signal"}},
            root_signal=Signal(x=np.array([1.0]), fs=1.0), step_results={},
        )
        assert False, "expected SideInputResolutionError"
    except SideInputResolutionError as e:
        assert "exemplar" in str(e)


# ── typed_step_value ─────────────────────────────────────────────────────────

def test_typed_step_value_prefers_the_results_typed_value():
    value = Signal(x=np.array([1.0]), fs=1.0)
    result = AdapterResult(output_kind="scores", value=value)
    assert typed_step_value(result) is value


def test_typed_step_value_of_a_signal_output_is_its_signal():
    """This used to assert that a `signal` result with no `value` was wrapped
    into a `Signal` from its `x` carrier. Ticket 10 deleted that carrier, so
    there is no longer an unwrapped form to fall back from — a signal block
    returns its `Signal` and `typed_step_value` hands it straight back."""
    signal = Signal(x=np.array([1.0, 2.0]), fs=5.0)
    result = AdapterResult(output_kind="signal", value=signal)
    assert typed_step_value(result) is signal


def test_typed_step_value_is_none_for_an_unresolvable_output():
    result = AdapterResult(output_kind="spanset")
    assert typed_step_value(result) is None


# ── execute_recipe wiring, end-to-end through the real adapter registry ────

def _register_once(spec):
    """Register `spec` unless an adapter of that name is already registered
    — idempotent across repeated runs of this file in the same process."""
    try:
        get_adapter(spec.name)
    except KeyError:
        register(spec)
    return spec.name


def _register_exemplar_probe_adapter():
    return _register_once(AdapterSpec(
        name="detection.side_input_probe", display_name="Side-input probe",
        stage="detection", params=[],
        run=lambda x, t, fs, exemplar=None: AdapterResult(
            output_kind="spanset",
            value=SpanSet(starts=(0,), ends=(1,), scores=(float(exemplar.x[0]),)),
        ),
        output_kind="spanset",
        side_inputs=[SideInputSpec(name="exemplar", type_kind="signal", sources=["library_exemplar"])],
    ))


def _register_dual_probe_adapter():
    return _register_once(AdapterSpec(
        name="detection.dual_side_input_probe", display_name="Dual side-input probe",
        stage="detection", params=[],
        run=lambda x, t, fs, root=None, ref=None: AdapterResult(
            output_kind="spanset",
            value=SpanSet(
                starts=(0,), ends=(1,),
                scores=(float(root.x[0]) + float(ref.x[0]),),
            ),
        ),
        output_kind="spanset",
        side_inputs=[
            SideInputSpec(name="root", type_kind="signal", sources=["root_signal"]),
            SideInputSpec(name="ref", type_kind="signal", sources=["earlier_step"]),
        ],
    ))


def _db_with_two_recordings():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)

    root_npy = tempfile.NamedTemporaryFile(suffix=".npy", delete=False)
    root_npy.close()
    np.save(root_npy.name, np.zeros(1000, dtype=float))
    q.insert_recording(conn, "root.mat", 0, 1.0, 1000, 0, root_npy.name)

    exemplar_npy = tempfile.NamedTemporaryFile(suffix=".npy", delete=False)
    exemplar_npy.close()
    np.save(exemplar_npy.name, np.arange(1000, dtype=float))
    q.insert_recording(conn, "exemplar.mat", 0, 1.0, 1000, 0, exemplar_npy.name)

    conn.close()
    return tf.name, [root_npy.name, exemplar_npy.name]


def test_execute_recipe_resolves_a_library_exemplar_binding_before_running():
    _register_exemplar_probe_adapter()
    db_path, npy_paths = _db_with_two_recordings()
    try:
        recipe = make_recipe(1, [{
            "stage": "detection", "algorithm": "side_input_probe",
            "side_inputs": {"exemplar": {
                "source_kind": "library_exemplar", "entry_id": 1,
                "source_file": "exemplar.mat", "channel": 0,
                "start_idx": 100, "end_idx": 110,
            }},
        }], span=(0, 100))
        out = execute_recipe(recipe, db_path=db_path)
        assert out["detections_written"] == 1

        conn = init_db(db_path)
        dets = R.list_detections(conn, out["run_id"])
        conn.close()
        assert len(dets) == 1
        assert dets[0]["score"] == 100.0  # exemplar.mat[100] == 100.0
    finally:
        os.unlink(db_path)
        for p in npy_paths:
            os.unlink(p)


def test_execute_recipe_raises_naming_the_binding_when_unresolved():
    _register_exemplar_probe_adapter()
    db_path, npy_paths = _db_with_two_recordings()
    try:
        recipe = make_recipe(1, [
            {"stage": "detection", "algorithm": "side_input_probe"},
        ], span=(0, 100))
        try:
            execute_recipe(recipe, db_path=db_path)
            assert False, "expected RecipeExecutionError"
        except RecipeExecutionError as e:
            assert "exemplar" in str(e)

        conn = init_db(db_path)
        runs = R.list_runs(conn)
        assert len(runs) == 1
        assert runs[0]["status"] == "failed"
        conn.close()
    finally:
        os.unlink(db_path)
        for p in npy_paths:
            os.unlink(p)


def test_execute_recipe_resolves_root_signal_and_earlier_step_bindings():
    _register_dual_probe_adapter()
    db_path, npy_paths = _db_with_two_recordings()
    try:
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
            {"stage": "detection", "algorithm": "dual_side_input_probe",
             "side_inputs": {
                 "root": {"source_kind": "root_signal"},
                 "ref": {"source_kind": "earlier_step", "step_index": 0},
             }},
        ], span=(0, 600))
        out = execute_recipe(recipe, db_path=db_path)

        conn = init_db(db_path)
        dets = R.list_detections(conn, out["run_id"])
        conn.close()
        # Both bindings resolved to real arrays (not None) — the probe's
        # run() would have raised AttributeError, not written a detection,
        # had either been left unresolved.
        assert len(dets) == 1
        assert dets[0]["score"] is not None
    finally:
        os.unlink(db_path)
        for p in npy_paths:
            os.unlink(p)


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
