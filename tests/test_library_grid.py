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

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.database import vocabulary as v
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


def _write_recording(conn, npy_dir, source_file, channel, data, fs=1.0):
    """Write `data` to a scratch .npy file and insert a recording row that
    points at it. Returns the recording id."""
    npy_path = os.path.join(npy_dir, f"{source_file}_ch{channel}.npy")
    np.save(npy_path, np.asarray(data, dtype=float))
    return q.insert_recording(conn, source_file, channel, fs, len(data), 0, npy_path)


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

    Returns (conn, (e1, e2, e3)).
    """
    conn = init_db(":memory:")
    v.seed_vocabulary(conn)
    sine = np.sin(2 * np.pi * np.arange(200) / 200)
    rec = _write_recording(conn, npy_dir, "A.mat", 0, sine)
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


# ── criterion 1: the selector exists and offers the three bases ─────────────

def test_library_grid_has_grouping_selector():
    conn = init_db(":memory:")
    try:
        grid = LibraryGrid(_FakeLibraryApp(conn))
        assert grid.group_by is not None
        bases = set(grid.group_by.options.values())
        assert {"shape", "cluster", "tag"} <= bases, bases
    finally:
        conn.close()


# ── criterion 2: shape grouping groups by sax_string ────────────────────────

def test_group_by_shape_groups_entries_by_sax_string():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (e1, e2, e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.group_by.value = "shape"
            groups = dict(grid.groups)
            assert set(groups["aaa"]) == {e1, e2}
            assert set(groups["bbb"]) == {e3}
        finally:
            conn.close()


# ── criterion 3: cluster membership lists each entry as its own cluster ─────

def test_group_by_cluster_lists_each_entry_as_its_own_cluster():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (e1, e2, e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            grid.group_by.value = "cluster"
            assert len(grid.groups) == 3
            for title, entry_ids in grid.groups:
                assert len(entry_ids) == 1, (title, entry_ids)
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
            assert set(_group_titles_from_layout(layout)) == {"aaa", "bbb"}

            grid.group_by.value = "tag"
            assert set(_group_titles_from_layout(layout)) == {
                "sharkfin", "ridge", "untagged",
            }

            grid.group_by.value = "cluster"
            assert set(_group_titles_from_layout(layout)) == {
                "sine-a", "sine-b", "sine-c",
            }
        finally:
            conn.close()


# ── criterion 5: the same entries appear under every basis ──────────────────

def test_all_grouping_bases_show_the_same_entries():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, (e1, e2, e3) = _make_three_entry_library(npy_dir)
        try:
            grid = LibraryGrid(_FakeLibraryApp(conn))
            all_ids = {e1, e2, e3}
            for basis in ("shape", "cluster", "tag"):
                grid.group_by.value = basis
                grouped_ids = {
                    eid
                    for _title, entry_ids in grid.groups
                    for eid in entry_ids
                }
                assert grouped_ids == all_ids, basis
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
