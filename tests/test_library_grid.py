"""
test_library_grid.py
=====================
Headless construction tests for `UI/workspaces/library/grid.py` grouping
selectors (ticket 42): the Library grid must offer a selector that groups the
same set of motif entries by shape, by cluster membership, or by manual tag.

The acceptance criteria under test:

1. The grid exposes a group-by selector whose bases are shape, cluster
   membership and manual tag.
2. Grouping by shape groups entries that share a symbolic shape
   (`sax_string`) under one heading.
3. Grouping by cluster membership lists every entry as the exemplar of its
   own family/cluster — the shape-first library's clusters *are* the motif
   families, so each entry heads one group.
4. Grouping by tag groups entries under each tag value, and a tag is never
   treated as a primary key: an entry carrying two tags appears under both
   tag headings rather than being collapsed onto one.
5. Whatever the basis, the same set of entries appears — only the grouping
   changes.

Headless: a scratch `tempfile` directory holds the .npy files the recordings
point at, and the database is an in-memory sqlite file — never the real
annotations database.
"""

import inspect
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import panel as pn
pn.extension("tabulator")
import holoviews as hv
hv.extension("bokeh")

from Working.database.schema import ENTRY_SCALE_EVENT, ENTRY_SCALE_TRAIN, init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.database import vocabulary as v
from Working.distances import DISTANCE_SCALE_INVARIANT
from UI.workspaces.library.grid import LibraryGrid


# ── fixture helpers ─────────────────────────────────────────────────────────

def _group_titles_from_layout(layout):
    """Walk a `LibraryGrid.layout()` panel tree and collect the group
    heading text (the `### <title>` markdown panes), recursing into nested
    Column/FlexBox containers. Used to assert on what the grid actually
    renders, not just on the `grid.groups` data structure."""
    titles = []
    for obj in layout:
        if isinstance(obj, pn.pane.Markdown) and obj.object.startswith("### "):
            titles.append(obj.object[len("### "):])
        elif hasattr(obj, "__iter__"):
            titles.extend(_group_titles_from_layout(obj))
    return titles


def _all_markdown_texts(obj):
    """Every markdown string rendered anywhere under a panel tree, for
    assertions on sentences the grid shows (not just `### ` headings)."""
    texts = []
    if isinstance(obj, pn.pane.Markdown):
        texts.append(obj.object or "")
    if hasattr(obj, "__iter__"):
        for child in obj:
            texts.extend(_all_markdown_texts(child))
    return texts


def _write_recording(conn, npy_dir, source_file, channel, data, fs=1.0):
    """Write `data` to a scratch .npy file and insert a recording row that
    points at it. Returns the recording id."""
    npy_path = os.path.join(npy_dir, f"{source_file}_ch{channel}.npy")
    np.save(npy_path, np.asarray(data, dtype=float))
    return q.insert_recording(conn, source_file, channel, fs, len(data), 0, npy_path)


def _element_ylim(element):
    """The ylim stored on a HoloViews element or Overlay, or None."""
    if isinstance(element, hv.Overlay):
        limits = [_element_ylim(el) for el in element]
        limits = [l for l in limits if l is not None]
        if not limits:
            return None
        assert len({tuple(l) for l in limits}) == 1, \
            f"overlay leaves disagree about ylim: {limits}"
        return tuple(limits[0])
    if hasattr(element, "opts"):
        ylim = element.opts.get("plot").kwargs.get("ylim")
        return tuple(ylim) if ylim is not None else None
    return None


def _card_ylim(card):
    """The ylim of a LibraryGrid card's HoloViews thumbnail."""
    for obj in card:
        if isinstance(obj, pn.pane.HoloViews):
            ylim = _element_ylim(obj.object)
            if ylim is not None:
                return ylim
    raise AssertionError(f"no HoloViews thumbnail with a ylim in card: {card}")


class _FakeLibraryApp:
    """The only app surface `LibraryGrid` is allowed to read."""

    def __init__(self, conn):
        self.conn = conn


