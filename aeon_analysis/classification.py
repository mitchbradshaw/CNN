import numpy as np
from pathlib import Path
import sys

# ── Path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Default paths ─────────────────────────────────────────────────────────────
_DATA        = PROJECT_ROOT / "DATA" / "10_MINUTES"
TRAIN_INT    = _DATA / "10min_fs1.0_interesting_rawdata"
TRAIN_NINT   = _DATA / "10min_fs1.0_notinteresting_rawdata"
TEST_INT     = _DATA / "10min_fs1.0_interesting_rawdata_test"
TEST_NINT    = _DATA / "10min_fs1.0_notinteresting_rawdata_test"
MODELS_DIR   = PROJECT_ROOT / "MODELS"
OUT_DIR      = SCRIPT_DIR / "test_out"


# ═══════════════════════════════════════════════════════════════════════════════
# Data loading helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _load_labeled_windows(interesting_dir, notinteresting_dir):
    """
    Load all .npy windows from two directories and return (X, y).

    Each .npy file is one window: shape (n_channels, n_timepoints).
    Only channel 0 (raw signal) is used.  Channel 1 (absolute time) is dropped
    because its values are recording-specific and do not generalise — applying
    a model trained on one recording's time range to another gives degenerate
    constant predictions (all 0.5).
    Label 1 = interesting, 0 = not-interesting.

    Returns
    -------
    X : np.ndarray, shape (n_instances, 1, n_timepoints), float32
    y : np.ndarray, shape (n_instances,), int
    """
    int_files  = sorted(Path(interesting_dir).glob("*.npy"))
    nint_files = sorted(Path(notinteresting_dir).glob("*.npy"))

    if not int_files:
        raise FileNotFoundError(f"No .npy files found in {interesting_dir}")
    if not nint_files:
        raise FileNotFoundError(f"No .npy files found in {notinteresting_dir}")

    # [0:1] keeps the channel axis: (2, 600) → (1, 600)
    X_int  = np.stack([np.load(f)[0:1] for f in int_files]).astype(np.float32)
    X_nint = np.stack([np.load(f)[0:1] for f in nint_files]).astype(np.float32)

    X = np.concatenate([X_int, X_nint], axis=0)
    y = np.concatenate([
        np.ones(len(X_int),  dtype=int),
        np.zeros(len(X_nint), dtype=int),
    ])
    return X, y


# ═══════════════════════════════════════════════════════════════════════════════
# Classification pipelines (AeonDataset-based, unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

def pipeline_v1(ds) -> dict:
    """
    End-to-end sklearn-compatible pipeline: Catch22 features → Random Forest.
    """
    from aeon.transformations.collection.feature_based import Catch22
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score,
                                 classification_report, roc_auc_score,
                                 average_precision_score)
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline

    X_tr, X_te, y_tr, y_te = train_test_split(
        ds.X, ds.y, test_size=0.2, random_state=42, stratify=ds.y
    )

    pipe = make_pipeline(
        Catch22(replace_nans=True),
        RandomForestClassifier(n_estimators=100, random_state=42, class_weight="balanced"),
    )
    pipe.fit(X_tr, y_tr)
    y_pred   = pipe.predict(X_te)
    probas   = pipe.predict_proba(X_te)[:, 1]
    acc      = accuracy_score(y_te, y_pred)
    bal_acc  = balanced_accuracy_score(y_te, y_pred)
    auc_roc  = roc_auc_score(y_te, probas)
    auc_pr   = average_precision_score(y_te, probas)
    report   = classification_report(y_te, y_pred, zero_division=0)

    summary = (
        f"Catch22 + Balanced RandomForest pipeline\n"
        f"  n_train       : {len(X_tr)}\n"
        f"  n_test        : {len(X_te)}\n"
        f"  accuracy      : {acc:.4f}\n"
        f"  bal. accuracy : {bal_acc:.4f}\n"
        f"  AUC-ROC       : {auc_roc:.4f}\n"
        f"  AUC-PR        : {auc_pr:.4f}\n\n"
        f"{report}"
    )
    return {
        "y_pred": y_pred, "y_true": y_te, "probas": probas,
        "accuracy": acc, "balanced_accuracy": bal_acc,
        "auc_roc": auc_roc, "auc_pr": auc_pr,
        "_summary": summary,
    }

