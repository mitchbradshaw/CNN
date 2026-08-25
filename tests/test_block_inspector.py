"""
test_block_inspector.py
========================
Ticket 30 — the block inspector (`UI.workspaces.analyse.inspector.BlockInspector`).
Opening one step of the chain under construction shows its parameter controls,
side-input pickers, derived readouts and any cached result, all generated from
the adapter contract rather than hand-written per block.

The unit tests below use a fake app plus a synthetic recording and a single
registered probe adapter, so they run headless and do not need the real
channel. The two mounting tests build a real `ViewerApp` and are gated on the
real channel .npy, the same convention as tests/test_chain_builder.py.

Run from the project root:
    python tests/test_block_inspector.py
"""

import inspect
import os
import sys

import numpy as np
import pytest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import panel as pn
pn.extension()

from Adapters.base import AdapterResult, AdapterSpec, ParamSpec, SideInputSpec
from Adapters.registry import discover_adapters, get_adapter, register
from Working.database import queries as q
from Working.database import runs as R
from Working.database.schema import init_db
from Working.recipes import recipe_hash

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600

discover_adapters()


# ── probe adapter + fixtures ───────────────────────────────────────────────

def _register_probe_adapter():
    """A tiny, real adapter exercising every inspector feature: four param
    widget shapes, a span-aware recommend, severity-styled derive readouts,
    and two typed side inputs."""
    name = "detection.t30_probe"
    try:
        get_adapter(name)
    except KeyError:
        register(AdapterSpec(
            name=name,
            display_name="T30 probe",
            stage="detection",
            params=[
                ParamSpec("window", int, 10, "Window length", min=1, max=100),
                ParamSpec("mode", str, "fast", "Mode", choices=["fast", "slow"]),
                ParamSpec("scale", float, 1.0, "Scale", min=0.1, max=10.0),
                ParamSpec("enabled", bool, True, "Enabled"),
            ],
            run=lambda x, t, fs, window=10, mode="fast", scale=1.0, enabled=True,
                        sig=None, exemplar=None: AdapterResult(
                output_kind="signal", x=x, t=t,
            ),
            output_kind="signal",
            side_inputs=[
                SideInputSpec(name="sig", type_kind="signal",
                              sources=["root_signal", "earlier_step"]),
                SideInputSpec(name="exemplar", type_kind="signal",
                              sources=["library_exemplar"]),
            ],
            recommend=lambda x, t, fs: {
                "window": max(1, min(100, len(x) // 2)),
                "scale": 2.0,
            },
            derive=lambda x, t, fs, params: [
                ("Symbols", str(params["window"]), ""),
                ("Scale warn", "warn", "warn"),
                ("Scale error", "error", "error"),
            ],
        ))
    return name


class _FakeChainBuilder:
    def __init__(self, chain):
        self.chain = chain


class _FakeApp:
    """The minimal shape `BlockInspector` reads off `app`: the database
    connection, the chain under construction, the current recording, and an
    optional `run_panel` used for the currently selected span. Without a
    `run_panel`, the inspector falls back to `chain.span` (or whole channel)."""

    def __init__(self, conn, chain, recording_id, fs=1.0, n_samples=200):
        self.conn = conn
        self.chain_builder = _FakeChainBuilder(chain)
        self._recording_id = recording_id
        self._fs = fs
        self._n_samples = n_samples
        self.run_panel = None


def _db_with_recording(tmp_path, n_samples=200):
    """A fresh db + synthetic channel, with an open connection returned."""
    db_path = str(tmp_path / "t30.sqlite")
    npy_path = str(tmp_path / "CH0.npy")
    np.save(npy_path, np.arange(n_samples, dtype=float))
    conn = init_db(db_path)
    rid = q.insert_recording(conn, "fake.mat", 0, 1.0, n_samples, 0, npy_path)
    return conn, db_path, npy_path, rid


def _make_chain(recording_id, steps, span=None):
    from UI.analyse.chain_state import ChainState
    return ChainState(recording_id=recording_id, span=span, steps=steps)


def _probe_step(side_inputs=None):
    return {
        "stage": "detection",
        "algorithm": "t30_probe",
        "params": {},
        "side_inputs": side_inputs or {},
    }


def _lowpass_step():
    return {
        "stage": "preprocessing",
        "algorithm": "lowpass",
        "params": {},
        "side_inputs": {},
    }


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    import tempfile as _tempfile
    from Working.database import queries as _q
    from Working.database.schema import init_db as _init_db
    from UI.viewer import ViewerApp
    from tests._session_isolation import scratch_session_file

    tf = _tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = _init_db(tf.name)
    _q.insert_recording(conn, "UNITTEST_block_inspector.mat", 0, 1.0, REAL_L, 0,
                        REAL_CHANNEL_PATH)
    conn.close()
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    return app, tf.name


def _close_and_unlink(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


def _tab_names(tabs):
    return list(tabs._names)


def _pane_named(tabs, name):
    names = _tab_names(tabs)
    assert name in names, f"no tab named {name!r}; got {names}"
    return tabs.objects[names.index(name)]


# ── construction ───────────────────────────────────────────────────────────

def test_construction_builds_a_non_none_layout(tmp_path):
    from UI.workspaces.analyse.inspector import BlockInspector

    _register_probe_adapter()
    conn, db_path, npy_path, rid = _db_with_recording(tmp_path)
    try:
        chain = _make_chain(rid, [_probe_step()])
        inspector = BlockInspector(_FakeApp(conn, chain, rid))
        layout = inspector.layout()
        assert layout is not None
        assert inspector.step_select is not None
        assert inspector.param_column is not None
        assert inspector.derived_pane is not None
        assert inspector.side_inputs_column is not None
        assert inspector.cached_pane is not None
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(npy_path)


# ── parameter widgets preserve the ticket-17 mapping ───────────────────────

def test_opening_a_step_generates_param_widgets_preserving_mapping(tmp_path):
    from UI.workspaces.analyse.inspector import BlockInspector

    _register_probe_adapter()
    conn, db_path, npy_path, rid = _db_with_recording(tmp_path)
    try:
        chain = _make_chain(rid, [_probe_step()])
        inspector = BlockInspector(_FakeApp(conn, chain, rid))

        widgets = inspector._param_widgets
        assert set(widgets) == {"window", "mode", "scale", "enabled"}
        assert isinstance(widgets["window"], pn.widgets.IntInput)
        assert isinstance(widgets["scale"], pn.widgets.FloatInput)
        assert isinstance(widgets["mode"], pn.widgets.Select)
        assert isinstance(widgets["enabled"], pn.widgets.Checkbox)
        assert widgets["window"].start == 1
        assert widgets["window"].end == 100
        assert widgets["scale"].start == 0.1
        assert widgets["scale"].end == 10.0
        assert list(widgets["mode"].options) == ["fast", "slow"]
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(npy_path)


# ── recommend: applied now, re-applied when the span changes ───────────────

def test_recommend_is_applied_for_current_span_and_reapplied_on_span_change(tmp_path):
    from UI.workspaces.analyse.inspector import BlockInspector

    _register_probe_adapter()
    conn, db_path, npy_path, rid = _db_with_recording(tmp_path, n_samples=200)
    try:
        chain = _make_chain(rid, [_probe_step()])
        inspector = BlockInspector(_FakeApp(conn, chain, rid, n_samples=200))

        # Whole channel: recommend sees 200 samples -> window 100, scale 2.0.
        assert inspector._param_widgets["window"].value == 100
        assert inspector._param_widgets["scale"].value == 2.0

        # A smaller selected span re-applies the span-aware recommendation.
        chain.span = (0, 50)
        inspector._apply_recommended_defaults(force=False)
        assert inspector._param_widgets["window"].value == 25
        assert inspector._param_widgets["scale"].value == 2.0
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(npy_path)


# ── derive readouts recompute live, severity-styled ────────────────────────

def test_derive_recomputes_live_with_severity_styling(tmp_path):
    from UI.workspaces.analyse.inspector import BlockInspector

    _register_probe_adapter()
    conn, db_path, npy_path, rid = _db_with_recording(tmp_path, n_samples=200)
    try:
        chain = _make_chain(rid, [_probe_step()])
        inspector = BlockInspector(_FakeApp(conn, chain, rid, n_samples=200))

        html = inspector.derived_pane.object
        assert "Symbols" in html
        assert "warn" in html
        assert "error" in html
        # Severity styling survives from ticket 17's readout renderer.
        assert "#fff3cd" in html
        assert "#f8d7da" in html

        inspector._param_widgets["window"].value = 25
        assert "25" in inspector.derived_pane.object
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(npy_path)


# ── side-input pickers emit ticket 14's binding structure ──────────────────

def test_side_input_pickers_offer_typed_sources_and_emit_bindings(tmp_path):
    from UI.workspaces.analyse.inspector import BlockInspector

    _register_probe_adapter()
    conn, db_path, npy_path, rid = _db_with_recording(tmp_path, n_samples=200)
    try:
        entry_id = R.insert_motif_entry(conn, rid, 10, 20)
        chain = _make_chain(rid, [_lowpass_step(), _probe_step()])
        inspector = BlockInspector(_FakeApp(conn, chain, rid, n_samples=200))

        # Open the second step (the probe) by selecting it in the inspector.
        inspector.step_select.value = 1

        assert set(inspector._side_input_widgets) == {"sig", "exemplar"}

        sig = inspector._side_input_widgets["sig"]
        # Only the two declared sources for `sig`, and the earlier-step picker
        # offers only the earlier step whose output type is `signal`.
        assert list(sig["source"].options.values()) == ["root_signal", "earlier_step"]
        assert list(sig["target"].options.values()) == [0]

        ex = inspector._side_input_widgets["exemplar"]
        assert list(ex["source"].options.values()) == ["library_exemplar"]
        assert list(ex["exemplar"].options.values()) == [entry_id]

        # root_signal emits the exact ticket-14 shape.
        sig["source"].value = "root_signal"
        assert chain.steps[1]["side_inputs"]["sig"] == {"source_kind": "root_signal"}

        # earlier_step emits the exact ticket-14 shape.
        sig["source"].value = "earlier_step"
        assert sig["target"].visible is True
        assert chain.steps[1]["side_inputs"]["sig"] == {
            "source_kind": "earlier_step", "step_index": 0,
        }

        # library_exemplar emits the full content-addressed binding.
        ex["source"].value = "library_exemplar"
        binding = chain.steps[1]["side_inputs"]["exemplar"]
        assert binding["source_kind"] == "library_exemplar"
        assert binding["entry_id"] == entry_id
        assert binding["source_file"] == "fake.mat"
        assert binding["channel"] == 0
        assert binding["start_idx"] == 10
        assert binding["end_idx"] == 20
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(npy_path)


# ── cached result: ticket 15's step_artifacts row is surfaced, labelled ────

def test_cached_result_is_displayed_when_present(tmp_path):
    from UI.workspaces.analyse.inspector import BlockInspector

    _register_probe_adapter()
    conn, db_path, npy_path, rid = _db_with_recording(tmp_path, n_samples=200)
    try:
        step = _probe_step()
        chain = _make_chain(rid, [step])
        recipe = {
            "recording_id": rid,
            "span": list(chain.span) if chain.span is not None else None,
            "steps": [dict(step)],
        }
        prefix = dict(recipe)
        prefix["steps"] = recipe["steps"][:1]
        prefix_hash = recipe_hash(prefix)
        cache_path = str(tmp_path / "cached_step")
        R.insert_step_artifact(conn, prefix_hash, 0, cache_path)

        inspector = BlockInspector(_FakeApp(conn, chain, rid, n_samples=200))
        assert "Cached result" in inspector.cached_pane.object
        assert cache_path in inspector.cached_pane.object
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(npy_path)


# ── mounting: reaches the Analyse workspace, survives a registry reset ─────

def test_block_inspector_survives_a_workspace_registry_reset():
    from UI import workspaces

    workspaces.reset()
    try:
        analyse = [label for label, _ in workspaces.sections("Analyse")]
        assert "Block inspector" in analyse
    finally:
        workspaces.reset()


def test_block_inspector_mounts_into_the_analyse_workspace_as_a_real_pane():
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        analyse = _pane_named(app.tabs, "Analyse")
        assert isinstance(analyse, pn.Tabs), \
            "Analyse should group its sections once more than one is mounted"
        assert "Block inspector" in _tab_names(analyse)
        pane = _pane_named(analyse, "Block inspector")
        assert pane is not None, "Block inspector renders as None -- the blank-pane failure"
    finally:
        _close_and_unlink(app, db_path)


# ── runner ──────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, skipped, failed = 0, 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except pytest.skip.Exception as e:
            print(f"[SKIP] {fn.__name__}: {e}")
            skipped += 1
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    tally = f"{passed}/{len(fns)} passed"
    if skipped:
        tally += f", {skipped} skipped (real channel data absent)"
    print(f"\n{tally}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
