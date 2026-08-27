"""
test_database.py
==================
Tests for Working/database/: schema init, the global<->local
index conversion (including the channel-boundary-straddle case), and the
plain CRUD functions.

Run from the project root:
    python tests/test_database.py
"""

import inspect
import os
import sqlite3
import sys
import tempfile

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.database.schema import init_db
from Working.database import schema as sch
from Working.database import queries as q


def _fresh_conn():
    return init_db(":memory:")


# ── global_to_local / boundary-straddle ────────────────────────────────────────

def test_global_to_local_within_first_channel():
    assert q.global_to_local(50, 1000) == (0, 50)


def test_global_to_local_second_channel():
    assert q.global_to_local(1050, 1000) == (1, 50)


def test_global_to_local_exact_boundary():
    # start exactly on a channel boundary belongs to the *next* channel
    assert q.global_to_local(1000, 1000) == (1, 0)


def test_window_straddles_boundary_true():
    # L=1000, window=600, local=700 -> 700+600=1300 > 1000
    assert q.window_straddles_boundary(700, 600, 1000) is True


def test_window_straddles_boundary_false():
    # local=300 -> 300+600=900 <= 1000
    assert q.window_straddles_boundary(300, 600, 1000) is False


def test_window_straddles_boundary_exact_fit():
    # local=400 -> 400+600=1000 == L, not a straddle
    assert q.window_straddles_boundary(400, 600, 1000) is False


# ── schema / recordings ─────────────────────────────────────────────────────────

def test_init_db_is_idempotent():
    conn = _fresh_conn()
    init_db(":memory:")  # separate in-memory db, just checking no error
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    expected = {"recordings", "reviewed_spans", "annotations", "configs",
                "runs", "detections", "encodings", "motifs"}
    assert expected.issubset(tables), tables


def test_insert_recording_idempotent():
    conn = _fresh_conn()
    id1 = q.insert_recording(conn, "rec.mat", 0, 1.0, 1000, 0, "path/CH0.npy")
    id2 = q.insert_recording(conn, "rec.mat", 0, 1.0, 1000, 0, "path/CH0.npy")
    assert id1 == id2
    rows = conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()
    assert rows["n"] == 1


def test_list_recordings_filters_by_source_file():
    conn = _fresh_conn()
    q.insert_recording(conn, "a.mat", 0, 1.0, 100, 0, "a/CH0.npy")
    q.insert_recording(conn, "b.mat", 0, 1.0, 100, 0, "b/CH0.npy")
    rows = q.list_recordings(conn, source_file="a.mat")
    assert len(rows) == 1
    assert rows[0]["source_file"] == "a.mat"


# ── annotations ──────────────────────────────────────────────────────────────

def test_insert_and_list_annotation():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    q.insert_annotation(conn, rid, 10, 610, "interesting", source=q.SOURCE_MANUAL_UI)
    rows = q.list_annotations(conn, rid)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "interesting"


def test_insert_annotation_rejects_bad_verdict():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    try:
        q.insert_annotation(conn, rid, 0, 600, "bogus", source=q.SOURCE_MANUAL_UI)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_annotation_exists():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    assert not q.annotation_exists(conn, rid, 0, 600, q.SOURCE_IMPORTED_10MIN)
    q.insert_annotation(conn, rid, 0, 600, "artifact", source=q.SOURCE_IMPORTED_10MIN)
    assert q.annotation_exists(conn, rid, 0, 600, q.SOURCE_IMPORTED_10MIN)


def test_update_annotation_protects_imported():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    aid = q.insert_annotation(conn, rid, 0, 600, "artifact", source=q.SOURCE_IMPORTED_10MIN)
    try:
        q.update_annotation(conn, aid, verdict="unsure")
        assert False, "expected PermissionError"
    except PermissionError:
        pass
    # force=True is an explicit override
    q.update_annotation(conn, aid, force=True, verdict="unsure")
    assert q.get_annotation(conn, aid)["verdict"] == "unsure"


def test_update_annotation_allows_manual():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    aid = q.insert_annotation(conn, rid, 0, 600, "unsure", source=q.SOURCE_MANUAL_UI)
    q.update_annotation(conn, aid, verdict="interesting", note="edited")
    row = q.get_annotation(conn, aid)
    assert row["verdict"] == "interesting"
    assert row["note"] == "edited"


