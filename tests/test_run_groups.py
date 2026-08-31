"""
test_run_groups.py
====================
Ticket 25 — scope selection and run-group fan-out. A single action over N
channels or N bands creates one `run_groups` row and N `runs` rows
referencing it. The fan-out target list is baked into the recipe so a
cluster task index can select its own target from it, and a channel fan-out
and a band fan-out are the same code path.

Run from the project root:
    python tests/test_run_groups.py
"""

import inspect
import os
import shutil
import sys
import tempfile

import numpy as np
import panel as pn
import pytest

pn.extension("tabulator")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working import run_groups
from Working.database import bands as db_bands
from Working.database import queries as q
from Working.database import runs as R
from Working.database.schema import init_db
from Working.recipes import make_recipe


def _fresh_db_with_channels(n_channels, n_samples=200, fs=1.0):
    """A fresh temp sqlite db with `n_channels` synthetic recordings (one
    channel each), each backed by a real .npy file so `execute_recipe` can
    actually run. Returns (db_path, tmpdir); caller cleans up tmpdir."""
    tmpdir = tempfile.mkdtemp(prefix="t25_test_")
    db_path = os.path.join(tmpdir, "test.sqlite")
    conn = init_db(db_path)
    for ch in range(n_channels):
        npy_path = os.path.join(tmpdir, f"CH{ch}.npy")
        np.save(npy_path, np.random.default_rng(ch).standard_normal(n_samples))
        q.insert_recording(conn, "fake.mat", ch, fs, n_samples, 0, npy_path)
    conn.close()
    return db_path, tmpdir


def _recording_ids(db_path, source_file="fake.mat"):
    conn = init_db(db_path)
    try:
        return [r["id"] for r in q.list_recordings(conn, source_file)]
    finally:
        conn.close()


def _lowpass_recipe(recording_id, span=(0, 100)):
    return make_recipe(
        recording_id,
        [{"stage": "preprocessing", "algorithm": "lowpass",
          "params": {"cutoff_hz": 0.05}}],
        span=span,
    )


def _run_group_structure(db_path, run_group_id):
    """Read back the on-disk shape of a run group: a (run_group_count,
    [(run_id, run_group_id, recording_id, status), ...]) tuple that both a
    channel and a band fan-out must produce identically."""
    conn = init_db(db_path)
    try:
        n_groups = conn.execute("SELECT COUNT(*) FROM run_groups").fetchone()[0]
        runs = R.list_run_group_runs(conn, run_group_id)
        return n_groups, [(r["id"], r["run_group_id"], r["recording_id"], r["status"])
                          for r in runs]
    finally:
        conn.close()


# ── paired surrogate runs (ticket 44) ────────────────────────────────────────

def test_surrogate_recipe_prepends_surrogate_step():
    recipe = make_recipe(
        1,
        [{"stage": "preprocessing", "algorithm": "lowpass",
          "params": {"cutoff_hz": 0.05}}],
        span=(0, 100),
    )
    surrogate = run_groups.surrogate_recipe(recipe)

    assert surrogate["steps"][0]["stage"] == "preprocessing"
    assert surrogate["steps"][0]["algorithm"] == "surrogate"
    assert surrogate["steps"][1] == recipe["steps"][0]


def test_run_paired_recipe_creates_surrogate_run_linked_by_surrogate_of_run_id():
    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        recipe = make_recipe(
            rec_id,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
        )
        recipe["surrogate"] = True

        out = run_groups.run_paired_recipe(recipe, db_path=db_path)

        assert out.get("surrogate_run_id") is not None
        conn = init_db(db_path)
        try:
            original = R.get_run(conn, out["run_id"])
            surrogate = R.get_run(conn, out["surrogate_run_id"])
            assert surrogate["surrogate_of_run_id"] == original["id"]

            stored_original = R.load_recipe(conn, original["config_id"])
            assert stored_original["surrogate"] is True

            stored_surrogate = R.load_recipe(conn, surrogate["config_id"])
            assert stored_surrogate["steps"][0]["algorithm"] == "surrogate"
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_run_paired_recipe_surrogate_off_is_recorded_on_the_run():
    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        recipe = make_recipe(
            rec_id,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
        )
        recipe["surrogate"] = False

        out = run_groups.run_paired_recipe(recipe, db_path=db_path)

        assert out.get("surrogate_run_id") is None
        conn = init_db(db_path)
        try:
            run = R.get_run(conn, out["run_id"])
            stored = R.load_recipe(conn, run["config_id"])
            assert stored["surrogate"] is False
            assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_surrogate_run_gets_no_recordings_row_and_cannot_create_motif_entry():
    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        recipe = make_recipe(
            rec_id,
            [{"stage": "detection", "algorithm": "spike_v1", "params": {}}],
            span=(0, 100),
        )
        recipe["surrogate"] = True

        out = run_groups.run_paired_recipe(recipe, db_path=db_path)
        assert out.get("surrogate_run_id") is not None

        conn = init_db(db_path)
        try:
            # The surrogate signal is transient: it adds no recordings row.
            assert conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 1

            surrogate_detections = R.list_detections(conn, out["surrogate_run_id"])
            assert surrogate_detections, "expected the surrogate run to produce detections"

            det = surrogate_detections[0]
            with pytest.raises(ValueError):
                R.insert_motif_entry(
                    conn, rec_id, det["start_idx"], det["end_idx"],
                    detection_id=det["id"],
                )
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── channel fan-out ──────────────────────────────────────────────────────────

