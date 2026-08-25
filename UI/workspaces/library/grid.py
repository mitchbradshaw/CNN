"""
grid.py
=======
The Library grid (ticket 38): the shape vocabulary at a glance. A thumbnail
per motif exemplar, each with a scope summary naming the recordings and
channels its family appears in.

This surface reads the shape-first library tables written by ticket 36
(`motif_entry` / `motif_member` / `motif_edge`). It renders the exemplar's own
waveform with the same `build_motif_waveform_overlay` the motif browser uses —
called, not copied — so a thumbnail and the detail view show the same shape.

The grid is deliberately static at layout time. It is the "what is in the
library" surface, not the matching/search surface; those actions write rows and
the grid rebuilds on next app construction.
"""

import panel as pn

from Working.database import queries as q
from Working.database import runs as R
from UI.plots import build_motif_waveform_overlay, load_channel_mmap

_THUMB_HEIGHT = 120
_CARD_WIDTH = 260


class LibraryGrid:
    """A thumbnail grid of motif exemplars with scope summaries.

    `app` only needs to expose `conn` — the same minimal contract the Review
    surface and `MotifBrowser` already use for their database reads.
    """

    def __init__(self, app):
        self.app = app
        self.conn = app.conn
        self.cards = []
        self.scope_panes = []
        self._build()

    # ── Layout ─────────────────────────────────────────────────────────

    def layout(self):
        if not self.cards:
            return pn.pane.Markdown(
                "### Library\n\n"
                "*No exemplars yet. Save a motif from the motif browser or "
                "adjudicate and promote a candidate to populate the library.*"
            )
        return pn.FlexBox(*self.cards, sizing_mode="stretch_width")

    # ── Construction ───────────────────────────────────────────────────

    def _build(self):
        self.cards = []
        self.scope_panes = []
        for entry in R.list_motif_entries(self.conn):
            card, scope_pane = self._build_card(entry)
            self.cards.append(card)
            self.scope_panes.append(scope_pane)

    def _build_card(self, entry):
        title = entry["label"] or f"Exemplar {entry['id']}"
        if entry["rating"]:
            title += f" (rating {entry['rating']})"

        recording = q.get_recording_by_id(self.conn, entry["recording_id"])
        if recording is None:
            thumb = pn.pane.Markdown("*recording missing*")
        else:
            thumb = self._thumbnail(entry, recording)

        scope_text = self._scope_summary(entry)
        scope_pane = pn.pane.Markdown(scope_text)
        card = pn.Column(
            pn.pane.Markdown(f"**{title}**"),
            thumb,
            scope_pane,
            width=_CARD_WIDTH,
            styles={"border": "1px solid #ddd", "border-radius": "6px",
                    "padding": "8px"},
        )
        return card, scope_pane

    def _thumbnail(self, entry, recording):
        x = load_channel_mmap(recording["npy_path"])
        m = int(entry["end_idx"]) - int(entry["start_idx"])
        group = {"seed_idx": int(entry["start_idx"]), "neighbours": []}
        overlay = build_motif_waveform_overlay(
            group, x, m, recording["fs"], show_envelope=False,
        )
        return pn.pane.HoloViews(
            overlay, sizing_mode="stretch_width", height=_THUMB_HEIGHT,
        )

    def _scope_summary(self, entry):
        recording_ids = {entry["recording_id"]}
        recording_ids.update(
            member["recording_id"]
            for member in R.list_motif_members(self.conn, entry["id"])
        )

        scopes = []
        for recording_id in sorted(recording_ids):
            recording = q.get_recording_by_id(self.conn, recording_id)
            if recording is None:
                continue
            scopes.append(f"{recording['source_file']} CH{recording['channel']:02d}")

        if not scopes:
            return "*Scope: no recordings.*"
        return "**Scope:** " + "; ".join(scopes)
