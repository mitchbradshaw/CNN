
# ── Repo-root bootstrap ───────────────────────────────────────────────────────
# Makes `Working.*` / `Pipelines.*` importable when this file is run directly.
# Walks up to the directory containing Working/, so it survives future moves.
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from Working.Preprocessing.window_matrix.create_matrix import *
from Working.Catalogue.dendrogram.dendrogram_cluster import (
    preprocess_window_matrix,
    cluster_window_matrix,
    cluster_summary,
    get_all_centroids,
    find_representative_window,
    find_most_similar_pairs,
    find_outliers,
    get_representative_windows,
    plot_dendrogram,
    plot_cluster_signals,
    plot_cluster_timeline,
    plot_cluster_heatmap,
    interactive_cluster_browser,
    plot_outlier_slideshow,
)
import copy
import numpy as np
import pandas as pd

pd.set_option("display.float_format", "{:.4f}".format)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 120)

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
FILENAME = "0.01_percent_M2_concat_fs1.mat"
WINSIZE  = 10       # minutes
FS       = 1
CSVFILE  = "0.01_percent_M2_concat_fs1_consecutive.csv"

wm = get_wm(FS, WINSIZE, FILENAME, matname="VECTOR", csvfilename=CSVFILE)

# ---------------------------------------------------------------------------
# Stage 1: Preprocessing
# ---------------------------------------------------------------------------
prep = preprocess_window_matrix(wm.df)

# ---------------------------------------------------------------------------
# Stage 2a: Outlier detection
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  STAGE 2a: Outlier detection")
print("=" * 62)
outlier_df = find_outliers(prep, z_threshold=3.0)
print(outlier_df.head(10).to_string())
flagged = outlier_df[outlier_df["is_outlier"]]
print(f"\n  {len(flagged)} outlier window(s) flagged at z > 3.0:")
for sidx, row in flagged.iterrows():
    print(f"    start_idx={sidx:>8d}  t={sidx/(FS*3600):.2f} hr  "
          f"norm_dist={row['norm_distance']:.4f}  z={row['z_score']:.2f}")

WINSIZE_SAMPLES = int(FS * WINSIZE * 60)

if len(flagged) > 0:
    plot_outlier_slideshow(flagged, wm, fs=FS, winsize_samples=WINSIZE_SAMPLES)

# ---------------------------------------------------------------------------
# Stage 2b: Silhouette sweep - average vs complete, full data
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  STAGE 2b: Silhouette sweep - average vs complete linkage")
print("=" * 62)
print(f"  {'k':>3}  {'avg sil':>9}  {'avg sizes':>30}  |  {'cpl sil':>9}  {'cpl sizes'}")
print("  " + "-" * 80)

for k in range(2, 9):
    cr_avg = cluster_window_matrix(
        prep, method="average", n_clusters=k, optimal_ordering=False
    )
    cr_cpl = cluster_window_matrix(
        prep, method="complete", n_clusters=k, optimal_ordering=False
    )
    sil_avg = cr_avg.silhouette or float("nan")
    sil_cpl = cr_cpl.silhouette or float("nan")
    sizes_avg = "  ".join(str(s) for s in sorted(cr_avg.cluster_counts.values(), reverse=True))
    sizes_cpl = "  ".join(str(s) for s in sorted(cr_cpl.cluster_counts.values(), reverse=True))
    print(f"  k={k}  {sil_avg:>+.4f}   {sizes_avg:>30}  |  {sil_cpl:>+.4f}   {sizes_cpl}")

# ---------------------------------------------------------------------------
# Stage 2c: Complete linkage gap analysis
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  STAGE 2c: Complete linkage - gap analysis")
print("=" * 62)
cr_cpl_full = cluster_window_matrix(prep, method="complete")
cluster_summary(cr_cpl_full)

# ---------------------------------------------------------------------------
# Stage 2d: Complete linkage on outlier-removed data
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  STAGE 2d: Outlier-removed clustering  (complete linkage)")
print("=" * 62)
outlier_indices = set(flagged.index.tolist())
df_clean = prep.df_features.loc[~prep.df_features.index.isin(outlier_indices)]
mask_clean = ~np.isin(prep.df_features.index.values,
                       list(outlier_indices))