def test_delete_annotation_protects_imported():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    aid = q.insert_annotation(conn, rid, 0, 600, "artifact", source=q.SOURCE_IMPORTED_10MIN)
    try:
        q.delete_annotation(conn, aid)
        assert False, "expected PermissionError"
    except PermissionError:
        pass
    assert q.get_annotation(conn, aid) is not None


# ── reviewed_spans / summary ─────────────────────────────────────────────────

def test_reviewed_fraction_merges_overlaps():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    q.insert_reviewed_span(conn, rid, 0, 200, source=q.SOURCE_MANUAL_UI)
    q.insert_reviewed_span(conn, rid, 100, 300, source=q.SOURCE_MANUAL_UI)  # overlaps
    q.insert_reviewed_span(conn, rid, 500, 600, source=q.SOURCE_MANUAL_UI)
    # covered = [0,300) + [500,600) = 300 + 100 = 400 out of 1000
    assert q.reviewed_fraction(conn, rid) == 400 / 1000


def test_reviewed_fraction_zero_when_unreviewed():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    assert q.reviewed_fraction(conn, rid) == 0.0


def test_recording_summary_counts():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    q.insert_annotation(conn, rid, 0, 600, "interesting", source=q.SOURCE_MANUAL_UI)
    q.insert_annotation(conn, rid, 100, 700, "artifact", source=q.SOURCE_IMPORTED_10MIN)
    q.insert_annotation(conn, rid, 200, 800, "interesting", source=q.SOURCE_MANUAL_UI)
    summary = q.recording_summary(conn, rid)
    assert summary["interesting"] == 2
    assert summary["artifact"] == 1
    assert summary["not_interesting"] == 0
    assert summary["total"] == 3


# ── schema extension (T02) ──────────────────────────────────────────────────
# Raw INSERTs against the tables directly — this ticket adds no accessors,
# so the constraints are exercised the only way available: SQL.

def _insert_detection(conn, rid, start_idx=0, end_idx=100):
    """Configs -> runs -> detections boilerplate shared by the tests below."""
    cid = conn.execute(
        "INSERT INTO configs (config_hash, config_json, created_at) VALUES (?, ?, ?)",
        (f"hash-{rid}-{start_idx}-{end_idx}", "{}", "2026-01-01T00:00:00"),
    ).lastrowid
    run_id = conn.execute(
        "INSERT INTO runs (config_id, recording_id, span_start, span_end, started_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cid, rid, 0, 1000, "2026-01-01T00:00:00", "done"),
    ).lastrowid
    det_id = conn.execute(
        "INSERT INTO detections (run_id, start_idx, end_idx) VALUES (?, ?, ?)",
        (run_id, start_idx, end_idx),
    ).lastrowid
    conn.commit()
    return det_id


def test_adjudications_unique_per_detection_raises():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    det_id = _insert_detection(conn, rid)
    conn.execute(
        "INSERT INTO adjudications (detection_id, verdict, created_at) VALUES (?, ?, ?)",
        (det_id, "interesting", "2026-01-01T00:00:00"),
    )
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO adjudications (detection_id, verdict, created_at) VALUES (?, ?, ?)",
            (det_id, "artifact", "2026-01-01T00:00:01"),
        )
        assert False, "expected sqlite3.IntegrityError"
    except sqlite3.IntegrityError:
        pass


def test_motif_entry_unique_span_raises():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    conn.execute(
        "INSERT INTO motif_entry (recording_id, start_idx, end_idx) VALUES (?, ?, ?)",
        (rid, 0, 100),
    )
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO motif_entry (recording_id, start_idx, end_idx) VALUES (?, ?, ?)",
            (rid, 0, 100),
        )
        assert False, "expected sqlite3.IntegrityError"
    except sqlite3.IntegrityError:
        pass


def test_step_artifacts_unique_key_raises():
    conn = _fresh_conn()
    conn.execute(
        "INSERT INTO step_artifacts (recipe_prefix_hash, step_index, path) VALUES (?, ?, ?)",
        ("abc123", 0, "Plots/step0.png"),
    )
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO step_artifacts (recipe_prefix_hash, step_index, path) VALUES (?, ?, ?)",
            ("abc123", 0, "Plots/step0_dup.png"),
        )
        assert False, "expected sqlite3.IntegrityError"
    except sqlite3.IntegrityError:
        pass


