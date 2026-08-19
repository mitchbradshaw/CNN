"""
test_session_persistence.py
=============================
Tests for Part E9 (session persistence): ViewerApp remembers the last
recording/channel/viewport/filters/search/toggles across restarts via a
plain JSON file at Working.config.SESSION_STATE_PATH, restores them on
reopen, and warns (rather than silently discarding) when switching
recording/channel with an unsaved pending span.

Monkeypatches `SESSION_STATE_PATH` to a scratch-directory file for every
test -- never reads or writes the real DATA/db/ui_session.json. Real-data-
gated (ViewerApp needs a real channel .npy), same convention as
tests/test_ui_selection.py.

Run from the project root:
    python tests/test_session_persistence.py
"""

import inspect
import json
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
from Working.database import vocabulary as v
import UI.viewer as appmod
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _fresh_db_with_two_channels(tag):
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    v.seed_vocabulary(conn)
    rid0 = q.insert_recording(conn, f"UNITTEST_session_{tag}.mat", 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    q.insert_recording(conn, f"UNITTEST_session_{tag}.mat", 1, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
    q.insert_annotation(conn, rid0, 1000, 1100, "interesting", source=q.SOURCE_MANUAL_UI)
    q.insert_annotation(conn, rid0, 5000, 5100, "artifact", source=q.SOURCE_MANUAL_UI)
    conn.close()
    return tf.name


def _close_and_unlink(app, db_path):
    app.conn.close()
    os.unlink(db_path)


# ── round trip: save then restore into a fresh app instance ────────────────

def test_no_session_file_constructs_with_defaults():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file():
        db = _fresh_db_with_two_channels("defaults")
        app = appmod.ViewerApp(db_path=db)
        try:
            assert app.channel == 0
            assert app.filter_verdict.value == []
        finally:
            _close_and_unlink(app, db)


def test_save_then_restore_round_trip():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file() as session_path:
        db = _fresh_db_with_two_channels("roundtrip")
        app1 = appmod.ViewerApp(db_path=db)
        app1.channel = 1
        app1.filter_verdict.value = ["interesting", "artifact"]
        app1.search_text_input.value = "sharkfin"
        app1.show_annotation_ribbon_toggle.value = False
        app1.dc_offset_toggle.value = True
        app1.time_unit_toggle.value = "hours"
        app1._range_stream.event(x_range=(100.0 / 3600.0, 2000.0 / 3600.0))
        app1._save_session_state()
        app1.conn.close()

        assert os.path.isfile(session_path)

        app2 = appmod.ViewerApp(db_path=db)
        try:
            assert app2.channel == 1
            assert set(app2.filter_verdict.value) == {"interesting", "artifact"}
            assert app2.search_text_input.value == "sharkfin"
            assert app2.show_annotation_ribbon_toggle.value is False
            assert app2.dc_offset_toggle.value is True
            assert app2.time_unit_toggle.value == "hours"
            assert app2._range_stream.x_range is not None
            assert abs(app2._range_stream.x_range[0] * 3600 - 100.0) < 1.0
        finally:
            _close_and_unlink(app2, db)


def test_restoring_a_session_does_not_immediately_resave_it():
    """Applying a loaded session must not itself trigger another write --
    otherwise a session saved with, say, filters A could be silently
    overwritten by whatever transient intermediate state __init__ passes
    through while restoring."""
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file() as session_path:
        db = _fresh_db_with_two_channels("noresave")
        app1 = appmod.ViewerApp(db_path=db)
        app1.channel = 1
        app1.filter_source.value = ["manual_ui"]
        app1._save_session_state()
        app1.conn.close()
        with open(session_path) as f:
            before = json.load(f)

        app2 = appmod.ViewerApp(db_path=db)
        with open(session_path) as f:
            after = json.load(f)
        try:
            assert after == before
        finally:
            _close_and_unlink(app2, db)


def test_corrupt_session_file_does_not_crash_startup():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file() as session_path:
        with open(session_path, "w") as f:
            f.write("{not valid json")
        db = _fresh_db_with_two_channels("corrupt")
        app = appmod.ViewerApp(db_path=db)  # must not raise
        try:
            assert app.channel == 0  # falls back to the default
        finally:
            _close_and_unlink(app, db)


def test_stale_channel_in_session_is_ignored():
    """A session saved against a channel that no longer exists for this
    source_file (e.g. a re-materialized recording with fewer channels)
    must degrade to the default, not crash or set an invalid param."""
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file() as session_path:
        db = _fresh_db_with_two_channels("stale")
        with open(session_path, "w") as f:
            json.dump({"source_file": f"UNITTEST_session_stale.mat", "channel": 99}, f)
        app = appmod.ViewerApp(db_path=db)
        try:
            assert app.channel in app.param.channel.objects
        finally:
            _close_and_unlink(app, db)


def test_stale_channel_shows_a_visible_notice():
    """Part C1: degrading silently isn't enough -- a stale saved channel
    must produce a status-line notice, or a broken/misleading assumption
    ("this IS the session I saved") could go unnoticed."""
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file() as session_path:
        db = _fresh_db_with_two_channels("stalenotice")
        with open(session_path, "w") as f:
            json.dump({"source_file": "UNITTEST_session_stalenotice.mat", "channel": 99}, f)
        app = appmod.ViewerApp(db_path=db)
        try:
            assert "no longer exists" in app.status.object
            assert "99" in app.status.object
        finally:
            _close_and_unlink(app, db)


def test_stale_recording_shows_a_visible_notice():
    """Part C1: the recording itself (not just the channel) can be gone
    entirely -- e.g. re-imported under a different source_file name --
    and that must also produce a visible notice, not just a silent
    fall-back to the first available recording."""
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file() as session_path:
        db = _fresh_db_with_two_channels("stalerecording")
        with open(session_path, "w") as f:
            json.dump({"source_file": "UNITTEST_this_recording_was_deleted.mat", "channel": 0}, f)
        app = appmod.ViewerApp(db_path=db)
        try:
            assert "no longer exists" in app.status.object
            assert "UNITTEST_this_recording_was_deleted.mat" in app.status.object
            # Still falls back to a valid, loadable recording.
            assert app.source_file in app.param.source_file.objects
            assert app._recording_id is not None
        finally:
            _close_and_unlink(app, db)


def test_valid_session_shows_no_stale_notice():
    """A session that matches a real recording/channel must NOT show the
    stale-session warning -- it's specifically for the mismatch case."""
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file() as session_path:
        db = _fresh_db_with_two_channels("validnotice")
        with open(session_path, "w") as f:
            json.dump({"source_file": "UNITTEST_session_validnotice.mat", "channel": 1}, f)
        app = appmod.ViewerApp(db_path=db)
        try:
            assert "no longer exists" not in app.status.object
        finally:
            _close_and_unlink(app, db)


# ── warn before switching with an unsaved pending span ──────────────────────

def test_switching_channel_with_pending_span_warns():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file():
        db = _fresh_db_with_two_channels("warn")
        app = appmod.ViewerApp(db_path=db)
        try:
            app._set_pending_bounds(2000, 2100)
            assert app._pending_bounds is not None and app._pending_bounds[0] is not None
            app.channel = 1
            assert "unsaved pending span" in app.status.object
        finally:
            _close_and_unlink(app, db)


def test_switching_channel_without_pending_span_does_not_warn():
    if not _channel_available():
        pytest.skip(
            f"real channel data not present: {REAL_CHANNEL_PATH}")
    with scratch_session_file():
        db = _fresh_db_with_two_channels("nowarn")
        app = appmod.ViewerApp(db_path=db)
        try:
            app.status.object = ""
            app.channel = 1
            assert "unsaved pending span" not in app.status.object
        finally:
            _close_and_unlink(app, db)


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
            # `Skipped` derives from BaseException, not Exception, so it would
            # sail past the handler below and abort the whole standalone run on
            # the first guarded test. Absent data is a skip here too, not a pass.
            print(f"[SKIP] {fn.__name__}: {e}")
            skipped += 1
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    tally = f"{passed}/{len(fns)} passed"
    if skipped:
        # Never fold skips into the pass count: "all green" and "the data
        # was not there" are the two readings this file exists to keep
        # apart.
        tally += f", {skipped} skipped (real channel data absent)"
    print(f"\n{tally}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
