"""
detail.py
=========
The Library entry detail (ticket 39): one motif family inspectable as a set.
Selecting an exemplar shows the exemplar's own span, every span matched to it,
all of those spans overlaid on a shared relative-time axis, and the edges that
put the members there — distance function, threshold and distance value per
member.

The overlay is `UI.plots.build_motif_waveform_overlay` — called, not copied —
so the detail view and the motif browser/review surface show the same shape
(`axiswise=True`, `zscore` vdim, z-normalised). The family may span recordings
and channels; each member's snippet is resampled to the exemplar's length
before being concatenated and handed to that builder as one group.

The entry detail also hosts the "search at other scales" action (ticket 40):
searching for the exemplar's shape across a configurable range of durations,
under both the scale-invariant distance and the native-length control, with
their recall shown side by side. And the export action (ticket 46): the family
leaves the tool as a folder containing a manifest, a spans CSV and copied
plots, via `Working.export.export_library_entry`.
"""

import numpy as np
import panel as pn

from Working.config import MOTIF_BOTTOM_HEIGHT
from Working.database import queries as q
from Working.database import runs as R
from Working.distances import (
    DISTANCE_NATIVE_LENGTH, DISTANCE_SCALE_INVARIANT, resample_to_length,
)
from Working.export import (
    entry_edges_by_member, export_library_entry, gather_entry_members,
)
from Working.library import search_entry_across_durations
from Working.recipes import short_hash
from UI.plots import build_motif_waveform_overlay, load_channel_mmap


