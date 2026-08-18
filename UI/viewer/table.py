"""
The annotations Tabulator: what it shows, what may be edited in it, and how
its row selection stays in step with the plot's.
"""

import pandas as pd
import panel as pn

from Working.database import queries as q
from Working.database import vocabulary as v
from Working.database import bands as b

from UI.viewer.constants import TABLE_COLUMNS, TABLE_EDITORS


class AnnotationTableMixin:
    """The annotation table and the channel summary. Mixed into `ViewerApp`."""

    def _build_annotation_table(self):
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
