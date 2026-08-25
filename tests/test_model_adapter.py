"""
test_model_adapter.py
======================
Ticket 12 — new adapter: classifier training to a `Model`.

The block is the last segment of RQ1's chain. The PRD names that chain
explicitly — "the typed chain from signal through window set and grouping
to a model" (`docs/PIPELINE_PRD.md`, the research-question table) — and
`tests/test_chain_validation.py::test_cnn_chain_validates_end_to_end`
already pins the same shape against the validator. So the classifier's
primary input is the `Grouping` (the labels), and the `WindowSet` carrying
the feature matrix those labels were assigned over arrives as a side input
bound to the earlier window-matrix step.

The ticket's AC1 states the two the other way round. It cannot be met as
written: `Working/chain_validation.py` types a chain as a linear spine, so
a step whose primary input is a `WindowSet` can never follow a step that
produces a `Grouping`, and AC5's `window_matrix -> cluster -> classifier`
would not validate under any ordering. AC5, the PRD and the shipped
validator agree with each other, so AC1's ordering is the odd one out and
these tests encode the other three.

What AC2 actually asks for survives that correction intact: RQ1 is only a
comparison if cluster-derived and manually derived labels are trained by
the *same* block. `run` never asks where its `Grouping` came from, so
swapping the upstream step changes the labels and nothing else — that is
what `test_the_same_block_trains_from_cluster_and_manual_labels` pins.

Run from the project root:
    python -m pytest tests/test_model_adapter.py -q
"""

import json
import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Adapters.registry import discover_adapters, get_adapter
from Working.chain_validation import validate_chain
from Working.types import Grouping, Model, WindowSet

discover_adapters()

CLASSIFIER_NAME = "catalogue.classifier"
CLUSTER_NAME = "catalogue.cluster"
WINDOW_MATRIX_NAME = "preprocessing.window_matrix"


# ── fixtures ────────────────────────────────────────────────────────────────

def _synthetic_window_set(n_per_group=12, seed=0):
    """Two separable Gaussian blobs as a `WindowSet` with an attached
    two-feature matrix, plus the group id each window truly belongs to.

    The separation (6 units) dwarfs the spread (0.2), so a classifier that
    has learned anything at all must recover the membership — the same
    "assert by membership, not by score" shape `test_grouping_adapter.py`
    uses for the clustering block.
    """
    rng = np.random.RandomState(seed)
    centers = [np.array([0.0, 0.0]), np.array([6.0, 0.0])]
    rows, group_ids = [], []
    for group_id, center in enumerate(centers):
        rows.append(center + rng.normal(0.0, 0.2, size=(n_per_group, 2)))
        group_ids.extend([group_id] * n_per_group)

    features = pd.DataFrame(np.vstack(rows), columns=["x", "y"])
    window_set = WindowSet(
        starts=np.arange(len(features)), length=128, fs=1.0, features=features,
    )
    return window_set, np.array(group_ids)


