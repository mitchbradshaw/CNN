"""
test_motif_migration.py
========================
Tests for the shape-first library migration (ticket 16): legacy
detection-keyed `motifs` rows become `motif_entry` rows identified by
recording + sample range, their `motif_tags` links become
`motif_entry_tags` links, and the migration is idempotent.

The migration runs inside `init_db()`, so these tests exercise it the same
way the application does -- by re-opening a scratch database -- rather than
calling a private migration helper directly.
"""

import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.database import vocabulary as v


def _insert_legacy_motif(conn, recording_id, start, end, *, label, tags,
                         rating, notes, sax_string, tag_values):
    """Insert one old-style `motifs` row plus its `motif_tags` links.

    Uses raw SQL rather than `R.insert_motif` so the test keeps exercising
    the migration of pre-existing rows, independent of whichever helper the
    UI happens to use today.
    """
    config_id = conn.execute(
        "INSERT INTO configs (config_hash, config_json, created_at) "
        "VALUES (?, ?, ?)",
        ("legacy-{}".format(len(conn.execute(
            "SELECT 1 FROM motifs").fetchall())), "{}", "2026-01-01T00:00:00"),
    ).lastrowid
    run_id = conn.execute(
        "INSERT INTO runs (config_id, recording_id, span_start, span_end, "
        "started_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        (config_id, recording_id, start, end, "2026-01-01T00:00:00", "completed"),
    ).lastrowid
    detection_id = conn.execute(
        "INSERT INTO detections (run_id, start_idx, end_idx, score, meta_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (run_id, start, end, 0.5, None),
    ).lastrowid
    motif_id = conn.execute(
        "INSERT INTO motifs (detection_id, label, tags, rating, notes, "
        "sax_string, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (detection_id, label, tags, rating, notes, sax_string, "2026-01-01T00:00:00"),
    ).lastrowid
    for value in tag_values:
        term_id = v.get_or_create_term(conn, "element", value)
        conn.execute(
            "INSERT OR IGNORE INTO motif_tags (motif_id, tag_id) VALUES (?, ?)",
            (motif_id, term_id),
        )
    conn.commit()
    return motif_id, detection_id


def _setup_legacy_db(db_path):
    conn = init_db(db_path)
    v.seed_vocabulary(conn)
    recording_id = q.insert_recording(
        conn, "legacy.mat", 0, 1.0, 1000, 0, "legacy/CH0.npy",
    )
    _insert_legacy_motif(
        conn, recording_id, 0, 100,
        label="legacy A", tags="free-text-a", rating=4, notes="note A",
        sax_string="abc", tag_values=["sharkfin", "ridge"],
    )
    _insert_legacy_motif(
        conn, recording_id, 200, 300,
        label="legacy B", tags="free-text-b", rating=2, notes="note B",
        sax_string="xyz", tag_values=["ridge"],
    )
    conn.close()
    return recording_id


def _entry_tags(conn, entry_id):
    return {
        row["value"]
        for row in conn.execute(
            "SELECT v.value FROM motif_entry_tags t "
            "JOIN tag_vocabulary v ON v.id = t.tag_id "
            "WHERE t.entry_id = ? ORDER BY v.value",
            (entry_id,),
        )
    }


def _legacy_tags(conn, motif_id):
    return {
        row["value"]
        for row in conn.execute(
            "SELECT v.value FROM motif_tags t "
            "JOIN tag_vocabulary v ON v.id = t.tag_id "
            "WHERE t.motif_id = ? ORDER BY v.value",
            (motif_id,),
        )
    }


def test_backfill_carries_rows_tags_and_legacy_fields():
    tmpdir = tempfile.mkdtemp(prefix="motif_migration_test_")
    db_path = os.path.join(tmpdir, "test.sqlite")
    try:
        recording_id = _setup_legacy_db(db_path)

        # Re-opening the database runs the same `init_db()` migration path
        # the application hits on startup.
        conn = init_db(db_path)
        entries = conn.execute(
            "SELECT * FROM motif_entry WHERE recording_id = ? ORDER BY start_idx",
            (recording_id,),
        ).fetchall()

        assert len(entries) == 2, [dict(e) for e in entries]

        legacy_motifs = conn.execute(
            "SELECT id FROM motifs ORDER BY id"
        ).fetchall()
        assert len(legacy_motifs) == 2

        by_span = {(e["start_idx"], e["end_idx"]): e for e in entries}
        for motif in legacy_motifs:
            legacy = conn.execute(
                """SELECT m.*, d.start_idx, d.end_idx, d.id AS detection_id
                   FROM motifs m JOIN detections d ON d.id = m.detection_id
                   WHERE m.id = ?""",
                (motif["id"],),
            ).fetchone()
            entry = by_span[(legacy["start_idx"], legacy["end_idx"])]

            # Identity moved from detection-keyed to recording + sample range.
            assert entry["recording_id"] == recording_id
            # Detection pointer retained as provenance.
            assert entry["detection_id"] == legacy["detection_id"]

            # Legacy columns are carried across, not silently lost.
            assert entry["label"] == legacy["label"]
            assert entry["rating"] == legacy["rating"]
            assert entry["notes"] == legacy["notes"]
            assert entry["tags"] == legacy["tags"]
            assert entry["sax_string"] == legacy["sax_string"]

            # Tag links moved table-for-table, with identical values.
            assert _entry_tags(conn, entry["id"]) == _legacy_tags(conn, motif["id"])

        # Identical link counts across the two tables, not just per-entry values.
        assert conn.execute("SELECT COUNT(*) FROM motif_tags").fetchone()[0] == \
            conn.execute("SELECT COUNT(*) FROM motif_entry_tags").fetchone()[0]

        conn.close()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_backfill_is_idempotent():
    tmpdir = tempfile.mkdtemp(prefix="motif_migration_test_")
    db_path = os.path.join(tmpdir, "test.sqlite")
    try:
        _setup_legacy_db(db_path)

        conn = init_db(db_path)
        entries_a = conn.execute("SELECT COUNT(*) FROM motif_entry").fetchone()[0]
        links_a = conn.execute("SELECT COUNT(*) FROM motif_entry_tags").fetchone()[0]
        conn.close()

        conn = init_db(db_path)
        entries_b = conn.execute("SELECT COUNT(*) FROM motif_entry").fetchone()[0]
        links_b = conn.execute("SELECT COUNT(*) FROM motif_entry_tags").fetchone()[0]
        conn.close()

        assert entries_a == 2
        assert entries_b == entries_a
        assert links_b == links_a
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_entry_can_be_created_without_detection_pointer():
    conn = init_db(":memory:")
    recording_id = q.insert_recording(
        conn, "eye.mat", 0, 1.0, 1000, 0, "eye/CH0.npy",
    )
    entry_id = R.insert_motif_entry(conn, recording_id, 10, 20)
    entry = R.get_motif_entry(conn, entry_id)

    assert entry is not None
    assert entry["recording_id"] == recording_id
    assert entry["start_idx"] == 10
    assert entry["end_idx"] == 20
    assert entry["detection_id"] is None
