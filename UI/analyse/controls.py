"""
Choosing what to run: stage, algorithm, span mode, preprocessing, and the
auto-generated parameter column those choices produce.
"""

import threading

import numpy as np
import panel as pn

from Adapters.registry import discover_adapters, get_adapter, list_adapters

from Working.database import queries as q
from Working.config import AUTO_PREVIEW_DEBOUNCE_MS
from Working.recipes import STAGES

from UI.window_matrix_panel import WindowMatrixPanel
from UI.analyse.param_widgets import _widget_for_param
from UI.analyse.ui_thread import _run_on_ui_thread


_WINDOW_MATRIX_ALGORITHM = "preprocessing.window_matrix"

# Populates the registry the stage/algorithm selects read from, at import of
# this package rather than at first use — `_on_stage_changed(None)` runs from
# `RunPanel.__init__` and needs a populated registry to have anything to offer.
discover_adapters()


class ControlsMixin:
    """Stage/algorithm/preprocessing selection and the parameter column."""

    def _build_control_widgets(self):
        self.stage_select = pn.widgets.Select(name="Stage", options=list(STAGES))
        self.algorithm_select = pn.widgets.Select(name="Algorithm", options=[])
        self.span_mode = pn.widgets.RadioButtonGroup(
            name="Span", options=["Current viewport", "Selected span", "Whole channel"],
            value="Current viewport",
        )
        # Part 6, 2e: a run-panel-level step, NOT a SAX (or any other
        # algorithm's) parameter — prepended as its own recipe step ahead
        # of whatever algorithm actually runs (see `_build_steps`), so the
        # recipe hash covers it and Run History shows what really ran.
        # Part 7, Part 4 item 2: the widget's OWN `name` is what Panel
        # renders as its label — a SEPARATE "Preprocessing (applied
        # first):" Markdown heading right above it (see `layout()`) would
        # just repeat the same text twice.
        self.preprocess_select = pn.widgets.Select(
            name="Mode", options=["none", "rolling_mean", "rolling_z", "linear"], value="none",
        )
        self.preprocess_window = pn.widgets.FloatInput(name="Window (s)", value=600.0, start=1.0, disabled=True)
        self.param_column = pn.Column()
        self.derived_pane = pn.pane.HTML("", sizing_mode="stretch_width")
        self.span_changed_note = pn.pane.Markdown("")
        self.reset_recommended_button = pn.widgets.Button(name="Reset to recommended", button_type="default")
        self.auto_preview_checkbox = pn.widgets.Checkbox(name="Auto-preview on parameter change", value=True)

    def _build_window_matrix_panel(self):
        # Constructed before the wiring below, since `_on_stage_changed(None)`
        # at the end of __init__ immediately fires `_on_algorithm_changed`,
        # which needs this to exist to toggle its visibility.
        self.window_matrix_panel = WindowMatrixPanel(self)

    def _on_stage_changed(self, _event):
        specs = list_adapters(stage=self.stage_select.value)
        self.algorithm_select.options = {s.display_name: s.name for s in specs}
        if specs:
            self.algorithm_select.value = specs[0].name
        self._on_algorithm_changed(None)

    def _on_algorithm_changed(self, _event):
        name = self.algorithm_select.value
        self.param_column.clear()
        self._recommended_values = {}
        self._param_base_names = {}
        # Part 6, 4f: a stale Encoding section from a PREVIOUS algorithm
        # (a run, or an auto-preview) must not linger once a different,
        # non-encoding algorithm is selected — the same "never show state
        # that no longer matches the current selection" rule as the
        # pre-run preview (Part 5 A2). Re-shown by an actual run/preview
        # of a new encoding-producing algorithm, never left stale.
        spec_for_visibility = get_adapter(name) if name else None
        if spec_for_visibility is None or spec_for_visibility.output_kind != "encoding":
            self.encoding_section.visible = False
        # §3.1: the window-matrix panel is hidden — not disabled, not shown
        # empty — unless this exact algorithm is selected. Extra controls
        # sit BESIDE the auto-generated param form, never special-cased
        # inside it.
        self.window_matrix_panel.set_visible(name == _WINDOW_MATRIX_ALGORITHM)
        if not name:
            self._param_widgets = {}
            self.derived_pane.object = ""
            return
        spec = get_adapter(name)
        widgets = [_widget_for_param(p) for p in spec.params]
        for w, p in zip(widgets, spec.params):
            # `_widget_for_param` already set the short, humanized label
            # and moved the long description to `w.description` (a hover
            # tooltip) — just remember it as the "unmodified" base name.
            self._param_base_names[p.name] = w.name
        self.param_column.objects = widgets
        self._param_widgets = dict(zip((p.name for p in spec.params), widgets))

        # Part 6, 4a/4b: every param widget refreshes the derive() readout,
        # the "(modified)" marker, and (debounced) the auto-preview on
        # every edit — one shared handler, not one-off per widget.
        for pname, w in self._param_widgets.items():
            w.param.watch(lambda e, n=pname: self._on_param_widget_changed(n), "value")

        self._apply_recommended_defaults(force=True)  # a fresh algorithm has no user edits yet
        # `_apply_recommended_defaults` only reaches `_refresh_derived()`
        # when `spec.recommend` is set — an algorithm with no `recommend`
        # (e.g. bandpass) would otherwise leave the PREVIOUS algorithm's
        # stale derive() table on screen indefinitely. Always refresh here.
        self._sync_trend_param_controls()
        self._refresh_derived()

        if name == _WINDOW_MATRIX_ALGORITHM:
            self._refresh_window_matrix_panel()

    def _refresh_window_matrix_panel(self):
        """Whatever the ladder/cost/coverage should reflect right now —
        called whenever the algorithm becomes `preprocessing.window_matrix`
        and whenever the span/recording changes while it's selected
        (`_on_span_context_changed`), so the panel is never stale against
        what a real run would actually do."""
        if not self.window_matrix_panel.visible:
            return
        if self.app._recording_id is None:
            self.window_matrix_panel.refresh(None, None)
            return
        recording = q.get_recording_by_id(self.conn, self.app._recording_id)
        try:
            span = self._current_span()
        except ValueError:
            span = None
        self.window_matrix_panel.refresh(recording, span)

    def _current_params(self):
        return {name: w.value for name, w in self._param_widgets.items()}

    # ── Part 6, 4a: span-aware recommended defaults ─────────────────────

    def _current_span_signal(self):
        """(x, t, fs, recording) for whatever `_current_span()` resolves
        to right now, loaded via mmap + slice (cheap — never the whole
        channel just to compute a recommendation). Returns None if no
        span can be resolved yet (e.g. nothing loaded)."""
        app = self.app
        if app._recording_id is None or app._fs is None:
            return None
        try:
            span = self._current_span()
        except ValueError:
            return None
        start, end = (0, app._n_samples) if span is None else span
        recording = q.get_recording_by_id(self.conn, app._recording_id)
        x_full = np.load(recording["npy_path"], mmap_mode="r")
        x = np.asarray(x_full[start:end])
        t = np.arange(start, end) / recording["fs"]
        return x, t, recording["fs"], recording

    def _on_preprocess_changed(self, _event=None):
        # Part 7, Part 4 item 3: window_s means nothing for mode="none" --
        # disabled (not hidden, so the sidebar doesn't reflow) whenever
        # there's no mode to apply it to.
        self.preprocess_window.disabled = self.preprocess_select.value == "none"
        self._refresh_derived()
        self._schedule_auto_preview()

    def _schedule_auto_preview(self):
        """Debounce `AUTO_PREVIEW_DEBOUNCE_MS`, then recompute an encoding
        PREVIEW — no DB writes, no `runs`/`configs` rows; the explicit Run
        button remains the only thing that records a run. No-op unless
        auto-preview is on and the selected algorithm is a SAX-family
        encoding — the only shape `_run_auto_preview`/`_show_encoding` know
        how to render, and (unlike SAX) neither matrix profile nor the
        window matrix are cheap enough to recompute on every keystroke
        anyway (see `_is_sax_shaped_encoding`)."""
        if self._auto_preview_timer is not None:
            self._auto_preview_timer.cancel()
        if not self.auto_preview_checkbox.value:
            return
        name = self.algorithm_select.value
        spec = get_adapter(name) if name else None
        if spec is None or spec.output_kind != "encoding" or not self._is_sax_shaped_encoding(name):
            return
        doc = pn.state.curdoc
        if doc is None:
            # No live session (a bare script or test) — there is no UI for
            # a delayed background recompute to safely reach, and firing
            # one anyway would touch `self.conn` from a thread that didn't
            # create it (sqlite3 forbids this). Callers that need the
            # preview outside a live session call `_run_auto_preview()`
            # directly instead (see tests/test_encoding_view.py).
            return

        def _fire():
            _run_on_ui_thread(doc, self._run_auto_preview)

        self._auto_preview_timer = threading.Timer(AUTO_PREVIEW_DEBOUNCE_MS / 1000.0, _fire)
        self._auto_preview_timer.daemon = True
        self._auto_preview_timer.start()

    def _run_auto_preview(self):
        """The debounced preview recompute itself — mirrors `_build_steps`
        exactly (same helper `_on_run` uses) so a preview can never show
        something a real Run wouldn't, but bypasses `execute_recipe`/the
        database entirely: SAX-family encodings are cheap enough (well
        under a second at the span sizes auto-preview defaults on for) to
        just run inline on the UI thread rather than spinning up a worker.

        Guarded here too, not just in `_schedule_auto_preview`'s caller —
        this is called directly by tests (and could be called directly by
        anything else) bypassing that gate. Calling `_show_encoding` for a
        non-SAX "encoding" adapter (matrix profile, the window matrix) is a
        real crash, not a cosmetic mismatch: their `result.meta` has no
        `"details"` key at all, so `result.meta["details"]` below raises
        `KeyError('details')` — confirmed live against
        `preprocessing.window_matrix` with auto-preview left on.
        """
        if self._thread is not None and self._thread.is_alive():
            return  # a real run is in progress -- don't fight it
        app = self.app
        if app._recording_id is None:
            return
        if not self._is_sax_shaped_encoding(self.algorithm_select.value):
            return
        try:
            span = self._current_span()
        except ValueError:
            return
        start, end = (0, app._n_samples) if span is None else span
        recording = q.get_recording_by_id(self.conn, app._recording_id)
        x_full = np.load(recording["npy_path"], mmap_mode="r")
        x = np.asarray(x_full[start:end])
        t = np.arange(start, end) / recording["fs"]
        try:
            steps = self._build_steps()
            for step in steps[:-1]:
                step_spec = get_adapter(f"{step['stage']}.{step['algorithm']}")
                step_params = step_spec.validate_params(step["params"])
                step_result = step_spec.run(x, t, recording["fs"], **step_params)
                x, t = step_result.x, step_result.t
            last_step = steps[-1]
            spec = get_adapter(f"{last_step['stage']}.{last_step['algorithm']}")
            params = spec.validate_params(last_step["params"])
            result = spec.run(x, t, recording["fs"], **params)
        except Exception as e:
            self.status.object = f"*Auto-preview failed: {e}*"
            return
        self.encoding_section.visible = True
        self._show_encoding(result.x, result.t, result.encoding, result.meta["details"], recording)
        self.status.object = "*Auto-preview shown below — not a run, nothing recorded. Click Run to record one.*"
