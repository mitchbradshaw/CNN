"""
Two selections, deliberately distinct: the *pending* span being drawn for a
new annotation, and the set of *existing* annotations selected in the table
or on the plot. The drag mode decides which one a drag feeds.
"""

import panel as pn

from Working.database import queries as q
from Working.database.similarity import find_similar_annotations, find_near_duplicate_pairs

from UI.plots import build_channel_dmap, x_range_to_sample_bounds
from UI.viewer.constants import (
    _DRAG_MODE_COLORS, _DRAG_MODE_DESCRIPTIONS, _DRAG_MODE_STYLE_BASE,
)
from UI.viewer.formatting import _format_duration_human


class SelectionMixin:
    """Pending-span bounds, the shared annotation selection, and drag modes."""

    def _build_selection_widgets(self):
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
