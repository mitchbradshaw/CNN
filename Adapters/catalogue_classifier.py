"""
catalogue_classifier.py
========================
Adapter for the last segment of RQ1's chain — a `Grouping` (one label per
window) trained into a `Model` (a reference to a fitted classifier on
disk), over the feature matrix carried by the `WindowSet` those labels
were assigned across.

The chain shape
---------------
`signal -> windowset -> grouping -> model`, which is the PRD's own
statement of it ("the typed chain from signal through window set and
grouping to a model") and the shape
`tests/test_chain_validation.py::test_cnn_chain_validates_end_to_end`
already pins against the validator. `Working.chain_validation` types a
chain as a linear spine, so the step before this one determines its
primary input: after `catalogue.cluster` that is a `Grouping`. The
`WindowSet` therefore arrives as a side input bound to the earlier
window-matrix step, not as the primary input.

Why the label source is a binding and not a parameter
-----------------------------------------------------
RQ1 asks whether cluster-derived labels produce a classifier that
generalises better than manually derived ones. That is only a comparison
if both are trained by the same block. `_run` never asks where its
`Grouping` came from and exposes no parameter that could name it, so
swapping `catalogue.cluster` for a manual-label step upstream changes the
labels and nothing else — no branch, and nothing else to hold equal.

What is reused, and what is not
-------------------------------
`Working/Catalogue/aeon_classification/classification.py` is the reference
for the estimator shape (variance pruning into a balanced random forest)
but is deliberately not called: every entry point there either loads
windows from labelled directories or splits-and-reports rather than
returning a fitted estimator, and none accepts an in-memory feature
matrix. `Working/Catalogue/cnn/apply_cnn.py` is inference over a
pre-trained network, not training. Both are left unmodified.

What *is* reused is `preprocess_window_matrix` — the same feature-matrix
preprocessing `Adapters/catalogue_cluster.py` runs before clustering, so
the classifier and the clustering that labelled it see one feature space.
Two blocks that disagreed about which columns are features would make
their comparison meaningless. It also means Catch22 is not recomputed
here: the window-matrix step already computed it, and these features are
its output.

That module imports matplotlib at module scope for its plotting half, and
sklearn is a second-long import of its own, so both are imported inside
the functions that need them rather than at adapter-import time —
registering this adapter must not drag a plotting backend or a fitted-model
stack into every `discover_adapters()` call.
"""

import os

from Adapters.base import AdapterResult, AdapterSpec, ParamSpec, SideInputSpec
from Adapters.registry import register
from Working.recipes import recipe_hash
from Working.types import Model

# Trained models live beside the other derived artefacts, referenced by
# path and never inlined into the database (CLAUDE.md rule 4). Kept here
# rather than in `Working/config.py` for the same reason
# `Working/encoding_cache.py` keeps `ENCODING_ROOT` locally: it is this
# block's storage layout, not a setting anything else needs to agree on.
MODEL_ROOT = os.path.join("DATA", "derived", "models")

# Below this many members, the smallest class cannot be split across a
# train/holdout boundary and still be present on both sides. Two is the
# floor for a stratified split; anything less and the holdout is dropped
# rather than silently producing a fold with a class missing from it.
_MIN_CLASS_MEMBERS_FOR_HOLDOUT = 2


def _feature_matrix(window_set, grouping):
    """The preprocessed feature matrix and its labels, or a `ValueError`
    naming exactly what is missing.

    Every refusal here names both the block and the quantity that is wrong,
    because the alternative is sklearn raising about array shapes the
    researcher never chose directly.
    """
    if grouping is None:
        raise ValueError(
            "catalogue.classifier requires a Grouping input from a prior step "
            "(input_kind='grouping') — the labels to train on."
        )
    if window_set is None:
        raise ValueError(
            "catalogue.classifier requires its 'windows' side input: a WindowSet "
            "bound to the earlier step that built the window matrix. Bind it with "
            "{'windows': {'source_kind': 'earlier_step', 'step_index': <i>}}."
        )

    features = window_set.features
    if features is None or features.shape[0] == 0 or features.shape[1] == 0:
        raise ValueError(
            "catalogue.classifier requires a WindowSet with an attached feature "
            "matrix, one row per window — there is nothing to train on without one."
        )

    labels = grouping.labels
    if len(labels) != window_set.n_windows:
        raise ValueError(
            f"catalogue.classifier: the Grouping has {len(labels)} label(s) but "
            f"the WindowSet has {window_set.n_windows} window(s). The labels must "
            "have been assigned over this exact window set."
        )

    n_classes = len(set(labels.tolist()))
    if n_classes < 2:
        raise ValueError(
            "catalogue.classifier: the Grouping puts every window in one class, "
            "so there is nothing to separate. Cluster into at least two groups, "
            "or adjudicate a second class, before training."
        )

    from Working.Catalogue.dendrogram.dendrogram_cluster import preprocess_window_matrix

    preprocessed = preprocess_window_matrix(features)
    if preprocessed.n_samples_dropped:
        raise ValueError(
            f"catalogue.classifier: feature preprocessing dropped "
            f"{preprocessed.n_samples_dropped} window(s), so the remaining rows no "
            "longer line up with the Grouping's labels."
        )
    return preprocessed, labels, n_classes


