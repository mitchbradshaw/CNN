"""
motif_browser.py
==================
The motif browser (MATRIX_PROFILE_UI_PROMPT.md §6, "slide 27"): pick a
scale from the matrix-profile ladder, browse precomputed motif groups
(seed + nearest neighbours) two at a time — the full channel with
occurrence markers on top, all occurrences z-normalised and overlaid on
a shared relative-time axis below.

The group LIST is precomputed once per (run, n_neighbors, max_motifs,
max_distance) and persisted (`Working.Detection.matrix_profiling.
motif_groups`) — this tab never re-walks `argsort(mp)` + `stumpy.match`
per slide on open, only on an explicit Compute/Recompute action.

Compute-a-missing-scale deliberately does NOT duplicate `run_panel.py`'s
background-thread/progress/cancel machinery: it stages the
`detection.matrix_profile` recipe in the existing Run panel (the same way
`run_history.py`'s "Reopen" does) and switches tabs there, so the one
tier-routing/execution implementation this app has stays the only one.
"""

import json

import holoviews as hv
import numpy as np
import panel as pn

from Working.config import (
    MOTIF_BOTTOM_HEIGHT, MOTIF_DEFAULT_MAX_MOTIFS, MOTIF_DEFAULT_N_NEIGHBORS, MOTIF_TOP_HEIGHT,
)
from Working.database import queries as q
from Working.database import runs as R
from Working.database import vocabulary as v
from Working.database import matrix_profile_store as store
from Working.Detection.matrix_profiling import motif_groups as mg
from Working.Detection.matrix_profiling.segments import segment_profile, slice_channel_profile
from UI.plots import (
    build_channel_dmap, build_motif_occurrence_overlay, build_motif_waveform_overlay,
    load_channel_mmap, style_main_plot_frame, PLOT_FONTSIZE,
)
from UI.workspaces.library.grid import LibraryGrid

_MotifRefreshTrigger = hv.streams.Stream.define("MotifRefreshTrigger", tick=0)

_STATE_LABELS = {
    "available": "", "approx": " (approx)", "stale": " (stale)",
    "missing": " (missing)", "invalid": " (invalid)",
}

_SEGMENT_MODE_OPTIONS = [
    "(1) nearest neighbour across full channel",
    "(2) nearest neighbour within this segment",
]


