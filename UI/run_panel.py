"""
run_panel.py
==============
The run panel (5a), before/after comparison (5b), and save-as-motif (5d)
views. One component because they share so much live state (the current
recipe, the last run's result) that splitting them would just mean passing
the same handful of things back and forth.

Auto-generates parameter controls from each `AdapterSpec.params` list — no
hand-built form per algorithm (adding an algorithm is one new file in
`Adapters/`, zero UI changes, per the brief). Long-running recipes execute
in a background thread so the UI stays responsive; cancellation is checked
between steps (an in-progress numpy/scipy call can't be interrupted
mid-flight — see `Working.execution.execute_recipe`'s `should_cancel`).
"""

import re
import threading
import time

import holoviews as hv
import numpy as np
import pandas as pd
import panel as pn

from Adapters.registry import discover_adapters, get_adapter, list_adapters
from Adapters._sax_common import diagnostic_rows, segment_plan
from Adapters.detection_sax_dsax import (
    NOISE_FLOOR_MAX_SAMPLES, NOISE_FLOOR_RATIO_ALERT, delta_diagnostic_rows,
    noise_floor_surrogate_count,
)
from Working.artifacts import save_plot
from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.database import vocabulary as v
from Working.config import (
    AUTO_PREVIEW_DEBOUNCE_MS, AUTO_PREVIEW_SPAN_THRESHOLD, ENCODING_RECOMPUTE_MAX_SAMPLES,
    ENCODING_STRING_INLINE_THRESHOLD, RUN_PREVIEW_HEIGHT, UI_TABLE_FONT_SIZE,
)
from Working.encoding_cache import build_encoding_path, read_encoding_file
from Working.execution import RecipeCancelled, RecipeExecutionError, execute_recipe
from Working.recipes import STAGES, make_recipe, recipe_summary
from Working.Detection.sax.dsax_python.dsax import (
    same_band_halfwidth, same_fraction_under_halfwidth, working_domain_array,
)
from Working.Detection.sax.dsax_python.trend_estimators import surrogate_same_halfwidth
from UI.plots import (
    build_encoding_panels, build_peek_curve, compute_display_y_range, cutline_domain,
    format_scale_viewed, same_symbol_index, segment_time_edges, style_main_plot_frame,
    symbol_cmap_name, symbol_colors, symbol_label, symbol_letters, symbol_names,
    symbols_to_rle, symbols_to_string, value_axis_label,
    CURVE_COLOR, ENCODING_HIGHLIGHT_CAP, HighlightStream, PLOT_FONTSIZE,
)
from UI.window_matrix_panel import WindowMatrixPanel

_WINDOW_MATRIX_ALGORITHM = "preprocessing.window_matrix"

discover_adapters()

# The sharkfin from the tag vocabulary, pre-loaded into the morphology
# search box so the feature explains itself rather than presenting an
# empty box with no clue what belongs in it.
DEFAULT_MORPHOLOGY_PATTERN = "UD{3,}"

_SEVERITY_STYLE = {
    "": "",
    "warn": "background:#fff3cd;color:#7a5b00;",
    "error": "background:#f8d7da;color:#7a1f28;",
}


def _rows_to_html(rows):
    """(label, value, severity) rows -> a compact read-only HTML table,
    warn rows amber and error rows red (Part 6, 4b) — plain HTML rather
    than a Tabulator since this is a small, purely read-only readout with
    no interaction, recomputed on every parameter change."""
    if not rows:
        return ""
    trs = []
    for label, value, severity in rows:
        style = _SEVERITY_STYLE.get(severity, "")
        trs.append(
            f'<tr style="{style}"><td style="padding:2px 8px 2px 0;white-space:nowrap;'
            f'font-weight:600;">{label}</td><td style="padding:2px 0;">{value}</td></tr>'
        )
    return f'<table style="border-collapse:collapse;font-size:{UI_TABLE_FONT_SIZE};">{"".join(trs)}</table>'


def _format_duration_human(seconds):
    """Space-separated variant of `UI.plots.format_scale_viewed` for a
    table cell / preview caption (Part 5, Sections A/C) — reuses that
    function's exact thresholds and rounding (so "10 min" here and the
    zoom-span label on an annotation always describe the same span
    identically) rather than a second, independently-tuned formatter."""
    label = format_scale_viewed((0.0, seconds), (0.0, seconds))
    for i, ch in enumerate(label):
        if ch.isalpha():
            return f"{label[:i]} {label[i:]}"
    return label


def _humanize_param_name(name):
    """"seconds_per_symbol" -> "Seconds per symbol" (Part 7, Part 3 item
    6) — short enough not to truncate mid-word; the long explanation
    moves to the widget's `description` tooltip instead of living in the
    label text itself."""
    return name.replace("_", " ").capitalize()


def _widget_for_param(p):
    """Build the auto-generated control for one ParamSpec. `description`
    (Part 7, Part 3 item 6) renders as a small hover-help icon next to a
    SHORT label, rather than the long explanation being crammed into the
    label text itself — the previous
    "seconds_per_symbol — Live when segment_mode='seconds_per_symbol'"
    labels truncated mid-word in the sidebar."""
    name = _humanize_param_name(p.name)
    if p.type is bool:
        # pn.widgets.Checkbox has no `description` param (unlike every
        # other widget type here) in this Panel version — the long
        # explanation, if any, stays appended to the label for booleans
        # only, since there's nowhere else to put it.
        return pn.widgets.Checkbox(name=f"{name} — {p.description}" if p.description else name, value=p.default)
    if p.choices is not None:
        return pn.widgets.Select(name=name, options=list(p.choices), value=p.default, description=p.description)
    if p.type is int:
        kwargs = {}
        if p.min is not None:
            kwargs["start"] = int(p.min)
        if p.max is not None:
            kwargs["end"] = int(p.max)
        return pn.widgets.IntInput(name=name, value=p.default, description=p.description, **kwargs)
    if p.type is float:
        kwargs = {}
        if p.min is not None:
            kwargs["start"] = float(p.min)
        if p.max is not None:
            kwargs["end"] = float(p.max)
        return pn.widgets.FloatInput(name=name, value=p.default, description=p.description, **kwargs)
    return pn.widgets.TextInput(name=name, value=str(p.default), description=p.description)


def _run_on_ui_thread(doc, fn):
    """Schedule `fn` to run on the Bokeh document's own thread (required for
    thread-safe widget updates from a background thread) — `doc` must be
    captured via `pn.state.curdoc` on the *serving* thread before spawning
    the background thread; querying it from inside the background thread
    itself returns nothing useful. Falls back to calling `fn` directly if
    there's no live session (a script or test)."""
    if doc is not None:
        doc.add_next_tick_callback(fn)
    else:
        fn()


