"""
decode2.py
===========
Round 2, Task B: the nuisance/signal claim as a decoding problem.

THE CLAIM, AND WHY DECODING IS THE RIGHT SHAPE FOR IT
------------------------------------------------------
The paper's central claim is that ABSOLUTE AMPLITUDE carries the recording
site while NORMALISED GEOMETRY does not - that how big an event is tells
you which electrode saw it, and what shape it is does not.

Round one tested that with a Cramer's V between family and channel
(0.115 against a null median of 0.061) and with an amplitude-spread /
shape-spread ratio (2.26x). Both are real but neither is legible: a V of
0.115 is "weakly associated" on a scale nobody has intuitions about, and a
spread ratio depends on the clustering that produced the families.

Decoding replaces both with one number a reader already understands. Train
a classifier to name the electrode from an event, and report how often it
is right. Chance is 20% on five channels. If amplitude decodes well above
chance and shape barely beats it, the claim holds and is quantified. If
shape decodes as well as amplitude, THE CLAIM IS FALSIFIED - and that is
the finding, to be reported as one.

The three representations are `round2`'s two plus their concatenation:

  AMPLITUDE   drop depth, fall duration, tangent slope. Three numbers.
  SHAPE       the 200-point z-normalised vector the tree is built from.
              Each event's own duration and amplitude are divided out per
              vector, so nothing about size survives into it.
  BOTH        the two stacked, each standardised first so the three
              amplitude columns are not drowned by two hundred shape ones.
              If shape adds nothing over amplitude, that is the result.

WHAT IS CONTROLLED, AND WHY EACH CONTROL IS THERE
--------------------------------------------------
CLASS IMBALANCE. The five channels contribute 204 / 350 / 97 / 250 / 196
events, so a classifier that always answered "CH1" would score 32% plain
accuracy and look like it had learned something. Two defences, both
needed: BALANCED ACCURACY (the mean per-class recall, which that
classifier scores 20% on) and `class_weight="balanced"`, so the fit is not
dragged toward the largest channel in the first place.

FOLD LEAKAGE. Stratified 5-fold, and every scaler fitted INSIDE the fold
through a pipeline. Standardising over the whole matrix first would leak
the test fold's mean into training - a small effect here, and free to
avoid.

TWO CLASSIFIER FAMILIES, BOTH REPORTED. Logistic regression asks whether
the classes are LINEARLY separable in the representation; a random forest
asks whether they are separable at all. Reporting only the first would
understate shape, which is the representation the claim needs to come out
LOW - so the more generous model is the one that matters here, and hiding
it would be choosing the tool that flatters the hypothesis.

A PERMUTATION NULL, NOT A COMPARISON TO 0.20. Chance is 20% in
expectation, but a five-fold estimate on 1097 events has a spread around
it, and a representation with 200 columns can overfit its way above 20%
on noise. Permuting the channel labels and refitting the whole pipeline
measures that spread directly, so every accuracy gets a p rather than a
bare gap from a nominal baseline.
"""

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, confusion_matrix
from sklearn.model_selection import (StratifiedKFold, cross_val_predict,
                                     permutation_test_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from Pipelines.drop_motifs.round2 import SEED_BASE

N_FOLDS = 5
N_PERMUTATIONS = 1000
SCORING = "balanced_accuracy"

REPRESENTATIONS = ("amplitude", "shape", "both")


def _seed():
    """The round-2 formula with no channel and no realisation.

    `SEED_BASE + 100 * channel + realisation` is for per-channel draws.
    Task B's randomness is not per channel - one fold assignment and one
    label permutation stream cover all five - so it takes the base itself.
    Written down because a bare `random_state=20260903` in six call sites
    is how a seed formula quietly stops being a formula.
    """
    return SEED_BASE


def build(representation, shape, amplitude):
    """The design matrix for one representation."""
    if representation == "amplitude":
        return np.asarray(amplitude, dtype=float)
    if representation == "shape":
        return np.asarray(shape, dtype=float)
    if representation == "both":
        # Standardised before stacking, not after: three raw millivolt
        # columns next to two hundred z-scored ones would be invisible to
        # a distance-based or regularised model. The scaler inside the
        # pipeline then re-standardises within each fold, which is
        # harmless and keeps the leakage guarantee in one place.
        a = np.asarray(amplitude, dtype=float)
        a = (a - a.mean(axis=0)) / np.where(a.std(axis=0) > 0,
                                            a.std(axis=0), 1.0)
        return np.hstack([a, np.asarray(shape, dtype=float)])
    raise ValueError(f"unknown representation {representation!r}")


def classifiers(seed=None):
    """The two models, each inside a pipeline that scales within the fold."""
    seed = _seed() if seed is None else seed
    return {
        "logistic_regression": Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(
                max_iter=2000, class_weight="balanced", random_state=seed)),
        ]),
        "random_forest": Pipeline([
            # A forest does not need the scaler; it is here so the two
            # models see byte-identical input and any difference between
            # them is the model rather than the preprocessing.
            ("scale", StandardScaler()),
            # n_jobs=1, NOT -1. `permutation_test_score` already fans the
            # 1000 permutations across every core, and a forest that also
            # asks for every core turns that into 16 x 16 threads on 16
            # cores. Measured: the nested form had not finished one
            # representation after an hour; with the forest single-threaded
            # the whole grid runs in minutes. The outer loop is the one
            # worth parallelising - it has 1000 independent units of work
            # and the forest has 200.
            ("clf", RandomForestClassifier(
                n_estimators=200, min_samples_leaf=2,
                class_weight="balanced_subsample",
                random_state=seed, n_jobs=1)),
        ]),
    }


