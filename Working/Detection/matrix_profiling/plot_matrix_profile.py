
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
from Working.Preprocessing.manage_data.load_data import load_raw_data

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
        npz_path = f"Results/Detection/matrix_profile/mp_{os.path.splitext(filename)[0]}_WIN{winsize}.npz"
    
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
        npz_path = f"Results/Detection/matrix_profile/mp_{os.path.splitext(filename)[0]}.npz"
    
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
        npz_path = f"Results/Detection/matrix_profile/mp_{os.path.splitext(filename)[0]}_WIN{winsize}.npz"

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
        npz_path = (f"Results/Detection/matrix_profile/"
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
    # ax_sig spans the full width to the right figure edge;
    # ax_wave stops at WAVE_R to leave room for the outside legend.
    LPAD   = 0.06
    RPAD   = 0.03
    WAVE_R = 0.78
    VGAP   = 0.10
    PLOT_T = 0.92
    PLOT_B = 0.14

    panel_h = (PLOT_T - PLOT_B - VGAP) / 2
    sig_b   = PLOT_T - panel_h
    wave_b  = PLOT_B

    fig = plt.figure(figsize=(18, 9))
    ax_sig  = fig.add_axes([LPAD, sig_b,  1.0 - RPAD - LPAD, panel_h])
    ax_wave = fig.add_axes([LPAD, wave_b, WAVE_R - LPAD,      panel_h])

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
        ax_sig.plot(t_hours, x_mv, linewidth=0.55, color='steelblue', alpha=0.68)
        ax_sig.set_ylabel('Signal (mV)', fontsize=11)
        ax_sig.set_xlabel('Time (hours)', fontsize=11)
        ax_sig.set_title(
            f'Motif {i + 1} / {len(slides)}   '
            f'seed @ {seed_t:.3f} h   MP distance = {mp_val:.4f}',
            fontsize=12)

        yrange  = ymax - ymin
        arrow_y = ymax + 0.04 * yrange

        for k, nb_idx in enumerate(occurrences):
            color = PALETTE[k % len(PALETTE)]
            nb_t  = t_hours[min(nb_idx, len(t_hours) - 1)]
            alpha = 0.60 if k == 0 else 0.28
            lw    = 1.5  if k == 0 else 0.5
            ax_sig.add_patch(
                Rectangle((nb_t, ymin), window_hours, yrange,
                           facecolor=color, edgecolor=color,
                           linewidth=lw, alpha=alpha, zorder=2))
            ax_sig.plot(nb_t + window_hours / 2, arrow_y,
                        marker='v', markersize=10 if k == 0 else 7,
                        color=color, alpha=min(alpha * 1.8, 1.0),
                        markeredgewidth=0, zorder=5)

        ax_sig.set_ylim(ymin, ymax + 0.13 * yrange)

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
        ax_wave.legend(fontsize=7, loc='upper left', bbox_to_anchor=(1.02, 1.0),
                        ncol=1, framealpha=0.65, handlelength=1.1, borderaxespad=0)

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

def plot_seed_chain(filename, fs, seed_idx, winsize=10, npz_path="",
                    n_neighbors=10, normalize=True,
                    max_distance=None, exclusion_zone=None,
                    show_envelope=True, interactive=True):
    """
    Query-by-example motif search: given a seed window index, retrieve and
    visualise the most similar windows across the entire signal using the
    pre-computed matrix profile.

    Layout
    ------
    Left           : seed window in original (mV) scale — the query motif.
    Top-right      : full signal with seed (gold) and all neighbours highlighted.
    Bottom-right   : all occurrences overlaid on a shared z-normalised axis with
                     optional mean ± 1-std envelope.

    Interactive controls  (interactive=True)
    ----------------------------------------
    ← / →           shift seed by ±1 sample and immediately recompute.
    Shift + ← / →   shift seed by ±10 samples.
    On-screen buttons: ◀◀ -10 | ◀ -1 | +1 ▶ | +10 ▶▶
    Slider           drag to any position in the signal.

    Parameters
    ----------
    filename       : str    Signal file name (passed to load_raw_data).
    fs             : float  Sampling rate in Hz.
    seed_idx       : int    Starting sample index of the query motif.
    winsize        : int    Window size in minutes (for default npz_path).
    npz_path       : str    Path to .npz produced by run_matrix_profile.py.
    n_neighbors    : int    Nearest neighbours to retrieve (default 10).
    normalize      : bool   Z-normalise waveforms in the overlay plot.
    max_distance   : float  Maximum MP distance for a neighbour; None = no filter.
    exclusion_zone : int    Samples to exclude around the seed (default m // 2).
    show_envelope  : bool   Overlay mean ± 1-std envelope on the waveform plot.
    interactive    : bool   Enable interactive seed-adjustment controls.
    """
    from matplotlib.widgets import Button, Slider

    # ── Data ─────────────────────────────────────────────────────────────────────
    x, t = load_raw_data(filename, fs)
    t_hours = t / 3600.0

    if npz_path == "":
        npz_path = (f"Results/Detection/matrix_profile/"
                    f"mp_{os.path.splitext(filename)[0]}_WIN{winsize}.npz")

    data = np.load(npz_path)
    mp   = data['mp'].astype(float)
    m    = int(data['m'])

    if exclusion_zone is None:
        exclusion_zone = m // 2

    x_mv         = x * 1000
    ymin, ymax   = x_mv.min(), x_mv.max()
    window_hours = m / fs / 3600.0
    t_win_s      = np.arange(m) / fs          # relative x-axis in seconds
    n_valid      = len(x) - m + 1             # valid window starts in the full signal

    if seed_idx >= len(mp):
        print(f"Note: seed_idx={seed_idx} is beyond the matrix profile length "
              f"({len(mp)} positions). MP value will show as NaN for this seed, "
              f"but stumpy.match will still search the full signal.")

    PALETTE = [
        'tomato', 'steelblue', 'mediumseagreen', 'darkorange', 'mediumpurple',
        'deeppink', 'teal', 'goldenrod', 'coral', 'slategray',
    ]
    SEED_COLOR = 'gold'

    # ── Neighbour retrieval ───────────────────────────────────────────────────────
    def _get_neighbors(seed):
        if seed < 0 or seed + m > len(x):
            return np.array([]).reshape(0, 2)
        Q     = x[seed : seed + m]
        max_d = max_distance if max_distance is not None else np.inf
        try:
            matches = stumpy.match(
                Q, x,
                max_matches=n_neighbors,
                max_distance=max_d,
                query_idx=seed,
            )
        except Exception as e:
            print(f"  stumpy.match failed: {e}")
            matches = np.array([]).reshape(0, 2)
        return matches

    # ── Figure ────────────────────────────────────────────────────────────────────
    bottom_margin = 0.18 if interactive else 0.08
    fig = plt.figure(figsize=(20, 9))
    fig.suptitle(f'Seed Chain Explorer — {filename}', fontsize=13, fontweight='bold')

    # Layout constants — ax_sig spans full right width (to RPAD);
    # ax_wave stops at WAVE_R to leave room for the outside legend.
    LPAD   = 0.07
    RPAD   = 0.03
    SEED_W = 0.19
    HGAP   = 0.03
    WAVE_R = 0.78
    VGAP   = 0.045
    PLOT_T = 0.91

    right_l = LPAD + SEED_W + HGAP                          # left edge of right panels
    panel_h = (PLOT_T - bottom_margin - VGAP) / 2           # height of each right panel
    sig_b   = PLOT_T - panel_h                               # bottom of top-right panel
    wave_b  = bottom_margin                                  # bottom of bottom-right panel

    ax_seed = fig.add_axes([LPAD,    bottom_margin, SEED_W,               PLOT_T - bottom_margin])
    ax_sig  = fig.add_axes([right_l, sig_b,         1.0 - RPAD - right_l, panel_h])
    ax_wave = fig.add_axes([right_l, wave_b,         WAVE_R - right_l,    panel_h])

    # ── Widget axes (only created when interactive) ───────────────────────────────
    state = {'seed': int(np.clip(seed_idx, 0, n_valid - 1))}

    if interactive:
        # 8 buttons of width 0.06, starting at 0.07, ending at 0.55
        ax_slider = fig.add_axes([0.07,  0.105, 0.48,  0.025])
        ax_m500   = fig.add_axes([0.07,  0.040, 0.06,  0.042])
        ax_m100   = fig.add_axes([0.13,  0.040, 0.06,  0.042])
        ax_m10    = fig.add_axes([0.19,  0.040, 0.06,  0.042])
        ax_m1     = fig.add_axes([0.25,  0.040, 0.06,  0.042])
        ax_p1     = fig.add_axes([0.31,  0.040, 0.06,  0.042])
        ax_p10    = fig.add_axes([0.37,  0.040, 0.06,  0.042])
        ax_p100   = fig.add_axes([0.43,  0.040, 0.06,  0.042])
        ax_p500   = fig.add_axes([0.49,  0.040, 0.06,  0.042])
        ax_info   = fig.add_axes([0.57,  0.018, 0.40,  0.075])
        ax_info.axis('off')
        info_txt  = ax_info.text(0.02, 0.5, '', va='center', fontsize=9.5,
                                  transform=ax_info.transAxes)

        slider   = Slider(ax_slider, 'Seed idx', 0, n_valid - 1,
                          valinit=state['seed'], valstep=1)
        btn_m500 = Button(ax_m500, '◀◀◀ -500')
        btn_m100 = Button(ax_m100, '◀◀ -100')
        btn_m10  = Button(ax_m10,  '◀◀ -10')
        btn_m1   = Button(ax_m1,   '◀ -1')
        btn_p1   = Button(ax_p1,   '+1 ▶')
        btn_p10  = Button(ax_p10,  '+10 ▶▶')
        btn_p100 = Button(ax_p100, '+100 ▶▶')
        btn_p500 = Button(ax_p500, '+500 ▶▶▶')

    # ── Draw ─────────────────────────────────────────────────────────────────────
    def _draw(seed):
        seed = int(np.clip(seed, 0, n_valid - 1))
        state['seed'] = seed

        matches        = _get_neighbors(seed)
        n_shown        = len(matches)
        neighbor_idxs  = [int(matches[k, 1]) for k in range(n_shown)]
        neighbor_dists = [float(matches[k, 0]) for k in range(n_shown)]
        all_idxs       = [seed] + neighbor_idxs

        seed_t  = t_hours[seed]
        mp_val  = mp[seed] if seed < len(mp) else float('nan')

        # ── Left: seed window (original mV scale) ─────────────────────────
        ax_seed.cla()
        ax_seed.plot(t_win_s, x_mv[seed : seed + m],
                     linewidth=1.8, color=SEED_COLOR, zorder=3)
        ax_seed.set_title(f'Seed Window\n@ {seed_t:.5f} h  (idx {seed})',
                          fontsize=11, fontweight='bold')
        ax_seed.set_xlabel('Time within window (s)', fontsize=10)
        ax_seed.set_ylabel('Signal (mV)', fontsize=10)
        ax_seed.text(0.97, 0.97, f'MP = {mp_val:.4f}',
                     transform=ax_seed.transAxes, ha='right', va='top',
                     fontsize=9, color='dimgray',
                     bbox=dict(boxstyle='round,pad=0.3', fc='white', alpha=0.7))

        # ── Top-right: full signal + patches ─────────────────────────────
        ax_sig.cla()
        ax_sig.plot(t_hours, x_mv, linewidth=0.55, color='steelblue', alpha=0.68)

        yrange  = ymax - ymin
        arrow_y = ymax + 0.04 * yrange   # triangle tip sits just above signal peak

        # Neighbours (draw first; seed on top)
        for k, (nb_idx, dist) in enumerate(zip(neighbor_idxs, neighbor_dists)):
            nb_t  = t_hours[min(nb_idx, len(t_hours) - 1)]
            color = PALETTE[k % len(PALETTE)]
            sim   = 1.0 / (1.0 + dist)
            alpha = float(np.clip(0.20 + 0.40 * sim, 0.15, 0.60))
            ax_sig.add_patch(
                Rectangle((nb_t, ymin), window_hours, yrange,
                           facecolor=color, edgecolor=color,
                           linewidth=0.5, alpha=alpha, zorder=2))
            ax_sig.plot(nb_t + window_hours / 2, arrow_y,
                        marker='v', markersize=7, color=color,
                        alpha=min(alpha * 1.8, 1.0), markeredgewidth=0, zorder=5)

        # Seed patch + triangle (opaque gold, on top)
        ax_sig.add_patch(
            Rectangle((seed_t, ymin), window_hours, yrange,
                       facecolor=SEED_COLOR, edgecolor='darkorange',
                       linewidth=1.5, alpha=0.85, zorder=3))
        ax_sig.plot(seed_t + window_hours / 2, arrow_y,
                    marker='v', markersize=10, color='darkorange',
                    markeredgewidth=0, zorder=6)

        ax_sig.set_ylim(ymin, ymax + 0.13 * yrange)   # headroom for triangles
        ax_sig.set_title(
            f'Full Signal   seed @ {seed_t:.4f} h   '
            f'MP = {mp_val:.4f}   neighbours = {n_shown}',
            fontsize=11)
        ax_sig.set_xlabel('Time (hours)', fontsize=10)
        ax_sig.set_ylabel('Signal (mV)', fontsize=10)

        # ── Bottom-right: z-normalised overlay ───────────────────────────
        ax_wave.cla()
        normalised_stack = []

        for k, idx in enumerate(all_idxs):
            snippet = x_mv[idx : idx + m]
            if len(snippet) < m:
                continue
            if normalize:
                std   = snippet.std()
                norm_s = ((snippet - snippet.mean()) / std
                          if std > 0 else snippet - snippet.mean())
            else:
                norm_s = snippet
            normalised_stack.append(norm_s)

            color = SEED_COLOR if k == 0 else PALETTE[(k - 1) % len(PALETTE)]
            lw    = 2.2 if k == 0 else 0.9
            alpha = 1.0 if k == 0 else 0.55
            nb_t  = t_hours[min(idx, len(t_hours) - 1)]

            if k == 0:
                label = f'SEED @ {nb_t:.3f} h'
            else:
                dist  = neighbor_dists[k - 1]
                sim   = 1.0 / (1.0 + dist)
                label = f'nb{k} @ {nb_t:.3f} h  d={dist:.3f}  sim={sim:.2f}'

            ax_wave.plot(t_win_s, norm_s, linewidth=lw, color=color,
                         alpha=alpha, label=label,
                         zorder=4 if k == 0 else 2)

        # Mean ± 1-std envelope across neighbours (not the seed)
        if show_envelope and len(normalised_stack) > 2:
            stack = np.array(normalised_stack[1:])
            mu    = stack.mean(axis=0)
            sigma = stack.std(axis=0)
            ax_wave.plot(t_win_s, mu, color='black', linewidth=1.6,
                         linestyle='--', zorder=5, label='neighbour mean')
            ax_wave.fill_between(t_win_s, mu - sigma, mu + sigma,
                                  alpha=0.12, color='black', zorder=1,
                                  label='±1 std')

        y_label = 'Z-score' if normalize else 'Signal (mV)'
        ax_wave.set_xlabel('Time within window (s)', fontsize=10)
        ax_wave.set_ylabel(y_label, fontsize=10)
        ax_wave.set_title('Nearest-neighbour overlay (z-normalised)', fontsize=11)
        ax_wave.legend(fontsize=7, loc='upper left', bbox_to_anchor=(1.02, 1.0),
                        ncol=1, framealpha=0.65, handlelength=1.1, borderaxespad=0)

        # ── Info bar & console summary ────────────────────────────────────
        if interactive:
            slider.set_val(seed)
            info_txt.set_text(
                f'Seed idx: {seed}   |   {seed_t:.5f} h   |   '
                f'{n_shown} neighbour(s)   |   MP = {mp_val:.4f}\n'
                f'← →: ±1  |  Shift+←→: ±10  |  Ctrl+←→: ±100  |  Ctrl+Shift+←→: ±500'
            )

        print(f"\nSeed idx={seed}  @ {seed_t:.5f} h  MP={mp_val:.4f}")
        for k, (nb_idx, dist) in enumerate(zip(neighbor_idxs, neighbor_dists)):
            nb_t = t_hours[min(nb_idx, len(t_hours) - 1)]
            sim  = 1.0 / (1.0 + dist)
            print(f"  nb{k+1:2d}  idx={nb_idx:<8d} @ {nb_t:.5f} h  "
                  f"dist={dist:.4f}  sim={sim:.4f}")

        fig.canvas.draw_idle()

    _draw(state['seed'])

    if not interactive:
        plt.show()
        return fig

    # ── Widget callbacks ──────────────────────────────────────────────────────────
    def _shift(delta):
        _draw(state['seed'] + delta)

    def _on_slider(val):
        s = int(round(slider.val))
        if s != state['seed']:
            _draw(s)

    btn_m500.on_clicked(lambda _: _shift(-500))
    btn_m100.on_clicked(lambda _: _shift(-100))
    btn_m10.on_clicked(lambda _:  _shift(-10))
    btn_m1.on_clicked(lambda _:   _shift(-1))
    btn_p1.on_clicked(lambda _:   _shift(+1))
    btn_p10.on_clicked(lambda _:  _shift(+10))
    btn_p100.on_clicked(lambda _: _shift(+100))
    btn_p500.on_clicked(lambda _: _shift(+500))
    slider.on_changed(_on_slider)

    def _on_key(event):
        if   event.key == 'left':               _shift(-1)
        elif event.key == 'right':              _shift(+1)
        elif event.key == 'shift+left':         _shift(-10)
        elif event.key == 'shift+right':        _shift(+10)
        elif event.key == 'ctrl+left':          _shift(-100)
        elif event.key == 'ctrl+right':         _shift(+100)
        elif event.key == 'ctrl+shift+left':    _shift(-500)
        elif event.key == 'ctrl+shift+right':   _shift(+500)

    fig.canvas.mpl_connect('key_press_event', _on_key)

    plt.show()
    return fig

if False:
    print("")



# ── Demo drivers ──────────────────────────────────────────────────────────────
# These were previously at module level, which fired an interactive plot on
# every `import`.  Guarded so this file can be imported as a library.
if __name__ == "__main__":
    _RESULTS = "Results/Detection/matrix_profile"

    #plot_matrix_profile("M2_concat_fs1_CH0.npy", 1, npz_path=f"{_RESULTS}/0_mp_M2_concat_fs1_CH0.npz")
    #plot_matrix_discords("M2_concat_fs1_CH0.npy", 1, npz_path=f"{_RESULTS}/1_mp_M2_concat_fs1_CH0.npz")
    #plot_best_motifs("M2_concat_fs1_CH0.npy", 1, npz_path=f"{_RESULTS}/1_mp_M2_concat_fs1_CH0.npz", max_motifs=10)

    #plot_motif_slideshow("M2_concat_fs1_CH0.npy", fs=1,
    #                     npz_path=f"{_RESULTS}/1_mp_M2_concat_fs1_CH0_WIN1.npz",
    #                     max_motifs=1000, n_neighbors=10)

    plot_seed_chain(
        "M2_concat_fs1_CH2.npy", fs=1, seed_idx=104078,
        npz_path=f"{_RESULTS}/1_mp_M2_concat_fs1_CH2_WIN50.npz",
        n_neighbors=10, max_distance=None, show_envelope=True, interactive=True)
