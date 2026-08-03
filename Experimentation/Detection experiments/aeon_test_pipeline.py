"""
aeon_test_pipeline.py
─────────────────────
Runs all aeon example functions against the user's own time-series dataset,
handling failures gracefully and persisting outputs to Results/Catalogue/aeon/current/.

Run from the project root (g:/My Drive/PROJECTS/UndergroundBrainsProject/CNN):
    python aeon_analysis/aeon_test_pipeline.py
"""

import os
import sys
import pickle
import logging
import textwrap
import traceback
from collections import Counter
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional


import numpy as np

# ── Path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR
while not (PROJECT_ROOT / "Working").is_dir() and PROJECT_ROOT != PROJECT_ROOT.parent:
    PROJECT_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Working.Preprocessing.manage_data.load_data import load_raw_data   # noqa: E402 (after sys.path fix)

# ── Configuration ─────────────────────────────────────────────────────────────
FILE        = "0.01_percent_M2_concat_fs1.mat"
FS          = 1.0    # Hz
MATNAME     = "VECTOR"
WINDOWMIN   =  10
WINDOW_SIZE  = int(60 * WINDOWMIN * FS)  # samples per window (= 10 min @ 1 Hz)
N_CLUSTERS   = 2        # used by clustering fallback label generator
OUT_DIR      = PROJECT_ROOT / "Results" / "Catalogue" / "aeon" / "current"

# ── WindowMatrix / CNN label settings ────────────────────────────────────────
# Set to True to load CNN confidence scores from CSV_FILE as labels.
# Set to False to fall back to amplitude-binning (generate_labels).
USE_WIN_MATRIX  = True
CSV_FILE        = "0.01_percent_M2_concat_fs1.mat_step0.5.csv"   # relative to MATRICES/
LABEL_THRESHOLD = 0.5   # score >= threshold → 1 (interesting), else 0 (not-interesting)
# All available CNN confidence columns.  All present ones are averaged per window.
CNN_SCORE_COLS  = [
    "cnn_p_fusion_interesting",
    "cnn_p_GASF_interesting",
    "cnn_p_GADF_interesting",
    "cnn_p_recurrence_interesting",
]

# ── Performance caps ──────────────────────────────────────────────────────────
# ClaSP is O(n²) in signal length — subsample the raw signal for segmentation.
MAX_SEG_PTS  = 10_000   # max raw points passed to ClaSPSegmenter
# DTW pairwise distance is O(n_windows × W²) — cap windows for DTW estimators.
MAX_WINDOWS  = 200      # max windows used by KNN / K-Means DTW methods

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Label generation
# ═══════════════════════════════════════════════════════════════════════════════

def generate_labels_from_wm(wm) -> tuple[np.ndarray, np.ndarray]:
    """
    Derive binary CNN labels from a WindowMatrix that carries pre-computed
    confidence scores.

    All columns listed in CNN_SCORE_COLS that are actually present in the matrix
    are averaged per window (NaN-safe).  The averaged score is then thresholded
    at LABEL_THRESHOLD to produce a binary label:

        score >= LABEL_THRESHOLD  →  1  (interesting)
        score <  LABEL_THRESHOLD  →  0  (not-interesting)

    Windows where every score column is NaN are dropped.

    Parameters
    ----------
    wm : WindowMatrix

    Returns
    -------
    start_indices : (N,) int64 array  – window start sample positions
    y             : (N,) int64 array  – 0 or 1 per window
    """
    available = set(wm.columns)
    found_cols = [c for c in CNN_SCORE_COLS if c in available]

    if not found_cols:
        raise ValueError(
            f"None of the expected CNN score columns were found in the WindowMatrix.\n"
            f"  Expected (any of) : {CNN_SCORE_COLS}\n"
            f"  Available columns : {sorted(available)}\n"
            "Run add_cnn_scores() on the WindowMatrix first."
        )

    log.info("  CNN score columns found: %s", found_cols)

    # Stack found columns into (N, n_cols) float array; missing cols already absent
    import pandas as pd
    score_matrix = pd.concat(
        [wm.get_column(c).rename(c) for c in found_cols], axis=1
    ).to_numpy(dtype=np.float64)                    # (N, n_found)

    # Average across available models per window (NaN-safe)
    combined_score = np.nanmean(score_matrix, axis=1)   # (N,)

    start_indices = wm.df.index.to_numpy(dtype=np.int64)

    # Drop windows where every score column was NaN
    valid = ~np.isnan(combined_score)
    n_dropped = int((~valid).sum())
    if n_dropped:
        log.warning("  Dropped %d windows with all-NaN scores.", n_dropped)
        start_indices  = start_indices[valid]
        combined_score = combined_score[valid]

    y = (combined_score >= LABEL_THRESHOLD).astype(np.int64)

    n_interesting = int(y.sum())
    n_not         = int((y == 0).sum())
    log.info(
        "  Labels from %d column(s), threshold=%.2f:  "
        "%d interesting  /  %d not-interesting",
        len(found_cols), LABEL_THRESHOLD, n_interesting, n_not,
    )

    return start_indices, y


