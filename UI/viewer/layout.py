"""
The seven-tab layout. Assembles widgets the other modules built; it does not
build any of its own, so a change to what a control *does* never has to be
made here as well.
"""

import panel as pn

from Working.config import OVERLAY_DENSITY_THRESHOLD

from UI.viewer.constants import SECTION_HEADER_STYLE


class LayoutMixin:
    """Assembles the seven-tab Panel layout. Mixed into `ViewerApp`."""

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
        
        # T18: Four-workspace shell — seven tabs become four workspaces plus Admin group
        # Explore is the existing viewer (behaviorally unchanged)
        # Analyse, Review, Library are mount points that register content without editing the shell
        explore_tab = viewer_tab
        analyse_tab = self.run_panel.layout()
        
        # Review is an empty mount point for now (to be filled by future tickets T20/T21)
        review_tab = pn.pane.Markdown("### Review workspace\n\n*Content to be added by ticket T20/T21*")
        
        # Library contains the motif browser (T18: moved from standalone tab to Library workspace)
        library_tab = self.motif_browser.layout()
        
        # Admin group holds vocabulary administration and recording import
        admin_group = pn.Tabs(
            ("Vocabulary admin", self.admin.layout()),
            ("Import recording", self.file_import.layout()),
        )
        
        self.tabs = pn.Tabs(
            ("Explore", explore_tab),
            ("Analyse", analyse_tab),
            ("Review", review_tab),
            ("Library", library_tab),
            ("Admin", admin_group),
            sizing_mode="stretch_width",
        )
        # Part 5 A1: arriving on the Run algorithm tab (index 1) — whether
        # by clicking it directly or via `_switch_to_run_tab`'s
        # programmatic switch after staging — must show a fresh preview of
        # whatever's currently selected there, not whatever was on screen
        # the last time this tab was visited.
        self.tabs.param.watch(self._on_tab_changed, "active")
        return self.tabs
