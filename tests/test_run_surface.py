"""
test_run_surface.py
=====================
Ticket 31 — the run surface (`UI.workspaces.analyse.run_surface.
RunSurface`): the decision surface before a run. It shows the chain's
estimated runtime including the fan-out multiplier, reads ticket 26's
routing value to promote "export cluster job" to the primary action above
the configured ceiling (with local execution demoted, not removed), feeds
the ticket-25 scope selector (recordings/channels, span, bands) into the
recipe's fan-out, and wires launch/cancel to the ticket-24 background-run
machinery. No surrogate control appears on this surface (ticket 44 owns
that).

Most tests use a fake app — `RunSurface` reads `_recording_id`, `_fs`,
`_n_samples` and optionally `conn` off it, nothing else, so these need no
real channel data. The estimate/routing tests calibrate the matrix-profile
cost module into an isolated scratch file (same pattern as
tests/test_job_export.py). The launch test uses a fresh temp sqlite with
synthetic .npy channels, exactly like tests/test_run_groups.py.

Run from the project root:
    python tests/test_run_surface.py
"""

import inspect
import os
import shutil
import sys
import tempfile
import threading
import time

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

from Adapters.registry import discover_adapters
from Working.database.schema import init_db
from Working.database import queries as q
from Working.hpc.job_export import estimate_recipe_seconds
from Working.Detection.matrix_profiling import cost as mp_cost
from tests._calibration_isolation import scratch_calibration
from UI.analyse.chain_state import ChainState

discover_adapters()


class _FakeApp:
    """The minimal shape `RunSurface` needs off `app` — the current
    recording id, fs, sample count and an optional live db connection.
    No `chain_builder` because every test passes a `chain` explicitly."""

    def __init__(self, recording_id=1, fs=1.0, n_samples=1000, conn=None):
        self._recording_id = recording_id
        self._fs = fs
        self._n_samples = n_samples
        self.conn = conn


def _fresh_db_with_channels(n_channels, n_samples=200, fs=1.0):
    """A fresh temp sqlite db with `n_channels` synthetic recordings (one
    channel each), each backed by a real .npy file so a launch actually
    runs. Returns (db_path, tmpdir, recording_ids)."""
    tmpdir = tempfile.mkdtemp(prefix="t31_test_")
    db_path = os.path.join(tmpdir, "test.sqlite")
    conn = init_db(db_path)
    ids = []
    try:
        for ch in range(n_channels):
            npy_path = os.path.join(tmpdir, f"CH{ch}.npy")
            np.save(npy_path, np.random.default_rng(ch).standard_normal(n_samples))
            ids.append(q.insert_recording(conn, "fake.mat", ch, fs, n_samples, 0, npy_path))
    finally:
        conn.close()
    return db_path, tmpdir, ids


def _widget_names(obj):
    """Every `name` reachable from a Panel object tree — used to assert on
    what actions a surface actually renders, including that nothing
    surrogate-related is present."""
    names = []

    def _walk(o):
        name = getattr(o, "name", None)
        if isinstance(name, str) and name:
            names.append(name)
        for attr in ("objects", "panels"):
            children = getattr(o, attr, None)
            if isinstance(children, (list, tuple)):
                for child in children:
                    _walk(child)
            elif isinstance(children, dict):
                for child in children.values():
                    _walk(child)

    _walk(obj)
    return names


def _lowpass_chain(recording_id=1):
    chain = ChainState(recording_id=recording_id)
    chain.add_step("preprocessing", "lowpass", params={"cutoff_hz": 0.05})
    return chain


# ── construction: a real layout, every pane non-None ─────────────────────────

def test_construction_returns_non_none_layout_with_all_panes():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    layout = surface.layout()
    assert layout is not None
    assert surface.estimate_pane is not None
    assert surface.routing_pane is not None
    assert surface.channel_scope is not None
    assert surface.band_scope is not None
    assert surface.local_button is not None
    assert surface.export_button is not None
    assert surface.cancel_button is not None
    assert surface.status is not None
    # The two actions + cancel are the buttons a researcher acts on.
    names = _widget_names(layout)
    assert "Run locally" in names
    assert "Export cluster job" in names
    assert "Cancel" in names


def test_empty_chain_does_not_crash_and_says_not_ready():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=ChainState(recording_id=1))
    layout = surface.layout()
    assert layout is not None
    assert "not ready" in surface.estimate_pane.object.lower() or "no steps" in surface.estimate_pane.object.lower()


# ── estimate: chain sum × fan-out width, shown before launch ────────────────

def test_estimate_display_includes_fanout_multiplier():
    from UI.workspaces.analyse.run_surface import RunSurface

    with scratch_calibration(mp_cost):
        mp_cost.calibrate("stump", n0=2000)
        chain = ChainState(recording_id=1)
        chain.add_step("detection", "matrix_profile",
                       params={"window_min": 10.0, "backend": "stump"})
        surface = RunSurface(_FakeApp(recording_id=1, fs=1.0, n_samples=4000), chain=chain)
        surface.channel_scope.options = {"CH0": "1", "CH1": "2", "CH2": "3"}
        surface.channel_scope.value = ["1", "2", "3"]
        surface._refresh()

        single = estimate_recipe_seconds(chain.to_recipe(), 4000, 1.0)
        assert single > 0
        assert surface._fanout_width == 3
        assert surface._estimate_seconds == pytest.approx(3 * single)
        assert "× 3" in surface.estimate_pane.object