def _make_three_entry_library(npy_dir):
    """A scratch in-memory library with three entries on one recording:
    - e1 and e2 share the symbolic shape "aaa".
    - e3 has the symbolic shape "bbb".
    - e1 carries two element tags (sharkfin, ridge); e2 carries one
      (sharkfin); e3 is untagged.

    The recording holds a *detrended* signal in millivolts: three sine
    bursts of different amplitudes, all centred on zero (baseline removed —
    the trace detection ran on). e1 (10 mV), e2 (5 mV) and e3 (2 mV) sit on
    those bursts, so their thumbnail y-ranges can be asserted against real
    millivolt amplitudes.

    Returns (conn, (e1, e2, e3)).
    """
    conn = init_db(":memory:")
    v.seed_vocabulary(conn)
    sig = np.zeros(200)
    sig[10:50] = 10.0 * np.sin(2 * np.pi * np.arange(40) / 40)
    sig[60:100] = 5.0 * np.sin(2 * np.pi * np.arange(40) / 40)
    sig[110:150] = 2.0 * np.sin(2 * np.pi * np.arange(40) / 40)
    rec = _write_recording(conn, npy_dir, "A.mat", 0, sig)
    e1 = R.insert_motif_entry(
        conn, rec, 10, 50, label="sine-a", sax_string="aaa",
        created_at="2026-01-03T00:00:00+00:00",
    )
    e2 = R.insert_motif_entry(
        conn, rec, 60, 100, label="sine-b", sax_string="aaa",
        created_at="2026-01-02T00:00:00+00:00",
    )
    e3 = R.insert_motif_entry(
        conn, rec, 110, 150, label="sine-c", sax_string="bbb",
        created_at="2026-01-01T00:00:00+00:00",
    )
    v.set_motif_entry_tags(conn, e1, "element", ["sharkfin", "ridge"])
    v.set_motif_entry_tags(conn, e2, "element", ["sharkfin"])
    return conn, (e1, e2, e3)


def _set_entry_scale(conn, entry_id, scale):
    """Stamp an entry with one of the two T52 scales."""
    conn.execute(
        "UPDATE motif_entry SET scale = ? WHERE id = ?", (scale, entry_id),
    )
    conn.commit()


def _make_two_axis_library(npy_dir):
    """A scratch library with the two T54 axes represented in the data.

    Two spike trains (train-scale entries) live on two different recordings.
    Two event-scale family entries live one on each recording. The first
    family spans both recordings through a second `motif_member`, so its card
    is cross-recording. Each event entry's own span is also a member of its
    spike-train entry, which is how provenance is resolved.

    Returns (conn, (train_a, train_b, family_a, family_b)).
    """
    conn = init_db(":memory:")
    v.seed_vocabulary(conn)
    sig = np.zeros(200)
    rec_a = _write_recording(conn, npy_dir, "A.mat", 0, sig)
    rec_b = _write_recording(conn, npy_dir, "B.mat", 1, sig)

    train_a = R.insert_motif_entry(
        conn, rec_a, 0, 200, label="spike train id001",
    )
    _set_entry_scale(conn, train_a, ENTRY_SCALE_TRAIN)
    train_b = R.insert_motif_entry(
        conn, rec_b, 0, 200, label="spike train id002",
    )
    _set_entry_scale(conn, train_b, ENTRY_SCALE_TRAIN)

    family_a = R.insert_motif_entry(
        conn, rec_a, 10, 50, label="drop family 0",
    )
    _set_entry_scale(conn, family_a, ENTRY_SCALE_EVENT)
    family_b = R.insert_motif_entry(
        conn, rec_b, 110, 150, label="drop family 1",
    )
    _set_entry_scale(conn, family_b, ENTRY_SCALE_EVENT)

    # Every event's span belongs to exactly one train.
    R.get_or_create_motif_member(conn, train_a, rec_a, 10, 50)
    R.get_or_create_motif_member(conn, train_b, rec_b, 110, 150)

    # Family A spans both recordings; family B stays on its own recording.
    R.get_or_create_motif_member(conn, family_a, rec_a, 10, 50)
    R.get_or_create_motif_member(conn, family_a, rec_b, 10, 50)
    R.get_or_create_motif_member(conn, family_b, rec_b, 110, 150)
    return conn, (train_a, train_b, family_a, family_b)


