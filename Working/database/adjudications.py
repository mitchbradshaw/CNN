"""
adjudications.py
================
Plain functions for the adjudication store: a human verdict against a machine
detection, one row per detection. Same pattern as `queries.py` — plain
`sqlite3`, no ORM, every function commits its own writes.

The invariant (coding standard 2.5): adjudicating writes an `adjudications`
row and never an `annotations` row. `annotations` is written only by a human
action; `detections` and `adjudications` are written only by machine or by
adjudication of a machine row. No code path in this module writes to the
human annotation store.

Tags attach through the `adjudication_tags` join table against the same
controlled `tag_vocabulary` as annotations and motifs. The shared tag helpers
in `Working.database.vocabulary` are reused, not reimplemented (rule 6.4).

The verdict vocabulary is the single shared constant `VERDICTS` from
`Working.database.schema`, imported rather than restated, so the annotation
and adjudication vocabularies cannot drift apart (rule 6.4 / T04).
"""

import datetime

from Working.database.schema import VERDICTS
from Working.database.vocabulary import _add_tag, _get_tags, _set_tags


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def insert_adjudication(conn, detection_id, verdict, note=None, tags=None,
                        commit=True):
    """Record a human verdict against a machine detection.

    One adjudication per detection. Re-adjudicating the same detection updates
    the existing row in place (via the `UNIQUE (detection_id)` constraint)
    rather than inserting a second.

    Parameters
    ----------
    verdict : str
        One of `VERDICTS` ('seed', 'interesting', 'not_interesting',
        'artifact', 'unsure').
    note : str, optional
    tags : dict[str, list[str]], optional
        Category -> values, e.g. {"element": ["sharkfin"]}. Stored through the
        `adjudication_tags` join table against `tag_vocabulary`. Existing tags
        in a category are replaced when that category is passed; categories not
        passed are left untouched.

    Returns
    -------
    int — the adjudication row id.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    now = _now()
    conn.execute(
        """INSERT INTO adjudications (detection_id, verdict, note, created_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(detection_id) DO UPDATE SET
               verdict = excluded.verdict,
               note = excluded.note,
               created_at = excluded.created_at""",
        (detection_id, verdict, note, now),
    )
    row = conn.execute(
        "SELECT id FROM adjudications WHERE detection_id = ?", (detection_id,)
    ).fetchone()
    adj_id = row["id"]
    if tags:
        for category, values in tags.items():
            set_adjudication_tags(conn, adj_id, category, values, commit=False)
    if commit:
        conn.commit()
    return adj_id


def get_adjudication(conn, detection_id):
    """The adjudication row for a detection, or None if unadjudicated."""
    return conn.execute(
        "SELECT * FROM adjudications WHERE detection_id = ?", (detection_id,)
    ).fetchone()


def get_adjudication_by_id(conn, adjudication_id):
    return conn.execute(
        "SELECT * FROM adjudications WHERE id = ?", (adjudication_id,)
    ).fetchone()


def set_adjudication_tags(conn, adjudication_id, category, values, commit=True):
    """Replace an adjudication's tags for one category with `values`.

    Same contract as `set_annotation_tags` — a single string, an iterable of
    strings, or None/empty to clear the category. Unknown (category, value)
    pairs raise ValueError. The shared implementation in
    `Working.database.vocabulary` is reused, targeting `adjudication_tags`.
    """
    _set_tags(conn, "adjudication_tags", "adjudication_id", adjudication_id,
              category, values, commit)


def add_adjudication_tag(conn, adjudication_id, category, value, commit=True):
    """Add one tag without touching this category's other assignments —
    the multi-select ('element') case. Idempotent (INSERT OR IGNORE)."""
    _add_tag(conn, "adjudication_tags", "adjudication_id", adjudication_id,
             category, value, commit)


def get_adjudication_tags(conn, adjudication_id):
    """Return {category: [values]} for everything tagged on one adjudication."""
    return _get_tags(conn, "adjudication_tags", "adjudication_id", adjudication_id)
