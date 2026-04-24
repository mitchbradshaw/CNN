
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

    x = x[:10000]
    t = t[:10000]
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


# ── Motif slideshow ────────────────────────────────────────────────────────────
def plot_motif_slideshow(filename, fs, winsize=10, npz_path="",
                         max_motifs=20, n_neighbors=10):
    """
    Interactive slideshow of top motifs ordered by significance (lowest matrix-
    profile distance first).  For each slide, the motif seed and its n_neighbors
    closest matches are found with stumpy.match and highlighted on the signal.

    Layout
    ------
    Top    : full raw signal; seed patch (opaque) + neighbour patches (translucent).
    Bottom : all occurrences overlaid on a common relative time axis.

    Navigation
    ----------
    Left / right arrow keys  or  on-screen Prev / Next buttons.

    Exclusion
    ---------
    Any window already shown as a neighbour of an earlier slide is skipped as a
    future seed (exclusion zone = m // 2 samples either side).

    Parameters
    ----------
    filename    : str   Signal file passed to load_raw_data.
    fs          : float Sampling rate in Hz.
    winsize     : int   Window size in minutes (used to build default npz_path).
    npz_path    : str   Path to .npz produced by run_matrix_profile.py.
    max_motifs  : int   Maximum slides to pre-compute (default 20).
    n_neighbors : int   Nearest neighbours to show per slide (default 10).
    """
    from matplotlib.widgets import Button

    x, t = load_raw_data(filename, fs)
    t_hours = t / 3600.0

    if npz_path == "":
        npz_path = (f"matrix_profiling/results/"
                    f"mp_{os.path.splitext(filename)[0]}_WIN{winsize}.npz")

    data = np.load(npz_path)
    mp   = data['mp'].astype(float)
    m    = int(data['m'])

    excl_zone    = m // 2
    x_mv         = x * 1000
    ymin, ymax   = x_mv.min(), x_mv.max()
    window_hours = m / fs / 3600.0
    t_win_s      = np.arange(m) / fs          # relative x-axis in seconds

    # ── Build slide list ──────────────────────────────────────────────────────
    print("Pre-computing motifs and nearest neighbours — please wait…")
    excluded = np.zeros(len(mp), dtype=bool)
    slides   = []   # list of (seed_idx, matches_array)

    for pos in np.argsort(mp):
        pos = int(pos)
        if excluded[pos] or not np.isfinite(mp[pos]):
            continue

        Q = x[pos : pos + m]
        try:
            matches = stumpy.match(
                Q, x,
                max_matches=n_neighbors,
                max_distance=np.inf,
                query_idx=pos,       # applies exclusion zone around seed
            )
        except Exception:
            continue

        slides.append((pos, matches))

        # Mark seed + every neighbour as excluded for future seeds
        all_nb = [pos] + [int(matches[k, 1]) for k in range(len(matches))]
        for nb in all_nb:
            lo = max(0, nb - excl_zone)
            hi = min(len(excluded), nb + excl_zone + 1)
            excluded[lo:hi] = True

        print(f"  [{len(slides):>2}]  seed @ {t_hours[pos]:.3f} h  "
              f"mp = {mp[pos]:.4f}  neighbours = {len(matches)}")
        if len(slides) >= max_motifs:
            break

    if not slides:
        print("No motifs found.")
        return

    print(f"Done — {len(slides)} slides ready.\n")

    # ── Colours ───────────────────────────────────────────────────────────────
    PALETTE = [
        'tomato', 'steelblue', 'mediumseagreen', 'darkorange', 'mediumpurple',
        'deeppink', 'teal', 'goldenrod', 'coral', 'slategray',
    ]

    # ── Figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(18, 9))
    fig.subplots_adjust(left=0.06, right=0.97, top=0.92, bottom=0.14, hspace=0.38)

    ax_sig  = fig.add_subplot(2, 1, 1)
    ax_wave = fig.add_subplot(2, 1, 2)

    ax_prev = fig.add_axes([0.06,  0.025, 0.12, 0.055])
    ax_next = fig.add_axes([0.82,  0.025, 0.12, 0.055])
    ax_info = fig.add_axes([0.22,  0.025, 0.56, 0.055])
    ax_info.axis('off')
    info_txt = ax_info.text(0.5, 0.5, '', ha='center', va='center',
                             fontsize=11, transform=ax_info.transAxes)

    btn_prev = Button(ax_prev, '◀  Prev')
    btn_next = Button(ax_next, 'Next  ▶')

    state = {'slide': 0}

    def _draw(i):
        seed, matches = slides[i]
        ax_sig.cla()
        ax_wave.cla()

        seed_t  = t_hours[seed]
        mp_val  = mp[seed]
        n_shown = len(matches)

        # All occurrences: seed first, then neighbours sorted closest-first
        occurrences = [seed] + [int(matches[k, 1]) for k in range(n_shown)]

        # ── Signal axes ───────────────────────────────────────────────────
        ax_sig.plot(t_hours, x_mv, linewidth=0.4, color='steelblue', alpha=0.5)
        ax_sig.set_ylabel('Signal (mV)', fontsize=11)
        ax_sig.set_xlabel('Time (hours)', fontsize=11)
        ax_sig.set_title(
            f'Motif {i + 1} / {len(slides)}   '
            f'seed @ {seed_t:.3f} h   MP distance = {mp_val:.4f}',
            fontsize=12)

        for k, nb_idx in enumerate(occurrences):
            color = PALETTE[k % len(PALETTE)]
            nb_t  = t_hours[min(nb_idx, len(t_hours) - 1)]
            alpha = 0.60 if k == 0 else 0.28
            lw    = 1.5  if k == 0 else 0.5
            ax_sig.add_patch(
                Rectangle((nb_t, ymin), window_hours, ymax - ymin,
                           facecolor=color, edgecolor=color,
                           linewidth=lw, alpha=alpha, zorder=2))

        # ── Waveform overlay axes (z-normalised) ─────────────────────────
        for k, nb_idx in enumerate(occurrences):
            snippet = x_mv[nb_idx : nb_idx + m]
            if len(snippet) < m:
                continue
            std = snippet.std()
            normalised = (snippet - snippet.mean()) / std if std > 0 else snippet - snippet.mean()
            color = PALETTE[k % len(PALETTE)]
            nb_t  = t_hours[min(nb_idx, len(t_hours) - 1)]
            lw    = 1.8 if k == 0 else 0.8
            alpha = 0.95 if k == 0 else 0.50
            dist  = 0.0 if k == 0 else float(matches[k - 1, 0])
            label = (f'seed @ {nb_t:.3f} h' if k == 0
                     else f'nb{k} @ {nb_t:.3f} h  d={dist:.3f}')
            ax_wave.plot(t_win_s, normalised, linewidth=lw, color=color,
                         alpha=alpha, label=label)

        ax_wave.set_xlabel('Time within window (s)', fontsize=11)
        ax_wave.set_ylabel('Z-score', fontsize=11)
        ax_wave.set_title('All occurrences overlaid (z-normalised)', fontsize=11)
        ax_wave.legend(fontsize=7, loc='upper right', ncol=3,
                        framealpha=0.6, handlelength=1.2)

        info_txt.set_text(
            f'Slide {i + 1} / {len(slides)}   |   '
            f'{n_shown} neighbour(s) shown   |   '
            f'← / → to navigate'
        )
        fig.canvas.draw_idle()

    _draw(0)

    def on_prev(_):
        if state['slide'] > 0:
            state['slide'] -= 1
            _draw(state['slide'])

    def on_next(_):
        if state['slide'] < len(slides) - 1:
            state['slide'] += 1
            _draw(state['slide'])

    btn_prev.on_clicked(on_prev)
    btn_next.on_clicked(on_next)

    fig.canvas.mpl_connect(
        'key_press_event',
        lambda e: on_prev(e) if e.key == 'left'
                  else on_next(e) if e.key == 'right' else None)

    plt.show()
    return fig


plot_matrix_profile("M2_concat_fs1_CH0.npy",1,npz_path="matrix_profiling/results/0_mp_M2_concat_fs1_CH0.npz")
#plot_matrix_discords("M2_concat_fs1_CH0.npy",1,npz_path="matrix_profiling/results/1_mp_M2_concat_fs1_CH0.npz")
#plot_best_motifs("M2_concat_fs1_CH0.npy",1,npz_path="matrix_profiling/results/1_mp_M2_concat_fs1_CH0.npz",max_motifs=10)

#plot_motif_slideshow("M2_concat_fs1_CH0.npy", fs=1,
 #                    npz_path="matrix_profiling/results/1_mp_M2_concat_fs1_CH0_WIN1.npz",
  #                   max_motifs=1000, n_neighbors=10)
