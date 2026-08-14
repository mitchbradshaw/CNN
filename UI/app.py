"""
app.py
=======
Panel entry point for the signal viewer + annotation UI. The only place in
this project that Panel/HoloViews/Datashader are imported outside `UI/`
itself — everything in `Working/` and `Pipelines/` stays headless.

Run
---
    panel serve UI/app.py --show
    python UI/app.py

Architecture
------------
`ViewerApp` (a `param.Parameterized`) owns the database connection, the
current recording selection, and the persistent HoloViews `DynamicMap` +
streams for the plot. Widgets are built and wired in `layout()`. All actual
reads/writes go through `Working.database.queries` /
`vocabulary` — the same functions a headless SLURM script would call.

Tags replace the old free-text `tag` field (the column still exists on
`annotations` for historic rows, but new annotations are tagged through the
controlled vocabulary instead — see `Working.database.vocabulary`).
Spike-train-length and duration bands are never stored: they're computed
fresh on every read from `event_count` / `(end_idx-start_idx)/fs` via
`Working.database.bands`, and used both as extra table columns
and as filter options.
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import io
import json
import os
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import holoviews as hv
import numpy as np
import pandas as pd
import panel as pn
import param

from UI.admin import VocabularyAdmin
from UI.file_import import FileImportPanel
from UI.run_panel import RunPanel
from UI.run_history import RunHistoryBrowser
from UI.motif_browser import MotifBrowser
from UI.plots import (
    build_annotation_ribbon,
    build_channel_dmap,
    build_detection_overlay,
    build_peek_curve,
    build_pending_selection_overlay,
    build_reviewed_ribbon,
    build_selected_overlay,
    format_scale_viewed,
    load_channel_mmap,
    style_main_plot_frame,
    x_range_to_sample_bounds,
)
from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import vocabulary as v
from Working.database import bands as b
from Working.database import runs as R
from Working.database.similarity import find_similar_annotations, find_near_duplicate_pairs
from Working.config import (
    OVERLAY_DENSITY_THRESHOLD, SESSION_STATE_PATH, UI_BASE_FONT_SIZE, UI_MONO_FONT_SIZE,
    UI_TABLE_FONT_SIZE, ZOOM_PRESETS_SECONDS,
)

# Part 7: one app-wide readability baseline, from Working/config.py's font
# constants — NOT scattered per-widget. Tabulator renders inside its OWN
# shadow DOM (a separate web component) and does not inherit Panel's own
# font sizing at all, so it needs its own explicit rule; the symbol
# string/RLE boxes (`.bk-input textarea`, used nowhere else as textareas
# in this app) get the monospace-box size.
_READABILITY_CSS = f"""
.bk-root, .bk-input, .bk-btn, .bk-slider-title, .bk-clearfix, label, .markdown {{
    font-size: {UI_BASE_FONT_SIZE} !important;
}}
.tabulator, .tabulator-cell, .tabulator-col-title, .tabulator-header {{
    font-size: {UI_TABLE_FONT_SIZE} !important;
}}
.bk-input[type="textarea"], textarea.bk-input {{
    font-size: {UI_MONO_FONT_SIZE} !important;
    font-family: monospace !important;
}}
"""

pn.extension("tabulator", raw_css=[_READABILITY_CSS])
hv.extension("bokeh")

# Drives the annotation/reviewed/detection/pending-selection overlay
# DynamicMaps (see ViewerApp._rebuild_plot). Reassigning `plot_pane.object`
# on every routine update turned out to replace the *entire* underlying
# Bokeh plot model each time — confirmed with a real bokeh.document.Document,
# the model's `id` changed on every refresh even though no Python object
# it was built from did — which silently tore down the BoxSelectTool's
# live event wiring along with it. Triggering this stream instead lets
# Panel patch the existing model's data in place. See UI/plots.py module
# docstring, bug 4.
_RefreshTrigger = hv.streams.Stream.define("RefreshTrigger", tick=0)

# Categories offered per-annotation. "provenance" is excluded here: it's set
# automatically by importers and not user-editable (per the brief), but is
# still manageable in the admin panel and filterable in the table.
ANNOTATION_TAG_CATEGORIES = ["element", "quality", "structure"]
FILTER_TAG_CATEGORIES = ["element", "quality", "structure", "provenance", "status"]
# Derived from the same config tables bands.py reads, not hand-copied — spike
# and duration bands have different label sets (3 vs 5) since Working/config.py's
# fix for the duration_band bug.
SPIKE_BAND_OPTIONS = [label for _, label in b.SPIKE_TRAIN_BANDS]
DURATION_BAND_OPTIONS = [label for _, label in b.DURATION_BANDS_S]

TABLE_COLUMNS = ["pinned", "id", "start_idx", "end_idx", "verdict", "status", "event_count",
                  "spike_train_band", "duration_band", "element", "quality",
                  "structure", "source", "note", "created_at"]
# D3: which columns accept inline edits, and how -- everything else gets an
# explicit `None` editor (Tabulator's way of saying "not editable"), since
# the widget-level `disabled=False` needed for these has to also apply to
# the columns that must NOT change from a table cell (id, start_idx,
# source, band labels derived from other fields, ...).
EDITABLE_COLUMNS = {
    "verdict": {"type": "list", "values": list(q.VERDICTS)},
    "status": "input",
    "event_count": "input",
    "note": "input",
}
TABLE_EDITORS = {col: (EDITABLE_COLUMNS[col] if col in EDITABLE_COLUMNS else None)
                  for col in TABLE_COLUMNS}

# A drag means three different things depending on `drag_mode`, and picking
# the wrong one fails *silently* — no error, just not the effect you
# expected. Each mode gets its own background colour behind an explicit
# sentence (see `drag_mode_description`), not just the RadioButtonGroup's
# own active-option highlight, which is easy to miss mid-workflow.
_DRAG_MODE_DESCRIPTIONS = {
    "Pan": "**Dragging will pan the view.**",
    "New span": "**Dragging will create a new pending span** for a fresh annotation.",
    "Select annotations": "**Dragging will toggle-select existing annotations** it covers.",
}
_DRAG_MODE_COLORS = {
    "Pan": "#e8e8e8",
    "New span": "#dceaf7",
    "Select annotations": "#fdf1cf",
}
_DRAG_MODE_STYLE_BASE = {
    "padding": "6px 10px", "border-radius": "4px", "border": "1px solid #999",
}

# Part C1: section headers (`### Recording`, `### Filters`, ...) render at
# the same size as any other bold text by default -- easy to lose track of
# where one logical section ends and the next begins in a long column.
# Bumped up and given a bit of top margin so a new section is unmistakable
# at a glance, without needing a full visual redesign.
SECTION_HEADER_STYLE = {"font-size": "1.15em", "margin-top": "0.6em"}


def _format_duration_human(seconds):
    """"12 min 30 s" / "3 h 20 min" / "45 s" — the two largest applicable
    units, dropping the smaller one when it's zero. Used for the pending
    span's live width readout (Part 2b)."""
    seconds = abs(seconds)
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    total_s = int(round(seconds))
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h} h {m} min" if m else f"{h} h"
    if m > 0:
        return f"{m} min {s} s" if s else f"{m} min"
    return f"{s} s"


