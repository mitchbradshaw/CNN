"""
retrofit_provenance.py
========================
One-time (idempotent) retrofit: tag every existing `source='imported_10min'`
annotation (the ~11,000 windows from `import_10min_labels.py`) with
`provenance='manually_sorted_for_cnn'`.

This is a distinct concept from the existing `source` column: `source`
protects imported rows from accidental UI edits (see
`Working/database/queries.py`); `provenance` is the richer,
vocabulary-managed classification the tag-vocabulary feature introduces,
which will also distinguish `excel_catalog` and future import sources
without needing another schema change.

Usage
-----
    python Pipelines/retrofit_provenance/retrofit_provenance.py
    python Pipelines/retrofit_provenance/retrofit_provenance.py --dry-run
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import argparse

from Working.database.schema import init_db
from Working.database.queries import SOURCE_IMPORTED_10MIN
from Working.database.vocabulary import (
    add_annotation_tag,
    get_term,
    seed_vocabulary,
)

PROVENANCE_VALUE = "manually_sorted_for_cnn"
COMMIT_EVERY = 500


def retrofit_provenance(dry_run=False, db_path=None):
    conn = init_db(db_path)
    seed_vocabulary(conn)
    term = get_term(conn, "provenance", PROVENANCE_VALUE)

    rows = conn.execute(
        "SELECT id FROM annotations WHERE source = ?", (SOURCE_IMPORTED_10MIN,)
    ).fetchall()

    already, tagged = 0, 0
    for i, row in enumerate(rows, start=1):
        aid = row["id"]
        has_tag = conn.execute(
            "SELECT 1 FROM annotation_tags WHERE annotation_id = ? AND tag_id = ?",
            (aid, term["id"]),
        ).fetchone()
        if has_tag:
            already += 1
            continue
        tagged += 1
        if dry_run:
            continue
        add_annotation_tag(conn, aid, "provenance", PROVENANCE_VALUE, commit=False)
        if i % COMMIT_EVERY == 0:
            conn.commit()

    if not dry_run:
        conn.commit()

    print(
        f"Done{' (dry run)' if dry_run else ''}. "
        f"{len(rows)} annotations with source={SOURCE_IMPORTED_10MIN!r}: "
        f"newly tagged={tagged}  already_tagged={already}"
    )
    conn.close()
    return {"total": len(rows), "tagged": tagged, "already_tagged": already}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    retrofit_provenance(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