def _synthetic_signal(n_windows=24, window_samples=60, seed=0):
    """A signal in two regimes — quiet, then an order of magnitude noisier —
    long enough for the real window-matrix block to build `n_windows`
    one-minute windows at fs=1.0."""
    rng = np.random.default_rng(seed)
    n = n_windows * window_samples
    x = np.concatenate([
        rng.normal(0.0, 0.1, n // 2),
        rng.normal(0.0, 1.0, n - n // 2),
    ])
    return x, np.arange(n) / 1.0, 1.0


def _train(spec, window_set, grouping, **overrides):
    params = spec.validate_params(overrides)
    return spec.run(
        np.zeros(3), np.arange(3), 1.0,
        value=grouping, windows=window_set, **params,
    )


# ── AC1: the declared contract ──────────────────────────────────────────────

def test_classifier_declares_grouping_to_model():
    spec = get_adapter(CLASSIFIER_NAME)
    assert spec.input_kind == "grouping"
    assert spec.output_kind == "model"


def test_classifier_declares_one_windowset_side_input_bound_to_an_earlier_step():
    spec = get_adapter(CLASSIFIER_NAME)
    assert len(spec.side_inputs) == 1

    side = spec.side_inputs[0]
    assert side.type_kind == "windowset"
    assert "earlier_step" in side.sources


# ── AC2: one block, two label sources, no branch ────────────────────────────

def test_the_same_block_trains_from_cluster_and_manual_labels():
    """RQ1's comparison only exists if both label sources go through one
    block. The cluster-derived `Grouping` comes from the real clustering
    adapter; the manual one is hand-built the way an adjudicated set of
    human verdicts would arrive. Same `run`, same keyword, two models."""
    spec = get_adapter(CLASSIFIER_NAME)
    window_set, group_ids = _synthetic_window_set()

    cluster = get_adapter(CLUSTER_NAME)
    cluster_params = cluster.validate_params({"linkage": "ward", "k": 2})
    cluster_derived = cluster.run(
        np.zeros(3), np.arange(3), 1.0, value=window_set, **cluster_params,
    ).value

    manual = Grouping(labels=group_ids)

    from_cluster = _train(spec, window_set, cluster_derived)
    from_manual = _train(spec, window_set, manual)

    for result in (from_cluster, from_manual):
        assert result.output_kind == "model"
        assert isinstance(result.value, Model)
        assert os.path.isfile(result.value.path)

    # The two are trained from genuinely different label vectors, so they
    # must not collapse onto one cached artefact.
    assert not np.array_equal(cluster_derived.labels, manual.labels)
    assert from_cluster.value.path != from_manual.value.path


def test_no_parameter_selects_where_the_labels_came_from():
    """The label source is a binding, not a setting. A param that named it
    would be the branch AC2 forbids, wearing a different hat."""
    spec = get_adapter(CLASSIFIER_NAME)
    names = {p.name for p in spec.params}
    assert not (names & {"label_source", "labels_from", "source", "manual", "mode"})


def test_the_classifier_recovers_the_labels_it_was_trained_on():
    """A model that cannot separate two blobs six standard deviations apart
    has not been fitted, and every other assertion here would pass anyway.

    Also pins the loading contract: the file is a bare fitted pipeline (so
    the window matrix's own `rf` stage can consume one), and `meta` carries
    the column names it expects — feature preprocessing may have dropped
    some, and a `Model` is a path with nowhere to record which.
    """
    import joblib

    spec = get_adapter(CLASSIFIER_NAME)
    window_set, group_ids = _synthetic_window_set()

    result = _train(spec, window_set, Grouping(labels=group_ids), holdout_frac=0.0)
    pipeline = joblib.load(result.value.path)

    columns = result.meta["feature_names"]
    assert set(columns) <= set(window_set.features.columns)

    predicted = pipeline.predict(window_set.features[columns].to_numpy())
    assert np.array_equal(predicted, group_ids)


# ── AC3: the Model serialises by path reference ─────────────────────────────

def test_model_serialises_by_path_reference_not_by_embedding_the_classifier(tmp_path):
    spec = get_adapter(CLASSIFIER_NAME)
    window_set, group_ids = _synthetic_window_set()

    model = _train(spec, window_set, Grouping(labels=group_ids)).value

    manifest_path = model.to_path(str(tmp_path))
    with open(manifest_path) as f:
        payload = json.load(f)

    # A reference and nothing else — the fitted estimator stays on disk
    # where joblib put it (CLAUDE.md: bulk arrays never enter the database).
    assert payload == {"path": model.path}
    assert os.path.getsize(manifest_path) < 4096
    assert Model.from_path(str(tmp_path)) == model


# ── AC4: the estimate callable ──────────────────────────────────────────────

def test_classifier_declares_an_estimate_callable():
    spec = get_adapter(CLASSIFIER_NAME)
    assert spec.estimate is not None
    assert callable(spec.estimate)


def test_a_training_step_routes_as_unknown_rather_than_as_free():
    """The consequence the callable exists for. `route_recipe` skips a step
    whose `estimate` is None entirely — training would then be costed at
    zero and routed local. Declaring an estimator that answers "not
    calibrated" is what makes the router say so out loud."""
    from Working.hpc.job_export import route_recipe
    from Working.recipes import make_recipe

    recipe = make_recipe(1, [
        {"stage": "preprocessing", "algorithm": "window_matrix",
         "params": {"window_min": 1.0, "slow_entropy": False}},
        {"stage": "catalogue", "algorithm": "cluster", "params": {"k": 2}},
        {"stage": "catalogue", "algorithm": "classifier",
         "side_inputs": {"windows": {"source_kind": "earlier_step", "step_index": 0}}},
    ])

    assert route_recipe(recipe, n_samples=1440, fs=1.0) == "unknown"


# ── AC5: the chain validates and runs end to end ────────────────────────────

def test_window_matrix_cluster_classifier_chain_validates():
    specs = [
        get_adapter(WINDOW_MATRIX_NAME),
        get_adapter(CLUSTER_NAME),
        get_adapter(CLASSIFIER_NAME),
    ]
    ok, reason = validate_chain(specs)
    assert ok is True, reason
    assert reason == ""


def test_the_chain_runs_end_to_end_on_a_synthetic_signal():
    """signal -> window set -> grouping -> model, every step the real
    registered adapter, threading each step's typed output into the next
    exactly as `execute_recipe` does."""
    x, t, fs = _synthetic_signal()

    window_set = get_adapter(WINDOW_MATRIX_NAME).run(
        x, t, fs, window_min=1.0, step_frac=1.0,
        catch22=True, fast_entropy=True, slow_entropy=False,
    ).value
    assert window_set.n_windows >= 3
    assert window_set.features is not None

    cluster = get_adapter(CLUSTER_NAME)
    grouping = cluster.run(
        x, t, fs, value=window_set, **cluster.validate_params({"k": 2}),
    ).value
    assert len(grouping.labels) == window_set.n_windows

    result = _train(get_adapter(CLASSIFIER_NAME), window_set, grouping)

    assert result.output_kind == "model"
    assert os.path.isfile(result.value.path)
    assert result.meta["n_windows"] == window_set.n_windows
    assert result.meta["n_classes"] == len(np.unique(grouping.labels))


# ── refusals that name what is missing ──────────────────────────────────────

def test_a_missing_window_set_side_input_names_the_side_input():
    spec = get_adapter(CLASSIFIER_NAME)
    _, group_ids = _synthetic_window_set()
    try:
        spec.run(np.zeros(3), np.arange(3), 1.0,
                 value=Grouping(labels=group_ids), windows=None)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "windows" in str(e)


def test_labels_that_do_not_match_the_window_count_are_refused():
    spec = get_adapter(CLASSIFIER_NAME)
    window_set, group_ids = _synthetic_window_set()
    try:
        _train(spec, window_set, Grouping(labels=group_ids[:-1]))
        assert False, "expected ValueError"
    except ValueError as e:
        message = str(e)
        assert str(len(group_ids) - 1) in message
        assert str(window_set.n_windows) in message


def test_a_single_class_grouping_is_refused():
    """One label over every window is not a classification problem, and
    sklearn's own failure for it names neither the block nor the reason."""
    spec = get_adapter(CLASSIFIER_NAME)
    window_set, _ = _synthetic_window_set()
    try:
        _train(spec, window_set, Grouping(labels=np.zeros(window_set.n_windows, dtype=int)))
        assert False, "expected ValueError"
    except ValueError as e:
        assert "one class" in str(e).lower()


# ── the adapter stays cheap to register ─────────────────────────────────────

def test_registering_the_adapter_does_not_import_torch():
    """`Working/Catalogue/cnn/apply_cnn.py` imports torch at module scope.
    Every `discover_adapters()` call in the suite pays for whatever this
    module imports, so the classifier must reach its dependencies lazily —
    the same discipline `catalogue_cluster.py` keeps against matplotlib.
    """
    import subprocess

    probe = (
        "import sys; "
        "import Adapters.catalogue_classifier; "
        "assert 'torch' not in sys.modules, 'adapter import dragged in torch'; "
        "print('ok')"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], cwd=PROJECT_ROOT,
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
