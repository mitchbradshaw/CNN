"""
test_vocabulary_and_bands.py
==============================
Tests for Working/database/vocabulary.py and bands.py: the
controlled tag vocabulary (seeding, single/multi-select assignment,
soft-delete) and the derived spike-train-length / duration bands.

Run from the project root:
    python tests/test_vocabulary_and_bands.py
"""

import inspect
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import vocabulary as v
from Working.database import bands as b


def _fresh_conn_with_recording():
    conn = init_db(":memory:")
    v.seed_vocabulary(conn)
    rid = q.insert_recording(conn, "a.mat", 0, 1.0, 10_000, 0, "a/CH0.npy")
    return conn, rid


# ── vocabulary ───────────────────────────────────────────────────────────────

def test_seed_vocabulary_matches_brief():
    conn = init_db(":memory:")
    v.seed_vocabulary(conn)
    elements = {r["value"] for r in v.list_terms(conn, category="element")}
    assert elements == {
        "sharkfin", "crestedwave", "furrycaterpillar", "rollinghill", "halfdome",
        "ridge", "trough", "sharp_trough", "spike", "spore_drop", "stegasaurus",
        "tonic_bursting", "cycle_sequence", "other",
    }
    assert {r["value"] for r in v.list_terms(conn, category="quality")} == \
        {"clean", "noisy", "superimposed", "unclear"}
    assert {r["value"] for r in v.list_terms(conn, category="structure")} == \
        {"single_cycle", "sequence", "nested_sequence", "type_specimen"}
    assert {r["value"] for r in v.list_terms(conn, category="provenance")} == \
        {"manually_sorted_for_cnn", "excel_catalog", "manual_ui"}
    assert {r["value"] for r in v.list_terms(conn, category="status")} == \
        {"candidate", "examined", "confirmed"}


def test_seed_vocabulary_is_idempotent():
    conn = init_db(":memory:")
    v.seed_vocabulary(conn)
    n_before = len(v.list_terms(conn, category="element"))
    v.seed_vocabulary(conn)
    assert len(v.list_terms(conn, category="element")) == n_before


def test_multi_select_element_tags():
    conn, rid = _fresh_conn_with_recording()
    aid = q.insert_annotation(conn, rid, 0, 600, "interesting", source=q.SOURCE_MANUAL_UI)
    v.set_annotation_tags(conn, aid, "element", ["sharkfin", "ridge"])
    assert sorted(v.get_annotation_tags(conn, aid)["element"]) == ["ridge", "sharkfin"]


def test_single_select_replaces_not_accumulates():
    conn, rid = _fresh_conn_with_recording()
    aid = q.insert_annotation(conn, rid, 0, 600, "interesting", source=q.SOURCE_MANUAL_UI)
    v.set_annotation_tags(conn, aid, "quality", "noisy")
    v.set_annotation_tags(conn, aid, "quality", "clean")
    assert v.get_annotation_tags(conn, aid)["quality"] == ["clean"]


def test_deactivate_preserves_existing_assignment():
    conn, rid = _fresh_conn_with_recording()
    aid = q.insert_annotation(conn, rid, 0, 600, "interesting", source=q.SOURCE_MANUAL_UI)
    v.set_annotation_tags(conn, aid, "element", "sharkfin")
    term = v.get_term(conn, "element", "sharkfin")
    v.deactivate_term(conn, term["id"])
    assert v.get_annotation_tags(conn, aid)["element"] == ["sharkfin"]
    assert "sharkfin" not in {r["value"] for r in v.list_terms(conn, category="element")}


def test_unknown_term_raises():
    conn, rid = _fresh_conn_with_recording()
    aid = q.insert_annotation(conn, rid, 0, 600, "interesting", source=q.SOURCE_MANUAL_UI)
    try:
        v.set_annotation_tags(conn, aid, "element", "not_a_real_term")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_annotations_matching_tags_and_across_categories():
    conn, rid = _fresh_conn_with_recording()
    a1 = q.insert_annotation(conn, rid, 0, 600, "interesting", source=q.SOURCE_MANUAL_UI)
    a2 = q.insert_annotation(conn, rid, 700, 1300, "interesting", source=q.SOURCE_MANUAL_UI)
    v.set_annotation_tags(conn, a1, "element", ["sharkfin"])
    v.set_annotation_tags(conn, a1, "quality", "clean")
    v.set_annotation_tags(conn, a2, "element", ["ridge"])
    v.set_annotation_tags(conn, a2, "quality", "clean")

    only_sharkfin = v.annotations_matching_tags(conn, rid, {"element": ["sharkfin"]})
    assert only_sharkfin == {a1}

    both_clean = v.annotations_matching_tags(conn, rid, {"quality": ["clean"]})
    assert both_clean == {a1, a2}

    sharkfin_and_clean = v.annotations_matching_tags(
        conn, rid, {"element": ["sharkfin"], "quality": ["clean"]}
    )
    assert sharkfin_and_clean == {a1}


def test_get_tags_for_recording_matches_per_row_lookup():
    conn, rid = _fresh_conn_with_recording()
    aid = q.insert_annotation(conn, rid, 0, 600, "interesting", source=q.SOURCE_MANUAL_UI)
    v.set_annotation_tags(conn, aid, "element", ["sharkfin", "ridge"])
    bulk = v.get_tags_for_recording(conn, rid)
    assert sorted(bulk[aid]["element"]) == sorted(v.get_annotation_tags(conn, aid)["element"])


# ── bands ────────────────────────────────────────────────────────────────────

def test_spike_train_band_boundaries():
    assert b.spike_train_band(None) is None
    assert b.spike_train_band(4) == "short"
    assert b.spike_train_band(5) == "medium"
    assert b.spike_train_band(9) == "medium"
    assert b.spike_train_band(10) == "long"
    assert b.spike_train_band(1000) == "long"


def test_duration_band_boundaries():
    # 5-band scheme, all boundaries INCLUSIVE (<=) — see Working/config.py.
    assert b.duration_band(0, 59, 1.0) == "short"
    assert b.duration_band(0, 60, 1.0) == "short"        # exactly on the short/medium edge -> short
    assert b.duration_band(0, 61, 1.0) == "medium"
    assert b.duration_band(0, 900, 1.0) == "medium"      # exactly on the medium/long edge -> medium
    assert b.duration_band(0, 901, 1.0) == "long"
    assert b.duration_band(0, 3600, 1.0) == "long"
    assert b.duration_band(0, 3601, 1.0) == "very_long"
    assert b.duration_band(0, 21600, 1.0) == "very_long"
    assert b.duration_band(0, 21601, 1.0) == "extreme"


def test_duration_band_600s_is_medium_not_long():
    """Regression test for the reported bug: every one of the ~11,234
    imported 10-minute (600s) windows showed duration_band="long" because
    the old bounds (60, 600) put 600s exactly on an edge that a strict `<`
    comparison pushed the wrong way. 600s must land comfortably inside
    "medium" (60s < 600s <= 900s), nowhere near either edge."""
    assert b.duration_band(0, 600, 1.0) == "medium"


def test_duration_band_respects_fs():
    # Same sample count, different fs -> different wall-clock duration -> different band.
    assert b.duration_band(0, 30, 1.0) == "short"      # 30 samples / 1Hz = 30s
    assert b.duration_band(0, 30, 0.1) == "medium"      # 30 samples / 0.1Hz = 300s
    assert b.duration_band(0, 6000, 10.0) == "medium"   # 6000 samples / 10Hz = 600s


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