def generate_labels(X: np.ndarray) -> np.ndarray:
    """
    Placeholder label generator.

    Partitions windows into N_CLUSTERS classes by their mean amplitude using
    equal-frequency binning (quantile-based).  Replace the body with
    CNN-based scoring when available.

    Parameters
    ----------
    X : ndarray, shape (n_instances, n_channels, n_timepoints)

    Returns
    -------
    y : ndarray, shape (n_instances,), dtype int
        Labels in range [0, N_CLUSTERS).
    """
    means = X[:, 0, :].mean(axis=1)
    edges = np.percentile(means, np.linspace(0, 100, N_CLUSTERS + 1))
    # Ensure unique edges to avoid zero-width bins
    edges = np.unique(edges)
    y = np.digitize(means, edges[1:-1])   # 0 … len(edges)-2
    return y.astype(np.int64)


# ═══════════════════════════════════════════════════════════════════════════════
# Dataset loading & adaptation
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AeonDataset:
    """
    Holds the user's dataset pre-adapted for aeon estimators.

    Attributes
    ----------
    x_raw       : 1-D raw signal,             shape (T,)
    t           : time axis (seconds),         shape (T,)
    X           : windowed collection,         shape (n_instances, 1, window_size)
    y           : integer class labels,        shape (n_instances,)
    y_cont      : continuous targets (window mean amplitude), shape (n_instances,)
    window_size : int – samples per window
    """
    x_raw:       np.ndarray
    t:           np.ndarray
    X:           np.ndarray
    y:           np.ndarray
    y_cont:      np.ndarray
    window_size: int


def _window_signal(x: np.ndarray, window_size: int) -> np.ndarray:
    """
    Slice a 1-D signal into non-overlapping windows.

    Returns
    -------
    ndarray, shape (n_windows, 1, window_size), dtype float32
    """
    n_windows = len(x) // window_size
    if n_windows < 2:
        raise RuntimeError(
            f"Signal length {len(x)} too short to create ≥2 windows of size "
            f"{window_size}.  Reduce WINDOW_SIZE or supply more data."
        )
    trimmed = x[: n_windows * window_size]
    windows = trimmed.reshape(n_windows, window_size)
    return windows[:, np.newaxis, :].astype(np.float32)   # (N, 1, W)


def _validate_array(arr: np.ndarray, name: str) -> None:
    """Raise if arr contains NaN / Inf or is empty."""
    if arr.size == 0:
        raise ValueError(f"{name} is empty.")
    if not np.isfinite(arr).all():
        n_bad = (~np.isfinite(arr)).sum()
        raise ValueError(f"{name} contains {n_bad} non-finite value(s) (NaN/Inf).")


