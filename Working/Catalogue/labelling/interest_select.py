"""
interest_select.py
==================
Interactive window-labelling tool — Python reimplementation of the MATLAB
`interest_select_windows` function.

Browse randomised time-series windows and label each as:
    interesting  /  not interesting  /  flag

On finish (or window close), saves for each labelled category:
    - raw data (.npy)          → DATA/{N}_MINUTES/{N}min_fs{fs}_{label}_rawdata{_suffix}/
    - GASF image (.png)        → DATA/{N}_MINUTES/{N}min_fs{fs}_{label}_GASF{_suffix}/
    - GADF image (.png)        → DATA/{N}_MINUTES/{N}min_fs{fs}_{label}_GADF{_suffix}/
    - recurrence image (.png)  → DATA/{N}_MINUTES/{N}min_fs{fs}_{label}_recurrence{_suffix}/
    - fusion image (.png)      → DATA/{N}_MINUTES/{N}min_fs{fs}_{label}_fusion{_suffix}/

Session (window order + progress) is persisted to:
    DATA/{N}_MINUTES/{N}min/{N}min_session_fs_{fs:.2f}.json

Label index files (start-sample lists) are persisted to:
    DATA/{N}_MINUTES/{N}min/{N}min_{label}_fs_{fs:.2f}.json

Usage
-----
    from interest_select import interest_select_windows
    import scipy.io, numpy as np

    mat = scipy.io.loadmat("DATA/RAW/M2_aug_concat_fs1.mat")
    x   = mat["x"].ravel()
    interest_select_windows(x, fs=1.0, window_min=10, suffix="v1")

Keyboard shortcuts
------------------
    1 / i  – interesting
    2 / n  – not interesting
    3 / f  – flag
    z      – undo (up to 3 steps)
"""

import os
import json
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button

from Working.Catalogue.gramian.gramian_calc import save_gramian_windows


LABELS     = ["interesting", "notinteresting", "flag"]
MAX_UNDO   = 3
SAVE_EVERY = 25


# ── Public API ──────────────────────────────────────────────────────────────

