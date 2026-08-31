"""
grid.py
=======
The Library grid (ticket 38): the shape vocabulary at a glance. A thumbnail
per motif exemplar, each with a scope summary naming the recordings and
channels its family appears in.

This surface reads the shape-first library tables written by ticket 36
(`motif_entry` / `motif_member` / `motif_edge`). Each card draws the
exemplar's own waveform — the detrended trace in millivolts, unnormalised —
and every card within one shape family shares a y-range, so relative depth
between members is visible rather than flattened by per-card autoscaling
(ticket 53). It deliberately does NOT use `build_motif_waveform_overlay`:
that builder z-normalises, and normalisation of amplitude destroys the
scaling-law evidence the figures exist to show (PIPELINE_PRD Part 2,
"Rendering rule for motif waveforms").

A group-by selector (ticket 42) reorganises the same set of cards under three
bases: shape (the entry's symbolic `sax_string`), cluster membership (each
entry is the exemplar of its own family, so each heads a cluster), or manual
tag (the `motif_entry_tags` vocabulary). Switching basis never adds or drops an
entry — it only changes how the cards are sectioned. The shared y-range is per
shape family and is fixed at construction, so switching basis never rescales a
card.

Filters (ticket 55) narrow the same set before grouping: morphology, purity,
spike train, source recording and channel, plus range filters on drop depth
and fall duration. Filters compose (AND across categories), and a filter that
matches nothing renders a sentence rather than an empty grid. Families can
also be distance-sorted through `sorted_member_ids_by_distance`, which reads
the edge distances the importer already persisted.

The grid is deliberately static at layout time. It is the "what is in the
library" surface, not the matching/search surface; those actions write rows and
the grid rebuilds on next app construction.
"""

import holoviews as hv
import numpy as np
import panel as pn

from Working.database import queries as q
from Working.database import runs as R
from Working.database.schema import ENTRY_SCALE_EVENT, ENTRY_SCALE_TRAIN
from Working.database.vocabulary import get_motif_entry_tags, list_terms
from UI.plots import SEED_MOTIF_COLOR, load_channel_mmap

_THUMB_HEIGHT = 120
_CARD_WIDTH = 260
_THUMB_VDIM = "amplitude_mv"  # distinct from "amplitude": see `_decimated_curve`
_Y_PAD_FRACTION = 0.12

# The grouping bases the selector offers, label -> value.
GROUPING_OPTIONS = {
    "Provenance": "provenance",
    "Shape family": "family",
    "Manual tag": "tag",
}

_UNTAGGED = "untagged"

