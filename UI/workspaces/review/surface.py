"""
surface.py
==========
The Review candidate surface (ticket 21) — one candidate at a time, in its
signal context, with enough padding and overlay to judge it in under a
second.

This surface renders what `queue_state.ReviewQueue` holds; it keeps no
second copy of the queue, the candidate list, or the adjudication write
path. It reads the app's live state (`conn`, `_recording_id`) rather than
duplicating it, the same contract `MotifBrowser` uses.

The two HoloViews panes follow the motif browser's shape exactly on purpose:
the top pane is `build_channel_dmap` (full signal context) with the
candidate's `build_detection_overlay` rectangle on top, and the bottom pane
is `build_motif_waveform_overlay` called — not copied — with a one-seed,
no-neighbour group so the candidate is z-normalised on a relative-time axis
by the same code path the motif browser already uses.
"""

import json

import holoviews as hv
import panel as pn

from Working.config import MOTIF_BOTTOM_HEIGHT, MOTIF_TOP_HEIGHT
from Working.database import queries as q
from UI.plots import (
    PLOT_FONTSIZE,
    build_channel_dmap,
    build_detection_overlay,
    build_motif_waveform_overlay,
    load_channel_mmap,
    style_main_plot_frame,
)
from UI.workspaces.review.queue_state import ReviewQueue

_ReviewRefreshTrigger = hv.streams.Stream.define("ReviewRefreshTrigger", tick=0)

_STATUS_OPTIONS = ("unadjudicated", "adjudicated", "accepted", "rejected", "all")

# The five single-key verdict bindings for the Review workspace. These are
# deliberately disjoint from Explore's keys (1-4, Enter, n/p/r/z/x/c, Escape),
# whose keydown listener is also attached to `document`.
_REVIEW_KEY_ORDER = ("5", "6", "7", "8", "9")
REVIEW_VERDICT_KEYS = dict(zip(_REVIEW_KEY_ORDER, q.VERDICTS))