def _subsample_windows(
    X: np.ndarray,
    y: np.ndarray,
    max_n: int,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Stratified subsample of windows to at most *max_n* instances.

    Each class is sampled proportionally so minority classes are not accidentally
    wiped out by uniform random selection.  Returns arrays unchanged when
    len(X) <= max_n.  Indices are sorted to preserve temporal order.
    """
    if len(X) <= max_n:
        return X, y
    rng = np.random.default_rng(seed)
    classes, class_counts = np.unique(y, return_counts=True)
    chosen = []
    for cls, count in zip(classes, class_counts):
        cls_pos = np.where(y == cls)[0]
        n_take  = max(1, round(max_n * count / len(X)))
        n_take  = min(n_take, len(cls_pos))
        chosen.append(rng.choice(cls_pos, size=n_take, replace=False))
    idx   = np.sort(np.concatenate(chosen))
    y_sub = y[idx]
    dist  = {int(c): int((y_sub == c).sum()) for c in classes}
    log.info(
        "  Stratified subsample %d → %d windows  class dist: %s",
        len(X), len(idx), dist,
    )
    return X[idx], y_sub


def load_dataset() -> AeonDataset:
    """
    Load and pre-process the user's dataset into an AeonDataset.

    When USE_WIN_MATRIX is True, windows and labels are taken directly from the
    pre-computed WindowMatrix CSV (CNN confidence scores → binary labels).
    When False, windows are created with uniform non-overlapping slicing and
    labels come from amplitude-quantile binning (placeholder).
    """
    log.info("Loading dataset  (%s) …", FILE)
    x_raw, t = load_raw_data(FILE, FS, matname=MATNAME)

    if x_raw.ndim != 1:
        raise ValueError(f"Expected 1-D raw signal, got shape {x_raw.shape}.")

    x_raw = x_raw.astype(np.float32)
    _validate_array(x_raw, "x_raw")

    if USE_WIN_MATRIX:
        # ── Path A: windows + labels from WindowMatrix ────────────────────
        from Working.Preprocessing.window_matrix.matrix_calc import load_matrix   # lazy import; avoids circular deps

        timescale_min = WINDOW_SIZE / (60.0 * FS)   # e.g. 10 min for 600 samples @ 1 Hz
        csv_path      = PROJECT_ROOT / "MATRICES" / CSV_FILE
        log.info("Loading WindowMatrix from %s …", csv_path.name)
        wm = load_matrix(str(csv_path), x_raw, timescale_min, FS)

        start_indices, y = generate_labels_from_wm(wm)
        ws = wm._window_samples   # samples per window as stored in the matrix

        # Discard any window whose tail would exceed the signal boundary
        in_bounds = (start_indices + ws) <= len(x_raw)
        n_clipped = int((~in_bounds).sum())
        if n_clipped:
            log.warning("  Dropped %d out-of-bounds windows.", n_clipped)
            start_indices = start_indices[in_bounds]
            y             = y[in_bounds]

        # Build (N, 1, ws) float32 array from the matrix's actual window slices
        X = np.stack(
            [x_raw[idx : idx + ws] for idx in start_indices], axis=0
        )[:, np.newaxis, :].astype(np.float32)

        window_size_used = ws

    else:
        # ── Path B: uniform windows + amplitude-binning labels (fallback) ─
        log.info("USE_WIN_MATRIX=False — using amplitude-binning labels.")
        X                = _window_signal(x_raw, WINDOW_SIZE)
        y                = generate_labels(X)
        window_size_used = WINDOW_SIZE

    if X.shape[0] < 2:
        raise RuntimeError(
            f"Need at least 2 windows, got {X.shape[0]}.  "
            "Check CSV_FILE path or increase the dataset size."
        )

    y_cont = X[:, 0, :].mean(axis=1).astype(np.float32)

    log.info(
        "Dataset ready  –  raw: %d pts | windows: %s | unique labels: %s",
        len(x_raw), X.shape, sorted(np.unique(y).tolist()),
    )
    return AeonDataset(
        x_raw=x_raw, t=t,
        X=X, y=y, y_cont=y_cont,
        window_size=window_size_used,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Output helpers
# ═══════════════════════════════════════════════════════════════════════════════

def save_output(name: str, payload: dict, summary: Optional[str] = None) -> None:
    """Persist result to Results/Catalogue/aeon/current/<name>_output.pkl and optionally .txt."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pkl_path = OUT_DIR / f"{name}_output.pkl"
    with open(pkl_path, "wb") as fh:
        pickle.dump(payload, fh)
    log.info("  Saved  →  %s", pkl_path.name)

    if summary:
        txt_path = OUT_DIR / f"{name}_output.txt"
        with open(txt_path, "w") as fh:
            fh.write(summary)
        log.info("  Saved  →  %s", txt_path.name)


# ═══════════════════════════════════════════════════════════════════════════════
# Example functions – each adapted to the user's AeonDataset
# ═══════════════════════════════════════════════════════════════════════════════

def detect_anomaly(ds: AeonDataset) -> dict:
    """
    STOMP-based anomaly detection on the raw 1-D signal.

    Scores each position in the time series with a matrix profile; higher
    values indicate more anomalous subsequences.
    """
    # aeon moved STOMP between versions; try each known path.
    import importlib
    STOMP = None
    # Try every known module path across aeon versions, then fall back to
    # scanning the top-level package for any class named STOMP.
    for _mod in (
        "aeon.anomaly_detection.distance_based",
        "aeon.anomaly_detection",
        "aeon.anomaly_detection._stomp",
        "aeon.anomaly_detection.matrix_profile._stomp",
        "aeon.anomaly_detection.matrix_profile",
    ):
        try:
            STOMP = getattr(importlib.import_module(_mod), "STOMP")
            break
        except (ImportError, AttributeError):
            continue

    if STOMP is None:
        # Last resort: walk every public name in the top-level package
        try:
            import aeon.anomaly_detection as _ad
            for _name in dir(_ad):
                if _name == "STOMP":
                    STOMP = getattr(_ad, _name)
                    break
        except ImportError:
            pass

    if STOMP is None:
        raise ImportError(
            "Cannot locate STOMP in any known aeon.anomaly_detection submodule. "
            "Check your aeon version with: python -c \"import aeon; print(aeon.__version__)\""
        )

    stomp = STOMP(window_size=int(ds.window_size))
    scores = stomp.fit_predict(ds.x_raw)

    summary = (
        f"STOMP anomaly scores\n"
        f"  input shape  : {ds.x_raw.shape}\n"
        f"  scores shape : {scores.shape}\n"
        f"  min / max    : {scores.min():.4f} / {scores.max():.4f}\n"
        f"  mean         : {scores.mean():.4f}\n"
    )
    return {"scores": scores, "_summary": summary}


def segmentation(ds: AeonDataset) -> dict:
    """
    ClaSP-based time-series segmentation on the raw 1-D signal.

    Identifies structural change points in the signal.

    Note: ClaSP is O(n²) in signal length.  To stay tractable the input is
    capped at MAX_SEG_PTS points (configurable at the top of this file).
    """
    from aeon.segmentation import ClaSPSegmenter

    # Subsample: ClaSP at 162k pts will never finish in a reasonable wall time.
    x_seg = ds.x_raw[:MAX_SEG_PTS].astype(np.float64)   # ClaSP requires float64
    log.info(
        "  Segmentation using first %d / %d signal points (MAX_SEG_PTS cap).",
        len(x_seg), len(ds.x_raw),
    )

    clasp = ClaSPSegmenter()
    change_points = clasp.fit_predict(x_seg)

    summary = (
        f"ClaSP segmentation\n"
        f"  signal used   : {len(x_seg)} / {len(ds.x_raw)} pts  (MAX_SEG_PTS={MAX_SEG_PTS})\n"
        f"  change points : {change_points}\n"
        f"  n_segments    : {len(change_points) + 1}\n"
    )
    return {"change_points": change_points, "model": clasp, "_summary": summary}


def classifier_KN(ds: AeonDataset) -> dict:
    """
    1-NN DTW time-series classifier trained/evaluated on windowed data.
    Windows are capped at MAX_WINDOWS before splitting to keep DTW tractable.
    """
    from aeon.classification.distance_based import KNeighborsTimeSeriesClassifier
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report
    from sklearn.model_selection import train_test_split

    X, y = _subsample_windows(ds.X, ds.y, MAX_WINDOWS)
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    clf = KNeighborsTimeSeriesClassifier(n_neighbors=1, distance="dtw")
    clf.fit(X_tr, y_tr)
    y_pred   = clf.predict(X_te)
    acc      = accuracy_score(y_te, y_pred)
    bal_acc  = balanced_accuracy_score(y_te, y_pred)
    report   = classification_report(y_te, y_pred, zero_division=0)

    summary = (
        f"KNN classifier (DTW, k=1)\n"
        f"  n_train       : {len(X_tr)}\n"
        f"  n_test        : {len(X_te)}\n"
        f"  accuracy      : {acc:.4f}\n"
        f"  bal. accuracy : {bal_acc:.4f}\n\n"
        f"{report}"
    )
    return {
        "y_pred": y_pred, "y_true": y_te,
        "accuracy": acc, "balanced_accuracy": bal_acc,
        "_summary": summary,
    }


def regression_forecast(ds: AeonDataset) -> dict:
    """
    KNN time-series regressor predicting the mean amplitude of each window.
    Windows are capped at MAX_WINDOWS before splitting to keep DTW tractable.
    """
    from aeon.regression.distance_based import KNeighborsTimeSeriesRegressor
    from sklearn.metrics import mean_squared_error, r2_score
    from sklearn.model_selection import train_test_split

    X, y_cont = _subsample_windows(ds.X, ds.y_cont, MAX_WINDOWS)
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y_cont, test_size=0.2, random_state=42
    )

    reg = KNeighborsTimeSeriesRegressor(n_neighbors=3, distance="dtw")
    reg.fit(X_tr, y_tr)
    y_pred = reg.predict(X_te)
    mse    = mean_squared_error(y_te, y_pred)
    r2     = r2_score(y_te, y_pred)

    summary = (
        f"KNN regressor (DTW, k=3)\n"
        f"  target       : window mean amplitude\n"
        f"  n_train      : {len(X_tr)}\n"
        f"  n_test       : {len(X_te)}\n"
        f"  MSE          : {mse:.6f}\n"
        f"  R²           : {r2:.4f}\n"
    )
    return {
        "y_pred": y_pred, "y_true": y_te,
        "mse": mse, "r2": r2,
        "_summary": summary,
    }


