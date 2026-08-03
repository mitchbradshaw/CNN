
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

# --- Create / load matrix ---
wm = load_matrix("MATRICES/features.csv", x, timescale=10, fs=1.0)

# --- STFT log-spectrum column ---
# Each window is timescale * 60 * fs samples long (600 samples at fs=1, 10min).
# We run an STFT *within* each window using a 60-sample (1-min) sub-window
# and 50% overlap.  stft_log_spectrum returns (bin_freqs, power); we store
# only the power array since bin_freqs is identical for every window.
#
# To recover bin_freqs later for plotting/analysis:
#   bin_freqs, _ = stft_log_spectrum(wm.get_window_signal(start_idx),
#                                    fs=1.0, window_size=60, hop_size=30)

STFT_WINDOW = 60    # sub-window size within each matrix window (samples)
STFT_HOP    = 30    # 50 % overlap
N_LOG_BINS  = 64    # frequency resolution of the output vector

def stft_power(window_x: np.ndarray) -> np.ndarray:
    """Wrapper: runs stft_log_spectrum on one window and returns the power vector."""
    _, power = stft_log_spectrum(
        window_x,
        fs=wm._fs,
        window_size=STFT_WINDOW,
        hop_size=STFT_HOP,
        n_log_bins=N_LOG_BINS,
        return_2d=False,        # averaged across time frames → 1-D [n_log_bins]
    )
    return power

# Each log-frequency bin becomes its own scalar column: stft_bin_0 … stft_bin_63
wm.add_vector_columns("stft_bin", stft_power)

# --- Access examples ---
# Single bin value:    wm.get_value(149801, "stft_bin_12")
# All columns as a 2-D numpy array (n_windows × N_LOG_BINS):
#   import pandas as pd
#   power_matrix = wm.df[[c for c in wm.columns if c.startswith("stft_bin_")]].to_numpy()

# --- Save ---
wm.df.to_csv("MATRICES/features.csv")

# ------------------------------------------------------------------ #
#  Power matrix plots                                                  #
# ------------------------------------------------------------------ #

bin_cols     = sorted([c for c in wm.columns if c.startswith("stft_bin_")],
                      key=lambda c: int(c.split("_")[-1]))[1:]  # skip bin_0
power_matrix = wm.df[bin_cols].to_numpy()          # (n_windows, N_LOG_BINS-1)
window_ids   = wm.df.index.to_numpy()              # start_idx values in order

# Recover the shared bin-centre frequencies for the y-axis tick labels
bin_freqs, _ = stft_log_spectrum(
    wm.get_window_signal(window_ids[0]),
    fs=wm._fs, window_size=STFT_WINDOW, hop_size=STFT_HOP,
    n_log_bins=N_LOG_BINS, return_2d=False,
)
bin_freqs = bin_freqs[1:]   # drop first bin to match power_matrix columns

def _imshow_power(ax, mat, ids, vmin, vmax, title):
    """Plot a power matrix on ax with shared log colour scale."""
    # Clip any non-positive values before applying LogNorm
    safe_mat = np.clip(mat, a_min=max(vmin, 1e-30), a_max=None)
    im = ax.imshow(
        safe_mat.T,                 # rows = freq bins, cols = windows
        aspect="auto",
        origin="lower",             # bin 0 at bottom
        norm=LogNorm(vmin=vmin, vmax=vmax),
        cmap="inferno",
        extent=[0, mat.shape[0], 0, mat.shape[1]],
    )
    # x-axis: show a handful of window start-index labels
    n_xticks = min(8, mat.shape[0])
    xtick_pos = np.linspace(0, mat.shape[0] - 1, n_xticks, dtype=int)
    ax.set_xticks(xtick_pos + 0.5)
    ax.set_xticklabels(ids[xtick_pos], rotation=45, ha="right", fontsize=7)
    # y-axis: log-frequency bin centres (a handful of representative values)
    n_yticks = min(8, len(bin_freqs))
    ytick_pos = np.linspace(0, len(bin_freqs) - 1, n_yticks, dtype=int)
    ax.set_yticks(ytick_pos + 0.5)
    ax.set_yticklabels([f"{bin_freqs[i]:.4f}" for i in ytick_pos], fontsize=7)
    ax.set_xlabel("Window start index")
    ax.set_ylabel("Log-freq bin centre (Hz)")
    ax.set_title(title)
    return im

# --- 1. All windows ---
fig1, ax1 = py.subplots(figsize=(12, 5))
vmin_all = max(power_matrix[power_matrix > 0].min(), 1e-30)
vmax_all = power_matrix.max()
im1 = _imshow_power(ax1, power_matrix, window_ids, vmin_all, vmax_all,
                    "STFT log-power — all windows")
py.colorbar(im1, ax=ax1, label="Power")
py.tight_layout()
py.show()

# --- 2 & 3. Per-category with shared colour scale ---
cat_col = wm.get_column("category")

mask_int    = (cat_col == "interesting").values
mask_notint = (cat_col == "notinteresting").values

pm_int    = power_matrix[mask_int]
pm_notint = power_matrix[mask_notint]
ids_int    = window_ids[mask_int]
ids_notint = window_ids[mask_notint]

# Shared colour limits across both category plots
combined = np.concatenate([pm_int.ravel(), pm_notint.ravel()])
vmin_cat = max(combined[combined > 0].min(), 1e-30)
vmax_cat = combined.max()

fig2, (ax2, ax3) = py.subplots(2, 1, figsize=(12, 9), sharex=False)

im2 = _imshow_power(ax2, pm_int,    ids_int,    vmin_cat, vmax_cat, "STFT log-power — interesting")
im3 = _imshow_power(ax3, pm_notint, ids_notint, vmin_cat, vmax_cat, "STFT log-power — not interesting")

# Single shared colourbar on the right
fig2.subplots_adjust(right=0.88, hspace=0.45)
cbar_ax = fig2.add_axes([0.91, 0.15, 0.02, 0.7])
py.colorbar(im3, cax=cbar_ax, label="Power")

py.show()

# ------------------------------------------------------------------ #
#  Entropy scatter plot — colour coded by category                    #
# ------------------------------------------------------------------ #


# notintvalues = wm2.get_column("cnn_1_minus_p_notinteresting")

# ------------------------------------------------------------------ #
#  Signal + CNN score overlay plot                                    #
# ------------------------------------------------------------------ #