class ReviewSurface:
    """The candidate queue surface for the Review workspace."""

    def __init__(self, app):
        self.app = app
        self.conn = app.conn
        self.queue = ReviewQueue(self.conn)

        # ── Signal context controls ────────────────────────────────────
        self.pad_left_input = pn.widgets.FloatInput(
            name="Padding left (s)", value=5.0, start=0.0, step=1.0,
        )
        self.pad_right_input = pn.widgets.FloatInput(
            name="Padding right (s)", value=5.0, start=0.0, step=1.0,
        )

        # ── Filters ─────────────────────────────────────────────────────
        self.method_input = pn.widgets.TextInput(name="Method (blank = any)", value="")
        self.score_min_input = pn.widgets.FloatInput(name="Score min", value=None)
        self.score_max_input = pn.widgets.FloatInput(name="Score max", value=None)
        self.channel_input = pn.widgets.TextInput(name="Channel (blank = any)", value="")
        self.status_select = pn.widgets.Select(
            name="Status", options=list(_STATUS_OPTIONS), value="unadjudicated",
        )
        self.apply_filters_button = pn.widgets.Button(name="Apply filters", button_type="primary")

        # ── Navigation ──────────────────────────────────────────────────
        self.next_button = pn.widgets.Button(name="Next candidate", button_type="primary")

        # ── Verdict keys and undo ────────────────────────────────────────
        self.note_input = pn.widgets.TextInput(
            name="Note (saved with next verdict)", value="",
        )
        self.undo_button = pn.widgets.Button(
            name="Undo last verdict", button_type="warning", disabled=True,
        )
        self.verdict_key_reference = pn.pane.Markdown(
            "**Verdict keys** (not while typing in a text field): "
            + " &nbsp;|&nbsp; ".join(
                f"`{key}` = {verdict}"
                for key, verdict in REVIEW_VERDICT_KEYS.items()
            ),
            styles={"background": "#f0f0f0", "padding": "6px 10px",
                    "border-radius": "4px"},
        )
        self._verdict_buttons = {}
        self._build_verdict_shortcut_widgets()

        # ── Readouts and panes ───────────────────────────────────────────
        self.queue_status = pn.pane.Markdown("")
        self.candidate_label = pn.pane.Markdown("*No candidates loaded.*")
        self.score_pane = pn.pane.Markdown("")
        self.signal_pane = pn.pane.HoloViews(sizing_mode="stretch_width")
        self.waveform_pane = pn.pane.HoloViews(sizing_mode="stretch_width")

        # ── State ────────────────────────────────────────────────────────
        self._recording_id = None
        self._fs = None
        self._n_samples = None
        self._npy_path = None
        self._x = None
        self._dmap = None
        self._range_stream = None
        self._full_extent = (0.0, 1.0)
        self._y_extent = (0.0, 1.0)
        self._refresh_trigger = None

        # ── Wiring ───────────────────────────────────────────────────────
        self.apply_filters_button.on_click(self._on_apply_filters)
        self.next_button.on_click(self._on_next)
        self.undo_button.on_click(self._on_undo)
        self.pad_left_input.param.watch(self._on_padding_changed, "value")
        self.pad_right_input.param.watch(self._on_padding_changed, "value")

        self._load_recording()
        self._render_current()

    # ── Layout ────────────────────────────────────────────────────────────

    def layout(self):
        sidebar = pn.Column(
            pn.pane.Markdown("### Review queue"),
            self.queue_status,
            pn.layout.Divider(),
            pn.pane.Markdown("**Verdicts**"),
            self.verdict_key_reference,
            self.note_input,
            self.undo_button,
            pn.layout.Divider(),
            pn.pane.Markdown("**Signal context**"),
            self.pad_left_input,
            self.pad_right_input,
            pn.layout.Divider(),
            pn.pane.Markdown("**Filters**"),
            self.method_input,
            self.score_min_input,
            self.score_max_input,
            self.channel_input,
            self.status_select,
            self.apply_filters_button,
            pn.layout.Divider(),
            *self._verdict_buttons.values(),
            self._review_key_listener,
            self.next_button,
            width=340,
        )
        main = pn.Column(
            self.candidate_label,
            self.score_pane,
            pn.pane.Markdown(
                "*Top: candidate in its signal context (orange dashed box). "
                "Bottom: the same span z-normalised on a relative-time axis.*"
            ),
            self.signal_pane,
            self.waveform_pane,
            sizing_mode="stretch_width",
        )
        return pn.Row(sidebar, main, sizing_mode="stretch_width")

    # ── Actions ──────────────────────────────────────────────────────────

    def advance(self):
        """Move to the next unadjudicated candidate and re-render."""
        self.queue.advance()
        self._render_current()

    def on_tab_activated(self):
        """Refresh from the Viewer's current recording when Review opens.

        The surface is built against `app._recording_id`, which can change
        while Review is not visible. Like `MotifBrowser`, it re-syncs on tab
        activation rather than watching the Viewer continuously."""
        self._render_current()

    def _on_next(self, _event=None):
        self.advance()

    def _on_padding_changed(self, _event=None):
        if self._range_stream is None:
            return
        self._range_stream.event(
            x_range=self._candidate_context_x_range(self.queue.current)
        )

    def _on_apply_filters(self, _event=None):
        filters = {}
        method = (self.method_input.value or "").strip()
        if method:
            filters["method"] = method

        score_min = self._optional_float(self.score_min_input.value)
        if score_min is not None:
            filters["score_min"] = score_min
        score_max = self._optional_float(self.score_max_input.value)
        if score_max is not None:
            filters["score_max"] = score_max

        channel = self._optional_int(self.channel_input.value)
        if channel is not None:
            filters["channel"] = channel

        status = self.status_select.value
        filters["adjudication_status"] = None if status == "all" else status

        try:
            self.queue.set_filters(**filters)
        except ValueError as e:
            self.queue_status.object = f"**Filter error:** {e}"
            return
        self._render_current()

    def _on_verdict(self, verdict):
        """Adjudicate the current candidate and re-render the queue."""
        if self.queue.current is None:
            self._render_current()
            return
        note = (self.note_input.value or "").strip() or None
        self.queue.adjudicate_current(verdict, note=note)
        self.note_input.value = ""
        self._render_current()

    def _on_undo(self, _event=None):
        """Undo the last verdict and return to the candidate it reversed."""
        self.queue.undo()
        self._render_current()

    def _build_verdict_shortcut_widgets(self):
        """Invisible buttons and the keydown listener that clicks them.

        Panel has no global-keyboard hook, so the Review workspace uses the
        same DOM-safe pattern as Explore: one real (1px, opacity 0) button per
        verdict, clicked by a document-level `keydown` listener. Text fields
        are excluded so typing a note/filter value never fires a verdict.
        """

        def _hidden_review_button(css_class, handler):
            btn = pn.widgets.Button(
                name="", css_classes=[css_class], width=1, height=1,
                styles={"opacity": "0", "position": "fixed",
                        "pointer-events": "none", "top": "0", "left": "0"},
            )
            btn.on_click(handler)
            return btn

        for key, verdict in REVIEW_VERDICT_KEYS.items():
            self._verdict_buttons[verdict] = _hidden_review_button(
                f"review-verdict-{key}",
                lambda _event, v=verdict: self._on_verdict(v),
            )

        key_map_js = ", ".join(
            f"'{key}': 'review-verdict-{key}'" for key in REVIEW_VERDICT_KEYS
        )
        self._review_key_listener = pn.pane.HTML(
            """
            <script>
            (function() {
                var KEY_MAP = { __KEY_MAP__ };
                function handleReviewShortcut(e) {
                    var tag = (document.activeElement && document.activeElement.tagName) || '';
                    if (tag === 'INPUT' || tag === 'TEXTAREA') { return; }
                    var cls = KEY_MAP[e.key];
                    if (!cls) { return; }
                    var candidates = document.querySelectorAll('.' + cls + ', .' + cls + ' button');
                    candidates.forEach(function(el) {
                        if (el.tagName === 'BUTTON') { el.click(); }
                    });
                }
                document.removeEventListener('keydown', window.__reviewShortcutHandler || function(){});
                window.__reviewShortcutHandler = handleReviewShortcut;
                document.addEventListener('keydown', handleReviewShortcut);
            })();
            </script>
            """.replace("__KEY_MAP__", key_map_js),
            width=1, height=1, margin=0, styles={"opacity": "0"},
        )

    # ── Rendering ─────────────────────────────────────────────────────────

    def _load_recording(self):
        """Build (or rebuild) the two panes for the app's current recording."""
        recording_id = getattr(self.app, "_recording_id", None)
        if recording_id is None:
            self._recording_id = None
            self.signal_pane.object = hv.Overlay([
                hv.Curve([], "time", "amplitude").opts(axiswise=True)
            ])
            self.waveform_pane.object = hv.Overlay([
                hv.Curve([], "time_s", "zscore").opts(axiswise=True)
            ])
            return

        recording = q.get_recording_by_id(self.conn, recording_id)
        if recording is None:
            self._recording_id = None
            return

        if recording_id == self._recording_id and self._dmap is not None:
            return

        self._recording_id = recording_id
        self._fs = recording["fs"]
        self._n_samples = recording["n_samples"]
        self._npy_path = recording["npy_path"]
        self._x = load_channel_mmap(self._npy_path)

        self._dmap, self._range_stream, self._full_extent, self._y_extent = \
            build_channel_dmap(
                self._npy_path, self._fs, self._n_samples, height=MOTIF_TOP_HEIGHT,
            )

        self._refresh_trigger = _ReviewRefreshTrigger()

        detection_dmap = hv.DynamicMap(
            lambda tick: self._detection_overlay(),
            streams=[self._refresh_trigger],
        )
        self.signal_pane.object = style_main_plot_frame(self._dmap * detection_dmap)

        waveform_dmap = hv.DynamicMap(
            lambda tick: self._waveform_overlay(),
            streams=[self._refresh_trigger],
        ).opts(
            height=MOTIF_BOTTOM_HEIGHT, responsive=True, toolbar=None,
            fontsize=PLOT_FONTSIZE,
        )
        self.waveform_pane.object = waveform_dmap

    def _detection_overlay(self):
        row = self.queue.current
        rows = [row] if row is not None else []
        return build_detection_overlay(rows, self._fs, self._y_extent)

    def _waveform_overlay(self):
        row = self.queue.current
        if row is None:
            return build_motif_waveform_overlay(None, self._x, 0, self._fs)
        m = int(row["end_idx"]) - int(row["start_idx"])
        if m < 1:
            return build_motif_waveform_overlay(None, self._x, 0, self._fs)
        group = {"seed_idx": int(row["start_idx"]), "neighbours": []}
        return build_motif_waveform_overlay(group, self._x, m, self._fs)

    def _render_current(self):
        self._load_recording()
        self.undo_button.disabled = not bool(self.queue.history)
        if self._range_stream is None:
            self.queue_status.object = "**No recording loaded in the Viewer.**"
            self.candidate_label.object = "*No candidates loaded.*"
            self.score_pane.object = ""
            return

        row = self.queue.current
        n = len(self.queue.candidates)
        if row is None:
            self.queue_status.object = "**No candidates match these filters.**"
            self.candidate_label.object = "*End of the queue.*"
            self.score_pane.object = ""
        else:
            method = self._detection_method(row["config_json"]) or "unknown"
            start_s = row["start_idx"] / self._fs
            end_s = row["end_idx"] / self._fs
            self.queue_status.object = (
                f"**Candidate {self.queue.index + 1} / {n}** — "
                f"method={method}, span {start_s:.3f}s–{end_s:.3f}s"
            )
            self.candidate_label.object = (
                f"### Candidate {self.queue.index + 1} / {n}\n\n"
                f"detection_id={row['id']}, method={method}, "
                f"span [{row['start_idx']}, {row['end_idx']}) samples "
                f"({start_s:.3f}s–{end_s:.3f}s)"
            )
            if row["score"] is None:
                self.score_pane.object = "**Analytical score:** —"
            else:
                self.score_pane.object = f"**Analytical score:** {row['score']:.3f}"

        self._range_stream.event(x_range=self._candidate_context_x_range(row))
        self._refresh_trigger.event(tick=self._refresh_trigger.tick + 1)

    def _candidate_context_x_range(self, row):
        if row is None:
            return self._full_extent
        start_s = row["start_idx"] / self._fs
        end_s = row["end_idx"] / self._fs
        left = max(self._full_extent[0], start_s - float(self.pad_left_input.value))
        right = min(self._full_extent[1], end_s + float(self.pad_right_input.value))
        if right <= left:
            right = min(self._full_extent[1], left + 1.0)
        return (left, right)

    # ── Small parsing helpers ─────────────────────────────────────────────

    @staticmethod
    def _optional_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_int(value):
        raw = (value or "").strip()
        if not raw:
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _detection_method(config_json):
        if not config_json:
            return None
        try:
            data = json.loads(config_json)
        except (TypeError, ValueError):
            return None
        for step in data.get("steps", []):
            if step.get("stage") == "detection":
                return step.get("algorithm")
        return None
