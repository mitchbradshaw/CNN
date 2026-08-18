"""
The filter and search controls, the single filtered-row query every consumer
(table, plot overlay, live counts, export) goes through, and the exports of
whatever that query currently returns.
"""

import io
import json

import pandas as pd
import panel as pn

from Working.database import queries as q
from Working.database import vocabulary as v
from Working.database import bands as b

from UI.viewer.constants import DURATION_BAND_OPTIONS, FILTER_TAG_CATEGORIES, SPIKE_BAND_OPTIONS


class FiltersMixin:
    """Filter/search widgets, the filtered-row query, and the CSV/JSON exports."""

    def _build_filter_widgets(self):
        # ── Filter widgets — affect both the table and the plot overlay ───
        self.filter_verdict = pn.widgets.MultiChoice(name="verdict", options=list(q.VERDICTS))
        self.filter_source = pn.widgets.MultiChoice(name="source", options=[])
        self.filter_tag_widgets = {
            cat: pn.widgets.MultiChoice(name=cat, options=[]) for cat in FILTER_TAG_CATEGORIES
        }
        self.filter_spike_band = pn.widgets.MultiChoice(name="spike-train length", options=SPIKE_BAND_OPTIONS)
        self.filter_duration_band = pn.widgets.MultiChoice(name="duration", options=DURATION_BAND_OPTIONS)
        self.clear_filters_button = pn.widgets.Button(name="Clear filters", button_type="default")
        self.clear_filters_button.on_click(self._on_clear_filters)

        # D2: search composes WITH the filters above (both apply), not
        # instead of them -- folded into the same `_filtered_annotation_rows`
        # every other consumer (table, plot overlay, live counts) already
        # calls, so there's no separate code path that could drift.
        self.search_id_input = pn.widgets.TextInput(
            name="Search by id", placeholder="e.g. 42, 108, 233",
        )
        self.search_text_input = pn.widgets.TextInput(
            name="Search note/tags", placeholder="free text",
        )

        self.filter_match_count = pn.pane.Markdown("")

        # Part E8: export the CURRENT filtered/searched set, tags and
        # derived bands included — `callback=` (not a static `file=`) so
        # each download reflects whatever's filtered/searched at click time.
        self.export_csv_button = pn.widgets.FileDownload(
            callback=self._export_csv_callback, filename="annotations.csv",
            button_type="default", label="Export filtered set (CSV)",
        )
        self.export_json_button = pn.widgets.FileDownload(
            callback=self._export_json_callback, filename="annotations.json",
            button_type="default", label="Export filtered set (JSON)",
        )

    def _wire_filter_watchers(self):
        for w in [self.filter_verdict, self.filter_source, self.filter_spike_band,
                  self.filter_duration_band, self.search_id_input, self.search_text_input,
                  *self.filter_tag_widgets.values()]:
            w.param.watch(lambda _e: self._on_filters_changed(), "value")

    # ── Filtering ─────────────────────────────────────────────────────────

    def _on_filters_changed(self):
        self._refresh_view()
        self._refresh_table()
        self._update_filter_match_count()
        self._save_session_state()

    def _on_clear_filters(self, _event=None):
        self.filter_verdict.value = []
        self.filter_source.value = []
        self.filter_spike_band.value = []
        self.filter_duration_band.value = []
        self.search_id_input.value = ""
        self.search_text_input.value = ""
        for w in self.filter_tag_widgets.values():
            w.value = []

    def _update_filter_match_count(self):
        """Part E10: distinguishes an empty result from a broken filter —
        without this, both look identical (an empty table)."""
        if self._recording_id is None:
            self.filter_match_count.object = ""
            return
        total = len(q.list_annotations(self.conn, self._recording_id))
        matched = len(self._filtered_annotation_rows())
        if matched == total:
            self.filter_match_count.object = f"**{total}** annotation(s) (no filters active)"
        else:
            self.filter_match_count.object = f"**{matched}** of {total} annotation(s) match"

    # ── Export (Part E8) ─────────────────────────────────────────────────

    def _export_records(self):
        """The current filtered/searched set (same `_filtered_annotation_rows`
        everything else uses), with tags and derived bands included —
        shared by both the CSV and JSON export callbacks so the two never
        drift out of sync with each other or with what's on screen."""
        rows = self._filtered_annotation_rows()
        tags_by_id = v.get_tags_for_recording(self.conn, self._recording_id) if self._recording_id else {}
        records = []
        for r in rows:
            tags = tags_by_id.get(r["id"], {})
            records.append({
                "id": r["id"], "recording_id": r["recording_id"],
                "source_file": self.source_file, "channel": self.channel,
                "start_idx": r["start_idx"], "end_idx": r["end_idx"],
                "verdict": r["verdict"], "status": r["status"], "event_count": r["event_count"],
                "spike_train_band": b.spike_train_band(r["event_count"]),
                "duration_band": b.duration_band(r["start_idx"], r["end_idx"], self._fs),
                "element": list(tags.get("element", [])),
                "quality": list(tags.get("quality", [])),
                "structure": list(tags.get("structure", [])),
                "source": r["source"], "note": r["note"], "created_at": r["created_at"],
            })
        return records

    def _export_csv_callback(self):
        records = self._export_records()
        for r in records:  # CSV has no list type -- join tag lists into one string
            for k in ("element", "quality", "structure"):
                r[k] = ", ".join(r[k])
        df = pd.DataFrame(records)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return io.BytesIO(buf.getvalue().encode("utf-8"))

    def _export_json_callback(self):
        records = self._export_records()
        return io.BytesIO(json.dumps(records, indent=2, default=str).encode("utf-8"))

    def _filtered_annotation_rows(self):
        """The one canonical filter function — the table (`_refresh_table`),
        the annotation-density ribbon pane (`annotation_ribbon_dmap` in
        `_rebuild_plot`), and the live per-filter match counts
        (`_update_filter_counts`) all call this, not independent copies of
        the same logic, so they can't silently drift apart.

        Semantics: OR *within* each multi-select category, AND *across*
        categories — e.g. verdict IN (a, b) AND source IN (c) AND
        element-tag IN (...). Each `if widget.value and row[...] not in
        widget.value: continue` line below is exactly that OR-within-
        category test (empty selection = no restriction from that
        category, not "match nothing"); chaining several such checks
        with independent `continue`s is what gives AND-across-categories.
        """
        rows = q.list_annotations(self.conn, self._recording_id)

        tag_filters = {cat: w.value for cat, w in self.filter_tag_widgets.items() if w.value}
        matching_ids = v.annotations_matching_tags(self.conn, self._recording_id, tag_filters)
        tags_by_id = v.get_tags_for_recording(self.conn, self._recording_id)

        # D2: search composes with (is ANDed onto) the filters above, not a
        # separate code path -- an id search matches ANY of the listed ids
        # (OR, like every other multi-value control here); a text search
        # matches note OR any tag value, case-insensitively.
        id_query = self.search_id_input.value.strip()
        wanted_ids = set()
        for tok in id_query.replace(",", " ").split():
            try:
                wanted_ids.add(int(tok))
            except ValueError:
                pass
        text_query = self.search_text_input.value.strip().lower()

        out = []
        for r in rows:
            if matching_ids is not None and r["id"] not in matching_ids:
                continue
            if self.filter_verdict.value and r["verdict"] not in self.filter_verdict.value:
                continue
            if self.filter_source.value and r["source"] not in self.filter_source.value:
                continue
            if self.filter_spike_band.value:
                if b.spike_train_band(r["event_count"]) not in self.filter_spike_band.value:
                    continue
            if self.filter_duration_band.value:
                if b.duration_band(r["start_idx"], r["end_idx"], self._fs) not in self.filter_duration_band.value:
                    continue
            if wanted_ids and r["id"] not in wanted_ids:
                continue
            if text_query:
                tags = tags_by_id.get(r["id"], {})
                haystack = " ".join([r["note"] or "", *[v for vals in tags.values() for v in vals]]).lower()
                if text_query not in haystack:
                    continue
            out.append(r)
        return out
