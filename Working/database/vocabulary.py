"""
vocabulary.py
==============
Controlled tag vocabulary for annotations: `tag_vocabulary` (the editable
term list) and `annotation_tags` (the many-to-many assignment). Plain
functions, no ORM — same pattern as `queries.py`.

Categories
----------
`element`     multi-select  — signal morphology (sharkfin, ridge, ...)
`quality`     single-select — clean / noisy / superimposed / unclear
`structure`   single-select — single_cycle / sequence / nested_sequence / type_specimen
`provenance`  single-select — set automatically by importers, not user-editable
`status`      single-select — candidate / examined / confirmed

`status` also exists as a plain column on `annotations` (see schema.py) —
that column is the actual single source of truth for an annotation's
status, since it's always exactly one value and is filtered/queried
heavily. The `status` vocabulary category exists so its allowed values are
still managed through the same admin-editable term list rather than a
hardcoded Python enum; the UI's status dropdown reads its options from
here but writes to `annotations.status` directly, not to `annotation_tags`.
"""

MULTI_SELECT_CATEGORIES = {"element"}

SEED_VOCABULARY = {
    "element": [
        "sharkfin", "crestedwave", "furrycaterpillar", "rollinghill",
        "halfdome", "ridge", "trough", "sharp_trough", "spike",
        "spore_drop", "stegasaurus", "tonic_bursting", "cycle_sequence",
        "other",
    ],
    "quality": ["clean", "noisy", "superimposed", "unclear"],
    "structure": ["single_cycle", "sequence", "nested_sequence", "type_specimen"],
    "provenance": ["manually_sorted_for_cnn", "excel_catalog", "manual_ui"],
    "status": ["candidate", "examined", "confirmed"],
}


def seed_vocabulary(conn):
    """Insert every term in `SEED_VOCABULARY` that isn't already present.
    Idempotent — safe to call on every startup."""
    for category, values in SEED_VOCABULARY.items():
        for value in values:
            conn.execute(
                "INSERT OR IGNORE INTO tag_vocabulary (category, value, active) "
                "VALUES (?, ?, 1)",
                (category, value),
            )
    conn.commit()


# ── Term admin (add / deactivate / reactivate) ───────────────────────────────

def add_term(conn, category, value, description=None):
    """Add a new vocabulary term, or reactivate + update the description of
    an existing (possibly deactivated) one. Returns the term id."""
    conn.execute(
        "INSERT INTO tag_vocabulary (category, value, description, active) "
        "VALUES (?, ?, ?, 1) "
        "ON CONFLICT (category, value) DO UPDATE SET active = 1, "
        "description = COALESCE(excluded.description, tag_vocabulary.description)",
        (category, value, description),
    )
    conn.commit()
    return get_term(conn, category, value)["id"]


def deactivate_term(conn, term_id):
    """Soft-delete a term. Existing `annotation_tags` rows referencing it
    are untouched — deactivating only hides it from future dropdowns."""
    conn.execute("UPDATE tag_vocabulary SET active = 0 WHERE id = ?", (term_id,))
    conn.commit()


def reactivate_term(conn, term_id):
    conn.execute("UPDATE tag_vocabulary SET active = 1 WHERE id = ?", (term_id,))
    conn.commit()


def get_term(conn, category, value):
    return conn.execute(
        "SELECT * FROM tag_vocabulary WHERE category = ? AND value = ?",
        (category, value),
    ).fetchone()


def get_or_create_term(conn, category, value, description=None):
    """Look up a term, creating it (active) if it doesn't exist yet — for
    importers that must not silently drop an unrecognized value."""
    row = get_term(conn, category, value)
    if row is not None:
        return row["id"]
    return add_term(conn, category, value, description)


def list_terms(conn, category=None, active_only=True):
    query = "SELECT * FROM tag_vocabulary"
    clauses, params = [], []
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    if active_only:
        clauses.append("active = 1")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY category, value"
    return conn.execute(query, params).fetchall()


def list_categories(conn):
    return [r["category"] for r in conn.execute(
        "SELECT DISTINCT category FROM tag_vocabulary ORDER BY category"
    )]


# ── Tag assignment ────────────────────────────────────────────────────────────

def _set_tags(conn, table, id_column, entity_id, category, values, commit=True):
    """Shared implementation behind `set_annotation_tags`/`set_motif_tags` —
    replace `entity_id`'s tags for one category with `values`. See
    `set_annotation_tags` for the parameter contract."""
    if values is None:
        values = []
    elif isinstance(values, str):
        values = [values]

    conn.execute(
        f"""DELETE FROM {table} WHERE {id_column} = ? AND tag_id IN
                (SELECT id FROM tag_vocabulary WHERE category = ?)""",
        (entity_id, category),
    )
    for value in values:
        term = get_term(conn, category, value)
        if term is None:
            raise ValueError(f"Unknown vocabulary term: {category}={value!r}")
        conn.execute(
            f"INSERT OR IGNORE INTO {table} ({id_column}, tag_id) VALUES (?, ?)",
            (entity_id, term["id"]),
        )
    if commit:
        conn.commit()