def test_motif_member_accepts_different_recording_and_channel():
    conn = _fresh_conn()
    rid_a = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    rid_b = q.insert_recording(conn, "a.mat", 1, 1.0, 1000, 0, "a/CH1.npy")
    entry_id = conn.execute(
        "INSERT INTO motif_entry (recording_id, start_idx, end_idx) VALUES (?, ?, ?)",
        (rid_a, 0, 100),
    ).lastrowid
    conn.commit()
    # The member's recording (and therefore channel) differs from the entry's.
    conn.execute(
        "INSERT INTO motif_member (entry_id, recording_id, start_idx, end_idx) "
        "VALUES (?, ?, ?, ?)",
        (entry_id, rid_b, 50, 150),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM motif_member WHERE entry_id = ?", (entry_id,)
    ).fetchone()
    assert row is not None
    assert row["recording_id"] == rid_b
    assert row["recording_id"] != rid_a
    assert row["start_idx"] == 50
    assert row["end_idx"] == 150


# ── T52: motif_entry scale column (event-scale vs train-scale) ───────────────

def test_motif_entry_has_scale_column():
    conn = _fresh_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(motif_entry)")}
    assert "scale" in cols


def test_motif_entry_scale_column_is_nullable():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    conn.execute(
        "INSERT INTO motif_entry (recording_id, start_idx, end_idx) VALUES (?, ?, ?)",
        (rid, 0, 100),
    )
    conn.commit()
    row = conn.execute("SELECT scale FROM motif_entry LIMIT 1").fetchone()
    assert row["scale"] is None


def test_motif_entry_scale_column_accepts_event_and_train():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    conn.execute(
        "INSERT INTO motif_entry (recording_id, start_idx, end_idx, scale) "
        "VALUES (?, ?, ?, ?)",
        (rid, 0, 100, sch.ENTRY_SCALE_EVENT),
    )
    conn.execute(
        "INSERT INTO motif_entry (recording_id, start_idx, end_idx, scale) "
        "VALUES (?, ?, ?, ?)",
        (rid, 200, 300, sch.ENTRY_SCALE_TRAIN),
    )
    conn.commit()
    scales = {r["scale"] for r in conn.execute("SELECT scale FROM motif_entry")}
    assert scales == {"event", "train"}
    assert sch.ENTRY_SCALE_EVENT == "event"
    assert sch.ENTRY_SCALE_TRAIN == "train"


def test_init_db_adds_scale_column_once():
    path = _temp_db_path()
    try:
        conn = init_db(path)
        cols1 = {r["name"] for r in conn.execute("PRAGMA table_info(motif_entry)")}
        conn.close()
        conn = init_db(path)
        cols2 = {r["name"] for r in conn.execute("PRAGMA table_info(motif_entry)")}
        conn.close()
        assert cols1 == cols2
        assert "scale" in cols2
    finally:
        _cleanup(path)


def test_init_db_idempotent_preserves_all_row_counts():
    # Unlike the presence check above, this hits a real on-disk db twice —
    # ":memory:" makes a fresh anonymous database per connection, which
    # can't demonstrate idempotency against a *populated* database.
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    os.remove(path)
    try:
        conn = init_db(path)
        rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
        q.insert_annotation(conn, rid, 0, 600, "interesting", source=q.SOURCE_MANUAL_UI)
        tag_id = conn.execute(
            "INSERT INTO tag_vocabulary (category, value) VALUES (?, ?)",
            ("element", "spike"),
        ).lastrowid
        ann_id = conn.execute("SELECT id FROM annotations LIMIT 1").fetchone()["id"]
        conn.execute(
            "INSERT INTO annotation_tags (annotation_id, tag_id) VALUES (?, ?)",
            (ann_id, tag_id),
        )
        conn.commit()
        conn.close()

        def _counts():
            c = sqlite3.connect(path)
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
            c.close()
            return counts

        before = _counts()
        init_db(path).close()
        after = _counts()
        assert after == before, (before, after)
    finally:
        if os.path.exists(path):
            os.remove(path)


