import matplotlib.pyplot as py
from matplotlib.colors import LogNorm
from Working.Preprocessing.manage_data.load_data import load_raw_data
import numpy as np
import pandas as pd
from Working.Detection.analysis.freq_analysis import stft_log_spectrum
from Working.Preprocessing.window_matrix.matrix_calc import *

def plot_cnn_columns(wm,filename,TIMESCALE,FS,matname='x'):
    x, t = load_raw_data(filename,FS,matname)

    window_samples = int(TIMESCALE * 60 * FS)   # 600 samples
    intvalues = wm.get_column("cnn_p_interesting")

    # x-axis for the score: mid-point of each window in seconds
    score_starts  = wm.df.index.to_numpy()                        # sample indices
    score_t_mid   = (score_starts + window_samples / 2) / FS   # seconds

    t_hours       = t / 3600.0
    score_t_hours = score_t_mid / 3600.0

    fig, (ax_sig, ax_score) = py.subplots(
        2, 1, figsize=(16, 6),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )

    # ── Top: raw signal ───────────────────────────────────────────────
    ax_sig.plot(t_hours, x * 1000, color="steelblue", linewidth=0.4, alpha=0.8)
    ax_sig.set_ylabel("Signal amplitude")
    ax_sig.set_title(f"{filename} — raw signal and CNN interesting score")

    # ── Bottom: CNN score ─────────────────────────────────────────────
    ax_score.step(score_t_hours, intvalues.to_numpy(),
                where="mid", color="tomato", linewidth=1.0)
    ax_score.fill_between(score_t_hours, intvalues.to_numpy(),
                        step="mid", alpha=0.25, color="tomato")
    ax_score.set_ylim(0, 1)
    ax_score.set_ylabel("P(interesting)")
    ax_score.set_xlabel("Time (hours)")
    ax_score.axhline(0.5, color="gray", linewidth=0.7, linestyle="--")

    py.tight_layout()
    py.show()
    
def plot_fusion_prediction_v1_error(wm, filename, TIMESCALE, FS, matname="VECTOR"):
    x, t = load_raw_data(filename, FS, matname)

    window_samples = int(TIMESCALE * 60 * FS)
    error_values = wm.get_column("fusion_pred_v1_error")

    # x-axis: mid-point of each window in hours
    score_starts  = wm.df.index.to_numpy()
    score_t_mid   = (score_starts + window_samples / 2) / FS
    t_hours       = t / 3600.0
    score_t_hours = score_t_mid / 3600.0

    error_arr = error_values.to_numpy().astype(float)

    fig, (ax_sig, ax_err) = py.subplots(
        2, 1, figsize=(16, 6),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )

    # ── Top: raw signal ───────────────────────────────────────────────
    ax_sig.plot(t_hours, x * 1000, color="steelblue", linewidth=0.4, alpha=0.8)
    ax_sig.set_ylabel("Signal amplitude")
    ax_sig.set_title(f"{filename} — raw signal and fusion prediction v1 error")

    # ── Bottom: prediction error ──────────────────────────────────────
    ax_err.step(score_t_hours, error_arr, where="mid", color="darkorange", linewidth=1.0)
    ax_err.fill_between(score_t_hours, error_arr, step="mid", alpha=0.25, color="darkorange")
    ax_err.set_ylabel("Prediction error")
    ax_err.set_xlabel("Time (hours)")
    ax_err.axhline(0, color="gray", linewidth=0.7, linestyle="--")

    py.tight_layout()
    py.show()

def plot_wm_signal(wm):
    x = wm.get_entire_signal()
    fs = wm._fs
    t = np.linspace(0,len(x)*fs,len(x))
    py.plot(t/3600,x*1000)
    py.xlabel("Time (hr)")
    py.ylabel("Signal (mV)")
    py.show()

_PALETTE = [
    "tomato", "darkorange", "mediumseagreen", "mediumpurple",
    "saddlebrown", "deeppink", "teal", "goldenrod",
    "coral", "slategray",
]


def _scalar_column_names(wm, colnames):
    """
    Return the list of columns to plot.

    If colnames is None or empty, auto-detect: skip vector-type columns and
    any column whose values cannot be meaningfully cast to float.
    Uses pd.to_numeric(..., errors='coerce') so object-dtype columns (e.g.
    catch22 values read back from CSV) are handled correctly.
    """
    if colnames:
        return list(colnames)
    result = []
    for name in wm.columns:
        if wm._meta.get(name, {}).get("type") == "vector":
            continue
        numeric = pd.to_numeric(wm.get_column(name), errors="coerce")
        if numeric.notna().any():
            result.append(name)
    return result


def _style_checkboxes(chk, colors):
    """
    Color CheckButtons indicators and labels.

    'rectangles' was removed in matplotlib 3.7; fall back gracefully so the
    labels (which are always present) still carry the color information.
    """
    boxes = getattr(chk, "rectangles", None)
    if boxes is not None:
        for box, color in zip(boxes, colors):
            box.set_facecolor(color)
            box.set_alpha(0.5)
    for lbl, color in zip(chk.labels, colors):
        lbl.set_color(color)


