"""
schema.py
=========
SQLite schema for the annotation/labelling database and the run-tracking
tables the pipeline (algorithm runs, detections, cached encodings) writes to.

`configs`, `runs`, `detections`, `encodings` and `motifs` are the original
run-tracking tables. `adjudications` (+ `adjudication_tags`) is where a human
verdict against a machine detection lives — the one place algorithmic output
is judged, kept physically separate from `annotations`. `motif_entry`,
`motif_member`, `motif_edge` and `motif_entry_tags` are the shape-first motif
library: an entry is an exemplar span, a member is any span matched to it in
any recording/channel, an edge is a distance-carrying relationship between
two members. `run_groups` holds N sibling runs fanned out from one recipe
(`runs.run_group_id`); `runs.surrogate_of_run_id` pairs a run with its
surrogate control. `step_artifacts` is the per-step recipe-prefix cache.
`templates` is a saved chain with recording and span stripped.

No ORM — plain `sqlite3`, callable from scripts and the UI alike.

Migrations
----------
`init_db()` is always additive and safe to call repeatedly: base tables use
`CREATE TABLE IF NOT EXISTS`, and anything added to an *existing* table
(new columns on `annotations`; `run_group_id`/`surrogate_of_run_id` on
`runs`) is applied by `_migrate_columns`, which checks `PRAGMA table_info`
first and only adds what's missing. Nothing here ever drops or rewrites a
column, so existing rows are untouched.
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

-- Human verdict against a machine detection — the only place adjudication
-- of algorithmic output lives (standards rule 2.5: annotations stays
-- human-only, detections/adjudications stay machine-only). One row per
-- detection. `verdict` carries no CHECK: the vocabulary is due to gain
-- `seed`, SQLite can't alter a CHECK in place, and a four-verdict CHECK
-- written here would make that a second non-additive rebuild that rule 2.2
-- doesn't permit. The vocabulary is enforced in Python instead, against
-- the shared constant `queries.VERDICTS`.
CREATE TABLE IF NOT EXISTS adjudications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    detection_id  INTEGER NOT NULL REFERENCES detections(id),
    verdict       TEXT    NOT NULL,
    note          TEXT,
    created_at    TEXT    NOT NULL,
    UNIQUE (detection_id)
);

-- Many-to-many: an adjudication's tags, via the same controlled vocabulary
-- as annotations and motifs.
CREATE TABLE IF NOT EXISTS adjudication_tags (
    adjudication_id INTEGER NOT NULL REFERENCES adjudications(id),
    tag_id          INTEGER NOT NULL REFERENCES tag_vocabulary(id),
    PRIMARY KEY (adjudication_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_adjudication_tags_tag ON adjudication_tags(tag_id);

-- Shape-first motif library. An entry is an exemplar span identified by
-- recording and sample range, with one nullable provenance pointer back to
-- the detection it came from. One pointer only — a second nullable FK
-- alongside it would rebuild the origin-discriminator shape `v_spans` was
-- withdrawn for, one column lower.
CREATE TABLE IF NOT EXISTS motif_entry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id),
    start_idx     INTEGER NOT NULL,
    end_idx       INTEGER NOT NULL,
    detection_id  INTEGER REFERENCES detections(id),
    UNIQUE (recording_id, start_idx, end_idx)
);
CREATE INDEX IF NOT EXISTS idx_motif_entry_recording ON motif_entry(recording_id);

-- A span matched to a motif_entry. May sit in any recording and any
-- channel — membership is not restricted to the entry's own recording.
CREATE TABLE IF NOT EXISTS motif_member (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id      INTEGER NOT NULL REFERENCES motif_entry(id),
    recording_id  INTEGER NOT NULL REFERENCES recordings(id),
    start_idx     INTEGER NOT NULL,
    end_idx       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_motif_member_entry ON motif_member(entry_id);
CREATE INDEX IF NOT EXISTS idx_motif_member_recording ON motif_member(recording_id);

-- A relationship between two members of a motif family — cross-channel
-- classification compares each pair of members on different channels of
-- one recording (PIPELINE_PRD.md, Analysis semantics). Carries the
-- distance that produced the match, plus, when the pair is cross-channel,
-- the lag/correlation/bin classification.
CREATE TABLE IF NOT EXISTS motif_edge (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    member_a_id          INTEGER NOT NULL REFERENCES motif_member(id),
    member_b_id          INTEGER NOT NULL REFERENCES motif_member(id),
    distance_function    TEXT    NOT NULL,
    threshold            REAL    NOT NULL,
    distance_value       REAL    NOT NULL,
    recipe_hash          TEXT    NOT NULL,
    lag                  INTEGER,
    waveform_correlation REAL,
    classification_bin   TEXT
);
CREATE INDEX IF NOT EXISTS idx_motif_edge_member_a ON motif_edge(member_a_id);
CREATE INDEX IF NOT EXISTS idx_motif_edge_member_b ON motif_edge(member_b_id);

-- Many-to-many: an entry's tags. Surrogate `id` with a UNIQUE pair, rather
-- than the composite primary key `motif_tags`/`annotation_tags` use,
-- because no tag may be part of any primary key here.
CREATE TABLE IF NOT EXISTS motif_entry_tags (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES motif_entry(id),
    tag_id   INTEGER NOT NULL REFERENCES tag_vocabulary(id),
    UNIQUE (entry_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_motif_entry_tags_tag ON motif_entry_tags(tag_id);

-- N sibling runs sharing one recipe, fanned out over a channel or band
-- list. Carries only an id and a created_at — fan-out and scope semantics
-- belong to the ticket that writes to this table.
CREATE TABLE IF NOT EXISTS run_groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT    NOT NULL
);

-- Per-step cache, keyed on the hash of the recipe prefix up to and
-- including that step.
CREATE TABLE IF NOT EXISTS step_artifacts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_prefix_hash TEXT    NOT NULL,
    step_index         INTEGER NOT NULL,
    path               TEXT    NOT NULL,
    UNIQUE (recipe_prefix_hash, step_index)
);

-- Saved chains, with recording and span stripped.
CREATE TABLE IF NOT EXISTS templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    steps_json TEXT NOT NULL
);
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
    # Fan-out (run_groups) and surrogate-control pairing, both nullable —
    # a run belongs to neither unless something opts it in.
    ("run_group_id", "INTEGER REFERENCES run_groups(id)"),
    ("surrogate_of_run_id", "INTEGER REFERENCES runs(id)"),
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
