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
"""

import numpy as np
import panel as pn

from Working.config import MOTIF_BOTTOM_HEIGHT
from Working.database import queries as q
from Working.database import runs as R
from Working.distances import resample_to_length
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

        self._entry_id = None
        self._entries = R.list_motif_entries(self.conn)

        self._build_entry_options()
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
        members = self._gather_members(entry)
        edges_by_member = self._edges_by_member(entry, members)

        self.member_pane.object = self._format_members(members, edges_by_member)
        self.edge_pane.object = self._format_edges(members, edges_by_member)
        self.overlay_pane.object = self._build_overlay(members, edges_by_member)

    def _gather_members(self, entry):
        """The exemplar first, then every stored member span.

        The exemplar itself may or may not have a `motif_member` row yet (a
        freshly promoted entry has none), so it is always represented once
        from the `motif_entry` row; any stored row for the same span is only
        used to recover its member id.
        """
        exemplar = {
            "id": None,
            "entry_id": entry["id"],
            "recording_id": entry["recording_id"],
            "start_idx": entry["start_idx"],
            "end_idx": entry["end_idx"],
            "is_seed": True,
        }
        members = [exemplar]
        exemplar_key = (
            entry["recording_id"], entry["start_idx"], entry["end_idx"],
        )
        seen = {exemplar_key}

        for row in R.list_motif_members(self.conn, entry["id"]):
            key = (row["recording_id"], row["start_idx"], row["end_idx"])
            if key in seen:
                if key == exemplar_key and exemplar["id"] is None:
                    exemplar["id"] = row["id"]
                continue
            seen.add(key)
            member = dict(row)
            member["is_seed"] = False
            members.append(member)

        return members

    def _edges_by_member(self, entry, members):
        """Map each non-exemplar member id to the edge that connects it to the
        exemplar. `match_span_to_entry` stores (exemplar, candidate) oriented
        edges, so the candidate is the endpoint that is not the exemplar."""
        exemplar_member_id = members[0]["id"]
        member_ids = {m["id"] for m in members if m["id"] is not None}
        edges_by_member = {}

        for edge in R.list_motif_edges(self.conn, entry["id"]):
            if exemplar_member_id is not None:
                if edge["member_a_id"] == exemplar_member_id:
                    candidate_id = edge["member_b_id"]
                elif edge["member_b_id"] == exemplar_member_id:
                    candidate_id = edge["member_a_id"]
                else:
                    candidate_id = edge["member_a_id"]
            else:
                candidate_id = edge["member_a_id"]

            if candidate_id in member_ids:
                edges_by_member.setdefault(candidate_id, edge)

        return edges_by_member

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
