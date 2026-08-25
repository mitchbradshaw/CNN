"""
test_manifest.py
=================
Tests for T27: the single manifest schema owner (`Working/manifest.py`), the
`run_recipe.py` manifest writer, and the one generic manifest import action.

The manifest is the portability payload for cluster work: `run_recipe.py`
writes one beside its artifacts on every invocation (including failed runs),
and a single import action reads any manifest at a matching relative path and
reconstructs the local `configs`/`runs`/`detections`/`artifacts` rows.

Covered here:

  - the manifest carries every required field (recipe, config hash, run status,
    step timings, detections, artifact paths, code version, timestamps);
  - the round-trip: write a manifest, import it into an empty database, and
    the reconstructed run rows match the original — including step timings and
    detection sample ranges;
  - importing the same manifest twice does not duplicate runs or detections;
  - a failed run still gets a manifest (status='failed', error_text, partial
    step timings);
  - the manifest lands beside its run's artifacts;
  - the UI import action constructs as a Panel surface with non-None panes;
  - `run_recipe.py` writes a manifest on every invocation, including failed
    runs (exercised end-to-end through the CLI).

Run from the project root:
    python tests/test_manifest.py
"""

import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import panel as pn

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.execution import execute_recipe
from Working.recipes import make_recipe
from Working import manifest
from UI.admin import ManifestImport


# ── helpers ──────────────────────────────────────────────────────────────────

def _temp_db_path():
    tf = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tf.close()
    return tf.name


def _fresh_synthetic_recording(n_samples=200, fs=1.0, source_file="fake.mat"):
    """A tiny synthetic channel + fresh db, cleaned up via the returned
    tmpdir. Returns (db_path, npy_path, tmpdir)."""
    tmpdir = tempfile.mkdtemp(prefix="t27_")
    npy_path = os.path.join(tmpdir, "CH0.npy")
    np.save(npy_path, np.random.default_rng(0).standard_normal(n_samples))
    db_path = os.path.join(tmpdir, "test.sqlite")
    conn = init_db(db_path)
    q.insert_recording(conn, source_file, 0, fs, n_samples, 0, npy_path)
    conn.close()
    return db_path, npy_path, tmpdir


def _run_detection_recipe(db_path, results_dir):
    """matrix_profile -> threshold over the full 200-sample synthetic channel.
    Writes exactly one deterministic detection (span [0, 200 - m + 1]) and one
    encoding artifact, mirroring test_execution.py's established pattern."""
    import Adapters.detection_matrix_profile as mp_adapter

    prior = mp_adapter.RESULTS_DIR
    mp_adapter.RESULTS_DIR = results_dir
    try:
        recipe = make_recipe(1, [
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": 0.1, "backend": "stump"}},
            {"stage": "detection", "algorithm": "threshold",
             "params": {"threshold": -1.0}},
        ], span=(0, 200))
        return execute_recipe(recipe, db_path=db_path)
    finally:
        mp_adapter.RESULTS_DIR = prior


def _write_source_manifest():
    """Run a detection recipe in a fresh source db and write its manifest.
    Returns (manifest_path, source_tmpdir, orig_rows). The source_tmpdir holds
    the channel .npy and the encoding artifact, so it must outlive the import."""
    src_db, _npy, src_tmpdir = _fresh_synthetic_recording(200)
    out = _run_detection_recipe(src_db, os.path.join(src_tmpdir, "results"))
    conn = init_db(src_db)
    try:
        orig = R.list_runs(conn)[0]
        orig_dets = R.list_detections(conn, orig["id"])
        orig_artifacts = R.list_artifacts(conn, orig["id"])
        orig_config = R.get_config(conn, orig["config_id"])
        manifest_path = manifest.write_manifest(
            conn, [orig["id"]], out_dir=os.path.join(src_tmpdir, "manifest_out"),
        )
    finally:
        conn.close()
    return manifest_path, src_tmpdir, (orig, orig_dets, orig_artifacts, orig_config)


