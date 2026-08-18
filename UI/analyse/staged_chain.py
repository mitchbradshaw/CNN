"""
The staged-span basket as the run panel sees it. The list itself lives on
the owning `ViewerApp` (`app._staged_spans`) -- this module views and edits
it, and resolves "which span would actually run" from it.
"""

import pandas as pd
import panel as pn

from Working.database import queries as q

from UI.analyse.formatting import _format_duration_human


class StagedChainMixin:
    """The staged-span table and the span a run would use. Mixed into `RunPanel`."""

    def _build_staged_widgets(self):
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