def _split(X, labels, holdout_frac, random_state):
    """A stratified train/holdout split, or the whole set twice over when a
    holdout is not asked for or cannot be taken.

    Returns `(X_train, y_train, X_holdout, y_holdout)` with the holdout pair
    `None` when the model is fitted on every window.
    """
    import numpy as np

    if holdout_frac <= 0.0:
        return X, labels, None, None

    _, counts = np.unique(labels, return_counts=True)
    n_holdout = int(round(len(labels) * holdout_frac))
    if counts.min() < _MIN_CLASS_MEMBERS_FOR_HOLDOUT or n_holdout < len(counts):
        return X, labels, None, None

    from sklearn.model_selection import train_test_split

    X_train, X_holdout, y_train, y_holdout = train_test_split(
        X, labels, test_size=holdout_frac,
        random_state=random_state, stratify=labels,
    )
    return X_train, y_train, X_holdout, y_holdout


def _model_path(preprocessed, labels, params):
    """A deterministic, content-addressed path for the fitted model.

    Keyed on the labels, the feature columns and the training parameters —
    everything that changes what gets fitted. Re-running an identical
    training overwrites its own file; training the same windows from a
    different `Grouping` (RQ1's whole point) lands somewhere else, so the
    two models can be compared rather than one silently replacing the other.
    """
    digest = recipe_hash({
        "labels": labels.tolist(),
        "features": list(preprocessed.feature_names),
        "params": params,
    })[:16]
    return os.path.join(MODEL_ROOT, f"catalogue_classifier_{digest}.joblib")


def _run(x, t, fs, n_estimators=300, class_weight="balanced", holdout_frac=0.25,
         random_state=42, value=None, windows=None):
    import joblib
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_selection import VarianceThreshold
    from sklearn.pipeline import make_pipeline

    preprocessed, labels, n_classes = _feature_matrix(windows, value)
    params = {
        "n_estimators": n_estimators,
        "class_weight": class_weight,
        "holdout_frac": holdout_frac,
        "random_state": random_state,
    }

    # Fitted on the cleaned features in their original units, not on
    # `X_scaled`: a forest is invariant to monotone rescaling, and storing
    # the unscaled pipeline means a later `predict` can be handed a raw
    # window-matrix row without having to reproduce this run's scaler.
    X = preprocessed.df_features.to_numpy()
    X_train, y_train, X_holdout, y_holdout = _split(
        X, labels, holdout_frac, random_state,
    )

    pipeline = make_pipeline(
        VarianceThreshold(threshold=1e-6),
        RandomForestClassifier(
            n_estimators=n_estimators,
            class_weight=(None if class_weight == "none" else class_weight),
            random_state=random_state,
            n_jobs=-1,
        ),
    )
    pipeline.fit(X_train, y_train)

    path = _model_path(preprocessed, labels, params)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    joblib.dump(pipeline, path)

    kept = pipeline.named_steps["variancethreshold"].get_support()
    holdout_accuracy = (
        float((pipeline.predict(X_holdout) == y_holdout).mean())
        if X_holdout is not None else None
    )

    return AdapterResult(
        output_kind="model",
        value=Model(path=path),
        meta={
            "n_windows": int(windows.n_windows),
            "n_classes": int(n_classes),
            "class_counts": {
                int(label): int(count)
                for label, count in zip(*np.unique(labels, return_counts=True))
            },
            # The columns the dumped pipeline expects, in the order it
            # expects them. `preprocess_window_matrix` may drop constant,
            # NaN-heavy or collinear columns, so the fitted estimator does
            # NOT accept a raw window-matrix row — and a `Model` is a bare
            # path with nowhere to record that. Whoever loads the file
            # reindexes to these names first.
            "feature_names": list(preprocessed.feature_names),
            "n_features_in": int(X.shape[1]),
            "n_features_kept": int(kept.sum()),
            "n_train": int(len(y_train)),
            "n_holdout": int(len(y_holdout)) if y_holdout is not None else 0,
            "holdout_accuracy": holdout_accuracy,
            **params,
        },
    )


