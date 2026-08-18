"""
Moving the viewport: zoom presets, vertical pan, the display-only view
transforms, the seconds/hours unit toggle, and the annotation navigator.
"""

import panel as pn

from Working.config import ZOOM_PRESETS_SECONDS

from UI.viewer.formatting import _format_duration_human


class NavigationMixin:
    """Viewport movement and the annotation navigator. Mixed into `ViewerApp`."""

    def _build_navigation_widgets(self):
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