class EntryDetail:
    """The "entry detail" surface for the Library workspace.

    `app` only needs to expose `conn` — the same minimal contract the Library
    grid and the Review surface use for their database reads.
    """

    def __init__(self, app):
        self.app = app
        self.conn = app.conn

        self.entry_select = pn.widgets.Select(name="Exemplar", options={})
        self.overlay_pane = pn.pane.HoloViews(
            sizing_mode="stretch_width", height=MOTIF_BOTTOM_HEIGHT,
        )
        self.member_pane = pn.pane.Markdown("*No exemplar selected.*")
        self.edge_pane = pn.pane.Markdown("*No edges yet.*")

        # Search-at-other-scales action (ticket 40).
        self.search_recording = pn.widgets.Select(
            name="Search recording", options={},
        )
        self.search_min_duration = pn.widgets.IntInput(
            name="Min duration (samples)", value=10, step=1,
        )
        self.search_max_duration = pn.widgets.IntInput(
            name="Max duration (samples)", value=200, step=1,
        )
        self.search_step = pn.widgets.IntInput(
            name="Duration step (samples)", value=10, step=1,
        )
        self.search_threshold = pn.widgets.FloatInput(
            name="Threshold", value=0.1, step=0.05,
        )
        self.search_run_button = pn.widgets.Button(
            name="Search at other scales", button_type="primary",
        )
        self.search_results_pane = pn.pane.Markdown("*Run a search to see results.*")
        self.last_search_results = None
        self.search_run_button.on_click(self._on_search_run)

        # Export action (ticket 46).
        self.export_out_dir = pn.widgets.TextInput(
            name="Output directory", value="exports",
        )
        self.export_button = pn.widgets.Button(
            name="Export entry", button_type="primary",
        )
        self.export_status = pn.pane.Markdown("")
        self.export_button.on_click(self._on_export)

        self._entry_id = None
        self._entries = R.list_motif_entries(self.conn)

        self._build_entry_options()
        self._build_search_recording_options()
        self.entry_select.param.watch(self._on_select_entry, "value")
        self._render_empty()
        if self._entries:
            self.entry_select.value = self._entries[0]["id"]

    # ── Layout ─────────────────────────────────────────────────────────

    def layout(self):
        return pn.Column(
            pn.pane.Markdown("### Entry detail"),
            self.entry_select,
            pn.pane.Markdown(
                "*All members overlaid, z-normalised on a shared relative-time "
                "axis.*"
            ),
            self.overlay_pane,
            pn.pane.Markdown("**Members**"),
            self.member_pane,
            pn.pane.Markdown("**Edges**"),
            self.edge_pane,
            pn.pane.Markdown("### Search at other scales"),
            pn.pane.Markdown(
                "*Search for the exemplar's shape at durations it was never "
                "defined at, under both the scale-invariant distance and the "
                "native-length control.*"
            ),
            self.search_recording,
            pn.Row(self.search_min_duration, self.search_max_duration,
                   self.search_step),
            self.search_threshold,
            self.search_run_button,
            self.search_results_pane,
            pn.pane.Markdown("### Export entry"),
            pn.pane.Markdown(
                "*Exports the family as a folder containing a manifest, a "
                "spans table as CSV, and copies of its plots.*"
            ),
            self.export_out_dir,
            self.export_button,
            self.export_status,
            sizing_mode="stretch_width",
        )

    # ── Selection ───────────────────────────────────────────────────────

    def select_entry(self, entry_id):
        """Show `entry_id` in the detail surface.

        The actual render happens in the value watcher so a user picking an
        exemplar from the select widget follows the same path as a
        programmatic caller.
        """
        self.entry_select.value = entry_id

    def _on_select_entry(self, event):
        if event.new is None:
            self._render_empty()
        else:
            self._render_entry(event.new)

    # ── Construction helpers ────────────────────────────────────────────

    def _build_entry_options(self):
        options = {}
        for entry in self._entries:
            recording = q.get_recording_by_id(self.conn, entry["recording_id"])
            label = entry["label"] or f"Exemplar {entry['id']}"
            if recording is not None:
                label += (
                    f" — {recording['source_file']} "
                    f"CH{recording['channel']:02d} "
                    f"[{entry['start_idx']}, {entry['end_idx']})"
                )
            options[label] = entry["id"]
        self.entry_select.options = options

    def _build_search_recording_options(self):
        options = {}
        for recording in q.list_recordings(self.conn):
            label = f"{recording['source_file']} CH{recording['channel']:02d}"
            options[label] = recording["id"]
        self.search_recording.options = options

    # ── Search at other scales ──────────────────────────────────────────

    def _on_search_run(self, event):
        """Run the search-at-other-scales action for the selected exemplar.

        Runs the same search under `DISTANCE_SCALE_INVARIANT` and under
        `DISTANCE_NATIVE_LENGTH` (the unnormalised control) so their recall
        is comparable side by side, writes the resulting members/edges, and
        renders a summary table.
        """
        if self._entry_id is None:
            self.search_results_pane.object = "*Select an exemplar first.*"
            return
        if not self.search_recording.options:
            self.search_results_pane.object = "*No recordings to search.*"
            return

        recording_id = self.search_recording.value
        if recording_id is None:
            recording_id = next(iter(self.search_recording.options.values()))

        min_dur = int(self.search_min_duration.value)
        max_dur = int(self.search_max_duration.value)
        step = int(self.search_step.value)
        threshold = float(self.search_threshold.value)

        if step < 1 or max_dur < min_dur or min_dur < 1:
            self.search_results_pane.object = "*Invalid duration range.*"
            return

        durations = list(range(min_dur, max_dur + 1, step))
        entry = R.get_motif_entry(self.conn, self._entry_id)
        entry_rec = q.get_recording_by_id(self.conn, entry["recording_id"])

        results = {}
        for distance_function in (DISTANCE_SCALE_INVARIANT, DISTANCE_NATIVE_LENGTH):
            search_recipe = {
                "action": "search_at_other_scales",
                "entry": {
                    "source_file": entry_rec["source_file"] if entry_rec else None,
                    "channel": entry_rec["channel"] if entry_rec else None,
                    "start_idx": entry["start_idx"],
                    "end_idx": entry["end_idx"],
                },
                "recording_id": recording_id,
                "durations": durations,
                "threshold": threshold,
                "distance_function": distance_function,
            }
            h = short_hash(search_recipe)
            results[distance_function] = search_entry_across_durations(
                self.conn, self._entry_id, recording_id,
                durations=durations,
                threshold=threshold, recipe_hash=h,
                distance_function=distance_function,
            )

        self.last_search_results = results
        self.search_results_pane.object = self._format_search_results(
            entry, results, durations,
        )

    def _format_search_results(self, entry, results, durations):
        entry_rec = q.get_recording_by_id(self.conn, entry["recording_id"])
        entry_label = entry["label"] or f"Exemplar {entry['id']}"
        if entry_rec is not None:
            entry_label += (
                f" — {entry_rec['source_file']} CH{entry_rec['channel']:02d} "
                f"[{entry['start_idx']}, {entry['end_idx']})"
            )

        target = results[DISTANCE_SCALE_INVARIANT]["recording_id"]
        target_rec = q.get_recording_by_id(self.conn, target)
        if target_rec is not None:
            target_label = (
                f"{target_rec['source_file']} CH{target_rec['channel']:02d}"
            )
        else:
            target_label = f"recording {target}"

        step_text = "—"
        if len(durations) > 1:
            step_text = str(durations[1] - durations[0])

        lines = [
            f"**Search at other scales** — {entry_label}",
            f"Target: {target_label}",
            f"Durations: {durations[0]}–{durations[-1]} step {step_text}",
            "",
            "| distance_function | matches | matched durations |",
            "|---|---|---|",
        ]
        for distance_function, result in results.items():
            matched_durations = sorted({r["duration"] for r in result["matches"]})
            dur_text = (
                ", ".join(str(d) for d in matched_durations)
                if matched_durations else "—"
            )
            lines.append(
                f"| {distance_function} | {result['recall']} | {dur_text} |"
            )
        return "\n".join(lines)

    # ── Export ────────────────────────────────────────────────────────────────

    def _on_export(self, _event=None):
        """Export the selected entry to the requested directory.

        The headless work lives in `Working.export.export_library_entry`; this
        handler only reads the widget values and reports the outcome.
        """
        if self._entry_id is None:
            self.export_status.object = "*Select an exemplar first.*"
            return
        out_dir = self.export_out_dir.value or "exports"
        try:
            result = export_library_entry(self.conn, self._entry_id, out_dir)
        except Exception as e:
            self.export_status.object = f"**Export failed:** {e}"
            return
        self.export_status.object = (
            f"**Exported entry {result['entry_id']} to `{result['out_dir']}`.**"
        )

    def _render_empty(self):
        self._entry_id = None
        self.overlay_pane.object = build_motif_waveform_overlay(
            None, np.array([]), 0, 1.0,
        )
        self.member_pane.object = "*No exemplar selected.*"
        self.edge_pane.object = "*No edges yet.*"

    def _render_entry(self, entry_id):
        entry = R.get_motif_entry(self.conn, entry_id)
        if entry is None:
            self._render_empty()
            return

        self._entry_id = entry_id

        # Default the search target to the exemplar's own recording so the
        # action's first run is the natural "does this recur at other scales
        # in the same recording" question.
        if self.search_recording.options:
            entry_rec_id = entry["recording_id"]
            if entry_rec_id in self.search_recording.options.values():
                self.search_recording.value = entry_rec_id

        members = self._gather_members(entry)
        edges_by_member = self._edges_by_member(entry, members)

        self.member_pane.object = self._format_members(members, edges_by_member)
        self.edge_pane.object = self._format_edges(members, edges_by_member)
        self.overlay_pane.object = self._build_overlay(members, edges_by_member)

    def _gather_members(self, entry):
        """The exemplar first, then every stored member span.

        Shared with the exporter (`Working.export.gather_entry_members`) so
        the detail view and the export report exactly the same family.
        """
        return gather_entry_members(self.conn, entry)

    def _edges_by_member(self, entry, members):
        """Map each non-exemplar member id to the edge that connects it to the
        exemplar. Shared with the exporter."""
        return entry_edges_by_member(self.conn, entry, members)

    # ── Text panes ──────────────────────────────────────────────────────

    @staticmethod
    def _member_label(recording, member):
        if recording is None:
            return f"recording {member['recording_id']}"
        return f"{recording['source_file']} CH{recording['channel']:02d}"

    def _format_members(self, members, edges_by_member):
        lines = [f"**Members ({len(members)})**"]
        for index, member in enumerate(members):
            recording = q.get_recording_by_id(self.conn, member["recording_id"])
            label = self._member_label(recording, member)
            span = f"[{member['start_idx']}, {member['end_idx']})"

            if index == 0:
                lines.append(f"- **seed** {label} {span}")
                continue

            edge = edges_by_member.get(member["id"])
            line = f"- {label} {span}"
            if edge is not None:
                line += (
                    f" — {edge['distance_function']} "
                    f"d={edge['distance_value']:.6g} "
                    f"thr={edge['threshold']:.6g}"
                )
            lines.append(line)
        return "\n".join(lines)

    def _format_edges(self, members, edges_by_member):
        rows = [
            "| member | distance_function | threshold | distance_value |",
            "|---|---|---|---|",
        ]
        for member in members[1:]:
            recording = q.get_recording_by_id(self.conn, member["recording_id"])
            label = self._member_label(recording, member)
            span = f"[{member['start_idx']}, {member['end_idx']})"
            edge = edges_by_member.get(member["id"])
            if edge is None:
                rows.append(f"| {label} {span} | — | — | — |")
            else:
                rows.append(
                    f"| {label} {span} "
                    f"| {edge['distance_function']} "
                    f"| {edge['threshold']:.6g} "
                    f"| {edge['distance_value']:.6g} |"
                )
        if len(rows) == 2:
            return "*No edges yet.*"
        return "\n".join(rows)

    # ── Overlay ─────────────────────────────────────────────────────────

    def _build_overlay(self, members, edges_by_member):
        seed = members[0]
        m = int(seed["end_idx"]) - int(seed["start_idx"])
        if m < 1:
            return build_motif_waveform_overlay(None, np.array([]), 0, 1.0)

        seed_recording = q.get_recording_by_id(self.conn, seed["recording_id"])
        fs = float(seed_recording["fs"]) if seed_recording is not None else 1.0

        snippets = []
        neighbour_distances = []
        for index, member in enumerate(members):
            recording = q.get_recording_by_id(self.conn, member["recording_id"])
            if recording is None:
                if index == 0:
                    return build_motif_waveform_overlay(
                        None, np.array([]), 0, fs,
                    )
                continue

            snippet = self._load_resampled_snippet(recording, member, m)
            if snippet is None:
                if index == 0:
                    return build_motif_waveform_overlay(
                        None, np.array([]), 0, fs,
                    )
                continue

            snippets.append(snippet)
            if index > 0:
                edge = edges_by_member.get(member["id"])
                neighbour_distances.append(
                    float(edge["distance_value"]) if edge is not None else 0.0
                )

        if not snippets:
            return build_motif_waveform_overlay(None, np.array([]), 0, fs)

        x_cat = snippets[0] if len(snippets) == 1 else np.concatenate(snippets)
        neighbours = [
            (k * m, distance)
            for k, distance in enumerate(neighbour_distances, start=1)
        ]
        group = {"seed_idx": 0, "neighbours": neighbours}
        return build_motif_waveform_overlay(group, x_cat, m, fs)

    @staticmethod
    def _load_resampled_snippet(recording, member, m):
        try:
            full = load_channel_mmap(recording["npy_path"])
            start = int(member["start_idx"])
            end = int(member["end_idx"])
            snippet = np.asarray(full[start:end], dtype=np.float64)
        except (OSError, ValueError, IndexError):
            return None
        if len(snippet) == 0:
            return None
        if len(snippet) != m:
            snippet = resample_to_length(snippet, m)
        return snippet
