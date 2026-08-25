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

A group-by selector (ticket 42) reorganises the same set of cards under three
bases: shape (the entry's symbolic `sax_string`), cluster membership (each
entry is the exemplar of its own family, so each heads a cluster), or manual
tag (the `motif_entry_tags` vocabulary). Switching basis never adds or drops an
entry — it only changes how the cards are sectioned.

The grid is deliberately static at layout time. It is the "what is in the
library" surface, not the matching/search surface; those actions write rows and
the grid rebuilds on next app construction.
"""

import panel as pn

from Working.database import queries as q
from Working.database import runs as R
from Working.database.vocabulary import get_motif_entry_tags
from UI.plots import build_motif_waveform_overlay, load_channel_mmap

_THUMB_HEIGHT = 120
_CARD_WIDTH = 260

# The grouping bases the selector offers, label -> value.
GROUPING_OPTIONS = {
    "Shape": "shape",
    "Cluster membership": "cluster",
    "Manual tag": "tag",
}

_UNCLASSIFIED = "unclassified"
_UNTAGGED = "untagged"


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
        self._card_by_entry = {}
        self.group_by = pn.widgets.Select(
            name="Group by", options=GROUPING_OPTIONS, value="shape",
        )
        self.group_by.param.watch(self._on_group_by, "value")
        self._build()
        self.groups = self._group_entries()
        self._sections = pn.Column(sizing_mode="stretch_width")
        self._render_sections()

    # ── Layout ─────────────────────────────────────────────────────────

    def layout(self):
        if not self.cards:
            return pn.Column(
                self.group_by,
                pn.pane.Markdown(
                    "### Library\n\n"
                    "*No exemplars yet. Save a motif from the motif browser or "
                    "adjudicate and promote a candidate to populate the library.*"
                ),
                sizing_mode="stretch_width",
            )
        return pn.Column(self.group_by, self._sections, sizing_mode="stretch_width")

    # ── Grouping ───────────────────────────────────────────────────────

    def _on_group_by(self, event):
        self.groups = self._group_entries()
        self._render_sections()

    def _render_sections(self):
        """Rebuild the section panes for the current `self.groups` in place,
        so the `pn.Column` already embedded by `layout()` picks up the new
        grouping without needing `layout()` to be called again."""
        sections = []
        for title, entry_ids in self.groups:
            sections.append(pn.pane.Markdown(f"### {title}"))
            sections.append(pn.FlexBox(
                *[self._card_by_entry[eid] for eid in entry_ids],
                sizing_mode="stretch_width",
            ))
        self._sections.objects = sections

    def _group_entries(self):
        basis = self.group_by.value
        if basis == "shape":
            return self._group_by_shape()
        if basis == "cluster":
            return self._group_by_cluster()
        if basis == "tag":
            return self._group_by_tag()
        raise ValueError(f"Unknown grouping basis {basis!r}")

    def _group_by_shape(self):
        """Group entries by their symbolic shape (`sax_string`)."""
        order = {}
        for entry in self.entries:
            key = entry["sax_string"] or _UNCLASSIFIED
            order.setdefault(key, []).append(entry["id"])
        return [(key, ids) for key, ids in sorted(order.items())]

    def _group_by_cluster(self):
        """Group entries by family: the shape-first library's clusters *are*
        the motif families, so each entry heads its own cluster."""
        return [
            (entry["label"] or f"Exemplar {entry['id']}", [entry["id"]])
            for entry in self.entries
        ]

    def _group_by_tag(self):
        """Group entries by manual tag. An entry with several tags appears
        under each of them — a tag is a heading, never a primary key."""
        tag_order = {}
        untagged = []
        for entry in self.entries:
            tags = get_motif_entry_tags(self.conn, entry["id"])
            values = sorted({val for vals in tags.values() for val in vals})
            if not values:
                untagged.append(entry["id"])
                continue
            for value in values:
                tag_order.setdefault(value, []).append(entry["id"])
        groups = [(tag, ids) for tag, ids in sorted(tag_order.items())]
        if untagged:
            groups.append((_UNTAGGED, untagged))
        return groups

    # ── Construction ───────────────────────────────────────────────────

    def _build(self):
        self.cards = []
        self.scope_panes = []
        self._card_by_entry = {}
        self.entries = R.list_motif_entries(self.conn)
        for entry in self.entries:
            card, scope_pane = self._build_card(entry)
            self.cards.append(card)
            self.scope_panes.append(scope_pane)
            self._card_by_entry[entry["id"]] = card

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