def plot_singlevalue_columns(wm, colnames=None, overlay=False, figsize=None):
    """
    Plot one or more scalar WindowMatrix columns alongside the raw signal.

    Parameters
    ----------
    wm       : WindowMatrix
    colnames : list of str, optional
        Columns to plot.  If None or empty, all single-value numeric columns
        are plotted automatically (vector columns are excluded).
    overlay  : bool
        False (default) — each column gets its own subplot stacked below the
        signal, sharing the time axis.
        True            — all columns are normalised to [0, 1] and drawn on a
                          twin y-axis overlaid on the signal plot.
    figsize  : (width, height) tuple, optional

    Returns
    -------
    matplotlib.figure.Figure

    Interaction
    -----------
    A checkbox panel lets you toggle individual column traces on/off.
    In stacked mode the corresponding y-label dims when hidden.
    """
    from matplotlib.widgets import CheckButtons

    cols = _scalar_column_names(wm, colnames)
    if not cols:
        raise ValueError("No scalar numeric columns found in WindowMatrix.")

    x           = wm._x
    fs          = wm._fs
    win_samples = wm._window_samples
    t_sig       = np.arange(len(x)) / fs / 3600.0          # hours
    starts      = wm.df.index.to_numpy()
    t_mid       = (starts + win_samples / 2) / fs / 3600.0  # window mid-points, hours

    n_cols = len(cols)
    colors = [_PALETTE[i % len(_PALETTE)] for i in range(n_cols)]
    col_data = {
        name: pd.to_numeric(wm.get_column(name), errors="coerce").to_numpy(dtype=float)
        for name in cols
    }

    # ── Overlay mode ──────────────────────────────────────────────────────────
    if overlay:
        if figsize is None:
            figsize = (18, 5)
        fw, fh = figsize
        fig = py.figure(figsize=(fw, fh))

        chk_h  = min(0.82, max(0.12, 0.06 * n_cols + 0.06))
        ax_sig  = fig.add_axes([0.06, 0.12, 0.70, 0.80])
        ax_twin = ax_sig.twinx()
        ax_chk  = fig.add_axes([0.79, max(0.10, 0.92 - chk_h), 0.18, chk_h])

        # Signal
        ax_sig.plot(t_sig, x * 1000, color="steelblue", linewidth=0.4, alpha=0.6)
        ax_sig.set_xlabel("Time (hours)")
        ax_sig.set_ylabel("Signal (mV)", color="steelblue")
        ax_sig.tick_params(axis="y", labelcolor="steelblue")
        ax_sig.set_title("WindowMatrix columns — overlay")

        # Columns: normalised to [0, 1] on twin axis
        ax_twin.set_ylabel("Normalised [0–1]", fontsize=9)
        ax_twin.set_ylim(-0.05, 1.05)

        lines, fills = {}, {}
        for name, color in zip(cols, colors):
            v    = col_data[name]
            vr   = np.nanmax(v) - np.nanmin(v)
            vnorm = (v - np.nanmin(v)) / vr if vr > 0 else np.full_like(v, 0.5)
            line, = ax_twin.step(t_mid, vnorm, where="mid",
                                  color=color, linewidth=1.2, alpha=0.85)
            fill  = ax_twin.fill_between(t_mid, vnorm, step="mid",
                                          color=color, alpha=0.15)
            lines[name], fills[name] = line, fill

        # Checkboxes
        chk = CheckButtons(ax_chk, cols, [True] * n_cols)
        _style_checkboxes(chk, colors)

        def _toggle_overlay(label):
            vis = not lines[label].get_visible()
            lines[label].set_visible(vis)
            fills[label].set_visible(vis)
            for lbl in chk.labels:
                if lbl.get_text() == label:
                    lbl.set_alpha(1.0 if vis else 0.30)
            fig.canvas.draw_idle()

        chk.on_clicked(_toggle_overlay)

    # ── Stacked subplots mode ─────────────────────────────────────────────────
    else:
        if figsize is None:
            figsize = (16, 3 + 1.5 * n_cols)
        fw, fh = figsize

        fig, axes = py.subplots(
            1 + n_cols, 1, figsize=(fw, fh), sharex=True,
            gridspec_kw={"height_ratios": [3] + [1] * n_cols, "hspace": 0.06},
        )
        fig.subplots_adjust(right=0.78)

        ax_sig = axes[0]
        ax_sig.plot(t_sig, x * 1000, color="steelblue", linewidth=0.4, alpha=0.8)
        ax_sig.set_ylabel("Signal (mV)")
        ax_sig.set_title("WindowMatrix columns")

        col_axes, lines, fills = {}, {}, {}
        for i, (name, color) in enumerate(zip(cols, colors)):
            ax = axes[i + 1]
            v  = col_data[name]
            line, = ax.step(t_mid, v, where="mid", color=color, linewidth=1.0)
            fill  = ax.fill_between(t_mid, v, step="mid", color=color, alpha=0.20)
            ax.set_ylabel(name, fontsize=8, color=color)
            ax.yaxis.set_tick_params(labelsize=7)
            if i == n_cols - 1:
                ax.set_xlabel("Time (hours)")
            col_axes[name], lines[name], fills[name] = ax, line, fill

        # Checkboxes — right margin, vertically centred
        chk_h  = min(0.85, max(0.10, 0.055 * n_cols + 0.05))
        ax_chk = fig.add_axes([0.80, max(0.05, 0.95 - chk_h), 0.17, chk_h])
        chk = CheckButtons(ax_chk, cols, [True] * n_cols)
        _style_checkboxes(chk, colors)

        def _toggle_stacked(label):
            vis = not lines[label].get_visible()
            lines[label].set_visible(vis)
            fills[label].set_visible(vis)
            # Dim the y-label and tick text when hidden
            color = col_axes[label].yaxis.get_label().get_color()
            col_axes[label].set_ylabel(
                label, fontsize=8,
                color="lightgray" if not vis else color,
            )
            for lbl in chk.labels:
                if lbl.get_text() == label:
                    lbl.set_alpha(1.0 if vis else 0.30)
            fig.canvas.draw_idle()

        chk.on_clicked(_toggle_stacked)

    py.show()
    return fig