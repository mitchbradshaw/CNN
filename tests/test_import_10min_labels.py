"""
test_import_10min_labels.py
=============================
Tests for Pipelines/import_labels/import_10min_labels.py: idempotency
against the real label JSON files, and the flag -> 'artifact' verdict
mapping (flag is a distinct class, not a form of "not interesting").

Uses a throwaway temp database with fabricated `recordings` rows (the real
per-channel length for M2_aug_concat_fs1.mat, so real label indices resolve
correctly) — never touches DATA/db/annotations.sqlite. Requires the real
label files under DATA/derived/windows/10min_fs1.0/labels/, matching this
repo's existing convention of tests depending on DATA/ being present
locally (see tests/test_analysis_modules.py).

Run from the project root:
    python tests/test_import_10min_labels.py
"""

import inspect
import json
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
from Pipelines.import_labels.import_10min_labels import (
    SOURCE_RECORDING,
    _label_dir,
    import_10min_labels,
)

REAL_L = 2_595_600  # M2_aug_concat_fs1.mat, verified in Step 1 investigation
REAL_N_CHANNELS = 16


def _labels_available():
    return os.path.isdir(_label_dir())


def _fresh_db_with_fabricated_recording():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    conn = init_db(tf.name)
    for ch in range(REAL_N_CHANNELS):
        q.insert_recording(
            conn, SOURCE_RECORDING, ch, 1.0, REAL_L, ch * REAL_L,
            f"DATA/derived/channels/M2_aug_concat_fs1/CH{ch}.npy",
        )
    conn.close()
    return tf.name


def test_import_is_idempotent():
    if not _labels_available():
        print("  (skipped: DATA/derived/windows/10min_fs1.0/labels not present)")
        return
    db_path = _fresh_db_with_fabricated_recording()
    try:
        first = import_10min_labels(db_path=db_path)
        assert first["imported"] > 0
        assert first["already_present"] == 0

        second = import_10min_labels(db_path=db_path)
        assert second["imported"] == 0
        assert second["already_present"] == first["imported"]
        assert second["quarantined"] == first["quarantined"]
        assert second["out_of_bounds"] == first["out_of_bounds"]
    finally:
        os.unlink(db_path)


def test_flag_maps_to_artifact_not_not_interesting():
    if not _labels_available():
        print("  (skipped: DATA/derived/windows/10min_fs1.0/labels not present)")
        return
    flag_path = os.path.join(_label_dir(), "10min_flag_fs_1.00.json")
    if not os.path.isfile(flag_path):
        print("  (skipped: flag label file not present)")
        return
    with open(flag_path) as f:
        flagged_starts = json.load(f)["starts"]
    assert flagged_starts, "expected at least one flagged window"

    db_path = _fresh_db_with_fabricated_recording()
    try:
        import_10min_labels(db_path=db_path)
        conn = init_db(db_path)
        channel, local = q.global_to_local(flagged_starts[0], REAL_L)
        recording_id = q.get_recording(conn, SOURCE_RECORDING, channel)["id"]
        rows = [r for r in q.list_annotations(conn, recording_id)
                if r["start_idx"] == local and r["source"] == q.SOURCE_IMPORTED_10MIN]
        assert len(rows) == 1
        assert rows[0]["verdict"] == "artifact"
        conn.close()
    finally:
        os.unlink(db_path)


def test_dry_run_writes_nothing():
    if not _labels_available():
        print("  (skipped: DATA/derived/windows/10min_fs1.0/labels not present)")
        return
    db_path = _fresh_db_with_fabricated_recording()
    try:
        counts = import_10min_labels(db_path=db_path, dry_run=True)
        assert counts["imported"] > 0
        conn = init_db(db_path)
        total = conn.execute("SELECT COUNT(*) AS n FROM annotations").fetchone()["n"]
        assert total == 0
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