class RunPanel:
    def __init__(self, app):
        # `app` is the owning ViewerApp — this panel reads its *current*
        # recording/viewport/selection live rather than duplicating that
        # state, since a run is always "on whatever channel/span is on
        # screen right now".
        self.app = app
        self.conn = app.conn

        self._thread = None
        self._cancel_event = threading.Event()
        self._last_run_result = None
        self._last_recipe = None
        self._last_recording = None

        # Part 6, 4a: recommend()/derive() bookkeeping — `_recommended_values`
        # is the LAST recommendation applied, used both to detect whether the
        # user has edited a widget away from it (per-widget "(modified)"
        # marker) and to decide whether a span change may silently re-apply
        # new recommended values (only when NOTHING has been touched yet).
        self._recommended_values = {}
        self._recommended_preprocess_window = None
        self._param_base_names = {}
        self._auto_preview_timer = None
        self._syncing_segment_controls = False  # re-entrancy guard for _sync_segment_mode_controls
        self._suppress_param_watchers = False   # see `_on_param_widget_changed`
        self._noise_floor_thread = None
        self._last_encoding = None  # (x, t, symbols, details, recording) for zoom-toggle/motif-seed re-render without re-running
        self._enc_range_stream = None  # the encoding view's shared RangeX stream (Part 6 3b) -- read by the "Visible range only" toggle

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
        self.run_button = pn.widgets.Button(name="Run", button_type="primary")
        self.cancel_button = pn.widgets.Button(name="Cancel", button_type="danger", disabled=True)
        self.status = pn.pane.Markdown("")
        self.duration_pane = pn.pane.Markdown("")

        # Part 5, Section A: a single pane that holds EITHER the pre-run
        # "staged span" preview OR the post-run Before/After pair, never
        # both — see `_refresh_preview`/`_show_before_after`, the only two
        # places that assign `result_pane.object`.
        self.result_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.preview_info = pn.pane.Markdown("")
        self.yaxis_mode = pn.widgets.RadioButtonGroup(
            name="Y-axis", options=["Independent y-axis", "Shared y-axis"],
            value="Independent y-axis",
        )
        self.scale_note = pn.pane.Markdown("")
        self._last_before_after = None  # (recording, result_x, result_t) for the y-axis toggle to re-render without re-running

        # Part 6/7, Section 3: the encoding inspection view — an entire
        # section, hidden (not shown empty) whenever the last run's
        # output_kind isn't "encoding" (Part 4f). `encoding_section` wraps
        # every widget below so `.visible` toggles the whole thing at once.
        self.enc_preprocessing_banner = pn.pane.Markdown("", styles={"display": "none"})
        self.enc_signal_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.enc_paa_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.enc_quant_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.enc_colour_key = pn.pane.HTML("", sizing_mode="stretch_width")
        self.enc_strip_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.enc_yaxis_mode = pn.widgets.RadioButtonGroup(
            options=["Auto-scale each panel", "Match the signal panel"], value="Auto-scale each panel",
        )
        self.enc_view_toggle = pn.widgets.RadioButtonGroup(
            options=["Whole span", "Visible range only"], value="Whole span",
        )
        self.enc_string_pane = pn.widgets.TextAreaInput(
            name="Symbol string", value="", disabled=True, height=100, sizing_mode="stretch_width",
        )
        self.enc_string_info = pn.pane.Markdown("")
        self.enc_copy_button = pn.widgets.Button(name="Copy", button_type="default", width=80)
        self.enc_rle_pane = pn.widgets.TextAreaInput(
            name="Run-length encoded", value="", disabled=True, height=70, sizing_mode="stretch_width",
        )
        self.enc_rle_info = pn.pane.Markdown("")
        self.enc_diagnostics_pane = pn.pane.HTML("", sizing_mode="stretch_width")
        self.enc_legend_pane = pn.pane.HTML("", sizing_mode="stretch_width")
        self.enc_seed_motif_button = pn.widgets.Button(
            name="Save this encoding as a motif seed", button_type="success",
        )
        self.enc_seed_motif_status = pn.pane.Markdown("")

        # ── Morphology regex search (dSAX Phase F) ───────────────────────
        # Deliberately visible for EVERY encoding, not just trend ones — a
        # cSAX string is just as searchable, and gating it on the domain
        # would be an arbitrary restriction on a feature that costs
        # nothing to offer.
        self.enc_search_input = pn.widgets.TextInput(
            name="Morphology pattern (regex over the symbol string)",
            value=DEFAULT_MORPHOLOGY_PATTERN, sizing_mode="stretch_width",
        )
        self.enc_search_button = pn.widgets.Button(name="Find", button_type="primary", width=80)
        self.enc_search_clear_button = pn.widgets.Button(name="Clear", width=80)
        self.enc_search_prev_button = pn.widgets.Button(name="< Prev", width=80, disabled=True)
        self.enc_search_next_button = pn.widgets.Button(name="Next >", width=80, disabled=True)
        self.enc_search_status = pn.pane.Markdown(
            f"*`{DEFAULT_MORPHOLOGY_PATTERN}` is the sharkfin pattern: one sharp rise, "
            "then a sustained fall. Searches the WHOLE span, not just the visible range.*"
        )
        self._search_matches = []      # [(seg_start, seg_end)] over the whole span
        self._search_index = -1        # which match the view is currently centred on
        self._search_summary = ""      # match count + cap notice, re-rendered on every step
        self._enc_highlight_stream = None

        # ── Noise-floor estimate (dSAX Phase D) ──────────────────────────
        # Hidden for amplitude-domain encodings: a surrogate half-width is
        # a statement about a delta distribution and has no meaning for a
        # PAA one.
        self.enc_noise_floor_button = pn.widgets.Button(
            name="Estimate noise floor", button_type="default",
            description=(
                "Draws phase-randomised surrogates of this exact span and measures how big a "
                "per-segment rise appears with NO trend present. Surrogate COUNT is reduced on "
                "long spans (never the span itself, which would change the spectrum the null "
                f"depends on); disabled above {NOISE_FLOOR_MAX_SAMPLES:,} samples."
            ),
        )
        self.enc_noise_floor_alpha = pn.widgets.FloatInput(
            name="alpha", value=0.95, start=0.5, end=0.9999, step=0.01, width=90,
            description=(
                "Quantile of the surrogate |rise| distribution to call the noise floor. "
                "0.95 means 'a rise this big happens by chance in 5% of trend-free segments'. "
                "The right false-positive rate is a scientific choice, not a constant."
            ),
        )
        self.enc_noise_floor_status = pn.pane.Markdown("")
        # Part 7, Part 4 item 5: a collapsible Card (expanded by default)
        # so the controls and the alphabet table don't require heavy
        # scrolling between them; diagnostics + alphabet sit side by side
        # rather than stacked.
        self.encoding_section = pn.Card(
            self.enc_preprocessing_banner,
            pn.pane.Markdown("**Y-axis:**"), self.enc_yaxis_mode,
            self.enc_signal_pane, self.enc_paa_pane, self.enc_quant_pane,
            self.enc_colour_key, self.enc_strip_pane,
            self.enc_view_toggle,
            self.enc_string_pane, self.enc_string_info,
            pn.Row(self.enc_copy_button),
            self.enc_rle_pane, self.enc_rle_info,
            pn.pane.Markdown("**Find a morphology:**"),
            self.enc_search_input,
            pn.Row(self.enc_search_button, self.enc_search_clear_button,
                   self.enc_search_prev_button, self.enc_search_next_button),
            self.enc_search_status,
            pn.Row(
                pn.Column(pn.pane.Markdown("**Diagnostics:**"), self.enc_diagnostics_pane),
                pn.Column(pn.pane.Markdown("**Alphabet:**"), self.enc_legend_pane),
                sizing_mode="stretch_width",
            ),
            pn.Row(self.enc_noise_floor_button, self.enc_noise_floor_alpha),
            self.enc_noise_floor_status,
            pn.Row(self.enc_seed_motif_button, self.enc_seed_motif_status),
            title="Encoding", collapsed=False, visible=False, sizing_mode="stretch_width",
        )

        self.save_plot_button = pn.widgets.Button(
            name="Save plot", button_type="default", disabled=True,
        )
        self.save_plot_status = pn.pane.Markdown("")
        self.detections_placeholder = pn.pane.Markdown("*No run yet.*")
        self.detections_table = pn.widgets.Tabulator(
            pd.DataFrame(columns=["id", "start_idx", "end_idx", "score"]),
            page_size=8, disabled=True, selectable=1,
            show_index=False, sizing_mode="stretch_width", visible=False,
        )

        # Save-as-motif controls
        self.motif_label = pn.widgets.TextInput(name="Label")
        self.motif_elements = pn.widgets.MultiChoice(name="element tags", options=[])
        self.motif_rating = pn.widgets.IntSlider(name="Rating", start=0, end=5, value=0)
        self.motif_notes = pn.widgets.TextAreaInput(name="Notes")
        self.save_motif_button = pn.widgets.Button(
            name="Save selected detection as motif", button_type="success", disabled=True,
        )
        self.save_viewport_motif_button = pn.widgets.Button(
            name="Save current selection as motif (no detection needed)", button_type="default",
            disabled=True,
        )
        self.motif_gate_note = pn.pane.Markdown(
            "*Run something (to save a detection) or pick a span above "
            "via 'Selected span'/'Current viewport' (to save it directly) "
            "before saving a motif.*"
        )
        self.motif_status = pn.pane.Markdown("")

        # Staged-spans basket (Part 3) — a shared, in-memory list living on
        # `app._staged_spans`; this panel only VIEWS and edits it, it
        # doesn't own the data. Deliberately no "run all staged" wiring
        # yet: this part only needs the spans to arrive here and be listed
        # correctly, not to execute — see the brief.
        self.staged_badge = pn.pane.Markdown("**Staged: 0**")
        self.staged_table = pn.widgets.Tabulator(
            pd.DataFrame(columns=["source_file", "channel", "start_idx", "end_idx", "duration", "annotation_id"]),
            page_size=6, disabled=True, selectable="checkbox",
            show_index=False, sizing_mode="stretch_width",
            layout="fit_columns",  # Part 5 C1: fit the sidebar's fixed width
            # exactly, no horizontal scrollbar, rather than "fitData"'s
            # natural-content widths that clipped start_idx/end_idx.
            hidden_columns=["annotation_id"],  # still in the underlying
            # data (e.g. for a future "jump to annotation" action) but not
            # one of the columns the brief asked to fit without scrolling
            # (source_file/channel/start_idx/end_idx/duration) — showing it
            # too left every column, including the ones that matter, too
            # narrow to read.
            widths={"source_file": "24%", "channel": "10%", "start_idx": "20%",
                    "end_idx": "20%", "duration": "26%"},
        )
        self.remove_staged_button = pn.widgets.Button(name="Remove selected", button_type="default")
        self.clear_staged_button = pn.widgets.Button(name="Clear all staged", button_type="default")

        # Constructed before the wiring below, since `_on_stage_changed(None)`
        # at the end of __init__ immediately fires `_on_algorithm_changed`,
        # which needs this to exist to toggle its visibility.
        self.window_matrix_panel = WindowMatrixPanel(self)

        self.stage_select.param.watch(self._on_stage_changed, "value")
        self.algorithm_select.param.watch(self._on_algorithm_changed, "value")
        self.run_button.on_click(self._on_run)
        self.cancel_button.on_click(self._on_cancel)
        self.save_motif_button.on_click(self._on_save_detection_as_motif)
        self.save_viewport_motif_button.on_click(self._on_save_viewport_as_motif)
        self.save_plot_button.on_click(self._on_save_plot)
        self.remove_staged_button.on_click(self._on_remove_staged)
        self.clear_staged_button.on_click(self._on_clear_staged)

        # Part 5, Section A: anything that changes WHICH span would
        # actually be run must refresh the preview (A4) and the save-as-
        # motif gating (C4) — never a duplicate, independent recomputation
        # (A5), always through `_refresh_preview`/`_current_span`.
        self.span_mode.param.watch(self._on_span_context_changed, "value")
        self.staged_table.param.watch(self._on_span_context_changed, "selection")
        self.yaxis_mode.param.watch(self._on_yaxis_mode_changed, "value")

        # Part 6, 4a/4b/4c: a span/preprocessing change re-derives
        # recommended defaults; any of these also refresh the read-only
        # `derive()` table and (debounced) the auto-preview.
        self.reset_recommended_button.on_click(lambda _e: self._apply_recommended_defaults(force=True))
        self.preprocess_select.param.watch(self._on_preprocess_changed, "value")
        self.preprocess_window.param.watch(self._on_preprocess_changed, "value")
        self.enc_view_toggle.param.watch(lambda _e: self._refresh_encoding_string_display(), "value")
        self.enc_yaxis_mode.param.watch(self._on_enc_yaxis_mode_changed, "value")
        self.enc_copy_button.js_on_click(args={"source": self.enc_string_pane}, code="""
            navigator.clipboard.writeText(source.value);
        """)
        self.enc_seed_motif_button.on_click(self._on_save_encoding_as_motif)
        self.enc_search_button.on_click(self._on_morphology_search)
        self.enc_search_input.param.watch(lambda _e: self._on_morphology_search(), "enter_pressed")
        self.enc_search_clear_button.on_click(self._on_morphology_search_clear)
        self.enc_search_prev_button.on_click(lambda _e: self._step_morphology_match(-1))
        self.enc_search_next_button.on_click(lambda _e: self._step_morphology_match(+1))
        self.enc_noise_floor_button.on_click(self._on_estimate_noise_floor)

        self._refresh_element_options()
        self._on_stage_changed(None)
        self.refresh_staged_list()

    # ── Staged-spans basket ──────────────────────────────────────────────

    def refresh_staged_list(self):
        """Called by `app._stage_span` whenever the basket changes, and
        once at init — re-renders the table from `app._staged_spans`,
        the single source of truth this panel doesn't own."""
        records = [
            {"source_file": s["source_file"], "channel": s["channel"],
             "start_idx": s["start_idx"], "end_idx": s["end_idx"],
             "duration": self._staged_duration_label(s),
             "annotation_id": s["annotation_id"] if s["annotation_id"] is not None else ""}
            for s in self.app._staged_spans
        ]
        df = pd.DataFrame(records, columns=["source_file", "channel", "start_idx", "end_idx", "duration", "annotation_id"])
        self.staged_table.value = df
        self.staged_badge.object = f"**Staged: {len(self.app._staged_spans)}**"
        self._on_span_context_changed()

    def _staged_duration_label(self, staged_row):
        rec = q.get_recording_by_id(self.conn, staged_row["recording_id"])
        if rec is None:
            return ""
        return _format_duration_human((staged_row["end_idx"] - staged_row["start_idx"]) / rec["fs"])

    def _on_remove_staged(self, _event=None):
        selected = self.staged_table.selection
        if not selected:
            return
        for i in sorted(selected, reverse=True):
            del self.app._staged_spans[i]
        self.refresh_staged_list()
        self.app._refresh_staged_badge()

    def _on_clear_staged(self, _event=None):
        self.app._staged_spans.clear()
        self.refresh_staged_list()
        self.app._refresh_staged_badge()

    # ── Adapter/param wiring ─────────────────────────────────────────────

    def _refresh_element_options(self):
        self.motif_elements.options = [r["value"] for r in v.list_terms(self.conn, category="element")]

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

    def _apply_recommended_defaults(self, force=False):
        """Part 6, 4a: call `spec.recommend(x, t, fs)` for the CURRENT
        span and pre-fill the parameter widgets — UNLESS the user has
        already edited one of them away from the last recommendation, in
        which case leave every edit alone and just note that recommended
        values have changed (force=True, from the "Reset to recommended"
        button, always applies regardless).

        Never silently overwrites a deliberate choice on an incidental
        viewport pan — that would be maddening (the brief's own words).
        """
        name = self.algorithm_select.value
        spec = get_adapter(name) if name else None
        if spec is None or spec.recommend is None:
            self.span_changed_note.object = ""
            return
        signal = self._current_span_signal()
        if signal is None:
            return
        x, t, fs, _recording = signal
        rec = spec.recommend(x, t, fs)

        any_modified = any(
            self._recommended_values.get(pname) is not None
            and w.value != self._recommended_values[pname]
            for pname, w in self._param_widgets.items()
        )
        preprocess_modified = (
            self._recommended_preprocess_window is not None
            and self.preprocess_window.value != self._recommended_preprocess_window
        )

        # Update the "last recommendation" bookkeeping BEFORE setting any
        # widget value below — `_on_param_widget_changed` (fired by each
        # assignment) compares against `_recommended_values` to decide the
        # "(modified)" marker, and must see the NEW recommendation, not a
        # stale one, or a widget freshly set to its recommended value could
        # transiently (and permanently, since nothing re-checks it later)
        # get mismarked "(modified)".
        self._recommended_values = {k: v for k, v in rec.items() if k != "preprocess_window_s"}
        if "preprocess_window_s" in rec:
            self._recommended_preprocess_window = rec["preprocess_window_s"]

        if force or not (any_modified or preprocess_modified):
            for pname, value in rec.items():
                if pname in self._param_widgets:
                    self._param_widgets[pname].value = value
                    self._param_base_names.setdefault(pname, self._param_widgets[pname].name)
                    self._param_widgets[pname].name = self._param_base_names[pname]
                elif pname == "preprocess_window_s":
                    self.preprocess_window.value = value
            self.span_changed_note.object = ""
        else:
            self.span_changed_note.object = (
                "*Span changed; recommended values updated. Click "
                "'Reset to recommended' to apply them.*"
            )

        n = len(x)
        self.auto_preview_checkbox.value = n < AUTO_PREVIEW_SPAN_THRESHOLD
        self._sync_segment_mode_controls()
        self._refresh_derived()

    def _on_param_widget_changed(self, pname):
        """Part 6 4a's modified marker — appended to a widget's own label
        the moment its value differs from the last recommendation applied
        to it, cleared the moment it matches again (including right after
        Reset). Part 7, Part 3 item 6: a compact "•" rather than the word
        "(modified)", which was long enough on its own to push these
        already-long labels into mid-word truncation."""
        if self._syncing_segment_controls:
            # `_sync_segment_mode_controls` is assigning a RESOLVED display
            # value to an inactive, disabled control — not a user edit, so
            # it must not be marked "modified" or re-trigger a sync of
            # itself (this method is what it's called FROM).
            return
        if self._suppress_param_watchers:
            # A MEASURED value being written into a control by the panel
            # itself (currently only `min_same_halfwidth`, from the
            # noise-floor button). Not a user edit, and running the normal
            # chain from here is actively wrong twice over:
            #   - it would schedule an auto-preview, so a DIAGNOSTIC would
            #     silently recompute the encoding it just measured — the
            #     one thing the button promises not to do;
            #   - `_refresh_derived`/`_sync_segment_mode_controls` read
            #     `self.conn`, and this runs on the noise-floor WORKER
            #     thread whenever there is no live Bokeh document to defer
            #     to (`_run_on_ui_thread` falls back to calling directly),
            #     which sqlite3 rejects outright: "SQLite objects created
            #     in a thread can only be used in that same thread."
            #     Confirmed by exactly that traceback.
            # The status pane tells the user the value was set and that a
            # re-run is needed, which is the deliberate action this
            # replaces.
            return
        w = self._param_widgets.get(pname)
        if w is None:
            return
        base = self._param_base_names.get(pname, w.name)
        recommended = self._recommended_values.get(pname)
        modified = recommended is not None and w.value != recommended
        new_name = f"{base} •" if modified else base
        if w.name != new_name:
            w.name = new_name
        self._sync_segment_mode_controls()
        self._sync_trend_param_controls()
        self._refresh_derived()
        self._schedule_auto_preview()

    def _sync_trend_param_controls(self):
        """dSAX Phase E: `min_same_halfwidth` is a floor on the SAME band's
        half-width, and an EVEN alphabet size has no SAME band at all — the
        cutlines include one exactly AT zero rather than a band around it
        (IMPLEMENTATION_NOTES.md 7.7). The parameter is silently ignored by
        `dsax()` there, so the control is disabled and says why rather than
        accepting a number that will have no effect.

        Same principle as `_sync_segment_mode_controls`: a control that
        cannot affect the run must never look like one that can."""
        w = self._param_widgets.get("min_same_halfwidth")
        alphabet = self._param_widgets.get("alphabet_size")
        if w is None or alphabet is None:
            return  # not the dSAX adapter
        inert = int(alphabet.value) % 2 == 0
        w.disabled = inert
        base = self._param_base_names.get("min_same_halfwidth", w.name)
        w.description = (
            f"No effect at alphabet_size={int(alphabet.value)}: an even alphabet has a cutline "
            "exactly at zero and therefore no SAME band to widen. Use an odd alphabet size."
            if inert else
            "Floor on the SAME band half-width, in the working delta domain "
            "(use 'Estimate noise floor' to measure one). 0 = unset"
        )
        # Keep the "modified" marker logic in `_on_param_widget_changed`
        # authoritative over the name; only append the inert marker.
        if inert and not w.name.endswith("(n/a)"):
            w.name = f"{base} (n/a)"
        elif not inert and w.name.endswith("(n/a)"):
            w.name = base

    def _sync_segment_mode_controls(self):
        """Part 7, Part 4 item 1: the single most confusing thing on the
        page before this fix — with `segment_mode="seconds_per_symbol"`,
        the other three controls kept showing whatever stale value they
        last held, actively contradicting what would run. Now: only the
        ACTIVE control is enabled; the other three are disabled AND their
        displayed values are kept resolved to the SAME `samples_per_symbol`
        the active one means, via `segment_plan` — the identical function
        a real run uses — so all four can never disagree about what's
        about to happen."""
        widgets = self._param_widgets
        segment_param_names = ("seconds_per_symbol", "samples_per_symbol", "target_symbol_count", "dim_ratio")
        if "segment_mode" not in widgets or not all(p in widgets for p in segment_param_names):
            return  # not a SAX-style adapter (e.g. bandpass) -- nothing to sync
        signal = self._current_span_signal()
        if signal is None:
            return
        x, _t, fs, _rec = signal
        n = len(x)
        active_mode = widgets["segment_mode"].value
        params = {p: widgets[p].value for p in segment_param_names}
        try:
            plan = segment_plan(active_mode, params, fs, n)
        except (ValueError, ZeroDivisionError):
            return
        sps = max(1, plan["requested_sps"])
        resolved = {
            "seconds_per_symbol": sps / fs,
            "samples_per_symbol": sps,
            "target_symbol_count": max(2, round(n / sps)),  # matches that ParamSpec's own min=2
            "dim_ratio": 1.0 / sps,
        }
        self._syncing_segment_controls = True
        try:
            for pname in segment_param_names:
                w = widgets[pname]
                w.disabled = (pname != active_mode)
                if pname != active_mode:
                    w.value = resolved[pname]
        finally:
            self._syncing_segment_controls = False

    def _on_preprocess_changed(self, _event=None):
        # Part 7, Part 4 item 3: window_s means nothing for mode="none" --
        # disabled (not hidden, so the sidebar doesn't reflow) whenever
        # there's no mode to apply it to.
        self.preprocess_window.disabled = self.preprocess_select.value == "none"
        self._refresh_derived()
        self._schedule_auto_preview()

    def _refresh_derived(self):
        """Part 6 4b: the read-only `derive()` table beneath the
        parameter controls — recomputed on every parameter change,
        without running anything."""
        name = self.algorithm_select.value
        spec = get_adapter(name) if name else None
        if spec is None or spec.derive is None:
            self.derived_pane.object = ""
            return
        signal = self._current_span_signal()
        if signal is None:
            self.derived_pane.object = ""
            return
        x, t, fs, _recording = signal
        try:
            rows = spec.derive(x, t, fs, self._current_params())
        except Exception as e:
            self.derived_pane.object = f"<i>Could not compute: {e}</i>"
            return
        self.derived_pane.object = _rows_to_html(rows)

    # ── Part 6, 4c: auto-preview on parameter change ─────────────────────

    def _schedule_auto_preview(self):
        """Debounce `AUTO_PREVIEW_DEBOUNCE_MS`, then recompute an encoding
        PREVIEW — no DB writes, no `runs`/`configs` rows; the explicit Run
        button remains the only thing that records a run. No-op unless
        auto-preview is on and the selected algorithm produces an
        encoding (the only output kind this preview knows how to show)."""
        if self._auto_preview_timer is not None:
            self._auto_preview_timer.cancel()
        if not self.auto_preview_checkbox.value:
            return
        name = self.algorithm_select.value
        spec = get_adapter(name) if name else None
        if spec is None or spec.output_kind != "encoding":
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
        database entirely: encodings are cheap enough (well under a
        second at the span sizes auto-preview defaults on for) to just
        run inline on the UI thread rather than spinning up a worker."""
        if self._thread is not None and self._thread.is_alive():
            return  # a real run is in progress -- don't fight it
        app = self.app
        if app._recording_id is None:
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

    def _staged_row_index(self):
        """Which staged-table row counts as THE staged span (Part 5 A3):
        the checkbox-selected row if any, else the first row — `None` if
        the basket is empty. Shared by the preview and `_current_span` so
        they can never pick a different row from each other."""
        if not self.app._staged_spans:
            return None
        sel = self.staged_table.selection
        return sel[0] if sel else 0

    def _current_span(self):
        """(start, end) sample indices for whichever span mode is selected,
        or None for the whole channel. This is the ONLY place that decides
        what a run actually operates on — the pre-run preview (Part 5,
        Section A) calls this exact method too, specifically so the two
        can never disagree about what's about to happen (A4/A5).

        `app._pending_bounds` / `app._range_stream.x_range` are expressed
        in whatever the viewer's current display unit is (seconds or
        hours — see `ViewerApp._unit_scale`), not necessarily seconds, so
        both must be rescaled before multiplying by `fs`.

        Part 5 A3: when a span is staged for the recording currently
        loaded in the Viewer, "Selected span" resolves to the staged
        table's selected (or first) row rather than the ad hoc
        drag-selected `_pending_bounds` — arriving here via staging a span
        is the overwhelmingly common path, and that staged span IS "the
        selected span" in that flow. Falls back to the previous
        `_pending_bounds` behaviour when nothing is staged, or the staged
        row belongs to a different recording than what's currently loaded
        (its indices wouldn't mean anything against this channel's `fs`/
        sample count), preserving the original ad hoc drag-select
        workflow untouched.
        """
        app = self.app
        if self.span_mode.value == "Whole channel":
            return None
        scale = app._unit_scale()
        if self.span_mode.value == "Selected span":
            idx = self._staged_row_index()
            if idx is not None:
                row = app._staged_spans[idx]
                if row["recording_id"] == app._recording_id:
                    return (row["start_idx"], row["end_idx"])
            bounds = app._pending_bounds
            if not bounds or bounds[0] is None:
                raise ValueError(
                    "No span currently selected — stage a span above, drag on the "
                    "main viewer plot, or switch Span to 'Current viewport'/'Whole channel'."
                )
            start = max(0, int(round(bounds[0] * scale * app._fs)))
            end = min(app._n_samples, int(round(bounds[1] * scale * app._fs)))
            return (start, end)
        # Current viewport
        if app._range_stream is None:
            raise ValueError("No recording loaded yet.")
        x0, x1 = app._range_stream.x_range or app._full_extent
        start = max(0, int(round(x0 * scale * app._fs)))
        end = min(app._n_samples, int(round(x1 * scale * app._fs)))
        return (start, end)

    # ── Pre-run preview (Part 5, Section A) ─────────────────────────────

    def _on_span_context_changed(self, _event=None):
        """Whatever just changed (span mode, staged-row selection, or the
        staged basket itself), the set of things that could be run just
        changed too — refresh both the preview and the save-as-motif
        gating (C4) from the same `_current_span` a real run uses, never a
        second, independent notion of "what's selected". Also re-derives
        recommended param defaults for the new span (Part 6, 4a)."""
        self._refresh_preview()
        self._update_motif_button_states()
        self._apply_recommended_defaults(force=False)
        self._refresh_window_matrix_panel()

    def _refresh_preview(self):
        """Render whatever `_current_span()` would actually run on, using
        the exact same decimated-curve rendering path as the Viewer tab
        (`UI.plots.build_peek_curve`, also used for the cross-channel peek)
        — never a second, independent renderer (A5), so this tab and the
        Viewer can never visually disagree about the same samples.

        `result_pane.object` has exactly two writers: this method (the
        pre-run preview) and `_show_before_after` (the post-run pair) —
        whichever ran most recently is what's on screen, so a stale
        single-plot and a Before/After pair can never both be showing
        (A2). Called on init, whenever the span mode or staged-row
        selection changes, and whenever the staged basket itself changes
        (`refresh_staged_list`) — i.e. every event that could change what
        `_current_span()` returns.
        """
        app = self.app
        if app._recording_id is None or app._fs is None:
            self.result_pane.object = None
            self.preview_info.object = "*No recording loaded.*"
            return
        try:
            span = self._current_span()
        except ValueError as e:
            self.result_pane.object = None
            self.preview_info.object = f"*{e}*"
            return

        start, end = (0, app._n_samples) if span is None else span
        recording = q.get_recording_by_id(self.conn, app._recording_id)
        # Part A4: "Whole channel" is just `(0, n_samples)` through this
        # SAME call — `build_peek_curve` already decimates via
        # `_minmax_decimate`, so a multi-million-sample channel is never
        # rendered raw, with no special-casing needed here.
        curve = build_peek_curve(
            recording["npy_path"], recording["fs"], (start, end), height=RUN_PREVIEW_HEIGHT,
        ).opts(color=CURVE_COLOR, title="Staged span — not yet processed")
        if self.window_matrix_panel.visible:
            # The coverage ribbons (§4) sit directly under this preview and
            # share its x-range only, the same relationship the Viewer's own
            # ribbon panes have to its main curve — which requires matching
            # `min_border_left`/`right` (`style_main_plot_frame`, the same
            # hook the Viewer curve uses), or a wider/narrower left margin
            # here shifts every ribbon bucket sideways relative to what it's
            # meant to annotate. Scoped to when the window-matrix panel is
            # actually visible so every other algorithm's preview (nothing
            # stacks ribbons under those) keeps its default framing.
            curve = style_main_plot_frame(curve)
        self.result_pane.object = curve
        self._last_before_after = None  # this preview IS "before" now; no stale pair left to re-toggle

        n = end - start
        duration_label = _format_duration_human(n / recording["fs"])
        which = ""
        if self.span_mode.value == "Selected span":
            idx = self._staged_row_index()
            n_staged = len(app._staged_spans)
            if idx is not None and n_staged > 1:
                which = f" (staged row {idx + 1}/{n_staged})"
            elif idx is not None:
                which = " (staged span)"
        self.preview_info.object = f"**{n:,} samples** ({duration_label}){which}"

    def _has_valid_manual_span(self):
        """Whether `_current_span()` resolves to an actual bounded span —
        NOT `None`/"Whole channel", which 'Save current selection as
        motif' has always explicitly rejected (see `_on_save_viewport_as_motif`)."""
        if self.span_mode.value == "Whole channel":
            return False
        try:
            return self._current_span() is not None
        except ValueError:
            return False

    def _update_motif_button_states(self):
        """Part 5 C4: 'Save selected detection' only means anything once a
        run has actually produced detections to pick from; 'Save current
        selection' only means anything once `_current_span` resolves to a
        real span. Re-evaluated on every span/staged-selection change and
        after every run so neither button is ever clickable in a
        meaningless state."""
        self.save_motif_button.disabled = len(self.detections_table.value) == 0
        self.save_viewport_motif_button.disabled = not self._has_valid_manual_span()

    def _on_yaxis_mode_changed(self, _event=None):
        """Part 5 B2: re-render the last Before/After pair (if any) under
        the newly chosen y-axis mode without re-running anything — the
        toggle is purely a display choice over data already in hand."""
        if self._last_before_after is not None:
            recording, result_x, result_t = self._last_before_after
            self._show_before_after(recording, result_x, result_t)

    # ── Run / cancel ─────────────────────────────────────────────────────

    def _build_steps(self):
        """Part 6, 2e: prepend a preprocessing step ahead of whatever
        algorithm is selected, when the user has picked one — a REAL
        recipe step (not baked into the SAX/any other adapter), so the
        recipe hash covers it and Run History shows what actually ran.
        Used by a real Run, and by the auto-preview path (Part 4c), so
        the two can never silently diverge on what a run consists of."""
        stage = self.stage_select.value
        algorithm_full = self.algorithm_select.value  # e.g. "detection.sax_csax"
        algorithm_short = algorithm_full.split(".", 1)[1]
        params = self._current_params()
        steps = []
        if self.preprocess_select.value != "none":
            steps.append({
                "stage": "preprocessing", "algorithm": "detrend",
                "params": {"mode": self.preprocess_select.value, "window_s": self.preprocess_window.value},
            })
        steps.append({"stage": stage, "algorithm": algorithm_short, "params": params})
        return steps

    def _on_run(self, _event=None):
        self.status.object = ""
        self.motif_status.object = ""
        if self._thread is not None and self._thread.is_alive():
            self.status.object = "**A run is already in progress.**"
            return

        try:
            span = self._current_span()
        except ValueError as e:
            self.status.object = f"**{e}**"
            return

        recipe = make_recipe(self.app._recording_id, self._build_steps(), span=span)
        self._last_recipe = recipe
        self._last_recording = self.app._recording_id

        self._cancel_event.clear()
        self.run_button.disabled = True
        self.cancel_button.disabled = False
        self.status.object = f"Running {recipe_summary(recipe)} ..."

        db_path = self.conn.execute("PRAGMA database_list").fetchone()[2] or None
        doc = pn.state.curdoc  # captured here, on the serving thread

        def _worker():
            # A worker thread must never touch `self.conn` (or any
            # sqlite3.Row/Connection it produced) — SQLite connections are
            # thread-affined. This thread opens its own, reads whatever
            # plain data the UI update will need, and closes it before
            # handing off — only plain dicts/arrays cross the thread
            # boundary, never live DB objects.
            def on_progress(i, n, s, a):
                def _update():
                    self.status.object = f"Running step {i + 1}/{n}: {s}.{a} ..."
                _run_on_ui_thread(doc, _update)

            try:
                out = execute_recipe(
                    recipe, db_path=db_path, on_progress=on_progress,
                    should_cancel=self._cancel_event.is_set,
                )
                conn_w = init_db(db_path)
                try:
                    display_data = self._gather_display_data(conn_w, out, recipe)
                finally:
                    conn_w.close()
                _run_on_ui_thread(doc, lambda: self._on_run_finished(out, display_data))
            except RecipeCancelled:
                _run_on_ui_thread(doc, lambda: self._on_run_cancelled())
            except RecipeExecutionError as e:
                _run_on_ui_thread(doc, lambda: self._on_run_failed(str(e)))

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _gather_display_data(self, conn_w, out, recipe):
        """Runs on the worker thread with its own connection `conn_w`.
        Returns a plain (no live DB objects) dict describing what the UI
        thread needs to render.

        The last step's adapter spec (not `out["result"]`, which is None
        for a reused run) tells us the *actual* output kind regardless of
        whether anything was recomputed. `intervals` are persisted
        (`detections`), so a reused run can still show them; `signal`/
        `encoding` outputs are not persisted anywhere the UI can cheaply
        re-read, so a reused run reports that rather than fabricating a
        stale or recomputed preview.
        """
        last_step = recipe["steps"][-1]
        spec = get_adapter(f"{last_step['stage']}.{last_step['algorithm']}")
        result = out["result"]

        if spec.output_kind == "intervals":
            dets = R.list_detections(conn_w, out["run_id"])
            return {"kind": "intervals", "detections": [dict(d) for d in dets]}

        if spec.output_kind == "encoding":
            # Not every 'encoding' adapter is SAX-shaped (a details dict +
            # x/t + a discrete symbol array) -- matrix profile is also
            # output_kind='encoding' but is a continuous distance profile
            # with its own dedicated exploration UI (the Motif browser
            # tab). Same `algorithm_short.startswith("sax_")` convention
            # `_persist_sax_encoding`'s caller already uses below to keep
            # SAX-only behaviour SAX-only.
            if last_step["algorithm"].startswith("sax_"):
                return self._gather_encoding_display_data(conn_w, out, recipe, spec, result)
            return self._gather_generic_encoding_display_data(conn_w, out, recipe, spec, result)

        if result is None:  # reused signal run — nothing to re-show cheaply
            return {"kind": "reused_no_preview"}

        if spec.output_kind == "signal":
            recording = q.get_recording_by_id(conn_w, recipe["recording_id"])
            return {
                "kind": "signal",
                "recording": dict(recording),
                "result_x": result.x, "result_t": result.t,
            }

        return {"kind": None}

    def _gather_encoding_display_data(self, conn_w, out, recipe, spec, result):
        """Part 6, 3a. A REUSED encoding run has `result=None` (nothing
        recomputed) — but an encoding is cheap (well under a second even
        at ~63k samples), so re-run just this step for spans under
        `ENCODING_RECOMPUTE_MAX_SAMPLES` rather than showing nothing.
        Above that, fall back to the cached STRING alone (no detail
        panels — the array/`details` a fresh recompute would need aren't
        persisted anywhere cheap to re-read), with an explicit note why.
        """
        span = recipe["span"]
        recording = q.get_recording_by_id(conn_w, recipe["recording_id"])
        start, end = (0, recording["n_samples"]) if span is None else span
        n = end - start

        if result is None and n <= ENCODING_RECOMPUTE_MAX_SAMPLES:
            x_full = np.load(recording["npy_path"], mmap_mode="r")
            x = np.asarray(x_full[start:end])
            t = np.arange(start, end) / recording["fs"]
            # Replay any preprocessing step(s) that preceded the SAX step,
            # so the recomputed encoding matches what the real run
            # actually encoded, not the raw span.
            for step in recipe["steps"][:-1]:
                step_spec = get_adapter(f"{step['stage']}.{step['algorithm']}")
                step_params = step_spec.validate_params(step["params"])
                step_result = step_spec.run(x, t, recording["fs"], **step_params)
                x, t = step_result.x, step_result.t
            params = spec.validate_params(recipe["steps"][-1]["params"])
            result = spec.run(x, t, recording["fs"], **params)

        if result is not None:
            algorithm_short = recipe["steps"][-1]["algorithm"]
            if algorithm_short.startswith("sax_"):  # Part 6, 4e
                self._persist_sax_encoding(conn_w, recording, recipe, out, result.encoding,
                                           algorithm_short, result.meta["details"])
            return {
                "kind": "encoding", "recording": dict(recording),
                "x": result.x, "t": result.t, "symbols": result.encoding,
                "details": result.meta["details"],
            }

        cached = R.get_encoding_by_hash(conn_w, out["config_hash"])
        if cached is not None:
            try:
                return {"kind": "encoding_cached_only",
                        "string": read_encoding_file(cached["path"]),
                        # Carried through so `_show_encoding_string_only` can
                        # name the alphabet — there is no `details` there.
                        "encoding_type": cached["encoding_type"],
                        "n_samples": n}
            except Exception:
                pass
        return {"kind": "encoding_too_large", "n_samples": n}

    def _gather_generic_encoding_display_data(self, conn_w, out, recipe, spec, result):
        """For 'encoding' adapters that are NOT SAX-shaped — currently
        just `detection.matrix_profile`. These have no `details`/x/t
        triplet to hand to the SAX 4-panel view (Part 6); matrix profile
        has its own dedicated exploration UI instead (the Motif browser
        tab, reading the v2 artifact this adapter's `persist` hook already
        wrote — see `Adapters.detection_matrix_profile`).

        Unlike SAX, recomputing a matrix profile just for a preview is NOT
        cheap (it's the same O(n^2)-ish cost as the run itself), so —
        unlike `_gather_encoding_display_data` — a reused run is never
        silently re-run here; it just reports `reused=True`.
        """
        artifacts = R.list_artifacts(conn_w, out["run_id"])
        artifact_path = next((a["path"] for a in artifacts if a["kind"] == "encoding"), None)

        summary = None
        if artifact_path is not None:
            try:
                from Working.database.matrix_profile_store import load_mp
                data = load_mp(artifact_path, mmap=True)
                mp_arr = np.asarray(data["mp"])
                finite = mp_arr[np.isfinite(mp_arr)]
                summary = {
                    "n": int(len(mp_arr)), "m": int(data["m"]), "backend": str(data["backend"]),
                    "approx": bool(data["approx"]),
                    "min": float(finite.min()) if len(finite) else None,
                    "mean": float(finite.mean()) if len(finite) else None,
                    "max": float(finite.max()) if len(finite) else None,
                }
            except Exception:
                summary = None

        return {
            "kind": "generic_encoding", "run_id": out["run_id"],
            "artifact_path": artifact_path, "summary": summary, "reused": result is None,
        }

    def _persist_sax_encoding(self, conn_w, recording, recipe, out, symbols, algorithm_short,
                              details=None):
        """Part 6, 4e: persist the run's symbol string through
        `Working.encoding_cache` with `encoding_type` "sax_csax" /
        "sax_psax" / "sax_dsax" — so `_find_sax_string_for_span` (already
        written to look for exactly this) picks it up automatically the
        moment a detection or a manual selection over the SAME span is
        saved as a motif, with no further wiring needed there. Skips
        silently if already cached (`get_or_compute_encoding`'s own
        cache-hit path) — a reused run recomputed here for display doesn't
        need a duplicate write.

        `encoding_type` needed no extension for dSAX: it is already
        DERIVED from the recipe's own `algorithm` short name by the caller,
        so `detection.sax_dsax` becomes "sax_dsax" without a special case.

        `details` (2026-08, dSAX) supplies the alphabet, so the cached
        `.txt` holds the SAME string the run panel displays. Without it a
        dSAX run would persist "abcba..." while the UI showed "USDSU..." —
        two spellings of one encoding, and a morphology regex saved
        against one would silently not match the other.
        """
        from Working.encoding_cache import get_or_compute_encoding
        span = recipe["span"]
        start, end = (0, recording["n_samples"]) if span is None else span
        letters = symbol_letters(details) if details is not None else None
        get_or_compute_encoding(
            conn_w, recording, algorithm_short, out["config_hash"],
            lambda: (symbols_to_string(symbols, letters), start, end),
        )

    def _on_cancel(self, _event=None):
        self._cancel_event.set()
        self.status.object = "Cancelling after the current step finishes ..."

    def _on_run_finished(self, out, display_data):
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        self._last_run_result = out

        last_step = self._last_recipe["steps"][-1]
        spec = get_adapter(f"{last_step['stage']}.{last_step['algorithm']}")
        self.save_plot_button.disabled = spec.plot is None
        self.save_plot_status.object = ""

        reused_note = " (reused an identical prior run — not recomputed)" if out["reused"] else ""
        total_s = sum(out["step_timings"].values()) if out["step_timings"] else 0.0
        self.status.object = f"Done{reused_note}. run_id={out['run_id']}"
        self.duration_pane.object = (
            f"**Duration:** {total_s:.3f}s"
            + ("" if not out["step_timings"] else " (" + ", ".join(
                f"step {i}: {t:.3f}s" for i, t in sorted(out["step_timings"].items(), key=lambda kv: int(kv[0]))
            ) + ")")
        )

        # Part 6, 4f: the Encoding section is hidden entirely (not shown
        # empty) whenever the last run's output isn't an encoding.
        self.encoding_section.visible = display_data["kind"] in (
            "encoding", "encoding_cached_only", "encoding_too_large",
        )

        if display_data["kind"] == "intervals":
            self._show_detections(display_data["detections"])
        elif display_data["kind"] == "signal":
            self._show_before_after(display_data["recording"], display_data["result_x"], display_data["result_t"])
        elif display_data["kind"] == "encoding":
            self._show_encoding(display_data["x"], display_data["t"], display_data["symbols"],
                                 display_data["details"], display_data["recording"])
        elif display_data["kind"] == "encoding_cached_only":
            self.status.object += (
                f"  |  span is {display_data['n_samples']:,} samples, above the "
                f"{ENCODING_RECOMPUTE_MAX_SAMPLES:,}-sample recompute limit — showing the cached "
                "symbol string only, no detail panels."
            )
            self._show_encoding_string_only(display_data["string"],
                                            display_data.get("encoding_type"))
        elif display_data["kind"] == "encoding_too_large":
            self.status.object += (
                f"  |  span is {display_data['n_samples']:,} samples, above the "
                f"{ENCODING_RECOMPUTE_MAX_SAMPLES:,}-sample recompute limit, and no cached "
                "encoding was found for this exact recipe — nothing to show."
            )
            self.encoding_section.visible = False
        elif display_data["kind"] == "reused_no_preview":
            self.status.object += (
                "  |  no new preview to show for a reused run — see the Run History "
                "tab for this run's prior artifacts, or change a parameter to recompute."
            )
        elif display_data["kind"] == "generic_encoding":
            reused_note2 = " (reused an identical prior run)" if display_data["reused"] else ""
            summary = display_data["summary"]
            if summary is not None:
                approx_note = " approx" if summary["approx"] else ""
                self.status.object += (
                    f"  |  profile: n={summary['n']:,} m={summary['m']} "
                    f"backend={summary['backend']}{approx_note}  "
                    f"min={summary['min']:.4f} mean={summary['mean']:.4f} max={summary['max']:.4f}"
                    f"{reused_note2}. See the **Motif browser** tab to explore it."
                )
            elif display_data["artifact_path"] is not None:
                self.status.object += (
                    f"  |  saved to {display_data['artifact_path']}{reused_note2}. "
                    "See the **Motif browser** tab to explore it."
                )
            else:
                self.status.object += (
                    f"  |  no artifact was registered for this run{reused_note2} — nothing to show."
                )
        self._update_motif_button_states()

    def _on_run_cancelled(self):
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        self.status.object = "**Cancelled.**"

    def _on_run_failed(self, message):
        self.run_button.disabled = False
        self.cancel_button.disabled = True
        self.status.object = f"**Failed:** {message}"

    # ── 5b: before/after comparison ─────────────────────────────────────

    def _show_before_after(self, recording, result_x, result_t):
        """Part 5, Section B: independent-by-default y-axes, because most
        of what runs here (anything removing a DC offset or changing
        scale — e.g. the bandpass filter's After output, which can be
        orders of magnitude smaller than Before's raw DC-offset range)
        renders as a flat line near zero if forced onto a shared/
        normalized range. `self.yaxis_mode` lets the user opt back into a
        shared range for the (rarer) amplitude-preserving transform where
        that's the more informative comparison.
        """
        x_full = np.load(recording["npy_path"], mmap_mode="r")
        start = int(round(result_t[0] * recording["fs"]))
        end = start + len(result_x)
        x_before = np.asarray(x_full[start:end])
        t = np.arange(start, end) / recording["fs"]
        x_after = np.asarray(result_x)

        self._last_before_after = (recording, result_x, result_t)

        # `compute_display_y_range` is the exact per-frame autoscale the
        # Viewer's main curve uses (10% padding) — reused here (A5's reuse
        # principle applies just as much to a y-range computation as to a
        # curve's decimation) so "auto-scaled" means the same thing in
        # both tabs.
        before_lo, before_hi = compute_display_y_range(x_before, (0.0, 1.0), y_autoscale=True)
        after_lo, after_hi = compute_display_y_range(x_after, (0.0, 1.0), y_autoscale=True)

        shared = self.yaxis_mode.value == "Shared y-axis"
        if shared:
            lo = min(before_lo, after_lo)
            hi = max(before_hi, after_hi)
            before_range, after_range = (lo, hi), (lo, hi)
        else:
            before_range, after_range = (before_lo, before_hi), (after_lo, after_hi)

        # Part B3: the actual numeric range in each title, so the two
        # panels' scales are never just inferred from eyeballing the axes.
        before = hv.Curve((t, x_before), "time_s", "amplitude").opts(
            color="#999999", title=f"Before  [y: {before_lo:.4g} to {before_hi:.4g}]",
            height=RUN_PREVIEW_HEIGHT, responsive=True, fontsize=PLOT_FONTSIZE,
            ylim=before_range, framewise=True, axiswise=True,
        )
        after = hv.Curve((result_t, result_x), "time_s", "amplitude").opts(
            color="steelblue", title=f"After  [y: {after_lo:.4g} to {after_hi:.4g}]",
            height=RUN_PREVIEW_HEIGHT, responsive=True, fontsize=PLOT_FONTSIZE,
            ylim=after_range, framewise=True, axiswise=True,
        )
        # Stacked with a shared/linked x-axis: combining same-dimension
        # Curves in a Layout shares axes by default, so zooming one pans/
        # zooms the other in lockstep. `axiswise=True` on each curve (Part
        # B1) stops HoloViews' separate per-Layout normalization of shared
        # value dimensions from silently re-merging the two y-ranges back
        # together regardless of the explicit `ylim`s above — without it,
        # "independent" mode rendered identically to "shared" because both
        # curves carry the "amplitude" dimension.
        self.result_pane.object = (before + after).cols(1).opts(shared_axes=True)

        # Part B4: make an amplitude-scale change visible rather than
        # requiring it to be inferred from the two titles.
        before_span = before_hi - before_lo
        after_span = after_hi - after_lo
        if before_span > 0:
            ratio = after_span / before_span
            self.scale_note.object = (
                f"*Output range is {ratio:.3g}x the input range "
                f"({after_span:.4g} vs {before_span:.4g}).*"
            )
        else:
            self.scale_note.object = ""

    # ── Encoding inspection view (Part 6, Section 3) ─────────────────────

    def _preprocessing_active(self):
        return self.preprocess_select.value != "none"

    def _preprocessing_description(self):
        return f"{self.preprocess_select.value}, window {self.preprocess_window.value:g} s"

    def _update_preprocessing_banner(self):
        """Part 7, Part 2 item 6 — the same loud-banner treatment the
        Viewer uses for its own "DISPLAY TRANSFORM ACTIVE" state (Part
        E3): the only way to know the encoding ran on a transformed
        signal, not the raw trace, used to be remembering the dropdown."""
        if self._preprocessing_active():
            self.enc_preprocessing_banner.object = (
                f"**⚠ PREPROCESSED — {self._preprocessing_description()} — "
                "panels below show the preprocessed signal, not the raw trace.**"
            )
            self.enc_preprocessing_banner.styles = {
                "display": "block", "background": "#fff3cd", "border": "2px solid #f0ad4e",
                "padding": "8px", "border-radius": "4px",
            }
        else:
            self.enc_preprocessing_banner.object = ""
            self.enc_preprocessing_banner.styles = {"display": "none"}

    def _build_colour_key_html(self, details):
        """Part 7, Part 4 item 4: a compact, horizontal letter-to-swatch
        key sitting immediately above the symbol strip — the full
        alphabet table further down the page is too far away to be
        usable while looking at the strip.

        For a trend alphabet the full name is shown beside the letter
        (`D DOWN`, `S SAME`, `U UP`): a single-character alphabet is only
        self-explanatory once, and this key is exactly where someone looks
        to learn it."""
        alphabet_size = int(details["alphabet_size"])
        colors = symbol_colors(alphabet_size, symbol_cmap_name(details))
        letters = symbol_letters(details)
        names = symbol_names(details)
        cells = "".join(
            f'<span style="display:inline-flex;align-items:center;margin-right:10px;">'
            f'<span style="display:inline-block;width:12px;height:12px;background:{colors[i % len(colors)]};'
            f'border:1px solid #999;margin-right:3px;"></span>{symbol_label(i, letters)}'
            f'{f"&nbsp;<span style=\'color:#666;\'>{names[i]}</span>" if names and i < len(names) else ""}'
            f'</span>'
            for i in range(alphabet_size)
        )
        return f'<div style="padding:2px 0;">{cells}</div>'

    def _show_encoding(self, x, t, symbols, details, recording):
        """Build the four panels + string/RLE/diagnostics/legend from a
        fresh (or display-recomputed) encoding result. `x`/`t` are
        whatever was actually encoded (post any preprocessing step — see
        `Adapters.detection_sax_csax`'s module note)."""
        self._last_encoding = (x, t, symbols, details, recording)
        self._update_preprocessing_banner()
        signal_title = (
            "Encoded signal (after preprocessing)" if self._preprocessing_active() else "Encoded signal"
        )
        y_mode = "shared" if self.enc_yaxis_mode.value == "Match the signal panel" else "auto"
        # A fresh highlight stream per encoding: the old one's `spans` are
        # segment INDICES into a different symbol array and would highlight
        # arbitrary places in the new one.
        self._enc_highlight_stream = HighlightStream()
        dmap_signal, dmap_paa, dmap_quant, dmap_strip, range_stream = build_encoding_panels(
            x, t, symbols, details, signal_title=signal_title, y_mode=y_mode,
            highlight_stream=self._enc_highlight_stream,
        )
        self._enc_range_stream = range_stream
        self.enc_signal_pane.object = dmap_signal
        self.enc_paa_pane.object = dmap_paa
        self.enc_quant_pane.object = dmap_quant
        self.enc_strip_pane.object = dmap_strip
        self.enc_colour_key.object = self._build_colour_key_html(details)
        self.enc_view_toggle.visible = True
        self.enc_seed_motif_button.visible = True

        n_symbols = details["n_symbols"]
        # Part 3c: default "Visible range only" above the inline threshold
        # (a several-thousand-symbol string is unreadable rendered whole).
        self.enc_view_toggle.value = (
            "Visible range only" if n_symbols > ENCODING_STRING_INLINE_THRESHOLD else "Whole span"
        )
        self._refresh_encoding_string_display()
        self._reset_morphology_search()
        self._sync_noise_floor_controls(x, details)

        # `diagnostic_rows` is domain-agnostic (occupancy entropy,
        # self-transition rate, realised alphabet size) and serves all
        # three encoders; the trend-specific rows are APPENDED rather than
        # replacing it, so a dSAX run gets both and cSAX/pSAX are
        # untouched. See `Adapters.detection_sax_dsax.delta_diagnostic_rows`.
        rows = list(diagnostic_rows(symbols, details))
        if cutline_domain(details) == "delta":
            rows += delta_diagnostic_rows(symbols, details)
        self.enc_diagnostics_pane.object = _rows_to_html(rows)
        self.enc_legend_pane.object = self._build_legend_html(symbols, details)
        self.enc_seed_motif_status.object = ""

    def _on_enc_yaxis_mode_changed(self, _event=None):
        """Part 7, Part 2 item 4: re-render the last encoding (if any)
        under the newly chosen y-axis mode without re-running anything."""
        if self._last_encoding is not None:
            x, t, symbols, details, recording = self._last_encoding
            self._show_encoding(x, t, symbols, details, recording)

    def _show_encoding_string_only(self, string, encoding_type=None):
        """Part 3a's "too large to recompute" fallback — the cached
        string alone, no detail panels (there's nothing to draw them
        from), with the panels/diagnostics/legend left empty rather than
        stale from a previous run.

        There is no `details` here, so the alphabet cannot be derived the
        way `symbol_letters` derives it everywhere else. It does not need
        to be: `_persist_sax_encoding` wrote this string with the correct
        letters already, so displaying it verbatim is correct. What the
        cached row's `encoding_type` DOES buy is telling the reader which
        alphabet they are looking at — "UDDSU..." and "abcba..." are
        otherwise indistinguishable as to whether they encode trends or
        levels."""
        self._last_encoding = None
        self.enc_preprocessing_banner.object = ""
        self.enc_preprocessing_banner.styles = {"display": "none"}
        self.enc_signal_pane.object = None
        self.enc_paa_pane.object = None
        self.enc_quant_pane.object = None
        self.enc_strip_pane.object = None
        self.enc_colour_key.object = ""
        self.enc_view_toggle.visible = False
        self.enc_seed_motif_button.visible = False
        self.enc_string_pane.value = string
        alphabet_note = ""
        if encoding_type == "sax_dsax":
            alphabet_note = " — dSAX trend alphabet (D = down, S = same, U = up)"
        elif encoding_type:
            alphabet_note = f" — {encoding_type} alphabet (a, b, c, ...)"
        self.enc_string_info.object = (
            f"Length: {len(string):,} symbols (cached; too large to recompute for display)"
            f"{alphabet_note}"
        )
        self.enc_rle_pane.value = ""
        self.enc_rle_info.object = ""
        self.enc_diagnostics_pane.object = ""
        self.enc_legend_pane.object = ""
        self._reset_morphology_search()
        self.enc_noise_floor_button.visible = False
        self.enc_noise_floor_alpha.visible = False
        self.enc_noise_floor_status.object = ""

    def _visible_symbol_slice(self, t, symbols, details):
        """Which symbols fall within the encoding view's CURRENT x-range —
        shared by the string/RLE display's "Visible range only" mode."""
        if self._enc_range_stream is None or self._enc_range_stream.x_range is None:
            return symbols
        x0, x1 = self._enc_range_stream.x_range
        sps = details["samples_per_symbol"]
        n_symbols = details["n_symbols"]
        seg_t = segment_time_edges(t, n_symbols, sps)
        i0 = max(0, int(np.searchsorted(seg_t, x0, side="right")) - 1)
        i1 = min(n_symbols, int(np.searchsorted(seg_t, x1, side="left")) + 1)
        return symbols[i0:i1]

    def _refresh_encoding_string_display(self):
        """Part 3c: the string/RLE boxes respect the current zoom — a
        toggle switches between the full string and just the symbols
        currently in view."""
        if self._last_encoding is None:
            return
        x, t, symbols, details, recording = self._last_encoding
        if self.enc_view_toggle.value == "Visible range only":
            visible = self._visible_symbol_slice(t, symbols, details)
        else:
            visible = symbols
        letters = symbol_letters(details)
        string = symbols_to_string(visible, letters)
        rle = symbols_to_rle(visible, letters)
        self.enc_string_pane.value = string
        self.enc_string_info.object = f"Length: {len(string):,} symbols"
        self.enc_rle_pane.value = rle
        self.enc_rle_info.object = f"Length: {len(rle.split()) if rle else 0:,} runs"

    def _build_legend_html(self, symbols, details):
        """Part 3/7e: symbol index, letter, colour swatch, value range (raw
        amplitude units), representative value, count, and percentage with
        an inline horizontal bar — what lets someone read the
        quantisation/strip panels without guessing, at a glance rather
        than by parsing numbers. A styled HTML pane (not a Tabulator): the
        row-striping and inline occupancy bar are plain CSS/inline-`<div>`
        tricks that are simpler to get right in raw HTML than fighting a
        Tabulator's own per-cell formatter/styler API for the same effect,
        and this table is read-only with no sort/filter/selection need
        that would favour a Tabulator instead."""
        symbols = np.asarray(symbols)
        alphabet_size = details["alphabet_size"]
        colors = symbol_colors(alphabet_size, symbol_cmap_name(details))
        letters = symbol_letters(details)
        names = symbol_names(details)
        same_index = same_symbol_index(details)
        is_delta = cutline_domain(details) == "delta"
        # The range column is in the units of whatever was QUANTISED, and
        # for a trend encoding that is a rise per segment, not an
        # amplitude — labelling it "Value range" there would be the same
        # dimensional error the quantisation panel exists to avoid.
        range_header = "Rise range" if is_delta else "Value range"
        cutlines_raw = np.asarray(details["cutlines_raw"])
        representatives_raw = np.asarray(details.get("representatives_raw", details["representatives"]))
        n = len(symbols)
        counts = np.bincount(symbols, minlength=alphabet_size)[:alphabet_size]
        th = "text-align:left;padding:4px 10px;border-bottom:2px solid #ccc;"
        td = "padding:4px 10px;"
        rows = [f'<table style="border-collapse:collapse;font-size:{UI_TABLE_FONT_SIZE};">',
                f"<tr><th style='{th}'>Symbol</th><th style='{th}'>Colour</th>"
                f"<th style='{th}'>{range_header}</th><th style='{th}'>Representative</th>"
                f"<th style='{th}'>Count</th><th style='{th}'>%</th></tr>"]
        for sym in range(alphabet_size):
            lo = cutlines_raw[sym - 1] if sym > 0 else float("-inf")
            hi = cutlines_raw[sym] if sym < alphabet_size - 1 else float("inf")
            rep = representatives_raw[sym] if sym < len(representatives_raw) else float("nan")
            count = int(counts[sym])
            pct = 100.0 * count / n if n else 0.0
            # The SAME row carries the zero anchor — the one bin whose
            # meaning is fixed a priori rather than learned — so it gets a
            # standing highlight instead of the alternating stripe.
            is_same = same_index is not None and sym == same_index
            row_bg = "#e8f0d8" if is_same else ("#f4f4f4" if sym % 2 else "#ffffff")
            name_suffix = f" {names[sym]}" if names and sym < len(names) else ""
            rows.append(
                f"<tr style='background:{row_bg};{'font-weight:600;' if is_same else ''}'>"
                f"<td style='{td}'>{symbol_label(sym, letters)}{name_suffix} (index {sym})</td>"
                f"<td style='{td}'><span style='display:inline-block;width:14px;height:14px;"
                f"background:{colors[sym % len(colors)]};border:1px solid #999;'></span></td>"
                f"<td style='{td}'>{lo:.4g} to {hi:.4g}</td>"
                f"<td style='{td}'>{rep:.4g}</td>"
                f"<td style='{td}'>{count:,}</td>"
                f"<td style='{td}'>"
                f"<div style='display:inline-block;width:60px;height:10px;background:#e8e8e8;"
                f"vertical-align:middle;margin-right:6px;'>"
                f"<div style='width:{min(pct, 100):.1f}%;height:100%;background:#1f4e8c;'></div>"
                f"</div>{pct:.1f}%</td></tr>"
            )
        rows.append("</table>")
        if is_delta and same_index is None:
            # IMPLEMENTATION_NOTES.md 7.7: an even alphabet has a cutline
            # exactly AT zero and therefore no "no meaningful change" bin.
            # Saying so is the only honest option — highlighting an
            # arbitrary row would assert a SAME bin that does not exist.
            rows.append(
                f"<p style='font-size:{UI_TABLE_FONT_SIZE};color:#7a5b00;background:#fff3cd;"
                "padding:6px;border-radius:3px;margin:6px 0 0 0;'>"
                f"<b>No SAME bin.</b> alphabet_size={alphabet_size} is even, so the cutlines "
                "include one exactly at zero rather than a band around it — every segment is "
                "labelled as rising or falling, however slightly. Use an odd alphabet size "
                "for trend work.</p>"
            )
        return "".join(rows)

    # ── Morphology regex search (dSAX Phase F) ───────────────────────────

    def _reset_morphology_search(self):
        """Clear match state without clearing the PATTERN — someone
        scanning several spans for the same morphology should not have to
        retype it after every run."""
        self._search_matches = []
        self._search_index = -1
        self._search_summary = ""
        self.enc_search_prev_button.disabled = True
        self.enc_search_next_button.disabled = True
        if self._enc_highlight_stream is not None:
            self._enc_highlight_stream.event(spans=())
        self.enc_search_status.object = (
            f"*`{DEFAULT_MORPHOLOGY_PATTERN}` is the sharkfin pattern: one sharp rise, "
            "then a sustained fall. Searches the WHOLE span, not just the visible range.*"
        )

    def _on_morphology_search_clear(self, _event=None):
        self._reset_morphology_search()

    def _on_morphology_search(self, _event=None):
        """Find every match of the user's regex over the WHOLE-span symbol
        string and highlight them in the symbol strip.

        Whole-span, never the visible slice: searching only what happens to
        be on screen is a trap — the answer would silently change with the
        zoom level, and "no matches" would mean "none here", which is not
        what anyone reads it as.
        """
        if self._last_encoding is None:
            self.enc_search_status.object = "**Run an encoding first.**"
            return
        pattern = self.enc_search_input.value or ""
        if not pattern.strip():
            self._reset_morphology_search()
            return

        _x, t, symbols, details, _recording = self._last_encoding
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            # Never raise into a Panel callback — an exception here is
            # swallowed by Panel's handler and the button just silently
            # stops working (this module's plots.py sibling documents the
            # same failure mode for DynamicMap callbacks).
            self._search_matches = []
            self._search_index = -1
            self.enc_search_prev_button.disabled = True
            self.enc_search_next_button.disabled = True
            self.enc_search_status.object = f"**Invalid regex:** {e}"
            return

        string = symbols_to_string(symbols, symbol_letters(details))
        # Zero-width matches would produce zero-width highlights and an
        # infinite-looking match list (one per position); dropped rather
        # than rendered, with the count reported so the user can see their
        # pattern matched nothing useful.
        matches = [(m.start(), m.end()) for m in compiled.finditer(string) if m.end() > m.start()]
        self._search_matches = matches
        self._search_index = 0 if matches else -1

        if not matches:
            self.enc_search_prev_button.disabled = True
            self.enc_search_next_button.disabled = True
            if self._enc_highlight_stream is not None:
                self._enc_highlight_stream.event(spans=())
            self.enc_search_status.object = (
                f"**No matches** for `{pattern}` in {len(string):,} symbols."
            )
            return

        capped = matches[:ENCODING_HIGHLIGHT_CAP]
        if self._enc_highlight_stream is not None:
            self._enc_highlight_stream.event(spans=tuple(capped))
        self.enc_search_prev_button.disabled = len(matches) < 2
        self.enc_search_next_button.disabled = len(matches) < 2

        cap_note = ""
        if len(matches) > ENCODING_HIGHLIGHT_CAP:
            cap_note = (f" Highlighting the first {ENCODING_HIGHLIGHT_CAP:,} only "
                        "(rendering every one would stall pan/zoom); Prev/Next still "
                        "steps through all of them.")
        # Held separately and re-rendered by `_focus_morphology_match`,
        # which runs immediately below and would otherwise overwrite it —
        # the cap notice must survive stepping, not flash once and vanish.
        self._search_summary = (
            f"**{len(matches):,} match{'es' if len(matches) != 1 else ''}** for `{pattern}` "
            f"in {len(string):,} symbols.{cap_note}"
        )
        self._focus_morphology_match(0)

    def _match_time_span(self, seg_start, seg_end):
        """(t0, t1) in seconds for a match covering segments
        [seg_start, seg_end)."""
        _x, t, _symbols, details, _recording = self._last_encoding
        seg_t = segment_time_edges(t, int(details["n_symbols"]), int(details["samples_per_symbol"]))
        i0 = int(np.clip(seg_start, 0, len(seg_t) - 1))
        i1 = int(np.clip(seg_end, 0, len(seg_t) - 1))
        return float(seg_t[i0]), float(seg_t[i1])

    def _focus_morphology_match(self, index):
        """Recentre the encoding view's x-range on one match, through the
        SAME `range_stream` the panels already share — so all four panels
        move together and the string/RLE "Visible range only" display
        follows, rather than a second, independent notion of "where we are
        looking"."""
        if not self._search_matches or self._last_encoding is None:
            return
        index = int(index) % len(self._search_matches)
        self._search_index = index
        seg_start, seg_end = self._search_matches[index]
        t0, t1 = self._match_time_span(seg_start, seg_end)
        duration = t1 - t0
        # A match rendered edge-to-edge is hard to see in context; one
        # match-width of padding either side keeps the surrounding shape
        # visible, which is what makes a morphology judgeable at all.
        pad = max(duration, 1e-9)
        if self._enc_range_stream is not None:
            self._enc_range_stream.event(x_range=(t0 - pad, t1 + pad))
        # ASCII only: this string is echoed to a cp1252 console by a failing
        # test's `[FAIL]` line, and an em-dash there raises
        # UnicodeEncodeError inside the test runner itself (BASELINE.md).
        self.enc_search_status.object = (
            f"{self._search_summary}\n\n"
            f"**Match {index + 1} of {len(self._search_matches):,}** - segments "
            f"{seg_start}-{seg_end - 1}, {t0:,.1f}s to {t1:,.1f}s ({duration:,.1f}s long)."
        )
        self._refresh_encoding_string_display()

    def _step_morphology_match(self, delta):
        if not self._search_matches:
            return
        self._focus_morphology_match(self._search_index + int(delta))

    # ── Noise-floor estimate (dSAX Phase D) ──────────────────────────────

    def _sync_noise_floor_controls(self, x, details):
        """Visible only for a delta-domain encoding, and disabled above the
        span ceiling — a surrogate half-width has no meaning for a PAA
        encoding, and drawing surrogates of a multi-million-sample span is
        not a thing to make someone wait for behind a diagnostic."""
        is_delta = cutline_domain(details) == "delta"
        self.enc_noise_floor_button.visible = is_delta
        self.enc_noise_floor_alpha.visible = is_delta
        self.enc_noise_floor_status.object = ""
        if not is_delta:
            return
        too_long = len(x) > NOISE_FLOOR_MAX_SAMPLES
        no_same_bin = same_band_halfwidth(details) is None
        self.enc_noise_floor_button.disabled = too_long or no_same_bin
        if too_long:
            self.enc_noise_floor_status.object = (
                f"*Noise-floor estimate disabled: this span is {len(x):,} samples, above the "
                f"{NOISE_FLOOR_MAX_SAMPLES:,}-sample limit. Estimate it on a shorter span "
                "of the same channel — the noise floor is a property of the signal, not of "
                "the span length.*"
            )
        elif no_same_bin:
            self.enc_noise_floor_status.object = (
                f"*Noise-floor estimate disabled: alphabet_size="
                f"{details['alphabet_size']} is even, so there is no SAME band to compare a "
                "floor against.*"
            )

    def _on_estimate_noise_floor(self, _event=None):
        """Measure how big a per-segment rise this signal produces with NO
        trend present, and compare it against the band Lloyd-Max learned.

        This is the gap IMPLEMENTATION_NOTES.md 6.3 measured at 3.1x on
        pure noise: Lloyd-Max minimises squared quantisation error against
        the observed delta density, which is a different question from "is
        this rise bigger than noise", and on a trendless signal it will
        happily label half the segments UP or DOWN and score 97% of its
        entropy ceiling doing it.

        Runs on a worker thread — `n_surrogates` FFTs of a long span is
        seconds, and blocking the Bokeh event loop for that would freeze
        every other control on the page with no explanation. NEVER re-runs
        the encoding: it reports a number and, at most, fills in the
        `min_same_halfwidth` control for the user to re-run deliberately.
        """
        if self._last_encoding is None:
            self.enc_noise_floor_status.object = "**Run an encoding first.**"
            return
        x, _t, _symbols, details, _recording = self._last_encoding
        if cutline_domain(details) != "delta":
            return

        alpha = float(self.enc_noise_floor_alpha.value)
        self.enc_noise_floor_button.disabled = True
        self.enc_noise_floor_status.object = "*Computing surrogates ...*"

        def _worker():
            try:
                started = time.time()
                # The half-width must be estimated in the WORKING delta
                # domain, because that is the domain `min_same_halfwidth`
                # is specified in — comparing a raw-domain estimate against
                # a normalised cutline differs by a factor of norm_std,
                # which on a fungal channel is two orders of magnitude.
                working = working_domain_array(x, details)
                sps = int(details["samples_per_symbol"])
                n_surrogates = noise_floor_surrogate_count(len(working))
                surrogate = surrogate_same_halfwidth(
                    working, sps, trend_estimator=details["trend_estimator"],
                    n_surrogates=n_surrogates, alpha=alpha, random_state=0,
                )
                elapsed = time.time() - started
                learned = same_band_halfwidth(details)
                projected, _ = same_fraction_under_halfwidth(details, surrogate)
                payload = {
                    "surrogate": surrogate, "learned": learned, "projected": projected,
                    "n_surrogates": n_surrogates, "elapsed": elapsed, "alpha": alpha,
                    "scale": details.get("delta_scale") or 1.0,
                    "observed": float(details.get("same_fraction_observed", 0.0)),
                }
            except Exception as e:                       # noqa: BLE001
                payload = {"error": repr(e)}
            _run_on_ui_thread(doc, lambda: self._on_noise_floor_finished(payload))

        # Captured on the SERVING thread, before the worker starts — see
        # `_run_on_ui_thread`'s docstring: reading `pn.state.curdoc` from
        # inside the worker returns nothing useful.
        doc = pn.state.curdoc
        self._noise_floor_thread = threading.Thread(target=_worker, daemon=True)
        self._noise_floor_thread.start()

    def _on_noise_floor_finished(self, payload):
        self.enc_noise_floor_button.disabled = False
        if "error" in payload:
            self.enc_noise_floor_status.object = f"**Noise-floor estimate failed:** {payload['error']}"
            return

        surrogate = payload["surrogate"]
        learned = payload["learned"]
        scale = payload["scale"]
        ratio = surrogate / learned if learned else float("inf")

        # The recommendation is stated only in the form the evidence
        # supports: a ratio is a measurement, "your labels are noise" is a
        # conclusion, and only the first is being reported here.
        if ratio >= NOISE_FLOOR_RATIO_ALERT:
            verdict = (
                f"**The learned SAME band is {ratio:.1f}x narrower than the noise floor.** "
                "A large share of the UP/DOWN labels in this encoding are likely to be noise "
                "rather than trend. Consider setting `min_same_halfwidth` below and re-running."
            )
        else:
            verdict = (
                f"The learned SAME band is within {ratio:.2f}x of the noise floor — the UP/DOWN "
                "labels are not obviously attributable to noise at this alpha."
            )

        # Fill the control in, but never re-run: a diagnostic that silently
        # changes the thing it measured is not a diagnostic.
        set_note = ""
        w = self._param_widgets.get("min_same_halfwidth")
        if w is not None and not w.disabled:
            self._suppress_param_watchers = True
            try:
                w.value = float(surrogate)
            finally:
                self._suppress_param_watchers = False
            set_note = (
                f"\n\n`min_same_halfwidth` has been set to **{surrogate:.6g}** "
                "(working delta units). **Re-run for it to take effect** — nothing has been "
                "recomputed."
            )

        self.enc_noise_floor_status.object = (
            f"{verdict}\n\n"
            f"| | working units | raw units |\n|---|---|---|\n"
            f"| learned SAME half-width | {learned:.6g} | {learned * scale:.6g} |\n"
            f"| surrogate half-width (alpha={payload['alpha']:.3g}) | {surrogate:.6g} "
            f"| {surrogate * scale:.6g} |\n"
            f"| ratio surrogate / learned | {ratio:.2f}x | |\n\n"
            f"SAME fraction now **{payload['observed'] * 100:.1f}%**; it would be "
            f"**{payload['projected'] * 100:.1f}%** with the floor imposed. "
            f"({payload['n_surrogates']} surrogates, {payload['elapsed']:.2f}s.)"
            f"{set_note}"
        )

    def _on_save_encoding_as_motif(self, _event=None):
        """Part 4e: save the current span + string + full recipe as a
        motif in one click, without requiring a detection first — the
        exact workflow this whole view exists to support."""
        self.enc_seed_motif_status.object = ""
        if self._last_encoding is None or self._last_recipe is None:
            self.enc_seed_motif_status.object = "**Run an encoding first.**"
            return
        _x, _t, symbols, details, recording = self._last_encoding
        span = self._last_recipe["span"]
        start, end = (0, recording["n_samples"]) if span is None else span

        config_id, _hash8 = R.get_or_create_config(self.conn, self._last_recipe)
        run_row = R.find_completed_run(self.conn, config_id, recording["id"], start, end)
        run_id = run_row["id"] if run_row is not None else R.insert_run(
            self.conn, config_id, recording["id"], start, end, status="completed",
        )
        detection_id = R.insert_detection(self.conn, run_id, start, end)
        # A morphology pattern that currently MATCHES this encoding is the
        # most useful thing to record alongside the seed string: the string
        # says what this span looks like, the pattern says what class of
        # shape it was recognised as. Appended to the free-text notes
        # rather than given a column — `motifs` has no pattern field, and
        # inventing one is a schema change this work order does not cover.
        notes = self.motif_notes.value or None
        if self._search_matches:
            pattern_note = (f"morphology pattern: {self.enc_search_input.value} "
                            f"({len(self._search_matches)} matches in this span)")
            notes = f"{notes}\n{pattern_note}" if notes else pattern_note
        motif_id = R.insert_motif(
            self.conn, detection_id,
            label=self.motif_label.value or None, rating=self.motif_rating.value or None,
            notes=notes,
            sax_string=symbols_to_string(symbols, symbol_letters(details)),
        )
        if self.motif_elements.value:
            v.set_motif_tags(self.conn, motif_id, "element", self.motif_elements.value)
        self.enc_seed_motif_status.object = f"Saved motif id={motif_id} with this encoding's seed string."
        self._clear_motif_fields()

    # ── 5d: save as motif ────────────────────────────────────────────────

    def _show_detections(self, detection_rows):
        records = [{"id": d["id"], "start_idx": d["start_idx"], "end_idx": d["end_idx"],
                    "score": d["score"]} for d in detection_rows]
        self.detections_table.value = pd.DataFrame(
            records, columns=["id", "start_idx", "end_idx", "score"]
        )
        # Part 5 C3: an empty Tabulator still renders its header row, which
        # reads as "something's broken", not "zero detections" — a plain
        # sentence is unambiguous either way (no run yet vs. a completed
        # run that just found nothing).
        if records:
            self.detections_table.visible = True
            self.detections_placeholder.visible = False
        else:
            self.detections_table.visible = False
            self.detections_placeholder.visible = True
            self.detections_placeholder.object = "*No detections in this run.*"

    def _find_sax_string_for_span(self, recording_id, start, end):
        from Working.encoding_cache import read_encoding_file
        for enc in R.list_encodings(self.conn, recording_id):
            if enc["span_start"] == start and enc["span_end"] == end \
                    and enc["encoding_type"].startswith("sax"):
                try:
                    return read_encoding_file(enc["path"])
                except Exception:
                    return None
        return None

    def _save_motif(self, detection_id, recording_id, start, end):
        sax_string = self._find_sax_string_for_span(recording_id, start, end)
        motif_id = R.insert_motif(
            self.conn, detection_id,
            label=self.motif_label.value or None,
            rating=self.motif_rating.value or None,
            notes=self.motif_notes.value or None,
            sax_string=sax_string,
        )
        if self.motif_elements.value:
            v.set_motif_tags(self.conn, motif_id, "element", self.motif_elements.value)
        return motif_id

    def _on_save_detection_as_motif(self, _event=None):
        self.motif_status.object = ""
        df = self.detections_table.value
        selected = self.detections_table.selection
        if not selected:
            self.motif_status.object = "**Select a detection row first.**"
            return
        row = df.iloc[selected[0]]
        detection_id = int(row["id"])
        det = R.get_detection(self.conn, detection_id)
        run = R.get_run(self.conn, det["run_id"])
        motif_id = self._save_motif(detection_id, run["recording_id"], det["start_idx"], det["end_idx"])
        self.motif_status.object = f"Saved motif id={motif_id} (inherited recipe from run_id={det['run_id']})."
        self._clear_motif_fields()

    def _on_save_viewport_as_motif(self, _event=None):
        self.motif_status.object = ""
        try:
            span = self._current_span()
        except ValueError as e:
            self.motif_status.object = f"**{e}**"
            return
        if span is None:
            self.motif_status.object = "**Choose 'Selected span' or 'Current viewport', not 'Whole channel'.**"
            return
        start, end = span

        # A manual span still goes through a (trivial) recipe/run/detection
        # so every motif — algorithmic or manual — inherits its metadata
        # through the same chain, with no special-cased nullable columns.
        recipe = make_recipe(
            self.app._recording_id,
            [{"stage": "catalogue", "algorithm": "manual_selection", "params": {}}],
            span=(start, end),
        )
        config_id, _hash8 = R.get_or_create_config(self.conn, recipe)
        run_id = R.insert_run(self.conn, config_id, self.app._recording_id, start, end, status="completed")
        detection_id = R.insert_detection(self.conn, run_id, start, end)
        motif_id = self._save_motif(detection_id, self.app._recording_id, start, end)
        self.motif_status.object = f"Saved motif id={motif_id} from a manual selection (run_id={run_id})."
        self._clear_motif_fields()

    def _clear_motif_fields(self):
        self.motif_label.value = ""
        self.motif_elements.value = []
        self.motif_rating.value = 0
        self.motif_notes.value = ""

    # ── Save plot (explicit only — never automatic) ─────────────────────

    def _on_save_plot(self, _event=None):
        self.save_plot_status.object = ""
        if self._last_recipe is None:
            self.save_plot_status.object = "**Run something first.**"
            return

        recipe = self._last_recipe
        last_step = recipe["steps"][-1]
        spec = get_adapter(f"{last_step['stage']}.{last_step['algorithm']}")
        if spec.plot is None:
            self.save_plot_status.object = "**This algorithm has no plotting hook.**"
            return

        recording = q.get_recording_by_id(self.conn, recipe["recording_id"])
        span = recipe["span"]
        start, end = (0, recording["n_samples"]) if span is None else span
        x_full = np.load(recording["npy_path"], mmap_mode="r")
        x = np.asarray(x_full[start:end])
        t = np.arange(start, end) / recording["fs"]

        params = spec.validate_params(last_step["params"])
        # Recomputed here rather than reusing the run's result: the run
        # panel only ever passes plain data across the worker-thread
        # boundary (see `_gather_display_data`), and re-running a single
        # step on a bounded span for a plot is cheap relative to the run
        # itself.
        result = spec.run(x, t, recording["fs"], **params)
        fig = spec.plot(x, t, result, **params)

        config_id, hash8 = R.get_or_create_config(self.conn, recipe)
        path = save_plot(
            fig, recording["source_file"], recording["channel"],
            last_step["stage"], f"{last_step['stage']}.{last_step['algorithm']}",
            params, hash8,
        )
        run_row = R.find_completed_run(self.conn, config_id, recipe["recording_id"], start, end)
        run_id = run_row["id"] if run_row is not None else R.insert_run(
            self.conn, config_id, recipe["recording_id"], start, end, status="completed",
        )
        R.insert_artifact(self.conn, run_id, "plot", path)
        self.save_plot_status.object = f"Saved: `{path}`"

    # ── Layout ───────────────────────────────────────────────────────────

    def layout(self):
        return pn.Row(
            pn.Column(
                pn.pane.Markdown("### Staged spans"),
                self.staged_badge,
                self.staged_table,
                # A row of fixed-width buttons in the sidebar uses
                # `pn.FlexBox`, not `pn.Row` — per UI/README.md, `Row`
                # does not wrap and bleeds past the sidebar's right edge
                # into the main column instead of clipping/wrapping in
                # place (the exact bug that hit the zoom presets once).
                pn.FlexBox(self.remove_staged_button, self.clear_staged_button),
                pn.layout.Divider(),
                pn.pane.Markdown("### Run an algorithm"),
                self.stage_select, self.algorithm_select,
                pn.pane.Markdown("**Span:**"), self.span_mode,
                pn.pane.Markdown("**Preprocessing (applied first):**"),
                self.preprocess_select, self.preprocess_window,
                pn.pane.Markdown("**Parameters:**"), self.param_column,
                # Beside, not inside, the auto-generated param form (§3,
                # ground rules) — hidden entirely unless the window-matrix
                # algorithm is selected (`set_visible`).
                self.window_matrix_panel.layout(),
                pn.pane.Markdown("**Derived:**"), self.derived_pane,
                self.span_changed_note,
                pn.Row(self.auto_preview_checkbox),
                pn.Row(self.reset_recommended_button),
                pn.FlexBox(self.run_button, self.cancel_button),
                self.status, self.duration_pane,
                width=480,  # Part 7, Part 3 item 6 (was 440) — shortened
                # labels mean this is no longer needed for THAT, but the
                # staged-spans table's 6 columns via `layout="fit_columns"`
                # still want the room, with no horizontal scrollbar.
                styles={"overflow-x": "hidden"},  # backstop per UI/README.md's FlexBox note
            ),
            pn.Column(
                pn.pane.Markdown("### Result"),
                self.preview_info,
                pn.pane.Markdown("**Y-axis (Before/After):**"), self.yaxis_mode,
                self.result_pane,
                # §4: one coverage-ribbon pane per ladder scale that has any
                # stored coverage, stacked directly under the staged-span
                # preview — hidden (empty Column) unless the window-matrix
                # algorithm is selected AND something is actually covered.
                self.window_matrix_panel.ribbon_column,
                self.scale_note,
                pn.Row(self.save_plot_button, self.save_plot_status),
                self.encoding_section,  # Part 6, 4f: hidden entirely unless the last run was an encoding
                pn.pane.Markdown("### Detections (this run)"),
                self.detections_placeholder,
                self.detections_table,
                pn.layout.Divider(),
                self.motif_gate_note,
                pn.pane.Markdown(
                    "### Save as motif\n"
                    "Recording, channel, span, and the full recipe are inherited "
                    "automatically from the run — only fill in what's below."
                ),
                self.motif_label, self.motif_elements, self.motif_rating, self.motif_notes,
                pn.Row(self.save_motif_button, self.save_viewport_motif_button),
                self.motif_status,
                sizing_mode="stretch_width",
            ),
            sizing_mode="stretch_width",
        )