# -- T04: verdict-constraint rebuild (add `seed`) ------------------------------
#
# SQLite cannot ALTER a CHECK constraint in place, so widening the annotations
# verdict vocabulary means the full table-rebuild procedure against a table that
# five ALTER TABLE ADD COLUMN migrations have already extended. The failure mode
# these tests exist to catch is the quiet one: a rebuild that succeeds, reports
# nothing wrong, and drops a column's values or an annotation_tags link on the
# floor. Every assertion below is a before/after identity, not a spot-check.

# The `annotations` DDL exactly as it stands in the live database today: the
# original CREATE TABLE with the four-term CHECK, plus the five columns appended
# by `_ANNOTATIONS_NEW_COLUMNS` via ALTER TABLE. Reproduced verbatim (including
# the comma placement ALTER TABLE produces) so the fixture meets the migration
# in the same shape the real file will.
_LEGACY_ANNOTATIONS_DDL = """
CREATE TABLE annotations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id),
    start_idx     INTEGER NOT NULL,
    end_idx       INTEGER NOT NULL,
    verdict       TEXT    NOT NULL CHECK (verdict IN
                      ('interesting', 'not_interesting', 'artifact', 'unsure')),
    tag           TEXT,
    note          TEXT,
    scale_viewed  TEXT,
    source        TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
, event_count INTEGER, parent_annotation_id INTEGER REFERENCES annotations(id), status TEXT, relation_kind TEXT CHECK (relation_kind IN ('type_specimen', 'sub_window') OR relation_kind IS NULL), deleted_at TEXT)
"""

_LEGACY_INDEXES = [
    "CREATE INDEX idx_annotations_recording ON annotations(recording_id)",
    "CREATE INDEX idx_annotations_verdict   ON annotations(verdict)",
]

# The `motif_entry` table as it stands before ticket 52: the shape-first
# library table with its legacy presentation columns but no `scale` column.
# Reproduced so the additive migration can be verified against a database
# that predates the change.
_LEGACY_MOTIF_ENTRY_DDL = """
CREATE TABLE motif_entry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id),
    start_idx     INTEGER NOT NULL,
    end_idx       INTEGER NOT NULL,
    detection_id  INTEGER REFERENCES detections(id),
    label         TEXT,
    rating        INTEGER,
    notes         TEXT,
    tags          TEXT,
    sax_string    TEXT,
    created_at    TEXT,
    UNIQUE (recording_id, start_idx, end_idx)
);
"""


def _make_legacy_db(path):
    """Build a pre-rebuild database that resembles the real one where it matters.

    Rows carry every added column; one row is soft-deleted (`deleted_at` set);
    two rows are children of another via `parent_annotation_id`; tag links span
    several annotations; and there is at least one row per legacy verdict term.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_LEGACY_ANNOTATIONS_DDL)
    for stmt in _LEGACY_INDEXES:
        conn.execute(stmt)
    # Everything else comes from the real schema; `IF NOT EXISTS` leaves the
    # legacy annotations table alone.
    conn.executescript(sch._SCHEMA)

    conn.execute(
        "INSERT INTO recordings (id, source_file, channel, fs, n_samples, "
        "global_offset, npy_path) VALUES (1, 'a.mat', 0, 1.0, 100000, 0, 'a/CH0.npy')"
    )
    rows = [
        # id, start, end, verdict, tag, note, scale, source, created,
        #     event_count, parent, status, relation_kind, deleted_at
        (1, 10, 610, "interesting", "spike", "n1", "1min", "manual_ui", "t1",
         3, None, "reviewed", None, None),
        (2, 700, 1300, "not_interesting", None, None, "1min", "imported_10min", "t2",
         0, None, None, None, None),
        (3, 1400, 2000, "artifact", "noise", "n3", "3min", "manual_ui", "t3",
         None, 1, "flagged", "sub_window", None),
        (4, 2100, 2700, "unsure", None, "n4", "10min", "manual_ui", "t4",
         7, None, None, "type_specimen", None),
        # Soft-deleted: `deleted_at` non-null must survive the rebuild, or the
        # undo behind `delete_annotation` quietly becomes a hard delete.
        (5, 2800, 3400, "interesting", "burst", None, "1min", "manual_ui", "t5",
         2, 1, "reviewed", None, "2026-08-01T00:00:00+00:00"),
    ]
    conn.executemany(
        "INSERT INTO annotations (id, start_idx, end_idx, verdict, tag, note, "
        "scale_viewed, source, created_at, event_count, parent_annotation_id, "
        "status, relation_kind, deleted_at, recording_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
        rows,
    )
    conn.execute("INSERT INTO tag_vocabulary (id, category, value) VALUES (1, 'element', 'spike')")
    conn.execute("INSERT INTO tag_vocabulary (id, category, value) VALUES (2, 'element', 'burst')")
    conn.executemany(
        "INSERT INTO annotation_tags (annotation_id, tag_id) VALUES (?, ?)",
        [(1, 1), (1, 2), (3, 1), (5, 2)],
    )
    conn.commit()
    conn.close()


def _annotation_snapshot(path):
    """Everything a rebuild could quietly lose, as comparable Python values."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(annotations)")]
    snap = {
        "columns": set(cols),
        "n_annotations": conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0],
        "n_links": conn.execute("SELECT COUNT(*) FROM annotation_tags").fetchone()[0],
        "tuples": sorted(
            tuple(r) for r in conn.execute(
                "SELECT id, start_idx, end_idx, verdict FROM annotations")
        ),
        "links": sorted(
            tuple(r) for r in conn.execute(
                "SELECT annotation_id, tag_id FROM annotation_tags")
        ),
        "full_rows": sorted(
            tuple(str(r[c]) for c in sorted(cols))
            for r in conn.execute("SELECT * FROM annotations")
        ),
        "indexes": set(
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='annotations' AND name NOT LIKE 'sqlite_%'")
        ),
    }
    conn.close()
    return snap