def clustering_kmeans(ds: AeonDataset) -> dict:
    """
    DTW K-Means clustering on windowed time-series data.
    Windows are capped at MAX_WINDOWS to keep DTW K-Means tractable.
    """
    from aeon.clustering import TimeSeriesKMeans
    from sklearn.metrics import rand_score

    X, y = _subsample_windows(ds.X, ds.y, MAX_WINDOWS)
    X = X.astype(np.float64)   # aeon's Numba-compiled DTW requires float64
    kmeans = TimeSeriesKMeans(n_clusters=N_CLUSTERS, distance="dtw", random_state=42)
    kmeans.fit(X)
    cluster_labels = kmeans.labels_
    rs = rand_score(y, cluster_labels)

    label_dist = {
        int(k): int(v)
        for k, v in zip(*np.unique(cluster_labels, return_counts=True))
    }
    summary = (
        f"K-Means clustering (DTW)\n"
        f"  n_clusters  : {N_CLUSTERS}\n"
        f"  rand_score  : {rs:.4f}\n"
        f"  label dist  : {label_dist}\n"
    )
    return {
        "labels": cluster_labels, "rand_score": rs,
        "model": kmeans,
        "_summary": summary,
    }


def sim_search(ds: AeonDataset) -> dict:
    """
    StompMotif similarity search: find the best matching subsequence of the
    first signal half within the second half.
    """
    from aeon.similarity_search.series import StompMotif

    midpoint = len(ds.x_raw) // 2
    X1 = ds.x_raw[:midpoint]
    X2 = ds.x_raw[midpoint:]

    motif_len = int(ds.window_size)
    top_k     = StompMotif(motif_len).fit(X1)
    distances, indexes = top_k.predict(X2, k=1)

    # StompMotif.predict() return type varies across aeon versions:
    # could be a plain list, a list of arrays, or a nested ndarray.
    # np.asarray(...).ravel()[0] handles all cases safely.
    def _first(v):
        return np.asarray(v).ravel()[0]

    summary = (
        f"StompMotif similarity search\n"
        f"  motif length  : {motif_len}\n"
        f"  query segment : first {midpoint} pts\n"
        f"  search segment: remaining {len(X2)} pts\n"
        f"  best distance : {float(_first(distances)):.6f}\n"
        f"  best index    : {int(_first(indexes))}\n"
    )
    return {"distances": distances, "indexes": indexes, "_summary": summary}


