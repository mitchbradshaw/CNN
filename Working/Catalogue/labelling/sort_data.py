"""
sort_data.py: Subcategorize already-labelled 'interesting' windows into
               clear / average / noisy / vague.

Writes lightweight JSON pointer files (source path only) rather than
copying or recomputing data.

Pointer usage
-------------
    import json, numpy as np, matplotlib.pyplot as plt

    ptr = json.load(open("path/to/pointer.json"))
    img = plt.imread(ptr["source"])        # GADF / GASF / recurrence / fusion
    raw = np.load(ptr["source"])           # rawdata: row 0 = x, row 1 = t

Usage
-----
    from sort_data import subcategorize_interesting_windows
    subcategorize_interesting_windows(timescale=10, fs=1.0)
"""
import os
import glob
import json
import random

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button
import numpy as np


SUBCATS    = ["clear", "average", "noisy", "vague"]
DATATYPES  = ["rawdata", "GADF", "GASF", "recurrence", "fusion"]
MAX_UNDO   = 3
SAVE_EVERY = 25


def subcategorize_interesting_windows(timescale, fs):
    """Browse interesting windows and assign each to a subcategory.

    Parameters
    ----------
    timescale : int or float
        Window length in minutes (must match the labelling step).
    fs : float
        Sample rate in Hz.

    Keyboard shortcuts
    ------------------
    1 / c  –  clear
    2 / a  –  average
    3 / n  –  noisy
    4 / v  –  vague
    z      –  undo (up to 3 steps)
    """

    # ── Source folders ────────────────────────────────────────────────────
    # Layout is <window root>/<encoding>/<class>/, so each encoding directory
    # is a valid torchvision ImageFolder root.
    from Working.Preprocessing.manage_data.load_data import window_root
    minutes_folder = window_root(timescale, fs)
    src = {
        name: os.path.join(minutes_folder, name, "interesting")
        for name in ("rawdata", "GADF", "GASF", "recurrence", "fusion")
    }
    for name, folder in src.items():
        if not os.path.isdir(folder):
            raise FileNotFoundError(f"Source folder not found: {folder!r}")

    # ── Discover window indices from GADF folder ──────────────────────────
    gadf_files = sorted(glob.glob(os.path.join(src["GADF"], "GADF_*.png")))
    if not gadf_files:
        raise RuntimeError(f"No GADF_*.png files found in {src['GADF']!r}")
    all_starts = [
        int(os.path.basename(f).removeprefix("GADF_").removesuffix(".png"))
        for f in gadf_files
    ]
    N = len(all_starts)
    print(f"Found {N} interesting windows.")

    # ── Output folder tree ────────────────────────────────────────────────
    out_root     = os.path.join(minutes_folder, f"{prefix}_subcategories")
    session_file = os.path.join(out_root, "session.json")
    for subcat in SUBCATS:
        for dtype in DATATYPES:
            os.makedirs(os.path.join(out_root, subcat, dtype), exist_ok=True)

    # ── Session: resume or fresh ──────────────────────────────────────────
    assignments: dict[int, str] = {}   # start_idx -> subcategory
    order: list[int] = list(range(N))  # permuted indices into all_starts

    if os.path.isfile(session_file):
        with open(session_file) as f:
            sess = json.load(f)
        ans = input(
            f"Resume session at window {sess['current'] + 1}/{N}? [Y/n]: "
        ).strip().lower()
        if ans in ("", "y", "yes"):
            pos         = sess["current"]
            order       = sess["order"]
            assignments = {int(k): v for k, v in sess["assignments"].items()}
            print(f"Resuming at {pos + 1} / {N}")
        else:
            random.shuffle(order)
            pos = 0
    else:
        random.shuffle(order)
        pos = 0

    # ── Shared mutable state ──────────────────────────────────────────────
    state = {
        "pos":         pos,
        "order":       order,
        "assignments": assignments,
        "undo_stack":  [],        # list of {"pos", "start_idx", "subcat"}
        "since_save":  0,
    }

    # ── Path helpers ──────────────────────────────────────────────────────
    def _src_paths(start_idx):
        return {
            "rawdata":    os.path.abspath(os.path.join(src["rawdata"],    f"{start_idx}.npy")),
            "GADF":       os.path.abspath(os.path.join(src["GADF"],       f"GADF_{start_idx}.png")),
            "GASF":       os.path.abspath(os.path.join(src["GASF"],       f"GASF_{start_idx}.png")),
            "recurrence": os.path.abspath(os.path.join(src["recurrence"], f"recurrence_{start_idx}.png")),
            "fusion":     os.path.abspath(os.path.join(src["fusion"],     f"fusion_{start_idx}.png")),
        }

    def _ptr_paths(start_idx, subcat):
        return {
            "rawdata":    os.path.join(out_root, subcat, "rawdata",    f"rawdata_{start_idx}.json"),
            "GADF":       os.path.join(out_root, subcat, "GADF",       f"GADF_{start_idx}.json"),
            "GASF":       os.path.join(out_root, subcat, "GASF",       f"GASF_{start_idx}.json"),
            "recurrence": os.path.join(out_root, subcat, "recurrence", f"recurrence_{start_idx}.json"),
            "fusion":     os.path.join(out_root, subcat, "fusion",     f"fusion_{start_idx}.json"),
        }

    def _write_pointers(start_idx, subcat):
        srcs = _src_paths(start_idx)
        for dtype, ptr_path in _ptr_paths(start_idx, subcat).items():
            with open(ptr_path, "w") as f:
                json.dump({"source": srcs[dtype], "start_idx": start_idx,
                           "timescale": timescale, "fs": fs}, f, indent=2)

    def _remove_pointers(start_idx, subcat):
        for ptr_path in _ptr_paths(start_idx, subcat).values():
            if os.path.isfile(ptr_path):
                os.remove(ptr_path)

    # ── Data loading ──────────────────────────────────────────────────────
    def _load(p):
        """Return (start_idx, raw_data, imgs_dict) for position p in order."""
        start_idx = all_starts[state["order"][p]]
        srcs      = _src_paths(start_idx)

        raw = np.load(srcs["rawdata"]) if os.path.isfile(srcs["rawdata"]) else None
        imgs = {}
        for dtype in ("GADF", "GASF", "recurrence", "fusion"):
            path = srcs[dtype]
            imgs[dtype] = plt.imread(path) if os.path.isfile(path) else None
        return start_idx, raw, imgs

    # Simple two-slot pre-fetch cache: current and current+1
    _cache: dict[int, tuple] = {}

    def _fetch(p):
        if 0 <= p < N and p not in _cache:
            _cache[p] = _load(p)
        return _cache.get(p)

    def _evict(p):
        _cache.pop(p - 1, None)

    # ── Figure ────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 9))
    try:
        fig.canvas.manager.set_window_title("Subcategory browser")
    except Exception:
        pass

    plt.subplots_adjust(top=0.88, bottom=0.13, left=0.05, right=0.97,
                        hspace=0.40, wspace=0.25)
    gs     = gridspec.GridSpec(2, 3, figure=fig)
    ax_raw = fig.add_subplot(gs[0, 0:2])
    ax_gad = fig.add_subplot(gs[0, 2])
    ax_gas = fig.add_subplot(gs[1, 0])
    ax_rec = fig.add_subplot(gs[1, 1])
    ax_fus = fig.add_subplot(gs[1, 2])

    # Buttons
    _btn_cfg = [
        ("clear",   "[1/c] Clear",   "#55cc55", 0.05),
        ("average", "[2/a] Average", "#4477dd", 0.27),
        ("noisy",   "[3/n] Noisy",   "#dd7722", 0.49),
        ("vague",   "[4/v] Vague",   "#aa44cc", 0.71),
    ]
    _buttons = {}   # keep references to prevent GC
    for subcat, label_txt, colour, x0 in _btn_cfg:
        ax_b = fig.add_axes([x0, 0.02, 0.20, 0.055])
        btn  = Button(ax_b, label_txt, color=colour, hovercolor=colour)
        btn.label.set_color("white")
        btn.label.set_fontweight("bold")
        btn.on_clicked(lambda _, s=subcat: _label(s))
        _buttons[subcat] = btn

    # ── Rendering ─────────────────────────────────────────────────────────
    def _render(p, start_idx, raw, imgs):
        counts  = _count()
        current = state["assignments"].get(start_idx, "—")

        ax_raw.cla()
        if raw is not None:
            ax_raw.plot(raw[1], raw[0], color="#2060c0", linewidth=1.0)
        else:
            ax_raw.text(0.5, 0.5, "Raw file not found",
                        ha="center", va="center", transform=ax_raw.transAxes, color="red")
        ax_raw.set_title("Raw signal")
        ax_raw.set_xlabel("Time (s)")
        ax_raw.set_ylabel("Amplitude")

        for ax, dtype, title in [
            (ax_gad, "GADF",       "GADF"),
            (ax_gas, "GASF",       "GASF"),
            (ax_rec, "recurrence", "Recurrence"),
            (ax_fus, "fusion",     "Fusion"),
        ]:
            ax.cla()
            ax.set_xticks([]); ax.set_yticks([])
            if imgs[dtype] is not None:
                ax.imshow(imgs[dtype], aspect="auto", origin="upper")
            else:
                ax.text(0.5, 0.5, "File not found",
                        ha="center", va="center", transform=ax.transAxes, color="red")
            ax.set_title(title)

        fig.suptitle(
            f"Window {p + 1} / {N}   start_idx={start_idx}   current label: {current}\n"
            f"clear={counts['clear']}  avg={counts['average']}  "
            f"noisy={counts['noisy']}  vague={counts['vague']}   "
            f"remaining={N - p}   [z] undo",
            fontsize=10,
        )
        fig.canvas.draw_idle()

    def _count():
        c = {s: 0 for s in SUBCATS}
        for v in state["assignments"].values():
            if v in c:
                c[v] += 1
        return c

    # ── Label / undo ──────────────────────────────────────────────────────
    def _label(subcat):
        p = state["pos"]
        if p >= N:
            return
        data = _fetch(p)
        if data is None:
            return
        start_idx, raw, imgs = data

        # Undo snapshot
        state["undo_stack"].append({"pos": p, "start_idx": start_idx, "subcat": subcat})
        if len(state["undo_stack"]) > MAX_UNDO:
            state["undo_stack"].pop(0)

        state["assignments"][start_idx] = subcat
        _write_pointers(start_idx, subcat)

        state["pos"] += 1
        state["since_save"] += 1
        _evict(p)

        if state["pos"] >= N:
            _finish()
            return

        # Pre-fetch next two windows
        _fetch(state["pos"])
        if state["pos"] + 1 < N:
            _fetch(state["pos"] + 1)

        next_data = _fetch(state["pos"])
        if next_data:
            _render(state["pos"], *next_data)

        if state["since_save"] >= SAVE_EVERY:
            _save_session()
            state["since_save"] = 0

    def _undo():
        if not state["undo_stack"]:
            print("Nothing to undo.")
            return
        entry     = state["undo_stack"].pop()
        p         = entry["pos"]
        start_idx = entry["start_idx"]
        old_cat   = entry["subcat"]

        _remove_pointers(start_idx, old_cat)
        state["assignments"].pop(start_idx, None)
        state["pos"] = p
        _cache.pop(p, None)   # force clean reload

        data = _fetch(p)
        if data:
            _render(p, *data)
        _save_session()
        state["since_save"] = 0

    # ── Session I/O ───────────────────────────────────────────────────────
    def _save_session():
        payload = {
            "current":     state["pos"],
            "order":       state["order"],
            "assignments": {str(k): v for k, v in state["assignments"].items()},
        }
        with open(session_file, "w") as f:
            json.dump(payload, f, indent=2)

    def _finish():
        _save_session()
        if os.path.isfile(session_file):
            os.remove(session_file)
        c = _count()
        print(f"\nDone!  clear:{c['clear']}  average:{c['average']}  "
              f"noisy:{c['noisy']}  vague:{c['vague']}")
        plt.close(fig)

    # ── Keyboard handler ──────────────────────────────────────────────────
    def _on_key(event):
        k = event.key
        if   k in ("1", "c"):  _label("clear")
        elif k in ("2", "a"):  _label("average")
        elif k in ("3", "n"):  _label("noisy")
        elif k in ("4", "v"):  _label("vague")
        elif k == "z":         _undo()

    def _on_close(_event):
        _save_session()
        p = state["pos"]
        print(f"Session saved. Resume at window {p + 1} / {N}")

    fig.canvas.mpl_connect("key_press_event", _on_key)
    fig.canvas.mpl_connect("close_event",     _on_close)

    # ── Initial draw ──────────────────────────────────────────────────────
    if state["pos"] < N:
        _fetch(state["pos"])
        if state["pos"] + 1 < N:
            _fetch(state["pos"] + 1)
        data = _fetch(state["pos"])
        if data:
            _render(state["pos"], *data)

    plt.show()