prep_clean = copy.copy(prep)
prep_clean.X_scaled   = prep.X_scaled[mask_clean]
prep_clean.df_features = df_clean
prep_clean.df_metadata = prep.df_metadata.loc[df_clean.index]

print(f"  Removed {len(outlier_indices)} outlier(s): {sorted(outlier_indices)}")
print(f"  Remaining windows: {len(df_clean)}")

cr_clean_nogap = cluster_window_matrix(prep_clean, method="complete")
cluster_summary(cr_clean_nogap)

print("\n  Silhouette sweep on outlier-removed data (complete linkage):")
print(f"  {'k':>3}   silhouette   cluster sizes")
print("  " + "-" * 50)
best_sil, best_k = -1, 2
for k in range(2, 9):
    cr_k = cluster_window_matrix(
        prep_clean, method="complete", n_clusters=k, optimal_ordering=False
    )
    sil = cr_k.silhouette or float("nan")
    sizes = "  ".join(str(s) for s in sorted(cr_k.cluster_counts.values(), reverse=True))
    marker = " <--" if sil == sil and sil > best_sil else ""
    print(f"  k={k}   {sil:>+.4f}   {sizes}{marker}")
    if sil == sil and sil > best_sil:
        best_sil, best_k = sil, k

print(f"\n  Best silhouette (clean, complete): k={best_k}  ({best_sil:.4f})")

# ---------------------------------------------------------------------------
# Stage 2e: Centroids for best k on clean data
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print(f"  STAGE 2e: Centroids for k={best_k}  (clean data, complete linkage)")
print("=" * 62)
cr_final = cluster_window_matrix(
    prep_clean, method="complete", n_clusters=best_k
)
centroids = get_all_centroids(cr_final, prep_clean)
print(centroids.T.to_string())

# ---------------------------------------------------------------------------
# Stage 2f: Representative window (medoid) per cluster
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print(f"  STAGE 2f: Representative windows (medoids) for k={best_k}")
print("=" * 62)
for cid in sorted(cr_final.cluster_counts):
    sidx, dist = find_representative_window(cr_final, cid, prep_clean)
    size = cr_final.cluster_counts[cid]
    t_hr = sidx / (FS * 3600)
    print(f"  Cluster {cid:>2d}  ({size:>3d} windows)  "
          f"medoid start_idx={sidx:>8d}  t={t_hr:.2f} hr  "
          f"dist_to_centroid={dist:.4f}")

# ---------------------------------------------------------------------------
# Stage 2g: Most similar window pairs
# ---------------------------------------------------------------------------
print("\n" + "=" * 62)
print("  STAGE 2g: 10 most similar window pairs")
print("=" * 62)
pairs = find_most_similar_pairs(cr_final, k=10)
print(pairs.to_string(index=False))

# ---------------------------------------------------------------------------
# Stage 3: Visualisation
# ---------------------------------------------------------------------------

# 3a: Dendrogram
print("\n" + "=" * 62)
print(f"  STAGE 3a: Dendrogram  (k={best_k}, clean data)")
print("=" * 62)
plot_dendrogram(cr_final, prep_clean, fs=FS, dark=False)

# 3b: Cluster timeline
print("\n" + "=" * 62)
print("  STAGE 3b: Cluster timeline")
print("=" * 62)
plot_cluster_timeline(
    cr_final, prep_clean, fs=FS,
    winsize_samples=WINSIZE_SAMPLES,
)

# 3c: Feature heatmap (reordered by dendrogram leaf order)
print("\n" + "=" * 62)
print("  STAGE 3c: Clustered feature heatmap")
print("=" * 62)
plot_cluster_heatmap(cr_final, prep_clean, fs=FS)

# 3d: Representative raw signal windows per cluster
print("\n" + "=" * 62)
print("  STAGE 3d: Representative signal windows per cluster")
print("=" * 62)
plot_cluster_signals(
    cr_final, prep_clean, wm, fs=FS,
    n_per_cluster=3,
    winsize_samples=WINSIZE_SAMPLES,
)

# 3e: Interactive browser (click dendrogram to explore cut heights)
print("\n" + "=" * 62)
print("  STAGE 3e: Interactive cluster browser")
print("=" * 62)
interactive_cluster_browser(
    cr_final, prep_clean, wm, fs=FS,
    n_signals=3,
    winsize_samples=WINSIZE_SAMPLES,
)
