"""
test_review_surface.py
======================
Tests for T21 — the Review candidate surface
(`UI/workspaces/review/surface.py`).

The surface is the "one candidate at a time, in context" pane the PRD
singles out: a zoomed signal context with configurable padding on each
side, the candidate's analytical score beside it, and the z-normalised
waveform overlay built by the same `build_motif_waveform_overlay` the motif
browser uses (called, not copied).

The blank-pane failure mode CLAUDE.md warns about is the thing under test:
a broken dynamic map renders as `None`-looking pane while tests pass. So
each test asserts the two HoloViews panes hold non-`None` objects and that
their current frames actually render, both before and after the surface
re-renders.

Headless and synthetic — a scratch sqlite plus a tiny on-disk `.npy`, never
the real `DATA/` database. The surface is constructed against a lightweight
fake app, since `ReviewSurface` only reads `app.conn` and
`app._recording_id`.

Run from the project root:
    python tests/test_review_surface.py
"""

import inspect
import json
import os
import shutil
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import panel as pn
pn.extension()
import holoviews as hv
hv.extension("bokeh")

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from UI.workspaces.review.surface import ReviewSurface

FS = 1.0
N = 2000


class _FakeApp:
    """The only app surface `ReviewSurface` is allowed to read."""

    def __init__(self, conn, recording_id):
        self.conn = conn
        self._recording_id = recording_id


def _fresh_conn():
    return init_db(":memory:")


def _planted_npy(path):
    rng = np.random.default_rng(0)
    x = rng.standard_normal(N) * 0.02
    pattern = np.sin(np.linspace(0, 2 * np.pi, 100))
    for s in (400, 700):
        x[s:s + 100] += pattern
    np.save(path, x)
    return path


def _insert_recording(conn, npy_path):
    return q.insert_recording(conn, "review_surface.mat", 0, FS, N, 0, npy_path)


