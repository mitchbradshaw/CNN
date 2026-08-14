"""
schema.py
=========
SQLite schema for the annotation/labelling database and the run-tracking
tables the next project phase (algorithm runs, detections, cached encodings)
will write to.

`configs`, `runs`, `detections`, `encodings` and `motifs` are created now so
that phase needs no migration, but nothing here writes to them yet.

No ORM — plain `sqlite3`, callable from scripts and the UI alike.

Migrations
----------
`init_db()` is always additive and safe to call repeatedly: base tables use
`CREATE TABLE IF NOT EXISTS`, and anything added to an *existing* table
(new columns on `annotations`, as of the tag-vocabulary feature) is applied
by `_migrate_annotations_columns`, which checks `PRAGMA table_info` first and
only adds what's missing. Nothing here ever drops or rewrites a column, so
existing rows are untouched.
"""

import os
import sqlite3

DB_PATH = os.path.join("DATA", "db", "annotations.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file   TEXT    NOT NULL,
    channel       INTEGER NOT NULL,
    fs            REAL    NOT NULL,
    n_samples     INTEGER NOT NULL,
    global_offset INTEGER NOT NULL,
    npy_path      TEXT    NOT NULL,
    notes         TEXT,
    UNIQUE (source_file, channel)
);

CREATE TABLE IF NOT EXISTS reviewed_spans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id),
    start_idx     INTEGER NOT NULL,
    end_idx       INTEGER NOT NULL,
    scale_viewed  TEXT,
    source        TEXT    NOT NULL,
    reviewed_at   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviewed_spans_recording ON reviewed_spans(recording_id);

CREATE TABLE IF NOT EXISTS annotations (
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
);
CREATE INDEX IF NOT EXISTS idx_annotations_recording ON annotations(recording_id);
CREATE INDEX IF NOT EXISTS idx_annotations_verdict   ON annotations(verdict);

CREATE TABLE IF NOT EXISTS configs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    config_hash   TEXT    NOT NULL UNIQUE,
    config_json   TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id     INTEGER NOT NULL REFERENCES configs(id),
    recording_id  INTEGER NOT NULL REFERENCES recordings(id),
    span_start    INTEGER NOT NULL,
    span_end      INTEGER NOT NULL,
    started_at    TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    artifact_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_recording ON runs(recording_id);

-- One row per saved artifact (plot, cached encoding, model, csv, ...)
-- produced by a run. `path` is relative to the repo root so it stays
-- portable across machines running the same recipe.
CREATE TABLE IF NOT EXISTS artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    kind          TEXT    NOT NULL CHECK (kind IN
                      ('plot', 'encoding', 'model', 'csv', 'other')),
    path          TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);

CREATE TABLE IF NOT EXISTS detections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    start_idx     INTEGER NOT NULL,
    end_idx       INTEGER NOT NULL,
    score         REAL,
    meta_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_detections_run ON detections(run_id);

CREATE TABLE IF NOT EXISTS encodings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id),
    span_start    INTEGER NOT NULL,
    span_end      INTEGER NOT NULL,
    encoding_type TEXT    NOT NULL,
    config_hash   TEXT    NOT NULL,
    path          TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_encodings_recording ON encodings(recording_id);

CREATE TABLE IF NOT EXISTS motifs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    detection_id  INTEGER NOT NULL REFERENCES detections(id),
    label         TEXT,
    tags          TEXT,
    rating        INTEGER,
    notes         TEXT,
    created_at    TEXT    NOT NULL
);

