"""
import_signal_catalogue.py
============================
Import `DATA/catalogue/signal_catalog.xlsx` (37 hand-catalogued signal
events, one row per event) into the annotation database.

Validated against the real spreadsheet before being written:
  - DATASET filter keeps 32/37 rows. Dropped: ID 14/16/17 (blank DATASET),
    ID 15 ("labview restarts every 100000 sampels"),
    ID 18 ("Mushroom_25_12_06_0954").
  - global_channel = Pack*4 + Channel falls in [0, 16) for all 32 kept rows.
  - 4 rows' stated Length_s disagrees with (StopTime_h-StartTime_h)*3600 by
    more than the tolerance: IDs 2, 8, 9, 10. Length is always *derived*,
    never taken from the Length_s column.
  - 8 rows have a non-zero Parent_ID; IDs 2/4/7/9 say "type specimen" in
    sequence_structure -> relation_kind='type_specimen', IDs 19/20/21/22
    have a parent without that phrase -> 'sub_window'.
  - Two Elements values didn't map to the seeded vocabulary: "Stegasauras"
    (ID 12, confirmed a typo for the seeded "stegasaurus" -- see
    `parsing.ELEMENT_ALIASES`) and "Bad News" (ID 13, "All channels
    identical, apart from DC" -- confirmed an equipment fault, not a
    morphology: imported as verdict='artifact' with no element tag at all,
    see `parsing.ARTIFACT_ID_NUMBERS`).

fs ambiguity (resolved): DATA/raw/ has both M2_aug_concat_fs1.mat and
M2_aug_concat_fs2.mat, and bounds-checking alone couldn't distinguish which
the catalogue's M2_aug StartTime_h/StopTime_h refer to (both durations
comfortably contain the catalogue's time range). Confirmed: fs1.

Idempotent: re-running looks up existing rows by (recording_id, start_idx,
end_idx, source='excel_catalog') -- for this dataset that's equivalent to
keying on (ID_Number, DATASET), since every kept row maps to a distinct,
deterministically-computed span.

Usage
-----
    python Pipelines/import_catalogue/import_signal_catalogue.py
    python Pipelines/import_catalogue/import_signal_catalogue.py --dry-run
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
import os

import pandas as pd

from Working.database.schema import init_db
from Working.database.queries import (
    annotation_exists,
    get_recording,
    insert_annotation,
    insert_reviewed_span,
    reviewed_span_exists,
)
from Working.database.vocabulary import (
    add_annotation_tag,
    get_or_create_term,
    list_terms,
    seed_vocabulary,
    set_annotation_tags,
)
from Pipelines.import_catalogue.parsing import (
    ARTIFACT_ID_NUMBERS,
    derive_relation_kind,
    derive_structure,
    hours_to_sample_index,
    normalize_parent_id,
    pack_channel_to_global,
    parse_event_count,
    split_elements,
)

DEFAULT_XLSX_PATH = os.path.join("DATA", "catalogue", "signal_catalog.xlsx")
SOURCE_EXCEL_CATALOG = "excel_catalog"
DATASET_TO_FILE = {
    "M2": "M2_concat_fs1.mat",
    "M2_aug": "M2_aug_concat_fs1.mat",  # confirmed, not fs2 -- see module docstring
}
LENGTH_MISMATCH_TOLERANCE_S = 0.5
COMMIT_EVERY = 100


def _note_for(row):
    parts = [str(x) for x in (row["sequence_structure"], row["Notes"]) if pd.notna(x)]
    return " | ".join(parts) if parts else None


def import_signal_catalogue(xlsx_path=None, dry_run=False, db_path=None):
    conn = init_db(db_path)
    seed_vocabulary(conn)
    xlsx_path = xlsx_path or DEFAULT_XLSX_PATH

    df = pd.read_excel(xlsx_path)
    keep_mask = df["DATASET"].isin(DATASET_TO_FILE)
    for _, r in df[~keep_mask].iterrows():
        print(f"  [DROP] ID {r['ID_Number']}: DATASET={r['DATASET']!r}")
    kept = df[keep_mask].copy()
    print(f"{len(kept)}/{len(df)} rows kept after DATASET filter.")

    known_element_vocab = {r["value"] for r in list_terms(conn, category="element")}
    recording_cache = {}

    def _get_recording_cached(source_file, channel):
        key = (source_file, channel)
        if key not in recording_cache:
            recording_cache[key] = get_recording(conn, source_file, channel)
        return recording_cache[key]

    counts = {
        "imported": 0, "already_present": 0, "out_of_bounds": 0,
        "length_mismatches": 0, "new_element_terms": 0,
    }
    id_to_annotation_id = {}     # ID_Number -> annotation_id (new or pre-existing)
    pending_parents = []         # (annotation_id, parent_id_number, own_id_number)
    inserted_this_run = set()    # annotation ids created during *this* call

    for _, r in kept.iterrows():
        id_number = int(r["ID_Number"])
        source_file = DATASET_TO_FILE[r["DATASET"]]
        global_channel = pack_channel_to_global(r["Pack"], r["Channel"])

        rec = _get_recording_cached(source_file, global_channel)
        if rec is None:
            raise RuntimeError(
                f"No recording row for {source_file} channel {global_channel} "
                "(ID_Number={id_number}). Run "
                "Pipelines/materialize_channels/materialize_channels.py first."
            )
        fs, L = rec["fs"], rec["n_samples"]

        start_idx = hours_to_sample_index(r["StartTime_h"], fs)
        end_idx = hours_to_sample_index(r["StopTime_h"], fs)

        computed_length_s = (r["StopTime_h"] - r["StartTime_h"]) * 3600
        if abs(r["Length_s"] - computed_length_s) > LENGTH_MISMATCH_TOLERANCE_S:
            counts["length_mismatches"] += 1
            print(
                f"  [LENGTH MISMATCH] ID {id_number}: stated Length_s={r['Length_s']:.1f} "
                f"computed={computed_length_s:.1f}"
            )

        if start_idx < 0 or end_idx > L or end_idx <= start_idx:
            counts["out_of_bounds"] += 1
            print(f"  [OOB] ID {id_number}: start={start_idx} end={end_idx} L={L}")
            continue

        existing = conn.execute(
            """SELECT id FROM annotations WHERE recording_id = ? AND start_idx = ?
               AND end_idx = ? AND source = ?""",
            (rec["id"], start_idx, end_idx, SOURCE_EXCEL_CATALOG),
        ).fetchone()

        parent_id_number = normalize_parent_id(r["Parent_ID"])

        if existing is not None:
            counts["already_present"] += 1
            id_to_annotation_id[id_number] = existing["id"]
            if existing["id"] in inserted_this_run:
                # Two different ID_Numbers in *this same* catalogue resolved
                # to the identical (recording_id, start_idx, end_idx) span --
                # not a cross-run idempotency skip. Report it; the later
                # ID_Number's own metadata (note/status/event_count) is not
                # separately stored anywhere.
                print(
                    f"  [DUPLICATE SPAN] ID {id_number} has the same channel/start/stop "
                    f"as an earlier row in this catalogue (annotation id {existing['id']}); "
                    "not creating a second annotation for it."
                )
            if parent_id_number is not None:
                pending_parents.append((existing["id"], parent_id_number, id_number))
            continue

        counts["imported"] += 1
        if dry_run:
            id_to_annotation_id[id_number] = None
            if parent_id_number is not None:
                pending_parents.append((None, parent_id_number, id_number))
            continue

        is_artifact_row = id_number in ARTIFACT_ID_NUMBERS
        verdict = "artifact" if is_artifact_row else "interesting"
        status = str(r["STATUS"]).strip().lower() if pd.notna(r["STATUS"]) else None
        relation_kind = derive_relation_kind(
            r["sequence_structure"], r["Notes"], parent_id_number is not None
        )
        event_count = parse_event_count(r["sequence_structure"], r["Notes"])

        aid = insert_annotation(
            conn, rec["id"], start_idx, end_idx, verdict,
            source=SOURCE_EXCEL_CATALOG, note=_note_for(r), commit=False,
        )
        conn.execute(
            "UPDATE annotations SET event_count = ?, status = ?, relation_kind = ? WHERE id = ?",
            (event_count, status, relation_kind, aid),
        )

        if not reviewed_span_exists(conn, rec["id"], start_idx, end_idx, SOURCE_EXCEL_CATALOG):
            insert_reviewed_span(
                conn, rec["id"], start_idx, end_idx,
                source=SOURCE_EXCEL_CATALOG, commit=False,
            )

        set_annotation_tags(conn, aid, "provenance", SOURCE_EXCEL_CATALOG, commit=False)

        if not is_artifact_row:
            for element in split_elements(r["Elements"], known_element_vocab):
                if element not in known_element_vocab:
                    print(f"  [NEW ELEMENT TERM] ID {id_number}: {element!r} -> adding to vocabulary")
                    get_or_create_term(conn, "element", element)
                    known_element_vocab.add(element)
                    counts["new_element_terms"] += 1
                add_annotation_tag(conn, aid, "element", element, commit=False)

        structure = derive_structure(r["sequence_structure"])
        if structure:
            set_annotation_tags(conn, aid, "structure", structure, commit=False)

        id_to_annotation_id[id_number] = aid
        inserted_this_run.add(aid)
        if parent_id_number is not None:
            pending_parents.append((aid, parent_id_number, id_number))

        if counts["imported"] % COMMIT_EVERY == 0:
            conn.commit()

    if not dry_run:
        for aid, parent_id_number, id_number in pending_parents:
            parent_aid = id_to_annotation_id.get(parent_id_number)
            if parent_aid is None:
                print(f"  [WARNING] ID {id_number}'s Parent_ID={parent_id_number} was not imported.")
                continue
            if parent_aid == aid:
                # Only possible when this row collided with its own stated
                # parent's span (a duplicate-span case, see [DUPLICATE SPAN]
                # above) -- a row can't meaningfully be its own parent.
                print(
                    f"  [WARNING] ID {id_number} resolved to the same annotation as its "
                    f"stated parent (ID {parent_id_number}) -- not setting a "
                    "self-referencing parent_annotation_id."
                )
                continue
            conn.execute(
                "UPDATE annotations SET parent_annotation_id = ? WHERE id = ?",
                (parent_aid, aid),
            )
        conn.commit()

    print(
        f"\nDone{' (dry run)' if dry_run else ''}. "
        f"imported={counts['imported']}  already_present={counts['already_present']}  "
        f"out_of_bounds={counts['out_of_bounds']}  "
        f"length_mismatches_reported={counts['length_mismatches']}  "
        f"new_element_terms={counts['new_element_terms']}"
    )
    conn.close()
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", default=None, help="Override the spreadsheet path.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import_signal_catalogue(xlsx_path=args.xlsx, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