def _insert_detection(conn, rid, start_idx, end_idx, score=None, method="rupture"):
    cid = conn.execute(
        "INSERT INTO configs (config_hash, config_json, created_at) VALUES (?, ?, ?)",
        (f"hash-{rid}-{start_idx}-{end_idx}-{method}",
         json.dumps({"steps": [{"stage": "detection", "algorithm": method}]}),
         "2026-01-01T00:00:00"),
    ).lastrowid
    run_id = conn.execute(
        """INSERT INTO runs
               (config_id, recording_id, span_start, span_end, started_at, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (cid, rid, 0, N, "2026-01-01T00:00:00", "done"),
    ).lastrowid
    det_id = conn.execute(
        "INSERT INTO detections (run_id, start_idx, end_idx, score) VALUES (?, ?, ?, ?)",
        (run_id, start_idx, end_idx, score),
    ).lastrowid
    conn.commit()
    return det_id


def _make_surface():
    tmpdir = tempfile.mkdtemp(prefix="review_surface_test_")
    npy_path = _planted_npy(os.path.join(tmpdir, "CH0.npy"))
    conn = _fresh_conn()
    rid = _insert_recording(conn, npy_path)
    d1 = _insert_detection(conn, rid, 400, 500, score=0.6, method="rupture")
    d2 = _insert_detection(conn, rid, 700, 800, score=0.9, method="peak_finder")
    app = _FakeApp(conn, rid)
    surface = ReviewSurface(app)
    return surface, conn, tmpdir, d1, d2


def _cleanup(surface, conn, tmpdir):
    conn.close()
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── construction and the headless blank-pane gate ──────────────────────────

def test_surface_returns_non_none_layout_and_panes():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        layout = surface.layout()
        assert layout is not None
        assert surface.signal_pane.object is not None
        assert surface.waveform_pane.object is not None
        assert surface.signal_pane.object[()] is not None
        assert isinstance(surface.waveform_pane.object[()], hv.Overlay)
    finally:
        _cleanup(surface, conn, tmpdir)


def test_score_is_displayed_alongside_the_candidate():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        assert "0.6" in surface.score_pane.object
        assert surface.queue.current["id"] == d1
    finally:
        _cleanup(surface, conn, tmpdir)


# ── signal context: configurable padding on each side ─────────────────────

def test_padding_inputs_control_the_signal_context_x_range():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        row = surface.queue.current
        start_s = row["start_idx"] / FS
        end_s = row["end_idx"] / FS

        surface.pad_left_input.value = 20.0
        surface.pad_right_input.value = 30.0

        lo, hi = surface._range_stream.x_range
        assert abs(lo - (start_s - 20.0)) < 1e-9
        assert abs(hi - (end_s + 30.0)) < 1e-9
    finally:
        _cleanup(surface, conn, tmpdir)


# ── the z-normalised overlay is the existing builder, not a copy ──────────

def test_waveform_overlay_uses_the_shared_zscore_builder_shape():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        frame = surface.waveform_pane.object[()]
        assert isinstance(frame, hv.Overlay)
        assert len(frame) >= 1
        for leaf in frame:
            assert leaf.opts.get().kwargs.get("axiswise") is True
            assert leaf.kdims[0].name == "time_s"
            assert leaf.vdims[0].name == "zscore"
    finally:
        _cleanup(surface, conn, tmpdir)


# ── advancing and filtering re-render without blanking the panes ──────────

def test_advance_rerenders_without_blanking_the_panes():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        assert surface.queue.current["id"] == d1
        surface.advance()
        assert surface.queue.current["id"] == d2

        assert surface.signal_pane.object is not None
        assert surface.waveform_pane.object is not None
        signal_frame = surface.signal_pane.object[()]
        waveform_frame = surface.waveform_pane.object[()]
        assert signal_frame is not None
        assert isinstance(waveform_frame, hv.Overlay)

        # Not just non-None: the current frames must actually render.
        signal_fig = hv.render(signal_frame, backend="bokeh")
        waveform_fig = hv.render(waveform_frame, backend="bokeh")
        assert len(signal_fig.renderers) >= 1
        assert len(waveform_fig.renderers) >= 1
    finally:
        _cleanup(surface, conn, tmpdir)


def test_changing_filters_rerenders_without_blanking_the_panes():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        surface.method_input.value = "rupture"
        surface._on_apply_filters()

        assert [c["id"] for c in surface.queue.candidates] == [d1]
        assert surface.signal_pane.object is not None
        assert surface.waveform_pane.object is not None
        assert surface.signal_pane.object[()] is not None
        assert isinstance(surface.waveform_pane.object[()], hv.Overlay)
    finally:
        _cleanup(surface, conn, tmpdir)


# ── promotion into the library (T23) ────────────────────────────────────────
#
# Scoring and cataloguing are one continuous motion: adjudicating writes an
# `adjudications` row and nothing else, and only the explicit Promote action
# creates a `motif_entry`. The entry retains a provenance pointer back to the
# detection, writes no `annotations` row, and is queryable immediately through
# the same `list_motif_entries` the Library grid renders.

def test_promote_creates_motif_entry_with_provenance():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        # Score the first candidate as a seed exemplar, then promote it.
        surface._on_verdict("seed")
        surface._on_promote()

        entries = R.list_motif_entries(conn)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["detection_id"] == d1
        assert entry["start_idx"] == 400
        assert entry["end_idx"] == 500
    finally:
        _cleanup(surface, conn, tmpdir)


def test_adjudicating_every_candidate_creates_zero_entries():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        surface._on_verdict("seed")
        surface._on_verdict("interesting")
        assert surface.queue.current is None
        assert R.list_motif_entries(conn) == []
    finally:
        _cleanup(surface, conn, tmpdir)


def test_promote_writes_no_annotation_row():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        surface._on_verdict("seed")
        surface._on_promote()
        n = conn.execute("SELECT COUNT(*) AS n FROM annotations").fetchone()["n"]
        assert n == 0
    finally:
        _cleanup(surface, conn, tmpdir)


def test_promoted_entry_appears_in_library_immediately():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        surface._on_verdict("seed")
        surface._on_promote()
        assert any(e["detection_id"] == d1 for e in R.list_motif_entries(conn))
    finally:
        _cleanup(surface, conn, tmpdir)


def test_promote_button_is_in_the_layout():
    surface, conn, tmpdir, d1, d2 = _make_surface()
    try:
        assert surface.promote_button is not None
        assert surface.promote_button.name == "Promote to library"
        layout = surface.layout()
        sidebar = layout.objects[0]
        assert surface.promote_button in list(sidebar.objects)
    finally:
        _cleanup(surface, conn, tmpdir)


# ── runner ─────────────────────────────────────────────────────────────────

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