-- Many-to-many: a motif's element tags, via the same controlled vocabulary
-- as annotations (`tag_vocabulary`). Separate from `annotation_tags` because
-- a motif and an annotation are different entities with different ids, not
-- because the tagging concept differs. The legacy `motifs.tags` TEXT column
-- (free text, pre-dating the vocabulary) is left alone.
CREATE TABLE IF NOT EXISTS motif_tags (
    motif_id INTEGER NOT NULL REFERENCES motifs(id),
    tag_id   INTEGER NOT NULL REFERENCES tag_vocabulary(id),
    PRIMARY KEY (motif_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_motif_tags_tag ON motif_tags(tag_id);

-- Controlled vocabulary: element / quality / structure / provenance / status
-- terms, editable through the admin panel rather than hardcoded. Deactivating
-- a term (active=0) is a soft-delete — existing annotation_tags rows
-- referencing it are never removed.
CREATE TABLE IF NOT EXISTS tag_vocabulary (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    category      TEXT    NOT NULL,
    value         TEXT    NOT NULL,
    description   TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    UNIQUE (category, value)
);
CREATE INDEX IF NOT EXISTS idx_tag_vocabulary_category ON tag_vocabulary(category);

-- Many-to-many: an annotation can carry several element tags (multi-select),
-- exactly one quality/structure/provenance tag in practice (the UI enforces
-- single-select for those categories; the schema doesn't need to, since
-- "at most one per category" is a UI/import-time rule, not a storage one).
CREATE TABLE IF NOT EXISTS annotation_tags (
    annotation_id INTEGER NOT NULL REFERENCES annotations(id),
    tag_id        INTEGER NOT NULL REFERENCES tag_vocabulary(id),
    PRIMARY KEY (annotation_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_annotation_tags_tag ON annotation_tags(tag_id);
"""

# Columns added to the original `annotations` table by the tag-vocabulary
# feature. Applied via ALTER TABLE ADD COLUMN, guarded by a PRAGMA
# table_info check so re-running is a no-op — CREATE TABLE IF NOT EXISTS
# doesn't help for columns added to a table that already exists.
_ANNOTATIONS_NEW_COLUMNS = [
    ("event_count", "INTEGER"),
    ("parent_annotation_id", "INTEGER REFERENCES annotations(id)"),
    ("status", "TEXT"),
    ("relation_kind", "TEXT CHECK (relation_kind IN ('type_specimen', 'sub_window') "
                       "OR relation_kind IS NULL)"),
    # Part E7: soft delete — NULL means "not deleted". `delete_annotation`
    # sets this instead of removing the row, so an accidental delete has an
    # undo. `list_annotations` excludes non-NULL rows by default.
    ("deleted_at", "TEXT"),
]

# Columns added to `runs` by the run-tracking/provenance feature (part 2).
_RUNS_NEW_COLUMNS = [
    ("finished_at", "TEXT"),
    ("duration_s", "REAL"),
    ("error_text", "TEXT"),
    ("step_timings_json", "TEXT"),
]

# `motifs` += the symbolic SAX string, when one exists for the motif's span.
_MOTIFS_NEW_COLUMNS = [
    ("sax_string", "TEXT"),
]


def _migrate_columns(conn, table, new_columns):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, coltype in new_columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")
    conn.commit()


def _migrate_annotations_columns(conn):
    _migrate_columns(conn, "annotations", _ANNOTATIONS_NEW_COLUMNS)


def _migrate_runs_columns(conn):
    _migrate_columns(conn, "runs", _RUNS_NEW_COLUMNS)


def _migrate_motifs_columns(conn):
    _migrate_columns(conn, "motifs", _MOTIFS_NEW_COLUMNS)


def get_connection(db_path=None):
    """Open a connection with row access by column name and FKs enforced.

    Parameters
    ----------
    db_path : str, optional
        Defaults to `DB_PATH` (DATA/db/annotations.sqlite). Pass ":memory:"
        or a temp path for tests.
    """
    db_path = DB_PATH if db_path is None else db_path
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    """Create every table (and index) if it doesn't already exist.

    Safe to call on every startup — CREATE TABLE/INDEX IF NOT EXISTS only.

    Returns
    -------
    sqlite3.Connection
    """
    conn = get_connection(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    _migrate_annotations_columns(conn)
    _migrate_runs_columns(conn)
    _migrate_motifs_columns(conn)
    return conn
