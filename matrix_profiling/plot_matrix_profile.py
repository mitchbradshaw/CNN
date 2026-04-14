
from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch
import os
import sys
import numpy as np
import stumpy

import pandas as pd
from scipy.io import loadmat
import itertools

plt.style.use('https://raw.githubusercontent.com/stumpy-dev/stumpy/main/docs/stumpy.mplstyle')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from manage_data.load_data import load_raw_data

# ── Profile ────────────────────────────────────────────────────────────────────
def plot_matrix_profile(filename, fs, winsize=10, npz_path=""):
    """
    Plot the raw signal with the top motif pair highlighted, and the
    matrix profile below it, following the stumpy documentation layout.

    Parameters
    ----------
    filename : str
        Signal file name (passed to load_raw_data, e.g. "M2_concat_fs1_CH0.npy").
    fs : float
        Sampling rate in Hz.
    npz_path : str
        Path to the .npz file saved by run_matrix_profile.py.
    """
    x, t = load_raw_data(filename, fs)
    t_hours = t / 3600.0

    if npz_path == "":
        npz_path = f"matrix_profiling/results/mp_{os.path.splitext(filename)[0]}_WIN{winsize}.npz"
    
    # ── Load matrix profile ───────────────────────────────────────────────
    data = np.load(npz_path)
    mp  = data['mp']          # distance profile  (n - m + 1,)
    mpi = data['mpi']         # nearest-neighbour indices
    m   = int(data['m'])      # window length in samples

    motif_idx            = int(np.argsort(mp)[0])
    nearest_neighbor_idx = int(mpi[motif_idx])

    # Convert sample indices → hours to match the signal x-axis
    motif_t          = t_hours[motif_idx]
    nearest_t        = t_hours[nearest_neighbor_idx]
    mp_t             = t_hours[:len(mp)]
    window_hours     = m / fs / 3600.0   # window length in hours

    # ── y-range for highlight rectangles ─────────────────────────────────
    x_mv = x * 1000
    ymin, ymax = x_mv.min(), x_mv.max()

    # ── Plot ──────────────────────────────────────────────────────────────
    fig, axs = plt.subplots(2, sharex=True, gridspec_kw={'hspace': 0})
    plt.suptitle('Motif (Pattern) Discovery', fontsize=30)

    # Top: raw signal
    axs[0].plot(t_hours, x_mv, linewidth=0.5)
    axs[0].set_ylabel('Signal (mV)', fontsize=20)
    for t_start in (motif_t, nearest_t):
        axs[0].add_patch(
            Rectangle((t_start, ymin), window_hours, ymax - ymin,
                       facecolor='lightgrey', alpha=0.7)
        )

    # Bottom: matrix profile
    axs[1].plot(mp_t, mp, linewidth=0.5)
    axs[1].axvline(x=motif_t,          linestyle="dashed", color="tomato")
    axs[1].axvline(x=nearest_t,        linestyle="dashed", color="tomato")
    axs[1].set_xlabel('Time (hours)', fontsize=20)
    axs[1].set_ylabel('Matrix Profile', fontsize=20)

    plt.show()

# ── Discords ────────────────────────────────────────────────────────────────────
def plot_matrix_discords(filename,fs,npz_path=""):
    """
    Plot the raw signal with the bottom motif pair highlighted, and the
    matrix profile below it, following the stumpy documentation layout.

    Parameters
    ----------
    filename : str
        Signal file name (passed to load_raw_data, e.g. "M2_concat_fs1_CH0.npy").
    fs : float
        Sampling rate in Hz.
    npz_path : str
        Path to the .npz file saved by run_matrix_profile.py.
    """
    x, t = load_raw_data(filename, fs)
    x = x[:10000]
    t = t[:10000]
    t_hours = t / 3600.0

    if npz_path == "":
        npz_path = f"matrix_profiling/results/mp_{os.path.splitext(filename)[0]}.npz"
    
    # ── Load matrix profile ───────────────────────────────────────────────
    data = np.load(npz_path)
    mp  = data['mp']          # distance profile  (n - m + 1,)
    mpi = data['mpi']         # nearest-neighbour indices
    m   = int(data['m'])      # window length in samples

    discord_idx  = int(np.argsort(mp)[-1])

    # Convert sample index → hours to match the signal x-axis
    discord_t    = t_hours[discord_idx]
    mp_t         = t_hours[:len(mp)]
    window_hours = m / fs / 3600.0   # window length in hours

    # ── y-range for highlight rectangle ──────────────────────────────────
    x_mv = x * 1000
    ymin, ymax = x_mv.min(), x_mv.max()

    # ── Plot ──────────────────────────────────────────────────────────────
    fig, axs = plt.subplots(2, sharex=True, gridspec_kw={'hspace': 0})
    plt.suptitle('Discord (Anomaly/Novelty) Discovery', fontsize=30)

    # Top: raw signal with discord window highlighted
    axs[0].plot(t_hours, x_mv, linewidth=0.5)
    axs[0].set_ylabel('Signal (mV)', fontsize=20)
    axs[0].add_patch(
        Rectangle((discord_t, ymin), window_hours, ymax - ymin,
                   facecolor='lightgrey', alpha=0.7)
    )

    # Bottom: matrix profile
    axs[1].plot(mp_t, mp, linewidth=0.5)
    axs[1].axvline(x=discord_t, linestyle="dashed", color="tomato")
    axs[1].set_xlabel('Time (hours)', fontsize=20)
    axs[1].set_ylabel('Matrix Profile', fontsize=20)

    plt.show()