# ── required fields ──────────────────────────────────────────────────────────

def test_manifest_carries_all_required_fields():
    """AC: the manifest carries recipe, config hash, run status, step timings,
    detections, artifact paths, code version and timestamps."""
    db_path, _npy, tmpdir = _fresh_synthetic_recording(200)
    try:
        out = _run_detection_recipe(db_path, os.path.join(tmpdir, "results"))
        assert out["detections_written"] == 1

        conn = init_db(db_path)
        try:
            manifest_path = manifest.write_manifest(
                conn, [out["run_id"]], out_dir=os.path.join(tmpdir, "manifest_out"),
            )
        finally:
            conn.close()

        with open(manifest_path) as f:
            data = json.load(f)

        assert data["manifest_version"] == manifest.MANIFEST_VERSION
        assert isinstance(data["code_version"], str) and data["code_version"]
        assert "created_at" in data and data["created_at"]

        run_data = data["runs"][0]
        assert run_data["config_hash"] == out["config_hash"]
        assert run_data["recipe"]["recording_id"] == 1
        assert run_data["recipe"]["span"] == [0, 200]
        assert run_data["status"] == "completed"
        assert run_data["span_start"] == 0
        assert run_data["span_end"] == 200
        assert "started_at" in run_data and run_data["started_at"]
        assert "finished_at" in run_data and run_data["finished_at"]
        assert isinstance(run_data["duration_s"], float)
        assert isinstance(run_data["step_timings"], dict) and run_data["step_timings"]
        assert run_data["recording"]["source_file"] == "fake.mat"
        assert run_data["recording"]["channel"] == 0
        assert run_data["recording"]["n_samples"] == 200
        assert len(run_data["detections"]) == 1
        assert run_data["detections"][0]["start_idx"] == 0
        assert run_data["detections"][0]["end_idx"] == 200 - 6 + 1
        assert len(run_data["artifacts"]) == 1
        assert run_data["artifacts"][0]["kind"] == "encoding"
        assert run_data["artifacts"][0]["path"]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── round-trip ───────────────────────────────────────────────────────────────

def test_manifest_round_trip_reconstructs_run_rows():
    """AC: write a manifest, import it into an empty database, and the
    reconstructed run rows match the original — including step timings and
    detection sample ranges."""
    manifest_path, src_tmpdir, (orig, orig_dets, orig_artifacts, orig_config) = \
        _write_source_manifest()

    dst_tmpdir = tempfile.mkdtemp(prefix="t27_dst_")
    dst_db = os.path.join(dst_tmpdir, "dst.sqlite")
    init_db(dst_db).close()  # genuinely empty: no recordings, no configs, no runs
    try:
        conn = init_db(dst_db)
        try:
            summary = manifest.import_manifest(conn, manifest_path)
            assert len(summary["imported_runs"]) == 1
            assert summary["imported_detections"] == 1
            assert summary["imported_artifacts"] == 1

            runs = R.list_runs(conn)
            assert len(runs) == 1
            got = runs[0]

            assert got["recording_id"] == orig["recording_id"]
            assert got["span_start"] == orig["span_start"]
            assert got["span_end"] == orig["span_end"]
            assert got["status"] == orig["status"]
            assert got["duration_s"] == orig["duration_s"]
            assert json.loads(got["step_timings_json"]) == json.loads(orig["step_timings_json"])

            got_config = R.get_config(conn, got["config_id"])
            assert got_config["config_hash"] == orig_config["config_hash"]

            got_dets = R.list_detections(conn, got["id"])
            assert len(got_dets) == len(orig_dets)
            for gd, od in zip(got_dets, orig_dets):
                assert gd["start_idx"] == od["start_idx"]
                assert gd["end_idx"] == od["end_idx"]
                assert gd["score"] == od["score"]

            got_artifacts = R.list_artifacts(conn, got["id"])
            assert len(got_artifacts) == len(orig_artifacts)
            assert got_artifacts[0]["kind"] == orig_artifacts[0]["kind"]
        finally:
            conn.close()
    finally:
        shutil.rmtree(src_tmpdir, ignore_errors=True)
        shutil.rmtree(dst_tmpdir, ignore_errors=True)


