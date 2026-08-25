"""
runs.py
========
Plain functions for the run-tracking / provenance layer: `configs`
(recipes), `runs`, `detections`, `artifacts`, `encodings` (the cache),
`motifs`, and the shape-first library's `motif_member`/`motif_edge` rows
(ticket 36). Same pattern as `queries.py` — plain `sqlite3`, no ORM, every
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
    error_text, step_timings_json, artifact_path, current_step,
    run_group_id, surrogate_of_run_id."""
    allowed = {"status", "finished_at", "duration_s", "error_text",
               "step_timings_json", "artifact_path", "current_step",
               "run_group_id", "surrogate_of_run_id"}
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


# ── run_groups (fan-out) ─────────────────────────────────────────────────────
#
# One `run_groups` row groups N sibling runs fanned out from a single recipe
# over a channel or band scope (`runs.run_group_id`). The row itself carries
# only id + created_at; the scope and per-target recipes live in the runs'
# own config rows (ticket 25).

def create_run_group(conn, created_at=None):
    """Insert a run_groups row and return its id."""
    created_at = created_at or _now()
    cur = conn.execute(
        "INSERT INTO run_groups (created_at) VALUES (?)", (created_at,)
    )
    conn.commit()
    return cur.lastrowid


def get_run_group(conn, run_group_id):
    return conn.execute(
        "SELECT * FROM run_groups WHERE id = ?", (run_group_id,)
    ).fetchone()


def list_run_group_runs(conn, run_group_id):
    """The sibling runs of one fan-out, ordered by id for a stable report."""
    return conn.execute(
        "SELECT * FROM runs WHERE run_group_id = ? ORDER BY id", (run_group_id,)
    ).fetchall()


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


# ── step_artifacts (the per-step recipe-prefix cache) ────────────────────────

def get_step_artifact(conn, recipe_prefix_hash, step_index):
    """Return the cached artifact row for a step's recipe-prefix hash, or
    None on a miss. The path points at a directory containing the typed
    step output written by its `Working.types` serialiser."""
    return conn.execute(
        "SELECT * FROM step_artifacts WHERE recipe_prefix_hash = ? AND step_index = ?",
        (recipe_prefix_hash, step_index),
    ).fetchone()


def insert_step_artifact(conn, recipe_prefix_hash, step_index, path):
    """Record a step's cached artifact. `INSERT OR REPLACE` so a missing
    on-disk artifact that gets recomputed can update its path under the same
    unique (recipe_prefix_hash, step_index) key."""
    conn.execute(
        "INSERT OR REPLACE INTO step_artifacts (recipe_prefix_hash, step_index, path) "
        "VALUES (?, ?, ?)",
        (recipe_prefix_hash, step_index, path),
    )
    conn.commit()


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


# ── motifs (shape-first entries) ─────────────────────────────────────────────
#
# The library is keyed by recording + sample range, not by detection. The
# functions below are the entry-based equivalents of the old detection-keyed
# `motifs` functions; the old names are kept as thin wrappers so existing
# callers/tests keep working while the UI moves onto `insert_motif_entry`.

