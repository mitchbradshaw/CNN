"""
dendrogram_cluster.py
=====================
Two-stage pipeline for hierarchical (dendrogram) clustering of window matrix data.

  Stage 1 — preprocess_window_matrix()  : clean, validate, and z-score features
  Stage 2 — cluster_window_matrix()     : hierarchical linkage and cluster extraction

Window matrix context
---------------------
Each row = one 10-minute window of mycelium bio-electric potential data.
Each column = a statistical feature computed on that window (entropy, Catch22,
CNN/RF probabilities, SAX encodings, optional labels).
The DataFrame index is `start_idx` — the sample offset where each window begins.

What hierarchical clustering produces
--------------------------------------
The algorithm does NOT produce a fixed partitioning.  Instead it builds a
*linkage matrix* Z of shape (n-1, 4) — a complete merge history:

    Z[i] = [left, right, distance, new_size]

      left, right  — indices of the two items merged at step i.
                     Indices 0..n-1 are original windows (leaves).
                     Indices n..2n-2 are composite clusters born from earlier merges.
      distance     — how far apart the two items were when merged.
                     Interpretation depends on linkage method (see below).
      new_size     — number of original windows in the merged cluster.

The resulting dendrogram is a binary tree whose root represents the entire
dataset and whose leaves are individual windows.  Cutting the tree at a given
height h produces flat clusters: every subtree that is entirely below h becomes
one cluster.  ``fcluster(Z, t, criterion='distance')`` makes this cut;
``fcluster(Z, t, criterion='maxclust')`` instead cuts to produce exactly t clusters.

Linkage method comparison
--------------------------
  ward      — minimises the increase in total within-cluster variance at each merge.
              Produces compact, roughly equal-sized clusters.  REQUIRES Euclidean
              distance.  Best default for shape-diverse electrophysiological states.
  average   — merges based on mean pairwise distance between all member pairs
              (UPGMA).  More robust to outliers than ward; compatible with any metric.
  complete  — merges based on the *maximum* pairwise distance (diameter).
              Tends to produce tightly bounded clusters; sensitive to outliers.
  single    — merges based on the *minimum* pairwise distance (nearest-neighbour).
              Can produce long, chained clusters; rarely ideal for signal data.

Interpreting cluster membership in electrophysiology
------------------------------------------------------
A cluster = a group of 10-minute windows with statistically similar bio-electric
patterns across all retained features (entropy, CNN model outputs, Catch22 …).
Low intra-cluster distance ⟹ windows are in the same physiological state.
The dendrogram height at which two clusters merge ⟹ dissimilarity between states.
Recurring clusters across the recording ⟹ recurring physiological states.

Workflow:

prep          = preprocess_window_matrix(wm.df)
outlier_df    = find_outliers(prep, z_threshold=3.0)   # inspect before removing
prep_clean    = # remove flagged rows (as in testing.py)
cr_explore    = cluster_window_matrix(prep_clean, method="complete")
cluster_summary(cr_explore)   # read top-gaps to choose k
cr_final      = cluster_window_matrix(prep_clean, method="complete", n_clusters=best_k)


"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Union

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.transforms import blended_transform_factory
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="[dendrogram] %(levelname)s: %(message)s",
)
log = logging.getLogger("dendrogram")

# ---------------------------------------------------------------------------
# Known metadata / label columns that should never be treated as features.
# Extend this list if you add more label or prediction columns to the matrix.
# ---------------------------------------------------------------------------
_DEFAULT_METADATA_COLS: list[str] = [
    "category",          # string label ("interesting", "notinteresting", …)
    "fusion_pred_v1",    # discrete class index 0–13 (prediction, not a feature)
    "fusion_pred_v1_error",  # prediction residual — arguably a QC column, not a signal feature
]


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------
@dataclass
class PreprocessResult:
    """
    All outputs from the preprocessing stage, ready to be passed into clustering.

    Attributes
    ----------
    X_scaled : np.ndarray, shape (n_samples, n_features)
        Z-score-standardised feature matrix.  This is the input for clustering.
    df_features : pd.DataFrame
        Cleaned feature DataFrame in *original* (unscaled) units.
        Index preserved from the input window matrix.
    df_metadata : pd.DataFrame
        Metadata columns (labels, class indices, etc.) aligned by index.
    scaler : StandardScaler
        Fitted scaler.  Keep it so you can inverse-transform later.
    feature_names : list[str]
        Column names in the order they appear in X_scaled / df_features.
    removed_summary : dict[str, list[str]]
        Audit trail of which columns were removed at each stage.
    n_samples_dropped : int
        Number of rows removed (only non-zero when impute_strategy="drop").
    """

    X_scaled: np.ndarray
    df_features: pd.DataFrame
    df_metadata: pd.DataFrame
    scaler: StandardScaler
    feature_names: list[str]
    removed_summary: dict[str, list[str]] = field(default_factory=dict)
    n_samples_dropped: int = 0


# ===========================================================================
# Public entry point
# ===========================================================================

def preprocess_window_matrix(
    source: Union[pd.DataFrame, str],
    metadata_cols: list[str] | None = None,
    drop_near_constant: bool = True,
    near_constant_threshold: float = 0.01,
    nan_col_threshold: float = 0.5,
    impute_strategy: str = "median",
    warn_high_dim: int = 100,
) -> PreprocessResult:
    """
    Full preprocessing pipeline for a window matrix before hierarchical clustering.

    Parameters
    ----------
    source : pd.DataFrame or str
        Either the window matrix DataFrame (``wm.df``) or a path to a saved
        CSV file (``MATRICES/my_matrix.csv``).
    metadata_cols : list[str], optional
        Column names to treat as metadata rather than features.
        Defaults to ``_DEFAULT_METADATA_COLS``.  These columns are preserved
        in the returned ``df_metadata`` but excluded from clustering.
    drop_near_constant : bool
        If True, also remove columns whose normalised standard deviation
        (std / |mean|) is below ``near_constant_threshold``.  Near-constant
        features add almost no discriminative signal but inflate distances.
    near_constant_threshold : float
        Coefficient-of-variation threshold below which a column is considered
        near-constant.  Default 0.01 (1 % relative variation).
    nan_col_threshold : float
        Columns with a NaN fraction above this value are dropped entirely.
        Default 0.5 — drop columns that are more than 50 % missing.
    impute_strategy : {"median", "mean", "drop"}
        How to handle remaining NaNs after bad columns are removed.
        - ``"median"`` / ``"mean"``: impute each column with its median/mean.
          Preserves all rows.  Safe default for most cases.
        - ``"drop"``: remove any row that still contains a NaN.
          Use only when missingness is sparse and you can afford losing rows.

        Tradeoffs
        ~~~~~~~~~
        Imputation keeps sample count intact, which is good when rows are
        expensive (long recordings).  However, imputed values are synthetic
        and may slightly compress intra-cluster distances near the mean/median.
        Dropping rows is unbiased but can silently discard a large fraction of
        your data if missingness is correlated with a condition of interest.
    warn_high_dim : int
        Emit a warning if the number of retained features exceeds this value.
        High dimensionality degrades linkage quality (curse of dimensionality).

    Returns
    -------
    PreprocessResult
        Dataclass containing scaled matrix, clean DataFrame, metadata, scaler,
        feature names, and an audit trail of what was removed.

    Notes for future extensions
    ---------------------------
    * **PCA / dimensionality reduction**: call after this function on X_scaled.
      A rule of thumb: keep enough components to explain ≥ 90 % of variance.
    * **Correlation filtering**: drop one column from any pair with |r| > 0.95
      (e.g. ``df_features.corr()``).  Redundant features double-weight certain
      directions in Euclidean distance, which biases ward linkage.
    * **Feature selection**: if you have labels in ``df_metadata["category"]``,
      use ANOVA F-scores or mutual information to rank features before passing
      to the clusterer.
    """
    if metadata_cols is None:
        metadata_cols = _DEFAULT_METADATA_COLS

    removed_summary: dict[str, list[str]] = {}
    n_samples_dropped = 0

    # ------------------------------------------------------------------
    # 1. Load
    # ------------------------------------------------------------------
    df = _load_dataframe(source)
    log.info("Loaded matrix: %d windows × %d columns", *df.shape)

    # ------------------------------------------------------------------
    # 2. Separate metadata
    # ------------------------------------------------------------------
    df_features, df_metadata = _separate_metadata(df, metadata_cols)
    removed_summary["metadata_separated"] = list(df_metadata.columns)
    log.info(
        "Metadata columns separated (%d): %s",
        len(df_metadata.columns),
        list(df_metadata.columns),
    )

    # ------------------------------------------------------------------
    # 3. Drop non-numeric columns
    #    Why: hierarchical clustering is distance-based; string/object
    #    columns cannot be converted to Euclidean distances.  SAX columns
    #    (psax_windowed, csax_windowed, …) are stored as array objects and
    #    will be caught here.
    # ------------------------------------------------------------------
    df_features, dropped_nonnumeric = _remove_non_numeric(df_features)
    removed_summary["non_numeric"] = dropped_nonnumeric
    if dropped_nonnumeric:
        log.info("Dropped %d non-numeric column(s): %s", len(dropped_nonnumeric), dropped_nonnumeric)

    # ------------------------------------------------------------------
    # 4. Drop columns that are entirely NaN
    #    Why: a column that is 100 % NaN carries zero information and cannot
    #    be imputed in any meaningful way.
    # ------------------------------------------------------------------
    df_features, dropped_all_nan = _remove_all_nan_columns(df_features)
    removed_summary["all_nan"] = dropped_all_nan
    if dropped_all_nan:
        log.info("Dropped %d all-NaN column(s): %s", len(dropped_all_nan), dropped_all_nan)

    # ------------------------------------------------------------------
    # 5. Drop columns with excessive missingness
    #    Why: imputing a column that is 80 % NaN effectively fabricates most
    #    of its values; the imputed column is dominated by its own median and
    #    contributes almost nothing but noise.
    # ------------------------------------------------------------------
    df_features, dropped_nan_heavy = _remove_nan_heavy_columns(df_features, nan_col_threshold)
    removed_summary["nan_heavy"] = dropped_nan_heavy
    if dropped_nan_heavy:
        log.info(
            "Dropped %d column(s) with NaN fraction > %.0f%%: %s",
            len(dropped_nan_heavy),
            nan_col_threshold * 100,
            dropped_nan_heavy,
        )

    # ------------------------------------------------------------------
    # 6. Drop constant columns
    #    Why: a column with zero variance has a standard deviation of zero.
    #    StandardScaler would divide by zero, and the column contributes
    #    nothing to any distance metric.
    # ------------------------------------------------------------------
    df_features, dropped_constant = _remove_constant_columns(df_features)
    removed_summary["constant"] = dropped_constant
    if dropped_constant:
        log.info("Dropped %d constant column(s): %s", len(dropped_constant), dropped_constant)

    # ------------------------------------------------------------------
    # 7. (Optional) Drop near-constant columns
    #    Why: columns with almost no variation inflate the feature space
    #    while contributing negligible discriminative power.  They can also
    #    anchor clusters artificially around their single dominant value.
    # ------------------------------------------------------------------
    if drop_near_constant:
        df_features, dropped_near_constant = _remove_near_constant_columns(
            df_features, near_constant_threshold
        )
        removed_summary["near_constant"] = dropped_near_constant
        if dropped_near_constant:
            log.info(
                "Dropped %d near-constant column(s) (CV < %.3f): %s",
                len(dropped_near_constant),
                near_constant_threshold,
                dropped_near_constant,
            )

    # ------------------------------------------------------------------
    # 8. Handle remaining NaNs
    # ------------------------------------------------------------------
    df_features, n_samples_dropped = _handle_nans(df_features, impute_strategy)
    if n_samples_dropped:
        log.info("Dropped %d row(s) due to remaining NaNs (impute_strategy='drop')", n_samples_dropped)
        df_metadata = df_metadata.loc[df_features.index]

    # ------------------------------------------------------------------
    # 9. Validation: assert no NaNs remain
    # ------------------------------------------------------------------
    n_remaining_nans = df_features.isna().sum().sum()
    if n_remaining_nans > 0:
        raise ValueError(
            f"NaN values remain after preprocessing ({n_remaining_nans} cells). "
            "This should not happen — check impute_strategy or nan_col_threshold."
        )

    # ------------------------------------------------------------------
    # 10. Dimensionality warning
    # ------------------------------------------------------------------
    n_features = df_features.shape[1]
    if n_features > warn_high_dim:
        log.warning(
            "%d features retained — this is high-dimensional for hierarchical clustering. "
            "Consider PCA or correlation filtering before clustering to avoid the "
            "curse of dimensionality degrading linkage quality.",
            n_features,
        )

    # ------------------------------------------------------------------
    # 11. Standardise
    #     Why: features have very different scales (e.g. entropy ∈ [0,1],
    #     CNN probabilities ∈ [0,1], Catch22 features can be O(100)).
    #     Ward linkage and most other linkage methods use Euclidean distance,
    #     which is dominated by the largest-magnitude features unless we
    #     z-score each column to mean=0, std=1.
    # ------------------------------------------------------------------
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(df_features.values)
    log.info(
        "Standardised %d features across %d windows. Ready for clustering.",
        n_features,
        len(df_features),
    )

    # ------------------------------------------------------------------
    # 12. Summary report
    # ------------------------------------------------------------------
    _print_summary(df_features, removed_summary, n_samples_dropped)

    return PreprocessResult(
        X_scaled=X_scaled,
        df_features=df_features,
        df_metadata=df_metadata,
        scaler=scaler,
        feature_names=list(df_features.columns),
        removed_summary=removed_summary,
        n_samples_dropped=n_samples_dropped,
    )


# ===========================================================================
# Helper functions
# ===========================================================================

def _load_dataframe(source: Union[pd.DataFrame, str]) -> pd.DataFrame:
    """
    Accept a DataFrame or a CSV path and return a DataFrame.

    The window matrix CSV always has `start_idx` as either a named column or
    the first (unnamed) column.  Both cases are handled.
    """
    if isinstance(source, pd.DataFrame):
        df = source.copy()
    elif isinstance(source, str):
        df = pd.read_csv(source)
        # Restore start_idx as the index whether it was saved as a column or
        # as the unnamed first column that pandas creates with to_csv().
        if "start_idx" in df.columns:
            df = df.set_index("start_idx")
        elif df.columns[0] == "Unnamed: 0":
            df = df.rename(columns={"Unnamed: 0": "start_idx"}).set_index("start_idx")
    else:
        raise TypeError(
            f"source must be a pd.DataFrame or a CSV path string, got {type(source)}"
        )
    return df


def _separate_metadata(
    df: pd.DataFrame, metadata_cols: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split the DataFrame into features and metadata.

    Only columns that are both in `metadata_cols` AND present in `df` are moved.
    Silently skips any requested metadata column that is absent (no error).
    """
    present_meta = [c for c in metadata_cols if c in df.columns]
    df_meta = df[present_meta].copy()
    df_feat = df.drop(columns=present_meta)
    return df_feat, df_meta


