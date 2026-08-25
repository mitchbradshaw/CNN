"""
test_seed_exemplar.py
=====================
T37 — Seed an exemplar from the viewer.

Marking a span as `seed` in Explore (the viewer) creates a `motif_entry` in the
shape-first library with no detection pointer — the eye-recognised case the
detection-keyed schema could not express. The annotation row and the entry are
separate objects: one lives in `annotations`, the other in `motif_entry`.

These are UI-level tests and follow the same real-channel-gated convention as
tests/test_ui_selection.py and tests/test_workspaces.py: skip if the real
channel .npy isn't present locally, never touch DATA/db/annotations.sqlite, and
always close the connection before unlinking (Windows/Drive-synced folders hold
a file lock otherwise).

Run from the project root:
    python tests/test_seed_exemplar.py
"""

import inspect
import os
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import panel as pn
pn.extension()

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from UI.viewer import ViewerApp
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_app():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    rid = q.insert_recording(conn, "UNITTEST_seed.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    conn.close()
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=tf.name)
    app._test_session_cm = session_cm
    app.layout()
    return app, tf.name


def _close_and_unlink(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


# ── seed verdict creates a separate library entry ───────────────────────────


def test_seed_annotation_creates_a_separate_library_entry():
    """Marking a span as `seed` saves an annotation AND creates a motif_entry
    with no detection pointer; the two are distinct objects."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        app._set_pending_bounds(1000.2, 1100.8)  # fs=1.0Hz -> samples 1000..1101
        app.verdict = "seed"
        aid = app._save_annotation()
        assert aid is not None

        # The annotation row exists and is a plain human annotation.
        anno = q.get_annotation(app.conn, aid)
        assert anno is not None
        assert anno["verdict"] == "seed"

        # The library entry exists, at the same span, with no detection pointer.
        entries = R.list_motif_entries(app.conn)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["detection_id"] is None
        assert entry["recording_id"] == anno["recording_id"]
        assert entry["start_idx"] == anno["start_idx"]
        assert entry["end_idx"] == anno["end_idx"]

        # Separate objects: the entry lives in motif_entry and is not counted
        # as an annotation row. The only annotation is the one we saved.
        assert len(q.list_annotations(app.conn, anno["recording_id"])) == 1
        assert R.get_motif_entry(app.conn, entry["id"]) is not None
    finally:
        _close_and_unlink(app, db_path)


def test_seed_annotation_appears_in_the_library_immediately():
    """Right after the save action the entry is queryable through the library
    listing — no migration, backfill or second step is required."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        assert R.list_motif_entries(app.conn) == []
        app._set_pending_bounds(2000.0, 2600.0)
        app.verdict = "seed"
        app._save_annotation()
        entries = R.list_motif_entries(app.conn)
        assert len(entries) == 1
        assert entries[0]["start_idx"] == 2000
        assert entries[0]["end_idx"] == 2600
    finally:
        _close_and_unlink(app, db_path)


def test_non_seed_annotation_does_not_create_a_library_entry():
    """Only the `seed` verdict anchors a library entry — a plain interesting
    annotation must not silently seed the library."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        app._set_pending_bounds(3000.0, 3600.0)
        app.verdict = "interesting"
        aid = app._save_annotation()
        assert aid is not None
        assert R.list_motif_entries(app.conn) == []
    finally:
        _close_and_unlink(app, db_path)


def test_seed_verdict_comes_from_the_shared_vocabulary():
    """The seed verdict is the shared vocabulary's term (ticket 04), not a
    second copy of the vocabulary: the form offers `q.VERDICTS` and saving a
    seed annotation stores exactly the shared term."""
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    app, db_path = _fresh_app()
    try:
        assert "seed" in q.VERDICTS
        assert list(app.param.verdict.objects) == list(q.VERDICTS)
        seed_term = q.VERDICTS[q.VERDICTS.index("seed")]
        app._set_pending_bounds(4000.0, 4600.0)
        app.verdict = seed_term
        aid = app._save_annotation()
        assert q.get_annotation(app.conn, aid)["verdict"] == "seed"
    finally:
        _close_and_unlink(app, db_path)


# ── runner ───────────────────────────────────────────────────────────────────


def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, skipped, failed = 0, 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except pytest.skip.Exception as e:
            print(f"[SKIP] {fn.__name__}: {e}")
            skipped += 1
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    tally = f"{passed}/{len(fns)} passed"
    if skipped:
        tally += f", {skipped} skipped (real channel data absent)"
    print(f"\n{tally}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
