"""
Presentation constants for the viewer, and the one place Panel's and
HoloViews' extensions are activated.

Split out of the single-file `UI/app.py` so that the modules under
`UI/viewer/` share one definition of the table columns, the tag categories
and the drag-mode chrome instead of each carrying its own copy.
"""

import holoviews as hv
import panel as pn

from Working.database import queries as q
from Working.database import bands as b
from Working.config import (
    UI_BASE_FONT_SIZE, UI_MONO_FONT_SIZE, UI_TABLE_FONT_SIZE,
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
