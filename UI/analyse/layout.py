"""
The run tab's layout. Assembles widgets the other modules built.
"""

import panel as pn


class LayoutMixin:
    """Assembles the run tab. Mixed into `RunPanel`."""

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
                pn.pane.Markdown("### Run"),
                pn.pane.Markdown("**Span:**"), self.span_mode,
                pn.FlexBox(self.run_button, self.cancel_button, self.confirm_rerun_button),
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
                self.filmstrip_pane,
                self.scale_note,
                pn.Row(self.save_plot_button, self.save_plot_status),
                self.encoding_section,  # Part 6, 4f: hidden entirely unless the last run was an encoding
                pn.pane.Markdown("### Detections (this run)"),
                self.detections_caption,
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
