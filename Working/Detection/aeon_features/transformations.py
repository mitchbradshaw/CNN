import numpy as np
from aeon.transformations.collection.feature_based import Catch22
from pathlib import Path
import sys

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

# ── Shared Catch22 instance ───────────────────────────────────────────────────
_c22 = Catch22(replace_nans=True)

# Canonical feature names in the order Catch22 returns them.
CATCH22_FEATURE_NAMES = [
    "DN_HistogramMode_5",
    "DN_HistogramMode_10",
    "CO_f1ecac",
    "CO_FirstMin_ac",
    "CO_HistogramAMI_even_2_5",
    "CO_trev_1_num",
    "MD_hrv_classic_pnn40",
    "SB_BinaryStats_mean_longstretch1",
    "SB_TransitionMatrix_3ac_sumdiagcov",
    "PD_PeriodicityWang_th0_01",
    "CO_Embed2_Dist_tau_d_expfit_meandiff",
    "IN_AutoMutualInfoStats_40_gaussian_fmmi",
    "FC_LocalSimple_mean1_tauresrat",
    "DN_OutlierInclude_p_001_mdrmd",
    "DN_OutlierInclude_n_001_mdrmd",
    "SP_Summaries_welch_rect_area_5_1",
    "SB_BinaryStats_diff_longstretch0",
    "SB_MotifThree_quantile_hh",
    "SC_FluctAnal_2_rsrangefit_50_1_logi_prop_r1",
    "SC_FluctAnal_2_dfa_50_1_2_logi_prop_r1",
    "SP_Summaries_welch_rect_centroid",
    "FC_LocalSimple_mean3_tauresrat",
]


def catch22_features(window: np.ndarray) -> np.ndarray:
    """
    Catch22 feature extraction for a single 1-D window.

    Returns features in the same order as CATCH22_FEATURE_NAMES.
    Use add_catch22_to_matrix to get descriptive column names automatically.

    Parameters
    ----------
    window : np.ndarray, shape (n_timepoints,)
        Raw signal slice for one window.

    Returns
    -------
    np.ndarray, shape (22,)
        22 catch22 summary statistics.
    """
    X = window.reshape(1, 1, -1).astype(np.float32)   # (1, 1, n_timepoints)
    return _c22.fit_transform(X)[0]                    # (22,)


def add_catch22_to_matrix(wm, prefix: str = "catch22"):
    """
    Add Catch22 features to a WindowMatrix with descriptive column names.

    Produces columns named ``{prefix}_{feature_name}`` for each of the 22
    features, e.g. ``catch22_DN_HistogramMode_5``.

    Parameters
    ----------
    wm     : WindowMatrix
    prefix : str  column-name prefix (default "catch22")

    Returns
    -------
    wm  (for chaining)
    """
    names = [f"{prefix}_{n}" for n in CATCH22_FEATURE_NAMES]
    return wm.add_vector_columns(prefix, catch22_features, names=names)


def transformations(w) -> np.ndarray:
    """
    Catch22 feature extraction – transforms each window into 22 summary statistics.
    Processes the full AeonDataset collection at once.
    """
    features = _c22.fit_transform(w.X)   # (n_instances, 22)

    feature_means = features.mean(axis=0)
    feature_stds  = features.std(axis=0)

    summary_lines = ["Catch22 feature extraction"]
    summary_lines.append(f"  input  shape : {w.X.shape}")
    summary_lines.append(f"  output shape : {features.shape}")
    summary_lines.append("  feature statistics (mean ± std):")
    for i, (m, s) in enumerate(zip(feature_means, feature_stds)):
        summary_lines.append(f"    feat_{i:02d} : {m:+.4f} ± {s:.4f}")
    summary = "\n".join(summary_lines) + "\n"

    print(summary)
    return features


if __name__ == "__main__":
    from aeon_test_pipeline import load_dataset
    J = load_dataset()
    transformations(J)