def _make_filter_library(npy_dir):
    """A scratch library exercising every T55 filter.

    Two recordings — A.mat CH0 (fs=1.0) and B.mat CH1 (fs=2.0) — and two
    spike trains, one per recording. Five event-scale family entries sit on
    those recordings with distinct morphologies, purity (quality) tags,
    peak-to-peak depths and fall durations, so each filter can be asserted
    against a known subset.

    Train-scale entries span a zero region of their recording, so their
    depth is 0 mV and they are excluded by any depth range that selects the
    event entries — keeping the depth/filter expectations about the motifs,
    not the bounding boxes.

    Returns (conn, (train_a, train_b, e1, e2, e3, e4, e5)).
    """
    def _sine(amp, n):
        return amp * np.sin(2 * np.pi * np.arange(n) / n)

    conn = init_db(":memory:")
    v.seed_vocabulary(conn)

    sig_a = np.zeros(200)
    sig_a[10:50] = _sine(10.0, 40)    # e1: ptp 20 mV
    sig_a[60:100] = _sine(5.0, 40)    # e2: ptp 10 mV
    sig_a[110:170] = _sine(4.0, 60)   # e3: ptp 8 mV
    rec_a = _write_recording(conn, npy_dir, "A.mat", 0, sig_a, fs=1.0)

    sig_b = np.zeros(200)
    sig_b[10:50] = _sine(6.0, 40)     # e4: ptp 12 mV
    sig_b[60:100] = _sine(3.0, 40)    # e5: ptp 6 mV
    rec_b = _write_recording(conn, npy_dir, "B.mat", 1, sig_b, fs=2.0)

    train_a = R.insert_motif_entry(conn, rec_a, 0, 10, label="spike train id001")
    _set_entry_scale(conn, train_a, ENTRY_SCALE_TRAIN)
    train_b = R.insert_motif_entry(conn, rec_b, 0, 10, label="spike train id002")
    _set_entry_scale(conn, train_b, ENTRY_SCALE_TRAIN)

    e1 = R.insert_motif_entry(conn, rec_a, 10, 50, label="sine-a", sax_string="aaa")
    _set_entry_scale(conn, e1, ENTRY_SCALE_EVENT)
    e2 = R.insert_motif_entry(conn, rec_a, 60, 100, label="sine-b", sax_string="aaa")
    _set_entry_scale(conn, e2, ENTRY_SCALE_EVENT)
    e3 = R.insert_motif_entry(conn, rec_a, 110, 170, label="sine-c", sax_string="bbb")
    _set_entry_scale(conn, e3, ENTRY_SCALE_EVENT)
    e4 = R.insert_motif_entry(conn, rec_b, 10, 50, label="sine-d", sax_string="ccc")
    _set_entry_scale(conn, e4, ENTRY_SCALE_EVENT)
    e5 = R.insert_motif_entry(conn, rec_b, 60, 100, label="sine-e", sax_string="ddd")
    _set_entry_scale(conn, e5, ENTRY_SCALE_EVENT)

    # Morphology (element) tags.
    v.set_motif_entry_tags(conn, e1, "element", ["sharkfin"])
    v.set_motif_entry_tags(conn, e2, "element", ["ridge"])
    v.set_motif_entry_tags(conn, e3, "element", ["sharkfin"])
    v.set_motif_entry_tags(conn, e4, "element", ["ridge"])
    v.set_motif_entry_tags(conn, e5, "element", ["sharkfin"])
    # Purity (quality) tags.
    v.set_motif_entry_tags(conn, e1, "quality", ["clean"])
    v.set_motif_entry_tags(conn, e2, "quality", ["noisy"])
    v.set_motif_entry_tags(conn, e3, "quality", ["clean"])
    v.set_motif_entry_tags(conn, e4, "quality", ["clean"])
    v.set_motif_entry_tags(conn, e5, "quality", ["noisy"])

    # Provenance: each event's own span is a member of its train, which is
    # how the grid resolves an event entry back to the train it came from.
    R.get_or_create_motif_member(conn, train_a, rec_a, 10, 50)
    R.get_or_create_motif_member(conn, train_a, rec_a, 60, 100)
    R.get_or_create_motif_member(conn, train_a, rec_a, 110, 170)
    R.get_or_create_motif_member(conn, train_b, rec_b, 10, 50)
    R.get_or_create_motif_member(conn, train_b, rec_b, 60, 100)

    return conn, (train_a, train_b, e1, e2, e3, e4, e5)


