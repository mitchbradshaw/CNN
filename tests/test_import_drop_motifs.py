"""
test_import_drop_motifs.py
==========================
Contract tests for the drop-motif library importer (ticket 50): reading the
tracked seed bundle and populating the shape-first motif library.

The importer is the third step of a pipeline whose first two steps already
exist and are imported, not reimplemented:

    store.load_run(bundle_dir)      -> 410 events, 410 snippets
    cluster.cluster_events(ev, sn)  -> N shape families

This ticket adds the step that turns a clustering into library rows:

    motif_entry   one event-scale row per shape family (the exemplar is the
                  member closest to the family's mean waveform) and, since
                  ticket 52, one train-scale row per spike train (`span_key`)
                  in the bundle.
    motif_member  one row per imported motif, keyed on content
                  (recording, start, end) and never duplicated.
    motif_edge    the within-family distances, carrying the distance
                  function, threshold and recipe hash.

The acceptance criteria under test:

1. The importer runs headlessly against the tracked seed bundle and exits 0.
2. After a run, `motif_entry` holds one row per shape family and
   `motif_member` holds one row per imported motif.
3. Every member carries the recording, channel and sample range it came
   from, resolvable back to a `recordings` row.
4. `motif_edge` rows record the distance function, threshold and recipe hash
   that produced them.
5. Running the importer twice does not duplicate members (idempotent).
6. The existing Library grid renders the imported entries without
   modification (headless construction test).

Headless: uses the tracked seed bundle and an in-memory sqlite database —
never the real annotations database.
"""

import inspect
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import panel as pn
pn.extension("tabulator")
import holoviews as hv
hv.extension("bokeh")

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.Detection.drop_motifs import store

from Pipelines.import_drop_motifs import import_drop_motifs, main as importer_main

# The tracked seed bundle — present in every worktree by construction.
BUNDLE_DIR = os.path.join(
    PROJECT_ROOT, "DATA", "library_seed", "drop_motifs5", "motifs",
)

SEED_N_MOTIFS = 410  # the manifest's n_motifs; every motif becomes a member.


class _FakeLibraryApp:
    """The only app surface `LibraryGrid` is allowed to read."""

    def __init__(self, conn):
        self.conn = conn


def _seed_content_set():
    """{(source_file, channel, snippet_start_idx, snippet_end_idx)} from the
    seed bundle — the provenance every imported member must resolve to."""
    events = store.load_events(BUNDLE_DIR)
    return {
        (e["source_file"], int(e["channel"]),
         int(e["snippet_start_idx"]), int(e["snippet_end_idx"]))
        for e in events
    }


def _precreate_recordings(conn, npy_dir):
    """Insert a `recordings` row for every distinct (source_file, channel) in
    the seed bundle, each pointing at a scratch .npy long enough to cover the
    bundle's absolute indices. The importer reuses these rows (idempotent on
    (source_file, channel)), which is what lets the Library grid's thumbnails
    slice real arrays."""
    events = store.load_events(BUNDLE_DIR)
    groups = {}
    for e in events:
        key = (e["source_file"], int(e["channel"]))
        groups.setdefault(key, []).append(e)
    for (source_file, channel), evs in groups.items():
        fs = float(evs[0]["fs"])
        n_samples = max(int(e["snippet_end_idx"]) for e in evs)
        npy_path = os.path.join(npy_dir, f"{source_file}.ch{channel}.npy")
        np.save(npy_path, np.zeros(n_samples + 1, dtype=float))
        q.insert_recording(conn, source_file, channel, fs, n_samples + 1, 0, npy_path)


# ── criterion 1 + 2: one entry per family, one member per motif ─────────────

def test_import_populates_library_from_seed_bundle():
    conn = init_db(":memory:")
    try:
        result = import_drop_motifs(conn, BUNDLE_DIR)
        assert result["n_members"] == SEED_N_MOTIFS
        assert result["n_entries"] > 0
        assert result["n_edges"] == result["n_members"] - result["n_entries"]

        entries = R.list_motif_entries(conn)
        assert len(entries) == result["n_entries"] + result["n_train_entries"]
        for entry in entries:
            assert R.list_motif_members(conn, entry["id"]), entry["id"]
    finally:
        conn.close()