def _temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    os.remove(path)
    return path


def _backups_for(path):
    d = os.path.dirname(path) or "."
    base = os.path.basename(path)
    return sorted(f for f in os.listdir(d)
                  if f.startswith(base) and f.endswith(".bak"))


def _cleanup(path):
    d = os.path.dirname(path) or "."
    for f in [os.path.basename(path)] + _backups_for(path):
        fp = os.path.join(d, f)
        if os.path.exists(fp):
            os.remove(fp)


def test_verdict_vocabulary_is_one_shared_constant():
    # Ticket 19 shares this vocabulary. Two literals that happen to agree today
    # are the bug; the annotation path and the adjudication path must read the
    # same object.
    assert sch.VERDICTS is q.VERDICTS
    assert set(sch.VERDICTS) == set(
        ["seed", "interesting", "not_interesting", "artifact", "unsure"])


def test_insert_annotation_accepts_seed():
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    q.insert_annotation(conn, rid, 10, 610, "seed", source=q.SOURCE_MANUAL_UI)
    rows = q.list_annotations(conn, rid)
    assert [r["verdict"] for r in rows] == ["seed"]


def test_fresh_schema_check_constraint_accepts_exactly_the_five_terms():
    # Straight at the CHECK constraint, bypassing the Python-side guard in
    # insert_annotation -- a validation that only lives in queries.py leaves the
    # database itself willing to store anything.
    conn = _fresh_conn()
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 1000, 0, "a/CH0.npy")
    for i, verdict in enumerate(sch.VERDICTS):
        conn.execute(
            "INSERT INTO annotations (recording_id, start_idx, end_idx, verdict, "
            "source, created_at) VALUES (?,?,?,?,'manual_ui','t')",
            (rid, i * 100, i * 100 + 50, verdict),
        )
    try:
        conn.execute(
            "INSERT INTO annotations (recording_id, start_idx, end_idx, verdict, "
            "source, created_at) VALUES (?,9000,9100,'bogus','manual_ui','t')",
            (rid,),
        )
        assert False, "CHECK constraint should reject an unknown verdict"
    except sqlite3.IntegrityError:
        pass