class ViewerApp(param.Parameterized):

    source_file = param.Selector(default=None, objects=[])
    channel = param.Selector(default=None, objects=[])
    verdict = param.Selector(default="interesting", objects=list(q.VERDICTS))
    note = param.String(default="")

    def __init__(self, db_path=None, **params):
        super().__init__(**params)
        self.conn = init_db(db_path)
        v.seed_vocabulary(self.conn)

        self._recording_id = None
        self._fs = None
        self._n_samples = None
        self._dmap = None
        self._range_stream = None
        self._bounds_stream = None
        self._refresh_trigger = None  # set in _rebuild_plot; see module-level _RefreshTrigger
        self._full_extent = (0.0, 1.0)
        self._y_extent = (0.0, 1.0)
        self._pending_bounds = None
        self._updating_time_fields = False  # re-entrancy guard, see _sync_time_fields_from_bounds
        self._time_unit = "s"  # "s" or "h" — see ViewerApp._unit_scale and _on_time_unit_toggle
        self._selected_annotation_ids = set()  # the one shared selection model — table & plot both read/write this
        self._updating_annotation_selection = False  # re-entrancy guard, see _sync_table_selection_from_ids
        self._similar_annotation_id = None  # best near-duplicate match for the pending span, if any
        self._staged_spans = []  # in-memory cross-tab basket; see _stage_span (Part 3)
        self._channel_mmap = None  # set in _rebuild_plot; reused for the ribbons' local y-range
        self._y_pan_fraction = 0.0  # vertical pan offset (Part C3), fraction of current y-span
        self._nav_current_id = None  # annotation navigator's current position (Part E1)
        self._pending_bulk_action = None  # (kind, value) staged by a "Stage ... change" button (Part E6)
        self._last_deleted_ids = []  # most recent soft-delete batch, for undo (Part E7)
        self._restoring_session = False  # re-entrancy guard: suppress saves while applying a loaded session
        self._init_complete = False  # suppresses saves during __init__'s own source_file/channel bootstrap
        self._session_state = self._load_session_state()  # read once here; applied after widgets exist (Part E9)
        # Part B6: accordion open/closed is UI chrome, not recording-specific
        # data, so (unlike filters/viewport) it's read here UNCONDITIONALLY --
        # not gated on the saved source_file matching what actually loads --
        # and applied at accordion-construction time in `layout()`, which
        # runs after `__init__` and needs the value before the widgets exist.
        self._initial_accordion_active = (self._session_state or {}).get("accordion_active", {})

        self.status = pn.pane.Markdown("", styles={"color": "#a33"})
        self.selection_info = pn.pane.Markdown("")
        self.summary_pane = pn.pane.Markdown("")

        self.time_unit_toggle = pn.widgets.RadioButtonGroup(
            name="Time unit", options=["seconds", "hours"], value="seconds",
        )
        self.time_unit_toggle.param.watch(self._on_time_unit_toggle, "value")

        # Part E2: fixed viewport widths, one click, exactly reproducible —
        # not a scroll-wheel guess, since switching timescale is central to
        # the actual research question here.
        self.viewport_width_display = pn.pane.Markdown("**Viewport width:**")
        self.zoom_preset_buttons = {}
        for label, seconds in ZOOM_PRESETS_SECONDS:
            btn = pn.widgets.Button(name=label, button_type="default", width=70)
            btn.on_click(lambda _e, s=seconds: self._on_zoom_preset(s))
            self.zoom_preset_buttons[label] = btn
        self.zoom_preset_full_button = pn.widgets.Button(name="Full channel", button_type="default", width=90)
        self.zoom_preset_full_button.on_click(self._on_zoom_preset_full)

        # Part E1: step through the FILTERED/SEARCHED set in index order —
        # with thousands of annotations, scrolling a table isn't workable.
        self.nav_prev_button = pn.widgets.Button(name="< Prev annotation", button_type="default")
        self.nav_prev_button.on_click(self._on_nav_prev)
        self.nav_next_button = pn.widgets.Button(name="Next annotation >", button_type="default")
        self.nav_next_button.on_click(self._on_nav_next)
        self.nav_padding_fraction_input = pn.widgets.FloatInput(
            name="Navigator padding (fraction of span)", value=0.5, start=0.0, end=5.0, width=200,
        )

        # Part E3: VIEW TRANSFORMS — display only, never alter stored data
        # (annotations/reviewed-spans store sample indices, never amplitude
        # values, so there is no path from these to the database regardless
        # — see build_channel_dmap's docstring). Off by default; the banner
        # below is deliberately loud, so a transformed view is never
        # mistaken for raw data.
        self.dc_offset_toggle = pn.widgets.Checkbox(name="Remove DC offset (display only)", value=False)
        self.detrend_toggle = pn.widgets.Checkbox(name="Light detrend (display only)", value=False)
        self.y_autoscale_toggle = pn.widgets.Checkbox(name="Y-autoscale to viewport", value=True)
        self.view_transform_banner = pn.pane.Markdown("", styles={"display": "none"})
        for w in (self.dc_offset_toggle, self.detrend_toggle, self.y_autoscale_toggle):
            w.param.watch(self._on_view_transform_changed, "value")

        # Part E4: cross-channel peek — a small linked panel showing the
        # SAME time span on another channel. Equipment faults tend to
        # appear on every channel at once; real biological activity
        # doesn't, so this is a fast artifact/signal discriminator.
        self.cross_channel_select = pn.widgets.Select(name="Compare with channel", options=["(none)"])
        self.cross_channel_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.cross_channel_select.param.watch(lambda _e: self._rebuild_cross_channel_peek(), "value")

        # Drag-select is the primary way to pick a span, but the two number
        # fields below are always kept in sync with it and are independently
        # editable — a reliable fallback if a drag ever misbehaves, and the
        # "prefilled with the current bounds" indicator that makes a live
        # selection unambiguous at a glance.
        #
        # One 3-way control, not two overlapping toggles: Bokeh only ever
        # has one active drag tool, so "pan" vs "box-select" was already a
        # single choice, and what a box-select's result MEANS (a new span,
        # vs which existing annotations it covers) is a second single
        # choice layered on top of the same drag gesture — modelling both
        # as one RadioButtonGroup makes the current mode unambiguous at a
        # glance and makes an invalid combination (e.g. "select annotations
        # while also creating a new span") structurally impossible, rather
        # than something to guard against.
        self.drag_mode = pn.widgets.RadioButtonGroup(
            name="Drag mode", options=["Pan", "New span", "Select annotations"],
            value="New span", button_type="primary",
        )
        self.drag_mode.param.watch(self._on_drag_mode_changed, "value")
        # The RadioButtonGroup's own active-option highlighting is easy to
        # miss mid-workflow — a drag now means three different things, and
        # a wrong-mode drag fails *silently* (no error, just the wrong
        # effect), so this restates the current mode as a sentence with its
        # own mode-coloured background, impossible to miss.
        self.drag_mode_description = pn.pane.Markdown(
            _DRAG_MODE_DESCRIPTIONS[self.drag_mode.value],
            styles=dict(_DRAG_MODE_STYLE_BASE, background=_DRAG_MODE_COLORS[self.drag_mode.value]),
        )
        self.start_time_input = pn.widgets.FloatInput(name="Start Time (s)", value=None, width=300)
        self.end_time_input = pn.widgets.FloatInput(name="End Time (s)", value=None, width=300)
        self.start_time_input.param.watch(self._on_time_field_changed, "value")
        self.end_time_input.param.watch(self._on_time_field_changed, "value")
        self.start_sample_info = pn.pane.Markdown("")
        self.end_sample_info = pn.pane.Markdown("")
        self.pending_width_info = pn.pane.Markdown("")
        self.similarity_warning = pn.pane.Markdown("")
        self.compare_similar_button = pn.widgets.Button(
            name="Compare with existing", button_type="default", visible=False, width=200,
        )
        self.compare_similar_button.on_click(self._on_compare_similar)
        self.clear_selection_button = pn.widgets.Button(name="Clear selection", button_type="default")
        self.clear_selection_button.on_click(self._on_clear_selection)

        # ── Existing-annotation selection (distinct from the pending new
        # span above) — the shared table/plot selection model's UI.
        self.annotation_selection_info = pn.pane.Markdown("*No annotations selected.*")
        # "Select annotations" mode is toggle-only (no ctrl/shift-extend —
        # BoundsX doesn't expose which modifier was held, see the drag_mode
        # docstring), so selection only ever accumulates until explicitly
        # cleared. That makes this button load-bearing, not a convenience —
        # sized and coloured to be found at a glance, and bound to Esc too
        # (see the hidden `_escape_key_button` wired up in `layout()`).
        self.clear_annotation_selection_button = pn.widgets.Button(
            name="Clear annotation selection (Esc)", button_type="warning", width=260,
        )
        self.clear_annotation_selection_button.on_click(self._on_clear_annotation_selection)
        self.zoom_to_selected_button = pn.widgets.Button(
            name="Zoom to selected", button_type="default",
        )
        self.zoom_to_selected_button.on_click(self._on_zoom_to_selected)
        self.run_selected_button = pn.widgets.Button(
            name="Run algorithms on selected", button_type="success",
        )
        self.run_selected_button.on_click(self._on_run_selected)
        self.staged_spans_badge = pn.pane.Markdown("**Staged: 0**")

        # Part E6: bulk operations on the selection model. Two-step —
        # "Stage ..." computes and shows the affected count (and how many
        # will be SKIPPED as imported without the override) but changes
        # nothing; only "CONFIRM" actually writes. Reuses
        # `allow_edit_imported_checkbox` (Part D3) as the same deliberate
        # override, rather than a second, easy-to-conflate checkbox.
        self.bulk_verdict_select = pn.widgets.Select(name="Set verdict", options=[""] + list(q.VERDICTS))
        self.bulk_apply_verdict_button = pn.widgets.Button(name="Stage verdict change", button_type="default")
        self.bulk_status_select = pn.widgets.Select(name="Set status", options=[""])
        self.bulk_apply_status_button = pn.widgets.Button(name="Stage status change", button_type="default")
        self.bulk_tag_category_select = pn.widgets.Select(name="Tag category", options=ANNOTATION_TAG_CATEGORIES)
        self.bulk_tag_value_select = pn.widgets.Select(name="Tag value", options=[])
        self.bulk_tag_action_select = pn.widgets.RadioButtonGroup(
            name="Tag action", options=["Add", "Remove"], value="Add",
        )
        self.bulk_apply_tag_button = pn.widgets.Button(name="Stage tag change", button_type="default")
        self.bulk_stage_for_algorithms_button = pn.widgets.Button(
            name="Stage selected for algorithms", button_type="success",
        )
        self.bulk_confirmation = pn.pane.Markdown("")
        self.bulk_confirm_button = pn.widgets.Button(
            name="CONFIRM bulk action", button_type="danger", disabled=True,
        )
        self.bulk_cancel_button = pn.widgets.Button(name="Cancel", button_type="default", disabled=True)
        self.bulk_apply_verdict_button.on_click(self._on_bulk_apply_verdict)
        self.bulk_apply_status_button.on_click(self._on_bulk_apply_status)
        self.bulk_apply_tag_button.on_click(self._on_bulk_apply_tag)
        self.bulk_stage_for_algorithms_button.on_click(self._on_run_selected)
        self.bulk_confirm_button.on_click(self._on_bulk_confirm)
        self.bulk_cancel_button.on_click(self._on_bulk_cancel)
        self.bulk_tag_category_select.param.watch(lambda _e: self._refresh_bulk_tag_value_options(), "value")
        self.find_near_duplicates_button = pn.widgets.Button(
            name="Find near-duplicates", button_type="default",
        )
        self.find_near_duplicates_button.on_click(self._on_find_near_duplicates)
        self.near_duplicates_report = pn.pane.Markdown("")

        # Part E5 (and Esc, pulled forward earlier since toggle-only
        # selection makes it essential, not a convenience): global keyboard
        # shortcuts for the labelling loop. Panel has no built-in
        # global-keyboard-shortcut hook, so each shortcut is a real,
        # visually-invisible Button wired to the same handler a visible
        # control would use, "clicked" programmatically by one shared
        # `pn.pane.HTML` script listening for `keydown` on `document` — see
        # `layout()`, where all of these are placed together.
        #
        # `opacity: 0` with real (1px) dimensions, not `width=0, height=0`
        # or `display: none` — either of those risks a browser/Bokeh CSS
        # layout rule collapsing a zero-size element out of the render
        # tree, which can make `.click()` silently do nothing in some
        # browsers (a real, plausible cause of an earlier Esc-doesn't-work
        # report). `pointer-events: none` just stops each button being an
        # invisible click-trap for the mouse; JS `.click()` bypasses that
        # entirely regardless.
        def _hidden_shortcut_button(css_class, handler):
            btn = pn.widgets.Button(
                name="", css_classes=[css_class], width=1, height=1,
                styles={"opacity": "0", "position": "fixed", "pointer-events": "none",
                        "top": "0", "left": "0"},
            )
            btn.on_click(handler)
            return btn

        self._shortcut_buttons = [
            _hidden_shortcut_button("shortcut-escape", self._on_clear_annotation_selection),
            _hidden_shortcut_button("shortcut-verdict-1", lambda _e: setattr(self, "verdict", "interesting")),
            _hidden_shortcut_button("shortcut-verdict-2", lambda _e: setattr(self, "verdict", "not_interesting")),
            _hidden_shortcut_button("shortcut-verdict-3", lambda _e: setattr(self, "verdict", "artifact")),
            _hidden_shortcut_button("shortcut-verdict-4", lambda _e: setattr(self, "verdict", "unsure")),
            _hidden_shortcut_button("shortcut-save", self._save_annotation),
            _hidden_shortcut_button("shortcut-next", self._on_nav_next),
            _hidden_shortcut_button("shortcut-prev", self._on_nav_prev),
            _hidden_shortcut_button("shortcut-review", self._mark_viewport_reviewed),
            _hidden_shortcut_button("shortcut-mode-pan", lambda _e: setattr(self.drag_mode, "value", "Pan")),
            _hidden_shortcut_button("shortcut-mode-newspan", lambda _e: setattr(self.drag_mode, "value", "New span")),
            _hidden_shortcut_button("shortcut-mode-selectann",
                                     lambda _e: setattr(self.drag_mode, "value", "Select annotations")),
        ]
        # `_escape_key_button`/`_escape_key_listener` names kept (rather
        # than renamed to "shortcut_listener") so anything that already
        # referenced them (tests, this turn's earlier C2 fix) still works.
        self._escape_key_button = self._shortcut_buttons[0]
        self._escape_key_listener = pn.pane.HTML(
            """
            <script>
            (function() {
                var KEY_MAP = {
                    'Escape': 'shortcut-escape',
                    '1': 'shortcut-verdict-1', '2': 'shortcut-verdict-2',
                    '3': 'shortcut-verdict-3', '4': 'shortcut-verdict-4',
                    'Enter': 'shortcut-save',
                    'n': 'shortcut-next', 'p': 'shortcut-prev',
                    'r': 'shortcut-review',
                    'z': 'shortcut-mode-pan', 'x': 'shortcut-mode-newspan', 'c': 'shortcut-mode-selectann'
                };
                function handleShortcut(e) {
                    var tag = (document.activeElement && document.activeElement.tagName) || '';
                    if (tag === 'INPUT' || tag === 'TEXTAREA') { return; }
                    var cls = KEY_MAP[e.key];
                    if (!cls) { return; }
                    var candidates = document.querySelectorAll('.' + cls + ', .' + cls + ' button');
                    candidates.forEach(function(el) {
                        if (el.tagName === 'BUTTON') { el.click(); }
                    });
                }
                document.removeEventListener('keydown', window.__annotationShortcutHandler || function(){});
                window.__annotationShortcutHandler = handleShortcut;
                document.addEventListener('keydown', handleShortcut);
            })();
            </script>
            """,
            width=1, height=1, margin=0, styles={"opacity": "0"},
        )
        self.shortcut_reference = pn.pane.Markdown(
            "**Keyboard shortcuts** (not while typing in a text field): "
            "`1`-`4` = verdict (interesting/not interesting/artifact/unsure) &nbsp;|&nbsp; "
            "`Enter` = save annotation &nbsp;|&nbsp; `n`/`p` = next/previous annotation &nbsp;|&nbsp; "
            "`Esc` = clear annotation selection &nbsp;|&nbsp; `r` = mark viewport reviewed &nbsp;|&nbsp; "
            "`z`/`x`/`c` = drag mode: Pan / New span / Select annotations",
            styles={"background": "#f0f0f0", "padding": "6px 10px", "border-radius": "4px"},
        )

        # Part A (2026-08 restructure): the reviewed-coverage and
        # annotation-density ribbons are separate, thin panes stacked
        # directly above/below the main plot (`layout()`), not overlays
        # inside it — see UI/plots.py's module docstring for why. `.object`
        # is set in `_rebuild_plot`; `.visible` is bound to the existing
        # show/hide toggles below so switching a ribbon off collapses its
        # pane entirely instead of leaving an empty strip (Part A4).
        self.reviewed_ribbon_pane = pn.pane.HoloViews(sizing_mode="stretch_width", linked_axes=False)
        self.annotation_ribbon_pane = pn.pane.HoloViews(sizing_mode="stretch_width", linked_axes=False)
        self.plot_pane = pn.pane.HoloViews(sizing_mode="stretch_width", linked_axes=False)
        # D3: disabled=False + per-column `editors` (None = not editable)
        # enables inline editing for exactly verdict/status/event_count/note
        # — every other column (id, indices, source, derived bands, tags)
        # stays read-only from the table regardless.
        self.annotations_table = pn.widgets.Tabulator(
            pd.DataFrame(columns=TABLE_COLUMNS), page_size=12, disabled=False,
            editors=TABLE_EDITORS, selectable="checkbox", show_index=False,
            sizing_mode="stretch_width",
        )
        self.annotations_table.param.watch(self._on_table_selection_changed, "selection")
        self.annotations_table.on_edit(self._on_table_cell_edited)
        # A deliberate, separate override — editing an imported annotation
        # from the table must never be a one-click accident. Off by default.
        self.allow_edit_imported_checkbox = pn.widgets.Checkbox(
            name="Allow editing imported annotations (source != manual_ui)", value=False,
        )

        # ── New-annotation tag widgets, populated from the vocabulary ──────
        self.element_widget = pn.widgets.MultiChoice(name="element", options=[])
        self.quality_widget = pn.widgets.Select(name="quality", options=[""])
        self.structure_widget = pn.widgets.Select(name="structure", options=[""])
        self.status_widget = pn.widgets.Select(name="status", options=[""])
        self.event_count_widget = pn.widgets.TextInput(
            name="event_count (optional)", placeholder="e.g. 16",
        )

        # ── Filter widgets — affect both the table and the plot overlay ───
        self.filter_verdict = pn.widgets.MultiChoice(name="verdict", options=list(q.VERDICTS))
        self.filter_source = pn.widgets.MultiChoice(name="source", options=[])
        self.filter_tag_widgets = {
            cat: pn.widgets.MultiChoice(name=cat, options=[]) for cat in FILTER_TAG_CATEGORIES
        }
        self.filter_spike_band = pn.widgets.MultiChoice(name="spike-train length", options=SPIKE_BAND_OPTIONS)
        self.filter_duration_band = pn.widgets.MultiChoice(name="duration", options=DURATION_BAND_OPTIONS)
        self.clear_filters_button = pn.widgets.Button(name="Clear filters", button_type="default")
        self.clear_filters_button.on_click(self._on_clear_filters)

        # D2: search composes WITH the filters above (both apply), not
        # instead of them -- folded into the same `_filtered_annotation_rows`
        # every other consumer (table, plot overlay, live counts) already
        # calls, so there's no separate code path that could drift.
        self.search_id_input = pn.widgets.TextInput(
            name="Search by id", placeholder="e.g. 42, 108, 233",
        )
        self.search_text_input = pn.widgets.TextInput(
            name="Search note/tags", placeholder="free text",
        )

        self.filter_match_count = pn.pane.Markdown("")

        # Part E8: export the CURRENT filtered/searched set, tags and
        # derived bands included — `callback=` (not a static `file=`) so
        # each download reflects whatever's filtered/searched at click time.
        self.export_csv_button = pn.widgets.FileDownload(
            callback=self._export_csv_callback, filename="annotations.csv",
            button_type="default", label="Export filtered set (CSV)",
        )
        self.export_json_button = pn.widgets.FileDownload(
            callback=self._export_json_callback, filename="annotations.json",
            button_type="default", label="Export filtered set (JSON)",
        )

        # Independent show/hide toggles for the two overlay families — so
        # you can tell at a glance where an algorithm's detections agree or
        # disagree with your own annotations by looking at either alone.
        # `show_annotations_toggle` is ALSO the annotation ribbon pane's
        # show/hide (Part A4, 2026-08) -- there's nothing left to
        # separately show/hide on the main plot now that ribbons live in
        # their own panes, so "show annotations" and "show the annotation
        # pane" are the same question.
        self.show_annotations_toggle = pn.widgets.Checkbox(name="Show annotations", value=True)
        self.show_detections_toggle = pn.widgets.Checkbox(name="Show detections", value=True)
        self.show_annotations_toggle.param.watch(self._on_overlay_toggle_changed, "value")
        self.show_detections_toggle.param.watch(self._on_overlay_toggle_changed, "value")

        # Independent per-ribbon toggles (Part B), on by default.
        # `show_annotation_ribbon_toggle` does NOT show/hide the pane --
        # it controls the density THRESHOLD within it (off = always render
        # individual rectangles, even above the threshold, a deliberate
        # choice for precise inspection at the cost of possible
        # slowness); `show_annotations_toggle` above is what shows/hides
        # the pane itself. `show_reviewed_ribbon_toggle` has no such
        # sub-mode, so it directly shows/hides its own pane (Part A4).
        self.show_annotation_ribbon_toggle = pn.widgets.Checkbox(
            name="Show annotation density ribbon", value=True,
        )
        self.show_reviewed_ribbon_toggle = pn.widgets.Checkbox(
            name="Show reviewed-coverage ribbon", value=True,
        )
        self.show_annotation_ribbon_toggle.param.watch(self._on_overlay_toggle_changed, "value")
        self.show_reviewed_ribbon_toggle.param.watch(self._on_overlay_toggle_changed, "value")

        # Part A4: collapsing (not just emptying) a hidden ribbon pane --
        # `.visible = False` on a Panel pane removes it from the rendered
        # layout's flow entirely, unlike feeding it empty data (which used
        # to still reserve the overlay's full-height footprint).
        self.show_annotations_toggle.param.watch(self._update_ribbon_pane_visibility, "value")
        self.show_reviewed_ribbon_toggle.param.watch(self._update_ribbon_pane_visibility, "value")
        self._update_ribbon_pane_visibility()

        for w in [self.filter_verdict, self.filter_source, self.filter_spike_band,
                  self.filter_duration_band, self.search_id_input, self.search_text_input,
                  *self.filter_tag_widgets.values()]:
            w.param.watch(lambda _e: self._on_filters_changed(), "value")

        self.admin = VocabularyAdmin(self.conn)
        self.admin.on_change.append(self._refresh_vocabulary_options)
        self._refresh_vocabulary_options()

        self.file_import = FileImportPanel(self.conn, on_imported=[self._refresh_source_file_options])
        self.run_panel = RunPanel(self)
        self.run_history = RunHistoryBrowser(self)
        self.motif_browser = MotifBrowser(self)
        self.tabs = None  # set in layout(); lets RunHistoryBrowser switch tabs on "Reopen"

        source_files = sorted({r["source_file"] for r in q.list_recordings(self.conn)})
        if not source_files:
            raise RuntimeError(
                "No recordings in the database. Run "
                "Pipelines/materialize_channels/materialize_channels.py first."
            )
        self.param.source_file.objects = source_files
        saved = self._session_state
        initial_source_file = source_files[0]
        # Part C1: a stale session (its recording or channel has since been
        # removed) must degrade to defaults VISIBLY, not just silently --
        # otherwise a broken/misleading view (wrong channel, or filters
        # meant for a different recording) could look like a real bug in
        # the current one. Checked once, up front, so both halves of a
        # partial mismatch (recording gone entirely vs. just this channel)
        # get their own specific notice.
        stale_notice = None
        if saved and saved.get("source_file") and saved["source_file"] not in source_files:
            stale_notice = (
                f"**Saved session referenced recording \"{saved['source_file']}\" which no "
                "longer exists — starting with defaults.**"
            )
        elif saved and saved.get("source_file") in source_files:
            initial_source_file = saved["source_file"]
            saved_channels = sorted(
                r["channel"] for r in q.list_recordings(self.conn, initial_source_file)
            )
            if saved.get("channel") is not None and saved["channel"] not in saved_channels:
                stale_notice = (
                    f"**Saved session referenced channel {saved['channel']} of "
                    f"\"{initial_source_file}\", which no longer exists — using the "
                    "default channel instead.**"
                )
        self.source_file = initial_source_file
        self.filter_source.options = [q.SOURCE_IMPORTED_10MIN, q.SOURCE_MANUAL_UI, "excel_catalog"]
        self._refresh_channel_options()
        if saved and saved.get("channel") in self.param.channel.objects:
            self.channel = saved["channel"]
        self._load_recording()
        if stale_notice:
            self.status.object = stale_notice

        # Part E9: filters/search/toggles/view-transforms/time-unit/viewport,
        # restored once here (after the recording above is already loaded,
        # since the viewport restore needs `_range_stream` to exist) --
        # `_restoring_session` suppresses the save-on-change watchers below
        # so loading a session never immediately re-writes the same file.
        #
        # Only applied when the saved session's source_file is the one we
        # actually just loaded -- a session file from a DIFFERENT database
        # (a different `db_path`, e.g. a test's own temp sqlite file, or a
        # stale save from a source_file that's since been removed) must
        # never silently impose its filters/viewport onto an unrelated
        # recording set. This also keeps every temp-DB-backed test that
        # doesn't isolate SESSION_STATE_PATH from picking up unrelated
        # leftover state, though tests should isolate it too (see
        # tests/test_session_persistence.py's `_ScratchSessionFile`).
        if saved and saved.get("source_file") == initial_source_file:
            self._restoring_session = True
            try:
                self._restore_session_state(saved, stale_notice=stale_notice)
            finally:
                self._restoring_session = False
        self._init_complete = True

    # ── Session persistence (Part E9) ────────────────────────────────────
    #
    # A plain JSON file at SESSION_STATE_PATH, not a DB table -- this is
    # pure UI/session state (last recording, viewport, filters, toggles),
    # not data, and must never participate in the DB-row-count invariant.
    # Both read and write are best-effort: a missing/corrupt/stale session
    # file must never block startup or crash a later save, so every path
    # through these three methods is wrapped to fail silently.

    def _load_session_state(self):
        try:
            with open(SESSION_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            return state if isinstance(state, dict) else None
        except Exception:
            return None

    def _save_session_state(self):
        if self._restoring_session or not self._init_complete:
            return  # suppressed while applying a loaded session, or during __init__'s own bootstrap
        try:
            state = {
                "source_file": self.source_file,
                "channel": self.channel,
                "x_range": list(self._range_stream.x_range) if (
                    self._range_stream is not None and self._range_stream.x_range is not None
                ) else None,
                "time_unit": self._time_unit,
                "filter_verdict": list(self.filter_verdict.value),
                "filter_source": list(self.filter_source.value),
                "filter_tags": {cat: list(w.value) for cat, w in self.filter_tag_widgets.items()},
                "filter_spike_band": list(self.filter_spike_band.value),
                "filter_duration_band": list(self.filter_duration_band.value),
                "search_id": self.search_id_input.value,
                "search_text": self.search_text_input.value,
                "show_annotations": self.show_annotations_toggle.value,
                "show_detections": self.show_detections_toggle.value,
                "show_annotation_ribbon": self.show_annotation_ribbon_toggle.value,
                "show_reviewed_ribbon": self.show_reviewed_ribbon_toggle.value,
                "dc_offset": self.dc_offset_toggle.value,
                "detrend": self.detrend_toggle.value,
                "y_autoscale": self.y_autoscale_toggle.value,
                # Part B6: accordions only exist once `layout()` has run
                # (unlike every other widget above, which `__init__`
                # builds) -- fall back to whatever was already loaded
                # rather than dropping the saved value if a save happens
                # to fire before `layout()` is ever called.
                "accordion_active": (
                    {
                        "legend": list(self.legend_accordion.active),
                        "shortcuts": list(self.shortcuts_accordion.active),
                        "summary": list(self.summary_accordion.active),
                    }
                    if hasattr(self, "legend_accordion")
                    else self._initial_accordion_active
                ),
            }
            os.makedirs(os.path.dirname(SESSION_STATE_PATH), exist_ok=True)
            tmp_path = SESSION_STATE_PATH + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, SESSION_STATE_PATH)  # atomic on both POSIX and Windows
        except Exception:
            pass

    def _restore_session_state(self, saved, stale_notice=None):
        """Applies a loaded session dict to the already-constructed widgets
        and the already-loaded recording. Every field is validated against
        the CURRENT vocabulary/options before being applied -- a session
        saved against a since-edited vocabulary or a since-removed
        recording must degrade to "skip that one field", never crash
        startup.

        `stale_notice` (Part C1) is the visible warning already computed
        by `__init__` when the saved channel (but not the source_file) no
        longer exists -- passed through so this method's own "restored"
        status message doesn't silently overwrite it; the two are
        combined instead."""
        try:
            if saved.get("time_unit") == "h" and self._time_unit != "h":
                self.time_unit_toggle.value = "hours"
            self.filter_verdict.value = [x for x in saved.get("filter_verdict", []) if x in q.VERDICTS]
            self.filter_source.value = [x for x in saved.get("filter_source", []) if x in self.filter_source.options]
            saved_tags = saved.get("filter_tags", {})
            for cat, widget in self.filter_tag_widgets.items():
                widget.value = [x for x in saved_tags.get(cat, []) if x in widget.options]
            self.filter_spike_band.value = [
                x for x in saved.get("filter_spike_band", []) if x in SPIKE_BAND_OPTIONS
            ]
            self.filter_duration_band.value = [
                x for x in saved.get("filter_duration_band", []) if x in DURATION_BAND_OPTIONS
            ]
            self.search_id_input.value = saved.get("search_id", "") or ""
            self.search_text_input.value = saved.get("search_text", "") or ""
            self.show_annotations_toggle.value = bool(saved.get("show_annotations", True))
            self.show_detections_toggle.value = bool(saved.get("show_detections", True))
            self.show_annotation_ribbon_toggle.value = bool(saved.get("show_annotation_ribbon", True))
            self.show_reviewed_ribbon_toggle.value = bool(saved.get("show_reviewed_ribbon", True))
            self.dc_offset_toggle.value = bool(saved.get("dc_offset", False))
            self.detrend_toggle.value = bool(saved.get("detrend", False))
            self.y_autoscale_toggle.value = bool(saved.get("y_autoscale", True))
            x_range = saved.get("x_range")
            if x_range and len(x_range) == 2 and self._range_stream is not None:
                self._rebuild_plot(x_range_override=tuple(x_range))
            restored_msg = "Restored previous session (recording, filters, viewport)."
            self.status.object = f"{stale_notice}\n\n{restored_msg}" if stale_notice else restored_msg
        except Exception:
            pass

    # ── Vocabulary-driven widget options ─────────────────────────────────

    def _refresh_vocabulary_options(self):
        for cat, widget in [("element", self.element_widget),
                             ("quality", self.quality_widget),
                             ("structure", self.structure_widget),
                             ("status", self.status_widget)]:
            values = [r["value"] for r in v.list_terms(self.conn, category=cat)]
            if widget is self.element_widget:
                widget.options = values
            else:
                widget.options = [""] + values
        for cat, widget in self.filter_tag_widgets.items():
            widget.options = [r["value"] for r in v.list_terms(self.conn, category=cat)]
        self.bulk_status_select.options = [""] + [r["value"] for r in v.list_terms(self.conn, category="status")]
        self._refresh_bulk_tag_value_options()

    def _refresh_bulk_tag_value_options(self):
        cat = self.bulk_tag_category_select.value
        self.bulk_tag_value_select.options = [r["value"] for r in v.list_terms(self.conn, category=cat)]

    # ── Recording selection ─────────────────────────────────────────────

    def _refresh_source_file_options(self):
        """Called after a new recording is imported via the "Import
        recording" tab, so it shows up in the Source file dropdown without
        needing an app restart."""
        source_files = sorted({r["source_file"] for r in q.list_recordings(self.conn)})
        self.param.source_file.objects = source_files
        self._refresh_channel_options()

    def _refresh_channel_options(self):
        channels = sorted(r["channel"] for r in q.list_recordings(self.conn, self.source_file))
        self.param.channel.objects = channels
        if self.channel not in channels:
            self.channel = channels[0]

    @param.depends("source_file", watch=True)
    def _on_source_file_change(self):
        had_pending_span = bool(self._pending_bounds and self._pending_bounds[0] is not None)
        self._refresh_channel_options()
        self._load_recording()
        if had_pending_span:
            # Part E9: no unsaved-span data is ever lost (annotations only
            # get written on explicit Save), but the drawn-but-unsaved span
            # itself is gone the moment `_load_recording` clears
            # `_pending_bounds` for the new channel -- a blocking JS confirm
            # dialog would be the tighter guarantee, but a loud post-hoc
            # warning is what fits in the current architecture without
            # adding a new JS round-trip; see this session's summary.
            self.status.object = (
                "**Switched recording — your unsaved pending span was cleared "
                "(nothing was saved to the database).**"
            )
        self._save_session_state()

    @param.depends("channel", watch=True)
    def _on_channel_change(self):
        had_pending_span = bool(self._pending_bounds and self._pending_bounds[0] is not None)
        self._load_recording()
        if had_pending_span:
            self.status.object = (
                "**Switched channel — your unsaved pending span was cleared "
                "(nothing was saved to the database).**"
            )
        self._save_session_state()

    def _load_recording(self):
        rec = q.get_recording(self.conn, self.source_file, self.channel)
        if rec is None:
            self.status.object = (
                f"**No recording row for {self.source_file} channel {self.channel}.**"
            )
            return
        self._recording_id = rec["id"]
        self._fs = rec["fs"]
        self._n_samples = rec["n_samples"]
        self._pending_bounds = None
        self._selected_annotation_ids = set()

        self._rebuild_plot(rec, preserve_zoom=False)
        self._update_time_field_steps()

        self._refresh_table()
        self._refresh_summary()
        self._sync_time_fields_from_bounds()
        self._update_selection_info()

        other_channels = [c for c in sorted(self.param.channel.objects) if c != self.channel]
        self.cross_channel_select.options = ["(none)"] + other_channels
        self.cross_channel_select.value = "(none)"
        self._rebuild_cross_channel_peek()

        # Part 5 A1: a different recording/channel means a different span
        # for the Run tab's "Current viewport"/"Whole channel" modes even
        # if nothing there was touched — keep its preview honest.
        if self.run_panel is not None:
            self.run_panel._on_span_context_changed()

    def _rebuild_cross_channel_peek(self):
        """(Re)build the peek panel's DynamicMap, linked to the MAIN
        plot's own RangeX stream so panning/zooming the main trace moves
        the peek panel too — driven off the SAME stream object, not a
        copy, so there's exactly one source of truth for "the current
        viewport"."""
        if self.cross_channel_select.value in (None, "(none)") or self._range_stream is None:
            self.cross_channel_pane.object = None
            return
        other_rec = q.get_recording(self.conn, self.source_file, self.cross_channel_select.value)
        if other_rec is None:
            self.cross_channel_pane.object = None
            return
        npy_path, fs, time_unit = other_rec["npy_path"], other_rec["fs"], self._time_unit

        def _cb(x_range):
            lo, hi = self._x_range_to_samples(x_range)
            return build_peek_curve(npy_path, fs, (lo, hi), time_unit=time_unit)

        self.cross_channel_pane.object = hv.DynamicMap(_cb, streams=[self._range_stream])

    def _rebuild_plot(self, rec=None, preserve_zoom=True, x_range_override=None):
        """(Re)build the channel curve and every overlay, and assign
        `plot_pane.object` — the one place in this class that does. Called
        once per recording/channel load, once whenever the select-mode
        toggle needs a different `active_tools` baked into the plot (Bokeh
        tool activation is set at plot-construction time, not something a
        later `.event()` can change), and once when the time-unit toggle
        changes what `build_channel_dmap`'s `time_unit` bakes into the
        curve's own coordinates. Every *other* update (filters, show/hide
        toggles, a new selection) goes through `_refresh_view()` instead,
        which never touches `plot_pane.object` at all — see the
        module-level `_RefreshTrigger` docstring for why that split matters.

        `preserve_zoom` carries the *current* x-range into the rebuilt
        `RangeX` stream. Without it, `build_channel_dmap` always seeds a
        fresh stream at the whole-channel extent — fine when switching
        recording/channel (a different signal, any old zoom is meaningless
        anyway; `_load_recording` passes `preserve_zoom=False`), but the
        select-mode toggle rebuilding the plot for an unrelated reason
        (re-arming Bokeh's active-tool set) must not also silently reset
        whatever you'd zoomed into. `x_range_override`, when given, wins
        over both — used by `_on_time_unit_toggle`, which must supply the
        current zoom range already converted into the *new* unit, not the
        stream's raw (old-unit) value `preserve_zoom` would otherwise reuse.
        """
        if rec is None:
            rec = q.get_recording(self.conn, self.source_file, self.channel)
        active_tools = (
            ["xpan", "xwheel_zoom"] if self.drag_mode.value == "Pan"
            else ["xbox_select", "xwheel_zoom"]
        )
        if x_range_override is not None:
            current_x_range = x_range_override
        elif preserve_zoom and self._range_stream is not None:
            current_x_range = self._range_stream.x_range
        else:
            current_x_range = None
        self._dmap, self._range_stream, self._full_extent, self._y_extent = build_channel_dmap(
            rec["npy_path"], self._fs, self._n_samples, active_tools=active_tools,
            initial_x_range=current_x_range, time_unit=self._time_unit,
            y_pan_fraction=self._y_pan_fraction,
            dc_offset=self.dc_offset_toggle.value, detrend=self.detrend_toggle.value,
            y_autoscale=self.y_autoscale_toggle.value,
        )
        self._bounds_stream = hv.streams.BoundsX(source=self._dmap)
        self._bounds_stream.add_subscriber(self._on_bounds_selected)
        self._range_stream.add_subscriber(self._on_range_changed)

        self._refresh_trigger = _RefreshTrigger()
        self._channel_mmap = load_channel_mmap(rec["npy_path"])
        # Every overlay builder computes `start_idx / fs` internally to get
        # seconds — but the curve itself is in `self._time_unit` display
        # units (hours divides everything by another 3600). Passing the
        # *effective* fs (fs * unit_scale) makes `start_idx / effective_fs`
        # land in display units too, matching the curve's own axis. Without
        # this, every rectangle overlay silently sits ~3600x off from the
        # curve whenever hours mode is active (confirmed: a real rendered
        # plot's Quad glyphs at x=12000-2591800 against a curve axis of
        # 0-721 when toggled to hours).
        effective_fs = self._fs * self._unit_scale()
        # Part A (2026-08 restructure): the two ribbons are no longer
        # overlaid on the main curve at all -- they're separate panes
        # (`self.reviewed_ribbon_pane`/`self.annotation_ribbon_pane`,
        # built once in `__init__`) whose `.object` is set below, linked
        # to the main plot by x-range only. Still recompute on every
        # pan/zoom via the same two streams as before.
        self.reviewed_ribbon_dmap = hv.DynamicMap(
            lambda tick, x_range: build_reviewed_ribbon(
                q.list_reviewed_spans(self.conn, self._recording_id) if self.show_reviewed_ribbon_toggle.value else [],
                effective_fs, self._x_range_to_samples(x_range),
            ),
            streams=[self._refresh_trigger, self._range_stream],
        )
        self.annotation_ribbon_dmap = hv.DynamicMap(
            lambda tick, x_range: build_annotation_ribbon(
                self._filtered_annotation_rows() if self.show_annotations_toggle.value else [],
                effective_fs, self._x_range_to_samples(x_range),
                density_threshold=(
                    OVERLAY_DENSITY_THRESHOLD if self.show_annotation_ribbon_toggle.value
                    else float("inf")  # ribbon toggled off -> always render individually
                ),
            ),
            streams=[self._refresh_trigger, self._range_stream],
        )
        self.reviewed_ribbon_pane.object = self.reviewed_ribbon_dmap
        self.annotation_ribbon_pane.object = self.annotation_ribbon_dmap
        detection_dmap = hv.DynamicMap(
            lambda tick: build_detection_overlay(
                R.list_detections_for_recording(self.conn, self._recording_id)
                if self.show_detections_toggle.value else [],
                effective_fs, self._y_extent,
            ),
            streams=[self._refresh_trigger],
        )
        selected_dmap = hv.DynamicMap(
            lambda tick: build_selected_overlay(
                q.get_annotations_by_ids(self.conn, self._selected_annotation_ids),
                effective_fs, self._y_extent,
            ),
            streams=[self._refresh_trigger],
        )
        pending_dmap = hv.DynamicMap(
            lambda tick: build_pending_selection_overlay(self._pending_bounds),
            streams=[self._refresh_trigger],
        )
        # Part A (2026-08): the ribbons are no longer part of this overlay
        # at all (see above) -- only overlays that genuinely belong on the
        # SAME axes as the trace (a specific selected/detected span, drawn
        # ON the signal you're looking at) stay here. `style_main_plot_frame`
        # (not a `hooks=` opt on the curve alone -- see its docstring) is
        # what keeps this frame's borders fixed/matching the ribbon panes'
        # once combined into one multi-DynamicMap Overlay (Part A3).
        self.plot_pane.object = style_main_plot_frame(
            self._dmap * selected_dmap * detection_dmap * pending_dmap
        )
        # `self._range_stream` is a fresh object every time this method
        # runs (drag_mode/time_unit/view-transform toggles all rebuild it,
        # not just a recording/channel change) — the peek panel's
        # DynamicMap was built against whatever the OLD stream was, so it
        # must be rebuilt here too or it silently stops tracking the main
        # plot's viewport.
        if hasattr(self, "cross_channel_select"):  # not yet constructed during __init__'s first call
            self._rebuild_cross_channel_peek()

    # ── Filtering ─────────────────────────────────────────────────────────

    def _on_filters_changed(self):
        self._refresh_view()
        self._refresh_table()
        self._update_filter_match_count()
        self._save_session_state()

    def _on_clear_filters(self, _event=None):
        self.filter_verdict.value = []
        self.filter_source.value = []
        self.filter_spike_band.value = []
        self.filter_duration_band.value = []
        self.search_id_input.value = ""
        self.search_text_input.value = ""
        for w in self.filter_tag_widgets.values():
            w.value = []

    def _update_filter_match_count(self):
        """Part E10: distinguishes an empty result from a broken filter —
        without this, both look identical (an empty table)."""
        if self._recording_id is None:
            self.filter_match_count.object = ""
            return
        total = len(q.list_annotations(self.conn, self._recording_id))
        matched = len(self._filtered_annotation_rows())
        if matched == total:
            self.filter_match_count.object = f"**{total}** annotation(s) (no filters active)"
        else:
            self.filter_match_count.object = f"**{matched}** of {total} annotation(s) match"

    # ── Export (Part E8) ─────────────────────────────────────────────────

    def _export_records(self):
        """The current filtered/searched set (same `_filtered_annotation_rows`
        everything else uses), with tags and derived bands included —
        shared by both the CSV and JSON export callbacks so the two never
        drift out of sync with each other or with what's on screen."""
        rows = self._filtered_annotation_rows()
        tags_by_id = v.get_tags_for_recording(self.conn, self._recording_id) if self._recording_id else {}
        records = []
        for r in rows:
            tags = tags_by_id.get(r["id"], {})
            records.append({
                "id": r["id"], "recording_id": r["recording_id"],
                "source_file": self.source_file, "channel": self.channel,
                "start_idx": r["start_idx"], "end_idx": r["end_idx"],
                "verdict": r["verdict"], "status": r["status"], "event_count": r["event_count"],
                "spike_train_band": b.spike_train_band(r["event_count"]),
                "duration_band": b.duration_band(r["start_idx"], r["end_idx"], self._fs),
                "element": list(tags.get("element", [])),
                "quality": list(tags.get("quality", [])),
                "structure": list(tags.get("structure", [])),
                "source": r["source"], "note": r["note"], "created_at": r["created_at"],
            })
        return records

    def _export_csv_callback(self):
        records = self._export_records()
        for r in records:  # CSV has no list type -- join tag lists into one string
            for k in ("element", "quality", "structure"):
                r[k] = ", ".join(r[k])
        df = pd.DataFrame(records)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return io.BytesIO(buf.getvalue().encode("utf-8"))

    def _export_json_callback(self):
        records = self._export_records()
        return io.BytesIO(json.dumps(records, indent=2, default=str).encode("utf-8"))

    def _filtered_annotation_rows(self):
        """The one canonical filter function — the table (`_refresh_table`),
        the annotation-density ribbon pane (`annotation_ribbon_dmap` in
        `_rebuild_plot`), and the live per-filter match counts
        (`_update_filter_counts`) all call this, not independent copies of
        the same logic, so they can't silently drift apart.

        Semantics: OR *within* each multi-select category, AND *across*
        categories — e.g. verdict IN (a, b) AND source IN (c) AND
        element-tag IN (...). Each `if widget.value and row[...] not in
        widget.value: continue` line below is exactly that OR-within-
        category test (empty selection = no restriction from that
        category, not "match nothing"); chaining several such checks
        with independent `continue`s is what gives AND-across-categories.
        """
        rows = q.list_annotations(self.conn, self._recording_id)

        tag_filters = {cat: w.value for cat, w in self.filter_tag_widgets.items() if w.value}
        matching_ids = v.annotations_matching_tags(self.conn, self._recording_id, tag_filters)
        tags_by_id = v.get_tags_for_recording(self.conn, self._recording_id)

        # D2: search composes with (is ANDed onto) the filters above, not a
        # separate code path -- an id search matches ANY of the listed ids
        # (OR, like every other multi-value control here); a text search
        # matches note OR any tag value, case-insensitively.
        id_query = self.search_id_input.value.strip()
        wanted_ids = set()
        for tok in id_query.replace(",", " ").split():
            try:
                wanted_ids.add(int(tok))
            except ValueError:
                pass
        text_query = self.search_text_input.value.strip().lower()

        out = []
        for r in rows:
            if matching_ids is not None and r["id"] not in matching_ids:
                continue
            if self.filter_verdict.value and r["verdict"] not in self.filter_verdict.value:
                continue
            if self.filter_source.value and r["source"] not in self.filter_source.value:
                continue
            if self.filter_spike_band.value:
                if b.spike_train_band(r["event_count"]) not in self.filter_spike_band.value:
                    continue
            if self.filter_duration_band.value:
                if b.duration_band(r["start_idx"], r["end_idx"], self._fs) not in self.filter_duration_band.value:
                    continue
            if wanted_ids and r["id"] not in wanted_ids:
                continue
            if text_query:
                tags = tags_by_id.get(r["id"], {})
                haystack = " ".join([r["note"] or "", *[v for vals in tags.values() for v in vals]]).lower()
                if text_query not in haystack:
                    continue
            out.append(r)
        return out

    # ── Plot composition ─────────────────────────────────────────────────

    def _refresh_view(self):
        """Re-renders the annotation/reviewed/detection/pending overlays by
        triggering their shared DynamicMap stream — deliberately does NOT
        touch `plot_pane.object` (only `_rebuild_plot` does that). See the
        module-level `_RefreshTrigger` docstring."""
        if self._refresh_trigger is not None:
            self._refresh_trigger.event(tick=self._refresh_trigger.tick + 1)

    def _on_overlay_toggle_changed(self, _event=None):
        self._refresh_view()
        self._save_session_state()

    def _update_ribbon_pane_visibility(self, _event=None):
        """Part A4 (2026-08): a hidden ribbon pane COLLAPSES (no visible
        footprint at all), it doesn't just go blank — `show_annotations`
        is the annotation pane's show/hide (there's nothing else left on
        the main plot to separately toggle now that ribbons live in their
        own panes; see the toggle construction comment), `show_reviewed_
        ribbon` is the reviewed pane's."""
        self.annotation_ribbon_pane.visible = self.show_annotations_toggle.value
        self.reviewed_ribbon_pane.visible = self.show_reviewed_ribbon_toggle.value

    def _refresh_table(self):
        rows = self._filtered_annotation_rows()
        tags_by_id = v.get_tags_for_recording(self.conn, self._recording_id)
        records = []
        for r in rows:
            tags = tags_by_id.get(r["id"], {})
            records.append({
                "pinned": "\U0001F4CC" if r["id"] in self._selected_annotation_ids else "",
                "id": r["id"], "start_idx": r["start_idx"], "end_idx": r["end_idx"],
                "verdict": r["verdict"], "status": r["status"],
                "event_count": r["event_count"],
                "spike_train_band": b.spike_train_band(r["event_count"]),
                "duration_band": b.duration_band(r["start_idx"], r["end_idx"], self._fs),
                "element": ", ".join(tags.get("element", [])),
                "quality": ", ".join(tags.get("quality", [])),
                "structure": ", ".join(tags.get("structure", [])),
                "source": r["source"], "note": r["note"], "created_at": r["created_at"],
            })
        # D1: selected rows pinned to the top, stable sort so the rest of
        # the ordering (whatever it was) is otherwise unchanged.
        records.sort(key=lambda rec: rec["id"] not in self._selected_annotation_ids)
        df = pd.DataFrame(records, columns=TABLE_COLUMNS)
        self.annotations_table.value = df
        # Positional indices from before this rebuild are meaningless
        # against the new DataFrame (a filter change reorders/drops rows) —
        # re-derive `.selection` from the id-based model instead of leaving
        # it stale or silently dropping the selection (Part 1, "selection
        # vs filters").
        self._sync_table_selection_from_ids()
        self._update_annotation_selection_info()
        self._update_filter_match_count()

    def _refresh_summary(self):
        s = q.recording_summary(self.conn, self._recording_id)
        self.summary_pane.object = (
            f"**{self.source_file}  channel {self.channel}**\n\n"
            f"- interesting: **{s['interesting']}**\n"
            f"- not interesting: **{s['not_interesting']}**\n"
            f"- artifact: **{s['artifact']}**\n"
            f"- unsure: **{s['unsure']}**\n"
            f"- total annotations: **{s['total']}**\n"
            f"- reviewed: **{s['reviewed_fraction'] * 100:.1f}%** of channel"
        )

    def _on_drag_mode_changed(self, event):
        """Bokeh only allows one active *drag* tool at a time — box-select
        and pan are mutually exclusive as the drag action, though either
        can coexist with wheel-zoom (a separate tool category). "New span"
        and "Select annotations" both need box-select active; they differ
        only in what `_on_bounds_selected` does with the resulting bounds
        (see that method) — so switching between THOSE two doesn't need a
        plot rebuild at all, only switching to/from "Pan" does, since only
        that changes which Bokeh tool is active. Rebuilding unconditionally
        anyway keeps this simple and matches how the time-unit toggle
        already works; it's a cheap operation (confirmed elsewhere in this
        file: rebuilding is what the select/pan toggle always did).

        Bokeh's active-tool set is baked in at plot-construction time, not
        something a later data update can change, so this is one of only a
        few places that calls `_rebuild_plot` — every other update goes
        through `_refresh_view()` instead, which never rebuilds the plot at
        all. See `_rebuild_plot`'s docstring.
        """
        self.drag_mode_description.object = _DRAG_MODE_DESCRIPTIONS[event.new]
        self.drag_mode_description.styles = dict(
            _DRAG_MODE_STYLE_BASE, background=_DRAG_MODE_COLORS[event.new],
        )
        self._rebuild_plot()

    def _on_reset_full_view(self, _event=None):
        """Part C3: Bokeh's own "Reset" toolbar button restores the
        PREVIOUS view (its pan/zoom history), not the whole channel — easy
        to confuse with "go home" and not what it does. This is an
        explicit, always-whole-channel reset, also clearing any vertical
        pan so "full view" really means the whole signal, y-autoscaled
        (the curve's per-frame local y-range already IS an autoscale to
        whatever's visible, so resetting x to the full extent is
        sufficient — no separate y step needed once the pan offset is
        cleared)."""
        self._y_pan_fraction = 0.0
        self._rebuild_plot(preserve_zoom=False)

    def _on_pan_y(self, fraction_delta):
        """Part C3: vertical pan. Implemented as an app-level control
        (rebuilding the plot with a shifted y_pan_fraction baked into
        `build_channel_dmap`, the same "rebuild for a reason unrelated to
        navigation" pattern `drag_mode`/`time_unit` already use) rather
        than a Bokeh y-pan toolbar tool, whose cross-browser reliability
        for a restricted-to-y-axis drag isn't something I can verify
        without a live browser — this is deterministic and testable."""
        self._y_pan_fraction += fraction_delta
        self._rebuild_plot()

    def _on_pan_y_up(self, _event=None):
        self._on_pan_y(0.3)

    def _on_pan_y_down(self, _event=None):
        self._on_pan_y(-0.3)

    def _on_range_changed(self, x_range=None, **_kwargs):
        """Part E2: live viewport-width display — updates on every pan/
        zoom via the RangeX stream's subscriber list (previously a no-op
        just to keep the stream alive; now doing real work too)."""
        scale = self._unit_scale()
        x0, x1 = (x_range if x_range and x_range[0] is not None else self._full_extent)
        width_s = max(0.0, (x1 - x0) * scale)
        self.viewport_width_display.object = f"**Viewport width:** {_format_duration_human(width_s)}"

    def _on_view_transform_changed(self, _event=None):
        """Part E3: any view-transform toggle rebuilds the plot (transforms
        are baked into `build_channel_dmap` at construction time, same
        pattern as `y_pan_fraction`/`drag_mode`) and refreshes the banner
        that makes an active transform impossible to miss."""
        active = []
        if self.detrend_toggle.value:
            active.append("DETRENDED")
        elif self.dc_offset_toggle.value:  # detrend already subsumes DC-offset removal
            active.append("DC OFFSET REMOVED")
        if not self.y_autoscale_toggle.value:
            active.append("Y-AXIS FIXED (not autoscaled)")
        if active:
            self.view_transform_banner.object = (
                f"**⚠ DISPLAY TRANSFORM ACTIVE — {' + '.join(active)} — "
                "this is NOT raw data, and nothing here is saved.**"
            )
            self.view_transform_banner.styles = {
                "display": "block", "background": "#fff3cd", "border": "2px solid #f0ad4e",
                "padding": "8px", "border-radius": "4px",
            }
        else:
            self.view_transform_banner.object = ""
            self.view_transform_banner.styles = {"display": "none"}
        self._rebuild_plot()
        self._save_session_state()

    # ── Zoom presets (Part E2) ──────────────────────────────────────────

    def _on_zoom_preset(self, width_seconds):
        if self._range_stream is None or self._fs is None:
            return
        scale = self._unit_scale()
        x0, x1 = self._range_stream.x_range or self._full_extent
        center_s = (x0 + x1) / 2.0 * scale
        full_lo_s, full_hi_s = self._full_extent[0] * scale, self._full_extent[1] * scale
        half = min(width_seconds, full_hi_s - full_lo_s) / 2.0
        lo_s, hi_s = center_s - half, center_s + half
        if lo_s < full_lo_s:
            hi_s += full_lo_s - lo_s
            lo_s = full_lo_s
        if hi_s > full_hi_s:
            lo_s -= hi_s - full_hi_s
            hi_s = full_hi_s
        lo_s, hi_s = max(full_lo_s, lo_s), min(full_hi_s, hi_s)
        self._range_stream.event(x_range=(lo_s / scale, hi_s / scale))
        self._save_session_state()

    def _on_zoom_preset_full(self, _event=None):
        if self._range_stream is None:
            return
        self._range_stream.event(x_range=self._full_extent)
        self._save_session_state()

    # ── Annotation navigator (Part E1) ──────────────────────────────────

    def _navigator_rows(self):
        """Filtered + searched set, in the same start_idx order
        `list_annotations` (and therefore `_filtered_annotation_rows`,
        which only filters, never resorts) already returns — stepping
        through this is stepping through exactly what's currently
        visible in the table/plot, per the brief."""
        return self._filtered_annotation_rows()

    def _navigate_to(self, row):
        self._nav_current_id = row["id"]
        padding_fraction = self.nav_padding_fraction_input.value or 0.0
        self._zoom_to_ids([row["id"]], padding_fraction=padding_fraction)
        self._selected_annotation_ids = {row["id"]}
        # E1/E2 bug fix: `_refresh_table` (not just `_sync_table_selection_
        # from_ids`) is what rebuilds the pin markers and re-applies the
        # pin-sort -- calling only the sync half left the table showing a
        # stale pin column and the newly-selected row wherever it happened
        # to already be, not pinned to page 1.
        self._refresh_table()
        self._refresh_view()
        self.status.object = f"Navigated to annotation {row['id']} ({row['verdict']})."
        self._save_session_state()

    def _on_nav_next(self, _event=None):
        rows = self._navigator_rows()
        if not rows:
            self.status.object = "**No annotations match the current filters/search.**"
            return
        ids = [r["id"] for r in rows]
        if self._nav_current_id in ids:
            target = rows[(ids.index(self._nav_current_id) + 1) % len(rows)]
        else:
            target = rows[0]
        self._navigate_to(target)

    def _on_nav_prev(self, _event=None):
        rows = self._navigator_rows()
        if not rows:
            self.status.object = "**No annotations match the current filters/search.**"
            return
        ids = [r["id"] for r in rows]
        if self._nav_current_id in ids:
            target = rows[(ids.index(self._nav_current_id) - 1) % len(rows)]
        else:
            target = rows[-1]
        self._navigate_to(target)

    def _unit_scale(self):
        """Seconds per current display-unit — 3600 in hours view, 1 in
        seconds view. Everything Bokeh-facing (`_range_stream.x_range`,
        `_pending_bounds`, the Start/End Time fields) lives in the CURRENT
        display unit so it always matches the plot's own axis coordinates
        without conversion; anything that needs seconds for a sample-index
        computation (`_save_annotation`, `_mark_viewport_reviewed`) must
        multiply by this explicitly."""
        return 3600.0 if self._time_unit == "h" else 1.0

    def _x_range_to_samples(self, x_range):
        """Convert a display-unit (x0, x1) — as reported live by the
        `RangeX` stream — into the sample bounds [i0, i1) the CURRENT
        curve frame is actually plotted from. The domain the two
        viewport-reactive ribbons (Part B) bucket over, and (Part A,
        2026-08 fix) the exact same `x_range_to_sample_bounds` the curve
        itself uses (`UI/plots.py`'s `build_channel_dmap`) — an
        independently-rounded approximation here used to drift from what
        was really on screen as the zoom narrowed."""
        if x_range is None or x_range[0] is None or x_range[1] is None:
            x0, x1 = self._full_extent
        else:
            x0, x1 = x_range
        return x_range_to_sample_bounds(
            x0, x1, self._full_extent, self._fs, self._unit_scale(), self._n_samples,
        )

    # `_local_y_range_for_x_range` (the ribbons' "pin to the curve's
    # visible y-range" computation) was RETIRED in Part A (2026-08): the
    # ribbons moved into their own dedicated panes with a fixed (0, 1)
    # y-range that has nothing to do with the curve's axis, so nothing
    # needs to track it anymore. `compute_display_y_range` itself is
    # still shared/used -- by the curve alone now, for its own axis.

    def _on_time_unit_toggle(self, event):
        """Bokeh's x-axis coordinates ARE the curve's own data values (see
        `build_channel_dmap`'s `time_unit` param) — there's no way to
        relabel an axis without also rescaling everything drawn on it, so
        this rebuilds the plot like the select-mode toggle does. Unlike
        that toggle, the current zoom range and any pending selection are
        expressed in the OLD unit and must be explicitly rescaled into the
        new one, or a selection at "3600s" would silently reappear as
        "3600h" after switching to hours.
        """
        old_scale = self._unit_scale()
        self._time_unit = "h" if event.new == "hours" else "s"
        new_scale = self._unit_scale()
        rescale = old_scale / new_scale

        x_range_override = None
        if self._range_stream is not None and self._range_stream.x_range is not None:
            x0, x1 = self._range_stream.x_range
            x_range_override = (x0 * rescale, x1 * rescale)

        if self._pending_bounds and self._pending_bounds[0] is not None:
            px0, px1 = self._pending_bounds
            self._pending_bounds = (px0 * rescale, px1 * rescale)

        self.start_time_input.name = f"Start Time ({self._time_unit})"
        self.end_time_input.name = f"End Time ({self._time_unit})"
        self._update_time_field_steps()

        self._rebuild_plot(x_range_override=x_range_override)
        self._sync_time_fields_from_bounds()
        self._update_selection_info()
        self._update_similarity_warning()
        self._save_session_state()

    def _update_time_field_steps(self):
        """Start/End Time steppers must move by exactly one sample period —
        the smallest meaningful increment for this recording — in whatever
        the current display unit is. Called whenever `_fs` or `_time_unit`
        changes (`_load_recording`, `_on_time_unit_toggle`)."""
        if self._fs:
            step = 1.0 / self._fs / self._unit_scale()
            self.start_time_input.step = step
            self.end_time_input.step = step

    def _set_pending_bounds(self, x0, x1):
        """The one place `_pending_bounds` is ever assigned a non-None
        value — snaps both ends to the nearest exact sample boundary first,
        so no sub-sample time can reach the database (Part 2a) regardless
        of whether it came from a drag, a stepper click, or a typed value.
        A drag in particular arrives at whatever sub-pixel resolution Bokeh
        reports, never naturally sample-aligned.
        """
        scale = self._unit_scale()
        start_idx = int(round(x0 * scale * self._fs))
        end_idx = int(round(x1 * scale * self._fs))
        if end_idx <= start_idx:
            self._pending_bounds = None
        else:
            self._pending_bounds = (start_idx / self._fs / scale, end_idx / self._fs / scale)
        self._sync_time_fields_from_bounds()
        self._update_selection_info()
        self._update_similarity_warning()
        self._refresh_view()

    def _sync_time_fields_from_bounds(self):
        """Keep the Start/End Time fields (plus the sample-index and live
        width readouts) mirroring `_pending_bounds`, without re-triggering
        `_on_time_field_changed` — that watcher fires on programmatic
        `.value` assignment exactly like a user edit, and without this
        guard every drag-select would loop straight back into treating its
        own result as a fresh manual edit."""
        decimals = 6 if self._time_unit == "h" else 3  # hours need finer precision to resolve seconds
        self._updating_time_fields = True
        try:
            if self._pending_bounds and self._pending_bounds[0] is not None:
                x0, x1 = self._pending_bounds
                self.start_time_input.value = round(x0, decimals)
                self.end_time_input.value = round(x1, decimals)
                scale = self._unit_scale()
                start_idx = int(round(x0 * scale * self._fs))
                end_idx = int(round(x1 * scale * self._fs))
                self.start_sample_info.object = f"sample {start_idx:,}"
                self.end_sample_info.object = f"sample {end_idx:,}"
                self.pending_width_info.object = (
                    f"**Width:** {_format_duration_human((end_idx - start_idx) / self._fs)} "
                    f"({end_idx - start_idx:,} samples)"
                )
            else:
                self.start_time_input.value = None
                self.end_time_input.value = None
                self.start_sample_info.object = ""
                self.end_sample_info.object = ""
                self.pending_width_info.object = ""
        finally:
            self._updating_time_fields = False

    def _update_selection_info(self):
        u = self._time_unit
        if self._pending_bounds and self._pending_bounds[0] is not None:
            x0, x1 = self._pending_bounds
            fmt = "{:.4f}" if u == "h" else "{:.1f}"
            self.selection_info.object = (
                f"**Span selected:** {fmt.format(x0)}{u} - {fmt.format(x1)}{u}"
                f"  (duration {fmt.format(x1 - x0)}{u})"
            )
        else:
            self.selection_info.object = (
                "*No span selected — drag on the plot, or enter times below.*"
            )

    def _update_similarity_warning(self):
        """Part 2c: warn (never block) when the pending span substantially
        overlaps an existing annotation on this channel. Recomputed on
        every `_set_pending_bounds` call, so it always reflects the
        current pending span."""
        self._similar_annotation_id = None
        if (not self._pending_bounds or self._pending_bounds[0] is None
                or self._recording_id is None):
            self.similarity_warning.object = ""
            self.compare_similar_button.visible = False
            return
        scale = self._unit_scale()
        x0, x1 = self._pending_bounds
        start_idx = int(round(x0 * scale * self._fs))
        end_idx = int(round(x1 * scale * self._fs))
        matches = find_similar_annotations(self.conn, self._recording_id, start_idx, end_idx)
        if matches:
            best = matches[0]
            self._similar_annotation_id = best["id"]
            self.similarity_warning.object = (
                f"⚠️ **A similar annotation already exists** "
                f"(id={best['id']}, verdict={best['verdict']}, IoU={best['iou']:.2f}) "
                f"— are you sure?"
            )
            self.compare_similar_button.visible = True
        else:
            self.similarity_warning.object = ""
            self.compare_similar_button.visible = False

    def _on_compare_similar(self, _event=None):
        if self._similar_annotation_id is None:
            return
        self._selected_annotation_ids.add(self._similar_annotation_id)
        self._refresh_table()  # E1/E2: rebuilds pin markers + pin-sort, not just checkbox state
        self._zoom_to_ids([self._similar_annotation_id])
        self._refresh_view()

    def _on_bounds_selected(self, boundsx):
        """Routes a box-select drag by `drag_mode` — the SAME `BoundsX`
        stream (already proven reliable for span-creation) drives both
        "New span" and "Select annotations"; only the interpretation of
        the resulting (x0, x1) differs. "Pan" mode doesn't have box-select
        as the active Bokeh tool at all, so this shouldn't fire then; the
        mode check is defensive, not load-bearing.
        """
        if boundsx is None or boundsx[0] is None:
            return
        x0, x1 = boundsx
        if x1 <= x0:
            return
        mode = self.drag_mode.value
        if mode == "New span":
            self._set_pending_bounds(x0, x1)
        elif mode == "Select annotations":
            self._toggle_annotations_in_range(x0, x1)

    def _toggle_annotations_in_range(self, x0, x1):
        """Every currently-drawn (i.e. filter-passing) annotation whose
        span intersects the dragged range is TOGGLED — selected if it
        wasn't, deselected if it was — rather than the drag *replacing*
        the selection outright.

        This is additive/toggling instead of "shift-click to extend"
        because `hv.streams.BoundsX` doesn't expose which keyboard
        modifier (if any) was held during the drag — there is no reliable
        way from this stream alone to distinguish "replace" from "extend"
        gestures. Toggling means a single plain drag still does the
        obvious thing (select what's inside), repeated drags accumulate a
        multi-region selection without needing a modifier key at all, and
        "Clear annotation selection" is always available as an explicit
        reset. See this turn's summary for why box-select was used here
        instead of a Tap+modifier mechanism.
        """
        scale = self._unit_scale()
        start_idx = int(round(x0 * scale * self._fs))
        end_idx = int(round(x1 * scale * self._fs))
        for row in self._filtered_annotation_rows():
            if row["start_idx"] < end_idx and row["end_idx"] > start_idx:
                if row["id"] in self._selected_annotation_ids:
                    self._selected_annotation_ids.discard(row["id"])
                else:
                    self._selected_annotation_ids.add(row["id"])
        # E1/E2 bug fix: a plot-drag selection used to only push checkbox
        # state onto the table's EXISTING (possibly stale) dataframe --
        # the pin markers and pin-to-top sort weren't recomputed, so a
        # newly-selected row could show "N selected" in the info panel
        # above without a pin icon anywhere visible, and without landing
        # on page 1. `_refresh_table` rebuilds the dataframe (pin column +
        # sort) from the CURRENT `_selected_annotation_ids` first, then
        # re-derives checkbox positions against that new dataframe --
        # doing both, in that order, is exactly what was missing.
        self._refresh_table()
        self._refresh_view()

    def _on_time_field_changed(self, _event=None):
        if self._updating_time_fields:
            return
        x0, x1 = self.start_time_input.value, self.end_time_input.value
        if x0 is None or x1 is None or x1 <= x0:
            return  # incomplete edit (e.g. only one field filled in so far) — wait
        self._set_pending_bounds(x0, x1)

    def _on_clear_selection(self, _event=None):
        self._pending_bounds = None
        self._sync_time_fields_from_bounds()
        self._update_selection_info()
        self._update_similarity_warning()
        self._refresh_view()

    # ── Existing-annotation selection (table <-> plot, shared model) ──────

    def _sync_table_selection_from_ids(self):
        """Push `_selected_annotation_ids` onto the Tabulator's
        `.selection` (positional indices into the CURRENTLY VISIBLE/
        filtered DataFrame) — guarded against re-entering
        `_on_table_selection_changed`, which fires on this exact
        assignment. Ids that are filtered out of the current table simply
        have no position to set; they stay selected in the model, just not
        reflected in the checkbox column (see `_update_annotation_selection_info`'s
        "hidden by filters" count)."""
        self._updating_annotation_selection = True
        try:
            df = self.annotations_table.value
            if len(df):
                positions = [i for i, rid in enumerate(df["id"].tolist())
                             if rid in self._selected_annotation_ids]
            else:
                positions = []
            self.annotations_table.selection = positions
        finally:
            self._updating_annotation_selection = False

    def _on_table_selection_changed(self, event):
        """Table -> model: reconcile the model with whatever's now checked,
        but only for rows currently VISIBLE — any id selected while
        filtered out is left untouched, since it has no row here to
        reflect a check/uncheck of."""
        if self._updating_annotation_selection:
            return
        df = self.annotations_table.value
        if not len(df):
            return
        visible_ids = set(int(x) for x in df["id"].tolist())
        checked_ids = {int(df.iloc[i]["id"]) for i in event.new}
        self._selected_annotation_ids = (self._selected_annotation_ids - visible_ids) | checked_ids
        self._update_annotation_selection_info()
        self._refresh_view()

    def _on_table_cell_edited(self, event):
        """D3: inline edit from the table. Imported annotations
        (source != manual_ui) require the explicit
        `allow_edit_imported_checkbox` override — checked HERE, at the
        write path, not just left to whatever the table UI happens to
        allow, so it can't be bypassed by a stray click."""
        df = self.annotations_table.value
        aid = int(df.iloc[event.row]["id"])
        row = q.get_annotation(self.conn, aid)
        if row is None:
            return
        is_imported = row["source"] != q.SOURCE_MANUAL_UI
        if is_imported and not self.allow_edit_imported_checkbox.value:
            self.annotations_table.patch({event.column: [(event.row, event.old)]})
            self.status.object = (
                f"**Edit refused:** annotation {aid} is imported (source={row['source']!r}). "
                "Check 'Allow editing imported annotations' to override."
            )
            return

        value = event.value
        if event.column == "event_count":
            if value in (None, ""):
                value = None
            else:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    self.annotations_table.patch({event.column: [(event.row, event.old)]})
                    self.status.object = f"**event_count must be a whole number, got {value!r}.**"
                    return

        try:
            q.update_annotation(self.conn, aid, force=is_imported, **{event.column: value})
        except (ValueError, PermissionError) as e:
            self.annotations_table.patch({event.column: [(event.row, event.old)]})
            self.status.object = f"**Edit failed:** {e}"
            return

        self.status.object = f"Updated annotation {aid}.{event.column}."
        # Re-fetch rather than trust the raw edited value in place — e.g.
        # editing event_count must also update the displayed
        # spike_train_band, which _refresh_table recomputes from the DB.
        self._refresh_table()
        self._refresh_view()
        self._refresh_summary()

    def _update_annotation_selection_info(self):
        # E3: spelled out as "...pinned to top" (not just a bare count) --
        # this text sits right next to the table (Part B4), so it's the
        # one place that tells you WHERE to look for what you just
        # selected, not just how many.
        df = self.annotations_table.value
        visible_ids = set(int(x) for x in df["id"].tolist()) if len(df) else set()
        total = len(self._selected_annotation_ids)
        hidden = len(self._selected_annotation_ids - visible_ids)
        if total == 0:
            self.annotation_selection_info.object = "*No annotations selected.*"
        elif hidden:
            self.annotation_selection_info.object = (
                f"**{total} selected, pinned to top** ({hidden} hidden by filters)"
            )
        else:
            self.annotation_selection_info.object = f"**{total} selected, pinned to top**"

    def _on_clear_annotation_selection(self, _event=None):
        self._selected_annotation_ids = set()
        self._refresh_table()  # E1/E2: also clears stale pin markers, not just checkboxes
        self._refresh_view()

    def _zoom_to_ids(self, ids, padding_fraction=0.1):
        rows = q.get_annotations_by_ids(self.conn, ids)
        if not rows or self._range_stream is None:
            return
        lo = min(r["start_idx"] for r in rows)
        hi = max(r["end_idx"] for r in rows)
        pad = (hi - lo) * padding_fraction or self._fs
        scale = self._unit_scale()
        x0 = max(0, lo - pad) / self._fs / scale
        x1 = min(self._n_samples, hi + pad) / self._fs / scale
        self._range_stream.event(x_range=(x0, x1))

    def _on_zoom_to_selected(self, _event=None):
        if not self._selected_annotation_ids:
            self.status.object = "**No annotations selected.**"
            return
        self._zoom_to_ids(self._selected_annotation_ids)

    def _on_find_near_duplicates(self, _event=None):
        if self._recording_id is None:
            return
        pairs = find_near_duplicate_pairs(self.conn, self._recording_id)
        if not pairs:
            self.near_duplicates_report.object = "*No near-duplicates found on this channel.*"
            return
        lines = [f"**{len(pairs)} near-duplicate pair(s) found** (report only — nothing deleted):", ""]
        for p in pairs[:200]:  # cap the rendered list; the data itself isn't truncated elsewhere
            a, b_, iou = p["a"], p["b"], p["iou"]
            lines.append(
                f"- id={a['id']} [{a['start_idx']}-{a['end_idx']}] <-> "
                f"id={b_['id']} [{b_['start_idx']}-{b_['end_idx']}]  IoU={iou:.2f}"
            )
        if len(pairs) > 200:
            lines.append(f"- ... and {len(pairs) - 200} more")
        self.near_duplicates_report.object = "\n".join(lines)

    # ── Actions ──────────────────────────────────────────────────────────

    def _save_annotation(self, _event=None):
        """Returns the new annotation's id on success, None on any
        validation failure (nothing written) — callers that need to chain
        an action onto a successful save (`_on_save_and_run`) check this
        return value rather than re-deriving success from UI state."""
        self.status.object = ""
        if not self._pending_bounds or self._pending_bounds[0] is None:
            self.status.object = "**Drag-select a span on the plot first.**"
            return None
        x0, x1 = self._pending_bounds
        if x1 <= x0:
            self.status.object = "**Selection is empty.**"
            return None

        event_count_text = self.event_count_widget.value.strip()
        event_count = None
        if event_count_text:
            try:
                event_count = int(event_count_text)
            except ValueError:
                self.status.object = f"**event_count must be a whole number, got {event_count_text!r}.**"
                return None

        scale = self._unit_scale()
        x0_s, x1_s = x0 * scale, x1 * scale
        start_idx = max(0, int(round(x0_s * self._fs)))
        end_idx = min(self._n_samples, int(round(x1_s * self._fs)))
        range_x = self._range_stream.x_range or self._full_extent
        scale_viewed = format_scale_viewed(
            (range_x[0] * scale, range_x[1] * scale),
            (self._full_extent[0] * scale, self._full_extent[1] * scale),
        )
        aid = q.insert_annotation(
            self.conn, self._recording_id, start_idx, end_idx, self.verdict,
            source=q.SOURCE_MANUAL_UI, note=self.note or None,
            scale_viewed=scale_viewed, event_count=event_count,
            status=self.status_widget.value or None,
        )
        if self.element_widget.value:
            v.set_annotation_tags(self.conn, aid, "element", self.element_widget.value)
        if self.quality_widget.value:
            v.set_annotation_tags(self.conn, aid, "quality", self.quality_widget.value)
        if self.structure_widget.value:
            v.set_annotation_tags(self.conn, aid, "structure", self.structure_widget.value)

        self._pending_bounds = None
        self._sync_time_fields_from_bounds()
        self._update_similarity_warning()
        self.note = ""
        self.element_widget.value = []
        self.quality_widget.value = ""
        self.structure_widget.value = ""
        self.status_widget.value = ""
        self.event_count_widget.value = ""
        self._refresh_view()
        self._refresh_table()
        self._refresh_summary()
        self.selection_info.object = "*Saved.* " + (
            "*No span selected — drag on the plot, or enter times below.*"
        )
        return aid

    # ── Cross-tab staging basket (Part 3) ───────────────────────────────
    #
    # Deliberately in-memory only (a plain Python list on this instance),
    # not a DB table — "persists across tab switches within a session" per
    # the brief, not across app restarts or between users, and RunPanel
    # already holds a reference to this same `app` instance, so no new
    # plumbing is needed for it to read `self._staged_spans` directly.

    def _refresh_staged_badge(self):
        n = len(self._staged_spans)
        self.staged_spans_badge.object = f"**Staged: {n}**"

    def _stage_span(self, start_idx, end_idx, annotation_id=None):
        self._staged_spans.append({
            "recording_id": self._recording_id, "source_file": self.source_file,
            "channel": self.channel, "start_idx": int(start_idx), "end_idx": int(end_idx),
            "annotation_id": annotation_id,
        })
        self._refresh_staged_badge()
        if self.run_panel is not None:
            self.run_panel.refresh_staged_list()

    def _switch_to_run_tab(self):
        if self.tabs is not None:
            self.tabs.active = 1  # "Run algorithm" — see layout()

    def _on_tab_changed(self, event):
        if event.new == 1 and self.run_panel is not None:  # "Run algorithm"
            self.run_panel._on_span_context_changed()
        if event.new == 3 and self.motif_browser is not None:  # "Motif browser"
            self.motif_browser.on_tab_activated()

    def _on_save_and_run(self, _event=None):
        aid = self._save_annotation()
        if aid is None:
            return  # _save_annotation already set self.status with the reason
        row = q.get_annotation(self.conn, aid)
        self._stage_span(row["start_idx"], row["end_idx"], annotation_id=aid)
        self._switch_to_run_tab()

    def _on_stage_pending(self, _event=None):
        """Stage the pending span WITHOUT saving it as an annotation —
        for testing a region before deciding it's worth labelling."""
        if not self._pending_bounds or self._pending_bounds[0] is None:
            self.status.object = "**Drag-select a span on the plot first.**"
            return
        x0, x1 = self._pending_bounds
        scale = self._unit_scale()
        start_idx = max(0, int(round(x0 * scale * self._fs)))
        end_idx = min(self._n_samples, int(round(x1 * scale * self._fs)))
        self._stage_span(start_idx, end_idx, annotation_id=None)
        self._switch_to_run_tab()

    def _on_run_selected(self, _event=None):
        if not self._selected_annotation_ids:
            self.status.object = "**No annotations selected.**"
            return
        for row in q.get_annotations_by_ids(self.conn, self._selected_annotation_ids):
            self._stage_span(row["start_idx"], row["end_idx"], annotation_id=row["id"])
        self._switch_to_run_tab()

    # ── Bulk operations (Part E6) ────────────────────────────────────────

    def _stage_bulk_action(self, kind, value):
        """Computes and displays the confirmation preview; changes
        nothing in the database until `_on_bulk_confirm` runs."""
        if not self._selected_annotation_ids:
            self.status.object = "**No annotations selected.**"
            return
        rows = q.get_annotations_by_ids(self.conn, self._selected_annotation_ids)
        imported_count = sum(1 for r in rows if r["source"] != q.SOURCE_MANUAL_UI)
        self._pending_bulk_action = (kind, value)
        n = len(rows)
        msg = f"**Confirm bulk {kind}:** {value!r} on **{n}** selected annotation(s)."
        if imported_count:
            if self.allow_edit_imported_checkbox.value:
                msg += f" Includes **{imported_count} imported** (override enabled)."
            else:
                msg += (f" **{imported_count} imported annotation(s) will be SKIPPED** "
                        "(check 'Allow editing imported annotations' above to include them).")
        self.bulk_confirmation.object = msg
        self.bulk_confirm_button.disabled = False
        self.bulk_cancel_button.disabled = False

    def _on_bulk_apply_verdict(self, _event=None):
        if self.bulk_verdict_select.value:
            self._stage_bulk_action("verdict", self.bulk_verdict_select.value)

    def _on_bulk_apply_status(self, _event=None):
        if self.bulk_status_select.value:
            self._stage_bulk_action("status", self.bulk_status_select.value)

    def _on_bulk_apply_tag(self, _event=None):
        if self.bulk_tag_value_select.value:
            self._stage_bulk_action("tag", (
                self.bulk_tag_action_select.value,
                self.bulk_tag_category_select.value,
                self.bulk_tag_value_select.value,
            ))

    def _on_bulk_cancel(self, _event=None):
        self._pending_bulk_action = None
        self.bulk_confirmation.object = ""
        self.bulk_confirm_button.disabled = True
        self.bulk_cancel_button.disabled = True

    def _on_bulk_confirm(self, _event=None):
        if self._pending_bulk_action is None:
            return
        kind, value = self._pending_bulk_action
        rows = q.get_annotations_by_ids(self.conn, self._selected_annotation_ids)
        applied, skipped = 0, 0
        for r in rows:
            is_imported = r["source"] != q.SOURCE_MANUAL_UI
            if is_imported and not self.allow_edit_imported_checkbox.value:
                skipped += 1
                continue
            if kind == "verdict":
                q.update_annotation(self.conn, r["id"], force=is_imported, verdict=value)
            elif kind == "status":
                q.update_annotation(self.conn, r["id"], force=is_imported, status=value)
            elif kind == "tag":
                action, category, tag_value = value
                current = v.get_annotation_tags(self.conn, r["id"]).get(category, [])
                if action == "Add":
                    if tag_value not in current:
                        v.add_annotation_tag(self.conn, r["id"], category, tag_value)
                else:  # "Remove"
                    if tag_value in current:
                        v.set_annotation_tags(self.conn, r["id"], category,
                                               [t for t in current if t != tag_value])
            applied += 1
        self._pending_bulk_action = None
        self.bulk_confirmation.object = ""
        self.bulk_confirm_button.disabled = True
        self.bulk_cancel_button.disabled = True
        self.status.object = f"Bulk {kind} applied to {applied} annotation(s); {skipped} skipped (imported, no override)."
        self._refresh_table()
        self._refresh_view()
        self._refresh_summary()

    def _mark_viewport_reviewed(self, _event=None):
        x0, x1 = self._range_stream.x_range or self._full_extent
        scale = self._unit_scale()
        x0_s, x1_s = x0 * scale, x1 * scale
        start_idx = max(0, int(round(x0_s * self._fs)))
        end_idx = min(self._n_samples, int(round(x1_s * self._fs)))
        scale_viewed = format_scale_viewed(
            (x0_s, x1_s), (self._full_extent[0] * scale, self._full_extent[1] * scale),
        )
        if not q.reviewed_span_exists(self.conn, self._recording_id, start_idx, end_idx,
                                       q.SOURCE_MANUAL_UI):
            q.insert_reviewed_span(
                self.conn, self._recording_id, start_idx, end_idx,
                source=q.SOURCE_MANUAL_UI, scale_viewed=scale_viewed,
            )
        self._refresh_view()
        self._refresh_summary()
        u = self._time_unit
        fmt = "{:.4f}" if u == "h" else "{:.0f}"
        self.status.object = f"Marked {fmt.format(x0)}{u}-{fmt.format(x1)}{u} as reviewed."

    def _delete_selected(self, _event=None):
        """Part E7: `q.delete_annotation` soft-deletes (sets `deleted_at`,
        excluded from `list_annotations` and everything built on it) — the
        row isn't gone, so this tracks what was just deleted for
        `_on_undo_delete` to restore."""
        self.status.object = ""
        df = self.annotations_table.value
        selected = self.annotations_table.selection
        if not selected:
            self.status.object = "**No rows selected in the table.**"
            return
        skipped = 0
        deleted_ids = []
        for i in selected:
            row_id = int(df.iloc[i]["id"])
            try:
                q.delete_annotation(self.conn, row_id)
                deleted_ids.append(row_id)
            except PermissionError:
                skipped += 1
        self._last_deleted_ids = deleted_ids
        self.undo_delete_button.disabled = not deleted_ids
        self._refresh_view()
        self._refresh_table()
        self._refresh_summary()
        msg = f"Deleted {len(deleted_ids)} annotation(s)."
        if skipped:
            msg += f" Skipped {skipped} imported annotation(s) (protected)."
        self.status.object = msg

    def _on_undo_delete(self, _event=None):
        if not self._last_deleted_ids:
            return
        for aid in self._last_deleted_ids:
            q.undelete_annotation(self.conn, aid)
        n = len(self._last_deleted_ids)
        self._last_deleted_ids = []
        self.undo_delete_button.disabled = True
        self._refresh_view()
        self._refresh_table()
        self._refresh_summary()
        self.status.object = f"Restored {n} annotation(s)."

    # ── Layout ───────────────────────────────────────────────────────────

    def layout(self):
        save_btn = pn.widgets.Button(name="Save annotation", button_type="primary")
        save_btn.on_click(self._save_annotation)
        save_and_run_btn = pn.widgets.Button(
            name="Save annotation and run algorithms", button_type="success",
        )
        save_and_run_btn.on_click(self._on_save_and_run)
        stage_pending_btn = pn.widgets.Button(
            name="Stage span (without saving)", button_type="default",
        )
        stage_pending_btn.on_click(self._on_stage_pending)
        review_btn = pn.widgets.Button(name="Mark current viewport reviewed", button_type="default")
        review_btn.on_click(self._mark_viewport_reviewed)
        delete_btn = pn.widgets.Button(name="Delete selected (manual only)", button_type="danger")
        delete_btn.on_click(self._delete_selected)
        self.undo_delete_button = pn.widgets.Button(
            name="Undo last delete", button_type="warning", disabled=True,
        )
        self.undo_delete_button.on_click(self._on_undo_delete)

        reset_view_btn = pn.widgets.Button(
            name="Reset to full view", button_type="default",
            description="Bokeh's own Reset button restores the previous view, not the whole "
                        "channel — this always goes to the full signal, y-autoscaled.",
        )
        reset_view_btn.on_click(self._on_reset_full_view)
        pan_y_up_btn = pn.widgets.Button(name="Pan Y ↑", button_type="default", width=80)
        pan_y_up_btn.on_click(self._on_pan_y_up)
        pan_y_down_btn = pn.widgets.Button(name="Pan Y ↓", button_type="default", width=80)
        pan_y_down_btn.on_click(self._on_pan_y_down)

        # Part B (2026-08 layout restructure): "Keyboard shortcuts" and
        # "Summary" both collapse into accordions instead of sitting as
        # always-on blocks — shortcuts because it's dense reference
        # material you check occasionally, not on every glance; Summary
        # is the opposite (checked constantly) so it starts EXPANDED, but
        # still collapsible, and moves up to directly under "Recording"
        # instead of being stranded at the bottom of a long column. Each
        # accordion's open/closed state is named (`self.xxx_accordion`,
        # not a local variable) so `_save_session_state`/
        # `_restore_session_state` can persist it (Part B6).
        self.shortcuts_accordion = pn.Accordion(
            ("Keyboard shortcuts", self.shortcut_reference),
            active=self._initial_accordion_active.get("shortcuts", []),
        )
        self.summary_accordion = pn.Accordion(
            ("Summary", self.summary_pane),
            active=self._initial_accordion_active.get("summary", [0]),
        )
        for _name, _acc in [("shortcuts", self.shortcuts_accordion),
                             ("summary", self.summary_accordion)]:
            _acc.param.watch(lambda _e: self._save_session_state(), "active")

        controls = pn.Column(
            *self._shortcut_buttons, self._escape_key_listener,  # zero-size; see __init__
            self.shortcuts_accordion,
            pn.pane.Markdown("### Recording", styles=SECTION_HEADER_STYLE),
            pn.Param(self.param.source_file, widgets={"source_file": pn.widgets.Select}),
            pn.Param(self.param.channel, widgets={"channel": pn.widgets.Select}),
            self.time_unit_toggle,
            pn.Row(reset_view_btn, pan_y_up_btn, pan_y_down_btn),
            self.viewport_width_display,
            # D3 bug fix: 6 fixed-width buttons (350px + 90px) do not fit
            # an equally fixed 340px-wide sidebar. `pn.Row` does not wrap
            # its children, so the last two (24 h, Full channel) simply
            # rendered PAST the column's right edge, overlapping whatever
            # `viewer_main` had at that same height (this was also the
            # root cause behind D1/D2's "stray text"/overlap reports --
            # not two independent bugs, one overflowing sidebar). A
            # `pn.FlexBox` wraps onto a second line instead of overflowing.
            pn.FlexBox(*self.zoom_preset_buttons.values(), self.zoom_preset_full_button),
            pn.layout.Divider(),
            self.summary_accordion,
            pn.layout.Divider(),
            pn.pane.Markdown("### Annotation navigator", styles=SECTION_HEADER_STYLE),
            pn.Row(self.nav_prev_button, self.nav_next_button),
            self.nav_padding_fraction_input,
            self.staged_spans_badge,
            pn.layout.Divider(),
            pn.pane.Markdown("### New annotation", styles=SECTION_HEADER_STYLE),
            self.drag_mode,
            self.drag_mode_description,
            # D4 (earlier round): both "clear" actions sit directly beneath
            # the mode buttons — whichever mode you were in, undoing an
            # accidental drag is immediately at hand, not buried further
            # down. FlexBox (not Row, see the zoom-preset row above for
            # why) so the combined width never overflows the sidebar.
            pn.FlexBox(self.clear_selection_button, self.clear_annotation_selection_button),
            self.selection_info,
            self.start_time_input, self.start_sample_info,
            self.end_time_input, self.end_sample_info,
            self.pending_width_info,
            self.similarity_warning,
            self.compare_similar_button,
            pn.Param(self.param.verdict, widgets={"verdict": pn.widgets.RadioButtonGroup}),
            self.element_widget, self.quality_widget, self.structure_widget,
            self.status_widget, self.event_count_widget,
            pn.Param(self.param.note, widgets={"note": pn.widgets.TextAreaInput}),
            save_btn,
            save_and_run_btn,
            stage_pending_btn,
            review_btn,
            self.status,
            width=340,
            # D5 backstop: whatever the cause, sidebar content must never
            # visually bleed into `viewer_main` beside it -- this was the
            # actual mechanism behind D1/D2/D3's reports (see the
            # zoom-preset row above). Clipping here makes that a hard
            # layout guarantee instead of a promise each new sidebar
            # widget has to individually keep.
            styles={"overflow-x": "hidden"},
        )

        # Part B4: "Selected annotations" (count + Zoom to selected + Run
        # algorithms on selected + Bulk operations) moves out of the left
        # sidebar to sit directly beneath the annotations table — it acts
        # on whatever's selected IN that table/plot, so it reads more
        # naturally next to it than several screens away in the sidebar.
        selected_annotations_panel = pn.Column(
            pn.pane.Markdown("### Selected annotations", styles=SECTION_HEADER_STYLE),
            self.annotation_selection_info,
            self.zoom_to_selected_button,
            self.run_selected_button,
            pn.pane.Markdown("#### Bulk operations"),
            pn.Row(self.bulk_verdict_select, self.bulk_apply_verdict_button),
            pn.Row(self.bulk_status_select, self.bulk_apply_status_button),
            pn.Row(self.bulk_tag_category_select, self.bulk_tag_value_select, self.bulk_tag_action_select),
            self.bulk_apply_tag_button,
            self.bulk_stage_for_algorithms_button,
            self.bulk_confirmation,
            pn.Row(self.bulk_confirm_button, self.bulk_cancel_button),
            sizing_mode="stretch_width",
        )

        filters = pn.Column(
            pn.pane.Markdown("### Filters (table + plot overlay)", styles=SECTION_HEADER_STYLE),
            pn.Row(self.filter_verdict, self.filter_source),
            pn.Row(*self.filter_tag_widgets.values()),
            pn.Row(self.filter_spike_band, self.filter_duration_band, self.clear_filters_button),
            pn.Row(self.search_id_input, self.search_text_input),
            self.filter_match_count,
            pn.Row(self.export_csv_button, self.export_json_button),
            sizing_mode="stretch_width",
        )

        legend_content = pn.pane.Markdown(
            "**Verdict colour key:** "
            "<span style='color:#2ca02c'>■</span> interesting&nbsp;&nbsp;"
            "<span style='color:#7f7f7f'>■</span> not interesting&nbsp;&nbsp;"
            "<span style='color:#d62728'>■</span> artifact&nbsp;&nbsp;"
            "<span style='color:#9467bd'>■</span> unsure&nbsp;&nbsp;&nbsp;"
            "solid border = manual, no border = imported &nbsp;|&nbsp; "
            "<span style='color:#ff7f0e'>┄</span> dashed orange = algorithm detection&nbsp;&nbsp;&nbsp;"
            "<span style='color:#e91e63'>┄</span> dashed magenta = pending (unsaved) span selection&nbsp;&nbsp;&nbsp;"
            "<span style='color:#ffd700'>■</span> gold = selected annotation(s)<br>"
            f"Above {OVERLAY_DENSITY_THRESHOLD} annotations (current filters), individual spans "
            "are replaced by a thin **annotation density** ribbon along the **bottom** of the "
            "plot — same verdict colours, darker where annotations concentrate.<br>"
            "Along the **top**, a separate **reviewed-coverage** ribbon: "
            "<span style='color:#1f77b4'>■</span> fully reviewed&nbsp;&nbsp;"
            "<span style='color:#f0ad4e'>■</span> partially reviewed&nbsp;&nbsp;"
            "<span style='color:#d9d9d9'>■</span> not reviewed (a gap) — always matches the "
            "\"reviewed: X%\" figure below.",
        )
        # Part B1: collapsed by default -- reference material you check
        # occasionally, not a permanent 3-line fixture across the top.
        self.legend_accordion = pn.Accordion(
            ("Verdict colour key", legend_content),
            active=self._initial_accordion_active.get("legend", []),
        )
        self.legend_accordion.param.watch(lambda _e: self._save_session_state(), "active")
        overlay_toggles = pn.Row(
            self.show_annotations_toggle, self.show_detections_toggle,
            self.show_annotation_ribbon_toggle, self.show_reviewed_ribbon_toggle,
        )

        near_dup_row = pn.Column(
            self.find_near_duplicates_button, self.near_duplicates_report,
            sizing_mode="stretch_width",
        )

        view_transform_row = pn.Row(
            self.dc_offset_toggle, self.detrend_toggle, self.y_autoscale_toggle,
        )

        viewer_main = pn.Column(
            self.legend_accordion,
            overlay_toggles,
            view_transform_row,
            self.view_transform_banner,
            filters,
            # Part A (2026-08): reviewed-coverage above, annotation-density
            # below -- separate thin panes, not overlays inside the plot,
            # linked to it by x-range only (see UI/plots.py's module
            # docstring for why). `.visible` collapses either entirely
            # when its toggle is off (Part A4).
            self.reviewed_ribbon_pane,
            self.plot_pane,
            self.annotation_ribbon_pane,
            pn.pane.Markdown("### Cross-channel peek (same time span, linked to the plot above)",
                              styles=SECTION_HEADER_STYLE),
            self.cross_channel_select,
            self.cross_channel_pane,
            pn.pane.Markdown("### Annotations for this channel", styles=SECTION_HEADER_STYLE),
            self.allow_edit_imported_checkbox,
            self.annotations_table,
            # Part B4: acts on whatever's selected in the table/plot above,
            # not the sidebar several screens away.
            selected_annotations_panel,
            pn.Row(delete_btn, self.undo_delete_button),
            near_dup_row,
            sizing_mode="stretch_width",
        )

        viewer_tab = pn.Row(controls, viewer_main, sizing_mode="stretch_width")
        self.tabs = pn.Tabs(
            ("Viewer", viewer_tab),
            ("Run algorithm", self.run_panel.layout()),
            ("Run history", self.run_history.layout()),
            ("Motif browser", self.motif_browser.layout()),
            ("Vocabulary admin", self.admin.layout()),
            ("Import recording", self.file_import.layout()),
            sizing_mode="stretch_width",
        )
        # Part 5 A1: arriving on the Run algorithm tab (index 1) — whether
        # by clicking it directly or via `_switch_to_run_tab`'s
        # programmatic switch after staging — must show a fresh preview of
        # whatever's currently selected there, not whatever was on screen
        # the last time this tab was visited.
        self.tabs.param.watch(self._on_tab_changed, "active")
        return self.tabs


def create_app():
    return ViewerApp().layout()


create_app().servable(title="Mycelium Signal Viewer")

if __name__ == "__main__":
    pn.serve(create_app, show=True, title="Mycelium Signal Viewer")
