"""
test_import_signal_catalogue.py
==================================
Tests for Pipelines/import_catalogue/: the pure parsing functions (pack/
channel -> global channel, hours -> sample index, Parent_ID=0 -> NULL,
Elements multi-value splitting) and importer idempotency against the real
`DATA/catalogue/signal_catalog.xlsx`.

Run from the project root:
    python tests/test_import_signal_catalogue.py
"""

import inspect
import os
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
from Working.database import queries as q
from Pipelines.import_catalogue.parsing import (
    derive_relation_kind,
    derive_structure,
    hours_to_sample_index,
    normalize_parent_id,
    pack_channel_to_global,
    parse_event_count,
    split_elements,
)
from Pipelines.import_catalogue.import_signal_catalogue import (
    DEFAULT_XLSX_PATH,
    SOURCE_EXCEL_CATALOG,
    import_signal_catalogue,
)

VOCAB = {"sharkfin", "crestedwave", "furrycaterpillar", "rollinghill", "halfdome",
          "ridge", "trough", "sharp_trough", "spike", "spore_drop", "stegasaurus",
          "tonic_bursting", "cycle_sequence", "other"}


# ── pack/channel -> global channel ──────────────────────────────────────────

def test_pack_channel_to_global_corners():
    assert pack_channel_to_global(0, 0) == 0
    assert pack_channel_to_global(3, 3) == 15
    assert pack_channel_to_global(1, 2) == 6


def test_pack_channel_to_global_out_of_range_raises():
    try:
        pack_channel_to_global(4, 0)
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── hours -> sample index ───────────────────────────────────────────────────

def test_hours_to_sample_index_basic():
    assert hours_to_sample_index(1.0, 1.0) == 3600
    assert hours_to_sample_index(0.5, 2.0) == 3600


def test_hours_to_sample_index_rounds():
    # 337.9h * 3600 * 1.0 = 1216440.0 exactly; check a non-exact case rounds
    assert hours_to_sample_index(337.9, 1.0) == 1216440
    assert hours_to_sample_index(0.0002777778, 3600.0) == round(0.0002777778 * 3600 * 3600)


# ── Parent_ID -> NULL ────────────────────────────────────────────────────────

def test_parent_id_zero_is_none():
    assert normalize_parent_id(0) is None


def test_parent_id_nonzero_passthrough():
    assert normalize_parent_id(5) == 5
    assert normalize_parent_id("7") == 7


# ── Elements multi-value splitting ──────────────────────────────────────────

def test_split_elements_semicolon():
    assert split_elements("crestedwave ; sharkfin", VOCAB) == ["crestedwave", "sharkfin"]


def test_split_elements_single():
    assert split_elements("sharkfin", VOCAB) == ["sharkfin"]


def test_split_elements_plural_normalizes_to_known_vocab():
    assert split_elements("sharkfins, troughs", VOCAB) == ["sharkfin", "trough"]


def test_split_elements_alias_applied():
    # "Stegasauras" is a confirmed typo for the seeded "stegasaurus"
    assert split_elements("Stegasauras", VOCAB) == ["stegasaurus"]


def test_split_elements_empty():
    assert split_elements(None, VOCAB) == []
    assert split_elements("", VOCAB) == []


# ── event_count / structure / relation_kind spot checks ─────────────────────

def test_parse_event_count_examples_from_brief():
    assert parse_event_count("16 cycles", None) == 16
    assert parse_event_count("4x sharkfin sequence", None) == 4
    assert parse_event_count("14x sharkfin sequence", None) == 14
    assert parse_event_count("2 sharps", None) == 2
    assert parse_event_count("Regular sequence of 100 furrycaterpillars", None) == 100
    assert parse_event_count("3 sequences", None) == 3


def test_parse_event_count_multiple_counts_is_null():
    assert parse_event_count(None, "60 spikes (7mV) then 40 spikes (6mV)") is None


def test_parse_event_count_no_count_is_null():
    assert parse_event_count("nested sharkfin sequence", None) is None


def test_derive_structure_type_specimen_wins():
    assert derive_structure("single cycle; type specimen") == "type_specimen"


def test_derive_relation_kind():
    assert derive_relation_kind("single cycle; type specimen", "", True) == "type_specimen"
    assert derive_relation_kind("1 sharkfin", "", True) == "sub_window"
    assert derive_relation_kind("nested sharkfin sequence", "", False) is None


# ── importer idempotency against the real spreadsheet ───────────────────────

REAL_L = {"M2_concat_fs1.mat": 1_016_952, "M2_aug_concat_fs1.mat": 2_595_600}


def _spreadsheet_available():
    return os.path.isfile(DEFAULT_XLSX_PATH)


def _fresh_db_with_fabricated_recordings():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    for source_file, L in REAL_L.items():
        for ch in range(16):
            q.insert_recording(conn, source_file, ch, 1.0, L, ch * L,
                                f"DATA/derived/channels/{source_file}/CH{ch}.npy")
    conn.close()
    return tf.name


def test_import_is_idempotent():
    if not _spreadsheet_available():
        print("  (skipped: DATA/catalogue/signal_catalog.xlsx not present)")
        return
    db_path = _fresh_db_with_fabricated_recordings()
    try:
        first = import_signal_catalogue(db_path=db_path)
        assert first["imported"] > 0
        # The real catalogue has one genuine duplicate span (ID 19 restates
        # ID 2's exact channel/start/stop) -- that shows up as
        # already_present even on a first, from-scratch run.
        first_total = first["imported"] + first["already_present"]

        second = import_signal_catalogue(db_path=db_path)
        assert second["imported"] == 0
        assert second["already_present"] == first_total
    finally:
        os.unlink(db_path)


def test_import_drops_rows_outside_m2_datasets():
    if not _spreadsheet_available():
        print("  (skipped: DATA/catalogue/signal_catalog.xlsx not present)")
        return
    db_path = _fresh_db_with_fabricated_recordings()
    try:
        counts = import_signal_catalogue(db_path=db_path, dry_run=True)
        # 37 rows total, 5 dropped (blank/labview/mushroom) -> 32 kept
        assert counts["imported"] + counts["already_present"] == 32
    finally:
        os.unlink(db_path)


def test_import_reports_length_mismatches():
    if not _spreadsheet_available():
        print("  (skipped: DATA/catalogue/signal_catalog.xlsx not present)")
        return
    db_path = _fresh_db_with_fabricated_recordings()
    try:
        counts = import_signal_catalogue(db_path=db_path, dry_run=True)
        assert counts["length_mismatches"] == 4  # IDs 2, 8, 9, 10
    finally:
        os.unlink(db_path)


def test_import_sets_verdict_artifact_for_id_13():
    if not _spreadsheet_available():
        print("  (skipped: DATA/catalogue/signal_catalog.xlsx not present)")
        return
    db_path = _fresh_db_with_fabricated_recordings()
    try:
        import_signal_catalogue(db_path=db_path)
        conn = init_db(db_path)
        row = conn.execute(
            "SELECT verdict FROM annotations WHERE source = ? AND note LIKE ?",
            (SOURCE_EXCEL_CATALOG, "%All channels identical%"),
        ).fetchone()
        assert row is not None
        assert row["verdict"] == "artifact"
        conn.close()
    finally:
        os.unlink(db_path)


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
