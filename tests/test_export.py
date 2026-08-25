"""
test_export.py
================
Tests for T45 — the run-group exporter (`Working/export.py`).

A completed run group leaves the tool as a folder a thesis chapter can be
written from, without re-running anything. The export folder contains:

  - manifest.json — ticket 27's manifest schema, imported from
    `Working.manifest` (never restated) and enriched with the per-run
    surrogate block and per-detection adjudications;
  - spans.csv     — one row per span with named columns, so thesis tables
    come out of a spreadsheet rather than a JSON blob;
  - plots/        — a copy of every plot artifact the runs produced.

Covered here:

  - the folder contains a manifest, a spans CSV, and copied plots;
  - the manifest schema is ticket 27's, imported not restated (the base run
    fields of the exported manifest match `Working.manifest.build_manifest`);
  - the manifest covers recipe, config hash, per-run status and timings,
    detections with their adjudications, surrogate counts, artifact paths,
    code version and timestamps;
  - a null surrogate is stated explicitly rather than omitted — the field is
    present and null for an unpaired run;
  - the CSV has one row per span and named columns;
  - the export action constructs as a Panel surface with non-None panes.

Run from the project root:
    python tests/test_export.py
"""

import csv
import inspect
import json
import os
import shutil
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.database import queries as q
from Working.database import runs as R
from Working.database.adjudications import insert_adjudication
from Working.database.schema import init_db
from Working import manifest


# ── helpers ──────────────────────────────────────────────────────────────────

def _fresh_db():
    tmpdir = tempfile.mkdtemp(prefix="t45_")
    db_path = os.path.join(tmpdir, "test.sqlite")
    conn = init_db(db_path)
    return conn, db_path, tmpdir


def _add_recording(conn, tmpdir, channel=0):
    npy_path = os.path.join(tmpdir, f"CH{channel}.npy")
    return q.insert_recording(conn, "fake.mat", channel, 1.0, 200, 0, npy_path)


def _add_config(conn, rec_id):
    recipe = {
        "recording_id": rec_id,
        "span": [0, 200],
        "steps": [
            {"stage": "preprocessing", "algorithm": "lowpass",
             "params": {"cutoff_hz": 0.05}},
        ],
    }
    config_id, config_hash = R.get_or_create_config(conn, recipe)
    return config_id, config_hash