def test_verdict_rebuild_preserves_every_row_and_link():
    path = _temp_db_path()
    try:
        _make_legacy_db(path)
        before = _annotation_snapshot(path)
        probe = sqlite3.connect(path)
        legacy_sql = probe.execute(
            "SELECT sql FROM sqlite_master WHERE name='annotations'").fetchone()[0]
        probe.close()
        assert "seed" not in legacy_sql, "fixture is not pre-rebuild"

        init_db(path).close()
        after = _annotation_snapshot(path)

        assert after["n_annotations"] == before["n_annotations"] == 5
        assert after["tuples"] == before["tuples"]
        assert after["n_links"] == before["n_links"] == 4
        assert after["links"] == before["links"]
    finally:
        _cleanup(path)


def test_verdict_rebuild_preserves_added_columns_and_soft_deleted_rows():
    path = _temp_db_path()
    try:
        _make_legacy_db(path)
        before = _annotation_snapshot(path)

        init_db(path).close()
        after = _annotation_snapshot(path)

        # Same columns, and every value in every column identical -- this is the
        # assertion that catches a column missing from the INSERT ... SELECT.
        assert after["columns"] == before["columns"]
        assert after["full_rows"] == before["full_rows"]

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        deleted = conn.execute(
            "SELECT * FROM annotations WHERE deleted_at IS NOT NULL").fetchall()
        assert len(deleted) == 1
        assert deleted[0]["id"] == 5
        assert deleted[0]["deleted_at"] == "2026-08-01T00:00:00+00:00"
        assert deleted[0]["parent_annotation_id"] == 1
        assert deleted[0]["status"] == "reviewed"
        assert deleted[0]["event_count"] == 2
        conn.close()
    finally:
        _cleanup(path)


def test_verdict_rebuild_recreates_indexes_and_accepts_seed_afterwards():
    path = _temp_db_path()
    try:
        _make_legacy_db(path)
        before = _annotation_snapshot(path)

        conn = init_db(path)
        after = _annotation_snapshot(path)
        # SQLite drops a table's indexes along with the table and says nothing.
        assert after["indexes"] == before["indexes"]

        q.insert_annotation(conn, 1, 5000, 5600, "seed", source=q.SOURCE_MANUAL_UI)
        assert conn.execute(
            "SELECT COUNT(*) FROM annotations WHERE verdict='seed'").fetchone()[0] == 1
        conn.close()
    finally:
        _cleanup(path)


def test_verdict_rebuild_backs_up_the_database_first():
    path = _temp_db_path()
    try:
        _make_legacy_db(path)
        before = _annotation_snapshot(path)
        assert _backups_for(path) == []

        init_db(path).close()

        backups = _backups_for(path)
        assert len(backups) == 1, backups
        backup_path = os.path.join(os.path.dirname(path) or ".", backups[0])
        # A backup nobody has opened is a hypothesis.
        restored = _annotation_snapshot(backup_path)
        assert restored["tuples"] == before["tuples"]
        assert restored["links"] == before["links"]
    finally:
        _cleanup(path)


def test_verdict_rebuild_is_idempotent():
    path = _temp_db_path()
    try:
        _make_legacy_db(path)
        init_db(path).close()
        once = _annotation_snapshot(path)
        backups_once = _backups_for(path)

        init_db(path).close()
        twice = _annotation_snapshot(path)

        assert twice == once
        # A second rebuild would be harmless but wrong: it would re-copy 11k
        # rows and drop a fresh backup on every startup forever.
        assert _backups_for(path) == backups_once
    finally:
        _cleanup(path)


def test_legacy_motif_entry_gains_scale_column():
    # A database created before T52 has a `motif_entry` without `scale`;
    # `init_db()` must add the column when it next runs.
    path = _temp_db_path()
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_LEGACY_MOTIF_ENTRY_DDL)
        conn.executescript(sch._SCHEMA)
        conn.commit()
        conn.close()

        probe = sqlite3.connect(path)
        probe.row_factory = sqlite3.Row
        try:
            cols_before = {r["name"] for r in probe.execute(
                "PRAGMA table_info(motif_entry)")}
        finally:
            probe.close()
        assert "scale" not in cols_before

        init_db(path).close()

        probe = sqlite3.connect(path)
        probe.row_factory = sqlite3.Row
        try:
            cols_after = {r["name"] for r in probe.execute(
                "PRAGMA table_info(motif_entry)")}
        finally:
            probe.close()
        assert "scale" in cols_after
    finally:
        _cleanup(path)


# ── runner ───────────────────────────────────────────────────────────────────

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
