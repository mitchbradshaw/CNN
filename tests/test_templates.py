"""
test_templates.py
===================
Ticket 47 — templates: save, apply, carry and rebind. A template is a
chain's steps with recording and span stripped; each side-input binding
declares whether it is *carried* (the exemplar travels with the template)
or *rebound* (prompted for on apply). Applying a template produces an
ordinary recipe that validates and runs.

Run from the project root:
    python tests/test_templates.py
"""

import inspect
import os
import shutil
import sys
import tempfile

import numpy as np
import pytest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Adapters.base import AdapterResult, AdapterSpec, SideInputSpec
from Adapters.registry import get_adapter, register
from Working import templates as T
from Working.database import queries as q
from Working.database import runs as R
from Working.database.schema import init_db
from Working.execution import execute_recipe
from Working.recipes import make_recipe
from Working.types import SpanSet


def _register_probe():
    """Register the exemplar-consuming probe adapter once per process."""
    name = "detection.template_probe"
    try:
        get_adapter(name)
    except KeyError:
        register(AdapterSpec(
            name=name,
            display_name="Template probe",
            stage="detection",
            params=[],
            run=lambda x, t, fs, exemplar=None: AdapterResult(
                output_kind="spanset",
                value=SpanSet(starts=(0,), ends=(1,),
                              scores=(float(exemplar.x[0]),)),
            ),
            output_kind="spanset",
            side_inputs=[SideInputSpec(
                name="exemplar", type_kind="signal",
                sources=["library_exemplar"],
            )],
        ))
    return name


def _make_db(exemplar_first=False):
    """A fresh temp db with three synthetic recordings (root, exemplar and
    target), backed by real .npy files so `execute_recipe` can run.

    `exemplar_first=True` changes insertion order, which changes local row
    ids — the point of the portability test: the template carries content,
    not ids.
    """
    tmpdir = tempfile.mkdtemp(prefix="t47_test_")
    db_path = os.path.join(tmpdir, "test.sqlite")
    conn = init_db(db_path)

    def add(key, source_file, data):
        npy_path = os.path.join(tmpdir, f"{key}.npy")
        np.save(npy_path, data)
        q.insert_recording(conn, source_file, 0, 1.0, len(data), 0, npy_path)
        return q.get_recording(conn, source_file, 0)["id"]

    root_data = np.zeros(300, dtype=float)
    exemplar_data = np.arange(300, dtype=float)
    target_data = np.full(300, 5.0, dtype=float)

    if exemplar_first:
        ids = {
            "exemplar": add("exemplar", "ex.mat", exemplar_data),
            "root": add("root", "root.mat", root_data),
            "target": add("target", "target.mat", target_data),
        }
    else:
        ids = {
            "root": add("root", "root.mat", root_data),
            "exemplar": add("exemplar", "ex.mat", exemplar_data),
            "target": add("target", "target.mat", target_data),
        }
    conn.close()
    return db_path, tmpdir, ids


def _recipe_with_carried_exemplar(recording_id, entry_id=42):
    return make_recipe(recording_id, [{
        "stage": "detection",
        "algorithm": "template_probe",
        "side_inputs": {"exemplar": {
            "source_kind": "library_exemplar",
            "entry_id": entry_id,
            "source_file": "ex.mat",
            "channel": 0,
            "start_idx": 100,
            "end_idx": 110,
        }},
    }], span=(0, 50))


def _template(recording_id, mode):
    recipe = _recipe_with_carried_exemplar(recording_id)
    return T.template_from_recipe(recipe, "a template", modes={(0, "exemplar"): mode})


# ── saving: recording and span stripped, carry/rebind declared ─────────────

def test_template_stores_steps_with_recording_and_span_stripped():
    _register_probe()
    template = _template(recording_id=1, mode="carry")

    assert "recording_id" not in template
    assert "span" not in template
    assert template["name"] == "a template"

    step = template["steps"][0]
    assert step["stage"] == "detection"
    assert step["algorithm"] == "template_probe"
    assert step["params"] == {}

    binding = step["side_inputs"]["exemplar"]
    assert binding["source_kind"] == "library_exemplar"
    assert binding["mode"] == "carry"
    assert binding["source_file"] == "ex.mat"
    assert binding["channel"] == 0
    assert binding["start_idx"] == 100
    assert binding["end_idx"] == 110
    assert "entry_id" not in binding

    exported = T.template_to_json(template)
    assert "entry_id" not in exported
    assert "recording_id" not in exported
    assert "span" not in exported


def test_template_rebind_binding_carries_no_exemplar_content():
    _register_probe()
    template = _template(recording_id=1, mode="rebind")

    binding = template["steps"][0]["side_inputs"]["exemplar"]
    assert binding == {"source_kind": "library_exemplar", "mode": "rebind"}