# ── Find best motifs ────────────────────────────────────────────────────────────────────
def plot_best_motifs(filename, fs, winsize=10, npz_path="", max_motifs=3):
    """
    Use stumpy.motifs() to find the top recurring patterns and plot them.

    Layout (following stumpy documentation):
      Row 0       : full signal with each motif's occurrences highlighted in colour
      Rows 1..K   : one row per motif, all occurrences overlaid to show the pattern shape

    Parameters
    ----------
    filename   : str    Signal file name passed to load_raw_data.
    fs         : float  Sampling rate in Hz.
    npz_path   : str    Path to the .npz saved by run_matrix_profile.py.
    max_motifs : int    Number of top motifs to find and display (default 3).
    """
    x, t = load_raw_data(filename, fs)
    x = x[:10000]
    t = t[:10000]
    t_hours = t / 3600.0

    if npz_path == "":
        npz_path = f"matrix_profiling/results/mp_{os.path.splitext(filename)[0]}_WIN{winsize}.npz"

    # ── Load matrix profile ───────────────────────────────────────────────
    data = np.load(npz_path)
    mp  = data['mp']        # 1-D distance array  (n - m + 1,)
    m   = int(data['m'])    # window length in samples

    # ── Find motifs ───────────────────────────────────────────────────────
    # stumpy.motifs returns:
    #   mt_dist : (max_motifs,)              — profile distance for each motif
    #   mt_ind  : (max_motifs, max_matches)  — start indices of every occurrence
    #                                          (-1 padding for unused slots)
    mt_dist, mt_ind = stumpy.motifs(x, mp, max_motifs=max_motifs, max_distance=np.inf)

    if mt_ind.size == 0 or all(len(row[row >= 0]) == 0 for row in mt_ind):
        print("No motifs found.")
        return

    x_mv         = x * 1000
    ymin, ymax   = x_mv.min(), x_mv.max()
    window_hours = m / fs / 3600.0
    t_win        = np.arange(m) / fs / 3600.0   # relative x-axis for each occurrence

    # Collect all individual occurrences: [(motif_i, start_idx), ...]
    occurrences = []
    for motif_i, indices in enumerate(mt_ind):
        for idx in indices[indices >= 0]:
            occurrences.append((motif_i, int(idx)))

    # ── Plot ──────────────────────────────────────────────────────────────
    # Row 0: full signal | Rows 1..: one row per individual occurrence
    n_rows = len(occurrences) + 1
    fig, axs = plt.subplots(n_rows, 1, sharex=False,
                            figsize=(16, 3 * n_rows),
                            gridspec_kw={'hspace': 0.4})
    plt.suptitle('Top Motifs (Recurring Patterns)', fontsize=20)

    # Row 0: full signal with each occurrence in its own colour
    axs[0].plot(t_hours, x_mv, linewidth=0.5, color='steelblue')
    axs[0].set_ylabel('Signal (mV)', fontsize=12)
    axs[0].set_xlabel('Time (hours)', fontsize=12)
    for row, (motif_i, idx) in enumerate(occurrences):
        axs[0].add_patch(
            Rectangle((t_hours[idx], ymin), window_hours, ymax - ymin,
                       facecolor=f'C{row % 10}', alpha=0.3)
        )

    # One row per occurrence, each coloured by row
    for row, (motif_i, idx) in enumerate(occurrences):
        ax = axs[row + 1]
        ax.plot(t_win, x_mv[idx : idx + m], linewidth=0.8, color=f'C{row % 10}')
        ax.set_ylabel(f'Motif {motif_i + 1}  occ {row + 1}\n@ {t_hours[idx]:.3f}h', fontsize=11)
        ax.set_xlabel('Window time (hours)', fontsize=11)

    plt.show()


plot_matrix_profile("M2_concat_fs1_CH0.npy",1,"matrix_profiling/results/1_mp_M2_concat_fs1_CH0.npz")
#plot_matrix_discords("M2_concat_fs1_CH0.npy",1,"matrix_profiling/results/0_mp_M2_concat_fs1_CH0.npz")
#plot_best_motifs("M2_concat_fs1_CH0.npy",1,"matrix_profiling/results/0_mp_M2_concat_fs1_CH0.npz")