def insert_motif_entry(conn, recording_id, start_idx, end_idx, detection_id=None,
                       label=None, rating=None, notes=None, tags=None,
                       sax_string=None, created_at=None, commit=True):
    """Create (or return) a shape-first motif entry.

    The entry's identity is `(recording_id, start_idx, end_idx)`. The
    detection pointer is optional provenance only — an eye-flagged exemplar
    has none. Idempotent on the span: if an entry already exists for the
    same span, the existing entry id is returned rather than raising on the
    UNIQUE constraint.
    """
    if detection_id is not None:
        surrogate_of = conn.execute(
            """SELECT r.surrogate_of_run_id
               FROM detections d JOIN runs r ON r.id = d.run_id
               WHERE d.id = ?""",
            (detection_id,),
        ).fetchone()
        if surrogate_of is None:
            raise ValueError(f"Unknown detection id {detection_id}")
        if surrogate_of["surrogate_of_run_id"] is not None:
            raise ValueError(
                f"Detection {detection_id} belongs to a surrogate run; "
                "surrogate-derived spans cannot enter the library."
            )

    created_at = created_at or _now()
    conn.execute(
        """INSERT OR IGNORE INTO motif_entry
               (recording_id, start_idx, end_idx, detection_id,
                label, rating, notes, tags, sax_string, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (recording_id, start_idx, end_idx, detection_id,
         label, rating, notes, tags, sax_string, created_at),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        """SELECT id FROM motif_entry
           WHERE recording_id = ? AND start_idx = ? AND end_idx = ?""",
        (recording_id, start_idx, end_idx),
    ).fetchone()
    return row["id"]


def get_motif_entry(conn, entry_id):
    return conn.execute(
        "SELECT * FROM motif_entry WHERE id = ?", (entry_id,)
    ).fetchone()


def list_motif_entries(conn):
    return conn.execute(
        "SELECT * FROM motif_entry ORDER BY created_at DESC, id DESC"
    ).fetchall()


def motif_entry_provenance(conn, entry_id):
    """Full metadata for a shape-first motif entry.

    Returns
    -------
    dict, or None if the entry doesn't exist. Includes the entry's own span
    and recording (source_file/channel/fs) plus, when the entry retains a
    detection pointer, the parsed recipe that produced it. A pointerless
    eye-flagged entry returns `recipe` as None rather than failing.
    """
    row = conn.execute(
        """SELECT e.*, rec.source_file, rec.channel, rec.fs, c.config_json
           FROM motif_entry e
           JOIN recordings rec ON rec.id = e.recording_id
           LEFT JOIN detections d ON d.id = e.detection_id
           LEFT JOIN runs r ON r.id = d.run_id
           LEFT JOIN configs c ON c.id = r.config_id
           WHERE e.id = ?""",
        (entry_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["recipe"] = json.loads(row["config_json"]) if row["config_json"] else None
    return result


# ── motif_member / motif_edge (the shape-first library's edges) ─────────────
#
# A member is one span of a motif family, in any recording/channel. An edge
# is the distance-carrying relationship between two members, with every field
# needed to reproduce the match stored on the row (distance function name,
# threshold, distance value, recipe hash). `insert_motif_edge` is the single
# edge-writer signature tickets 41/46 call; they do not write raw SQL against
# `motif_edge`.

def get_or_create_motif_member(conn, entry_id, recording_id, start_idx, end_idx,
                               commit=True):
    """Return the id of the member for (entry_id, recording, span), creating
    it on first use.

    A member's identity is the 4-tuple (entry_id, recording_id, start_idx,
    end_idx) — idempotent, so re-matching the same span to the same entry
    never duplicates the member row. A member may reference any recording and
    any channel, including one the entry's exemplar did not come from.
    """
    row = conn.execute(
        """SELECT id FROM motif_member
           WHERE entry_id = ? AND recording_id = ? AND start_idx = ? AND end_idx = ?""",
        (entry_id, recording_id, start_idx, end_idx),
    ).fetchone()
    if row is not None:
        return row["id"]
    cur = conn.execute(
        """INSERT INTO motif_member (entry_id, recording_id, start_idx, end_idx)
           VALUES (?, ?, ?, ?)""",
        (entry_id, recording_id, start_idx, end_idx),
    )
    if commit:
        conn.commit()
    return cur.lastrowid


def get_motif_member(conn, member_id):
    return conn.execute(
        "SELECT * FROM motif_member WHERE id = ?", (member_id,)
    ).fetchone()


def list_motif_members(conn, entry_id):
    """Every member of one motif family, ordered by recording then span."""
    return conn.execute(
        """SELECT * FROM motif_member WHERE entry_id = ?
           ORDER BY recording_id, start_idx""",
        (entry_id,),
    ).fetchall()


def get_motif_edge(conn, member_a_id, member_b_id, distance_function, threshold,
                   recipe_hash):
    """The edge between two members under this exact
    (member_a_id, member_b_id, distance_function, threshold, recipe_hash) key,
    or None.

    Member order is significant: the match writer stores (exemplar, candidate)
    consistently, and the cross-channel classifier (ticket 46) relies on the
    same orientation to carry a signed lag.
    """
    return conn.execute(
        """SELECT * FROM motif_edge
           WHERE member_a_id = ? AND member_b_id = ? AND distance_function = ?
             AND threshold = ? AND recipe_hash = ?
           LIMIT 1""",
        (member_a_id, member_b_id, distance_function, threshold, recipe_hash),
    ).fetchone()


def insert_motif_edge(conn, member_a_id, member_b_id, distance_function, threshold,
                      distance_value, recipe_hash, lag=None,
                      waveform_correlation=None, classification_bin=None,
                      commit=True):
    """Create an edge between two members. The single edge-writer signature.

    Idempotent on the exact (member_a_id, member_b_id, distance_function,
    threshold, recipe_hash) key — re-running the same match with the same
    recipe returns the existing edge id instead of duplicating the row, and
    leaves the existing row unchanged (any `lag`/`waveform_correlation`/
    `classification_bin` passed on a duplicate key are ignored). The
    cross-channel classifier (ticket 46) stores those three columns at
    creation time.
    """
    existing = get_motif_edge(conn, member_a_id, member_b_id, distance_function,
                              threshold, recipe_hash)
    if existing is not None:
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO motif_edge
               (member_a_id, member_b_id, distance_function, threshold,
                distance_value, recipe_hash, lag, waveform_correlation,
                classification_bin)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (member_a_id, member_b_id, distance_function, threshold,
         distance_value, recipe_hash, lag, waveform_correlation,
         classification_bin),
    )
    if commit:
        conn.commit()
    return cur.lastrowid


def list_motif_edges(conn, entry_id):
    """Every edge of one motif family, reached through either endpoint's
    membership of the entry. Ordered by id for a stable report."""
    return conn.execute(
        """SELECT e.* FROM motif_edge e
           JOIN motif_member ma ON ma.id = e.member_a_id
           JOIN motif_member mb ON mb.id = e.member_b_id
           WHERE ma.entry_id = ? AND mb.entry_id = ?
           ORDER BY e.id""",
        (entry_id, entry_id),
    ).fetchall()


# ── legacy `motifs` wrappers ─────────────────────────────────────────────────

def insert_motif(conn, detection_id, label=None, rating=None, notes=None,
                  sax_string=None, created_at=None, tags=None):
    """Legacy wrapper: create an entry from a detection pointer.

    Kept so pre-entry callers don't break. Resolves the detection's span and
    recording, then delegates to the single entry-creation helper.
    """
    detection = get_detection(conn, detection_id)
    run = get_run(conn, detection["run_id"])
    return insert_motif_entry(
        conn, run["recording_id"], detection["start_idx"], detection["end_idx"],
        detection_id=detection_id, label=label, rating=rating, notes=notes,
        tags=tags, sax_string=sax_string, created_at=created_at,
    )


def get_motif(conn, motif_id):
    return get_motif_entry(conn, motif_id)


def list_motifs(conn):
    return list_motif_entries(conn)


def motif_provenance(conn, motif_id):
    return motif_entry_provenance(conn, motif_id)
