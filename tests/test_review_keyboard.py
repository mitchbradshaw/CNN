"""
test_review_keyboard.py
=======================
Tests for T22 — single-key verdicts with auto-advance and undo on the Review
candidate surface (`UI/workspaces/review/surface.py`).

T22's acceptance criteria are the things under test here, headlessly:

* five keys map to the five shared verdicts, and that mapping is on screen;
* one key/click writes an adjudication row and advances in one action;
* undo reverses the last verdict and returns to that candidate;
* the key listener ignores keystrokes while a text field has focus;
* the review keys do not collide with Explore's existing shortcuts;
* fifty candidates can be adjudicated end to end without the current index
  desynchronising from the displayed candidate.

The real browser `keydown` cannot be verified headlessly, so — exactly like
`tests/test_shortcuts_and_view_controls.py` — the verifiable halves are
pinned: the Python-side hidden-button wiring, the on-screen mapping text, and
the JS guard for text fields. The end-to-end test exercises the same button
handlers a real keystroke would click.

Run from the project root:
    python tests/test_review_keyboard.py
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
from Working.database import adjudications as adj
from Working.database import queries as q
from UI.workspaces.review.surface import REVIEW_VERDICT_KEYS, ReviewSurface

FS = 1.0
N = 2000

# The keys Explore's existing shortcut system already owns. T22 must not use
# any of them, because both keydown listeners are attached to `document`.
EXPLORE_KEYS = {"Escape", "1", "2", "3", "4", "Enter", "n", "p", "r", "z", "x", "c"}


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
    return q.insert_recording(conn, "review_keyboard.mat", 0, FS, N, 0, npy_path)


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


def _make_surface(n_detections=2):
    tmpdir = tempfile.mkdtemp(prefix="review_keyboard_test_")
    npy_path = _planted_npy(os.path.join(tmpdir, "CH0.npy"))
    conn = _fresh_conn()
    rid = _insert_recording(conn, npy_path)
    det_ids = [
        _insert_detection(conn, rid, i * 20, i * 20 + 10, score=0.5 + i / 100,
                          method="rupture")
        for i in range(n_detections)
    ]
    app = _FakeApp(conn, rid)
    surface = ReviewSurface(app)
    return surface, conn, tmpdir, det_ids, rid


def _cleanup(surface, conn, tmpdir):
    conn.close()
    shutil.rmtree(tmpdir, ignore_errors=True)


def _click(button):
    """Simulate a real click without a live browser — the same technique as
    `tests/test_shortcuts_and_view_controls.py`."""
    button._process_events({"clicks": (button.clicks or 0) + 1})


# ── key mapping and on-screen display ───────────────────────────────────────

def test_review_verdict_keys_match_the_shared_vocabulary():
    assert list(REVIEW_VERDICT_KEYS.values()) == list(q.VERDICTS)
    assert len(REVIEW_VERDICT_KEYS) == 5


def test_review_verdict_keys_do_not_collide_with_explore_shortcuts():
    assert set(REVIEW_VERDICT_KEYS).isdisjoint(EXPLORE_KEYS)


def test_verdict_key_mapping_is_displayed_on_screen():
    surface, conn, tmpdir, det_ids, rid = _make_surface()
    try:
        assert surface.verdict_key_reference is not None
        reference = surface.verdict_key_reference.object
        for key, verdict in REVIEW_VERDICT_KEYS.items():
            assert f"`{key}`" in reference
            assert verdict in reference
    finally:
        _cleanup(surface, conn, tmpdir)


# ── one key writes a verdict and advances ──────────────────────────────────

def test_verdict_button_writes_an_adjudication_and_advances():
    surface, conn, tmpdir, det_ids, rid = _make_surface(n_detections=2)
    try:
        verdict = q.VERDICTS[0]
        _click(surface._verdict_buttons[verdict])

        row = adj.get_adjudication(conn, det_ids[0])
        assert row is not None
        assert row["verdict"] == verdict
        assert surface.queue.current["id"] == det_ids[1]
        assert surface.queue.history[-1]["detection_id"] == det_ids[0]
    finally:
        _cleanup(surface, conn, tmpdir)


def test_each_of_the_five_keys_writes_its_verdict():
    surface, conn, tmpdir, det_ids, rid = _make_surface(n_detections=5)
    try:
        for det_id, (key, verdict) in zip(det_ids, REVIEW_VERDICT_KEYS.items()):
            _click(surface._verdict_buttons[verdict])
            row = adj.get_adjudication(conn, det_id)
            assert row is not None
            assert row["verdict"] == verdict

        assert surface.queue.current is None
        assert [h["verdict"] for h in surface.queue.history] == list(q.VERDICTS)
    finally:
        _cleanup(surface, conn, tmpdir)


# ── undo ────────────────────────────────────────────────────────────────────

def test_undo_button_reverses_the_last_verdict_and_returns():
    surface, conn, tmpdir, det_ids, rid = _make_surface(n_detections=3)
    try:
        _click(surface._verdict_buttons["interesting"])
        assert surface.queue.current["id"] == det_ids[1]
        assert adj.get_adjudication(conn, det_ids[0]) is not None

        _click(surface.undo_button)

        assert surface.queue.current["id"] == det_ids[0]
        assert adj.get_adjudication(conn, det_ids[0]) is None
        assert surface.queue.history == []
    finally:
        _cleanup(surface, conn, tmpdir)


# ── keys are inert while a text field has focus ────────────────────────────

def test_key_listener_ignores_text_fields():
    surface, conn, tmpdir, det_ids, rid = _make_surface()
    try:
        listener = surface._review_key_listener.object
        assert "document.activeElement" in listener
        assert "INPUT" in listener
        assert "TEXTAREA" in listener
    finally:
        _cleanup(surface, conn, tmpdir)


# ── fifty candidates, end to end ────────────────────────────────────────────

def test_fifty_candidates_stay_in_sync_end_to_end():
    surface, conn, tmpdir, det_ids, rid = _make_surface(n_detections=50)
    try:
        for det_id in det_ids:
            assert surface.queue.current["id"] == det_id
            verdict = q.VERDICTS[det_ids.index(det_id) % len(q.VERDICTS)]
            _click(surface._verdict_buttons[verdict])
            assert surface.signal_pane.object is not None
            assert surface.waveform_pane.object is not None

        assert surface.queue.current is None
        assert len(surface.queue.history) == 50

        # Undo all fifty: every undo must land back on the candidate it
        # reversed, newest first.
        for det_id in reversed(det_ids):
            assert surface.queue.undo() is True
            assert surface.queue.current["id"] == det_id
        assert surface.queue.undo() is False
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
