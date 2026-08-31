"""
test_step_cache.py
====================
Ticket 15 — step cache in the executor. `Working.execution.execute_recipe`
must reuse the expensive prefix of a chain when only a downstream step's
parameters change, and must key each cached artifact on the recipe prefix
up to that step so a changed step (or side-input binding) invalidates that
step and everything after it.

The assertions below are deliberately about artifact identity on disk, not
timing: a cache that recomputed the expensive prefix and merely happened to
run quickly would still pass a timing test, but it cannot fake the same
`step_artifacts.path`.

Run from the project root:
    python tests/test_step_cache.py
"""

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

from Adapters.base import AdapterResult, AdapterSpec, ParamSpec, SideInputSpec
from Adapters.registry import get_adapter, register
from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import runs as R
from Working.execution import execute_recipe, invalidated_step_indices
from Working.recipes import make_recipe, recipe_hash
from Working.types import Scores

import Working.config as config


def _prefix_hash(recipe, step_index):
    """The cache key under test: the recipe prefix through `step_index`."""
    prefix = dict(recipe)
    prefix["steps"] = recipe["steps"][:step_index + 1]
    return recipe_hash(prefix)


def _fresh_db_with_synthetic_recording(n_samples, fs=1.0):
    """One synthetic channel + fresh db, for `execute_recipe` runs that
    don't need the real channel data."""
    tmpdir = tempfile.mkdtemp(prefix="t15_test_")
    npy_path = os.path.join(tmpdir, "CH0.npy")
    np.save(npy_path, np.random.default_rng(0).standard_normal(n_samples))
    db_path = os.path.join(tmpdir, "test.sqlite")
    conn = init_db(db_path)
    q.insert_recording(conn, "fake.mat", 0, fs, n_samples, 0, npy_path)
    conn.close()
    return db_path, tmpdir


def _fresh_db_with_two_recordings(root_n=200, exemplar_n=1000):
    """A root recording plus a separate `exemplar.mat` for library-exemplar
    bindings. Returns (db_path, tmpdir)."""
    tmpdir = tempfile.mkdtemp(prefix="t15_exemplar_")
    root_npy = os.path.join(tmpdir, "root.npy")
    np.save(root_npy, np.zeros(root_n, dtype=float))
    exemplar_npy = os.path.join(tmpdir, "exemplar.npy")
    np.save(exemplar_npy, np.arange(exemplar_n, dtype=float))

    db_path = os.path.join(tmpdir, "test.sqlite")
    conn = init_db(db_path)
    q.insert_recording(conn, "root.mat", 0, 1.0, root_n, 0, root_npy)
    q.insert_recording(conn, "exemplar.mat", 0, 1.0, exemplar_n, 0, exemplar_npy)
    conn.close()
    return db_path, tmpdir


@pytest.fixture
def step_cache_on(tmp_path):
    """Redirect the step cache into tmp_path and cache every step, so the
    cache's write decision is not what the test is about."""
    old_threshold = getattr(config, "STEP_CACHE_WRITE_THRESHOLD_S", None)
    old_root = getattr(config, "STEP_CACHE_ROOT", None)
    config.STEP_CACHE_WRITE_THRESHOLD_S = 0.0
    config.STEP_CACHE_ROOT = str(tmp_path / "step_cache")
    yield tmp_path / "step_cache"
    if old_threshold is None:
        delattr(config, "STEP_CACHE_WRITE_THRESHOLD_S")
    else:
        config.STEP_CACHE_WRITE_THRESHOLD_S = old_threshold
    if old_root is None:
        delattr(config, "STEP_CACHE_ROOT")
    else:
        config.STEP_CACHE_ROOT = old_root


@pytest.fixture
def step_cache_off(tmp_path):
    """Raise the write threshold so nothing is cached."""
    old_threshold = getattr(config, "STEP_CACHE_WRITE_THRESHOLD_S", None)
    old_root = getattr(config, "STEP_CACHE_ROOT", None)
    config.STEP_CACHE_WRITE_THRESHOLD_S = float("inf")
    config.STEP_CACHE_ROOT = str(tmp_path / "step_cache")
    yield tmp_path / "step_cache"
    if old_threshold is None:
        delattr(config, "STEP_CACHE_WRITE_THRESHOLD_S")
    else:
        config.STEP_CACHE_WRITE_THRESHOLD_S = old_threshold
    if old_root is None:
        delattr(config, "STEP_CACHE_ROOT")
    else:
        config.STEP_CACHE_ROOT = old_root


def _step_paths(conn):
    rows = conn.execute(
        "SELECT recipe_prefix_hash, step_index, path FROM step_artifacts ORDER BY step_index"
    ).fetchall()
    return {(r["recipe_prefix_hash"], r["step_index"]): r["path"] for r in rows}


# ── the test that matters ────────────────────────────────────────────────────

