"""
schema.py
=========
SQLite schema for the annotation/labelling database and the run-tracking
tables the next project phase (algorithm runs, detections, cached encodings)
will write to.

Only `recordings`, `reviewed_spans` and `annotations` are populated by this
phase. `configs`, `runs`, `detections`, `encodings` and `motifs` are created
now so that phase needs no migration, but nothing here writes to them.

No ORM — plain `sqlite3`, callable from scripts and the UI alike.
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
"""


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
    return conn