def _remove_non_numeric(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Drop columns whose dtype is not numeric (int or float).

    In the window matrix this catches:
    - `category` (string labels) — should already be in metadata, but belt-and-braces
    - SAX columns that store Python list objects as strings when round-tripped via CSV
    """
    non_numeric = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
    return df.drop(columns=non_numeric), non_numeric


def _remove_all_nan_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Drop columns where every single value is NaN."""
    all_nan = [c for c in df.columns if df[c].isna().all()]
    return df.drop(columns=all_nan), all_nan


def _remove_nan_heavy_columns(
    df: pd.DataFrame, threshold: float
) -> tuple[pd.DataFrame, list[str]]:
    """Drop columns whose NaN fraction exceeds `threshold`."""
    nan_fractions = df.isna().mean()
    heavy = nan_fractions[nan_fractions > threshold].index.tolist()
    return df.drop(columns=heavy), heavy


def _remove_constant_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Drop columns with zero variance (std == 0).

    A constant column has no discriminative power and causes StandardScaler
    to raise a division-by-zero warning.
    """
    stds = df.std(ddof=0)
    constant = stds[stds == 0].index.tolist()
    return df.drop(columns=constant), constant


def _remove_near_constant_columns(
    df: pd.DataFrame, threshold: float
) -> tuple[pd.DataFrame, list[str]]:
    """
    Drop columns whose coefficient of variation (CV = std / |mean|) is below
    `threshold`, indicating negligible relative spread.

    CV is undefined when the mean is zero.  For zero-mean columns we fall back
    to comparing the plain std against `threshold * global_scale`, where
    `global_scale` is the median absolute value across all numeric cells.
    This avoids both false positives and false negatives near zero.
    """
    means = df.mean()
    stds = df.std(ddof=0)
    global_scale = df.abs().values.flatten()
    global_scale = float(np.nanmedian(global_scale[global_scale > 0])) or 1.0

    near_constant: list[str] = []
    for col in df.columns:
        m, s = means[col], stds[col]
        if abs(m) > 1e-12:
            cv = s / abs(m)
        else:
            cv = s / global_scale
        if cv < threshold:
            near_constant.append(col)

    return df.drop(columns=near_constant), near_constant


def _handle_nans(
    df: pd.DataFrame, strategy: str
) -> tuple[pd.DataFrame, int]:
    """
    Resolve any remaining NaNs.

    Returns the cleaned DataFrame and the number of rows dropped (0 unless
    strategy is "drop").
    """
    n_nan_cells = df.isna().sum().sum()
    if n_nan_cells == 0:
        return df, 0

    log.info("%d NaN cell(s) remain across %d column(s) — applying strategy='%s'",
             n_nan_cells, df.isna().any(axis=0).sum(), strategy)

    if strategy in ("median", "mean"):
        imputer = SimpleImputer(strategy=strategy)
        X_imp = imputer.fit_transform(df.values)
        return pd.DataFrame(X_imp, index=df.index, columns=df.columns), 0

    elif strategy == "drop":
        n_before = len(df)
        df_clean = df.dropna()
        n_dropped = n_before - len(df_clean)
        return df_clean, n_dropped

    else:
        raise ValueError(
            f"impute_strategy must be 'median', 'mean', or 'drop', got '{strategy}'"
        )


def _print_summary(
    df_features: pd.DataFrame,
    removed_summary: dict[str, list[str]],
    n_samples_dropped: int,
) -> None:
    """Print a human-readable audit table to stdout."""
    total_removed = sum(len(v) for v in removed_summary.values())
    log.info("=" * 60)
    log.info("Preprocessing summary")
    log.info("-" * 60)
    stage_labels = {
        "metadata_separated": "Metadata separated",
        "non_numeric":        "Non-numeric dropped",
        "all_nan":            "All-NaN dropped",
        "nan_heavy":          "NaN-heavy dropped",
        "constant":           "Constant dropped",
        "near_constant":      "Near-constant dropped",
    }
    for key, label in stage_labels.items():
        cols = removed_summary.get(key, [])
        log.info("  %-28s %3d column(s)", label + ":", len(cols))
    log.info("  %-28s %3d column(s)", "Total columns removed:", total_removed)
    log.info("  %-28s %3d row(s)", "Rows removed (NaN drop):", n_samples_dropped)
    log.info("-" * 60)
    log.info(
        "Final feature matrix: %d windows × %d features",
        df_features.shape[0],
        df_features.shape[1],
    )
    log.info("=" * 60)


# ===========================================================================
# Plotting constants
# ===========================================================================

# Feature groups in display order: model outputs first, raw statistics second.
# Each entry is (display_label, match_function).  A feature is assigned to the
# first group whose match function returns True.
_GROUP_RULES: list[tuple[str, object]] = [
    ("CNN (base)",       lambda n: n.startswith("cnn_p_") and not any(k in n for k in ("GASF", "GADF", "recurrence", "fusion"))),
    ("CNN (GASF)",       lambda n: "GASF" in n),
    ("CNN (GADF)",       lambda n: "GADF" in n),
    ("CNN (recurrence)", lambda n: "recurrence" in n),
    ("CNN (fusion)",     lambda n: "fusion" in n and n.startswith("cnn_p_")),
    ("Random Forest",    lambda n: n.startswith("rf_")),
    ("Entropy",          lambda n: "entropy" in n.lower()),
    ("Catch22",          lambda n: n.startswith("catch22_")),
]

# Colors for the optional category overlay strip
_CATEGORY_PALETTE: dict[str, list[float]] = {
    "interesting":    [0.87, 0.42, 0.42, 1.0],   # coral red
    "notinteresting": [0.33, 0.53, 0.80, 1.0],   # steel blue
    "flag":           [0.94, 0.65, 0.20, 1.0],   # amber
}
_CATEGORY_FALLBACK: list[float] = [0.60, 0.60, 0.60, 1.0]  # gray for unlabeled


# ===========================================================================
# Public plotting function
# ===========================================================================

def plot_preprocessed_heatmap(
    result: PreprocessResult,
    fs: float | None = None,
    figsize: tuple[float, float] = (16, 8),
    cmap: str = "RdBu_r",
    clip_sigma: float = 3.0,
    show_category_bar: bool = True,
) -> plt.Figure:
    """
    Heatmap of the preprocessed window matrix — features on the y-axis,
    windows (time) on the x-axis.

    Features are grouped by logical category (CNN outputs, entropy, Catch22,
    …) with labelled separators between groups.  All values shown are
    z-scored so the colour scale is comparable across features.

    Parameters
    ----------
    result : PreprocessResult
        Output of ``preprocess_window_matrix``.
    fs : float, optional
        Sampling frequency in Hz.  When provided the x-axis is labelled in
        hours; otherwise window index is used.
    figsize : tuple
        Figure size in inches (width, height).
    cmap : str
        Matplotlib colourmap name.  A diverging map centred at 0 (e.g.
        ``"RdBu_r"``, ``"coolwarm"``) works best for z-scored data.
    clip_sigma : float
        Symmetric colour-scale limit in standard deviations.  Values beyond
        ±clip_sigma are clipped to the end colours.  Default 3.0.
    show_category_bar : bool
        If True and the metadata contains a ``category`` column, draw a thin
        colour strip above the heatmap encoding window labels.

    Returns
    -------
    plt.Figure
    """
    # ------------------------------------------------------------------
    # 1. Sort features into logical groups
    # ------------------------------------------------------------------
    ordered_features, group_info = _group_and_sort_features(result.feature_names)
    feat_idx = [result.feature_names.index(f) for f in ordered_features]

    # Heatmap matrix: rows=features, cols=windows (time)
    Z = result.X_scaled[:, feat_idx].T   # shape (n_features, n_windows)
    n_features, n_windows = Z.shape

    # ------------------------------------------------------------------
    # 2. Time-axis ticks
    # ------------------------------------------------------------------
    start_indices = result.df_features.index.values
    x_tick_pos, x_tick_labels = _make_time_ticks(start_indices, fs, n_ticks=10)

    # ------------------------------------------------------------------
    # 3. Figure layout
    # ------------------------------------------------------------------
    has_cat = (
        show_category_bar
        and "category" in result.df_metadata.columns
        and result.df_metadata["category"].notna().any()
    )

    if has_cat:
        fig, (ax_cat, ax_heat) = plt.subplots(
            2, 1, figsize=figsize,
            gridspec_kw={"height_ratios": [1, 14], "hspace": 0.02},
        )
    else:
        fig, ax_heat = plt.subplots(1, 1, figsize=figsize)
        ax_cat = None

    fig.patch.set_facecolor("#1c1c1c")
    for ax in ([ax_cat, ax_heat] if ax_cat is not None else [ax_heat]):
        ax.set_facecolor("#1c1c1c")

    # ------------------------------------------------------------------
    # 4. Category bar
    # ------------------------------------------------------------------
    if ax_cat is not None:
        _draw_category_bar(ax_cat, result.df_metadata["category"], x_tick_pos, x_tick_labels)

    # ------------------------------------------------------------------
    # 5. Main heatmap
    # ------------------------------------------------------------------
    im = ax_heat.imshow(
        Z,
        aspect="auto",
        cmap=cmap,
        vmin=-clip_sigma,
        vmax=clip_sigma,
        interpolation="nearest",
        origin="upper",
    )

    # ------------------------------------------------------------------
    # 6. Y-axis: feature names on the right, group labels + separators left
    # ------------------------------------------------------------------
    short_names = _shorten_feature_names(ordered_features)
    ax_heat.yaxis.tick_right()
    ax_heat.yaxis.set_label_position("right")
    ax_heat.set_yticks(range(n_features))
    ax_heat.set_yticklabels(short_names, fontsize=6.5, color="#dddddd")
    ax_heat.tick_params(axis="y", length=0, pad=4)

    _draw_group_labels_and_separators(ax_heat, group_info, n_features)

    # ------------------------------------------------------------------
    # 7. X-axis
    # ------------------------------------------------------------------
    ax_heat.set_xticks(x_tick_pos)
    ax_heat.set_xticklabels(x_tick_labels, fontsize=8, rotation=30, ha="right", color="#dddddd")
    ax_heat.tick_params(axis="x", colors="#dddddd", length=3)
    xlabel = "Time (hours)" if fs is not None else "Window index"
    ax_heat.set_xlabel(xlabel, fontsize=9, color="#dddddd", labelpad=6)

    # ------------------------------------------------------------------
    # 8. Title
    # ------------------------------------------------------------------
    title_ax = ax_cat if ax_cat is not None else ax_heat
    title_ax.set_title(
        "Window matrix feature heatmap  (z-scored, clipped ±{:.0f}σ)".format(clip_sigma),
        fontsize=11, color="#eeeeee", pad=8,
    )

    # ------------------------------------------------------------------
    # 9. Colourbar
    # ------------------------------------------------------------------
    cbar = fig.colorbar(im, ax=ax_heat, orientation="vertical", fraction=0.018, pad=0.12)
    cbar.set_label("z-score", fontsize=8, color="#dddddd")
    cbar.ax.yaxis.set_tick_params(colors="#dddddd", labelsize=7)
    cbar.outline.set_edgecolor("#555555")

    plt.tight_layout(rect=[0.10, 0.0, 1.0, 1.0])   # leave left margin for group labels
    plt.show()
    return fig


# ===========================================================================
# Plotting helpers
# ===========================================================================

def _group_and_sort_features(
    feature_names: list[str],
) -> tuple[list[str], list[tuple[str, int, int]]]:
    """
    Assign each feature to the first matching group in ``_GROUP_RULES``,
    then concatenate groups in rule order.

    Returns
    -------
    ordered_features : list[str]
        Feature names in group-sorted order.
    group_info : list[(label, start_row, end_row)]
        Inclusive-exclusive row spans for each non-empty group.
    """
    buckets: dict[str, list[str]] = {label: [] for label, _ in _GROUP_RULES}
    buckets["Other"] = []

    for name in feature_names:
        placed = False
        for label, rule in _GROUP_RULES:
            if rule(name):
                buckets[label].append(name)
                placed = True
                break
        if not placed:
            buckets["Other"].append(name)

    ordered: list[str] = []
    group_info: list[tuple[str, int, int]] = []

    all_group_names = [label for label, _ in _GROUP_RULES] + ["Other"]
    for label in all_group_names:
        cols = buckets[label]
        if cols:
            start = len(ordered)
            ordered.extend(cols)
            group_info.append((label, start, len(ordered)))

    return ordered, group_info


def _make_time_ticks(
    start_indices: np.ndarray,
    fs: float | None,
    n_ticks: int = 10,
) -> tuple[list[int], list[str]]:
    """Return ~n_ticks evenly spaced tick positions and their formatted labels."""
    n = len(start_indices)
    positions = np.linspace(0, n - 1, min(n_ticks, n), dtype=int).tolist()
    if fs is not None:
        labels = [f"{start_indices[i] / (fs * 3600):.1f}h" for i in positions]
    else:
        labels = [str(i) for i in positions]
    return positions, labels


def _shorten_feature_names(names: list[str]) -> list[str]:
    """Strip well-known prefixes so tick labels are concise."""
    prefixes = ("catch22_", "cnn_p_", "rf_p_")
    result = []
    for name in names:
        for prefix in prefixes:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        result.append(name)
    return result


def _draw_group_labels_and_separators(
    ax: plt.Axes,
    group_info: list[tuple[str, int, int]],
    n_features: int,
) -> None:
    """
    Draw white horizontal separator lines between feature groups and place
    group name labels to the left of the axes in data-y / axes-x coordinates.
    """
    # Blended transform: x in axes fraction, y in data coordinates.
    trans = blended_transform_factory(ax.transAxes, ax.transData)

    for i, (label, start, end) in enumerate(group_info):
        # Separator line (skip before the first group)
        if start > 0:
            ax.axhline(start - 0.5, color="#ffffff", linewidth=0.8, alpha=0.4, zorder=3)

        # Group label at the vertical midpoint of the group
        mid = (start + end - 1) / 2.0
        ax.text(
            -0.01, mid,
            label,
            transform=trans,
            ha="right", va="center",
            fontsize=7.5, fontweight="bold",
            color="#cccccc",
            clip_on=False,
        )


def _draw_category_bar(
    ax: plt.Axes,
    category_series: pd.Series,
    x_tick_pos: list[int],
    x_tick_labels: list[str],
) -> None:
    """
    Draw a 1-row colour image encoding per-window category labels.

    Each window gets a coloured pixel: coral=interesting, blue=notinteresting,
    amber=flag, grey=unlabeled/unknown.
    """
    values = category_series.values
    n = len(values)
    img = np.zeros((1, n, 4), dtype=float)
    for i, val in enumerate(values):
        img[0, i] = _CATEGORY_PALETTE.get(str(val).lower(), _CATEGORY_FALLBACK)

    ax.imshow(img, aspect="auto", interpolation="nearest")
    ax.set_xticks([])
    ax.set_yticks([])

    # Legend patches
    present_cats = {str(v).lower() for v in values if pd.notna(v)}
    legend_items = [
        (k, _CATEGORY_PALETTE[k]) for k in ("interesting", "notinteresting", "flag")
        if k in present_cats
    ]
    if any(str(v).lower() not in _CATEGORY_PALETTE for v in values if pd.notna(v)):
        legend_items.append(("unlabeled", _CATEGORY_FALLBACK))

    handles = [Patch(facecolor=color, label=label) for label, color in legend_items]
    ax.legend(
        handles=handles,
        loc="upper left", bbox_to_anchor=(0.0, 1.0),
        fontsize=7, ncol=len(handles),
        framealpha=0.5, handlelength=1.0, borderpad=0.3,
        labelcolor="#eeeeee", facecolor="#333333", edgecolor="#555555",
    )


# ===========================================================================
# Stage 2 — hierarchical clustering
# ===========================================================================

# Linkage methods that only work with Euclidean distance.
# scipy silently accepts other metrics but produces incorrect results.
_EUCLIDEAN_ONLY_METHODS: frozenset[str] = frozenset({"ward", "centroid", "median"})

# Above this many windows, computing the full n×n distance matrix becomes
# memory-intensive (1 k windows → ~4 MB, 10 k → ~400 MB, 30 k → ~3.6 GB).
_PDIST_MEMORY_WARN_MB: float = 400.0

# Above this, skip optimal_leaf_ordering (O(n² log n) time).
_OPTIMAL_ORDER_MAX_N: int = 2000


@dataclass
class ClusterResult:
    """
    All outputs from ``cluster_window_matrix``, suitable for downstream
    visualisation, analysis, and export.

    Attributes
    ----------
    linkage_matrix : np.ndarray, shape (n-1, 4)
        Scipy linkage matrix.  Row i encodes the i-th merge:
        [left_index, right_index, merge_distance, new_cluster_size].
        Indices 0..n-1 are original windows; indices n..2n-2 are composite
        clusters created in earlier merges.
    labels : np.ndarray or None, shape (n,)
        Integer cluster assignment for each window (1-indexed).
        None if no cut was requested (n_clusters and distance_cutoff both absent).
    df_membership : pd.DataFrame or None
        Table indexed by start_idx with a 'cluster' column and all metadata
        columns from the preprocessing result.  None if labels is None.
    leaf_order : np.ndarray, shape (n,)
        Permutation of 0..n-1 giving the optimal left-to-right leaf order
        that minimises the sum of adjacent-leaf distances.  Use this to
        reorder rows of X_scaled or df_features for heatmap plotting so
        that similar windows are adjacent.
    cluster_counts : dict[int, int]
        Mapping cluster_id → number of windows.  Empty if labels is None.
    cophenetic_r : float
        Cophenetic correlation coefficient — how well the dendrogram
        preserves the original pairwise distances.  Values above 0.75
        are acceptable; above 0.85 is good.
    silhouette : float or None
        Mean silhouette score across all windows (sklearn).  Ranges from
        -1 (wrong cluster) to +1 (dense, well-separated clusters).
        None if labels is None or n is too large for efficient computation.
    n_windows : int
        Number of original windows (leaves in the dendrogram).
    n_features : int
        Number of features used for clustering.
    linkage_method : str
    distance_metric : str
    start_indices : np.ndarray
        start_idx values in the same row order as the linkage matrix leaves,
        giving you the mapping leaf_index → start_idx.
    diagnostics : dict
        Miscellaneous diagnostics: n_duplicate_rows, memory_mb,
        optimal_ordering_performed, etc.
    """

    linkage_matrix: np.ndarray
    labels: np.ndarray | None
    df_membership: pd.DataFrame | None
    leaf_order: np.ndarray
    cluster_counts: dict[int, int]
    cophenetic_r: float
    silhouette: float | None
    n_windows: int
    n_features: int
    linkage_method: str
    distance_metric: str
    start_indices: np.ndarray
    diagnostics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public clustering function
# ---------------------------------------------------------------------------

def cluster_window_matrix(
    result: PreprocessResult,
    method: str = "ward",
    metric: str = "euclidean",
    n_clusters: int | None = None,
    distance_cutoff: float | None = None,
    optimal_ordering: bool = True,
) -> ClusterResult:
    """
    Perform hierarchical agglomerative clustering on a preprocessed window matrix.

    Parameters
    ----------
    result : PreprocessResult
        Output of ``preprocess_window_matrix``.  ``result.X_scaled`` is used
        as the feature matrix.
    method : str
        Linkage method passed to ``scipy.cluster.hierarchy.linkage``.
        Options: ``"ward"`` (default), ``"average"``, ``"complete"``, ``"single"``.
        Ward linkage is recommended for electrophysiological data because it
        minimises within-cluster variance at each merge, producing compact and
        well-separated clusters.
    metric : str
        Distance metric.  ``"euclidean"`` is required for ``method="ward"``.
        Any metric accepted by ``scipy.spatial.distance.pdist`` is valid for
        other linkage methods (e.g. ``"cosine"``, ``"correlation"``).
    n_clusters : int, optional
        If given, cut the dendrogram to produce exactly this many flat clusters.
        Mutually exclusive with ``distance_cutoff``.
    distance_cutoff : float, optional
        If given, cut the dendrogram at this linkage distance.  All subtrees
        entirely below the cut become one cluster.  Typically chosen by
        inspecting the dendrogram visually (look for a large gap between
        consecutive merge heights).
    optimal_ordering : bool
        If True, reorder leaves to minimise the sum of adjacent-leaf distances.
        Makes dendrograms and heatmaps much more interpretable.
        Automatically disabled for n > 2000 with a warning (O(n² log n) cost).

    Returns
    -------
    ClusterResult
    """
    X = result.X_scaled
    n, p = X.shape
    start_indices = result.df_features.index.values

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    _validate_linkage_metric(method, metric)
    _warn_high_dimensionality(n, p)

    n_dupes = _detect_duplicate_rows(X)
    if n_dupes > 0:
        log.warning(
            "%d duplicate row(s) detected (identical feature vectors). "
            "These windows will have distance=0 and will always merge first in "
            "single/complete/average linkage, which can distort the dendrogram.",
            n_dupes,
        )

    if n_clusters is not None and distance_cutoff is not None:
        raise ValueError("Provide at most one of n_clusters or distance_cutoff, not both.")

    # ------------------------------------------------------------------
    # Memory estimate for pairwise distance matrix
    # ------------------------------------------------------------------
    memory_mb = n * (n - 1) / 2 * 8 / (1024 ** 2)
    if memory_mb > _PDIST_MEMORY_WARN_MB:
        log.warning(
            "Computing pairwise distances for %d windows requires ~%.0f MB. "
            "Consider applying PCA first to reduce dimensionality, or subsample.",
            n, memory_mb,
        )

    # ------------------------------------------------------------------
    # Pairwise condensed distance matrix
    # Computed once; reused for cophenet, optimal ordering, and non-ward linkage.
    # ------------------------------------------------------------------
    log.info("Computing pairwise %s distances for %d windows × %d features …", metric, n, p)
    dist_condensed = ssd.pdist(X, metric=metric)

    # ------------------------------------------------------------------
    # Linkage matrix
    # Ward is passed the raw X for better numerical stability (scipy uses
    # the Lance–Williams update formula internally, not explicit distances).
    # All other methods receive the pre-computed condensed distance matrix.
    # ------------------------------------------------------------------
    log.info("Computing '%s' linkage …", method)
    if method == "ward":
        Z = sch.linkage(X, method="ward", metric="euclidean")
    else:
        Z = sch.linkage(dist_condensed, method=method)

    # ------------------------------------------------------------------
    # Cophenetic correlation
    # Measures how well the dendrogram preserves pairwise distances.
    # c close to 1 means the tree is a faithful representation of the data.
    # ------------------------------------------------------------------
    c, _ = sch.cophenet(Z, dist_condensed)
    log.info("Cophenetic correlation: %.4f", c)
    if c < 0.75:
        log.warning(
            "Low cophenetic correlation (%.3f). The dendrogram may not faithfully "
            "represent the pairwise distances.  Consider a different linkage method "
            "or applying PCA before clustering.", c,
        )

    # ------------------------------------------------------------------
    # Optimal leaf ordering
    # Reorders leaves to minimise the sum of adjacent-leaf distances, making
    # the dendrogram and any heatmap reordering visually coherent.
    # ------------------------------------------------------------------
    do_optimal = optimal_ordering
    if do_optimal and n > _OPTIMAL_ORDER_MAX_N:
        log.warning(
            "Skipping optimal leaf ordering: n=%d exceeds threshold %d (O(n² log n) cost). "
            "Pass optimal_ordering=False to silence this warning.",
            n, _OPTIMAL_ORDER_MAX_N,
        )
        do_optimal = False

    if do_optimal:
        log.info("Computing optimal leaf ordering …")
        Z_ordered = sch.optimal_leaf_ordering(Z, dist_condensed)
        leaf_order = sch.leaves_list(Z_ordered)
    else:
        leaf_order = sch.leaves_list(Z)

    # ------------------------------------------------------------------
    # Cluster label extraction (flat clustering)
    # fcluster cuts the dendrogram to produce a 1-D array of cluster IDs.
    # Labels are 1-indexed integers.
    # ------------------------------------------------------------------
    labels: np.ndarray | None = None
    df_membership: pd.DataFrame | None = None
    cluster_counts: dict[int, int] = {}
    sil: float | None = None

    if n_clusters is not None:
        log.info("Cutting dendrogram into %d clusters …", n_clusters)
        labels = sch.fcluster(Z, t=n_clusters, criterion="maxclust")
    elif distance_cutoff is not None:
        log.info("Cutting dendrogram at distance %.4f …", distance_cutoff)
        labels = sch.fcluster(Z, t=distance_cutoff, criterion="distance")

    if labels is not None:
        unique, counts = np.unique(labels, return_counts=True)
        cluster_counts = dict(zip(unique.tolist(), counts.tolist()))
        n_found = len(cluster_counts)
        log.info(
            "Clusters found: %d  |  sizes: %s",
            n_found,
            {k: v for k, v in sorted(cluster_counts.items())},
        )

        # Chaining detection: average linkage can degenerate into one large
        # cluster with singletons peeled off one by one ("star" topology).
        # This is the expected symptom when outliers dominate the merge order.
        _check_cluster_imbalance(cluster_counts, n, method)

        # Silhouette score — skip for very large n (O(n²) memory)
        if memory_mb <= _PDIST_MEMORY_WARN_MB and n_found > 1:
            dist_sq = ssd.squareform(dist_condensed)
            sil = float(silhouette_score(dist_sq, labels, metric="precomputed"))
            log.info("Mean silhouette score: %.4f", sil)
        elif n_found <= 1:
            log.info("Silhouette score not computed: only 1 cluster.")
        else:
            log.info("Silhouette score skipped: distance matrix too large (%.0f MB).", memory_mb)

        # Membership table: start_idx -> cluster [+ metadata]
        df_membership = pd.DataFrame(
            {"cluster": labels},
            index=pd.Index(start_indices, name="start_idx"),
        )
        if not result.df_metadata.empty:
            df_membership = df_membership.join(result.df_metadata)

    # ------------------------------------------------------------------
    # Merge statistics — useful for choosing a distance cutoff
    # ------------------------------------------------------------------
    merge_distances = Z[:, 2]
    gaps = np.diff(merge_distances)
    top_gap_idx = int(np.argmax(gaps))   # index of the largest jump
    log.info(
        "Largest merge-distance gap: %.4f  (between merge %d and %d, "
        "heights %.4f -> %.4f).  This gap often indicates the natural "
        "number of clusters.",
        gaps[top_gap_idx],
        top_gap_idx, top_gap_idx + 1,
        merge_distances[top_gap_idx], merge_distances[top_gap_idx + 1],
    )

    # Top-5 gaps: each entry is (k_if_cut_here, gap_size, height_before, height_after)
    top5_idx = np.argsort(gaps)[::-1][:5]
    top_gaps = [
        (n - (int(i) + 1), float(gaps[i]), float(merge_distances[i]), float(merge_distances[i + 1]))
        for i in sorted(top5_idx)          # sort by k (ascending) so output reads naturally
    ]
    top_gaps.sort(key=lambda x: -x[1])    # re-sort by gap size descending for display

    diagnostics = {
        "n_duplicate_rows": n_dupes,
        "memory_mb": round(memory_mb, 2),
        "optimal_ordering_performed": do_optimal,
        "merge_distances_min": float(merge_distances.min()),
        "merge_distances_max": float(merge_distances.max()),
        "merge_distances_mean": float(merge_distances.mean()),
        "largest_gap_idx": top_gap_idx,
        "largest_gap_value": float(gaps[top_gap_idx]),
        "suggested_n_clusters": _suggest_n_clusters(Z),
        "top_gaps": top_gaps,
    }

    log.info(
        "Clustering complete.  %d windows, %d features, method='%s', metric='%s'.",
        n, p, method, metric,
    )

    return ClusterResult(
        linkage_matrix=Z,
        labels=labels,
        df_membership=df_membership,
        leaf_order=leaf_order,
        cluster_counts=cluster_counts,
        cophenetic_r=float(c),
        silhouette=sil,
        n_windows=n,
        n_features=p,
        linkage_method=method,
        distance_metric=metric,
        start_indices=start_indices,
        diagnostics=diagnostics,
    )


# ===========================================================================
# Clustering validation helpers
# ===========================================================================

def _validate_linkage_metric(method: str, metric: str) -> None:
    """Raise ValueError if the method/metric combination is incompatible."""
    if method in _EUCLIDEAN_ONLY_METHODS and metric != "euclidean":
        raise ValueError(
            f"Linkage method '{method}' requires Euclidean distance, but "
            f"metric='{metric}' was requested.  Either set metric='euclidean' "
            "or switch to method='average', 'complete', or 'single'."
        )


def _warn_high_dimensionality(n: int, p: int) -> None:
    """
    Warn when p is large relative to n.

    In high-dimensional spaces, Euclidean distances concentrate — all
    pairwise distances become nearly equal, making it hard to discriminate
    between similar and dissimilar windows.  This is the curse of dimensionality.
    A rough guideline: prefer p < n / 5 before clustering.
    """
    if p >= n:
        log.warning(
            "Feature count (%d) ≥ window count (%d).  In this regime Euclidean "
            "distances become unreliable (curse of dimensionality).  Consider "
            "applying PCA or correlation filtering first.", p, n,
        )
    elif p > n / 5:
        log.warning(
            "Feature count (%d) is high relative to window count (%d).  "
            "Consider PCA to reduce to ~%d dimensions before clustering.",
            p, n, max(2, n // 10),
        )


def _detect_duplicate_rows(X: np.ndarray) -> int:
    """Return the number of windows whose feature vector is identical to another."""
    return int(pd.DataFrame(X).duplicated().sum())


def _suggest_n_clusters(Z: np.ndarray) -> int:
    """
    Heuristic: find the largest gap between consecutive merge distances and
    return the number of clusters that would result from cutting *just before*
    that gap.

    Derivation
    ----------
    Z has n-1 rows (one per merge).  After performing the first k merges
    (rows 0..k-1), we have n-k clusters remaining.  If the largest gap is
    between row i and row i+1 (gaps[i] is maximal), we cut after row i,
    leaving n - (i+1) clusters.

    This mirrors the visual "longest vertical branch a horizontal line would
    cross" inspection on a dendrogram.
    """
    n = Z.shape[0] + 1          # n_windows = n_merges + 1
    gaps = np.diff(Z[:, 2])
    gap_idx = int(np.argmax(gaps))
    return n - (gap_idx + 1)


def _check_cluster_imbalance(
    cluster_counts: dict[int, int],
    n: int,
    method: str,
) -> None:
    """
    Warn when the cluster size distribution suggests chaining or outlier-dominated
    structure rather than genuine multi-cluster partitioning.

    Chaining signature: one cluster holds >80% of windows while the remaining
    clusters are singletons or very small.  This commonly occurs with average
    linkage when the dataset contains a few extreme outliers — they are peeled
    off one by one rather than allowing the main body to subdivide.

    Recommended remedies
    --------------------
    1. Use method='complete' — forms compact, diameter-bounded clusters and
       does not chain.
    2. Use method='ward' — minimises within-cluster variance; also avoids
       chaining but requires Euclidean distance and is sensitive to outliers
       inside the main body.
    3. Call find_outliers() to identify the extreme windows, optionally exclude
       them from the feature matrix, and re-cluster the remaining windows.
    """
    sizes = sorted(cluster_counts.values(), reverse=True)
    largest_frac = sizes[0] / n
    n_singletons = sum(1 for s in sizes if s == 1)

    if largest_frac > 0.80 and n_singletons >= len(sizes) - 1:
        log.warning(
            "Chaining detected: the largest cluster holds %d/%d windows (%.0f%%) "
            "and %d/%d other clusters are singletons. "
            "This is typical of average linkage with outliers — the main body "
            "is never subdivided. "
            "Try method='complete' for balanced clusters, or call find_outliers() "
            "to identify and optionally remove extreme windows before re-clustering.",
            sizes[0], n, largest_frac * 100,
            n_singletons, len(sizes) - 1,
        )


# ===========================================================================
# Post-clustering analysis helpers
# ===========================================================================


def find_outliers(
    preprocess_result: PreprocessResult,
    z_threshold: float = 3.0,
) -> pd.DataFrame:
    """
    Identify windows that are unusually far from the dataset centroid in
    z-score feature space.

    The Mahalanobis-like distance used here is the Euclidean distance in
    the already-standardised (z-scored) feature space, divided by
    sqrt(n_features) so the scale is comparable across datasets of different
    dimensionality.  Windows beyond ``z_threshold`` standard deviations of
    this normalised distance are flagged as outliers.

    Parameters
    ----------
    preprocess_result : PreprocessResult
    z_threshold : float
        Number of standard deviations above the mean normalised distance
        at which a window is considered an outlier.  Default 3.0.

    Returns
    -------
    pd.DataFrame indexed by start_idx, sorted by distance descending.
    Columns: norm_distance, z_score, is_outlier.
    """
    X = preprocess_result.X_scaled
    p = X.shape[1]
    centroid = X.mean(axis=0)
    raw_dists = np.linalg.norm(X - centroid, axis=1)
    norm_dists = raw_dists / np.sqrt(p)     # scale-free: expected ~1 for random normal data

    mean_d = norm_dists.mean()
    std_d  = norm_dists.std(ddof=1)
    z_scores = (norm_dists - mean_d) / std_d

    df = pd.DataFrame(
        {
            "norm_distance": norm_dists,
            "z_score":       z_scores,
            "is_outlier":    z_scores > z_threshold,
        },
        index=pd.Index(preprocess_result.df_features.index, name="start_idx"),
    )
    n_out = df["is_outlier"].sum()
    log.info(
        "Outlier detection (threshold=%.1f sigma): %d/%d windows flagged.",
        z_threshold, n_out, len(df),
    )
    return df.sort_values("norm_distance", ascending=False)

def get_cluster_members(
    cluster_result: ClusterResult,
    cluster_id: int,
    preprocess_result: PreprocessResult,
) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Return all windows assigned to a given cluster.

    Parameters
    ----------
    cluster_result : ClusterResult
    cluster_id : int
        1-indexed cluster label (as in ClusterResult.labels).
    preprocess_result : PreprocessResult

    Returns
    -------
    df_members : pd.DataFrame
        Subset of df_features (unscaled) for windows in this cluster.
        Index is start_idx.
    X_members : np.ndarray, shape (k, n_features)
        Corresponding rows of X_scaled.
    """
    if cluster_result.labels is None:
        raise ValueError("No cluster labels — run cluster_window_matrix with n_clusters or distance_cutoff.")

    mask = cluster_result.labels == cluster_id
    if not mask.any():
        raise ValueError(f"Cluster {cluster_id} not found.  Available: {sorted(cluster_result.cluster_counts)}")

    df_members = preprocess_result.df_features.iloc[mask]
    X_members = preprocess_result.X_scaled[mask]
    return df_members, X_members


def get_cluster_centroid(
    cluster_result: ClusterResult,
    cluster_id: int,
    preprocess_result: PreprocessResult,
) -> pd.Series:
    """
    Return the centroid (mean feature vector) of a cluster.

    The centroid is computed in z-score space and then inverse-transformed
    back to original units, so the values are directly interpretable.

    Returns
    -------
    pd.Series indexed by feature name, values in original (unscaled) units.
    """
    _, X_members = get_cluster_members(cluster_result, cluster_id, preprocess_result)
    centroid_scaled = X_members.mean(axis=0)
    centroid_original = preprocess_result.scaler.inverse_transform(centroid_scaled.reshape(1, -1))[0]
    return pd.Series(centroid_original, index=preprocess_result.feature_names, name=f"cluster_{cluster_id}_centroid")


def get_all_centroids(
    cluster_result: ClusterResult,
    preprocess_result: PreprocessResult,
) -> pd.DataFrame:
    """
    Return a DataFrame of centroids for every cluster, one row per cluster.

    Rows are indexed by cluster_id; columns are feature names in original units.
    Useful for comparing what distinguishes each cluster from the others.
    """
    rows = []
    for cid in sorted(cluster_result.cluster_counts):
        rows.append(get_cluster_centroid(cluster_result, cid, preprocess_result))
    df = pd.DataFrame(rows)
    df.index.name = "cluster_id"
    return df


def find_most_similar_pairs(
    cluster_result: ClusterResult,
    k: int = 10,
) -> pd.DataFrame:
    """
    Find the k most similar window *pairs* by scanning the linkage matrix
    for the earliest leaf-to-leaf merges.

    The linkage matrix is sorted by merge distance, so iterating from the top
    yields closest-first.  We stop as soon as we have found k pairs where
    both participants are original leaf nodes (index < n_windows).

    Returns
    -------
    pd.DataFrame with columns:
        start_idx_a, start_idx_b, distance, cluster_a, cluster_b
    """
    Z = cluster_result.linkage_matrix
    n = cluster_result.n_windows
    labels = cluster_result.labels

    pairs = []
    for row in Z:
        i, j, dist = int(row[0]), int(row[1]), float(row[2])
        if i < n and j < n:
            pairs.append({
                "start_idx_a":   cluster_result.start_indices[i],
                "start_idx_b":   cluster_result.start_indices[j],
                "distance":      dist,
                "cluster_a":     int(labels[i]) if labels is not None else None,
                "cluster_b":     int(labels[j]) if labels is not None else None,
            })
        if len(pairs) >= k:
            break

    return pd.DataFrame(pairs)


def find_representative_window(
    cluster_result: ClusterResult,
    cluster_id: int,
    preprocess_result: PreprocessResult,
) -> tuple[int, float]:
    """
    Find the window in a cluster that is closest to the cluster centroid
    (the medoid — the most "typical" window for that physiological state).

    Returns
    -------
    start_idx : int
        start_idx of the representative window.
    distance_to_centroid : float
        Euclidean distance in z-score space between the window and centroid.
    """
    _, X_members = get_cluster_members(cluster_result, cluster_id, preprocess_result)
    centroid = X_members.mean(axis=0)
    dists = np.linalg.norm(X_members - centroid, axis=1)
    best_local = int(np.argmin(dists))

    # Map local row index back to start_idx
    mask = cluster_result.labels == cluster_id
    global_indices = np.where(mask)[0]
    best_global = global_indices[best_local]
    start_idx = int(cluster_result.start_indices[best_global])

    return start_idx, float(dists[best_local])


def cluster_summary(cluster_result: ClusterResult) -> None:
    """
    Print a formatted diagnostic report to stdout.

    Covers: clustering parameters, quality metrics, cluster sizes,
    the largest merge-gap heuristic, and suggested next steps.
    """
    cr = cluster_result
    line = "-" * 62
    print(f"\n{'=' * 62}")
    print(f"  Clustering summary")
    print(line)
    print(f"  Windows          : {cr.n_windows}")
    print(f"  Features         : {cr.n_features}")
    print(f"  Linkage method   : {cr.linkage_method}")
    print(f"  Distance metric  : {cr.distance_metric}")
    print(line)
    print(f"  Cophenetic r     : {cr.cophenetic_r:.4f}   (>0.75 acceptable, >0.85 good)")
    if cr.silhouette is not None:
        print(f"  Silhouette score : {cr.silhouette:.4f}   (>0.5 reasonable, >0.7 strong)")
    else:
        print(f"  Silhouette score : not computed")
    print(line)

    if cr.labels is not None:
        print(f"  Clusters         : {len(cr.cluster_counts)}")
        for cid, count in sorted(cr.cluster_counts.items()):
            pct = count / cr.n_windows * 100
            bar = "|" * int(pct / 2)
            print(f"    Cluster {cid:>3d}  : {count:>5d} windows  ({pct:5.1f}%)  {bar}")
    else:
        print("  Clusters         : not yet extracted (pass n_clusters or distance_cutoff)")

    print(line)
    d = cr.diagnostics
    print(f"  Merge dist range : {d['merge_distances_min']:.4f} – {d['merge_distances_max']:.4f}")
    print(f"  Suggested k      : {d['suggested_n_clusters']}  (largest-gap heuristic — verify visually)")
    print()
    print(f"  Top merge gaps (candidate cut points):")
    for rank, (k_val, gap_val, h_before, h_after) in enumerate(d["top_gaps"], 1):
        print(f"    #{rank}  k={k_val:<4d}  gap={gap_val:.4f}  "
              f"(heights {h_before:.3f} -> {h_after:.3f})")
    if d["n_duplicate_rows"] > 0:
        print(f"  [!] Duplicate rows : {d['n_duplicate_rows']}")
    print(f"{'=' * 62}\n")


# ===========================================================================
# Stage 3 — Cluster visualisation
# ===========================================================================
#
# Choosing a "representative signal" for a biological cluster
# -----------------------------------------------------------
# Four options exist, each with different trade-offs for noisy bio-electric data:
#
# 1. Centroid feature vector
#    The mean of all z-scored feature vectors, inverse-transformed to original
#    units.  Cannot be plotted as a raw signal — it lives only in feature space.
#    Useful for comparing *what statistics* characterise each cluster but gives
#    no waveform intuition.
#
# 2. Medoid window  (single window closest to the centroid in feature space)
#    A real, recorded signal window.  Represents the most "statistically average"
#    observed window.  No phase-alignment or averaging artefacts.  The single
#    best choice when you need one window to represent a cluster.
#    Limitation: may miss intra-cluster variation.
#
# 3. k nearest-to-centroid windows  (recommended default)
#    A set of k real windows ordered by proximity to the centroid.  Shows both
#    the typical waveform AND the degree of consistency within the cluster.
#    For biological data with no natural phase reference this is safer than
#    averaging because it reveals genuine variability rather than blurring it.
#
# 4. Averaged waveform
#    Z-normalise all cluster windows, then average point-by-point.  Creates a
#    "mean waveform shape."  Only meaningful when windows share a consistent
#    morphology relative to a temporal reference (e.g. spike-triggered averaging).
#    For un-triggered bio-electric recordings, averaging often produces a smooth,
#    featureless trace that misrepresents the actual signal character.
#
# RECOMMENDATION for mycelium bio-electric windows: use option 3.  Plot the
# 3-5 nearest-to-centroid windows overlaid (z-normalised) as the primary view,
# and include the mean ± 1 SD envelope across all cluster windows as a
# semi-transparent background band.  This shows both the representative shape
# and the within-cluster consistency simultaneously.
# ===========================================================================

# --- Colour palette for up to 12 clusters (bright, readable on dark bg) -----
_CLUSTER_PALETTE: list[str] = [
    "#e05c5c",  # coral red
    "#5b9bd5",  # sky blue
    "#f5a623",  # amber
    "#7dbc66",  # sage green
    "#b07fe8",  # lavender
    "#4ec9b0",  # teal
    "#f08030",  # orange
    "#cc6e9e",  # mauve
    "#3cb4e6",  # cyan
    "#a3c744",  # yellow-green
    "#ff8c69",  # salmon
    "#7eb8c5",  # dusty blue
]


def _cluster_color(cluster_id: int) -> str:
    """Return a consistent hex colour for 1-indexed cluster_id."""
    return _CLUSTER_PALETTE[(cluster_id - 1) % len(_CLUSTER_PALETTE)]


def _get_raw_window(
    signal_source,
    start_idx: int,
    winsize_samples: int,
) -> np.ndarray:
    """
    Retrieve one raw signal window from either a WindowMatrix or a plain array.

    Accepts
    -------
    signal_source : WindowMatrix  (has .get_window_signal(start_idx))
                 or np.ndarray   (1-D raw signal; winsize_samples used directly)
                 or tuple        (x_array, winsize_samples) — winsize_samples arg ignored
    """
    if hasattr(signal_source, "get_window_signal"):
        return np.asarray(signal_source.get_window_signal(start_idx), dtype=float)
    if isinstance(signal_source, tuple):
        x, ws = signal_source
        return np.asarray(x[start_idx : start_idx + ws], dtype=float)
    # plain array
    return np.asarray(signal_source[start_idx : start_idx + winsize_samples], dtype=float)


def _get_winsize(signal_source, fallback: int | None = None) -> int:
    """Infer the window size in samples from various signal_source types."""
    if hasattr(signal_source, "_window_samples"):
        return int(signal_source._window_samples)
    if isinstance(signal_source, tuple):
        return int(signal_source[1])
    if fallback is not None:
        return fallback
    raise ValueError(
        "Cannot infer window size.  Pass signal_source as a WindowMatrix, "
        "a (x_array, winsize_samples) tuple, or provide winsize_samples explicitly."
    )


def _make_link_color_func(Z: np.ndarray, labels: np.ndarray, n: int):
    """
    Build a link_color_func for scipy.cluster.hierarchy.dendrogram that
    colours each branch with the cluster colour when all of its descendant
    leaves belong to the same cluster, and grey otherwise.

    This ensures the dendrogram colours match _CLUSTER_PALETTE used in all
    other plots, giving a coherent visual language across the whole figure set.
    """
    n_nodes = 2 * n - 1
    node_cluster = np.zeros(n_nodes, dtype=int)

    # Leaves
    for i in range(n):
        node_cluster[i] = int(labels[i])

    # Inner nodes — inherit cluster if both children agree, else -1 (mixed)
    for k_merge, row in enumerate(Z):
        left, right = int(row[0]), int(row[1])
        new_node = n + k_merge
        lc, rc = node_cluster[left], node_cluster[right]
        node_cluster[new_node] = lc if lc == rc else -1

    def _func(node_id: int) -> str:
        cid = node_cluster[node_id]
        return _cluster_color(cid) if cid > 0 else "#666666"

    return _func


# ---------------------------------------------------------------------------
# Helper: k representative windows per cluster
# ---------------------------------------------------------------------------

def get_representative_windows(
    cluster_result: ClusterResult,
    cluster_id: int,
    preprocess_result: PreprocessResult,
    k: int = 5,
    _labels_override: np.ndarray | None = None,
) -> list[int]:
    """
    Return the ``k`` start_idx values whose feature vectors are closest to the
    cluster centroid in z-score space (nearest-to-centroid ordering).

    The first entry is the medoid (single most representative window).
    Subsequent entries are the next closest, capturing intra-cluster variation.

    Parameters
    ----------
    _labels_override : used internally by interactive_cluster_browser when the
        cut height changes dynamically; pass None in normal usage.
    """
    labels = _labels_override if _labels_override is not None else cluster_result.labels
    if labels is None:
        raise ValueError("No cluster labels — pass n_clusters or distance_cutoff to cluster_window_matrix.")

    mask = labels == cluster_id
    if not mask.any():
        raise ValueError(f"Cluster {cluster_id} not found in labels.")

    X_members = preprocess_result.X_scaled[mask]
    centroid = X_members.mean(axis=0)
    dists = np.linalg.norm(X_members - centroid, axis=1)

    sorted_local = np.argsort(dists)[: min(k, len(dists))]
    global_indices = np.where(mask)[0]

    return [int(cluster_result.start_indices[global_indices[i]]) for i in sorted_local]


# ===========================================================================
# Plot 1 — Dendrogram
# ===========================================================================

def plot_dendrogram(
    cluster_result: ClusterResult,
    preprocess_result: PreprocessResult,
    fs: float | None = None,
    n_leaves: int = 60,
    color_threshold: float | None = None,
    orientation: str = "top",
    figsize: tuple[float, float] = (16, 7),
    title: str | None = None,
    dark: bool = False,
    ax: plt.Axes | None = None,
) -> plt.Figure:
    """
    Draw a clean, presentation-quality dendrogram.

    What the dendrogram shows
    -------------------------
    Each leaf represents one (or a group of) time window(s).
    The height at which two branches merge = the linkage distance between the
    corresponding clusters at that point.  Tall vertical branches mean the two
    groups were far apart — a large gap between nearby merge heights suggests a
    natural cluster boundary.

    Parameters
    ----------
    n_leaves : int
        Maximum number of leaf nodes to display.  scipy truncates the tree by
        collapsing subtrees into labelled diamonds.  Default 60 is readable on
        most screen sizes; use a larger value for publication.
    color_threshold : float, optional
        Branches whose merge height is below this value are coloured by cluster.
        Auto-set from ``cluster_result.labels`` when a cut was made, or from
        the suggested-k heuristic otherwise.
    orientation : {"top", "left"}
        "top"  — standard vertical dendrogram (leaves at bottom).
        "left" — horizontal layout; better for many labelled leaves.
    dark : bool
        If True, use a dark figure background (matches other plots in this module).
    ax : plt.Axes, optional
        Draw into an existing Axes instead of creating a new Figure.
    """
    Z = cluster_result.linkage_matrix
    n = cluster_result.n_windows
    start_indices = cluster_result.start_indices

    # ---- Determine color_threshold ----------------------------------------
    if color_threshold is None:
        if cluster_result.labels is not None:
            k = len(cluster_result.cluster_counts)
            # Cut threshold: just above the k-th merge from the end, so k subtrees
            # are coloured individually.
            idx = n - k - 1
            if 0 <= idx < len(Z) - 1:
                color_threshold = float((Z[idx, 2] + Z[idx + 1, 2]) / 2)
            else:
                color_threshold = float(Z[-2, 2] * 0.99)
        else:
            suggested_k = cluster_result.diagnostics.get("suggested_n_clusters", 2)
            idx = n - suggested_k - 1
            if 0 <= idx < len(Z) - 1:
                color_threshold = float((Z[idx, 2] + Z[idx + 1, 2]) / 2)

    # ---- Leaf label function -----------------------------------------------
    # For truncated inner nodes scipy passes ids >= n.
    # show_leaf_counts=True will append "(count)" automatically for those.
    def _leaf_label(node_id: int) -> str:
        if node_id < n:
            return "1"
        return str(int(Z[node_id - n, 3]))

    # ---- Link colour function (when labels exist) --------------------------
    link_color_func = None
    if cluster_result.labels is not None:
        link_color_func = _make_link_color_func(Z, cluster_result.labels, n)

    # ---- Figure / axes setup -----------------------------------------------
    bg = "#1a1a1a" if dark else "#ffffff"
    fg = "#dddddd" if dark else "#222222"
    grid_c = "#333333" if dark else "#eeeeee"

    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
        fig.patch.set_facecolor(bg)
    else:
        fig = ax.get_figure()

    ax.set_facecolor(bg)

    # ---- Draw dendrogram ---------------------------------------------------
    dendro = sch.dendrogram(
        Z,
        ax=ax,
        truncate_mode="lastp",
        p=n_leaves,
        orientation=orientation,
        color_threshold=color_threshold if link_color_func is None else -1,
        link_color_func=link_color_func,
        leaf_label_func=_leaf_label,
        leaf_rotation=90 if orientation == "top" else 0,
        leaf_font_size=10,
        show_leaf_counts=False,
        above_threshold_color="#666666",
    )

    # ---- Bold dendrogram lines --------------------------------------------
    for line in ax.get_lines():
        line.set_linewidth(2.5)

    # ---- Annotate junction node counts ------------------------------------
    height_to_count = {round(float(Z[j, 2]), 8): int(Z[j, 3]) for j in range(len(Z))}
    icoord = dendro["icoord"]
    dcoord = dendro["dcoord"]
    for xs, ys in zip(icoord, dcoord):
        merge_h = ys[1]
        count = height_to_count.get(round(merge_h, 8))
        if count is None:
            continue
        x_mid = (xs[1] + xs[2]) / 2
        ax.annotate(
            str(count),
            xy=(x_mid, merge_h),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center", va="bottom",
            fontsize=8, fontweight="bold",
            color=fg,
            bbox=dict(boxstyle="round,pad=0.15", facecolor=bg, edgecolor="none", alpha=0.75),
            zorder=6,
        )

    # ---- Styling -----------------------------------------------------------
    ax.tick_params(colors=fg, labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor(grid_c)

    # Y-axis label depends on orientation
    dist_label = f"Linkage distance  ({cluster_result.linkage_method})"
    if orientation == "top":
        ax.set_ylabel(dist_label, color=fg, fontsize=10, labelpad=6)
        ax.set_xlabel("Windows per leaf node", color=fg, fontsize=10, labelpad=6)
    else:
        ax.set_xlabel(dist_label, color=fg, fontsize=10, labelpad=6)
        ax.set_ylabel("Windows per leaf node", color=fg, fontsize=10, labelpad=6)
    ax.yaxis.label.set_color(fg)
    ax.xaxis.label.set_color(fg)


    # Annotation: largest-gap merge heights for reference
    gaps = cluster_result.diagnostics.get("top_gaps", [])
    if gaps:
        best_gap = gaps[0]
        k_val, _, h_before, h_after = best_gap
        ax.annotate(
            f"largest gap\n(k={k_val}, {h_before:.1f}->{h_after:.1f})",
            xy=(ax.get_xlim()[1] * 0.02, (h_before + h_after) / 2),
            fontsize=7, color="#aaaaaa" if dark else "#888888",
            va="center",
        )

    if title is None:
        n_shown = n if n <= n_leaves else n_leaves
        title = (f"Dendrogram  |  {n} windows  |  "
                 f"{cluster_result.linkage_method} linkage  |  "
                 f"coph. r={cluster_result.cophenetic_r:.3f}  |  "
                 f"showing last {n_shown} merges")
    ax.set_title(title, color=fg, fontsize=12, pad=12)

    plt.tight_layout()
    plt.show()
    return fig


# ===========================================================================
# Plot 2 — Cluster signal windows
# ===========================================================================

def plot_cluster_signals(
    cluster_result: ClusterResult,
    preprocess_result: PreprocessResult,
    signal_source,
    fs: float,
    n_per_cluster: int = 3,
    clusters: list[int] | None = None,
    normalize: bool = True,
    max_envelope_windows: int = 60,
    winsize_samples: int | None = None,
    figsize: tuple[float, float] | None = None,
) -> plt.Figure:
    """
    Plot representative raw signal windows for each cluster in a grid layout.

    Each row = one cluster.  Each column = one representative window (nearest
    to the cluster centroid).  A semi-transparent mean ± 1 SD envelope,
    computed over up to ``max_envelope_windows`` cluster members, is drawn as
    a background band to show how consistent the cluster's shape is.

    Parameters
    ----------
    signal_source : WindowMatrix, np.ndarray, or (array, winsize_samples) tuple
    fs : float
        Sampling frequency in Hz.  Used to build the time axis.
    n_per_cluster : int
        Number of representative windows to display per cluster.
    clusters : list[int], optional
        Which cluster IDs to display.  Defaults to all clusters, up to 8.
    normalize : bool
        If True, z-normalise each window before plotting so all windows share
        the same amplitude scale.  Recommended for comparing shape.
    max_envelope_windows : int
        Cap on how many windows are loaded to compute the mean ± SD envelope.
        For large clusters a random sample is used.
    winsize_samples : int, optional
        Override for window length.  Usually inferred from signal_source.
    """
    if cluster_result.labels is None:
        raise ValueError("No cluster labels — pass n_clusters to cluster_window_matrix first.")

    ws = _get_winsize(signal_source, fallback=winsize_samples)
    t_axis = np.arange(ws) / fs / 60   # minutes within window

    all_clusters = sorted(cluster_result.cluster_counts)
    show_clusters = (clusters or all_clusters)[: 8]   # cap at 8 rows

    n_rows = len(show_clusters)
    n_cols = n_per_cluster
    if figsize is None:
        figsize = (n_cols * 4.5, n_rows * 2.8)

    fig, axes = plt.subplots(n_rows, n_cols, figsize=figsize,
                              sharey="row", squeeze=False)
    fig.patch.set_facecolor("#1a1a1a")

    for row_idx, cid in enumerate(show_clusters):
        color = _cluster_color(cid)
        size = cluster_result.cluster_counts[cid]

        # ---- Compute mean ± SD envelope from up to max_envelope_windows ----
        mask = cluster_result.labels == cid
        all_sidx = cluster_result.start_indices[mask]
        rng = np.random.default_rng(seed=42)
        sample_sidx = rng.choice(
            all_sidx,
            size=min(max_envelope_windows, len(all_sidx)),
            replace=False,
        )

        env_windows = []
        for sidx in sample_sidx:
            raw = _get_raw_window(signal_source, int(sidx), ws)
            if normalize and raw.std() > 1e-12:
                raw = (raw - raw.mean()) / raw.std()
            env_windows.append(raw)

        if len(env_windows) > 1:
            env_stack = np.stack(env_windows)
            env_mean = env_stack.mean(axis=0)
            env_std  = env_stack.std(axis=0, ddof=1)
        else:
            env_mean = env_windows[0] if env_windows else None
            env_std  = None

        # ---- Representative windows ----------------------------------------
        rep_sidxs = get_representative_windows(cluster_result, cid, preprocess_result, k=n_cols)

        for col_idx in range(n_cols):
            ax = axes[row_idx][col_idx]
            ax.set_facecolor("#111111")
            for spine in ax.spines.values():
                spine.set_edgecolor("#333333")
            ax.tick_params(colors="#888888", labelsize=7)

            # Envelope band
            if env_mean is not None and env_std is not None:
                ax.fill_between(t_axis, env_mean - env_std, env_mean + env_std,
                                alpha=0.18, color=color, linewidth=0)
                ax.plot(t_axis, env_mean, color=color, linewidth=0.6,
                        alpha=0.35, linestyle="--")

            if col_idx < len(rep_sidxs):
                sidx = rep_sidxs[col_idx]
                sig = _get_raw_window(signal_source, sidx, ws)
                if normalize and sig.std() > 1e-12:
                    sig = (sig - sig.mean()) / sig.std()

                is_medoid = col_idx == 0
                lw = 1.5 if is_medoid else 0.9
                alpha = 1.0 if is_medoid else 0.75
                label = "medoid" if is_medoid else f"#{col_idx + 1}"
                ax.plot(t_axis, sig, color=color, linewidth=lw, alpha=alpha)

                t_hr = sidx / (fs * 3600)
                ax.set_title(
                    f"{label}  t={t_hr:.2f}h",
                    color="#cccccc", fontsize=8, pad=3,
                )

            if col_idx == 0:
                ax.set_ylabel(f"Cluster {cid}\n({size}w)",
                              color=color, fontsize=8, labelpad=4)
            if row_idx == n_rows - 1:
                ax.set_xlabel("min within window", color="#888888", fontsize=7)

    y_label = "z-score" if normalize else "amplitude"
    fig.supylabel(y_label, color="#999999", fontsize=9, x=0.01)
    fig.suptitle("Representative windows per cluster  (nearest to centroid)",
                 color="#dddddd", fontsize=11, y=1.0)
    plt.tight_layout()
    plt.show()
    return fig


# ===========================================================================
# Plot 3 — Cluster timeline
# ===========================================================================

def plot_cluster_timeline(
    cluster_result: ClusterResult,
    preprocess_result: PreprocessResult,
    fs: float,
    winsize_samples: int | None = None,
    signal_source=None,
    figsize: tuple[float, float] = (18, 2.2),
    show_legend: bool = True,
) -> plt.Figure:
    """
    Draw a coloured timeline strip showing which cluster each window belongs to.

    The x-axis is recording time in hours.  Each window is a filled rectangle
    whose colour encodes cluster membership.  Cluster transitions — recurring
    windows of the same colour — reveal repeating physiological states.

    Temporal clustering structure that is invisible in the feature heatmap
    (which reorders windows by similarity) becomes immediately apparent here
    because time order is preserved.
    """
    if cluster_result.labels is None:
        raise ValueError("No cluster labels.  Pass n_clusters to cluster_window_matrix first.")

    ws = _get_winsize(signal_source, fallback=winsize_samples) if signal_source is not None else winsize_samples
    window_hours = (ws / fs / 3600) if ws is not None else None

    start_indices = cluster_result.start_indices
    labels = cluster_result.labels
    total_dur = float(start_indices[-1]) / (fs * 3600)

    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("#1a1a1a")
    ax.set_facecolor("#111111")

    for i, (sidx, cid) in enumerate(zip(start_indices, labels)):
        t_start = sidx / (fs * 3600)
        w = window_hours if window_hours is not None else total_dur / len(start_indices)
        rect = plt.Rectangle(
            (t_start, 0), w, 1,
            facecolor=_cluster_color(int(cid)), edgecolor="none", alpha=0.85,
        )
        ax.add_patch(rect)

    ax.set_xlim(0, total_dur + (window_hours or 0))
    ax.set_ylim(0, 1)
    ax.set_xlabel("Recording time (hours)", color="#cccccc", fontsize=9)
    ax.set_yticks([])
    ax.tick_params(axis="x", colors="#aaaaaa", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333333")

    if show_legend:
        handles = [
            plt.Rectangle((0, 0), 1, 1,
                          facecolor=_cluster_color(cid),
                          label=f"Cluster {cid}  ({cluster_result.cluster_counts[cid]}w)")
            for cid in sorted(cluster_result.cluster_counts)
        ]
        ax.legend(
            handles=handles, loc="upper right",
            fontsize=7.5, ncol=min(len(handles), 6),
            facecolor="#222222", edgecolor="#444444",
            labelcolor="#dddddd", handlelength=1.2,
            framealpha=0.8, borderpad=0.4,
        )

    ax.set_title(
        f"Cluster timeline  |  {cluster_result.n_windows} windows  |  "
        f"{len(cluster_result.cluster_counts)} clusters",
        color="#dddddd", fontsize=10, pad=6,
    )
    plt.tight_layout()
    plt.show()
    return fig


# ===========================================================================
# Plot 4 — Clustered feature heatmap
# ===========================================================================

def plot_cluster_heatmap(
    cluster_result: ClusterResult,
    preprocess_result: PreprocessResult,
    fs: float | None = None,
    figsize: tuple[float, float] = (16, 9),
    cmap: str = "RdBu_r",
    clip_sigma: float = 3.0,
) -> plt.Figure:
    """
    Feature heatmap reordered by the dendrogram's optimal leaf ordering.

    Windows (x-axis) are sorted so that statistically similar windows are
    adjacent, matching the left-to-right leaf order of the dendrogram.
    A colour strip on the left of the heatmap shows cluster membership,
    making the relationship between feature patterns and cluster assignments
    visually explicit.

    Which features drive cluster formation?
    ----------------------------------------
    Columns where the colour clearly shifts between cluster groups are the
    features with the strongest discriminative power.  Uniform columns are
    features that contribute little to the cluster structure.
    """
    leaf_order = cluster_result.leaf_order
    labels = cluster_result.labels

    # Reorder windows by optimal leaf order
    X_ordered = preprocess_result.X_scaled[leaf_order]        # (n_windows, n_feat)
    si_ordered = cluster_result.start_indices[leaf_order]
    lab_ordered = labels[leaf_order] if labels is not None else None

    # Reorder features by group
    ordered_features, group_info = _group_and_sort_features(preprocess_result.feature_names)
    feat_idx = [preprocess_result.feature_names.index(f) for f in ordered_features]
    Z = X_ordered[:, feat_idx].T    # (n_features, n_windows) for imshow

    n_features, n_windows = Z.shape

    # ---- Time ticks --------------------------------------------------------
    x_pos, x_lab = _make_time_ticks(si_ordered, fs, n_ticks=10)

    # ---- Layout: main heatmap + bottom cluster strip -----------------------
    # Strip sits below the heatmap, sharing the same horizontal extent.
    # Windows run left→right on the X-axis; features run top→bottom on Y.
    LPAD     = 0.10   # left margin for group labels (_draw_group_labels_and_separators)
    RPAD     = 0.02
    CBAR_W   = 0.018
    CBAR_PAD = 0.012
    STRIP_H  = 0.030  # height of cluster colour strip
    BPAD     = 0.11   # bottom margin for time-axis tick labels
    HEAT_B   = BPAD + STRIP_H + 0.008   # bottom of heatmap, above strip
    PLOT_T   = 0.92

    heat_l = LPAD
    heat_w = 1.0 - heat_l - RPAD - CBAR_W - CBAR_PAD

    fig = plt.figure(figsize=figsize)
    fig.patch.set_facecolor("#1a1a1a")

    ax_heat  = fig.add_axes([heat_l, HEAT_B, heat_w, PLOT_T - HEAT_B])
    ax_strip = fig.add_axes([heat_l, BPAD,   heat_w, STRIP_H])
    ax_cbar  = fig.add_axes([heat_l + heat_w + CBAR_PAD, HEAT_B, CBAR_W, PLOT_T - HEAT_B])

    ax_heat.set_facecolor("#1a1a1a")

    # ---- Main heatmap ------------------------------------------------------
    im = ax_heat.imshow(
        Z, aspect="auto", cmap=cmap,
        vmin=-clip_sigma, vmax=clip_sigma,
        interpolation="nearest", origin="upper",
    )

    # Y-axis: feature names on right + group labels/separators on left
    short_names = _shorten_feature_names(ordered_features)
    ax_heat.yaxis.tick_right()
    ax_heat.yaxis.set_label_position("right")
    ax_heat.set_yticks(range(n_features))
    ax_heat.set_yticklabels(short_names, fontsize=6, color="#cccccc")
    ax_heat.tick_params(axis="y", length=0, pad=3)
    _draw_group_labels_and_separators(ax_heat, group_info, n_features)

    # X-axis: suppress labels on heatmap — strip below carries them
    ax_heat.set_xticks([])

    # Cluster boundary lines (vertical, one per cluster transition)
    if lab_ordered is not None:
        for i in range(1, n_windows):
            if lab_ordered[i] != lab_ordered[i - 1]:
                ax_heat.axvline(i - 0.5, color="#ffffff", linewidth=0.8,
                                alpha=0.5, zorder=3)

    # ---- Cluster colour strip (bottom, horizontal) -------------------------
    ax_strip.set_facecolor("#1a1a1a")
    if lab_ordered is not None:
        strip_img = np.zeros((1, n_windows, 4))
        for i, cid in enumerate(lab_ordered):
            rgb = plt.matplotlib.colors.to_rgba(_cluster_color(int(cid)))
            strip_img[0, i] = rgb
        ax_strip.imshow(strip_img, aspect="auto", origin="upper",
                        interpolation="nearest")
        # Also draw cluster boundary lines on strip
        for i in range(1, n_windows):
            if lab_ordered[i] != lab_ordered[i - 1]:
                ax_strip.axvline(i - 0.5, color="#ffffff", linewidth=0.8,
                                 alpha=0.5, zorder=3)
        for spine in ax_strip.spines.values():
            spine.set_edgecolor("#333333")
    else:
        ax_strip.set_visible(False)

    ax_strip.set_yticks([])
    ax_strip.set_xticks(x_pos)
    ax_strip.set_xticklabels(x_lab, fontsize=7.5, rotation=30,
                              ha="right", color="#cccccc")
    ax_strip.tick_params(axis="x", colors="#cccccc", length=3)
    xlabel = "Time (hours, dendrogram order)" if fs else "Window index (dendrogram order)"
    ax_strip.set_xlabel(xlabel, color="#cccccc", fontsize=9, labelpad=5)

    # ---- Colorbar ----------------------------------------------------------
    cbar = fig.colorbar(im, cax=ax_cbar)
    cbar.set_label("z-score", color="#cccccc", fontsize=8)
    cbar.ax.yaxis.set_tick_params(colors="#cccccc", labelsize=7)
    cbar.outline.set_edgecolor("#444444")

    # ---- Cluster legend above heatmap --------------------------------------
    if lab_ordered is not None:
        handles = [
            plt.Rectangle((0, 0), 1, 1, facecolor=_cluster_color(cid),
                          label=f"Cluster {cid}  ({cluster_result.cluster_counts[cid]}w)")
            for cid in sorted(cluster_result.cluster_counts)
        ]
        ax_heat.legend(
            handles=handles,
            loc="upper left", bbox_to_anchor=(0.0, 1.0),
            ncol=min(len(handles), 6), fontsize=7.5,
            facecolor="#222222", edgecolor="#444444",
            labelcolor="#dddddd", handlelength=1.2,
            framealpha=0.85, borderpad=0.4,
        )

    ax_heat.set_title(
        f"Clustered feature heatmap  |  "
        f"{cluster_result.linkage_method} linkage, "
        f"coph.r={cluster_result.cophenetic_r:.3f}  |  "
        f"clipped +/-{clip_sigma:.0f}s",
        color="#eeeeee", fontsize=10, pad=8,
    )
    plt.show()
    return fig


# ===========================================================================
# Plot 5 — Interactive cluster browser
# ===========================================================================

def interactive_cluster_browser(
    cluster_result: ClusterResult,
    preprocess_result: PreprocessResult,
    signal_source,
    fs: float,
    n_signals: int = 3,
    winsize_samples: int | None = None,
    normalize_signals: bool = True,
    figsize: tuple[float, float] = (18, 9),
    initial_cut: float | None = None,
) -> plt.Figure:
    """
    Interactive two-panel explorer: click the dendrogram to set a cut height,
    use arrow buttons to cycle through clusters, and inspect representative
    raw signal windows on the right.

    Controls
    --------
    Click in dendrogram  — sets cut height at clicked y-coordinate; updates
                           cluster assignments and resets to cluster 1.
    [<] / [>] buttons    — previous / next cluster.
    Left / Right arrow   — same as [<] / [>].

    What you can discover
    ---------------------
    By dragging the cut height you can explore how the cluster structure
    changes from coarse (2 groups) to fine (many groups).  Simultaneously
    inspecting the raw signal windows tells you which *waveform behaviours*
    correspond to each statistical cluster — closing the loop between
    abstract feature-space distances and actual biological activity.
    """
    from matplotlib.widgets import Button

    Z = cluster_result.linkage_matrix
    n = cluster_result.n_windows
    ws = _get_winsize(signal_source, fallback=winsize_samples)
    t_axis_min = np.arange(ws) / fs / 60   # minutes within window

    # ---- Determine initial cut height -------------------------------------
    if initial_cut is not None:
        _init_cut = float(initial_cut)
    elif cluster_result.labels is not None:
        k = len(cluster_result.cluster_counts)
        idx = max(0, n - k - 1)
        _init_cut = float((Z[idx, 2] + Z[min(idx + 1, len(Z) - 1), 2]) / 2)
    else:
        suggested_k = cluster_result.diagnostics.get("suggested_n_clusters", 2)
        idx = max(0, n - suggested_k - 1)
        _init_cut = float((Z[idx, 2] + Z[min(idx + 1, len(Z) - 1), 2]) / 2)

    # ---- Shared mutable state ---------------------------------------------
    state: dict = {
        "cut":      _init_cut,
        "labels":   sch.fcluster(Z, t=_init_cut, criterion="distance"),
        "cluster":  1,          # currently displayed cluster (1-indexed)
    }
    state["n_clusters"] = int(np.max(state["labels"]))

    # ---- Figure layout (all via add_axes for precise control) -------------
    DARK_BG = "#151515"
    fig = plt.figure(figsize=figsize)
    fig.patch.set_facecolor(DARK_BG)

    # Dendrogram: left 54%, full height minus button row
    ax_dendro = fig.add_axes([0.04, 0.13, 0.52, 0.82])
    ax_dendro.set_facecolor(DARK_BG)

    # Signal panels: right 38%, stacked evenly
    panel_h   = 0.77 / n_signals
    sig_axes  = []
    for i in range(n_signals):
        bottom = 0.13 + (n_signals - 1 - i) * panel_h
        ax_s = fig.add_axes([0.60, bottom, 0.37, panel_h - 0.01])
        ax_s.set_facecolor("#0e0e0e")
        sig_axes.append(ax_s)

    # Nav buttons (below signals)
    ax_prev = fig.add_axes([0.60, 0.02, 0.07, 0.07])
    ax_next = fig.add_axes([0.68, 0.02, 0.07, 0.07])

    # Info bar (bottom, spans full width below dendro)
    ax_info = fig.add_axes([0.04, 0.02, 0.52, 0.08])
    ax_info.set_facecolor("#1a1a1a")
    ax_info.set_xticks([]); ax_info.set_yticks([])
    for sp in ax_info.spines.values():
        sp.set_edgecolor("#333333")
    info_text = ax_info.text(
        0.01, 0.5, "", transform=ax_info.transAxes,
        va="center", ha="left", color="#cccccc", fontsize=8.5,
    )

    # ---- Draw dendrogram (called on cut-height change) --------------------
    def _draw_dendro():
        ax_dendro.cla()
        ax_dendro.set_facecolor(DARK_BG)

        cut = state["cut"]
        labels_now = state["labels"]

        link_fn = _make_link_color_func(Z, labels_now, n)
        sch.dendrogram(
            Z,
            ax=ax_dendro,
            truncate_mode="lastp",
            p=min(60, n),
            color_threshold=-1,
            link_color_func=link_fn,
            leaf_font_size=6,
            leaf_rotation=90,
            show_leaf_counts=True,
            above_threshold_color="#555555",
        )

        # Horizontal cut line
        ax_dendro.axhline(cut, color="#ffcc44", linewidth=1.4,
                          linestyle="--", alpha=0.85, zorder=6)

        # Axis styling
        ax_dendro.tick_params(colors="#888888", labelsize=7)
        for sp in ax_dendro.spines.values():
            sp.set_edgecolor("#333333")
        ax_dendro.set_ylabel(
            f"Linkage distance  ({cluster_result.linkage_method})",
            color="#aaaaaa", fontsize=8.5, labelpad=5,
        )
        ax_dendro.set_title(
            "Click to set cut height   |   < > to cycle clusters",
            color="#aaaaaa", fontsize=8.5, pad=6,
        )

    # ---- Draw signals for current cluster ---------------------------------
    def _draw_signals():
        cid  = state["cluster"]
        labs = state["labels"]
        color = _cluster_color(cid)

        mask = labs == cid
        count = int(mask.sum())

        if count == 0:
            for ax in sig_axes:
                ax.cla(); ax.set_facecolor("#0e0e0e")
            return

        rep_sidxs = get_representative_windows(
            cluster_result, cid, preprocess_result,
            k=n_signals, _labels_override=labs,
        )

        for i, ax in enumerate(sig_axes):
            ax.cla()
            ax.set_facecolor("#0e0e0e")
            for sp in ax.spines.values():
                sp.set_edgecolor("#2a2a2a")
            ax.tick_params(colors="#666666", labelsize=6.5)

            if i >= len(rep_sidxs):
                continue

            sidx = rep_sidxs[i]
            sig = _get_raw_window(signal_source, sidx, ws)
            if normalize_signals and sig.std() > 1e-12:
                sig = (sig - sig.mean()) / sig.std()

            is_medoid = i == 0
            lw    = 1.5 if is_medoid else 1.0
            alpha = 1.0 if is_medoid else 0.75
            ax.plot(t_axis_min, sig, color=color, linewidth=lw, alpha=alpha)

            t_hr = sidx / (fs * 3600)
            lbl = "medoid" if is_medoid else f"#{i+1}"
            ax.set_title(
                f"{lbl}  |  t = {t_hr:.2f} h  |  start_idx = {sidx}",
                color="#999999", fontsize=7.5, pad=2,
            )
            if i == len(sig_axes) - 1:
                ax.set_xlabel("min within window", color="#666666", fontsize=7)
            else:
                ax.set_xticklabels([])

            y_lab = "z-score" if normalize_signals else "amplitude"
            if i == 1:
                ax.set_ylabel(y_lab, color="#666666", fontsize=7)

    # ---- Update info bar --------------------------------------------------
    def _update_info():
        cid   = state["cluster"]
        labs  = state["labels"]
        k_now = state["n_clusters"]
        count = int((labs == cid).sum())
        pct   = count / n * 100

        info_text.set_text(
            f"Cut height: {state['cut']:.3f}   |   "
            f"k = {k_now} clusters   |   "
            f"Cluster {cid}/{k_now}   |   "
            f"{count} windows  ({pct:.1f}%)   |   "
            f"cophenetic r = {cluster_result.cophenetic_r:.3f}"
        )

    # ---- Full redraw ------------------------------------------------------
    def _full_redraw():
        _draw_dendro()
        _draw_signals()
        _update_info()
        fig.canvas.draw_idle()

    # ---- Dendrogram click handler -----------------------------------------
    def _on_dendro_click(event):
        if event.inaxes is not ax_dendro:
            return
        if event.ydata is None or event.ydata <= 0:
            return

        new_cut = float(event.ydata)
        new_labels = sch.fcluster(Z, t=new_cut, criterion="distance")
        state["cut"]       = new_cut
        state["labels"]    = new_labels
        state["n_clusters"] = int(np.max(new_labels))
        state["cluster"]   = 1
        _full_redraw()

    # ---- Cluster navigation -----------------------------------------------
    def _shift_cluster(delta: int):
        k_now = state["n_clusters"]
        state["cluster"] = max(1, min(k_now, state["cluster"] + delta))
        _draw_signals()
        _update_info()
        fig.canvas.draw_idle()

    def _on_prev(_): _shift_cluster(-1)
    def _on_next(_): _shift_cluster(+1)

    def _on_key(event):
        if event.key == "left":     _shift_cluster(-1)
        elif event.key == "right":  _shift_cluster(+1)

    # ---- Wire up buttons and events ---------------------------------------
    btn_prev = Button(ax_prev, "<  Prev",
                      color="#222222", hovercolor="#333333")
    btn_next = Button(ax_next, "Next  >",
                      color="#222222", hovercolor="#333333")
    btn_prev.label.set_color("#cccccc")
    btn_next.label.set_color("#cccccc")
    btn_prev.on_clicked(_on_prev)
    btn_next.on_clicked(_on_next)

    fig.canvas.mpl_connect("button_press_event", _on_dendro_click)
    fig.canvas.mpl_connect("key_press_event", _on_key)

    # ---- Initial draw -----------------------------------------------------
    _full_redraw()
    plt.show()

    # Keep widget references alive (prevents garbage collection of callbacks)
    fig._browser_widgets = (btn_prev, btn_next)
    return fig


# ===========================================================================
# Plot 5 — Outlier signal slideshow
# ===========================================================================

def plot_outlier_slideshow(
    outlier_df: pd.DataFrame,
    signal_source,
    fs: float,
    winsize_samples: int | None = None,
    normalize: bool = False,
    figsize: tuple[float, float] = (14, 6),
) -> plt.Figure | None:
    """
    Interactive slideshow of flagged outlier signal windows.

    Use the [Prev] / [Next] buttons or the Left / Right arrow keys to step
    through each outlier.  The title of every frame shows the window's
    start index, recording time, z-score, and normalised distance so you
    can judge whether each flagged window is a genuine artefact.

    Parameters
    ----------
    outlier_df : pd.DataFrame
        Output of find_outliers() — either the full DataFrame or already
        filtered to is_outlier == True.  Index must be start_idx.
    signal_source : WindowMatrix or array
        Raw signal source (same object passed to the other plot functions).
    fs : float
        Sampling frequency in Hz.
    winsize_samples : int, optional
        Window length in samples.  Inferred from signal_source when omitted.
    normalize : bool
        Z-normalise each window before plotting (default False so you can
        see the raw amplitude and judge whether the window is anomalous).
    figsize : tuple
        Figure size in inches.
    """
    from matplotlib.widgets import Button

    if "is_outlier" in outlier_df.columns:
        df = outlier_df[outlier_df["is_outlier"]].copy()
    else:
        df = outlier_df.copy()

    if len(df) == 0:
        print("No outlier windows to display.")
        return None

    ws = _get_winsize(signal_source, fallback=winsize_samples)
    t_axis = np.arange(ws) / fs / 60   # minutes within window
    outlier_sidxs = df.index.tolist()
    n_outliers = len(outlier_sidxs)

    state: dict = {"idx": 0}

    DARK_BG = "#151515"
    fig = plt.figure(figsize=figsize)
    fig.patch.set_facecolor(DARK_BG)

    ax_sig = fig.add_axes([0.07, 0.22, 0.90, 0.70])
    ax_sig.set_facecolor("#111111")
    for sp in ax_sig.spines.values():
        sp.set_edgecolor("#333333")

    ax_prev = fig.add_axes([0.07, 0.04, 0.10, 0.10])
    ax_next = fig.add_axes([0.18, 0.04, 0.10, 0.10])

    ax_info = fig.add_axes([0.30, 0.04, 0.67, 0.10])
    ax_info.set_facecolor("#1a1a1a")
    ax_info.set_xticks([])
    ax_info.set_yticks([])
    for sp in ax_info.spines.values():
        sp.set_edgecolor("#333333")
    info_txt = ax_info.text(
        0.01, 0.5, "",
        transform=ax_info.transAxes,
        va="center", ha="left",
        color="#cccccc", fontsize=9,
    )

    def _draw(i: int) -> None:
        ax_sig.cla()
        ax_sig.set_facecolor("#111111")
        for sp in ax_sig.spines.values():
            sp.set_edgecolor("#333333")

        sidx = outlier_sidxs[i]
        row  = df.loc[sidx]
        t_hr = sidx / (fs * 3600)

        sig = _get_raw_window(signal_source, int(sidx), ws)
        if normalize and sig.std() > 1e-12:
            sig = (sig - sig.mean()) / sig.std()

        ax_sig.plot(t_axis, sig, color="#ff6666", linewidth=1.5)
        ax_sig.set_xlim(t_axis[0], t_axis[-1])
        ax_sig.set_xlabel("Time within window (min)", color="#aaaaaa", fontsize=9, labelpad=5)
        ax_sig.set_ylabel(
            "Signal (z-norm)" if normalize else "Signal",
            color="#aaaaaa", fontsize=9,
        )
        ax_sig.tick_params(colors="#888888", labelsize=8)

        ax_sig.set_title(
            f"Outlier {i + 1} / {n_outliers}   |   "
            f"start_idx = {sidx}   |   "
            f"t = {t_hr:.2f} hr   |   "
            f"z-score = {row['z_score']:.2f}   |   "
            f"norm_dist = {row['norm_distance']:.4f}",
            color="#dddddd", fontsize=10, pad=8,
        )

        info_txt.set_text(
            f"Window {i + 1} of {n_outliers}   —   "
            f"← / → arrow keys or buttons to navigate"
        )
        fig.canvas.draw_idle()

    def _go(delta: int) -> None:
        state["idx"] = (state["idx"] + delta) % n_outliers
        _draw(state["idx"])

    def _on_prev(_): _go(-1)
    def _on_next(_): _go(+1)

    def _on_key(event):
        if event.key in ("left", "up"):
            _go(-1)
        elif event.key in ("right", "down"):
            _go(+1)

    btn_prev = Button(ax_prev, "◀  Prev", color="#222222", hovercolor="#333333")
    btn_next = Button(ax_next, "Next  ▶", color="#222222", hovercolor="#333333")
    btn_prev.label.set_color("#cccccc")
    btn_next.label.set_color("#cccccc")
    btn_prev.on_clicked(_on_prev)
    btn_next.on_clicked(_on_next)

    fig.canvas.mpl_connect("key_press_event", _on_key)

    _draw(0)
    plt.show()

    fig._slideshow_widgets = (btn_prev, btn_next)
    return fig