# Shown in place of an empty grid when filters compose to nothing, because an
# empty grid and a broken grid look identical.
_NO_MATCH_MESSAGE = "*No entries match the current filters.*"


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
            name="Group by", options=GROUPING_OPTIONS, value="provenance",
        )
        self.group_by.param.watch(self._on_group_by, "value")
        self._build()
        self._build_filter_widgets()
        self._connect_filter_watches()
        self._filter_column = self._build_filter_column()
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
        return pn.Column(
            self.group_by,
            self._filter_column,
            self._sections,
            sizing_mode="stretch_width",
        )

    # ── Grouping ───────────────────────────────────────────────────────

    def _on_group_by(self, event):
        self.groups = self._group_entries()
        self._render_sections()

    def _render_sections(self):
        """Rebuild the section panes for the current `self.groups` in place,
        so the `pn.Column` already embedded by `layout()` picks up the new
        grouping without needing `layout()` to be called again.

        The `loading` flag is set for the duration. Panel's
        `loading_indicator` covers panes it can see recomputing, but a
        wholesale `Column.objects` assignment is invisible to it — from
        Panel's side a slow rebuild here is indistinguishable from a dead
        control, and the natural response to a dead control is to click
        again and queue a second rebuild. Cleared in a `finally`: a
        rebuild that raises must not leave the surface greyed out forever,
        which looks exactly like a hang.
        """
        self._sections.loading = True
        try:
            if not self.groups:
                # An empty grid and a broken grid look identical; say so.
                self._sections.objects = [pn.pane.Markdown(_NO_MATCH_MESSAGE)]
                return
            sections = []
            for title, entry_ids in self.groups:
                sections.append(pn.pane.Markdown(f"### {title}"))
                sections.append(pn.FlexBox(
                    *[self._card_by_entry[eid] for eid in entry_ids],
                    sizing_mode="stretch_width",
                ))
            self._sections.objects = sections
        finally:
            self._sections.loading = False

    def _group_entries(self):
        basis = self.group_by.value
        if basis == "provenance":
            return self._group_by_provenance()
        if basis == "family":
            return self._group_by_family()
        if basis == "tag":
            return self._group_by_tag()
        raise ValueError(f"Unknown grouping basis {basis!r}")

    def _group_by_provenance(self):
        """Group entries by the spike train their exemplar came from.

        A train-scale entry is its own provenance. An event-scale entry's
        provenance is the train-scale entry whose members include the
        exemplar's own span — every imported motif belongs to exactly one
        train, so this is a lookup, not a clustering. Entries without a
        train (e.g. hand-flagged entries from before the importer ran) fall
        back to their recording so they are never dropped.
        """
        by_train = {}
        by_recording = {}
        for entry in self._filtered_entries():
            train_id = self._provenance_train_id(entry)
            if train_id is not None:
                by_train.setdefault(train_id, []).append(entry["id"])
            else:
                by_recording.setdefault(entry["recording_id"], []).append(entry["id"])

        groups = []
        for train_id, ids in sorted(by_train.items(), key=lambda kv: self._provenance_title(kv[0])):
            groups.append((self._provenance_title(train_id), ids))
        for recording_id, ids in sorted(by_recording.items(), key=lambda kv: self._recording_title(kv[0])):
            groups.append((self._recording_title(recording_id), ids))
        return groups

    def _group_by_family(self):
        """Group entries by computed shape family.

        Each event-scale entry IS the exemplar of one computed family, so it
        heads one section. Train-scale entries have no shape family; they
        stay their own sections so both scales appear under either axis
        without intermixing.
        """
        return [
            (self._family_title(entry), [entry["id"]])
            for entry in self._filtered_entries()
        ]

    def _provenance_train_id(self, entry):
        """The train-scale entry id an entry belongs to, or None."""
        if entry["scale"] == ENTRY_SCALE_TRAIN:
            return entry["id"]
        return self._train_by_member_span.get(
            (entry["recording_id"], entry["start_idx"], entry["end_idx"]),
        )

    def _provenance_title(self, train_id):
        for entry in self.entries:
            if entry["id"] == train_id:
                return entry["label"] or f"Spike train {train_id}"
        return f"Spike train {train_id}"

    def _family_title(self, entry):
        if entry["scale"] == ENTRY_SCALE_TRAIN:
            return entry["label"] or f"Spike train {entry['id']}"
        return entry["label"] or f"Family {entry['id']}"

    def _recording_title(self, recording_id):
        recording = q.get_recording_by_id(self.conn, recording_id)
        if recording is None:
            return f"Recording {recording_id}"
        return f"{recording['source_file']} CH{recording['channel']:02d}"

    def _build_train_member_span_map(self):
        """{(recording_id, start_idx, end_idx): train_entry_id} for every
        motif belonging to a train-scale entry."""
        mapping = {}
        for entry in self.entries:
            if entry["scale"] != ENTRY_SCALE_TRAIN:
                continue
            for member in R.list_motif_members(self.conn, entry["id"]):
                mapping[
                    (member["recording_id"], member["start_idx"], member["end_idx"])
                ] = entry["id"]
        return mapping

    def _group_by_tag(self):
        """Group entries by manual tag. An entry with several tags appears
        under each of them — a tag is a heading, never a primary key."""
        tag_order = {}
        untagged = []
        for entry in self._filtered_entries():
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

    # ── Filters ────────────────────────────────────────────────────────

    def _build_entry_meta(self):
        """Per-entry metadata the filters read: source recording and channel,
        peak-to-peak depth, span duration, the provenance train id and the
        morphology/purity tags. Computed once at construction because the
        filter widgets and the filter predicate both need it."""
        meta = {}
        for entry in self.entries:
            recording = q.get_recording_by_id(self.conn, entry["recording_id"])
            if recording is not None:
                source_file = recording["source_file"]
                channel = recording["channel"]
                fs = float(recording["fs"] or 1.0)
            else:
                source_file = None
                channel = None
                fs = 1.0
            values = self._load_span(recording, entry) if recording is not None else np.array([])
            depth = float(values.max()) - float(values.min()) if values.size else 0.0
            fall_duration = (int(entry["end_idx"]) - int(entry["start_idx"])) / fs
            tags = get_motif_entry_tags(self.conn, entry["id"])
            meta[entry["id"]] = {
                "source_file": source_file,
                "channel": channel,
                "depth_mv": depth,
                "fall_duration_s": fall_duration,
                "train_id": self._provenance_train_id(entry),
                "element_tags": set(tags.get("element", [])),
                "quality_tags": set(tags.get("quality", [])),
            }
        return meta

    def _build_filter_widgets(self):
        """The seven filter controls. Multi-selects are OR-within-category and
        empty means unfiltered; the two range sliders default to their full
        span, which is also unfiltered."""
        element_terms = list_terms(self.conn, "element")
        quality_terms = list_terms(self.conn, "quality")
        self.morphology = pn.widgets.MultiSelect(
            name="Morphology",
            options={t["value"]: t["value"] for t in element_terms},
            size=4,
        )
        self.purity = pn.widgets.MultiSelect(
            name="Purity",
            options={t["value"]: t["value"] for t in quality_terms},
            size=4,
        )
        train_options = {}
        for entry in self.entries:
            if entry["scale"] == ENTRY_SCALE_TRAIN:
                title = entry["label"] or f"Spike train {entry['id']}"
                train_options[title] = entry["id"]
        self.spike_train = pn.widgets.MultiSelect(
            name="Spike train", options=train_options, size=4,
        )
        recording_options = {
            rec["source_file"]: rec["source_file"]
            for rec in q.list_recordings(self.conn)
        }
        self.recording = pn.widgets.MultiSelect(
            name="Recording", options=recording_options, size=4,
        )
        channel_options = {}
        for meta in self._entry_meta.values():
            if meta["channel"] is not None:
                channel_options[str(meta["channel"])] = meta["channel"]
        self.channel = pn.widgets.MultiSelect(
            name="Channel", options=channel_options, size=4,
        )
        depths = [meta["depth_mv"] for meta in self._entry_meta.values()]
        falls = [meta["fall_duration_s"] for meta in self._entry_meta.values()]
        self.depth_range = pn.widgets.RangeSlider(
            name="Drop depth (mV)",
            start=min(depths) - 1.0 if depths else 0.0,
            end=max(depths) + 1.0 if depths else 1.0,
            value=(min(depths) - 1.0 if depths else 0.0,
                   max(depths) + 1.0 if depths else 1.0),
        )
        self.fall_duration_range = pn.widgets.RangeSlider(
            name="Fall duration (s)",
            start=min(falls) - 1.0 if falls else 0.0,
            end=max(falls) + 1.0 if falls else 1.0,
            value=(min(falls) - 1.0 if falls else 0.0,
                   max(falls) + 1.0 if falls else 1.0),
        )

    def _connect_filter_watches(self):
        # Discrete controls apply at once: a MultiSelect change is one
        # event and waiting for anything would just feel broken.
        for widget in (
            self.morphology, self.purity, self.spike_train,
            self.recording, self.channel,
        ):
            widget.param.watch(self._on_filter_change, "value")

        # Continuous controls apply on RELEASE. `value` fires on every
        # intermediate position of a drag, and each one re-filters every
        # entry and rebuilds every card in the grid — dragging a handle
        # across its track queued dozens of full rebuilds and the surface
        # went away for seconds. `value_throttled` fires once, when the
        # handle is dropped. Pinned by tests/test_ui_responsiveness.py.
        for widget in (self.depth_range, self.fall_duration_range):
            widget.param.watch(self._on_filter_change, "value_throttled")

    def _build_filter_column(self):
        return pn.Column(
            pn.pane.Markdown("**Filters**"),
            pn.Row(
                self.morphology, self.purity, self.spike_train,
                self.recording, self.channel,
            ),
            pn.Row(self.depth_range, self.fall_duration_range),
            sizing_mode="stretch_width",
        )

    def _on_filter_change(self, event):
        self.groups = self._group_entries()
        self._render_sections()

    def _filtered_entries(self):
        """The entries that pass every active filter."""
        return [entry for entry in self.entries if self._entry_matches_filters(entry)]

    def _entry_matches_filters(self, entry):
        meta = self._entry_meta[entry["id"]]
        if self.morphology.value:
            if not (meta["element_tags"] & set(self.morphology.value)):
                return False
        if self.purity.value:
            if not (meta["quality_tags"] & set(self.purity.value)):
                return False
        if self.spike_train.value:
            if meta["train_id"] is None or meta["train_id"] not in set(self.spike_train.value):
                return False
        if self.recording.value:
            if meta["source_file"] is None or meta["source_file"] not in set(self.recording.value):
                return False
        if self.channel.value:
            if meta["channel"] is None or meta["channel"] not in set(self.channel.value):
                return False
        if self.depth_range.value is not None:
            lo, hi = self.depth_range.value
            if not (lo <= meta["depth_mv"] <= hi):
                return False
        if self.fall_duration_range.value is not None:
            lo, hi = self.fall_duration_range.value
            if not (lo <= meta["fall_duration_s"] <= hi):
                return False
        return True

    # ── Distance sort ──────────────────────────────────────────────────

    def sorted_member_ids_by_distance(self, entry_id):
        """Member ids of one family, ordered by their persisted edge distance
        to the exemplar (closest first).

        Reads the already-persisted `motif_edge` distance values — no distance
        is recomputed here. The exemplar's own member is not included.
        """
        entry = R.get_motif_entry(self.conn, entry_id)
        if entry is None:
            return []
        exemplar_key = (entry["recording_id"], entry["start_idx"], entry["end_idx"])
        exemplar_member_id = None
        for member in R.list_motif_members(self.conn, entry_id):
            if (member["recording_id"], member["start_idx"], member["end_idx"]) == exemplar_key:
                exemplar_member_id = member["id"]
                break
        if exemplar_member_id is None:
            return []
        distances = {}
        for edge in R.list_motif_edges(self.conn, entry_id):
            if edge["member_a_id"] == exemplar_member_id:
                other = edge["member_b_id"]
            elif edge["member_b_id"] == exemplar_member_id:
                other = edge["member_a_id"]
            else:
                continue
            distances[other] = edge["distance_value"]
        return sorted(distances, key=lambda mid: distances[mid])

    # ── Construction ───────────────────────────────────────────────────

    def _build(self):
        self.cards = []
        self.scope_panes = []
        self._card_by_entry = {}
        self.entries = R.list_motif_entries(self.conn)
        self._train_by_member_span = self._build_train_member_span_map()
        self._entry_meta = self._build_entry_meta()
        family_ranges = self._family_y_ranges()
        for entry in self.entries:
            card, scope_pane = self._build_card(entry, family_ranges)
            self.cards.append(card)
            self.scope_panes.append(scope_pane)
            self._card_by_entry[entry["id"]] = card

    def _build_card(self, entry, family_ranges):
        title = entry["label"] or f"Exemplar {entry['id']}"
        if entry["rating"]:
            title += f" (rating {entry['rating']})"

        recording = q.get_recording_by_id(self.conn, entry["recording_id"])
        if recording is None:
            thumb = pn.pane.Markdown("*recording missing*")
        else:
            thumb = self._thumbnail(
                entry, recording, family_ranges.get(self._family_key(entry)),
            )

        recording_ids = self._member_recording_ids(entry)
        scope_text = self._scope_summary(entry, recording_ids)
        scope_pane = pn.pane.Markdown(scope_text)

        badges = [self._scale_badge(entry)]
        if len(recording_ids) > 1:
            badges.append(pn.pane.Markdown("**Cross-recording**"))

        card = pn.Column(
            pn.pane.Markdown(f"**{title}**"),
            *badges,
            thumb,
            scope_pane,
            width=_CARD_WIDTH,
            styles={"border": "1px solid #ddd", "border-radius": "6px",
                    "padding": "8px"},
        )
        return card, scope_pane

    def _scale_badge(self, entry):
        """A visible train/event badge so the two scales do not intermix
        into one undifferentiated grid (T52/T54)."""
        label = {
            ENTRY_SCALE_TRAIN: "TRAIN-SCALE",
            ENTRY_SCALE_EVENT: "EVENT-SCALE",
        }.get(entry["scale"], "UNSCALED")
        return pn.pane.Markdown(f"**{label}**")

    def _member_recording_ids(self, entry):
        """Every recording a family touches: the exemplar's own recording
        plus every member's, deduplicated."""
        recording_ids = {entry["recording_id"]}
        recording_ids.update(
            member["recording_id"]
            for member in R.list_motif_members(self.conn, entry["id"])
        )
        return recording_ids

    # ── Family y-ranges (ticket 53) ────────────────────────────────────

    def _family_key(self, entry):
        """The shape family an entry belongs to — the basis the PRD's "same
        shape" definition is built on (`sax_string`).

        An entry with no `sax_string` (e.g. an imported entry, where each
        entry IS the exemplar of its own cluster/family) is its own family:
        falling back to the row id keeps one imported entry from borrowing
        another's y-range and flattening its depth."""
        return entry["sax_string"] or f"entry:{entry['id']}"

    def _family_y_ranges(self):
        """{family_key: (y0, y1)} — one y-range shared by every card in the
        family, computed over ALL members' actual millivolt values so relative
        depth between members is real rather than an artifact of per-card
        autoscaling. Families do not share a range with each other."""
        families = {}
        for entry in self.entries:
            families.setdefault(self._family_key(entry), []).append(entry)

        ranges = {}
        for key, entries in families.items():
            lo, hi = self._family_data_bounds(entries)
            pad = (hi - lo) * _Y_PAD_FRACTION or 1.0
            ranges[key] = (float(lo - pad), float(hi + pad))
        return ranges

    def _family_data_bounds(self, entries):
        """(min, max) across every member's span in the family, in the
        recording's native units (detrended millivolts)."""
        lo, hi = np.inf, -np.inf
        for entry in entries:
            recording = q.get_recording_by_id(self.conn, entry["recording_id"])
            if recording is None:
                continue
            values = self._load_span(recording, entry)
            if values.size == 0:
                continue
            lo = min(lo, float(values.min()))
            hi = max(hi, float(values.max()))
        if lo > hi:
            return (0.0, 1.0)
        return (lo, hi)

    @staticmethod
    def _load_span(recording, entry):
        """The entry's span sliced out of its recording, in millivolts."""
        x = load_channel_mmap(recording["npy_path"])
        start = int(entry["start_idx"])
        end = int(entry["end_idx"])
        return np.asarray(x[start:end], dtype=np.float64)

    def _thumbnail(self, entry, recording, y_range):
        values = self._load_span(recording, entry)
        if values.size == 0:
            return pn.pane.Markdown("*no signal*")
        fs = float(recording["fs"] or 1.0)
        t = np.arange(values.size) / fs
        curve = hv.Curve((t, values), "time_s", _THUMB_VDIM).opts(
            color=SEED_MOTIF_COLOR, line_width=1, height=_THUMB_HEIGHT,
            responsive=True, framewise=True, axiswise=True, ylim=y_range,
            xlabel="time (s)", ylabel="amplitude (mV)",
        )
        return pn.pane.HoloViews(
            curve, sizing_mode="stretch_width", height=_THUMB_HEIGHT,
        )

    def _scope_summary(self, entry, recording_ids):
        scopes = []
        for recording_id in sorted(recording_ids):
            recording = q.get_recording_by_id(self.conn, recording_id)
            if recording is None:
                continue
            scopes.append(f"{recording['source_file']} CH{recording['channel']:02d}")

        if not scopes:
            return "*Scope: no recordings.*"
        return "**Scope:** " + "; ".join(scopes)