def test_edges_carry_distance_function_threshold_and_recipe_hash():
    conn = init_db(":memory:")
    try:
        result = import_drop_motifs(conn, BUNDLE_DIR, n_clusters=12)
        assert result["n_entries"] == 12
        rows = conn.execute(
            "SELECT * FROM motif_edge LIMIT 5"
        ).fetchall()
        assert rows
        for edge in rows:
            assert edge["distance_function"]
            assert edge["threshold"] is not None
            assert edge["recipe_hash"]
            assert edge["distance_value"] is not None
    finally:
        conn.close()


def test_import_with_threshold_only_clusters_by_that_height():
    """A bare `threshold` is the clustering cut: re-clustering at a new
    threshold regroups without re-ingesting (PRD Part 2, Library import)."""
    conn = init_db(":memory:")
    try:
        r12 = import_drop_motifs(conn, BUNDLE_DIR, n_clusters=12)
        threshold = r12["threshold"]
    finally:
        conn.close()

    conn = init_db(":memory:")
    try:
        r = import_drop_motifs(conn, BUNDLE_DIR, threshold=threshold)
        assert r["n_entries"] == 12
        assert r["n_members"] == SEED_N_MOTIFS
        assert r["threshold"] == threshold
    finally:
        conn.close()


# ── criterion 3: provenance survives onto a member row ──────────────────────

def test_every_member_resolves_to_a_seed_event():
    conn = init_db(":memory:")
    try:
        result = import_drop_motifs(conn, BUNDLE_DIR)
        seed = _seed_content_set()
        assert len(seed) == SEED_N_MOTIFS

        members = conn.execute(
            """SELECT m.*, rec.source_file, rec.channel
               FROM motif_member m
               JOIN recordings rec ON rec.id = m.recording_id"""
        ).fetchall()
        # Event-scale members plus train-scale members; both resolve to seed.
        assert len(members) == SEED_N_MOTIFS + result["n_train_members"]
        for m in members:
            key = (m["source_file"], m["channel"], m["start_idx"], m["end_idx"])
            assert key in seed, key
    finally:
        conn.close()


# ── criterion 5: idempotent ─────────────────────────────────────────────────

def test_import_is_idempotent():
    conn = init_db(":memory:")
    try:
        r1 = import_drop_motifs(conn, BUNDLE_DIR)
        r2 = import_drop_motifs(conn, BUNDLE_DIR)

        assert r2["n_members"] == r1["n_members"] == SEED_N_MOTIFS
        assert r2["n_entries"] == r1["n_entries"]
        assert r2["n_edges"] == r1["n_edges"]
        assert r2["n_train_entries"] == r1["n_train_entries"]
        assert r2["n_train_members"] == r1["n_train_members"]

        member_count = conn.execute(
            "SELECT COUNT(*) FROM motif_member"
        ).fetchone()[0]
        assert member_count == SEED_N_MOTIFS + r1["n_train_members"]

        train_entry_count = conn.execute(
            "SELECT COUNT(*) FROM motif_entry WHERE scale = 'train'"
        ).fetchone()[0]
        assert train_entry_count == r1["n_train_entries"]

        edge_count = conn.execute(
            "SELECT COUNT(*) FROM motif_edge"
        ).fetchone()[0]
        assert edge_count == r1["n_edges"]
    finally:
        conn.close()


# ── criterion 1: headless CLI, exits 0 ──────────────────────────────────────

def test_cli_runs_headlessly_against_seed_bundle_and_exits_zero():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.sqlite")
        rc = importer_main([
            "--db", db_path,
            "--bundle", BUNDLE_DIR,
            "--n-clusters", "12",
        ])
        assert rc == 0
        conn = init_db(db_path)
        try:
            member_count = conn.execute(
                "SELECT COUNT(*) FROM motif_member"
            ).fetchone()[0]
            # Event-scale members + train-scale members (every event belongs
            # to exactly one train).
            assert member_count == SEED_N_MOTIFS * 2
        finally:
            conn.close()