def test_changing_downstream_params_reuses_upstream_step_artifacts(step_cache_on):
    import Adapters.detection_matrix_profile as mp_adapter

    db_path, tmpdir = _fresh_db_with_synthetic_recording(200)
    prior_results_dir = mp_adapter.RESULTS_DIR
    mp_adapter.RESULTS_DIR = os.path.join(tmpdir, "results")
    try:
        first = make_recipe(1, [
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": 0.1, "backend": "stump"}},
            {"stage": "detection", "algorithm": "threshold",
             "params": {"threshold": -1.0}},
        ], span=(0, 200))
        execute_recipe(first, db_path=db_path)

        conn = init_db(db_path)
        first_paths = _step_paths(conn)
        conn.close()
        assert len(first_paths) == 2
        step0_hash = _prefix_hash(first, 0)
        step0_path = first_paths[(step0_hash, 0)]
        assert os.path.isdir(step0_path)
        # Round-trips through the type serialiser, not a bespoke format.
        assert os.path.isfile(os.path.join(step0_path, "scores.npz"))

        changed = make_recipe(1, [
            {"stage": "detection", "algorithm": "matrix_profile",
             "params": {"window_min": 0.1, "backend": "stump"}},
            {"stage": "detection", "algorithm": "threshold",
             "params": {"threshold": -0.5}},
        ], span=(0, 200))
        execute_recipe(changed, db_path=db_path)

        conn = init_db(db_path)
        second_paths = _step_paths(conn)
        conn.close()

        # Step 0's prefix is identical, so its artifact must be the same file.
        assert second_paths[(step0_hash, 0)] == step0_path
        # Step 1's prefix changed, so it gets a distinct artifact.
        step1_first = first_paths[(_prefix_hash(first, 1), 1)]
        step1_changed = second_paths[(_prefix_hash(changed, 1), 1)]
        assert step1_changed != step1_first
    finally:
        mp_adapter.RESULTS_DIR = prior_results_dir
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_step_artifacts_are_not_written_below_threshold(step_cache_off):
    db_path, tmpdir = _fresh_db_with_synthetic_recording(200)
    try:
        recipe = make_recipe(1, [
            {"stage": "preprocessing", "algorithm": "lowpass",
             "params": {"cutoff_hz": 0.05}},
        ], span=(0, 200))
        execute_recipe(recipe, db_path=db_path)

        conn = init_db(db_path)
        assert len(_step_paths(conn)) == 0
        conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── side-input bindings invalidate the step and everything after it ─────────

def _register_scores_probe():
    name = "detection.t15_scores_probe"
    try:
        get_adapter(name)
    except KeyError:
        register(AdapterSpec(
            name=name,
            display_name="T15 scores probe",
            stage="detection",
            params=[ParamSpec("bias", float, 0.0, "added to the exemplar value")],
            run=lambda x, t, fs, exemplar=None, bias=0.0: AdapterResult(
                output_kind="scores",
                value=Scores(
                    values=np.full(len(x), float(exemplar.x[0]) + bias, dtype=float),
                    fs=fs,
                ),
            ),
            output_kind="scores",
            side_inputs=[SideInputSpec(name="exemplar", type_kind="signal",
                                       sources=["library_exemplar"])],
        ))
    return name


def test_changing_side_input_binding_invalidates_step_and_downstream(step_cache_on):
    _register_scores_probe()
    db_path, tmpdir = _fresh_db_with_two_recordings(root_n=200, exemplar_n=1000)
    try:
        def recipe_for(start_idx):
            return make_recipe(1, [
                {"stage": "detection", "algorithm": "t15_scores_probe",
                 "params": {"bias": 0.0},
                 "side_inputs": {"exemplar": {
                     "source_kind": "library_exemplar", "entry_id": 1,
                     "source_file": "exemplar.mat", "channel": 0,
                     "start_idx": start_idx, "end_idx": start_idx + 10,
                 }}},
                {"stage": "detection", "algorithm": "threshold",
                 "params": {"threshold": 0.0}},
            ], span=(0, 200))

        first = recipe_for(0)
        execute_recipe(first, db_path=db_path)
        conn = init_db(db_path)
        first_paths = _step_paths(conn)
        conn.close()

        changed = recipe_for(10)
        execute_recipe(changed, db_path=db_path)
        conn = init_db(db_path)
        second_paths = _step_paths(conn)
        conn.close()

        assert len(first_paths) == 2
        # Both the bound step and its downstream step change their prefix
        # hash, so both must be recomputed under distinct artifact paths.
        assert second_paths[(_prefix_hash(changed, 0), 0)] != first_paths[(_prefix_hash(first, 0), 0)]
        assert second_paths[(_prefix_hash(changed, 1), 1)] != first_paths[(_prefix_hash(first, 1), 1)]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── suffix recomputation from a changed step (ticket 63) ────────────────────

def _suffix_recipe(n_steps):
    """A valid n-step lowpass chain — signal->signal throughout, so it
    validates — for exercising `invalidated_step_indices` without needing a
    real recording."""
    return make_recipe(1, [
        {"stage": "preprocessing", "algorithm": "lowpass",
         "params": {"cutoff_hz": 0.05 * (i + 1)}}
        for i in range(n_steps)
    ], span=(0, 200))


def test_invalidated_step_indices_returns_changed_step_and_suffix():
    recipe = _suffix_recipe(4)
    assert invalidated_step_indices(recipe, 1) == {1, 2, 3}


def test_invalidated_step_indices_never_returns_prefix():
    recipe = _suffix_recipe(4)
    for changed in range(len(recipe["steps"])):
        indices = invalidated_step_indices(recipe, changed)
        assert indices, "a change must invalidate at least the changed step"
        assert all(i >= changed for i in indices)


def test_invalidated_step_indices_changing_first_step_returns_all():
    recipe = _suffix_recipe(4)
    assert invalidated_step_indices(recipe, 0) == {0, 1, 2, 3}


def test_invalidated_step_indices_changing_last_step_returns_only_itself():
    recipe = _suffix_recipe(4)
    assert invalidated_step_indices(recipe, 3) == {3}


def test_invalidated_step_indices_single_step_recipe_returns_only_step_zero():
    recipe = _suffix_recipe(1)
    assert invalidated_step_indices(recipe, 0) == {0}


def test_invalidated_step_indices_raises_for_index_outside_recipe():
    recipe = _suffix_recipe(4)
    with pytest.raises(IndexError):
        invalidated_step_indices(recipe, -1)
    with pytest.raises(IndexError):
        invalidated_step_indices(recipe, 4)