def pipeline_pruned_catch22(ds) -> dict:
    """
    Catch22 → VarianceThreshold → Balanced RandomForest.

    VarianceThreshold automatically removes zero-variance and near-constant
    Catch22 features before the classifier sees them.  Uses the full window
    set (no DTW, so no MAX_WINDOWS cap needed).
    """
    from aeon.transformations.collection.feature_based import Catch22
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_selection import VarianceThreshold
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score,
                                 classification_report, roc_auc_score,
                                 average_precision_score)
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline

    X_tr, X_te, y_tr, y_te = train_test_split(
        ds.X, ds.y, test_size=0.2, random_state=42, stratify=ds.y
    )

    pipe = make_pipeline(
        Catch22(replace_nans=True),
        VarianceThreshold(threshold=1e-6),
        RandomForestClassifier(n_estimators=100, random_state=42, class_weight="balanced"),
    )
    pipe.fit(X_tr, y_tr)

    vt          = pipe.named_steps["variancethreshold"]
    kept_mask   = vt.get_support()
    kept_idx    = np.where(kept_mask)[0].tolist()
    dropped_idx = np.where(~kept_mask)[0].tolist()

    y_pred  = pipe.predict(X_te)
    probas  = pipe.predict_proba(X_te)[:, 1]
    acc     = accuracy_score(y_te, y_pred)
    bal_acc = balanced_accuracy_score(y_te, y_pred)
    auc_roc = roc_auc_score(y_te, probas)
    auc_pr  = average_precision_score(y_te, probas)
    report  = classification_report(y_te, y_pred, zero_division=0)

    summary = (
        f"Pruned Catch22 + Balanced RandomForest\n"
        f"  features kept   : {len(kept_idx)}/22  {kept_idx}\n"
        f"  features dropped: {len(dropped_idx)}/22  {dropped_idx}\n"
        f"  n_train         : {len(X_tr)}\n"
        f"  n_test          : {len(X_te)}\n"
        f"  accuracy        : {acc:.4f}\n"
        f"  bal. accuracy   : {bal_acc:.4f}\n"
        f"  AUC-ROC         : {auc_roc:.4f}\n"
        f"  AUC-PR          : {auc_pr:.4f}\n\n"
        f"{report}"
    )
    return {
        "y_pred": y_pred, "y_true": y_te, "probas": probas,
        "accuracy": acc, "balanced_accuracy": bal_acc,
        "auc_roc": auc_roc, "auc_pr": auc_pr,
        "features_kept": kept_idx, "features_dropped": dropped_idx,
        "_summary": summary,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-labelled directory pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def train_catch22_classifier_from_dirs(
    train_interesting_dir=TRAIN_INT,
    train_notinteresting_dir=TRAIN_NINT,
    test_interesting_dir=TEST_INT,
    test_notinteresting_dir=TEST_NINT,
    model_dir=MODELS_DIR,
    model_name="catch22_rf_prelabeled",
    out_dir=OUT_DIR,
) -> dict:
    """
    Train a Catch22 + RandomForest classifier from pre-labelled window directories.

    Each directory contains one .npy file per window (shape: n_channels × n_timepoints).
    Labels: 1 = interesting, 0 = not-interesting.

    Trains on train_* dirs, evaluates on test_* dirs, saves the fitted pipeline
    to model_dir/{model_name}.joblib, and writes results (pkl + txt) to out_dir.

    Parameters
    ----------
    train_interesting_dir    : path to .npy files for training interesting windows
    train_notinteresting_dir : path to .npy files for training not-interesting windows
    test_interesting_dir     : path to .npy files for test interesting windows
    test_notinteresting_dir  : path to .npy files for test not-interesting windows
    model_dir                : directory where the fitted pipeline is saved
    model_name               : filename stem for the saved model (.joblib)
    out_dir                  : directory for pkl / txt result files

    Returns
    -------
    dict with y_pred, y_true, probas, accuracy, balanced_accuracy,
              auc_roc, auc_pr, features_kept, features_dropped, _summary
    """
    import joblib
    import pickle
    from aeon.transformations.collection.feature_based import Catch22
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_selection import VarianceThreshold
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score,
                                 classification_report, roc_auc_score,
                                 average_precision_score)
    from sklearn.pipeline import make_pipeline

    # ── Load data ─────────────────────────────────────────────────────────────
    print("Loading training data…")
    X_tr, y_tr = _load_labeled_windows(train_interesting_dir, train_notinteresting_dir)
    print(f"  shape: {X_tr.shape}  "
          f"interesting={int(y_tr.sum())}  not-interesting={int((y_tr == 0).sum())}")

    print("Loading test data…")
    X_te, y_te = _load_labeled_windows(test_interesting_dir, test_notinteresting_dir)
    print(f"  shape: {X_te.shape}  "
          f"interesting={int(y_te.sum())}  not-interesting={int((y_te == 0).sum())}")

    # ── Build and fit pipeline ─────────────────────────────────────────────────
    n_channels  = X_tr.shape[1]
    n_features  = 22 * n_channels   # Catch22 computes 22 stats per channel
    print(f"\nFitting pipeline  "
          f"(Catch22 [{n_channels} ch → {n_features} features] "
          f"→ VarianceThreshold → RandomForest)…")

    pipe = make_pipeline(
        Catch22(replace_nans=True),
        VarianceThreshold(threshold=1e-6),
        RandomForestClassifier(
            n_estimators=300,
            random_state=42,
            class_weight="balanced",
            n_jobs=-1,
        ),
    )
    pipe.fit(X_tr, y_tr)
    print("  fit complete.")

    # ── Feature pruning report ─────────────────────────────────────────────────
    vt          = pipe.named_steps["variancethreshold"]
    kept_mask   = vt.get_support()
    kept_idx    = np.where(kept_mask)[0].tolist()
    dropped_idx = np.where(~kept_mask)[0].tolist()

    # ── Evaluate on held-out test set ─────────────────────────────────────────
    y_pred  = pipe.predict(X_te)
    probas  = pipe.predict_proba(X_te)[:, 1]
    acc     = accuracy_score(y_te, y_pred)
    bal_acc = balanced_accuracy_score(y_te, y_pred)
    auc_roc = roc_auc_score(y_te, probas)
    auc_pr  = average_precision_score(y_te, probas)
    report  = classification_report(
        y_te, y_pred,
        target_names=["not-interesting", "interesting"],
        zero_division=0,
    )

    summary = (
        f"Catch22 + Balanced RandomForest  (pre-labelled directories)\n"
        f"  train  interesting    : {int(y_tr.sum())}\n"
        f"  train  not-interesting: {int((y_tr == 0).sum())}\n"
        f"  test   interesting    : {int(y_te.sum())}\n"
        f"  test   not-interesting: {int((y_te == 0).sum())}\n"
        f"  features kept   : {len(kept_idx)}/{n_features}  {kept_idx}\n"
        f"  features dropped: {len(dropped_idx)}/{n_features}  {dropped_idx}\n"
        f"  accuracy        : {acc:.4f}\n"
        f"  bal. accuracy   : {bal_acc:.4f}\n"
        f"  AUC-ROC         : {auc_roc:.4f}\n"
        f"  AUC-PR          : {auc_pr:.4f}\n\n"
        f"{report}"
    )
    print("\n" + summary)

    # ── Save model ─────────────────────────────────────────────────────────────
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    model_path = Path(model_dir) / f"{model_name}.joblib"
    joblib.dump(pipe, model_path)
    print(f"Model saved  → {model_path}")

    # ── Save results ───────────────────────────────────────────────────────────
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    results = {
        "y_pred": y_pred, "y_true": y_te, "probas": probas,
        "accuracy": acc, "balanced_accuracy": bal_acc,
        "auc_roc": auc_roc, "auc_pr": auc_pr,
        "features_kept": kept_idx, "features_dropped": dropped_idx,
        "_summary": summary,
    }
    pkl_path = Path(out_dir) / f"{model_name}_output.pkl"
    txt_path = Path(out_dir) / f"{model_name}_output.txt"
    with open(pkl_path, "wb") as f:
        pickle.dump(results, f)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"Results saved → {pkl_path.name}  +  {txt_path.name}")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Threshold-aware model wrapper
