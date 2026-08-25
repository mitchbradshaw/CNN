"""
test_end_to_end.py
====================
Ticket 48 — end-to-end test and repository cleanup.

One test walks a synthetic signal through the whole Pipeline GUI claim: a
three-step chain runs, a detection is adjudicated, the candidate is promoted
into the shape library, and the run group is exported — and the exported
manifest's recipe hash equals the run's recipe hash. A second test pins
`discover_adapters()` to the expected count so no adapter is silently skipped
by a broken optional dependency.
"""

import json
import os

import numpy as np

from Adapters.registry import discover_adapters
from Working.database import queries as q
from Working.database import runs as R
from Working.database.adjudications import insert_adjudication
from Working.database.schema import init_db
from Working.execution import execute_recipe
from Working.recipes import make_recipe


def _fresh_db_with_synthetic_signal(tmp_path):
    """Create a temp DB with one synthetic 200-sample recording."""
    npy_path = tmp_path / "CH0.npy"
    np.save(npy_path, np.random.default_rng(0).standard_normal(200))
    db_path = tmp_path / "test.sqlite"
    conn = init_db(str(db_path))
    rec_id = q.insert_recording(
        conn, "synthetic.mat", 0, 1.0, 200, 0, str(npy_path)
    )
    conn.close()
    return str(db_path), rec_id


def _three_step_chain(recording_id):
    """A three-step chain that ends in a spanset (detections)."""
    return make_recipe(recording_id, [
        {"stage": "preprocessing", "algorithm": "lowpass",
         "params": {"cutoff_hz": 0.05}},
        {"stage": "preprocessing", "algorithm": "detrend", "params": {}},
        {"stage": "detection", "algorithm": "spike_v1", "params": {}},
    ], span=(0, 200))


def test_discover_adapters_registers_the_expected_count():
    """No adapter is silently skipped by a broken optional dependency.

    The wavelet-scattering adapter imports its heavy dependency lazily, so it
    registers even when kymatio is broken against the installed scipy. If any
    adapter module fails to import, this count drops and the test fails.
    """
    specs = discover_adapters()
    assert len(specs) == 20, (
        f"expected 20 registered adapters, got {len(specs)}"
    )


def test_synthetic_signal_flows_to_exported_run_group(tmp_path):
    """A synthetic signal -> three-step chain -> adjudicated detection ->
    library promotion -> exported run group, in one test."""
    db_path, rec_id = _fresh_db_with_synthetic_signal(tmp_path)
    recipe = _three_step_chain(rec_id)

    out = execute_recipe(recipe, db_path=db_path)
    assert out["detections_written"] >= 1

    conn = init_db(db_path)
    dets = R.list_detections(conn, out["run_id"])
    assert len(dets) >= 1

    # Adjudicate the first detection as a seed.
    det = dets[0]
    insert_adjudication(conn, det["id"], "seed", note="e2e")

    # Promote the adjudicated candidate into the shape library.
    entry_id = R.insert_motif_entry(
        conn, rec_id, det["start_idx"], det["end_idx"], detection_id=det["id"]
    )
    assert entry_id is not None
    entries = R.list_motif_entries(conn)
    assert any(e["id"] == entry_id for e in entries)

    # Export the run group.
    group_id = R.create_run_group(conn)
    R.update_run(conn, out["run_id"], run_group_id=group_id)
    conn.close()

    from Working import export

    out_dir = tmp_path / "export"
    result = export.export_run_group(init_db(db_path), group_id, str(out_dir))
    assert os.path.isfile(result["manifest_path"])
    assert result["run_ids"] == [out["run_id"]]

    # The exported manifest's recipe hash equals the run's recipe hash.
    with open(result["manifest_path"], encoding="utf-8") as f:
        data = json.load(f)
    assert data["manifest_version"] == 1
    run_block = data["runs"][0]
    assert run_block["config_hash"] == out["config_hash"]
    assert run_block["recipe"]["recording_id"] == rec_id
    assert len(run_block["recipe"]["steps"]) == 3
    assert len(run_block["detections"]) == out["detections_written"]