def _make_family_with_edges(npy_dir):
    """One family whose exemplar has two candidate members at known edge
    distances — m2 (0.1) closer than m1 (0.5). Returns
    (conn, entry_id, exemplar_member_id, m1, m2)."""
    conn = init_db(":memory:")
    v.seed_vocabulary(conn)
    sine = np.sin(2 * np.pi * np.arange(200) / 200)
    rec_a = _write_recording(conn, npy_dir, "A.mat", 0, sine)
    entry_id = R.insert_motif_entry(conn, rec_a, 10, 50, label="family")
    exemplar_member_id = R.get_or_create_motif_member(conn, entry_id, rec_a, 10, 50)
    m1 = R.get_or_create_motif_member(conn, entry_id, rec_a, 60, 100)
    m2 = R.get_or_create_motif_member(conn, entry_id, rec_a, 110, 150)
    R.insert_motif_edge(
        conn, exemplar_member_id, m1,
        distance_function=DISTANCE_SCALE_INVARIANT,
        threshold=0.1, distance_value=0.5, recipe_hash="h1",
    )
    R.insert_motif_edge(
        conn, exemplar_member_id, m2,
        distance_function=DISTANCE_SCALE_INVARIANT,
        threshold=0.1, distance_value=0.1, recipe_hash="h2",
    )
    return conn, entry_id, exemplar_member_id, m1, m2


def _card_markdown_texts(card):
    """Every markdown string rendered inside one card, for text assertions."""
    texts = []
    for obj in card:
        if isinstance(obj, pn.pane.Markdown):
            texts.append(obj.object or "")
    return texts


# ── criterion 1: the selector exists and offers the three bases ─────────────

def test_library_grid_has_grouping_selector():
    conn = init_db(":memory:")
    try:
        grid = LibraryGrid(_FakeLibraryApp(conn))
        assert grid.group_by is not None
        bases = set(grid.group_by.options.values())
        assert {"provenance", "family", "tag"} <= bases, bases
    finally:
        conn.close()


# ── criterion 2: shape-family grouping sections one entry per family ────────