# ═══════════════════════════════════════════════════════════════════════════════

class ThresholdedPipeline:
    """
    Wraps a fitted sklearn pipeline with a custom decision threshold.

    ``predict`` uses the stored threshold instead of the default 0.5.
    ``predict_proba`` delegates directly to the underlying pipeline.
    Fully picklable — safe to save/load with joblib.
    """

    def __init__(self, pipeline, threshold: float):
        self.pipeline  = pipeline
        self.threshold = threshold
        self.classes_  = pipeline.classes_   # sklearn compatibility

    def predict_proba(self, X):
        return self.pipeline.predict_proba(X)

    def predict(self, X):
        probas = self.predict_proba(X)[:, 1]
        return (probas >= self.threshold).astype(int)

    def __repr__(self):
        return (f"ThresholdedPipeline(threshold={self.threshold}, "
                f"pipeline={self.pipeline})")


# Ensure joblib can deserialise this class regardless of whether
# classification.py was run as __main__ or imported as a module.
ThresholdedPipeline.__module__ = "aeon_analysis.classification"


# ═══════════════════════════════════════════════════════════════════════════════
# Threshold sweep on saved results
# ═══════════════════════════════════════════════════════════════════════════════

def threshold_sweep_from_results(
    pkl_path=None,
    model_path=None,
    model_dir=MODELS_DIR,
    model_name="catch22_rf_prelabeled_opt",
    out_dir=OUT_DIR,
    base_name="catch22_rf_prelabeled",
) -> dict:
    """
    Sweep decision thresholds on already-computed probabilities, find the
    operating point that maximises F1 for the 'interesting' class, wrap the
    saved pipeline at that threshold, and re-save it.

    Reads probas and y_true from the pkl saved by train_catch22_classifier_from_dirs.
    No Catch22 recomputation needed.

    Parameters
    ----------
    pkl_path   : path to the results pkl (default: out_dir/{base_name}_output.pkl)
    model_path : path to the trained .joblib pipeline (default: model_dir/{base_name}.joblib)
    model_dir  : directory to save the thresholded model
    model_name : filename stem for the new model (.joblib)
    out_dir    : directory for sweep CSV / txt outputs
    base_name  : stem used to build default pkl_path and model_path

    Returns
    -------
    dict with best_threshold, sweep rows, PR curve arrays, and _summary
    """
    import csv as _csv
    import joblib
    import pickle
    from sklearn.metrics import (precision_recall_curve, average_precision_score,
                                 roc_auc_score, precision_score, recall_score,
                                 f1_score)

    out_dir   = Path(out_dir)
    model_dir = Path(model_dir)

    if pkl_path is None:
        pkl_path = out_dir / f"{base_name}_output.pkl"
    if model_path is None:
        model_path = model_dir / f"{base_name}.joblib"

    # ── Load saved probas and labels ──────────────────────────────────────────
    with open(pkl_path, "rb") as f:
        saved = pickle.load(f)
    probas = saved["probas"]
    y_te   = saved["y_true"]
    print(f"Loaded results from {pkl_path.name}  "
          f"(n_test={len(y_te)}, interesting={int(y_te.sum())})")

    auc_roc = roc_auc_score(y_te, probas)
    auc_pr  = average_precision_score(y_te, probas)

    # ── Discrete threshold sweep ──────────────────────────────────────────────
    thresholds = np.linspace(0.05, 0.95, 19)
    sweep_rows = []
    for t in thresholds:
        y_t = (probas >= t).astype(int)
        p   = precision_score(y_te, y_t, zero_division=0)
        r   = recall_score(y_te, y_t, zero_division=0)
        f   = f1_score(y_te, y_t, zero_division=0)
        sweep_rows.append({
            "threshold":               round(float(t), 3),
            "precision":               round(float(p), 4),
            "recall":                  round(float(r), 4),
            "f1":                      round(float(f), 4),
            "n_predicted_interesting": int(y_t.sum()),
        })

    best = max(sweep_rows, key=lambda row: row["f1"])

    # ── Continuous PR curve ───────────────────────────────────────────────────
    prec_c, rec_c, thr_c = precision_recall_curve(y_te, probas)

    # ── Format summary table ──────────────────────────────────────────────────
    header   = f"  {'thr':>5}  {'prec':>6}  {'rec':>6}  {'f1':>6}  {'n_pred':>6}"
    divider  = "  " + "─" * (len(header) - 2)
    rows_fmt = [header, divider]
    for row in sweep_rows:
        rows_fmt.append(
            f"  {row['threshold']:>5.2f}  {row['precision']:>6.4f}  "
            f"{row['recall']:>6.4f}  {row['f1']:>6.4f}  "
            f"{row['n_predicted_interesting']:>6}"
        )

    summary = "\n".join([
        f"PR Threshold Sweep  ({base_name})",
        f"  n_test         : {len(y_te)}",
        f"  interesting    : {int(y_te.sum())}",
        f"  not-interesting: {int((y_te == 0).sum())}",
        f"  AUC-ROC        : {auc_roc:.4f}",
        f"  AUC-PR         : {auc_pr:.4f}",
        f"  Best threshold : {best['threshold']:.2f}  "
        f"(prec={best['precision']:.4f}  rec={best['recall']:.4f}  "
        f"F1={best['f1']:.4f}  n_pred={best['n_predicted_interesting']})",
        "",
    ] + rows_fmt) + "\n"

    print("\n" + summary)

    # ── Save CSVs + txt ───────────────────────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)

    discrete_path  = out_dir / f"{base_name}_sweep_discrete.csv"
    prcurve_path   = out_dir / f"{base_name}_sweep_prcurve.csv"
    txt_path       = out_dir / f"{model_name}_sweep_output.txt"

    with open(discrete_path, "w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=sweep_rows[0].keys())
        writer.writeheader()
        writer.writerows(sweep_rows)

    with open(prcurve_path, "w", newline="") as fh:
        writer = _csv.writer(fh)
        writer.writerow(["precision", "recall", "threshold"])
        for p, r, t in zip(prec_c[:-1], rec_c[:-1], thr_c):
            writer.writerow([round(float(p), 4), round(float(r), 4), round(float(t), 4)])

    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(summary)

    print(f"Sweep saved → {discrete_path.name}  +  {prcurve_path.name}  +  {txt_path.name}")

    # ── Wrap pipeline at optimal threshold and re-save ────────────────────────
    pipeline = joblib.load(model_path)
    opt_threshold = best["threshold"]
    thresholded = ThresholdedPipeline(pipeline, opt_threshold)

    model_dir.mkdir(parents=True, exist_ok=True)
    opt_model_path = model_dir / f"{model_name}.joblib"
    joblib.dump(thresholded, opt_model_path)
    print(f"Thresholded model (t={opt_threshold}) saved → {opt_model_path}")

    return {
        "best_threshold": best,
        "sweep": sweep_rows,
        "prec_curve": prec_c,
        "rec_curve": rec_c,
        "thr_curve": thr_c,
        "auc_roc": auc_roc,
        "auc_pr": auc_pr,
        "_summary": summary,
    }


if __name__ == "__main__":
    threshold_sweep_from_results()

    # To retrain from scratch first, uncomment:
    #train_catch22_classifier_from_dirs()
