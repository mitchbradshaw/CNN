"""
The main signal view: which recording/channel is loaded, the persistent
channel `DynamicMap` and its overlays, and the linked cross-channel peek.
"""

import holoviews as hv
import panel as pn

from Working.database import queries as q
from Working.database import runs as R
from Working.config import OVERLAY_DENSITY_THRESHOLD

from UI.plots import (
    build_annotation_ribbon, build_channel_dmap, build_detection_overlay, build_peek_curve,
    build_pending_selection_overlay, build_reviewed_ribbon, build_selected_overlay,
    load_channel_mmap, style_main_plot_frame,
)
from UI.viewer.constants import _RefreshTrigger


class SignalViewMixin:
    """Recording selection, channel loading and the main plot. Mixed into `ViewerApp`.

    `_on_source_file_change`/`_on_channel_change` are watched imperatively
    from `ViewerApp.__init__`, not via `@param.depends(..., watch=True)`
    here. That decorator resolves its dependency at *this* class's own
    definition time, and `source_file`/`channel` are declared on `ViewerApp`,
    not on this mixin — across that boundary the decorator either fails to
    resolve the parameter (if this class is made Parameterized) or never
    gets discovered at all (if it isn't, since param only inherits watch
    dependencies from base classes that already have a `.param` namespace).
    Either way it fails silently: the pending-span warning would just stop
    appearing, with nothing to say why.
    """

    def _build_signal_view_widgets(self):
        # Part E4: cross-channel peek — a small linked panel showing the
        # SAME time span on another channel. Equipment faults tend to
        # appear on every channel at once; real biological activity
        # doesn't, so this is a fast artifact/signal discriminator.
        self.cross_channel_select = pn.widgets.Select(name="Compare with channel", options=["(none)"])
        self.cross_channel_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.cross_channel_select.param.watch(lambda _e: self._rebuild_cross_channel_peek(), "value")

    def _build_plot_pane(self):
        self.plot_pane = pn.pane.HoloViews(sizing_mode="stretch_width", linked_axes=False)

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

    def _on_source_file_change(self):
        from Working.config import HELD_OUT_RECORDING_FILE, HELD_OUT_UNLOCK
        
        # Guard against loading the held-out recording unless explicitly unlocked
        if not HELD_OUT_UNLOCK and self.source_file == HELD_OUT_RECORDING_FILE:
            self.status.object = (
                f"**Access to held-out recording '{HELD_OUT_RECORDING_FILE}' is locked.** "
                f"Set HELD_OUT_UNLOCK=True in Working/config.py to temporarily allow access."
            )
            # Revert to a safe selection
            source_files = sorted({r["source_file"] for r in q.list_recordings(self.conn)})
            safe_files = [f for f in source_files if f != HELD_OUT_RECORDING_FILE]
            if safe_files:
                self.source_file = safe_files[0]
            return
        
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
        # Tell the browser something is happening. This method tears down
        # and rebuilds every DynamicMap and reassigns `plot_pane.object`;
        # on a full channel that is comfortably long enough for the plot
        # to look frozen, and a frozen plot invites a second click, which
        # queues a second rebuild. Cleared in the `finally` at the end —
        # a rebuild that raises must not leave the pane greyed out
        # forever, which is indistinguishable from a hang.
        self.plot_pane.loading = True
        try:
            return self._rebuild_plot_inner(rec, preserve_zoom, x_range_override)
        finally:
            self.plot_pane.loading = False

    def _rebuild_plot_inner(self, rec, preserve_zoom, x_range_override):
        """The body of `_rebuild_plot`. Split out only so the loading flag
        has a `try`/`finally` to live in without re-indenting 90 lines."""
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

    # ── Plot composition ─────────────────────────────────────────────────

    def _refresh_view(self):
        """Re-renders the annotation/reviewed/detection/pending overlays by
        triggering their shared DynamicMap stream — deliberately does NOT
        touch `plot_pane.object` (only `_rebuild_plot` does that). See the
        module-level `_RefreshTrigger` docstring."""
        if self._refresh_trigger is not None:
            self._refresh_trigger.event(tick=self._refresh_trigger.tick + 1)