def test_channel_fan_out_creates_one_group_and_n_runs():
    db_path, tmpdir = _fresh_db_with_channels(3)
    try:
        targets = _recording_ids(db_path)
        recipe = make_recipe(
            targets[0],
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
            fan_out={"kind": "channels", "targets": targets},
        )
        out = run_groups.fan_out_recipe(recipe, db_path=db_path)

        assert out["run_group_id"] is not None
        assert len(out["runs"]) == 3
        assert [r["target"] for r in out["runs"]] == targets

        n_groups, runs = _run_group_structure(db_path, out["run_group_id"])
        assert n_groups == 1, "a fan-out must create exactly one run_groups row"
        assert len(runs) == 3
        assert all(rg == out["run_group_id"] for _, rg, _, _ in runs)
        assert all(status == "completed" for _, _, _, status in runs)
        # each run is over one distinct target channel
        assert {rec_id for _, _, rec_id, _ in runs} == set(targets)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_channel_fan_out_reports_per_item_progress():
    db_path, tmpdir = _fresh_db_with_channels(2)
    try:
        targets = _recording_ids(db_path)
        recipe = make_recipe(
            targets[0],
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
            fan_out={"kind": "channels", "targets": targets},
        )
        progress = []
        out = run_groups.fan_out_recipe(
            recipe, db_path=db_path,
            on_progress=lambda i, n, label: progress.append((i, n, label)),
        )
        assert progress == [(0, 2, targets[0]), (1, 2, targets[1])], (
            f"locally the N runs execute sequentially with per-item progress, "
            f"got {progress}"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── band fan-out ─────────────────────────────────────────────────────────────

def test_band_fan_out_creates_one_group_and_n_runs():
    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        bands = [
            {"label": "slow", "low_hz": 0.05, "high_hz": 0.2},
            {"label": "fast", "low_hz": 0.2, "high_hz": 0.4},
        ]
        recipe = make_recipe(
            rec_id,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
            fan_out={"kind": "bands", "targets": bands},
        )
        out = run_groups.fan_out_recipe(recipe, db_path=db_path)

        assert out["run_group_id"] is not None
        assert len(out["runs"]) == 2

        n_groups, runs = _run_group_structure(db_path, out["run_group_id"])
        assert n_groups == 1
        assert len(runs) == 2
        assert all(rg == out["run_group_id"] for _, rg, _, _ in runs)
        assert all(status == "completed" for _, _, _, status in runs)

        # each run's stored recipe has the matching bandpass step prepended
        conn = init_db(db_path)
        try:
            for run, band in zip(R.list_run_group_runs(conn, out["run_group_id"]), bands):
                stored = R.load_recipe(conn, run["config_id"])
                first = stored["steps"][0]
                assert first["stage"] == "preprocessing"
                assert first["algorithm"] == "bandpass"
                assert first["params"]["low_hz"] == band["low_hz"]
                assert first["params"]["high_hz"] == band["high_hz"]
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_band_fan_out_reuses_existing_band_definitions():
    # The fan-out must not define a parallel band vocabulary to
    # Working/database/bands.py — the labels that name a fan-out's targets
    # come from the existing definitions.
    labels = [label for _, label in db_bands.SPIKE_TRAIN_BANDS]
    assert len(labels) >= 2

    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        bands = [
            {"label": labels[0], "low_hz": 0.05, "high_hz": 0.2},
            {"label": labels[1], "low_hz": 0.2, "high_hz": 0.4},
        ]
        recipe = make_recipe(
            rec_id,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
            fan_out={"kind": "bands", "targets": bands},
        )
        out = run_groups.fan_out_recipe(recipe, db_path=db_path)
        assert len(out["runs"]) == 2
        n_groups, runs = _run_group_structure(db_path, out["run_group_id"])
        assert n_groups == 1 and len(runs) == 2
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── one mechanism for both scopes ────────────────────────────────────────────

def test_channel_and_band_fan_out_share_the_same_code_path():
    """Both scopes produce the same run-group structure — one run_groups row
    and N runs referencing it — so a test can run both and compare."""
    # channel scope
    db_path_c, tmpdir_c = _fresh_db_with_channels(2)
    try:
        targets_c = _recording_ids(db_path_c)
        recipe_c = make_recipe(
            targets_c[0],
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
            fan_out={"kind": "channels", "targets": targets_c},
        )
        out_c = run_groups.fan_out_recipe(recipe_c, db_path=db_path_c)
        struct_c = _run_group_structure(db_path_c, out_c["run_group_id"])
    finally:
        shutil.rmtree(tmpdir_c, ignore_errors=True)

    # band scope
    db_path_b, tmpdir_b = _fresh_db_with_channels(1)
    try:
        rec_id_b = _recording_ids(db_path_b)[0]
        bands_b = [
            {"label": "slow", "low_hz": 0.05, "high_hz": 0.2},
            {"label": "fast", "low_hz": 0.2, "high_hz": 0.4},
        ]
        recipe_b = make_recipe(
            rec_id_b,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
            fan_out={"kind": "bands", "targets": bands_b},
        )
        out_b = run_groups.fan_out_recipe(recipe_b, db_path=db_path_b)
        struct_b = _run_group_structure(db_path_b, out_b["run_group_id"])
    finally:
        shutil.rmtree(tmpdir_b, ignore_errors=True)

    # identical shape: one run_groups row, N runs, all referencing the group
    assert struct_c[0] == 1 and struct_b[0] == 1
    assert len(struct_c[1]) == len(struct_b[1]) == 2
    assert all(rg == out_c["run_group_id"] for _, rg, _, _ in struct_c[1])
    assert all(rg == out_b["run_group_id"] for _, rg, _, _ in struct_b[1])
    assert all(status == "completed" for _, _, _, status in struct_c[1])
    assert all(status == "completed" for _, _, _, status in struct_b[1])


# ── target list baked into the recipe ────────────────────────────────────────

def test_fan_out_target_list_is_baked_into_the_recipe():
    targets = [10, 20, 30]
    recipe = make_recipe(
        10,
        [{"stage": "preprocessing", "algorithm": "lowpass",
          "params": {"cutoff_hz": 0.05}}],
        span=(0, 100),
        fan_out={"kind": "channels", "targets": targets},
    )
    assert recipe["fan_out"]["kind"] == "channels"
    assert recipe["fan_out"]["targets"] == targets

    # a cluster task index selects its own target from the baked-in list
    assert run_groups.target_for_index(recipe, 0) == 10
    assert run_groups.target_for_index(recipe, 2) == 30

    # materializing a target produces a plain per-target recipe (scope stripped)
    per_target = run_groups.materialize_target(recipe, 1)
    assert "fan_out" not in per_target
    assert per_target["recording_id"] == 20
    assert per_target["span"] == [0, 100]


def test_band_fan_out_materializes_a_bandpass_step():
    bands = [{"label": "slow", "low_hz": 0.05, "high_hz": 0.2}]
    recipe = make_recipe(
        7,
        [{"stage": "preprocessing", "algorithm": "lowpass",
          "params": {"cutoff_hz": 0.05}}],
        span=(0, 100),
        fan_out={"kind": "bands", "targets": bands},
    )
    assert run_groups.target_for_index(recipe, 0) == bands[0]

    per_target = run_groups.materialize_target(recipe, 0)
    assert "fan_out" not in per_target
    assert per_target["recording_id"] == 7
    first = per_target["steps"][0]
    assert first["stage"] == "preprocessing"
    assert first["algorithm"] == "bandpass"
    assert first["params"]["low_hz"] == 0.05
    assert first["params"]["high_hz"] == 0.2
    assert len(per_target["steps"]) == 2


# ── T67: run naming / surrogate name inheritance ─────────────────────────────

def test_surrogate_run_inherits_parents_name():
    """PRD: 'A paired surrogate run inherits its parent's name with a
    surrogate suffix.' Naming the parent after the fact must propagate to the
    already-linked surrogate, so a paired run is not an anonymous stranger."""
    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        recipe = make_recipe(
            rec_id,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
        )
        recipe["surrogate"] = True

        out = run_groups.run_paired_recipe(recipe, db_path=db_path)
        assert out.get("surrogate_run_id") is not None

        conn = init_db(db_path)
        try:
            R.update_run(conn, out["run_id"], name="tuned lowpass")
            surrogate = R.get_run(conn, out["surrogate_run_id"])
            assert surrogate["name"] == "tuned lowpass" + R.SURROGATE_NAME_SUFFIX
            # the parent's own name is untouched by the inheritance
            assert R.get_run(conn, out["run_id"])["name"] == "tuned lowpass"
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_surrogate_linked_to_named_parent_inherits_name():
    """Linking a surrogate to an already-named parent copies the parent's name
    with the surrogate marker at link time."""
    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        recipe = make_recipe(
            rec_id,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
        )
        conn = init_db(db_path)
        try:
            config_id, _ = R.get_or_create_config(conn, recipe)
            parent_id = R.insert_run(conn, config_id, rec_id, 0, 100,
                                     status="completed", name="raw comparison")
            surrogate_id = R.insert_run(conn, config_id, rec_id, 100, 200,
                                        status="completed")
            R.update_run(conn, surrogate_id, surrogate_of_run_id=parent_id)
            surrogate = R.get_run(conn, surrogate_id)
            assert surrogate["name"] == "raw comparison" + R.SURROGATE_NAME_SUFFIX
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_surrogate_name_follows_parent_rename():
    """A surrogate's inherited name tracks the parent's rename: it is not a
    one-shot copy."""
    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        recipe = make_recipe(
            rec_id,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
        )
        conn = init_db(db_path)
        try:
            config_id, _ = R.get_or_create_config(conn, recipe)
            parent_id = R.insert_run(conn, config_id, rec_id, 0, 100,
                                     status="completed", name="first")
            surrogate_id = R.insert_run(conn, config_id, rec_id, 100, 200,
                                        status="completed")
            R.update_run(conn, surrogate_id, surrogate_of_run_id=parent_id)
            assert R.get_run(conn, surrogate_id)["name"] == "first" + R.SURROGATE_NAME_SUFFIX

            R.update_run(conn, parent_id, name="second")
            surrogate = R.get_run(conn, surrogate_id)
            assert surrogate["name"] == "second" + R.SURROGATE_NAME_SUFFIX
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_manually_named_surrogate_is_left_alone():
    """A surrogate the researcher has explicitly renamed is not clobbered when
    the parent is renamed again."""
    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        recipe = make_recipe(
            rec_id,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
        )
        conn = init_db(db_path)
        try:
            config_id, _ = R.get_or_create_config(conn, recipe)
            parent_id = R.insert_run(conn, config_id, rec_id, 0, 100,
                                     status="completed", name="first")
            surrogate_id = R.insert_run(conn, config_id, rec_id, 100, 200,
                                        status="completed", name="my explicit surrogate")
            R.update_run(conn, surrogate_id, surrogate_of_run_id=parent_id)
            # explicit name is respected at link time
            assert R.get_run(conn, surrogate_id)["name"] == "my explicit surrogate"

            R.update_run(conn, parent_id, name="second")
            # ... and after a parent rename
            assert R.get_run(conn, surrogate_id)["name"] == "my explicit surrogate"
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_run_history_browser_shows_and_edits_name():
    """Headless construction check: the run-history table carries the run name
    in its own column, and only that column is editable."""
    from UI.workspaces.analyse.history import RunHistoryBrowser

    db_path, tmpdir = _fresh_db_with_channels(1)
    try:
        rec_id = _recording_ids(db_path)[0]
        recipe = make_recipe(
            rec_id,
            [{"stage": "preprocessing", "algorithm": "lowpass",
              "params": {"cutoff_hz": 0.05}}],
            span=(0, 100),
        )
        conn = init_db(db_path)
        try:
            config_id, _ = R.get_or_create_config(conn, recipe)
            R.insert_run(conn, config_id, rec_id, 0, 100,
                         status="completed", name="tuned lowpass")
        finally:
            conn.close()

        conn = init_db(db_path)
        try:
            class _FakeApp:
                def __init__(self, conn):
                    self.conn = conn
                    self.chain_builder = None
                    self.tabs = None

            browser = RunHistoryBrowser(_FakeApp(conn))
            layout = browser.layout()
            assert layout is not None
            assert "name" in browser.table.value.columns
            assert browser.table.value.iloc[0]["name"] == "tuned lowpass"
            # the name column is the only editable one in the table
            assert browser.table.disabled is False
            assert browser.table.editors["name"] is not None
            assert browser.table.editors["id"] is None
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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
        except Exception as e:
            print(f"[FAIL] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