def test_importing_manifest_twice_does_not_duplicate():
    """AC: importing the same manifest twice does not duplicate runs or
    detections."""
    manifest_path, src_tmpdir, _orig = _write_source_manifest()

    dst_tmpdir = tempfile.mkdtemp(prefix="t27_dst_")
    dst_db = os.path.join(dst_tmpdir, "dst.sqlite")
    init_db(dst_db).close()
    try:
        conn = init_db(dst_db)
        try:
            s1 = manifest.import_manifest(conn, manifest_path)
            assert len(s1["imported_runs"]) == 1

            s2 = manifest.import_manifest(conn, manifest_path)
            assert len(s2["imported_runs"]) == 0
            assert len(s2["skipped_runs"]) == 1

            runs = R.list_runs(conn)
            assert len(runs) == 1
            run_id = runs[0]["id"]
            assert len(R.list_detections(conn, run_id)) == 1
            assert len(R.list_artifacts(conn, run_id)) == 1
        finally:
            conn.close()
    finally:
        shutil.rmtree(src_tmpdir, ignore_errors=True)
        shutil.rmtree(dst_tmpdir, ignore_errors=True)


# ── failed runs ──────────────────────────────────────────────────────────────

def test_write_manifest_handles_failed_run():
    """A failed run still produces a manifest: status='failed', the error text,
    and whatever step timings/current_step were recorded before the crash."""
    db_path = _temp_db_path()
    out_dir = tempfile.mkdtemp(prefix="t27_fail_")
    try:
        conn = init_db(db_path)
        try:
            rec_id = q.insert_recording(conn, "fake.mat", 0, 1.0, 100, 0, "fake/CH0.npy")
            recipe = make_recipe(1, [
                {"stage": "preprocessing", "algorithm": "lowpass",
                 "params": {"cutoff_hz": 0.05}},
            ], span=(0, 100))
            config_id, _ = R.get_or_create_config(conn, recipe)
            run_id = R.insert_run(conn, config_id, rec_id, 0, 100,
                                  status="running", started_at="2026-01-01T00:00:00Z")
            R.update_run(conn, run_id, status="failed", finished_at="2026-01-01T00:00:01Z",
                         duration_s=0.5, error_text="ValueError: boom",
                         step_timings_json=json.dumps({"0": 0.5}), current_step=0)
            manifest_path = manifest.write_manifest(conn, [run_id], out_dir=out_dir)
        finally:
            conn.close()

        with open(manifest_path) as f:
            data = json.load(f)
        run_data = data["runs"][0]
        assert run_data["status"] == "failed"
        assert "ValueError" in run_data["error_text"]
        assert run_data["step_timings"] == {"0": 0.5}
        assert run_data["current_step"] == 0
    finally:
        os.unlink(db_path)
        shutil.rmtree(out_dir, ignore_errors=True)


# ── path derivation ──────────────────────────────────────────────────────────

def test_manifest_written_beside_artifacts():
    """Without an explicit out_dir, the manifest lands in the directory of the
    run's first artifact."""
    db_path = _temp_db_path()
    out_dir = tempfile.mkdtemp(prefix="t27_path_")
    try:
        conn = init_db(db_path)
        try:
            rec_id = q.insert_recording(conn, "fake.mat", 0, 1.0, 100, 0, "fake/CH0.npy")
            recipe = make_recipe(1, [
                {"stage": "preprocessing", "algorithm": "lowpass",
                 "params": {"cutoff_hz": 0.05}},
            ], span=(0, 100))
            config_id, _ = R.get_or_create_config(conn, recipe)
            run_id = R.insert_run(conn, config_id, rec_id, 0, 100, status="completed")
            R.update_run(conn, run_id, status="completed")
            R.insert_artifact(conn, run_id, kind="encoding",
                              path=os.path.join(out_dir, "foo.npz"))
            manifest_path = manifest.write_manifest(conn, [run_id])
            expected = os.path.join(out_dir, "manifest.json")
            assert manifest_path.replace("\\", "/") == expected.replace("\\", "/")
        finally:
            conn.close()
    finally:
        os.unlink(db_path)
        shutil.rmtree(out_dir, ignore_errors=True)