def _plot_artifact(conn, tmpdir, run_id, name):
    """Create a fake plot file on disk and register it as a plot artifact."""
    plot_dir = os.path.join(tmpdir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    path = os.path.join(plot_dir, name)
    with open(path, "wb") as f:
        f.write(b"fake-png-bytes")
    R.insert_artifact(conn, run_id, kind="plot", path=path)
    return path


def _setup_run_group(with_surrogate=True):
    """A fresh db with a run group of two completed runs.

    Run 1 has two detections (one adjudicated) and one plot artifact. Run 2
    has one detection and no surrogate control. When `with_surrogate` is set,
    run 1 is paired with a surrogate control run that carries one detection
    (linked via `runs.surrogate_of_run_id`).

    Returns
    -------
    (conn, db_path, tmpdir, group_id, run1, run2, surrogate_run)
    """
    conn, db_path, tmpdir = _fresh_db()
    rec_id = _add_recording(conn, tmpdir)
    config_id, _config_hash = _add_config(conn, rec_id)

    group_id = R.create_run_group(conn)

    run1 = R.insert_run(conn, config_id, rec_id, 0, 200, status="completed")
    R.update_run(conn, run1, run_group_id=group_id, status="completed",
                 finished_at="2026-01-01T00:00:01Z", duration_s=1.0,
                 step_timings_json=json.dumps({"0": 1.0}))
    R.insert_detection(conn, run1, 10, 20, score=0.8)
    R.insert_detection(conn, run1, 50, 60, score=0.5)
    _plot_artifact(conn, tmpdir, run1, "run1.png")

    run2 = R.insert_run(conn, config_id, rec_id, 0, 200, status="completed")
    R.update_run(conn, run2, run_group_id=group_id, status="completed",
                 finished_at="2026-01-01T00:00:02Z", duration_s=2.0,
                 step_timings_json=json.dumps({"0": 2.0}))
    R.insert_detection(conn, run2, 5, 15, score=0.3)

    surrogate_run = None
    if with_surrogate:
        surrogate_run = R.insert_run(conn, config_id, rec_id, 0, 200,
                                     status="completed")
        R.update_run(conn, surrogate_run, status="completed",
                     finished_at="2026-01-01T00:00:03Z", duration_s=3.0)
        conn.execute("UPDATE runs SET surrogate_of_run_id = ? WHERE id = ?",
                     (run1, surrogate_run))
        conn.commit()
        R.insert_detection(conn, surrogate_run, 11, 21, score=0.7)

    dets1 = R.list_detections(conn, run1)
    insert_adjudication(conn, dets1[0]["id"], "interesting")

    return conn, db_path, tmpdir, group_id, run1, run2, surrogate_run


def _export(conn, group_id, tmpdir):
    """Run the export and return the parsed manifest dict."""
    from Working import export
    out_dir = os.path.join(tmpdir, "export")
    result = export.export_run_group(conn, group_id, out_dir)
    with open(os.path.join(out_dir, "manifest.json")) as f:
        data = json.load(f)
    return result, data, out_dir


# ── folder contents ──────────────────────────────────────────────────────────

def test_export_run_group_writes_manifest_spans_csv_and_plots():
    """AC: exports a folder containing a manifest, a spans table as CSV, and
    copied plots."""
    conn, db_path, tmpdir, group_id, run1, run2, _ = _setup_run_group()
    try:
        result, data, out_dir = _export(conn, group_id, tmpdir)

        assert os.path.isfile(os.path.join(out_dir, "manifest.json"))
        assert len(data["runs"]) == 2

        assert os.path.isfile(os.path.join(out_dir, "spans.csv"))

        plots_dir = os.path.join(out_dir, "plots")
        assert os.path.isdir(plots_dir)
        assert os.path.isfile(os.path.join(plots_dir, "run1.png"))

        # summary tells the caller where everything landed
        assert result["run_group_id"] == group_id
        assert result["run_ids"] == [run1, run2]
        assert result["plots_copied"] == [os.path.join(plots_dir, "run1.png")]
    finally:
        conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── schema: ticket 27's, imported not restated ───────────────────────────────

def test_export_manifest_schema_is_ticket_27s_imported():
    """AC: the manifest schema is ticket 27's, imported not restated — every
    base run field in the exported manifest matches what
    `Working.manifest.build_manifest` produces."""
    conn, db_path, tmpdir, group_id, run1, run2, _ = _setup_run_group()
    try:
        _result, data, _out_dir = _export(conn, group_id, tmpdir)
        run_ids = [r["id"] for r in R.list_run_group_runs(conn, group_id)]
        base = manifest.build_manifest(conn, run_ids)

        assert data["manifest_version"] == manifest.MANIFEST_VERSION
        assert data["code_version"] == base["code_version"]
        assert "created_at" in data and data["created_at"]

        for run_data, base_run in zip(data["runs"], base["runs"]):
            for key in ("config_hash", "recipe", "recording", "span_start",
                        "span_end", "status", "started_at", "finished_at",
                        "duration_s", "step_timings", "artifacts"):
                assert run_data[key] == base_run[key], key
            # detections come from ticket 27 too; the export only adds an
            # adjudication key per detection
            assert [d["start_idx"] for d in run_data["detections"]] == \
                   [d["start_idx"] for d in base_run["detections"]]
            assert [d["end_idx"] for d in run_data["detections"]] == \
                   [d["end_idx"] for d in base_run["detections"]]
    finally:
        conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── required coverage ────────────────────────────────────────────────────────

def test_export_manifest_covers_required_fields():
    """AC: covers recipe, config hash, per-run status and timings, detections
    with their adjudications, surrogate counts, artifact paths, code version
    and timestamps."""
    conn, db_path, tmpdir, group_id, run1, run2, surrogate_run = _setup_run_group()
    try:
        _result, data, _out_dir = _export(conn, group_id, tmpdir)
        run_by_id = _map_manifest_runs(conn, group_id, data)

        r1 = run_by_id[run1]
        assert r1["config_hash"]
        assert r1["recipe"]["recording_id"] == 1
        assert r1["status"] == "completed"
        assert isinstance(r1["step_timings"], dict) and r1["step_timings"]
        assert "started_at" in r1 and r1["started_at"]
        assert "finished_at" in r1 and r1["finished_at"]
        assert isinstance(r1["duration_s"], float)
        assert r1["artifacts"][0]["kind"] == "plot"
        assert r1["artifacts"][0]["path"]

        # detections carry their adjudications
        adjudicated = [d for d in r1["detections"] if d.get("adjudication") is not None]
        assert len(adjudicated) == 1
        assert adjudicated[0]["adjudication"]["verdict"] == "interesting"
        assert "note" in adjudicated[0]["adjudication"]

        # run 1 has a surrogate control; the surrogate counts are stated
        assert r1["surrogate"] is not None
        assert r1["surrogate"]["run_id"] == surrogate_run
        assert r1["surrogate"]["detection_count"] == 1

        r2 = run_by_id[run2]
        assert r2["surrogate"] is None
    finally:
        conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def _map_manifest_runs(conn, group_id, data):
    """Map manifest run blocks back to run ids via the group's run order
    (`Working.manifest.build_manifest` iterates run_ids in the same order,
    so the Nth manifest block is the Nth run of the group)."""
    run_rows = R.list_run_group_runs(conn, group_id)
    return {run_rows[i]["id"]: run_data
            for i, run_data in enumerate(data["runs"])}


# ── null surrogate is explicit ───────────────────────────────────────────────

def test_export_states_null_surrogate_explicitly_for_unpaired_run():
    """AC: a null surrogate is stated explicitly rather than omitted — a
    missing control is visible in the export. The field is present and null
    for an unpaired run."""
    conn, db_path, tmpdir, group_id, run1, run2, _ = _setup_run_group(
        with_surrogate=False,
    )
    try:
        _result, data, _out_dir = _export(conn, group_id, tmpdir)
        assert len(data["runs"]) == 2
        for run_data in data["runs"]:
            assert "surrogate" in run_data, \
                "surrogate key must be present even when there is no control"
            assert run_data["surrogate"] is None
    finally:
        conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── spans CSV ────────────────────────────────────────────────────────────────

def test_export_spans_csv_one_row_per_span_with_named_columns():
    """AC: the CSV opens in a spreadsheet with one row per span and named
    columns — thesis tables come out of a spreadsheet, not a JSON blob."""
    conn, db_path, tmpdir, group_id, run1, run2, _ = _setup_run_group()
    try:
        _result, _data, out_dir = _export(conn, group_id, tmpdir)
        csv_path = os.path.join(out_dir, "spans.csv")
        assert os.path.isfile(csv_path)

        with open(csv_path, newline="") as f:
            rows = list(csv.reader(f))

        header = rows[0]
        for col in ("run_id", "start_idx", "end_idx", "score", "verdict",
                    "surrogate_run_id"):
            assert col in header, f"spans.csv missing column {col!r}; got {header}"

        # run 1 has two detections, run 2 has one -> three span rows
        assert len(rows) - 1 == 3, f"expected one row per span, got {len(rows) - 1}"
    finally:
        conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_export_spans_csv_records_adjudication_and_surrogate_columns():
    """The spreadsheet carries the human verdict and the surrogate pointer per
    span, so a thesis table can show detected-versus-surrogate counts."""
    conn, db_path, tmpdir, group_id, run1, run2, _ = _setup_run_group()
    try:
        _result, _data, out_dir = _export(conn, group_id, tmpdir)
        with open(os.path.join(out_dir, "spans.csv"), newline="") as f:
            rows = list(csv.DictReader(f))

        # run 1's first detection (10-20) is adjudicated 'interesting'
        row = next(r for r in rows if r["run_id"] == str(run1) and r["start_idx"] == "10")
        assert row["verdict"] == "interesting"
        assert row["surrogate_run_id"] == str(
            _surrogate_run_id(conn, group_id)
        )

        # run 2's span has no surrogate and no adjudication -> blank cells
        row2 = next(r for r in rows if r["run_id"] == str(run2))
        assert row2["verdict"] == ""
        assert row2["surrogate_run_id"] == ""
    finally:
        conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def _surrogate_run_id(conn, group_id):
    run_id = R.list_run_group_runs(conn, group_id)[0]["id"]
    row = conn.execute(
        "SELECT id FROM runs WHERE surrogate_of_run_id = ?", (run_id,)
    ).fetchone()
    return row["id"]


# ── UI export action ─────────────────────────────────────────────────────────

def test_run_group_exporter_surface_constructs():
    """The export action is a Panel surface; a broken dynamic map here would
    render as a silently blank pane, so it must construct with the expected
    non-None panes."""
    import panel as pn
    pn.extension()
    from UI.workspaces.analyse.export import RunGroupExporter

    conn, db_path, tmpdir, group_id, run1, run2, _ = _setup_run_group()
    try:
        surface = RunGroupExporter(_FakeApp(conn))
        layout = surface.layout()
        assert layout is not None
        assert surface.run_group is not None
        assert surface.out_dir is not None
        assert surface.export_button is not None
        assert surface.status is not None
        assert any(isinstance(o, pn.widgets.Select) for o in layout.objects)
        assert any(isinstance(o, pn.widgets.Button) and "Export" in o.name
                   for o in layout.objects)
        # the run group we set up is offered as an option
        assert group_id in surface.run_group.options.values()
    finally:
        conn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


class _FakeApp:
    """The minimal shape the export surface needs off `app` — a live db
    connection."""

    def __init__(self, conn):
        self.conn = conn


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
