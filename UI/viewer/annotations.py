"""
Writing annotations: the new-annotation form, the staged-span basket, the
two-step bulk actions over the selection, and soft-delete with undo.

Everything here writes a *human* verdict, and only ever to `annotations` --
never to `detections` or `adjudications` (coding standard 2.5).
"""

import panel as pn

from Working.database import queries as q
from Working.database import vocabulary as v

from UI.plots import format_scale_viewed
from UI.viewer.constants import ANNOTATION_TAG_CATEGORIES


class AnnotationsMixin:
    """The annotation form, staging, bulk actions and delete/undo."""

    def _build_staged_and_bulk_widgets(self):
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

    def _build_annotation_form(self):
        # ── New-annotation tag widgets, populated from the vocabulary ──────
        self.element_widget = pn.widgets.MultiChoice(name="element", options=[])
        self.quality_widget = pn.widgets.Select(name="quality", options=[""])
        self.structure_widget = pn.widgets.Select(name="structure", options=[""])
        self.status_widget = pn.widgets.Select(name="status", options=[""])
        self.event_count_widget = pn.widgets.TextInput(
            name="event_count (optional)", placeholder="e.g. 16",
        )

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