# ── T52: train-scale entries, one per spike train ──────────────────────────

def test_importer_writes_one_train_scale_entry_per_spike_train():
    conn = init_db(":memory:")
    try:
        result = import_drop_motifs(conn, BUNDLE_DIR)
        n_trains = len({e["span_key"] for e in store.load_events(BUNDLE_DIR)})
        assert n_trains == 16
        assert result["n_train_entries"] == n_trains

        rows = conn.execute(
            "SELECT * FROM motif_entry WHERE scale = 'train'"
        ).fetchall()
        assert len(rows) == n_trains
    finally:
        conn.close()


def test_train_scale_entry_members_are_that_trains_motifs():
    conn = init_db(":memory:")
    try:
        result = import_drop_motifs(conn, BUNDLE_DIR)
        events = store.load_events(BUNDLE_DIR)

        # expected[span_key] = {(source_file, channel, start, end)}
        expected = {}
        for e in events:
            key = e["span_key"]
            expected.setdefault(key, set()).add(
                (e["source_file"], int(e["channel"]),
                 int(e["snippet_start_idx"]), int(e["snippet_end_idx"])))

        recs = conn.execute(
            "SELECT id, source_file, channel FROM recordings").fetchall()
        rec_id = {(r["source_file"], r["channel"]): r["id"] for r in recs}
        rec_src = {r["id"]: (r["source_file"], r["channel"]) for r in recs}

        # Map each train entry's bounding box back to its span_key.
        box_to_key = {}
        for key, spans in expected.items():
            src, ch = next(iter(spans))[0], next(iter(spans))[1]
            starts = [s[2] for s in spans]
            ends = [s[3] for s in spans]
            box_to_key[(rec_id[(src, ch)], min(starts), max(ends))] = key

        train_entries = conn.execute(
            "SELECT * FROM motif_entry WHERE scale = 'train'"
        ).fetchall()
        assert len(train_entries) == result["n_train_entries"]

        for entry in train_entries:
            box = (entry["recording_id"], entry["start_idx"], entry["end_idx"])
            assert box in box_to_key, box
            key = box_to_key[box]
            members = R.list_motif_members(conn, entry["id"])
            member_spans = {
                (rec_src[m["recording_id"]][0], rec_src[m["recording_id"]][1],
                 m["start_idx"], m["end_idx"])
                for m in members
            }
            assert member_spans == expected[key], key
    finally:
        conn.close()


def test_event_scale_entries_have_scale_event():
    conn = init_db(":memory:")
    try:
        result = import_drop_motifs(conn, BUNDLE_DIR)
        rows = conn.execute(
            "SELECT * FROM motif_entry WHERE scale = 'event'"
        ).fetchall()
        assert len(rows) == result["n_entries"]
        for row in rows:
            assert R.list_motif_members(conn, row["id"])
    finally:
        conn.close()


def test_all_imported_entries_have_an_explicit_scale():
    conn = init_db(":memory:")
    try:
        result = import_drop_motifs(conn, BUNDLE_DIR)
        nulls = conn.execute(
            "SELECT COUNT(*) FROM motif_entry WHERE scale IS NULL"
        ).fetchone()[0]
        assert nulls == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM motif_entry"
        ).fetchone()[0] == result["n_entries"] + result["n_train_entries"]
    finally:
        conn.close()


# ── criterion 6: the Library grid renders imported entries ──────────────────

def test_library_grid_renders_imported_entries():
    from UI.workspaces.library.grid import LibraryGrid

    with tempfile.TemporaryDirectory() as npy_dir:
        conn = init_db(":memory:")
        try:
            _precreate_recordings(conn, npy_dir)
            result = import_drop_motifs(conn, BUNDLE_DIR)
            assert result["n_entries"] > 0

            grid = LibraryGrid(_FakeLibraryApp(conn))
            layout = grid.layout()
            assert layout is not None
            assert len(grid.cards) == result["n_entries"] + result["n_train_entries"]
            assert all(card is not None for card in grid.cards)
        finally:
            conn.close()


# ── runner ──────────────────────────────────────────────────────────────────

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
