"""
test_library_detail.py
=======================
Headless construction tests for `UI/workspaces/library/detail.py` (ticket 39):
selecting a library exemplar must show the exemplar's own span, every span
matched to it, the all-members overlay on a shared relative-time axis, and the
edges that put those members there — distance function, threshold and distance
value per member.

The acceptance criteria under test:

1. Selecting an exemplar shows a non-`None` overlay, a member list and an edge
   list.
2. The edge list carries distance function, threshold and distance value per
   member.
3. The overlay is the existing `build_motif_waveform_overlay` shape — an
   `hv.Overlay` whose leaves are `axiswise=True` on the `zscore` vdim, the
   exact fingerprint of that builder (never a reimplementation).
4. A family with at least twenty members renders without the pane blanking.

Headless: a scratch `tempfile` directory holds the .npy files, and the database
is an in-memory sqlite file — never the real annotations database.
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
from Working.distances import DISTANCE_SCALE_INVARIANT
from Working.library import match_span_to_entry
from UI.workspaces.library.detail import EntryDetail


# ── fixture helpers ─────────────────────────────────────────────────────────

def _write_recording(conn, npy_dir, source_file, channel, data, fs=1.0):
    """Write `data` to a scratch .npy file and insert a recording row that
    points at it. Returns the recording id."""
    npy_path = os.path.join(npy_dir, f"{source_file}_ch{channel}.npy")
    np.save(npy_path, np.asarray(data, dtype=float))
    return q.insert_recording(conn, source_file, channel, fs, len(data), 0, npy_path)


class _FakeLibraryApp:
    """The only app surface `EntryDetail` is allowed to read."""

    def __init__(self, conn):
        self.conn = conn


def _make_one_member_family(npy_dir):
    """A two-member family:
    - recording A (source A.mat, channel 0) holds the exemplar span [10, 50).
    - recording B (source B.mat, channel 3) is the same sine and is matched to
      it, so the family has one exemplar plus one member joined by an edge.

    Returns (conn, entry_id).
    """
    conn = init_db(":memory:")
    sine = np.sin(2 * np.pi * np.arange(200) / 200)
    rec_a = _write_recording(conn, npy_dir, "A.mat", 0, sine)
    rec_b = _write_recording(conn, npy_dir, "B.mat", 3, sine)
    entry_id = R.insert_motif_entry(conn, rec_a, 10, 50, label="sine")
    result = match_span_to_entry(
        conn, entry_id, rec_b, 10, 50,
        distance_function=DISTANCE_SCALE_INVARIANT,
        threshold=0.1, recipe_hash="h1",
    )
    assert result is not None
    return conn, entry_id


# ── criterion 1 + 2: selecting an exemplar shows members and edge fields ────

def test_selecting_entry_shows_members_overlay_and_edge_fields():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id = _make_one_member_family(npy_dir)
        try:
            detail = EntryDetail(_FakeLibraryApp(conn))
            detail.select_entry(entry_id)

            assert detail.overlay_pane.object is not None
            assert isinstance(detail.overlay_pane.object, hv.Overlay)

            member_text = detail.member_pane.object
            assert "A.mat" in member_text
            assert "B.mat" in member_text

            edge_text = detail.edge_pane.object
            assert "B.mat" in edge_text
            assert DISTANCE_SCALE_INVARIANT in edge_text
            assert "0.1" in edge_text
        finally:
            conn.close()


# ── criterion 3: the overlay is the existing builder's shape, not a copy ────

def test_entry_detail_overlay_uses_the_shared_waveform_builder_shape():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn, entry_id = _make_one_member_family(npy_dir)
        try:
            detail = EntryDetail(_FakeLibraryApp(conn))
            detail.select_entry(entry_id)

            overlay = detail.overlay_pane.object
            assert isinstance(overlay, hv.Overlay)
            for leaf in overlay:
                kwargs = leaf.opts.get().kwargs
                assert kwargs.get("axiswise") is True, (
                    f"{type(leaf).__name__} is missing axiswise=True -- the "
                    "shared overlay builder sets it on every leaf"
                )
                vdims = [vd.name for vd in leaf.vdims]
                assert "zscore" in vdims, (
                    f"{type(leaf).__name__} uses {vdims}, not the builder's "
                    "distinct zscore vdim"
                )
        finally:
            conn.close()


# ── criterion 4: twenty members must not blank the pane ─────────────────────

def test_family_with_twenty_members_renders_without_blanking():
    with tempfile.TemporaryDirectory() as npy_dir:
        conn = init_db(":memory:")
        try:
            m = 40
            n = 2000
            rng = np.random.default_rng(0)
            x = rng.standard_normal(n) * 0.02
            pattern = np.sin(np.linspace(0, 2 * np.pi, m))
            for start in range(0, 21 * m, m):
                x[start:start + m] = pattern

            rec_a = _write_recording(conn, npy_dir, "A.mat", 0, x)
            entry_id = R.insert_motif_entry(conn, rec_a, 0, m, label="twenty")

            exemplar_member_id = R.get_or_create_motif_member(
                conn, entry_id, rec_a, 0, m,
            )
            for k in range(1, 21):
                start = k * m
                member_id = R.get_or_create_motif_member(
                    conn, entry_id, rec_a, start, start + m,
                )
                R.insert_motif_edge(
                    conn, exemplar_member_id, member_id,
                    distance_function=DISTANCE_SCALE_INVARIANT,
                    threshold=0.1,
                    distance_value=float(k) / 100.0,
                    recipe_hash=f"h{k}",
                )

            detail = EntryDetail(_FakeLibraryApp(conn))
            detail.select_entry(entry_id)

            assert detail.overlay_pane.object is not None
            assert isinstance(detail.overlay_pane.object, hv.Overlay)
            assert "Members (21)" in detail.member_pane.object
            assert detail.edge_pane.object is not None

            fig = hv.render(detail.overlay_pane.object, backend="bokeh")
            assert len(fig.renderers) >= 20, len(fig.renderers)
        finally:
            conn.close()


# ── empty library: non-None panes, not a silently blank surface ─────────────

def test_empty_library_entry_detail_renders_non_none_panes():
    conn = init_db(":memory:")
    try:
        detail = EntryDetail(_FakeLibraryApp(conn))
        layout = detail.layout()
        assert layout is not None
        assert detail.overlay_pane.object is not None
        assert detail.member_pane.object is not None
        assert detail.edge_pane.object is not None
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
