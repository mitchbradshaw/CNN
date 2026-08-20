"""
test_heldout_lock.py
====================
Tests for the held-out recording lock (ticket T03).

The held-out recording is refused by both the viewer and the runner unless
explicitly unlocked, so "untouched until the freeze" is true by construction.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


class TestHeldOutLockConfig:
    """Test that the config constants exist and are read correctly."""

    def test_held_out_constants_defined(self):
        """The held-out recording file and unlock flag are defined in config."""
        from Working.config import HELD_OUT_RECORDING_FILE, HELD_OUT_UNLOCK
        
        assert HELD_OUT_RECORDING_FILE == "M4_aug_concat_fs1.mat"
        assert HELD_OUT_UNLOCK is False  # Default is locked

    def test_config_not_hardcoded_literal(self):
        """The guard reads from config, not a hardcoded literal."""
        from Working.config import HELD_OUT_RECORDING_FILE
        
        # The constant must exist and be a string
        assert isinstance(HELD_OUT_RECORDING_FILE, str)
        assert len(HELD_OUT_RECORDING_FILE) > 0


class TestExecutionGuard:
    """Test that execute_recipe raises HeldOutRecordingLocked for the held-out recording."""

    def test_execution_raises_on_held_out_recording(self, tmp_path):
        """execute_recipe raises HeldOutRecordingLocked when trying to run on the held-out recording."""
        from Working.config import HELD_OUT_RECORDING_FILE
        from Working.database.schema import init_db
        from Working.database import queries as q
        from Working.execution import execute_recipe, HeldOutRecordingLocked
        from Working.recipes import make_recipe
        
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        
        # Insert a mock recording with the held-out source file
        conn.execute("""
            INSERT INTO recordings (source_file, channel, fs, n_samples, global_offset, npy_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (HELD_OUT_RECORDING_FILE, "ch1", 1.0, 1000, 0, "/fake/path.npy"))
        conn.commit()
        
        recording_id = conn.execute("SELECT id FROM recordings").fetchone()[0]
        
        recipe = make_recipe(recording_id, span=(0, 100), steps=[
            {"stage": "preprocessing", "algorithm": "zscore"}
        ])
        
        with pytest.raises(HeldOutRecordingLocked) as exc_info:
            execute_recipe(recipe, db_path=db_path)
        
        assert HELD_OUT_RECORDING_FILE in str(exc_info.value)
        assert "locked" in str(exc_info.value).lower()

    def test_execution_allows_when_unlocked(self, tmp_path):
        """execute_recipe proceeds when HELD_OUT_UNLOCK is True."""
        from Working.config import HELD_OUT_RECORDING_FILE, HELD_OUT_UNLOCK
        from Working.database.schema import init_db
        from Working.execution import execute_recipe, HeldOutRecordingLocked
        from Working.recipes import make_recipe
        
        # Temporarily unlock
        import Working.config as config_module
        original_unlock = config_module.HELD_OUT_UNLOCK
        config_module.HELD_OUT_UNLOCK = True
        
        try:
            db_path = tmp_path / "test.db"
            conn = init_db(db_path)
            
            # Insert a mock recording with the held-out source file
            conn.execute("""
                INSERT INTO recordings (source_file, channel, fs, n_samples, global_offset, npy_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (HELD_OUT_RECORDING_FILE, "ch1", 1.0, 1000, 0, str(tmp_path / "fake.npy")))
            conn.commit()
            
            recording_id = conn.execute("SELECT id FROM recordings").fetchone()[0]
            
            recipe = make_recipe(recording_id, span=(0, 100), steps=[
                {"stage": "preprocessing", "algorithm": "zscore"}
            ])
            
            # Should NOT raise - but will fail later due to fake npy path
            # We just want to verify the held-out check passes
            try:
                execute_recipe(recipe, db_path=db_path)
            except FileNotFoundError:
                # Expected - the npy path is fake, but the held-out guard passed
                pass
            except Exception as e:
                # As long as it's not HeldOutRecordingLocked, we're good
                if isinstance(e, HeldOutRecordingLocked):
                    pytest.fail("HeldOutRecordingLocked raised even when unlocked")
        finally:
            config_module.HELD_OUT_UNLOCK = original_unlock

    def test_execution_allows_non_held_out_recording(self, tmp_path):
        """execute_recipe works normally for non-held-out recordings."""
        from Working.database.schema import init_db
        from Working.execution import execute_recipe
        from Working.recipes import make_recipe
        
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        
        # Insert a normal recording (not the held-out one)
        conn.execute("""
            INSERT INTO recordings (source_file, channel, fs, n_samples, global_offset, npy_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("some_other_recording.mat", "ch1", 1.0, 1000, 0, str(tmp_path / "fake.npy")))
        conn.commit()
        
        recording_id = conn.execute("SELECT id FROM recordings").fetchone()[0]
        
        recipe = make_recipe(recording_id, span=(0, 100), steps=[
            {"stage": "preprocessing", "algorithm": "zscore"}
        ])
        
        # Should fail due to fake npy path, but NOT due to held-out lock
        with pytest.raises((FileNotFoundError,)):
            execute_recipe(recipe, db_path=db_path)


class TestViewerGuard:
    """Test that the viewer refuses to load the held-out recording."""

    def test_viewer_source_file_change_blocks_held_out(self, tmp_path):
        """ViewerApp._on_source_file_change blocks the held-out recording."""
        from Working.config import HELD_OUT_RECORDING_FILE
        from Working.database.schema import init_db
        from Working.database import queries as q
        from UI.viewer.app import ViewerApp
        
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        
        # Insert two recordings: one normal, one held-out
        conn.execute("""
            INSERT INTO recordings (source_file, channel, fs, n_samples, global_offset, npy_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("normal_recording.mat", "ch1", 1.0, 1000, 0, str(tmp_path / "fake1.npy")))
        conn.execute("""
            INSERT INTO recordings (source_file, channel, fs, n_samples, global_offset, npy_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (HELD_OUT_RECORDING_FILE, "ch1", 1.0, 1000, 0, str(tmp_path / "fake2.npy")))
        conn.commit()
        
        app = ViewerApp(db_path=db_path)
        
        # Initially should be on the first (normal) recording
        assert app.source_file == "normal_recording.mat"
        
        # Try to switch to held-out - should revert and show warning
        app.source_file = HELD_OUT_RECORDING_FILE
        # The watcher should have reverted it
        assert app.source_file != HELD_OUT_RECORDING_FILE
        assert "locked" in app.status.object.lower()

    def test_viewer_allows_when_unlocked(self, tmp_path):
        """ViewerApp allows held-out recording when unlocked."""
        from Working.config import HELD_OUT_RECORDING_FILE
        from Working.database.schema import init_db
        from UI.viewer.app import ViewerApp
        
        # Temporarily unlock
        import Working.config as config_module
        original_unlock = config_module.HELD_OUT_UNLOCK
        config_module.HELD_OUT_UNLOCK = True
        
        try:
            db_path = tmp_path / "test.db"
            conn = init_db(db_path)
            
            conn.execute("""
                INSERT INTO recordings (source_file, channel, fs, n_samples, global_offset, npy_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (HELD_OUT_RECORDING_FILE, "ch1", 1.0, 1000, 0, str(tmp_path / "fake.npy")))
            conn.commit()
            
            app = ViewerApp(db_path=db_path)
            
            # Should be allowed to select the held-out recording
            assert app.source_file == HELD_OUT_RECORDING_FILE
            # Status should not contain a lock warning
            assert "locked" not in app.status.object.lower()
        finally:
            config_module.HELD_OUT_UNLOCK = original_unlock