class MotifBrowser:
    def __init__(self, app):
        self.app = app
        self.conn = app.conn
        self.library_grid = LibraryGrid(app)

        # ── Scale switcher ──────────────────────────────────────────────
        self.scale_radio = pn.widgets.RadioButtonGroup(name="Scale", options=[], button_type="default")
        self.scale_status = pn.pane.Markdown("*Open this tab after loading a recording in the Viewer.*")
        self.compute_button = pn.widgets.Button(name="Compute this scale", button_type="primary", visible=False)

        # ── Group-set parameters ────────────────────────────────────────
        self.n_neighbors = pn.widgets.IntInput(name="n_neighbors", value=MOTIF_DEFAULT_N_NEIGHBORS, start=1, end=50)
        self.max_motifs = pn.widgets.IntInput(name="max_motifs", value=MOTIF_DEFAULT_MAX_MOTIFS, start=1, end=1000)
        self.max_distance = pn.widgets.TextInput(name="max_distance (blank = no cap)", value="")
        self.recompute_notice = pn.pane.Markdown("", visible=False)
        self.recompute_button = pn.widgets.Button(name="Recompute group set", button_type="warning", visible=False)

        # ── Navigation ───────────────────────────────────────────────────
        self.prev_button = pn.widgets.Button(name="<  Prev")
        self.next_button = pn.widgets.Button(name="Next  >")
        self.jump_input = pn.widgets.IntInput(name="Jump to group (1-based)", value=1, start=1)
        self.group_label = pn.pane.Markdown("*No groups loaded.*")

        # ── Actions ──────────────────────────────────────────────────────
        self.open_in_viewer_button = pn.widgets.Button(name="Open in Viewer")
        self.motif_label = pn.widgets.TextInput(name="Label")
        self.motif_elements = pn.widgets.MultiChoice(name="element tags", options=[])
        self.motif_rating = pn.widgets.IntSlider(name="Rating", start=0, end=5, value=0)
        self.motif_notes = pn.widgets.TextAreaInput(name="Notes")
        self.save_motif_button = pn.widgets.Button(name="Save group as motif", button_type="primary")
        self.motif_status = pn.pane.Markdown("")

        # ── Segment mode (MATRIX_PROFILE_UI_PROMPT.md §4 / §6.3) ────────
        self.segment_mode_radio = pn.widgets.RadioButtonGroup(
            name="Segment reading", options=_SEGMENT_MODE_OPTIONS, value=_SEGMENT_MODE_OPTIONS[0],
        )
        self.segment_mode_button = pn.widgets.Button(name="Compute for staged span")
        self.segment_mode_status = pn.pane.Markdown("")

        # ── Panes ────────────────────────────────────────────────────────
        self.top_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.bottom_pane = pn.pane.HoloViews(sizing_mode="stretch_width")

        # ── State ────────────────────────────────────────────────────────
        self._recording = None
        self._scale_status_base = ""
        self._ladder_rows = {}
        self._label_to_window_min = {}
        self._selected_window_min = None
        self._run_id = None
        self._m = None
        self._fs_at_scale = None
        self._mp = None
        self._x = None
        self._groups = []
        self._group_index = 0
        self._current_group_for_render = None
        self._dmap = None
        self._refresh_trigger = None
        self._group_params_dirty = False

        # ── Wiring ───────────────────────────────────────────────────────
        self.scale_radio.param.watch(self._on_scale_changed, "value")
        self.compute_button.on_click(self._on_compute_scale)
        for w in (self.n_neighbors, self.max_motifs, self.max_distance):
            w.param.watch(self._on_group_params_changed, "value")
        self.recompute_button.on_click(self._on_recompute_groups)
        self.prev_button.on_click(self._on_prev)
        self.next_button.on_click(self._on_next)
        self.jump_input.param.watch(self._on_jump, "value")
        self.open_in_viewer_button.on_click(self._on_open_in_viewer)
        self.save_motif_button.on_click(self._on_save_motif)
        self.segment_mode_button.on_click(self._on_segment_mode_compute)

        self.motif_elements.options = [r["value"] for r in v.list_terms(self.conn, category="element")]

    # ── Tab lifecycle ────────────────────────────────────────────────────

    def on_tab_activated(self):
        """Called by `UI/app.py` when this tab becomes active. Recording
        / channel default to "whatever the Viewer has loaded"
        (MATRIX_PROFILE_UI_PROMPT.md §6.3) — refreshed here rather than
        watched continuously, since the Viewer's recording only matters
        while this tab is actually visible."""
        self._refresh_ladder()

    # ── Scale ladder ─────────────────────────────────────────────────────

    def _refresh_ladder(self):
        if self.app._recording_id is None:
            self.scale_status.object = "*No recording loaded in the Viewer.*"
            self.scale_radio.options = []
            return
        recording = q.get_recording_by_id(self.conn, self.app._recording_id)
        if recording is None:
            return
        new_recording = self._recording is None or recording["id"] != self._recording["id"]
        self._recording = recording

        rows = store.ladder_status(self.conn, recording["id"], recording["fs"], recording["n_samples"])
        self._ladder_rows = {r["window_min"]: r for r in rows}
        options = [f"{r['window_min']:g} min{_STATE_LABELS[r['state']]}" for r in rows]
        self._label_to_window_min = {opt: r["window_min"] for opt, r in zip(options, rows)}
        self.scale_radio.options = options

        if new_recording:
            self._selected_window_min = None
            self._reset_group_state()
            self.scale_status.object = (
                f"**{recording['source_file']} CH{recording['channel']:02d}** — pick a scale."
            )
            self.top_pane.object = None
            self.bottom_pane.object = None
            # Auto-select the first already-AVAILABLE scale, if any, as a
            # convenience default — still fully transparent (the selection
            # is visible and labelled, not a silent choice); falls back to
            # no selection if nothing has been computed for this recording
            # yet, so the user isn't left staring at a blank pane with no
            # indication why.
            available = next((opt for opt, r in zip(options, rows) if r["state"] == "available"), None)
            self.scale_radio.value = available
        elif options and self.scale_radio.value not in options:
            self.scale_radio.value = options[0]

    def _on_scale_changed(self, event):
        if event.new is None:
            return
        window_min = self._label_to_window_min.get(event.new)
        if window_min is None:
            return
        self._selected_window_min = window_min
        row = self._ladder_rows[window_min]

        if row["state"] == "invalid":
            self.scale_status.object = f"**{window_min:g} min is not valid here:** {row['reason']}"
            self.compute_button.visible = False
            self._reset_group_state()
            return

        if row["state"] == "missing":
            est = f" (est. {row['est_seconds']:.0f}s)" if row.get("est_seconds") else " (not calibrated)"
            self.scale_status.object = f"**{window_min:g} min has not been computed yet**{est}."
            self.compute_button.visible = True
            self._reset_group_state()
            return

        self.compute_button.visible = False
        note = {"approx": " — **approximate profile.**", "stale": " — **stale: source data changed.**"}.get(row["state"], "")
        self._scale_status_base = f"**{window_min:g} min** (run_id={row['run_id']}){note}"
        self.scale_status.object = self._scale_status_base
        self._load_scale(window_min, row)

    def _on_compute_scale(self, _event=None):
        """Stages the recipe in the Run panel rather than running it here
        — see module docstring for why (one execution/progress/cancel
        implementation, not two)."""
        if self._selected_window_min is None:
            return
        rp = self.app.run_panel
        rp.stage_select.value = "detection"
        rp._on_stage_changed(None)
        rp.algorithm_select.value = "detection.matrix_profile"
        rp._on_algorithm_changed(None)
        if "window_min" in rp._param_widgets:
            rp._param_widgets["window_min"].value = self._selected_window_min
        rp.span_mode.value = "Whole channel"
        if self.app.tabs is not None:
            self.app.tabs.active = 1
        self.scale_status.object = (
            f"Opened **Run algorithm** with window_min={self._selected_window_min:g} min staged "
            "(whole channel) — click Run there, then come back to this tab and re-select the scale."
        )

    # ── Loading a scale's profile + groups ──────────────────────────────

    def _load_scale(self, window_min, row):
        match = store.find_mp(self.conn, self._recording["id"], window_min)
        if match is None:
            self.scale_status.object = "*Artifact listed as available but could not be found — try Refresh.*"
            self._reset_group_state()
            return
        data = store.load_mp(match["artifact_path"], mmap=False)
        self._mp = np.asarray(data["mp"], dtype=np.float32)
        self._m = int(data["m"])
        self._fs_at_scale = float(data["fs"])
        self._run_id = match["run_id"]
        self._x = load_channel_mmap(self._recording["npy_path"])

        self._build_panes()
        self._rebuild_groups()

    def _build_panes(self):
        self._dmap, self._range_stream, self._full_extent, self._y_extent = build_channel_dmap(
            self._recording["npy_path"], self._fs_at_scale, self._recording["n_samples"],
            height=MOTIF_TOP_HEIGHT,
        )
        self._refresh_trigger = _MotifRefreshTrigger()

        markers_dmap = hv.DynamicMap(
            lambda tick: build_motif_occurrence_overlay(
                self._current_group_for_render, self._m, self._fs_at_scale, self._y_extent,
            ),
            streams=[self._refresh_trigger],
        )
        self.top_pane.object = style_main_plot_frame(self._dmap * markers_dmap)

        waveform_dmap = hv.DynamicMap(
            lambda tick: build_motif_waveform_overlay(
                self._current_group_for_render, self._x, self._m, self._fs_at_scale,
            ),
            streams=[self._refresh_trigger],
        ).opts(height=MOTIF_BOTTOM_HEIGHT, responsive=True, toolbar=None, fontsize=PLOT_FONTSIZE)
        self.bottom_pane.object = waveform_dmap

    # ── Group set ────────────────────────────────────────────────────────

    def _parse_max_distance(self):
        raw = (self.max_distance.value or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _on_group_params_changed(self, _event=None):
        # Never recompute on a widget nudge alone (MATRIX_PROFILE_UI_PROMPT.md
        # §6.3) — just make the cost of doing so visible and explicit.
        if self._run_id is None:
            return
        self._group_params_dirty = True
        self.recompute_notice.object = (
            f"Parameters changed — click Recompute to build a new group set "
            f"(n_neighbors={int(self.n_neighbors.value)}, max_motifs={int(self.max_motifs.value)}, "
            f"max_distance={self._parse_max_distance()})."
        )
        self.recompute_notice.visible = True
        self.recompute_button.visible = True

    def _rebuild_groups(self, force=False):
        if self._run_id is None:
            return
        groups, reused = mg.get_or_build_motif_groups(
            self.conn, self._run_id, self._x, self._mp, self._m,
            n_neighbors=int(self.n_neighbors.value), max_motifs=int(self.max_motifs.value),
            max_distance=self._parse_max_distance(), force=force,
        )
        self._groups = groups
        self._group_index = 0
        self._group_params_dirty = False
        self.recompute_notice.visible = False
        self.recompute_button.visible = False
        reuse_note = " (reused an existing group set)" if reused else " (computed a new group set)"
        self.scale_status.object = self._scale_status_base + reuse_note
        self._refresh_group_view()

    def _on_recompute_groups(self, _event=None):
        self._rebuild_groups(force=True)

    def _reset_group_state(self):
        self._run_id = None
        self._groups = []
        self._group_index = 0
        self._current_group_for_render = None
        self.group_label.object = "*No groups loaded.*"
        if self._refresh_trigger is not None:
            self._refresh_trigger.event(tick=self._refresh_trigger.tick + 1)

    # ── Navigation ───────────────────────────────────────────────────────

    def _refresh_group_view(self):
        n = len(self._groups)
        if n == 0:
            self.group_label.object = "*No motif groups for this scale/parameters.*"
            self._current_group_for_render = None
        else:
            self._group_index = max(0, min(self._group_index, n - 1))
            g = self._groups[self._group_index]
            self._current_group_for_render = g
            seed_t = g["seed_idx"] / self._fs_at_scale
            self.group_label.object = (
                f"**Motif {self._group_index + 1} / {n}**   seed @ {seed_t:.3f} s   "
                f"MP distance = {g['mp_distance']:.4f}   ({len(g['neighbours'])} neighbours)"
            )
            self.jump_input.value = self._group_index + 1
        if self._refresh_trigger is not None:
            self._refresh_trigger.event(tick=self._refresh_trigger.tick + 1)

    def _on_prev(self, _event=None):
        if self._groups and self._group_index > 0:
            self._group_index -= 1
            self._refresh_group_view()

    def _on_next(self, _event=None):
        if self._groups and self._group_index < len(self._groups) - 1:
            self._group_index += 1
            self._refresh_group_view()

    def _on_jump(self, event):
        if not self._groups or event.new is None:
            return
        target = max(1, min(event.new, len(self._groups))) - 1
        if target != self._group_index:
            self._group_index = target
            self._refresh_group_view()

    # ── Actions ──────────────────────────────────────────────────────────

    def _current_group(self):
        if not self._groups:
            return None
        return self._groups[self._group_index]

    def _on_open_in_viewer(self, _event=None):
        g = self._current_group()
        if g is None or self.app._range_stream is None or self._fs_at_scale is None:
            return
        scale = self.app._unit_scale()
        start_s = g["seed_idx"] / self._fs_at_scale
        end_s = (g["seed_idx"] + self._m) / self._fs_at_scale
        pad = max((end_s - start_s) * 2.0, 1.0)
        self.app._range_stream.event(x_range=((start_s - pad) / scale, (end_s + pad) / scale))
        if self.app.tabs is not None:
            self.app.tabs.active = 0
        self.motif_status.object = f"Jumped the Viewer to seed @ {start_s:.3f}s."

    def _clear_motif_fields(self):
        self.motif_label.value = ""
        self.motif_elements.value = []
        self.motif_rating.value = 0
        self.motif_notes.value = ""

    def _on_save_motif(self, _event=None):
        self.motif_status.object = ""
        g = self._current_group()
        if g is None or "detection_id" not in g:
            self.motif_status.object = "**No group selected.**"
            return
        det = R.get_detection(self.conn, g["detection_id"])
        run = R.get_run(self.conn, det["run_id"])
        entry_id = R.insert_motif_entry(
            self.conn, run["recording_id"], det["start_idx"], det["end_idx"],
            detection_id=g["detection_id"],
            label=self.motif_label.value or None, rating=self.motif_rating.value or None,
            notes=self.motif_notes.value or None,
        )
        if self.motif_elements.value:
            v.set_motif_entry_tags(self.conn, entry_id, "element", self.motif_elements.value)
        self.motif_status.object = f"Saved motif id={entry_id} (detection_id={g['detection_id']})."
        self._clear_motif_fields()

    # ── Segment mode (§4) ────────────────────────────────────────────────

    def _on_segment_mode_compute(self, _event=None):
        self.segment_mode_status.object = ""
        bounds = getattr(self.app, "_pending_bounds", None)
        if bounds is None or bounds[0] is None or bounds[1] is None:
            self.segment_mode_status.object = (
                "**No span staged in the Viewer.** Drag-select or enter a Start/End "
                "time there first."
            )
            return
        if self._mp is None or self._x is None or self._m is None:
            self.segment_mode_status.object = "**Select an available scale first.**"
            return
        scale = self.app._unit_scale()
        a = int(round(bounds[0] * scale * self._fs_at_scale))
        b = int(round(bounds[1] * scale * self._fs_at_scale))
        reading = self.segment_mode_radio.value
        try:
            if reading == _SEGMENT_MODE_OPTIONS[0]:
                values = slice_channel_profile(self._mp, self._m, a, b)
                label = "nearest neighbour across full channel"
            else:
                result = segment_profile(self._x, self._m, a, b)
                values = result["mp"]
                label = "nearest neighbour within this segment"
        except ValueError as e:
            self.segment_mode_status.object = f"**{e}**"
            return
        if len(values) == 0:
            self.segment_mode_status.object = f"**{label}:** span too short for window m={self._m}."
            return
        finite = values[np.isfinite(values)]
        if len(finite) == 0:
            self.segment_mode_status.object = f"**{label}:** no finite values in this span."
            return
        self.segment_mode_status.object = (
            f"**{label}** over [{a}, {b}) ({len(values)} positions): "
            f"min={finite.min():.4f}  mean={finite.mean():.4f}  max={finite.max():.4f}"
        )

    # ── Layout ───────────────────────────────────────────────────────────

    def _browser_layout(self):
        sidebar = pn.Column(
            pn.pane.Markdown("### Motif browser"),
            self.scale_status,
            self.scale_radio,
            self.compute_button,
            pn.layout.Divider(),
            pn.pane.Markdown("**Group set**"),
            self.n_neighbors, self.max_motifs, self.max_distance,
            self.recompute_notice, self.recompute_button,
            pn.layout.Divider(),
            pn.Row(self.prev_button, self.next_button),
            self.jump_input, self.group_label,
            pn.layout.Divider(),
            self.open_in_viewer_button,
            pn.pane.Markdown("**Save this group as a motif**"),
            self.motif_label, self.motif_elements, self.motif_rating, self.motif_notes,
            self.save_motif_button, self.motif_status,
            pn.layout.Divider(),
            pn.pane.Markdown(
                "**Segment mode** — with a span staged in the Viewer, compare the two "
                "readings from MATRIX_PROFILE_UI_PROMPT.md §4 explicitly (never defaulted)."
            ),
            self.segment_mode_radio, self.segment_mode_button, self.segment_mode_status,
            width=340,
        )
        main = pn.Column(
            pn.pane.Markdown(
                "*Top: full channel, occurrence markers (seed + neighbours). "
                "Bottom: all occurrences overlaid, z-normalised on a shared relative-time axis.*"
            ),
            self.top_pane, self.bottom_pane,
            sizing_mode="stretch_width",
        )
        return pn.Row(sidebar, main, sizing_mode="stretch_width")

    def layout(self):
        """The Library workspace surface: the grid first, the existing motif
        browser preserved as a second sub-tab rather than replaced."""
        return pn.Tabs(
            ("Library grid", self.library_grid.layout()),
            ("Motif browser", self._browser_layout()),
            sizing_mode="stretch_width",
        )
