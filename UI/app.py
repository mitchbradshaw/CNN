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
reads/writes go through `Working.Preprocessing.database.queries` — the same
functions a headless SLURM script would call.
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import holoviews as hv
import pandas as pd
import panel as pn
import param

from UI.plots import (
    build_annotation_overlay,
    build_channel_dmap,
    build_pending_selection_overlay,
    build_reviewed_overlay,
    format_scale_viewed,
)
from Working.Preprocessing.database.schema import init_db
from Working.Preprocessing.database import queries as q

pn.extension("tabulator")
hv.extension("bokeh")

ANNOTATION_COLUMNS = ["id", "start_idx", "end_idx", "verdict", "tag", "note",
                       "scale_viewed", "source", "created_at"]


class ViewerApp(param.Parameterized):

    source_file = param.Selector(default=None, objects=[])
    channel = param.Selector(default=None, objects=[])
    verdict = param.Selector(default="interesting", objects=list(q.VERDICTS))
    tag = param.String(default="")
    note = param.String(default="")

    def __init__(self, db_path=None, **params):
        super().__init__(**params)
        self.conn = init_db(db_path)

        self._recording_id = None
        self._fs = None
        self._n_samples = None
        self._dmap = None
        self._range_stream = None
        self._bounds_stream = None
        self._full_extent = (0.0, 1.0)
        self._y_extent = (0.0, 1.0)
        self._pending_bounds = None

        self.status = pn.pane.Markdown("", styles={"color": "#a33"})
        self.selection_info = pn.pane.Markdown("*No span selected — drag on the plot.*")
        self.summary_pane = pn.pane.Markdown("")
        self.plot_pane = pn.pane.HoloViews(sizing_mode="stretch_width", linked_axes=False)
        self.annotations_table = pn.widgets.Tabulator(
            pd.DataFrame(columns=ANNOTATION_COLUMNS), page_size=12, disabled=True,
            selectable="checkbox", show_index=False, sizing_mode="stretch_width",
            hidden_columns=[],
        )

        source_files = sorted({r["source_file"] for r in q.list_recordings(self.conn)})
        if not source_files:
            raise RuntimeError(
                "No recordings in the database. Run "
                "Pipelines/materialize_channels/materialize_channels.py first."
            )
        self.param.source_file.objects = source_files
        self.source_file = source_files[0]
        self._refresh_channel_options()
        self._load_recording()

    # ── Recording selection ─────────────────────────────────────────────

    def _refresh_channel_options(self):
        channels = sorted(r["channel"] for r in q.list_recordings(self.conn, self.source_file))
        self.param.channel.objects = channels
        if self.channel not in channels:
            self.channel = channels[0]

    @param.depends("source_file", watch=True)
    def _on_source_file_change(self):
        self._refresh_channel_options()
        self._load_recording()

    @param.depends("channel", watch=True)
    def _on_channel_change(self):
        self._load_recording()

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

        self._dmap, self._range_stream, self._full_extent, self._y_extent = build_channel_dmap(
            rec["npy_path"], self._fs, self._n_samples,
        )
        self._bounds_stream = hv.streams.BoundsX(source=self._dmap)
        self._bounds_stream.add_subscriber(self._on_bounds_selected)
        self._range_stream.add_subscriber(lambda **_: None)  # keep stream alive

        self._refresh_view()
        self._refresh_table()
        self._refresh_summary()
        self.selection_info.object = "*No span selected — drag on the plot.*"

    # ── Plot composition ─────────────────────────────────────────────────

    def _refresh_view(self):
        reviewed_rows = q.list_reviewed_spans(self.conn, self._recording_id)
        annotation_rows = q.list_annotations(self.conn, self._recording_id)
        reviewed_ov = build_reviewed_overlay(reviewed_rows, self._fs, self._y_extent)
        annotation_ov = build_annotation_overlay(annotation_rows, self._fs, self._y_extent)
        pending_ov = build_pending_selection_overlay(self._pending_bounds)
        self.plot_pane.object = (self._dmap * reviewed_ov * annotation_ov * pending_ov)

    def _refresh_table(self):
        rows = q.list_annotations(self.conn, self._recording_id)
        df = pd.DataFrame([dict(r) for r in rows], columns=ANNOTATION_COLUMNS)
        self.annotations_table.value = df

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

    def _on_bounds_selected(self, boundsx):
        self._pending_bounds = boundsx
        if boundsx and boundsx[0] is not None:
            x0, x1 = boundsx
            self.selection_info.object = (
                f"**Selected:** {x0:.1f}s – {x1:.1f}s  (duration {x1 - x0:.1f}s)"
            )
        self._refresh_view()

    # ── Actions ──────────────────────────────────────────────────────────

    def _save_annotation(self, _event=None):
        self.status.object = ""
        if not self._pending_bounds or self._pending_bounds[0] is None:
            self.status.object = "**Drag-select a span on the plot first.**"
            return
        x0, x1 = self._pending_bounds
        if x1 <= x0:
            self.status.object = "**Selection is empty.**"
            return
        start_idx = max(0, int(round(x0 * self._fs)))
        end_idx = min(self._n_samples, int(round(x1 * self._fs)))
        scale_viewed = format_scale_viewed(self._range_stream.x_range, self._full_extent)
        q.insert_annotation(
            self.conn, self._recording_id, start_idx, end_idx, self.verdict,
            source=q.SOURCE_MANUAL_UI, tag=self.tag or None, note=self.note or None,
            scale_viewed=scale_viewed,
        )
        self._pending_bounds = None
        self.tag = ""
        self.note = ""
        self._refresh_view()
        self._refresh_table()
        self._refresh_summary()
        self.selection_info.object = "*Saved. No span selected — drag on the plot.*"

    def _mark_viewport_reviewed(self, _event=None):
        x0, x1 = self._range_stream.x_range or self._full_extent
        start_idx = max(0, int(round(x0 * self._fs)))
        end_idx = min(self._n_samples, int(round(x1 * self._fs)))
        scale_viewed = format_scale_viewed((x0, x1), self._full_extent)
        if not q.reviewed_span_exists(self.conn, self._recording_id, start_idx, end_idx,
                                       q.SOURCE_MANUAL_UI):
            q.insert_reviewed_span(
                self.conn, self._recording_id, start_idx, end_idx,
                source=q.SOURCE_MANUAL_UI, scale_viewed=scale_viewed,
            )
        self._refresh_view()
        self._refresh_summary()
        self.status.object = f"Marked {x0:.0f}s-{x1:.0f}s as reviewed."

    def _delete_selected(self, _event=None):
        self.status.object = ""
        df = self.annotations_table.value
        selected = self.annotations_table.selection
        if not selected:
            self.status.object = "**No rows selected in the table.**"
            return
        skipped = 0
        for i in selected:
            row_id = int(df.iloc[i]["id"])
            try:
                q.delete_annotation(self.conn, row_id)
            except PermissionError:
                skipped += 1
        self._refresh_view()
        self._refresh_table()
        self._refresh_summary()
        if skipped:
            self.status.object = (
                f"Deleted {len(selected) - skipped}; skipped {skipped} imported "
                "annotation(s) (protected)."
            )

    # ── Layout ───────────────────────────────────────────────────────────

    def layout(self):
        save_btn = pn.widgets.Button(name="Save annotation", button_type="primary")
        save_btn.on_click(self._save_annotation)
        review_btn = pn.widgets.Button(name="Mark current viewport reviewed", button_type="default")
        review_btn.on_click(self._mark_viewport_reviewed)
        delete_btn = pn.widgets.Button(name="Delete selected (manual only)", button_type="danger")
        delete_btn.on_click(self._delete_selected)

        controls = pn.Column(
            pn.pane.Markdown("### Recording"),
            pn.Param(self.param.source_file, widgets={"source_file": pn.widgets.Select}),
            pn.Param(self.param.channel, widgets={"channel": pn.widgets.Select}),
            pn.layout.Divider(),
            pn.pane.Markdown("### New annotation"),
            self.selection_info,
            pn.Param(self.param.verdict, widgets={"verdict": pn.widgets.RadioButtonGroup}),
            pn.Param(self.param.tag, widgets={"tag": pn.widgets.TextInput}),
            pn.Param(self.param.note, widgets={"note": pn.widgets.TextAreaInput}),
            save_btn,
            review_btn,
            self.status,
            pn.layout.Divider(),
            pn.pane.Markdown("### Summary"),
            self.summary_pane,
            width=340,
        )

        legend = pn.pane.Markdown(
            "**Verdict colour key:** "
            "<span style='color:#2ca02c'>■</span> interesting&nbsp;&nbsp;"
            "<span style='color:#7f7f7f'>■</span> not interesting&nbsp;&nbsp;"
            "<span style='color:#d62728'>■</span> artifact&nbsp;&nbsp;"
            "<span style='color:#9467bd'>■</span> unsure&nbsp;&nbsp;&nbsp;"
            "faint blue = reviewed &nbsp;|&nbsp; "
            "solid border = manual, no border = imported",
        )

        main = pn.Column(
            legend,
            self.plot_pane,
            pn.pane.Markdown("### Annotations for this channel"),
            self.annotations_table,
            delete_btn,
            sizing_mode="stretch_width",
        )

        return pn.Row(controls, main, sizing_mode="stretch_width")


def create_app():
    return ViewerApp().layout()


create_app().servable(title="Mycelium Signal Viewer")

if __name__ == "__main__":
    pn.serve(create_app, show=True, title="Mycelium Signal Viewer")
