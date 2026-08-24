"""
test_heldout_lock.py
====================
Tests for the held-out recording lock (ticket T03).

`M4_aug_concat_fs1.mat` is the evaluation recording. It is refused by both the
runner and the viewer unless the unlock flag is set, so "untouched until the
freeze" is true by construction rather than by memory.

The load-bearing test here is `test_the_guard_reads_config_not_a_literal`: a
guard that happens to name the same string as the config constant would pass
every other test in this file while being exactly the thing the ticket forbids.
It is tested by moving the config value and checking the guard moves with it.

Recordings go in through `q.insert_recording` rather than hand-written SQL --
`channel` is an integer column, and a hand-written row with a string in it
builds a database no other part of the app can read.

Run from the project root:
    python tests/test_heldout_lock.py
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

import Working.config as config
from Working.config import HELD_OUT_RECORDING_FILE
from Working.database.schema import init_db
from Working.database import queries as q
from Working.execution import execute_recipe, HeldOutRecordingLocked, RecipeExecutionError
from Working.recipes import make_recipe
from UI.viewer import ViewerApp
from tests._session_isolation import scratch_session_file

REAL_CHANNEL_PATH = "DATA/derived/channels/M2_aug_concat_fs1/CH0.npy"
REAL_L = 2_595_600

STEPS = [{"stage": "preprocessing", "algorithm": "zscore"}]


def _channel_available():
    return os.path.isfile(REAL_CHANNEL_PATH)


def _scratch_db(*source_files):
    """A temp database holding one recording per name given, in order."""
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    ids = [
        q.insert_recording(conn, name, 0, 1.0, REAL_L, 0, REAL_CHANNEL_PATH)
        for name in source_files
    ]
    conn.close()
    return tf.name, ids


class _unlocked:
    """Set the unlock flag for the duration of a block.

    Both guards re-read `Working.config` when they run rather than binding the
    value at import, which is what makes the flag flippable at all -- and what
    this context manager depends on.
    """

    def __init__(self, value=True):
        self.value = value

    def __enter__(self):
        self._original = config.HELD_OUT_UNLOCK
        config.HELD_OUT_UNLOCK = self.value
        return self

    def __exit__(self, *exc):
        config.HELD_OUT_UNLOCK = self._original
        return False


class _held_out_named:
    """Point the config at a different file for the duration of a block."""

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self._original = config.HELD_OUT_RECORDING_FILE
        config.HELD_OUT_RECORDING_FILE = self.name
        return self

    def __exit__(self, *exc):
        config.HELD_OUT_RECORDING_FILE = self._original
        return False


# ── Config ──────────────────────────────────────────────────────────────────


def test_the_held_out_recording_is_named_in_config():
    assert HELD_OUT_RECORDING_FILE == "M4_aug_concat_fs1.mat"
    assert config.HELD_OUT_UNLOCK is False, "the lock ships closed"


# ── The runner ──────────────────────────────────────────────────────────────


def test_execute_recipe_refuses_the_held_out_recording():
    db_path, (rid,) = _scratch_db(HELD_OUT_RECORDING_FILE)
    try:
        recipe = make_recipe(rid, span=(0, 100), steps=STEPS)
        with pytest.raises(HeldOutRecordingLocked) as excinfo:
            execute_recipe(recipe, db_path=db_path)
        assert HELD_OUT_RECORDING_FILE in str(excinfo.value)
    finally:
        os.unlink(db_path)


def test_execute_recipe_refuses_before_it_writes_a_run_row():
    """The point of the guard is that nothing happens, not that it fails late."""
    db_path, (rid,) = _scratch_db(HELD_OUT_RECORDING_FILE)
    try:
        recipe = make_recipe(rid, span=(0, 100), steps=STEPS)
        with pytest.raises(HeldOutRecordingLocked):
            execute_recipe(recipe, db_path=db_path)
        conn = init_db(db_path)
        try:
            runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        finally:
            conn.close()
        assert runs == 0, "the held-out recording got a run row despite being locked"
    finally:
        os.unlink(db_path)


def test_execute_recipe_permits_the_held_out_recording_when_unlocked():
    """Unlocked, the guard is out of the way: execution proceeds far enough to
    fail on the missing .npy instead, which is a different exception entirely."""
    db_path, (rid,) = _scratch_db(HELD_OUT_RECORDING_FILE)
    try:
        recipe = make_recipe(rid, span=(0, 100), steps=STEPS)
        with _unlocked():
            with pytest.raises(RecipeExecutionError) as excinfo:
                execute_recipe(recipe, db_path=db_path)
        assert not isinstance(excinfo.value, HeldOutRecordingLocked)
    finally:
        os.unlink(db_path)


def test_execute_recipe_leaves_other_recordings_alone():
    db_path, (rid,) = _scratch_db("some_other_recording.mat")
    try:
        recipe = make_recipe(rid, span=(0, 100), steps=STEPS)
        # Reaches the loader and fails there — `RecipeExecutionError` wrapping a
        # FileNotFoundError, because the fabricated row points at no real array.
        with pytest.raises(RecipeExecutionError) as excinfo:
            execute_recipe(recipe, db_path=db_path)
        assert not isinstance(excinfo.value, HeldOutRecordingLocked)
    finally:
        os.unlink(db_path)


def test_the_guard_reads_config_not_a_literal():
    """Move the config value; the guard must move with it.

    A guard comparing against its own copy of "M4_aug_concat_fs1.mat" passes
    every other test in this file. This is the one that fails it.
    """
    decoy = "T03_DECOY_not_the_real_held_out.mat"
    db_path, (rid,) = _scratch_db(decoy)
    try:
        recipe = make_recipe(rid, span=(0, 100), steps=STEPS)
        with _held_out_named(decoy):
            with pytest.raises(HeldOutRecordingLocked) as excinfo:
                execute_recipe(recipe, db_path=db_path)
        assert decoy in str(excinfo.value)
    finally:
        os.unlink(db_path)


# ── The viewer ──────────────────────────────────────────────────────────────


def _app_on(db_path):
    session_cm = scratch_session_file()
    session_cm.__enter__()
    app = ViewerApp(db_path=db_path)
    app._test_session_cm = session_cm
    return app


def _close(app, db_path):
    app._test_session_cm.__exit__(None, None, None)
    app.conn.close()
    os.unlink(db_path)


def test_viewer_refuses_to_load_the_held_out_recording():
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    db_path, _ = _scratch_db("normal_recording.mat", HELD_OUT_RECORDING_FILE)
    app = _app_on(db_path)
    try:
        assert app.source_file == "normal_recording.mat"
        app.source_file = HELD_OUT_RECORDING_FILE
        assert app.source_file != HELD_OUT_RECORDING_FILE, \
            "the viewer loaded the held-out recording"
        assert "locked" in app.status.object.lower()
    finally:
        _close(app, db_path)


def test_viewer_permits_the_held_out_recording_when_unlocked():
    if not _channel_available():
        pytest.skip(f"real channel data not present: {REAL_CHANNEL_PATH}")
    db_path, _ = _scratch_db(HELD_OUT_RECORDING_FILE)
    with _unlocked():
        app = _app_on(db_path)
        try:
            assert app.source_file == HELD_OUT_RECORDING_FILE
            assert "locked" not in app.status.object.lower()
        finally:
            _close(app, db_path)


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