def _add_tag(conn, table, id_column, entity_id, category, value, commit=True):
    """Shared implementation behind `add_annotation_tag`/`add_motif_tag`."""
    term = get_term(conn, category, value)
    if term is None:
        raise ValueError(f"Unknown vocabulary term: {category}={value!r}")
    conn.execute(
        f"INSERT OR IGNORE INTO {table} ({id_column}, tag_id) VALUES (?, ?)",
        (entity_id, term["id"]),
    )
    if commit:
        conn.commit()


def _get_tags(conn, table, id_column, entity_id):
    """Shared implementation behind `get_annotation_tags`/`get_motif_tags`."""
    rows = conn.execute(
        f"""SELECT v.category, v.value FROM {table} t
            JOIN tag_vocabulary v ON v.id = t.tag_id
            WHERE t.{id_column} = ?
            ORDER BY v.category, v.value""",
        (entity_id,),
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["category"], []).append(r["value"])
    return out


def set_annotation_tags(conn, annotation_id, category, values, commit=True):
    """Replace an annotation's tags for one category with `values`.

    `values` may be a single string, an iterable of strings, or None/empty
    to clear the category. For single-select categories this naturally
    replaces "the" tag; for multi-select categories (`element`) it replaces
    the whole set. Unrecognized (category, value) pairs raise ValueError —
    callers that want auto-creation should call `get_or_create_term` first.
    """
    _set_tags(conn, "annotation_tags", "annotation_id", annotation_id, category, values, commit)


def add_annotation_tag(conn, annotation_id, category, value, commit=True):
    """Add one tag without touching this category's other assignments —
    the multi-select ('element') case. Idempotent (INSERT OR IGNORE)."""
    _add_tag(conn, "annotation_tags", "annotation_id", annotation_id, category, value, commit)


def get_annotation_tags(conn, annotation_id):
    """Return {category: [values]} for everything tagged on one annotation."""
    return _get_tags(conn, "annotation_tags", "annotation_id", annotation_id)


def get_tags_for_recording(conn, recording_id):
    """Bulk version of `get_annotation_tags` for every annotation under one
    recording — one JOIN instead of one query per row. Returns
    {annotation_id: {category: [values]}}; annotations with no tags at all
    are simply absent (callers should use `.get(aid, {})`)."""
    rows = conn.execute(
        """SELECT t.annotation_id, v.category, v.value FROM annotation_tags t
           JOIN tag_vocabulary v ON v.id = t.tag_id
           JOIN annotations a ON a.id = t.annotation_id
           WHERE a.recording_id = ?
           ORDER BY t.annotation_id, v.category, v.value""",
        (recording_id,),
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["annotation_id"], {}).setdefault(r["category"], []).append(r["value"])
    return out


# ── motif tags (same controlled vocabulary, a different entity) ─────────────

def set_motif_tags(conn, motif_id, category, values, commit=True):
    """Motif equivalent of `set_annotation_tags` — same controlled
    vocabulary, stored in `motif_tags` instead of `annotation_tags`."""
    _set_tags(conn, "motif_tags", "motif_id", motif_id, category, values, commit)


def add_motif_tag(conn, motif_id, category, value, commit=True):
    """Motif equivalent of `add_annotation_tag`."""
    _add_tag(conn, "motif_tags", "motif_id", motif_id, category, value, commit)


def get_motif_tags(conn, motif_id):
    """Motif equivalent of `get_annotation_tags`."""
    return _get_tags(conn, "motif_tags", "motif_id", motif_id)


def annotations_matching_tags(conn, recording_id, tag_filters):
    """Return the set of annotation ids under `recording_id` that carry at
    least one of `values` in *every* requested category.

    Parameters
    ----------
    tag_filters : dict[str, list[str]]
        e.g. {"element": ["sharkfin", "ridge"], "quality": ["clean"]} ->
        annotations with (sharkfin OR ridge) AND clean.
    """
    if not tag_filters:
        return None  # None means "no tag filter" to the caller
    ids = None
    for category, values in tag_filters.items():
        if not values:
            continue
        placeholders = ",".join("?" * len(values))
        rows = conn.execute(
            f"""SELECT DISTINCT t.annotation_id FROM annotation_tags t
                JOIN tag_vocabulary v ON v.id = t.tag_id
                JOIN annotations a ON a.id = t.annotation_id
                WHERE a.recording_id = ? AND v.category = ? AND v.value IN ({placeholders})""",
            (recording_id, category, *values),
        ).fetchall()
        matched = {r["annotation_id"] for r in rows}
        ids = matched if ids is None else (ids & matched)
    return ids or set()
