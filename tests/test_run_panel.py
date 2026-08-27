"""
test_run_panel.py
===================
Tests for Part 5 (2026-08): the Run algorithm tab's pre-run preview
(Section A) and the Before/After comparison's y-axis handling (Section B).

Real-data-gated (ViewerApp needs a real channel .npy), same convention as
tests/test_ribbon_panes.py. Always a fresh temp sqlite file, never
DATA/db/annotations.sqlite.

Run from the project root:
    python tests/test_run_panel.py
"""

import inspect
import os
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import panel as pn
pn.extension("tabulator")
import holoviews as hv
hv.extension("bokeh")

from Working.database.schema import init_db
from Working.database import queries as q
from UI.viewer import ViewerApp
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600
CENTER = 12_300


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_run_panel.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    conn.close()
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    return app, tf.name, rid


def _close_and_unlink(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


def _curve_x_extent(curve):
    """(t_min, t_max) of a single hv.Curve's underlying data — used to
    check WHICH span a preview curve actually shows without depending on
    exact opt internals."""
    t = curve.dimension_values(0)
    return float(t.min()), float(t.max())


# ── A1/A2: preview renders on arrival, single-plot vs. Before/After ────────

def test_preview_renders_on_arrival_with_a_staged_span():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._stage_span(1000, 1600, annotation_id=None)
        rp.span_mode.value = "Selected span"
        assert isinstance(rp.result_pane.object, hv.Curve), (
            "arriving with a staged span should show a single unprocessed-signal curve, "
            f"got {type(rp.result_pane.object)}"
        )
        assert "not yet processed" in rp.result_pane.object.opts.get("plot").kwargs.get("title", "").lower()
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        # end_idx is exclusive, so the last plotted sample is at 1599, not 1600.
        assert abs(t0 - 1000.0) < 1.0 and abs(t1 - 1599.0) < 1.0, (
            f"preview should span the staged sample range (1000-1600), got ({t0}, {t1})"
        )
    finally:
        _close_and_unlink(app, db_path)


def test_result_pane_never_shows_stale_single_plot_alongside_before_after():
    """A2: after `_show_before_after` runs, the pane holds the Layout pair
    (not the earlier single Curve); switching span context afterwards
    reverts it to a fresh single-plot preview, never leaving both."""
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recording = dict(q.get_recording_by_id(app.conn, rid))
        result_t = np.arange(1000, 1600) / recording["fs"]
        result_x = np.random.default_rng(0).normal(0, 1e-6, size=600)
        rp._show_before_after(recording, result_x, result_t)
        assert isinstance(rp.result_pane.object, hv.Layout), "after a run, expected the Before/After Layout"

        rp.span_mode.value = "Whole channel"
        assert isinstance(rp.result_pane.object, hv.Curve), (
            "changing span context after a run should replace the stale Before/After "
            f"pair with a fresh single-plot preview, got {type(rp.result_pane.object)}"
        )
    finally:
        _close_and_unlink(app, db_path)


# ── A4: span mode changes the preview ───────────────────────────────────────

def test_preview_updates_on_span_mode_change():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        # span_mode already defaults to "Current viewport" -- assigning the
        # SAME value wouldn't fire its param.watch, so simulate the real
        # trigger (arriving/re-arriving on the tab) explicitly instead.
        app._range_stream.event(x_range=(5000.0, 5100.0))
        app._refresh_view()
        rp._on_span_context_changed()
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        assert abs(t0 - 5000.0) < 1.0 and abs(t1 - 5099.0) < 1.0, (
            f"'Current viewport' preview should match the viewer's x_range, got ({t0}, {t1})"
        )

        rp.span_mode.value = "Whole channel"
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        assert t1 > 100000, f"'Whole channel' preview should span the full channel, got ({t0}, {t1})"
    finally:
        _close_and_unlink(app, db_path)


# ── A3: staged-row selection changes the preview ────────────────────────────

def test_preview_updates_on_staged_row_selection():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        app._stage_span(1000, 1600, annotation_id=None)
        app._stage_span(9000, 9600, annotation_id=None)
        rp.span_mode.value = "Selected span"

        # Nothing explicitly selected -> first row (1000-1600).
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        assert abs(t0 - 1000.0) < 1.0, f"expected first staged row by default, got ({t0}, {t1})"

        # Select the second row -> preview follows it.
        rp.staged_table.selection = [1]
        t0, t1 = _curve_x_extent(rp.result_pane.object)
        assert abs(t0 - 9000.0) < 1.0 and abs(t1 - 9599.0) < 1.0, (
            f"selecting staged row 1 should preview 9000-9600, got ({t0}, {t1})"
        )
        assert "2/2" in rp.preview_info.object, (
            f"preview_info should make clear which staged row is shown, got {rp.preview_info.object!r}"
        )
    finally:
        _close_and_unlink(app, db_path)


# ── B2/B3: independent vs. shared y-axis ────────────────────────────────────

def test_independent_yaxis_gives_each_panel_its_own_tight_range():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recording = dict(q.get_recording_by_id(app.conn, rid))
        result_t = np.arange(1000, 1600) / recording["fs"]
        # Tiny-amplitude "after" against the raw channel's much larger
        # DC-offset range as "before" -- the exact bandpass-filter scenario
        # from the bug report.
        result_x = np.random.default_rng(0).normal(0, 1e-6, size=600)

        assert rp.yaxis_mode.value == "Independent y-axis", "default must be independent (B2)"
        rp._show_before_after(recording, result_x, result_t)
        before_curve, after_curve = list(rp.result_pane.object.values())
        before_ylim = before_curve.opts.get("plot").kwargs["ylim"]
        after_ylim = after_curve.opts.get("plot").kwargs["ylim"]
        after_span = after_ylim[1] - after_ylim[0]
        before_span = before_ylim[1] - before_ylim[0]
        assert after_span < before_span / 100, (
            f"independent mode should give the tiny 'after' signal its own tight range, "
            f"got before={before_ylim} after={after_ylim}"
        )
        # B3: the numeric range is visible in each title.
        assert "y:" in before_curve.opts.get("plot").kwargs["title"]
        assert "y:" in after_curve.opts.get("plot").kwargs["title"]
        # B4: the scale-change note is populated.
        assert rp.scale_note.object != ""
    finally:
        _close_and_unlink(app, db_path)


def test_shared_yaxis_gives_both_panels_the_identical_combined_range():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recording = dict(q.get_recording_by_id(app.conn, rid))
        result_t = np.arange(1000, 1600) / recording["fs"]
        result_x = np.random.default_rng(0).normal(0, 1e-6, size=600)

        rp.yaxis_mode.value = "Shared y-axis"
        rp._show_before_after(recording, result_x, result_t)
        before_curve, after_curve = list(rp.result_pane.object.values())
        before_ylim = before_curve.opts.get("plot").kwargs["ylim"]
        after_ylim = after_curve.opts.get("plot").kwargs["ylim"]
        assert before_ylim == after_ylim, (
            f"shared mode should give both panels the identical combined range, "
            f"got before={before_ylim} after={after_ylim}"
        )
    finally:
        _close_and_unlink(app, db_path)


def test_yaxis_toggle_rerenders_last_result_without_rerunning():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recording = dict(q.get_recording_by_id(app.conn, rid))
        result_t = np.arange(1000, 1600) / recording["fs"]
        result_x = np.random.default_rng(0).normal(0, 1e-6, size=600)
        rp._show_before_after(recording, result_x, result_t)

        rp.yaxis_mode.value = "Shared y-axis"
        before_curve, after_curve = list(rp.result_pane.object.values())
        assert before_curve.opts.get("plot").kwargs["ylim"] == after_curve.opts.get("plot").kwargs["ylim"]

        rp.yaxis_mode.value = "Independent y-axis"
        before_curve, after_curve = list(rp.result_pane.object.values())
        assert before_curve.opts.get("plot").kwargs["ylim"] != after_curve.opts.get("plot").kwargs["ylim"]
    finally:
        _close_and_unlink(app, db_path)


# ── C3/C4: placeholders and motif-button gating ─────────────────────────────

def test_detections_placeholder_shown_before_first_run():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        assert rp.detections_table.visible is False
        assert rp.detections_placeholder.visible is True
        rp._show_detections([{"id": 1, "start_idx": 0, "end_idx": 10, "score": 0.5}])
        assert rp.detections_table.visible is True
        assert rp.detections_placeholder.visible is False
    finally:
        _close_and_unlink(app, db_path)


def test_motif_buttons_disabled_until_run_or_valid_span():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        assert rp.save_motif_button.disabled is True, "no detections yet -> disabled"

        rp.span_mode.value = "Whole channel"
        assert rp.save_viewport_motif_button.disabled is True, "'Whole channel' has no manual span"

        rp.span_mode.value = "Current viewport"
        assert rp.save_viewport_motif_button.disabled is False, "a real viewport is a valid manual span"

        rp._show_detections([{"id": 1, "start_idx": 0, "end_idx": 10, "score": 0.5}])
        rp._update_motif_button_states()  # real trigger is `_on_run_finished`; called directly here
        assert rp.save_motif_button.disabled is False, "detections now exist -> enabled"
    finally:
        _close_and_unlink(app, db_path)


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
            # `Skipped` derives from BaseException, not Exception, so it would
            # sail past the handler below and abort the whole standalone run on
            # the first guarded test. Absent data is a skip here too, not a pass.
            print(f"[SKIP] {fn.__name__}: {e}")
            skipped += 1
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    tally = f"{passed}/{len(fns)} passed"
    if skipped:
        # Never fold skips into the pass count: "all green" and "the data
        # was not there" are the two readings this file exists to keep
        # apart.
        tally += f", {skipped} skipped (real channel data absent)"
    print(f"\n{tally}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()


# ─────────────────────────────────────────────────────────────────────────
#  The detections table says what it is detections OF (2026-08 usability)
# ─────────────────────────────────────────────────────────────────────────
#
# `Working.execution` writes a `detections` row for every span in ANY step
# whose `output_kind` is 'spanset' -- so the table's contents depend on
# which block in the chain produced them, and the table showed only
# id/start_idx/end_idx/score with no mention of the block, the units, or
# the recording. Reported as "it is unclear what the detections table is
# actually recording detections of".


def test_detections_caption_names_the_block_that_produced_them():
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        rp._last_recipe = {
            "recording_id": rid,
            "span": (0, 100),
            "steps": [
                {"stage": "preprocessing", "algorithm": "lowpass", "params": {}},
                {"stage": "detection", "algorithm": "spike_v1", "params": {}},
            ],
        }
        rp._show_detections([{"id": 1, "start_idx": 0, "end_idx": 10, "score": 0.5}])

        caption = rp.detections_caption.object
        assert "detection.spike_v1" in caption, (
            f"the caption must name the block whose spanset these are, got {caption!r}"
        )
        assert "sample" in caption.lower(), (
            f"the caption must say what start_idx/end_idx are counted in, got {caption!r}"
        )
    finally:
        _close_and_unlink(app, db_path)


def test_detections_caption_is_blank_before_any_run():
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        assert app.run_panel.detections_caption.object == ""
    finally:
        _close_and_unlink(app, db_path)


# ── T62: filmstrip renders the chain input and every step ───────────────────

def test_filmstrip_renders_input_and_each_step_with_non_none_panes():
    """The Run algorithm surface must render the chain's input at the top and
    one plot per step below it, in execution order, with no blank panes.

    This is a headless construction test: it does not run a recipe, it hands
    the surface a multi-step recipe and the typed per-step results a run would
    produce, and asserts the returned HoloViews Layout contains an input curve
    plus one non-`None` element per step — the silently-blank-pane failure mode
    this codebase has hit twice must fail here, not on a human's screen.
    """
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    from Adapters.base import AdapterResult
    from Working.types import Signal, SpanSet
    from UI.analyse.chain_state import ChainState

    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recipe = {
            "recording_id": rid,
            "span": [1000, 1600],
            "steps": [
                {"stage": "preprocessing", "algorithm": "lowpass", "params": {}},
                {"stage": "detection", "algorithm": "rupture", "params": {}},
            ],
        }
        step_results = {
            0: AdapterResult("signal", Signal(x=np.arange(600) / 1.0, fs=1.0), {}),
            1: AdapterResult("spanset", SpanSet(starts=(10, 20), ends=(30, 40)), {}),
        }
        input_value = Signal(x=np.arange(600) / 1.0, fs=1.0)

        layout = rp._build_filmstrip(recipe, step_results, input_value=input_value)

        assert layout is not None, "the filmstrip must return a HoloViews Layout"
        panes = list(layout.values())
        assert len(panes) == 3, (
            f"expected the chain input plus one pane per step (3), got {len(panes)}"
        )
        assert all(pane is not None for pane in panes), (
            "every filmstrip pane must be a non-None renderable object"
        )

        # The order must match the headless plan, with the chain input first.
        plan = ChainState.from_recipe(recipe).filmstrip_plan(rp.conn)
        assert [entry["position"] for entry in plan] == [0, 1]
        assert isinstance(panes[0], hv.Curve), "the chain input must render as a signal curve"
        assert isinstance(panes[1], hv.Curve), "a signal-producing step must render as a curve"
        assert isinstance(panes[2], hv.Rectangles), (
            "a spanset-producing step must render as an interval overlay, not a blank pane"
        )

        # Each plot is labelled with the block that produced it and its type.
        titles = [str(pane.opts.get("plot").kwargs.get("title", "")) for pane in panes]
        assert "chain input" in titles[0].lower(), titles
        assert "lowpass" in titles[1].lower() and "signal" in titles[1].lower(), titles
        assert "rupture" in titles[2].lower() and "spanset" in titles[2].lower(), titles

        # The surface itself must expose the filmstrip pane, not just a helper.
        assert rp.filmstrip_pane is not None
        rp._show_filmstrip(recipe, step_results, input_value=input_value)
        assert rp.filmstrip_pane.object is not None
        assert len(list(rp.filmstrip_pane.object.values())) == 3
    finally:
        _close_and_unlink(app, db_path)


# ── T64: re-run only the suffix when a parameter changes ─────────────────────

def test_suffix_recompute_plan_reruns_middle_step_and_successors():
    """T64: a parameter change on a middle step recomputes that step and
    every step after it — never an earlier step. The recomputed set is the
    suffix derived from T63's `invalidated_step_indices`; this test pins the
    RunPanel's use of that rule for a middle step of a multi-step chain."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recipe = {
            "recording_id": rid,
            "span": [1000, 1600],
            "steps": [
                {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
                {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.10}},
                {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.15}},
            ],
        }
        plan = rp._suffix_recompute_plan(recipe, 1)
        assert plan["indices"] == {1, 2}, (
            f"a change on the middle step must recompute that step and its "
            f"successor, never the earlier step; got {plan['indices']}"
        )
        assert 0 not in plan["indices"]
        # No calibrated estimator on these blocks → the suffix is free, so it
        # runs automatically (below the interactive budget).
        assert plan["estimate_s"] == 0
        assert plan["requires_confirmation"] is False
    finally:
        _close_and_unlink(app, db_path)


def test_suffix_recompute_plan_expensive_suffix_requires_confirmation():
    """T64: a suffix whose summed estimate is above the interactive budget
    must ask first, reporting the estimate — the existing estimator and the
    existing interactive-budget constant, not a second cost model."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    from tests._calibration_isolation import scratch_calibration
    from Working.Detection.matrix_profiling import cost as mp_cost

    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        with scratch_calibration(mp_cost):
            mp_cost.calibrate("stump", n0=2000)
            recipe = {
                "recording_id": rid,
                "span": [0, 10_000_000],
                "steps": [
                    {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
                    {"stage": "detection", "algorithm": "matrix_profile",
                     "params": {"window_min": 10.0, "backend": "stump"}},
                ],
            }
            plan = rp._suffix_recompute_plan(recipe, 1)
            assert plan["indices"] == {1}
            assert plan["estimate_s"] is not None and plan["estimate_s"] > 0
            assert plan["requires_confirmation"] is True
    finally:
        _close_and_unlink(app, db_path)


def test_filmstrip_marks_stale_steps_while_rerun_in_flight():
    """T64: plots for steps being recomputed are visibly marked stale — the
    suffix steps are flagged in the filmstrip while a re-run is in flight,
    and the unaffected prefix is not."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    from Adapters.base import AdapterResult
    from Working.types import Signal, SpanSet

    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        recipe = {
            "recording_id": rid,
            "span": [1000, 1600],
            "steps": [
                {"stage": "preprocessing", "algorithm": "lowpass", "params": {}},
                {"stage": "detection", "algorithm": "rupture", "params": {}},
            ],
        }
        step_results = {
            0: AdapterResult("signal", Signal(x=np.arange(600) / 1.0, fs=1.0), {}),
            1: AdapterResult("spanset", SpanSet(starts=(10, 20), ends=(30, 40)), {}),
        }
        input_value = Signal(x=np.arange(600) / 1.0, fs=1.0)

        layout = rp._build_filmstrip(
            recipe, step_results, input_value=input_value, stale_indices={1},
        )
        # The layout is [chain input, step 0, step 1], so a `stale_indices`
        # of {1} marks the LAST element. The prefix step 0 — the one whose
        # cached result is still valid — must stay unmarked; that, not the
        # chain input, is the negative case worth asserting.
        titles = [str(p.opts.get("plot").kwargs.get("title", "")) for p in layout.values()]
        assert "stale" in titles[2].lower(), titles
        assert "stale" not in titles[1].lower(), titles
        assert "stale" not in titles[0].lower(), titles
    finally:
        _close_and_unlink(app, db_path)


# ── T64: editing a parameter launches the suffix, when opted in ──────────────
#
# Wiring the plan to an actual trigger. The opt-in is the card's OWN checkbox,
# not `DeriveMixin.auto_preview_checkbox`: the mixin reassigns that one from the
# span length every time recommendations are applied, so a researcher who turned
# it off would find it back on after changing span. An opt-in that reverts by
# itself is not an opt-in.


def _chain_card(app, recording_id, steps):
    """A builder card over a chain of `steps`, plus that card's chain.

    `recording_id` is set explicitly: a fresh `ViewerApp` has none selected,
    and a chain without one cannot serialise to a recipe at all.
    """
    builder = app.chain_builder
    builder.chain.recording_id = recording_id
    builder.chain.steps = []
    for stage, algorithm, params in steps:
        builder.chain.add_step(stage, algorithm, params=params)
    builder._refresh()
    return builder


def _capture_launches(rp):
    """Record `_launch_recipe` calls instead of starting a run."""
    calls = []
    rp._launch_recipe = lambda recipe, stale_indices=(): calls.append(
        {"recipe": recipe, "stale_indices": set(stale_indices)}
    )
    return calls


def test_param_edit_does_not_launch_a_run_when_auto_run_is_off():
    """Off by default: a stray keystroke in a parameter box must never start
    work. This is the whole reason the trigger is opt-in."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        calls = _capture_launches(rp)
        builder = _chain_card(app, rid, [
            ("preprocessing", "lowpass", {}),
            ("preprocessing", "lowpass", {}),
        ])
        card = builder.editors[1]
        assert card.auto_run_checkbox.value is False, "auto-run must default to off"

        pname = next(iter(card._param_widgets))
        card._on_param_changed(pname)
        assert calls == [], "a parameter edit launched a run with auto-run off"
    finally:
        _close_and_unlink(app, db_path)


def test_cheap_suffix_launches_and_marks_only_the_suffix_stale():
    """Opted in and cheap: it just runs, and only the suffix is marked stale."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        calls = _capture_launches(rp)
        builder = _chain_card(app, rid, [
            ("preprocessing", "lowpass", {}),
            ("preprocessing", "lowpass", {}),
            ("preprocessing", "lowpass", {}),
        ])
        card = builder.editors[1]
        card.auto_run_checkbox.value = True

        pname = next(iter(card._param_widgets))
        card._on_param_changed(pname)

        assert len(calls) == 1, f"expected exactly one launch, got {len(calls)}"
        assert calls[0]["stale_indices"] == {1, 2}, calls[0]["stale_indices"]
        assert rp.confirm_rerun_button.visible is False
    finally:
        _close_and_unlink(app, db_path)


def test_expensive_suffix_asks_before_launching():
    """Opted in but expensive: nothing runs, the estimate is stated, and the
    confirm control appears. Losing an afternoon to a keystroke is the thing
    being prevented."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    from tests._calibration_isolation import scratch_calibration
    from Working.Detection.matrix_profiling import cost as mp_cost

    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        calls = _capture_launches(rp)
        with scratch_calibration(mp_cost):
            mp_cost.calibrate("stump", n0=2000)
            builder = _chain_card(app, rid, [
                ("preprocessing", "lowpass", {}),
                ("detection", "matrix_profile",
                 {"window_min": 10.0, "backend": "stump"}),
            ])
            builder.chain.span = (0, 10_000_000)
            card = builder.editors[1]
            card.auto_run_checkbox.value = True

            pname = next(iter(card._param_widgets))
            card._on_param_changed(pname)

            assert calls == [], "an expensive suffix launched without asking"
            assert rp.confirm_rerun_button.visible is True
            assert "estimate" in rp.status.object.lower(), rp.status.object
    finally:
        _close_and_unlink(app, db_path)


def test_confirming_launches_the_suffix_that_was_held():
    """The held suffix is exactly what runs when the researcher confirms."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    from tests._calibration_isolation import scratch_calibration
    from Working.Detection.matrix_profiling import cost as mp_cost

    app, db_path, rid = _fresh_app()
    try:
        rp = app.run_panel
        calls = _capture_launches(rp)
        with scratch_calibration(mp_cost):
            mp_cost.calibrate("stump", n0=2000)
            builder = _chain_card(app, rid, [
                ("preprocessing", "lowpass", {}),
                ("detection", "matrix_profile",
                 {"window_min": 10.0, "backend": "stump"}),
            ])
            builder.chain.span = (0, 10_000_000)
            card = builder.editors[1]
            card.auto_run_checkbox.value = True
            card._on_param_changed(next(iter(card._param_widgets)))
            assert calls == []

            rp._on_confirm_rerun(None)
            assert len(calls) == 1, "confirming did not launch the held suffix"
            assert calls[0]["stale_indices"] == {1}
            assert rp.confirm_rerun_button.visible is False, "control stayed visible"
    finally:
        _close_and_unlink(app, db_path)
