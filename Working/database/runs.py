"""
runs.py
========
Plain functions for the run-tracking / provenance layer: `configs`
(recipes), `runs`, `detections`, `artifacts`, `encodings` (the cache), and
`motifs`. Same pattern as `queries.py` — plain `sqlite3`, no ORM, every
function commits its own writes.

`config_hash` throughout this module is the recipe's *short* (8-char) hash
(`Working.recipes.short_hash`) — the single identifier tying a `configs`
row, a `runs` row, an `encodings` cache entry, and a saved artifact's
filename together. Collision risk at 32 bits is negligible at the scale a
single research project produces (millions of runs would be needed before
a birthday-paradox collision becomes likely).
"""

import datetime
import json

from Working.recipes import canonical_json, short_hash

ARTIFACT_KINDS = ("plot", "encoding", "model", "csv", "other")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── configs (recipes) ────────────────────────────────────────────────────────

def get_or_create_config(conn, recipe):
    """Insert the recipe's config row if new, else return the existing one.
    Idempotent on `config_hash` — calling this twice for an identical recipe
    is always a no-op the second time.

    Returns
    -------
    (config_id, config_hash) : (int, str)
    """
    h = short_hash(recipe)
    conn.execute(
        "INSERT OR IGNORE INTO configs (config_hash, config_json, created_at) VALUES (?, ?, ?)",
        (h, canonical_json(recipe), _now()),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM configs WHERE config_hash = ?", (h,)).fetchone()
    return row["id"], h


def get_config(conn, config_id):
    return conn.execute("SELECT * FROM configs WHERE id = ?", (config_id,)).fetchone()


def get_config_by_hash(conn, config_hash):
    return conn.execute("SELECT * FROM configs WHERE config_hash = ?", (config_hash,)).fetchone()


def load_recipe(conn, config_id):
    """Parse and return the recipe dict stored for a config row."""
    row = get_config(conn, config_id)
    if row is None:
        raise ValueError(f"No config with id={config_id}")
    return json.loads(row["config_json"])


# ── runs ─────────────────────────────────────────────────────────────────────

def insert_run(conn, config_id, recording_id, span_start, span_end,
                status="running", started_at=None):
    started_at = started_at or _now()
    cur = conn.execute(
        """INSERT INTO runs (config_id, recording_id, span_start, span_end, started_at, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (config_id, recording_id, span_start, span_end, started_at, status),
    )
    conn.commit()
    return cur.lastrowid


def update_run(conn, run_id, **fields):
    """Update editable run fields: status, finished_at, duration_s,
    error_text, step_timings_json, artifact_path."""
    allowed = {"status", "finished_at", "duration_s", "error_text",
               "step_timings_json", "artifact_path"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Cannot update fields: {bad}")
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE runs SET {set_clause} WHERE id = ?", (*fields.values(), run_id))
    conn.commit()


def get_run(conn, run_id):
    return conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()


def find_completed_run(conn, config_id, recording_id, span_start, span_end):
    """Idempotency lookup: the most recent *completed* run of this exact
    recipe over this exact (recording, span). None on a miss.

    Used by `execute_recipe` to decide whether to reuse a prior run instead
    of recomputing — "detect the existing completed run and offer to reuse
    it" per the brief.
    """
    return conn.execute(
        """SELECT * FROM runs
           WHERE config_id = ? AND recording_id = ? AND span_start = ? AND span_end = ?
             AND status = 'completed'
           ORDER BY id DESC LIMIT 1""",
        (config_id, recording_id, span_start, span_end),
    ).fetchone()


def list_runs(conn, recording_id=None, status=None):
    query = "SELECT * FROM runs"
    clauses, params = [], []
    if recording_id is not None:
        clauses.append("recording_id = ?")
        params.append(recording_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC"
    return conn.execute(query, params).fetchall()


# ── detections ───────────────────────────────────────────────────────────────

def insert_detection(conn, run_id, start_idx, end_idx, score=None, meta_json=None, commit=True):
    cur = conn.execute(
        "INSERT INTO detections (run_id, start_idx, end_idx, score, meta_json) VALUES (?, ?, ?, ?, ?)",
        (run_id, start_idx, end_idx, score, meta_json),
    )
    if commit:
        conn.commit()
    return cur.lastrowid


def get_detection(conn, detection_id):
    return conn.execute("SELECT * FROM detections WHERE id = ?", (detection_id,)).fetchone()


def list_detections(conn, run_id):
    return conn.execute(
        "SELECT * FROM detections WHERE run_id = ? ORDER BY start_idx", (run_id,)
    ).fetchall()


def list_detections_for_recording(conn, recording_id):
    return conn.execute(
        """SELECT d.* FROM detections d JOIN runs r ON r.id = d.run_id
           WHERE r.recording_id = ? ORDER BY d.start_idx""",
        (recording_id,),
    ).fetchall()


# ── artifacts ────────────────────────────────────────────────────────────────

def insert_artifact(conn, run_id, kind, path, created_at=None):
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"kind must be one of {ARTIFACT_KINDS}, got {kind!r}")
    created_at = created_at or _now()
    cur = conn.execute(
        "INSERT INTO artifacts (run_id, kind, path, created_at) VALUES (?, ?, ?, ?)",
        (run_id, kind, path, created_at),
    )
    conn.commit()
    return cur.lastrowid


def list_artifacts(conn, run_id):
    return conn.execute(
        "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at", (run_id,)
    ).fetchall()


def list_artifacts_for_recording(conn, recording_id):
    return conn.execute(
        """SELECT a.* FROM artifacts a JOIN runs r ON r.id = a.run_id
           WHERE r.recording_id = ? ORDER BY a.created_at""",
        (recording_id,),
    ).fetchall()


# ── encodings (the cache) ────────────────────────────────────────────────────

def get_encoding_by_hash(conn, config_hash):
    """Cache lookup by recipe hash. Returns the cached row on a hit, None on
    a miss — the hash already encodes recording, span and params, so an
    exact hash match is by construction the same computation."""
    return conn.execute(
        "SELECT * FROM encodings WHERE config_hash = ?", (config_hash,)
    ).fetchone()


def insert_encoding(conn, recording_id, span_start, span_end, encoding_type,
                     config_hash, path, created_at=None):
    created_at = created_at or _now()
    cur = conn.execute(
        """INSERT INTO encodings
               (recording_id, span_start, span_end, encoding_type, config_hash, path, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (recording_id, span_start, span_end, encoding_type, config_hash, path, created_at),
    )
    conn.commit()
    return cur.lastrowid


def list_encodings(conn, recording_id=None):
    if recording_id is None:
        return conn.execute("SELECT * FROM encodings ORDER BY created_at DESC").fetchall()
    return conn.execute(
        "SELECT * FROM encodings WHERE recording_id = ? ORDER BY created_at DESC",
        (recording_id,),
    ).fetchall()


# ── motifs ───────────────────────────────────────────────────────────────────

def insert_motif(conn, detection_id, label=None, rating=None, notes=None,
                  sax_string=None, created_at=None):
    created_at = created_at or _now()
    cur = conn.execute(
        """INSERT INTO motifs (detection_id, label, rating, notes, sax_string, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (detection_id, label, rating, notes, sax_string, created_at),
    )
    conn.commit()
    return cur.lastrowid


def get_motif(conn, motif_id):
    return conn.execute("SELECT * FROM motifs WHERE id = ?", (motif_id,)).fetchone()


def list_motifs(conn):
    return conn.execute("SELECT * FROM motifs ORDER BY created_at DESC").fetchall()


def motif_provenance(conn, motif_id):
    """Full inherited metadata for a motif — recording, channel, span, and
    full recipe — walked through `detection_id -> run -> config/recording`.
    This is the mechanism behind "metadata must be inherited from the run,
    not typed by me": nothing here is re-entered, only looked up.

    Returns
    -------
    dict, or None if the motif doesn't exist. Includes everything from the
    `motifs` row plus recording_id/source_file/channel/fs, start_idx/end_idx,
    and the parsed `recipe` dict.
    """
    row = conn.execute(
        """SELECT m.*, d.start_idx, d.end_idx, d.run_id,
                  r.recording_id, r.config_id,
                  rec.source_file, rec.channel, rec.fs,
                  c.config_json
           FROM motifs m
           JOIN detections d ON d.id = m.detection_id
           JOIN runs r ON r.id = d.run_id
           JOIN recordings rec ON rec.id = r.recording_id
           JOIN configs c ON c.id = r.config_id
           WHERE m.id = ?""",
        (motif_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["recipe"] = json.loads(row["config_json"])
    return result