def _derive(x, t, fs, params, value=None, windows=None):
    """Pre-run readout: what the classifier would be asked to separate.

    Like `catalogue.cluster`'s, this block's inputs are typed values rather
    than the root signal, so they arrive as the optional `value` (the
    `Grouping`) and `windows` (the `WindowSet`) keywords. Without them
    there is nothing to describe, so the readout says so instead of
    inventing a number.
    """
    if value is None or windows is None:
        return [("Training set", "run the window-matrix and grouping steps first", "warn")]

    import numpy as np

    labels = value.labels
    if len(labels) != windows.n_windows:
        return [(
            "Training set",
            f"{len(labels)} label(s) over {windows.n_windows} window(s) — mismatched",
            "error",
        )]

    unique, counts = np.unique(labels, return_counts=True)
    if len(unique) < 2:
        return [("Training set", "every window in one class — nothing to separate", "error")]

    sizes = ", ".join(str(int(count)) for count in counts)
    return [
        ("Windows", str(windows.n_windows), ""),
        ("Classes", str(len(unique)), ""),
        ("Class sizes", sizes, "warn" if counts.min() < _MIN_CLASS_MEMBERS_FOR_HOLDOUT else ""),
        ("Features offered", str(windows.features.shape[1]), ""),
    ]


def _estimate(x, t, fs, **params):
    """Predicted runtime in seconds — always `None`, meaning "not
    calibrated on this machine".

    This is not a stub. A forest fit is linear in the number of training
    windows, and that count is a property of the `Grouping` and `WindowSet`
    flowing into the step, not of the root span or of any parameter here:
    `Working.hpc.job_export` evaluates estimators against a span length and
    the step's own params alone, and no window geometry is recoverable from
    those. Guessing a constant is what
    `Working/Preprocessing/window_matrix/cost.py` exists to refuse — a wrong
    number here routes a multi-hour training job into the "wait with a
    spinner" path.

    Declaring the callable is still what earns its place. `route_recipe`
    skips a step whose `estimate` is None outright, costing training at
    zero and routing it local; an estimator that answers "unknown" makes it
    report `'unknown'` instead, which is the honest answer and the
    conservative one.
    """
    return None


SPEC = register(AdapterSpec(
    name="catalogue.classifier",
    display_name="Classifier training (Grouping -> Model)",
    stage="catalogue",
    params=[
        ParamSpec(
            "n_estimators", int, 300,
            "Trees in the forest. More is steadier and slower; 300 matches the "
            "pre-labelled-directory pipeline this block's estimator shape follows.",
            min=1,
        ),
        ParamSpec(
            "class_weight", str, "balanced",
            "How to weight classes during fitting. 'balanced' is the default "
            "because a cluster-derived Grouping has no reason to be evenly sized "
            "and an unweighted forest would learn the largest cluster.",
            choices=["balanced", "balanced_subsample", "none"],
        ),
        ParamSpec(
            "holdout_frac", float, 0.25,
            "Fraction of windows held back to report an accuracy against. This "
            "is a sanity check on the fit, NOT the thesis's generalisation "
            "measure — that is the held-out recording, which this block never "
            "sees. 0 trains on every window. Dropped automatically when a class "
            "is too small to appear on both sides of the split.",
            min=0.0, max=0.9,
        ),
        ParamSpec(
            "random_state", int, 42,
            "Seed for the forest and the holdout split, so a re-run of the same "
            "recipe produces the same model file.",
        ),
    ],
    run=_run,
    input_kind="grouping",
    output_kind="model",
    side_inputs=[
        SideInputSpec(
            name="windows",
            type_kind="windowset",
            sources=["earlier_step"],
        ),
    ],
    estimate=_estimate,
    derive=_derive,
    description=(
        "Trains a classifier on a window set's feature matrix using a Grouping "
        "as its labels, and returns the fitted model as a path reference. The "
        "labels arrive as the primary input, so the same block trains from "
        "cluster-derived and from manually adjudicated groupings with only the "
        "upstream binding changed — which is what makes RQ1's comparison a "
        "comparison."
    ),
))