def test_group_by_family_lists_each_entry_as_its_own_family():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (e1, e2, e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.group_by.value = "family"
            assert len(grid.groups) == 3
            for title, entry_ids in grid.groups:
                assert len(entry_ids) == 1, (title, entry_ids)
            assert {title for title, _ids in grid.groups} == {
                "sine-a", "sine-b", "sine-c",
            }
        finally:
            conn.close()


# ── criterion 4: tags are never treated as a primary key ────────────────────

def test_group_by_tag_puts_a_two_tag_entry_under_both_tags():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (e1, e2, e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.group_by.value = "tag"
            groups = dict(grid.groups)
            assert e1 in groups["sharkfin"]
            assert e1 in groups["ridge"]
            assert e2 in groups["sharkfin"]
            assert e3 in groups["untagged"]
        finally:
            conn.close()


# ── criterion 1b: the selector actually re-renders the layout ───────────────

def test_group_by_selector_rerenders_the_layout_when_changed():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (e1, e2, e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            layout = grid.layout()

            grid.group_by.value = "family"
            assert set(_group_titles_from_layout(layout)) == {
                "sine-a", "sine-b", "sine-c",
            }

            grid.group_by.value = "tag"
            assert set(_group_titles_from_layout(layout)) == {
                "sharkfin", "ridge", "untagged",
            }

            grid.group_by.value = "provenance"
            assert set(_group_titles_from_layout(layout)) == {"A.mat CH00"}
        finally:
            conn.close()


# ── criterion 5: the same entries appear under every basis ──────────────────

def test_all_grouping_bases_show_the_same_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (e1, e2, e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            all_ids = {e1, e2, e3}
            for basis in ("provenance", "family", "tag"):
                grid.group_by.value = basis
                grouped_ids = {
                    eid
                    for _title, entry_ids in grid.groups
                    for eid in entry_ids
                }
                assert grouped_ids == all_ids, basis
        finally:
            conn.close()


# ── criterion 6 (T53): thumbnails in millivolts, shared family y-range ──────

def test_thumbnails_share_y_range_within_shape_family_in_millivolts():
    """Two cards in the same shape family share one y-range; a card in a
    different family does not. The shared range reflects the real millivolt
    amplitudes of the (detrended) signal, not a z-score."""
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (e1, e2, e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.group_by.value = "family"
            ranges = {
                eid: _card_ylim(grid._card_by_entry[eid])
                for eid in (e1, e2, e3)
            }
            # Same family -> identical y-range.
            assert ranges[e1] == ranges[e2], (ranges[e1], ranges[e2])
            # Different family -> different y-range.
            assert ranges[e1] != ranges[e3], ranges[e1]
            # The shared range reflects real millivolt values (a 10 mV sine),
            # not a z-normalised curve (~[-2, 2]).
            y0, y1 = ranges[e1]
            assert y0 <= -9.0 and y1 >= 9.0, (y0, y1)
        finally:
            conn.close()


def test_thumbnail_grid_constructs_headlessly_with_non_none_panes():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (_e1, _e2, _e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            layout = grid.layout()
            assert layout is not None
            assert len(grid.cards) == 3
            assert all(card is not None for card in grid.cards)
            for card in grid.cards:
                thumbs = [o for o in card if isinstance(o, pn.pane.HoloViews)]
                assert len(thumbs) == 1, card
                assert thumbs[0].object is not None
        finally:
            conn.close()


# ── T54: provenance vs shape-family axes ─────────────────────────────────────

def test_library_grid_has_provenance_and_shape_family_axes():
    conn = init_db(":memory:")
    try:
        grid = LibraryGrid(_FakeLibraryApp(conn))
        bases = set(grid.group_by.options.values())
        assert {"provenance", "family"} <= bases, bases
    finally:
        conn.close()


def test_group_by_provenance_groups_entries_by_spike_train():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (train_a, train_b, family_a, family_b) = _make_two_axis_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.group_by.value = "provenance"
            groups = {title: set(ids) for title, ids in grid.groups}
            assert groups["spike train id001"] == {train_a, family_a}
            assert groups["spike train id002"] == {train_b, family_b}
        finally:
            conn.close()


def test_group_by_shape_family_groups_each_computed_family():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (train_a, train_b, family_a, family_b) = _make_two_axis_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.group_by.value = "family"
            groups = {title: set(ids) for title, ids in grid.groups}
            assert groups["drop family 0"] == {family_a}
            assert groups["drop family 1"] == {family_b}
            assert groups["spike train id001"] == {train_a}
            assert groups["spike train id002"] == {train_b}
        finally:
            conn.close()


def test_provenance_and_shape_axes_show_the_same_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, ids = _make_two_axis_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            all_ids = set(ids)
            for basis in ("provenance", "family"):
                grid.group_by.value = basis
                grouped_ids = {
                    eid
                    for _title, entry_ids in grid.groups
                    for eid in entry_ids
                }
                assert grouped_ids == all_ids, basis
        finally:
            conn.close()


def test_cross_recording_family_is_marked_on_its_card():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (_train_a, _train_b, family_a, family_b) = _make_two_axis_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            family_a_text = " ".join(_card_markdown_texts(grid._card_by_entry[family_a])).lower()
            family_b_text = " ".join(_card_markdown_texts(grid._card_by_entry[family_b])).lower()
            assert "cross-recording" in family_a_text, family_a_text
            assert "cross-recording" not in family_b_text, family_b_text
        finally:
            conn.close()


def test_train_and_event_cards_are_visually_distinguishable():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (train_a, _train_b, family_a, _family_b) = _make_two_axis_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            train_text = " ".join(_card_markdown_texts(grid._card_by_entry[train_a])).lower()
            family_text = " ".join(_card_markdown_texts(grid._card_by_entry[family_a])).lower()
            assert "train-scale" in train_text, train_text
            assert "event-scale" in family_text, family_text
        finally:
            conn.close()


def test_grid_constructs_headlessly_with_non_none_panes_under_each_axis():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, _ids = _make_two_axis_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            layout = grid.layout()
            for basis in ("provenance", "family"):
                grid.group_by.value = basis
                assert layout is not None
                assert grid._sections is not None
                assert len(grid._sections.objects) > 0
                assert all(obj is not None for obj in grid._sections.objects)
                assert all(card is not None for card in grid.cards)
        finally:
            conn.close()


# ── T55: filter and distance-sort the library grid ──────────────────────────

def test_grid_exposes_filter_widgets():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, _ids = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            assert grid.morphology is not None
            assert grid.purity is not None
            assert grid.spike_train is not None
            assert grid.recording is not None
            assert grid.channel is not None
            assert grid.depth_range is not None
            assert grid.fall_duration_range is not None
        finally:
            conn.close()


def test_morphology_filter_narrows_to_matching_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (_train_a, _train_b, e1, e2, e3, e4, e5) = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.morphology.value = ["sharkfin"]   # e1, e3, e5
            grouped_ids = {eid for _t, ids in grid.groups for eid in ids}
            assert grouped_ids == {e1, e3, e5}, grouped_ids
        finally:
            conn.close()


def test_purity_filter_narrows_to_matching_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (_train_a, _train_b, e1, e2, e3, e4, e5) = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.purity.value = ["clean"]          # e1, e3, e4
            grouped_ids = {eid for _t, ids in grid.groups for eid in ids}
            assert grouped_ids == {e1, e3, e4}, grouped_ids
        finally:
            conn.close()


def test_spike_train_filter_narrows_to_matching_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (train_a, train_b, e1, e2, e3, e4, e5) = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.spike_train.value = [train_a]     # train_a, e1, e2, e3
            grouped_ids = {eid for _t, ids in grid.groups for eid in ids}
            assert grouped_ids == {train_a, e1, e2, e3}, grouped_ids
        finally:
            conn.close()


def test_recording_filter_narrows_to_matching_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (train_a, train_b, e1, e2, e3, e4, e5) = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.recording.value = ["B.mat"]       # train_b, e4, e5
            grouped_ids = {eid for _t, ids in grid.groups for eid in ids}
            assert grouped_ids == {train_b, e4, e5}, grouped_ids
        finally:
            conn.close()


def test_channel_filter_narrows_to_matching_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (train_a, train_b, e1, e2, e3, e4, e5) = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.channel.value = [0]               # train_a, e1, e2, e3
            grouped_ids = {eid for _t, ids in grid.groups for eid in ids}
            assert grouped_ids == {train_a, e1, e2, e3}, grouped_ids
        finally:
            conn.close()


def test_depth_range_filter_narrows_to_matching_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (_train_a, _train_b, e1, e2, e3, e4, e5) = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.depth_range.value = (9, 21)       # e1(20), e2(10), e4(12)
            grouped_ids = {eid for _t, ids in grid.groups for eid in ids}
            assert grouped_ids == {e1, e2, e4}, grouped_ids
        finally:
            conn.close()


def test_fall_duration_range_filter_narrows_to_matching_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (_train_a, _train_b, e1, e2, e3, e4, e5) = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.fall_duration_range.value = (30, 70)   # e1(40), e2(40), e3(60)
            grouped_ids = {eid for _t, ids in grid.groups for eid in ids}
            assert grouped_ids == {e1, e2, e3}, grouped_ids
        finally:
            conn.close()


def test_filters_compose():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (_train_a, _train_b, e1, e2, e3, e4, e5) = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.morphology.value = ["sharkfin"]   # e1, e3, e5
            grid.recording.value = ["A.mat"]       # train_a, e1, e2, e3
            grouped_ids = {eid for _t, ids in grid.groups for eid in ids}
            assert grouped_ids == {e1, e3}, grouped_ids
        finally:
            conn.close()


def test_filter_matching_nothing_renders_a_sentence():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (_e1, _e2, _e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            # "spore_drop" is a vocabulary term but no entry carries it.
            grid.morphology.value = ["spore_drop"]
            layout = grid.layout()
            texts = _all_markdown_texts(layout)
            assert any("No entries match" in t for t in texts), texts
            # The sections hold a sentence, not an empty grid.
            assert len(grid._sections.objects) == 1
        finally:
            conn.close()


def test_members_sorted_by_edge_distance_to_exemplar():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id, _exemplar_member_id, m1, m2 = _make_family_with_edges(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            sorted_ids = grid.sorted_member_ids_by_distance(entry_id)
            assert sorted_ids == [m2, m1]          # closest first
        finally:
            conn.close()


def test_grid_constructs_headlessly_with_non_none_panes_under_filters():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (_train_a, _train_b, _e1, _e2, _e3, _e4, _e5) = _make_filter_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.morphology.value = ["sharkfin"]
            grid.depth_range.value = (9, 21)
            layout = grid.layout()
            assert layout is not None
            assert grid._sections is not None
            assert len(grid._sections.objects) > 0
            assert all(obj is not None for obj in grid._sections.objects)
            assert all(card is not None for card in grid.cards)
        finally:
            conn.close()


# ── runner ──────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