# ── routing: export promoted above the ceiling, local demoted not removed ──

def test_export_cluster_job_promoted_above_ceiling_and_local_demoted_not_removed():
    from UI.workspaces.analyse.run_surface import RunSurface

    with scratch_calibration(mp_cost):
        mp_cost.calibrate("stump", n0=2000)
        chain = ChainState(recording_id=1)
        chain.add_step("detection", "matrix_profile",
                       params={"window_min": 10.0, "backend": "stump"})
        surface = RunSurface(
            _FakeApp(recording_id=1, fs=1.0, n_samples=10_000_000),
            chain=chain, ceiling_s=1.0,
        )
        surface._refresh()

        assert surface._route == "cluster"
        assert surface.export_button.button_type == "primary"
        assert surface.local_button.button_type == "default", \
            "local execution is demoted but must not be removed"
        names = _widget_names(surface.layout())
        assert "Run locally" in names, "local execution must still be present"


def test_local_remains_primary_below_ceiling():
    from UI.workspaces.analyse.run_surface import RunSurface

    with scratch_calibration(mp_cost):
        mp_cost.calibrate("stump", n0=2000)
        chain = ChainState(recording_id=1)
        chain.add_step("detection", "matrix_profile",
                       params={"window_min": 10.0, "backend": "stump"})
        surface = RunSurface(
            _FakeApp(recording_id=1, fs=1.0, n_samples=1000),
            chain=chain, ceiling_s=1e9,
        )
        surface._refresh()

        assert surface._route == "local"
        assert surface.local_button.button_type == "primary"
        assert surface.export_button.button_type == "default"


# ── scope selector: recordings/channels, span, bands feed ticket-25 fan-out ─

def test_scope_selector_channel_fanout_feeds_recipe():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    surface.channel_scope.options = {"CH0": "1", "CH1": "2", "CH2": "3"}
    surface.channel_scope.value = ["1", "2", "3"]
    recipe = surface._current_recipe()
    assert recipe["fan_out"] == {"kind": "channels", "targets": [1, 2, 3]}


def test_scope_selector_band_fanout_feeds_recipe():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    surface.band_scope.options = list(surface._band_targets)
    surface.band_scope.value = ["delta", "theta"]
    recipe = surface._current_recipe()
    assert recipe["fan_out"]["kind"] == "bands"
    assert [t["label"] for t in recipe["fan_out"]["targets"]] == ["delta", "theta"]
    assert all("low_hz" in t and "high_hz" in t for t in recipe["fan_out"]["targets"])


def test_scope_selector_span_feeds_recipe():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    surface.whole_channel.value = False
    surface.span_start.value = 100
    surface.span_end.value = 500
    recipe = surface._current_recipe()
    assert recipe["span"] == [100, 500]


# ── surrogate toggle (ticket 44) ─────────────────────────────────────────────

def test_surrogate_toggle_defaults_on_and_appears_on_surface():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    layout = surface.layout()

    assert surface.surrogate_toggle is not None
    assert surface.surrogate_toggle.value is True
    names = _widget_names(layout)
    assert any("surrogate" in str(n).lower() for n in names), \
        f"surrogate toggle must appear on the run surface; found: {names}"


def test_surrogate_toggle_default_on_is_recorded_in_the_recipe():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    recipe = surface._current_recipe()
    assert recipe["surrogate"] is True


def test_surrogate_toggle_off_is_recorded_in_the_recipe():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    surface.surrogate_toggle.value = False
    recipe = surface._current_recipe()
    assert recipe["surrogate"] is False


def test_on_run_finished_displays_detected_versus_surrogate_counts():
    from UI.workspaces.analyse.run_surface import RunSurface
    from Working.database import runs as run_db
    from Working.database import queries as q

    conn = init_db(":memory:")
    try:
        rec_id = q.insert_recording(conn, "fake.mat", 0, 1.0, 1000, 0, "fake.npy")
        config_id, _ = run_db.get_or_create_config(conn, {"steps": []})
        run_a = run_db.insert_run(conn, config_id, rec_id, 0, 1000, status="completed")
        run_b = run_db.insert_run(conn, config_id, rec_id, 0, 1000, status="completed")
        run_db.insert_detection(conn, run_a, 0, 10)
        run_db.insert_detection(conn, run_a, 20, 30)
        run_db.insert_detection(conn, run_b, 40, 50)

        surface = RunSurface(_FakeApp(conn=conn), chain=_lowpass_chain(rec_id))
        surface._on_run_finished({
            "run_id": run_a,
            "surrogate_run_id": run_b,
            "reused": False,
            "config_hash": "x",
        })

        assert "surrogate" in surface.status.object.lower()
        assert "2" in surface.status.object
        assert "1" in surface.status.object
    finally:
        conn.close()


# ── launch / cancel: ticket-24 background run ───────────────────────────────