def transformations(ds: AeonDataset) -> dict:
    """
    Catch22 feature extraction – transforms each window into 22 summary statistics.
    """
    from aeon.transformations.collection.feature_based import Catch22

    c22      = Catch22(replace_nans=True)
    features = c22.fit_transform(ds.X)   # (n_instances, 22)

    feature_means = features.mean(axis=0)
    feature_stds  = features.std(axis=0)

    summary_lines = ["Catch22 feature extraction"]
    summary_lines.append(f"  input  shape : {ds.X.shape}")
    summary_lines.append(f"  output shape : {features.shape}")
    summary_lines.append("  feature statistics (mean ± std):")
    for i, (m, s) in enumerate(zip(feature_means, feature_stds)):
        summary_lines.append(f"    feat_{i:02d} : {m:+.4f} ± {s:.4f}")
    summary = "\n".join(summary_lines) + "\n"

    return {"features": features, "_summary": summary}


def pipeline_v1(ds: AeonDataset) -> dict:
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
    probas   = pipe.predict_proba(X_te)[:, 1]   # P(interesting)
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


def grid_search_KN(ds: AeonDataset) -> dict:
    """
    GridSearchCV over KNN distance metrics and neighbour counts.
    Uses StratifiedKFold with a safe fold count.
    Windows are capped at MAX_WINDOWS to keep DTW tractable across CV folds.
    """
    from aeon.classification.distance_based import KNeighborsTimeSeriesClassifier
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score,
                                 f1_score, classification_report)
    from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split

    X, y = _subsample_windows(ds.X, ds.y, MAX_WINDOWS)
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Cap folds so no class ends up with fewer samples than folds
    min_class_count = min(Counter(y_tr.tolist()).values())
    n_splits        = min(4, min_class_count)
    if n_splits < 2:
        raise RuntimeError(
            f"Not enough samples per class for cross-validation "
            f"(min class count in train = {min_class_count}).  "
            f"Increase WINDOW_SIZE or reduce N_CLUSTERS."
        )

    knn        = KNeighborsTimeSeriesClassifier()
    param_grid = {"n_neighbors": [1, 3], "distance": ["euclidean", "dtw"]}
    gscv       = GridSearchCV(
        knn, param_grid,
        cv=StratifiedKFold(n_splits=n_splits),
        n_jobs=-1,
        scoring="f1",
    )
    gscv.fit(X_tr, y_tr)
    y_pred   = gscv.predict(X_te)
    acc      = accuracy_score(y_te, y_pred)
    bal_acc  = balanced_accuracy_score(y_te, y_pred)
    f1       = f1_score(y_te, y_pred, zero_division=0)
    report   = classification_report(y_te, y_pred, zero_division=0)

    summary = (
        f"GridSearchCV – KNN  (scoring=f1)\n"
        f"  cv_folds      : {n_splits}\n"
        f"  best_params   : {gscv.best_params_}\n"
        f"  best_cv_f1    : {gscv.best_score_:.4f}\n"
        f"  test_accuracy : {acc:.4f}\n"
        f"  bal. accuracy : {bal_acc:.4f}\n"
        f"  test_f1       : {f1:.4f}\n\n"
        f"{report}"
    )
    return {
        "y_pred": y_pred, "y_true": y_te,
        "best_params": gscv.best_params_,
        "best_score": gscv.best_score_,
        "accuracy": acc, "balanced_accuracy": bal_acc, "f1": f1,
        "_summary": summary,
    }


