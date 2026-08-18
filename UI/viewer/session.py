"""
Session persistence (Part E9): last recording, viewport, filters, toggles.

`SESSION_STATE_PATH` is re-read from this module's global on every call, so
a test can point it at a scratch file by rebinding
`UI.viewer.session.SESSION_STATE_PATH` -- see `tests/_session_isolation.py`.
"""

import json
import os

from Working.database import queries as q
from Working.config import SESSION_STATE_PATH

from UI.viewer.constants import DURATION_BAND_OPTIONS, SPIKE_BAND_OPTIONS


class SessionPersistenceMixin:
    """Reads and writes the JSON session file. Mixed into `ViewerApp`."""

    # ── Session persistence (Part E9) ────────────────────────────────────
    #
    # A plain JSON file at SESSION_STATE_PATH, not a DB table -- this is
    # pure UI/session state (last recording, viewport, filters, toggles),
    # not data, and must never participate in the DB-row-count invariant.
    # Both read and write are best-effort: a missing/corrupt/stale session
    # file must never block startup or crash a later save, so every path
    # through these three methods is wrapped to fail silently.

    def _load_session_state(self):
        try:
            with open(SESSION_STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            return state if isinstance(state, dict) else None
        except Exception:
            return None

    def _save_session_state(self):
        if self._restoring_session or not self._init_complete:
            return  # suppressed while applying a loaded session, or during __init__'s own bootstrap
        try:
            state = {
                "source_file": self.source_file,
                "channel": self.channel,
                "x_range": list(self._range_stream.x_range) if (
                    self._range_stream is not None and self._range_stream.x_range is not None
                ) else None,
                "time_unit": self._time_unit,
                "filter_verdict": list(self.filter_verdict.value),
                "filter_source": list(self.filter_source.value),
                "filter_tags": {cat: list(w.value) for cat, w in self.filter_tag_widgets.items()},
                "filter_spike_band": list(self.filter_spike_band.value),
                "filter_duration_band": list(self.filter_duration_band.value),
                "search_id": self.search_id_input.value,
                "search_text": self.search_text_input.value,
                "show_annotations": self.show_annotations_toggle.value,
                "show_detections": self.show_detections_toggle.value,
                "show_annotation_ribbon": self.show_annotation_ribbon_toggle.value,
                "show_reviewed_ribbon": self.show_reviewed_ribbon_toggle.value,
                "dc_offset": self.dc_offset_toggle.value,
                "detrend": self.detrend_toggle.value,
                "y_autoscale": self.y_autoscale_toggle.value,
                # Part B6: accordions only exist once `layout()` has run
                # (unlike every other widget above, which `__init__`
                # builds) -- fall back to whatever was already loaded
                # rather than dropping the saved value if a save happens
                # to fire before `layout()` is ever called.
                "accordion_active": (
                    {
                        "legend": list(self.legend_accordion.active),
                        "shortcuts": list(self.shortcuts_accordion.active),
                        "summary": list(self.summary_accordion.active),
                    }
                    if hasattr(self, "legend_accordion")
                    else self._initial_accordion_active
                ),
            }
            os.makedirs(os.path.dirname(SESSION_STATE_PATH), exist_ok=True)
            tmp_path = SESSION_STATE_PATH + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, SESSION_STATE_PATH)  # atomic on both POSIX and Windows
        except Exception:
            pass

    def _restore_session_state(self, saved, stale_notice=None):
        """Applies a loaded session dict to the already-constructed widgets
        and the already-loaded recording. Every field is validated against
        the CURRENT vocabulary/options before being applied -- a session
        saved against a since-edited vocabulary or a since-removed
        recording must degrade to "skip that one field", never crash
        startup.

        `stale_notice` (Part C1) is the visible warning already computed
        by `__init__` when the saved channel (but not the source_file) no
        longer exists -- passed through so this method's own "restored"
        status message doesn't silently overwrite it; the two are
        combined instead."""
        try:
            if saved.get("time_unit") == "h" and self._time_unit != "h":
                self.time_unit_toggle.value = "hours"
            self.filter_verdict.value = [x for x in saved.get("filter_verdict", []) if x in q.VERDICTS]
            self.filter_source.value = [x for x in saved.get("filter_source", []) if x in self.filter_source.options]
            saved_tags = saved.get("filter_tags", {})
            for cat, widget in self.filter_tag_widgets.items():
                widget.value = [x for x in saved_tags.get(cat, []) if x in widget.options]
            self.filter_spike_band.value = [
                x for x in saved.get("filter_spike_band", []) if x in SPIKE_BAND_OPTIONS
            ]
            self.filter_duration_band.value = [
                x for x in saved.get("filter_duration_band", []) if x in DURATION_BAND_OPTIONS
            ]
            self.search_id_input.value = saved.get("search_id", "") or ""
            self.search_text_input.value = saved.get("search_text", "") or ""
            self.show_annotations_toggle.value = bool(saved.get("show_annotations", True))
            self.show_detections_toggle.value = bool(saved.get("show_detections", True))
            self.show_annotation_ribbon_toggle.value = bool(saved.get("show_annotation_ribbon", True))
            self.show_reviewed_ribbon_toggle.value = bool(saved.get("show_reviewed_ribbon", True))
            self.dc_offset_toggle.value = bool(saved.get("dc_offset", False))
            self.detrend_toggle.value = bool(saved.get("detrend", False))
            self.y_autoscale_toggle.value = bool(saved.get("y_autoscale", True))
            x_range = saved.get("x_range")
            if x_range and len(x_range) == 2 and self._range_stream is not None:
                self._rebuild_plot(x_range_override=tuple(x_range))
            restored_msg = "Restored previous session (recording, filters, viewport)."
            self.status.object = f"{stale_notice}\n\n{restored_msg}" if stale_notice else restored_msg
        except Exception:
            pass