def test_launch_starts_background_run_group_and_creates_run_rows():
    from UI.workspaces.analyse.run_surface import RunSurface

    db_path, tmpdir, ids = _fresh_db_with_channels(2)
    try:
        conn = init_db(db_path)
        try:
            chain = ChainState(recording_id=ids[0])
            chain.add_step("preprocessing", "lowpass", params={"cutoff_hz": 0.05})
            app = _FakeApp(recording_id=ids[0], fs=1.0, n_samples=200, conn=conn)
            surface = RunSurface(app, chain=chain)
            surface.channel_scope.options = {f"CH{i}": str(rid) for i, rid in enumerate(ids)}
            surface.channel_scope.value = [str(rid) for rid in ids]

            surface._on_run()
            deadline = time.time() + 30
            while surface._thread is not None and surface._thread.is_alive() and time.time() < deadline:
                time.sleep(0.02)
            time.sleep(0.05)  # grace for the completion callback to land

            assert "Done" in surface.status.object, surface.status.object
            n_groups = conn.execute("SELECT COUNT(*) FROM run_groups").fetchone()[0]
            assert n_groups == 1, "a fan-out launch must create exactly one run_groups row"
            n_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            assert n_runs == 4, (
                "a 2-channel fan-out with surrogate control on (the default) "
                "must create two original runs and two surrogate runs"
            )
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cancel_wires_cooperative_cancel_event():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    assert isinstance(surface._cancel_event, threading.Event)
    assert not surface._cancel_event.is_set()
    surface._on_cancel()
    assert surface._cancel_event.is_set()
    assert "Cancelling" in surface.status.object


# ── T32: progress indicator and per-stage results ──────────────────────────

def test_progress_and_stage_result_panes_are_present():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    layout = surface.layout()

    assert layout is not None
    assert surface.progress_pane is not None
    assert surface.stage_results is not None
    # Both start empty: no progress before a run, no stage results yet.
    assert surface.progress_pane.object == ""
    assert len(surface.stage_results.objects) == 0


def test_progress_indicator_appears_only_above_configured_threshold():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(
        _FakeApp(), chain=_lowpass_chain(), progress_threshold_s=60,
    )
    surface._estimate_seconds = 59.9
    surface._set_progress("Starting ...")
    assert surface.progress_pane.object == ""

    surface._estimate_seconds = 60.1
    surface._set_progress("Starting ...")
    assert "Estimated finish" in surface.progress_pane.object
    assert "Starting" in surface.progress_pane.object


def test_step_and_intra_step_progress_render_in_indicator():
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(
        _FakeApp(), chain=_lowpass_chain(), progress_threshold_s=1,
    )
    surface._estimate_seconds = 10.0
    surface._set_progress("Starting ...")

    surface._update_step_progress(0, 2, "preprocessing", "lowpass")
    assert "Step 1/2" in surface.progress_pane.object
    assert "preprocessing.lowpass" in surface.progress_pane.object

    surface._update_intra_step_progress(5, 10, "catch22")
    assert "catch22" in surface.progress_pane.object
    assert "5/10" in surface.progress_pane.object


def test_stage_results_append_and_earlier_stage_stays_inspectable():
    from Adapters.base import AdapterResult
    from UI.workspaces.analyse.run_surface import RunSurface

    surface = RunSurface(_FakeApp(), chain=_lowpass_chain())
    recipe = {"steps": [
        {"stage": "preprocessing", "algorithm": "lowpass", "params": {}},
        {"stage": "detection", "algorithm": "matrix_profile", "params": {}},
    ]}

    surface._clear_stage_results()
    surface._append_stage_result(
        0, AdapterResult(output_kind="signal", x=np.zeros(4)), recipe,
    )
    surface._append_stage_result(
        1, AdapterResult(output_kind="intervals", intervals=[(0, 2)]), recipe,
    )

    objects = surface.stage_results.objects
    assert len(objects) == 2
    assert "preprocessing.lowpass" in objects[0].object
    assert "detection.matrix_profile" in objects[1].object
    assert "1 detection" in objects[1].object


def test_launch_renders_stage_results_as_they_land():
    from UI.workspaces.analyse.run_surface import RunSurface

    db_path, tmpdir, ids = _fresh_db_with_channels(1)
    try:
        conn = init_db(db_path)
        try:
            chain = ChainState(recording_id=ids[0])
            chain.add_step("preprocessing", "lowpass", params={"cutoff_hz": 0.05})
            app = _FakeApp(recording_id=ids[0], fs=1.0, n_samples=200, conn=conn)
            surface = RunSurface(app, chain=chain)

            surface._on_run()
            deadline = time.time() + 30
            while surface._thread is not None and surface._thread.is_alive() \
                    and time.time() < deadline:
                time.sleep(0.02)
            time.sleep(0.05)  # grace for completion callbacks to land

            assert "Done" in surface.status.object, surface.status.object
            assert len(surface.stage_results.objects) == 1
            assert "preprocessing.lowpass" in surface.stage_results.objects[0].object
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── runner ───────────────────────────────────────────────────────────────────

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
        tally += f", {skipped} skipped"
    print(f"\n{tally}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