# ── run_recipe.py CLI (writes a manifest every invocation) ───────────────────

def _invoke_run_recipe(recipe_dict, db_path, out_dir):
    """Write a recipe JSON and invoke run_recipe.py in a subprocess."""
    tmpdir = tempfile.mkdtemp(prefix="t27_cli_")
    recipe_path = os.path.join(tmpdir, "recipe.json")
    with open(recipe_path, "w") as f:
        json.dump(recipe_dict, f)
    try:
        return subprocess.run(
            [sys.executable, "Pipelines/run_recipe/run_recipe.py",
             "--config", recipe_path, "--db", db_path, "--out-dir", out_dir],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_run_recipe_cli_writes_manifest_on_success():
    """AC: run_recipe.py writes a manifest on every invocation — success path
    exercised end-to-end through the CLI."""
    db_path, _npy, tmpdir = _fresh_synthetic_recording(200)
    out_dir = os.path.join(tmpdir, "out")
    try:
        result = _invoke_run_recipe(
            {"recording_id": 1, "span": [0, 200], "steps": [
                {"stage": "preprocessing", "algorithm": "lowpass",
                 "params": {"cutoff_hz": 0.05}},
            ]},
            db_path, out_dir,
        )
        assert result.returncode == 0, result.stderr
        with open(os.path.join(out_dir, "manifest.json")) as f:
            data = json.load(f)
        assert data["runs"][0]["status"] == "completed"
        assert data["runs"][0]["recipe"]["recording_id"] == 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_run_recipe_cli_writes_manifest_on_failure():
    """AC: run_recipe.py writes a manifest on every invocation — a failed run
    still produces one, with status='failed' and the error text."""
    tmpdir = tempfile.mkdtemp(prefix="t27_cli_fail_")
    db_path = os.path.join(tmpdir, "test.sqlite")
    conn = init_db(db_path)
    # npy path that does not exist -> execute_recipe fails while loading signal
    q.insert_recording(conn, "fake.mat", 0, 1.0, 200, 0,
                       os.path.join(tmpdir, "MISSING.npy"))
    conn.close()
    out_dir = os.path.join(tmpdir, "out")
    try:
        result = _invoke_run_recipe(
            {"recording_id": 1, "span": [0, 200], "steps": [
                {"stage": "preprocessing", "algorithm": "lowpass",
                 "params": {"cutoff_hz": 0.05}},
            ]},
            db_path, out_dir,
        )
        assert result.returncode != 0
        with open(os.path.join(out_dir, "manifest.json")) as f:
            data = json.load(f)
        assert data["runs"][0]["status"] == "failed"
        assert data["runs"][0]["error_text"]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── UI import action ─────────────────────────────────────────────────────────

def test_admin_manifest_import_surface_constructs():
    """The cluster-job import action is a Panel surface; a broken dynamic map
    here would render as a silently blank pane, so it must construct with the
    expected non-None panes (repo's admin/ribbon construction-test pattern)."""
    db_path = _temp_db_path()
    try:
        conn = init_db(db_path)
        try:
            surf = ManifestImport(conn)
            layout = surf.layout()
            assert isinstance(layout, pn.Column)
            assert any(
                isinstance(o, pn.widgets.TextInput) and o.name == "Manifest path"
                for o in layout.objects
            )
            assert any(
                isinstance(o, pn.widgets.Button) and "Import" in o.name
                for o in layout.objects
            )
            assert any(isinstance(o, pn.pane.Markdown) for o in layout.objects)
        finally:
            conn.close()
    finally:
        os.unlink(db_path)


# ── runner ───────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, skipped, failed = 0, 0, []
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