def test_template_round_trips_through_the_database():
    db_path, tmpdir, ids = _make_db()
    try:
        _register_probe()
        template = _template(recording_id=ids["root"], mode="carry")

        conn = init_db(db_path)
        try:
            template_id = R.save_template(conn, template["name"], template["steps"])
        finally:
            conn.close()

        conn = init_db(db_path)
        try:
            loaded = R.load_template(conn, template_id)
        finally:
            conn.close()

        assert loaded["name"] == template["name"]
        assert loaded["steps"] == template["steps"]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── applying: ordinary recipe, validates, rebinds prompted ─────────────────

def test_apply_carry_builds_a_valid_recipe_and_resolves_entry_id_by_content():
    db_path, tmpdir, ids = _make_db()
    try:
        _register_probe()
        conn = init_db(db_path)
        try:
            local_entry_id = R.insert_motif_entry(conn, ids["exemplar"], 100, 110)
        finally:
            conn.close()

        template = _template(recording_id=ids["root"], mode="carry")

        conn = init_db(db_path)
        try:
            applied = T.apply_template(conn, template, ids["root"], span=(0, 50))
        finally:
            conn.close()

        assert applied["recording_id"] == ids["root"]
        assert applied["span"] == [0, 50]

        binding = applied["steps"][0]["side_inputs"]["exemplar"]
        assert binding["entry_id"] == local_entry_id
        assert binding["source_file"] == "ex.mat"
        assert binding["channel"] == 0
        assert binding["start_idx"] == 100
        assert binding["end_idx"] == 110
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_apply_rebind_requires_a_binding_and_builds_a_recipe():
    db_path, tmpdir, ids = _make_db()
    try:
        _register_probe()
        template = _template(recording_id=ids["root"], mode="rebind")

        conn = init_db(db_path)
        try:
            with pytest.raises(ValueError, match="exemplar"):
                T.apply_template(conn, template, ids["root"], span=(0, 50))

            applied = T.apply_template(
                conn, template, ids["root"], span=(0, 50),
                rebinds={(0, "exemplar"): {
                    "source_kind": "library_exemplar",
                    "entry_id": 7,
                    "source_file": "ex.mat",
                    "channel": 0,
                    "start_idx": 100,
                    "end_idx": 110,
                }},
            )
        finally:
            conn.close()

        binding = applied["steps"][0]["side_inputs"]["exemplar"]
        assert binding["entry_id"] == 7
        assert binding["source_file"] == "ex.mat"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── export/import across different local ids ───────────────────────────────

def test_template_exports_and_imports_resolving_carried_exemplar_by_content():
    db_a, tmp_a, ids_a = _make_db()
    db_b, tmp_b, ids_b = _make_db(exemplar_first=True)
    try:
        _register_probe()

        # DB A: the carried exemplar's local entry id is made different from
        # DB B's by inserting a dummy entry first.
        conn = init_db(db_a)
        try:
            R.insert_motif_entry(conn, ids_a["exemplar"], 0, 10)
            entry_a = R.insert_motif_entry(conn, ids_a["exemplar"], 100, 110)
        finally:
            conn.close()

        template = _template(recording_id=ids_a["root"], mode="carry")
        exported = T.template_to_json(template)

        # DB B: same content, different local row ids.
        conn = init_db(db_b)
        try:
            entry_b = R.insert_motif_entry(conn, ids_b["exemplar"], 100, 110)
        finally:
            conn.close()

        imported = T.template_from_json(exported)
        conn = init_db(db_b)
        try:
            applied = T.apply_template(conn, imported, ids_b["root"], span=(0, 50))
        finally:
            conn.close()

        assert ids_a["root"] != ids_b["root"]
        assert ids_a["exemplar"] != ids_b["exemplar"]
        assert entry_a != entry_b

        binding = applied["steps"][0]["side_inputs"]["exemplar"]
        assert binding["entry_id"] == entry_b
        assert binding["source_file"] == "ex.mat"
        assert binding["start_idx"] == 100
        assert binding["end_idx"] == 110
    finally:
        shutil.rmtree(tmp_a, ignore_errors=True)
        shutil.rmtree(tmp_b, ignore_errors=True)


# ── end-to-end: applying to a recording the template has never seen ────────

def test_applying_template_to_an_unseen_recording_produces_a_run():
    db_path, tmpdir, ids = _make_db()
    try:
        _register_probe()

        conn = init_db(db_path)
        try:
            R.insert_motif_entry(conn, ids["exemplar"], 100, 110)
        finally:
            conn.close()

        template = _template(recording_id=ids["root"], mode="carry")

        conn = init_db(db_path)
        try:
            applied = T.apply_template(conn, template, ids["target"], span=(0, 50))
        finally:
            conn.close()

        out = execute_recipe(applied, db_path=db_path)

        conn = init_db(db_path)
        try:
            run = R.get_run(conn, out["run_id"])
            detections = R.list_detections(conn, out["run_id"])
        finally:
            conn.close()

        assert run["recording_id"] == ids["target"]
        assert run["status"] == "completed"
        assert len(detections) == 1
        assert detections[0]["score"] == 100.0  # ex.mat[100] == 100.0
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