def decode(X, y, model, *, n_permutations=N_PERMUTATIONS, n_folds=N_FOLDS,
           seed=None, n_jobs=-1):
    """Balanced accuracy, its permutation null, and the confusion matrix.

    `permutation_test_score` refits the WHOLE pipeline on each permuted
    labelling, so the null carries the model's capacity to overfit as well
    as the fold noise. That matters most for the 200-column shape matrix,
    which is where a naive comparison to 0.20 would be most misleading.
    """
    seed = _seed() if seed is None else seed
    folds = StratifiedKFold(n_splits=n_folds, shuffle=True,
                            random_state=seed)

    score, null, p = permutation_test_score(
        model, X, y, scoring=SCORING, cv=folds,
        n_permutations=n_permutations, random_state=seed, n_jobs=n_jobs)

    predicted = cross_val_predict(model, X, y, cv=folds, n_jobs=n_jobs)
    labels = sorted(set(np.asarray(y).tolist()))
    matrix = confusion_matrix(y, predicted, labels=labels)

    return {
        "balanced_accuracy": float(score),
        "p_permutation": float(p),
        "n_permutations": int(n_permutations),
        "p_floor": float(1.0 / (n_permutations + 1)),
        "at_p_floor": bool(p <= 1.0 / (n_permutations + 1)),
        "null_mean": float(np.mean(null)),
        "null_median": float(np.median(null)),
        "null_q1": float(np.percentile(null, 25)),
        "null_q3": float(np.percentile(null, 75)),
        "null_min": float(np.min(null)),
        "null_max": float(np.max(null)),
        "null_values": [float(v) for v in null],
        "confusion_matrix": matrix.tolist(),
        "confusion_labels": [int(v) for v in labels],
        "per_class_recall": [
            float(row[i] / row.sum()) if row.sum() else float("nan")
            for i, row in enumerate(matrix)],
        "chance": float(1.0 / len(labels)),
    }


def chance_baseline(X, y, *, n_folds=N_FOLDS, seed=None):
    """What a classifier that ignores the data actually scores here.

    Drawn on the figure rather than the nominal 1/5, because "20%" is the
    expectation and this is the realisation - the number a reader would
    get if they ran the same folds on a model that learned nothing.
    """
    seed = _seed() if seed is None else seed
    folds = StratifiedKFold(n_splits=n_folds, shuffle=True,
                            random_state=seed)
    dummy = DummyClassifier(strategy="stratified", random_state=seed)
    predicted = cross_val_predict(dummy, X, y, cv=folds)
    return float(balanced_accuracy_score(y, predicted))


def headline(results):
    """The sentence the paper leads with, built from the numbers.

    Returns `(sentence, verdict)`. The verdict is `falsified` when shape
    decodes as well as amplitude, and it is computed rather than chosen:
    the claim under test is that amplitude carries the electrode and shape
    does not, so shape reaching amplitude's accuracy refutes it whatever
    the rest of the round says.
    """
    best = {}
    for representation in ("amplitude", "shape"):
        entries = results[representation]
        name = max(entries, key=lambda m: entries[m]["balanced_accuracy"])
        best[representation] = (name, entries[name])

    amp_name, amp = best["amplitude"]
    shape_name, shape = best["shape"]
    chance = amp["chance"]

    # "As well as" needs a threshold and it should be generous to the
    # falsifying outcome, not to the claim. Shape within 90% of
    # amplitude's margin above chance counts as decoding the electrode
    # just as well.
    amp_margin = amp["balanced_accuracy"] - chance
    shape_margin = shape["balanced_accuracy"] - chance
    ratio = shape_margin / amp_margin if amp_margin > 0 else float("inf")

    if amp["p_permutation"] > 0.05:
        verdict = "not supported"
        gloss = ("amplitude does not decode the electrode above its own "
                 "permutation null, so the claim's premise fails")
    elif ratio >= 0.90:
        verdict = "falsified"
        gloss = ("normalised shape recovers the electrode as well as "
                 "amplitude does; the representations are not separable "
                 "the way the claim requires")
    elif shape["p_permutation"] > 0.05:
        verdict = "supported"
        gloss = ("shape does not decode the electrode above chance at all, "
                 "which is the strong form of the claim")
    else:
        verdict = "supported with a caveat"
        gloss = ("shape decodes the electrode above chance but far less "
                 "well than amplitude; the claim holds as a statement "
                 "about degree, not as an absolute")

    sentence = (
        f"Electrode identity is recoverable from event amplitude at "
        f"{amp['balanced_accuracy'] * 100:.1f}% balanced accuracy "
        f"(p = {amp['p_permutation']:.4f}"
        f"{', at the permutation floor' if amp['at_p_floor'] else ''}, "
        f"{amp_name.replace('_', ' ')}) and from normalised shape at "
        f"{shape['balanced_accuracy'] * 100:.1f}% "
        f"(p = {shape['p_permutation']:.4f}"
        f"{', at the permutation floor' if shape['at_p_floor'] else ''}, "
        f"{shape_name.replace('_', ' ')}), against a "
        f"{chance * 100:.0f}% baseline.")

    return sentence, {
        "verdict": verdict,
        "gloss": gloss,
        "amplitude": {"model": amp_name,
                      "balanced_accuracy": amp["balanced_accuracy"],
                      "p": amp["p_permutation"]},
        "shape": {"model": shape_name,
                  "balanced_accuracy": shape["balanced_accuracy"],
                  "p": shape["p_permutation"]},
        "shape_margin_as_fraction_of_amplitude_margin": float(ratio),
        "falsification_threshold": 0.90,
    }