def pipeline_pruned_catch22(ds: AeonDataset) -> dict:
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
        VarianceThreshold(threshold=1e-6),   # removes exactly-zero AND near-zero (e.g. feat_05)
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


def pipeline_pr_threshold_sweep(ds: AeonDataset) -> dict:
    """
    Fits Catch22 + Balanced RF then sweeps the decision threshold from 0.05
    to 0.95 to find the operating point that maximises class-1 F1.

    Saves two extra CSVs:
      Results/Catalogue/aeon/current/pipeline_pr_threshold_sweep_discrete.csv  — per-threshold metrics
      Results/Catalogue/aeon/current/pipeline_pr_threshold_sweep_prcurve.csv   — continuous PR curve
    """
    import csv as _csv
    from aeon.transformations.collection.feature_based import Catch22
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (precision_recall_curve, average_precision_score,
                                 roc_auc_score, precision_score, recall_score,
                                 f1_score)
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import make_pipeline

    X_tr, X_te, y_tr, y_te = train_test_split(
        ds.X, ds.y, test_size=0.2, random_state=42, stratify=ds.y
    )

    pipe = make_pipeline(
        Catch22(replace_nans=True),
        RandomForestClassifier(n_estimators=200, random_state=42, class_weight="balanced"),
    )
    pipe.fit(X_tr, y_tr)
    probas = pipe.predict_proba(X_te)[:, 1]

    auc_roc = roc_auc_score(y_te, probas)
    auc_pr  = average_precision_score(y_te, probas)

    # ── Discrete threshold sweep ──────────────────────────────────────────────
    thresholds = np.linspace(0.05, 0.95, 19)
    sweep_rows = []
    for t in thresholds:
        y_t   = (probas >= t).astype(int)
        n_pos = int(y_t.sum())
        p = precision_score(y_te, y_t, zero_division=0)
        r = recall_score(y_te, y_t, zero_division=0)
        f = f1_score(y_te, y_t, zero_division=0)
        sweep_rows.append({
            "threshold":              round(float(t), 3),
            "precision":              round(float(p), 4),
            "recall":                 round(float(r), 4),
            "f1":                     round(float(f), 4),
            "n_predicted_interesting": n_pos,
        })

    best = max(sweep_rows, key=lambda row: row["f1"])

    # ── Continuous PR curve ───────────────────────────────────────────────────
    prec_c, rec_c, thr_c = precision_recall_curve(y_te, probas)

    # ── Save CSVs ─────────────────────────────────────────────────────────────
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    discrete_path = OUT_DIR / "pipeline_pr_threshold_sweep_discrete.csv"
    with open(discrete_path, "w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=sweep_rows[0].keys())
        writer.writeheader()
        writer.writerows(sweep_rows)

    prcurve_path = OUT_DIR / "pipeline_pr_threshold_sweep_prcurve.csv"
    with open(prcurve_path, "w", newline="") as fh:
        writer = _csv.writer(fh)
        writer.writerow(["precision", "recall", "threshold"])
        for p, r, t in zip(prec_c[:-1], rec_c[:-1], thr_c):
            writer.writerow([round(float(p), 4), round(float(r), 4), round(float(t), 4)])

    log.info("  Saved → %s", discrete_path.name)
    log.info("  Saved → %s", prcurve_path.name)

    # ── Summary ───────────────────────────────────────────────────────────────
    col = f"  {'thr':>5}  {'prec':>6}  {'rec':>6}  {'f1':>6}  {'n_pred':>6}"
    rows_fmt = [col, "  " + "─" * (len(col) - 2)]
    for row in sweep_rows:
        rows_fmt.append(
            f"  {row['threshold']:>5.2f}  {row['precision']:>6.4f}  "
            f"{row['recall']:>6.4f}  {row['f1']:>6.4f}  "
            f"{row['n_predicted_interesting']:>6}"
        )

    summary = "\n".join([
        "PR Threshold Sweep (Catch22 + Balanced RF, 200 trees)",
        f"  n_train       : {len(X_tr)}",
        f"  n_test        : {len(X_te)}",
        f"  AUC-ROC       : {auc_roc:.4f}",
        f"  AUC-PR        : {auc_pr:.4f}",
        f"  Best threshold: {best['threshold']:.2f}  "
        f"(prec={best['precision']:.4f}  rec={best['recall']:.4f}  "
        f"F1={best['f1']:.4f}  n_pred={best['n_predicted_interesting']})",
        "",
    ] + rows_fmt) + "\n"

    return {
        "probas": probas, "y_true": y_te,
        "auc_roc": auc_roc, "auc_pr": auc_pr,
        "best_threshold": best, "sweep": sweep_rows,
        "_summary": summary,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Execution framework
# ═══════════════════════════════════════════════════════════════════════════════

# Ordered list of all example functions to run
EXAMPLES = [
    detect_anomaly,
    segmentation,
    classifier_KN,
    regression_forecast,
    clustering_kmeans,
    sim_search,
    transformations,
    pipeline_v1,
    grid_search_KN,
    pipeline_pruned_catch22,
    pipeline_pr_threshold_sweep,
]


def run_example(fn, ds: AeonDataset) -> bool:
    """
    Execute one example function, persist its output, and return True on success.

    On failure: print a detailed traceback and return False.
    Never raises – the pipeline always continues to the next example.
    """
    name = fn.__name__
    log.info("\nRunning %s …", name)
    try:
        result  = fn(ds)
        summary = result.pop("_summary", None)
        save_output(name, result, summary)

        if summary:
            for line in summary.splitlines():
                log.info("  %s", line)
        log.info("%s  completed successfully.", name)
        return True

    except Exception:
        tb = traceback.format_exc()
        log.error("%s  failed:\n%s", name, textwrap.indent(tb, "    "))
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        err_path = OUT_DIR / f"{name}_error.txt"
        with open(err_path, "w") as fh:
            fh.write(tb)
        log.error("  Error saved → %s", err_path.name)
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    # ── Load dataset (fail fast if data is unavailable) ──────────────────────
    try:
        ds = load_dataset()
    except Exception:
        log.error(
            "Dataset loading failed – aborting.\n%s",
            textwrap.indent(traceback.format_exc(), "  "),
        )
        sys.exit(1)

    # ── Run all examples sequentially ────────────────────────────────────────
    results: list[tuple[str, bool]] = []
    for fn in EXAMPLES:
        ok = run_example(fn, ds)
        results.append((fn.__name__, ok))

    # ── Final summary ─────────────────────────────────────────────────────────
    n_total   = len(results)
    n_success = sum(ok for _, ok in results)
    n_failed  = n_total - n_success

    sep = "─" * 60
    log.info("\n%s", sep)
    log.info("Pipeline summary")
    log.info("  Total    : %d", n_total)
    log.info("  Succeeded: %d", n_success)
    log.info("  Failed   : %d", n_failed)
    log.info(sep)
    for fn_name, ok in results:
        status = "OK  " if ok else "FAIL"
        log.info("  [%s]  %s", status, fn_name)
    log.info(sep)

    # Persist the summary table alongside the per-example outputs
    summary_path = OUT_DIR / "pipeline_summary.txt"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as fh:
        fh.write(f"Total: {n_total}  Succeeded: {n_success}  Failed: {n_failed}\n\n")
        for fn_name, ok in results:
            fh.write(f"{'OK  ' if ok else 'FAIL'}  {fn_name}\n")
    log.info("Summary saved → %s", summary_path)


if __name__ == "__main__":
    main()