def interest_select_windows(x, fs, window_min, t=None, suffix=""):
    """
    Interactively label windows of a time series.

    Parameters
    ----------
    x          : 1-D array-like  — the raw time series (samples)
    fs         : float           — sample rate (Hz)
    window_min : int | float     — window length in minutes
    t          : array-like, optional
                    Time vector (same length as x).
                    Defaults to np.arange(len(x)) / fs.
    suffix     : str
                    Appended to every output folder name (e.g. "v1", "test").
                    Empty string → no suffix.
    """
    x = np.asarray(x, dtype=float).ravel()
    t = (np.arange(len(x)) / fs) if t is None else np.asarray(t, dtype=float).ravel()

    win_samp  = round(window_min * 60 * fs)
    step_samp = max(1, round(win_samp / 3))

    # ── Path setup ───────────────────────────────────────────────────────
    fs_str      = f"{fs:.2f}"
    win_tag     = f"{window_min:g}min"
    minutes_dir = os.path.join("DATA", f"{window_min:g}_MINUTES")
    index_dir   = os.path.join(minutes_dir, win_tag)
    os.makedirs(index_dir, exist_ok=True)

    session_file = os.path.join(index_dir, f"{win_tag}_session_fs_{fs_str}.json")
    label_files  = {
        lbl: os.path.join(index_dir, f"{win_tag}_{lbl}_fs_{fs_str}.json")
        for lbl in LABELS
    }

    suffix_part = f"_{suffix}" if suffix else ""

    def _out_dir(label, kind):
        return os.path.join(minutes_dir, f"{win_tag}_fs{fs}_{label}_{kind}{suffix_part}")

    # ── Session: resume or start fresh ───────────────────────────────────
    def _new_session():
        starts_ord = np.arange(0, len(x) - win_samp + 1, step_samp)
        perm       = np.random.permutation(len(starts_ord))
        return starts_ord[perm].tolist(), 0

    if os.path.isfile(session_file):
        ans = input(
            f'Previous session found in "{index_dir}". Resume? [Y/n]: '
        ).strip().lower()
        if ans in ("", "y", "yes"):
            with open(session_file) as f:
                sess = json.load(f)
            starts  = sess["starts"]
            current = sess["current"]
            print(f"Resuming — {len(starts) - current} / {len(starts)} windows remaining.")
        else:
            starts, current = _new_session()
    else:
        starts, current = _new_session()

    N = len(starts)
    print(f"{N} windows  |  window={window_min}min  step={window_min/3:.2f}min")

    # ── Load any previously saved label lists (prior sessions) ───────────
    disk_baseline: dict[str, list] = {}
    for lbl in LABELS:
        if os.path.isfile(label_files[lbl]):
            with open(label_files[lbl]) as f:
                d = json.load(f)
            disk_baseline[lbl] = d.get("starts", [])
            print(f'  Existing "{lbl}": {len(disk_baseline[lbl])} entries')
        else:
            disk_baseline[lbl] = []

    # ── Mutable state ────────────────────────────────────────────────────
    this_session: dict[str, list] = {lbl: [] for lbl in LABELS}
    state = {
        "current":    current,
        "undo_stack": [],   # list of {"label", "start", "pos"}
        "since_save": 0,
    }

    # ── Window accessor ──────────────────────────────────────────────────
    def _get_window(i):
        s = starts[i]
        e = min(s + win_samp, len(x))
        return t[s:e], x[s:e]

    # ── Persistence ──────────────────────────────────────────────────────
    def _save_session():
        with open(session_file, "w") as f:
            json.dump({"starts": starts, "current": state["current"]}, f)

    def _save_label_index():
        for lbl in LABELS:
            all_starts = disk_baseline[lbl] + this_session[lbl]
            if not all_starts:
                if os.path.isfile(label_files[lbl]):
                    os.remove(label_files[lbl])
                continue
            with open(label_files[lbl], "w") as f:
                json.dump({
                    "starts":     all_starts,
                    "fs":         fs,
                    "win_samp":   win_samp,
                    "window_min": window_min,
                }, f, indent=2)

    # ── Output saving ─────────────────────────────────────────────────────
    def _save_raw(start_list, lbl):
        folder = _out_dir(lbl, "rawdata")
        os.makedirs(folder, exist_ok=True)
        for s in start_list:
            data = np.stack([x[s:s + win_samp], t[s:s + win_samp]])
            np.save(os.path.join(folder, f"{s}.npy"), data)
        print(f"  [{lbl}] rawdata  → {folder}/  ({len(start_list)} files)")

    def _save_gramians(start_list, lbl):
        save_gramian_windows(x, start_list, window_min, fs, lbl, win_samp, suffix=suffix)

    def _save_all_outputs():
        for lbl in LABELS:
            new_starts = this_session[lbl]
            if not new_starts:
                continue
            print(f"\nSaving [{lbl}] ({len(new_starts)} new windows)...")
            _save_raw(new_starts, lbl)
            _save_gramians(new_starts, lbl)

    # ── Figure ────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(12, 5))
    try:
        fig.canvas.manager.set_window_title("Window browser")
    except Exception:
        pass
    plt.subplots_adjust(bottom=0.22, top=0.86)
    ax = fig.add_subplot(111)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Amplitude")

    tw, xw  = _get_window(state["current"])
    (line,) = ax.plot(tw, xw, color="#2060c0", linewidth=1.2)

    _btn_cfg = [
        ("interesting",    "[1/i] Interesting",    "#44bb44", 0.05),
        ("notinteresting", "[2/n] Not interesting", "#e08020", 0.38),
        ("flag",           "[3/f] Flag",            "#cc3333", 0.71),
    ]
    _buttons = {}
    for lbl, btn_txt, colour, x0 in _btn_cfg:
        ax_b = fig.add_axes([x0, 0.02, 0.25, 0.08])
        btn  = Button(ax_b, btn_txt, color=colour, hovercolor=colour)
        btn.label.set_color("white")
        btn.label.set_fontweight("bold")
        btn.on_clicked(lambda _, l=lbl: _label(l))
        _buttons[lbl] = btn

    # ── Rendering ─────────────────────────────────────────────────────────
    def _update_plot():
        i = state["current"]
        if i >= N:
            return
        tw, xw = _get_window(i)
        line.set_xdata(tw)
        line.set_ydata(xw)
        ax.relim()
        ax.autoscale_view()
        s  = starts[i]
        ni = len(this_session["interesting"])
        nn = len(this_session["notinteresting"])
        nf = len(this_session["flag"])
        ax.set_title(
            f"Window {i + 1} / {N}   start={s}   t={t[s]:.4f}\n"
            f"i:{ni}  n:{nn}  f:{nf}   remaining:{N - i - 1}   [z] undo"
        )
        fig.canvas.draw_idle()

    # ── Labelling / undo ──────────────────────────────────────────────────
    def _label(lbl):
        i = state["current"]
        if i >= N:
            return
        s = starts[i]

        state["undo_stack"].append({"label": lbl, "start": s, "pos": i})
        if len(state["undo_stack"]) > MAX_UNDO:
            state["undo_stack"].pop(0)

        this_session[lbl].append(s)
        state["current"]    += 1
        state["since_save"] += 1

        if state["current"] >= N:
            _finish()
            return

        _update_plot()

        if state["since_save"] >= SAVE_EVERY:
            _save_label_index()
            _save_session()
            state["since_save"] = 0

    def _undo():
        if not state["undo_stack"]:
            print("Nothing to undo.")
            return
        entry = state["undo_stack"].pop()
        lbl   = entry["label"]
        s     = entry["start"]
        if s in this_session[lbl]:
            this_session[lbl].remove(s)
        state["current"] = entry["pos"]
        _update_plot()
        _save_label_index()
        _save_session()
        state["since_save"] = 0

    # ── Finish / close ────────────────────────────────────────────────────
    def _finish():
        _save_label_index()
        if os.path.isfile(session_file):
            os.remove(session_file)
        ni = len(this_session["interesting"])
        nn = len(this_session["notinteresting"])
        nf = len(this_session["flag"])
        print(f"\nDone.  i:{ni}  n:{nn}  f:{nf}")
        print("Saving all outputs...")
        _save_all_outputs()
        plt.close(fig)

    def _on_close(_event):
        _save_label_index()
        _save_session()
        i = state["current"]
        ni = len(this_session["interesting"])
        nn = len(this_session["notinteresting"])
        nf = len(this_session["flag"])
        print(f"\nClosed at {i + 1}/{N}.  i:{ni}  n:{nn}  f:{nf}")
        print("Saving outputs for labelled windows so far...")
        _save_all_outputs()

    def _on_key(event):
        k = event.key
        if   k in ("1", "i"): _label("interesting")
        elif k in ("2", "n"): _label("notinteresting")
        elif k in ("3", "f"): _label("flag")
        elif k == "z":        _undo()

    fig.canvas.mpl_connect("key_press_event", _on_key)
    fig.canvas.mpl_connect("close_event",     _on_close)

    _update_plot()
    plt.show()
