"""
interest_select_cnn.py
======================
CNN-assisted interactive window-labelling tool.

Extends interest_select_windows with:
  - Real-time CNN inference on each window
  - Side-by-side display of the raw signal, the CNN image, and a confidence bar
  - CNN predictions saved to JSON alongside the usual raw/gramian outputs

Layout
------
  ┌─────────────────────────┬──────────────┐
  │   Raw signal            │  CNN image   │
  ├─────────────────────────┴──────────────┤
  │   Confidence bar (horizontal)          │
  ├────────────┬────────────┬──────────────┤
  │ Interesting│Not interest│    Flag      │
  └────────────┴────────────┴──────────────┘

Keyboard shortcuts  (same as interest_select_windows)
--------------------
    1 / i  – interesting
    2 / n  – not interesting
    3 / f  – flag
    z      – undo (up to 3 steps)

Usage
-----
    from interest_select_cnn import interest_select_cnn
    import scipy.io

    mat = scipy.io.loadmat("DATA/RAW/M2_aug_concat_fs1.mat")
    x   = mat["x"].ravel()

    interest_select_cnn(
        x,
        fs=1.0,
        window_min=10,
        model_path="MODELS/fusion_cnn.pth",
        image_type="fusion",
        suffix="v1",
    )
"""

import os
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Button
from PIL import Image as PILImage
from skimage.transform import resize

import torch

from Working.Catalogue.gramian.gramian_calc import (
    compute_GASF, compute_GADF, compute_recurrence, to_uint8,
    save_gramian_windows,
)
from Working.Catalogue.cnn.cnn_rangapur import EEG_CNN, get_transforms


# ── Constants ───────────────────────────────────────────────────────────────

LABELS     = ["interesting", "notinteresting", "flag"]
MAX_UNDO   = 3
SAVE_EVERY = 25

# Default class names match ImageFolder alphabetical ordering used in training
DEFAULT_CLASS_NAMES = ["interesting", "notinteresting"]


# ── CNN helpers ─────────────────────────────────────────────────────────────

def _load_model(model_path: str, device: torch.device) -> EEG_CNN:
    ckpt        = torch.load(model_path, map_location=device, weights_only=True)
    num_classes = ckpt["backbone.classifier.1.weight"].shape[0]
    model       = EEG_CNN(num_classes=num_classes)
    model.load_state_dict(ckpt)
    model.to(device)
    model.eval()
    print(f"Loaded model: {model_path}  ({num_classes} classes)")
    return model, num_classes


def _window_to_tensor(win: np.ndarray, image_type: str,
                      img_size: int, device: torch.device) -> torch.Tensor:
    """Compute the CNN image for a window and return a (1, C, H, W) tensor."""
    is_rgb = (image_type == "fusion")

    if image_type == "GASF":
        mat = compute_GASF(win)
        arr = PILImage.fromarray(to_uint8(mat), mode="L")

    elif image_type == "GADF":
        mat = compute_GADF(win)
        arr = PILImage.fromarray(to_uint8(mat), mode="L")

    elif image_type == "recurrence":
        mat = compute_recurrence(win)
        arr = PILImage.fromarray(to_uint8(mat), mode="L")

    elif image_type == "fusion":
        gasf = compute_GASF(win)
        gadf = compute_GADF(win)
        rec  = compute_recurrence(win)
        rec_r = resize(rec, gasf.shape, anti_aliasing=True)

        def _norm(a):
            lo, hi = a.min(), a.max()
            return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)

        rgb = np.stack([_norm(gasf), _norm(gadf), _norm(rec_r)], axis=-1)
        arr = PILImage.fromarray((rgb * 255).astype(np.uint8), mode="RGB")

    else:
        raise ValueError(f"Unknown image_type: {image_type!r}. "
                         "Choose from 'GASF', 'GADF', 'recurrence', 'fusion'.")

    transform = get_transforms(img_size, is_train=False, is_rgb=is_rgb)
    return transform(arr).unsqueeze(0).to(device)


def _run_inference(model: EEG_CNN, tensor: torch.Tensor) -> tuple[int, list[float]]:
    """Return (predicted_class_index, list_of_probabilities)."""
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0].cpu().tolist()
    return int(np.argmax(probs)), probs


def _cnn_image_array(win: np.ndarray, image_type: str) -> np.ndarray:
    """Return a displayable numpy array (H, W) or (H, W, 3) for the given type."""
    if image_type == "GASF":
        return to_uint8(compute_GASF(win))
    elif image_type == "GADF":
        return to_uint8(compute_GADF(win))
    elif image_type == "recurrence":
        return to_uint8(compute_recurrence(win))
    elif image_type == "fusion":
        gasf = compute_GASF(win)
        gadf = compute_GADF(win)
        rec  = compute_recurrence(win)
        rec_r = resize(rec, gasf.shape, anti_aliasing=True)

        def _norm(a):
            lo, hi = a.min(), a.max()
            return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)

        return (np.stack([_norm(gasf), _norm(gadf), _norm(rec_r)], axis=-1) * 255).astype(np.uint8)
    raise ValueError(f"Unknown image_type: {image_type!r}")


# ── Public API ───────────────────────────────────────────────────────────────

def interest_select_cnn(
    x,
    fs,
    window_min,
    model_path,
    image_type   = "fusion",
    t            = None,
    suffix       = "",
    class_names  = None,
    img_size     = 224,
    device       = None,
):
    """
    CNN-assisted interactive window-labelling tool.

    Parameters
    ----------
    x            : 1-D array-like  — raw time series (samples)
    fs           : float           — sample rate (Hz)
    window_min   : int | float     — window length in minutes
    model_path   : str             — path to a trained .pth model file
    image_type   : str             — one of 'fusion', 'GASF', 'GADF', 'recurrence'
    t            : array-like, optional — time vector (defaults to sample/fs)
    suffix       : str             — appended to all output folder names
    class_names  : list[str], optional
                     Human-readable class names in the same order as training.
                     Defaults to ["interesting", "notinteresting"].
    img_size     : int             — image size fed to the CNN (default 224)
    device       : str | None      — 'cpu', 'cuda', or None (auto-detect)
    """
    # ── Setup ─────────────────────────────────────────────────────────────
    x = np.asarray(x, dtype=float).ravel()
    t = (np.arange(len(x)) / fs) if t is None else np.asarray(t, dtype=float).ravel()

    if class_names is None:
        class_names = DEFAULT_CLASS_NAMES

    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(device)
    print(f"Device: {device}")

    # Load model once
    model, num_classes = _load_model(model_path, device)
    if num_classes != len(class_names):
        print(f"  Warning: model has {num_classes} classes but "
              f"{len(class_names)} class_names were provided. "
              f"Indices 0..{num_classes-1} will be used.")

    win_samp  = round(window_min * 60 * fs)
    step_samp = max(1, round(win_samp / 3))

    # ── Path setup ────────────────────────────────────────────────────────
    fs_str      = f"{fs:.2f}"
    win_tag     = f"{window_min:g}min"
    minutes_dir = os.path.join("DATA", f"{window_min:g}_MINUTES")
    index_dir   = os.path.join(minutes_dir, win_tag)
    os.makedirs(index_dir, exist_ok=True)

    # Shared session file with interest_select_windows so progress is continuous
    session_file = os.path.join(index_dir, f"{win_tag}_session_fs_{fs_str}.json")
    label_files  = {
        lbl: os.path.join(index_dir, f"{win_tag}_{lbl}_fs_{fs_str}.json")
        for lbl in LABELS
    }
    pred_file = os.path.join(index_dir, f"{win_tag}_cnn_predictions_fs_{fs_str}.json")

    suffix_part = f"_{suffix}" if suffix else ""

    def _out_dir(label, kind):
        return os.path.join(minutes_dir, f"{win_tag}_fs{fs}_{label}_{kind}{suffix_part}")

    # ── Session ───────────────────────────────────────────────────────────
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

    # ── Load prior label baselines ────────────────────────────────────────
    disk_baseline: dict[str, list] = {}
    for lbl in LABELS:
        if os.path.isfile(label_files[lbl]):
            with open(label_files[lbl]) as f:
                d = json.load(f)
            disk_baseline[lbl] = d.get("starts", [])
            print(f'  Existing "{lbl}": {len(disk_baseline[lbl])} entries')
        else:
            disk_baseline[lbl] = []

    # Load any existing CNN predictions
    cnn_predictions: dict[str, dict] = {}
    if os.path.isfile(pred_file):
        with open(pred_file) as f:
            cnn_predictions = json.load(f)

    # ── Mutable state ─────────────────────────────────────────────────────
    this_session: dict[str, list] = {lbl: [] for lbl in LABELS}
    state = {
        "current":    current,
        "undo_stack": [],
        "since_save": 0,
    }

    # ── Helpers ───────────────────────────────────────────────────────────
    def _get_window(i):
        s = starts[i]
        e = min(s + win_samp, len(x))
        return t[s:e], x[s:e]

    def _infer_window(i):
        """Run CNN on window i. Returns (pred_idx, probs, display_img_array)."""
        s   = starts[i]
        win = x[s:min(s + win_samp, len(x))]
        tensor   = _window_to_tensor(win, image_type, img_size, device)
        pred, probs = _run_inference(model, tensor)
        img_arr  = _cnn_image_array(win, image_type)
        return pred, probs, img_arr

    # ── Persistence ───────────────────────────────────────────────────────
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

    def _save_predictions():
        with open(pred_file, "w") as f:
            json.dump(cnn_predictions, f, indent=2)

    # ── Output saving ─────────────────────────────────────────────────────
    def _save_raw(start_list, lbl):
        folder = _out_dir(lbl, "rawdata")
        os.makedirs(folder, exist_ok=True)
        for s in start_list:
            data = np.stack([x[s:s + win_samp], t[s:s + win_samp]])
            np.save(os.path.join(folder, f"{s}.npy"), data)
        print(f"  [{lbl}] rawdata → {folder}/  ({len(start_list)} files)")

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
        _save_predictions()

    # ── Figure ────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 8))
    try:
        fig.canvas.manager.set_window_title("CNN Window Browser")
    except Exception:
        pass

    gs = gridspec.GridSpec(
        3, 3,
        figure=fig,
        height_ratios=[5, 1.2, 1],
        hspace=0.45, wspace=0.3,
        left=0.06, right=0.97, top=0.90, bottom=0.08,
    )

    ax_sig  = fig.add_subplot(gs[0, 0:2])   # signal (wide)
    ax_img  = fig.add_subplot(gs[0, 2])     # CNN image
    ax_conf = fig.add_subplot(gs[1, :])     # confidence bar

    ax_sig.set_xlabel("Time (s)")
    ax_sig.set_ylabel("Amplitude")
    ax_img.set_title(image_type)
    ax_img.set_xticks([])
    ax_img.set_yticks([])

    # Initial draw (pre-fetch)
    tw, xw = _get_window(state["current"])
    (line,) = ax_sig.plot(tw, xw, color="#2060c0", linewidth=1.2)

    pred0, probs0, img0 = _infer_window(state["current"])
    im_handle = ax_img.imshow(img0, aspect="auto", origin="upper")

    bar_colors = ["#44bb44", "#e08020", "#cc3333", "#8844cc", "#2288cc"]
    bar_x      = list(range(num_classes))
    bars       = ax_conf.bar(
        bar_x, probs0,
        color=[bar_colors[i % len(bar_colors)] for i in bar_x],
        edgecolor="white",
    )
    ax_conf.set_xlim(-0.5, num_classes - 0.5)
    ax_conf.set_ylim(0, 1)
    ax_conf.set_xticks(bar_x)
    ax_conf.set_xticklabels(
        [class_names[i] if i < len(class_names) else str(i) for i in bar_x],
        fontsize=9,
    )
    ax_conf.set_ylabel("Confidence")
    ax_conf.axhline(0.5, color="gray", linewidth=0.8, linestyle="--")

    # Buttons
    _btn_cfg = [
        ("interesting",    "[1/i] Interesting",    "#44bb44", 0),
        ("notinteresting", "[2/n] Not interesting", "#e08020", 1),
        ("flag",           "[3/f] Flag",            "#cc3333", 2),
    ]
    _buttons = {}
    for lbl, btn_txt, colour, col in _btn_cfg:
        ax_b = fig.add_subplot(gs[2, col])
        ax_b.set_axis_off()
        # Place button inside the subplot axes
        btn_ax = fig.add_axes([
            ax_b.get_position().x0 + 0.01,
            ax_b.get_position().y0,
            ax_b.get_position().width - 0.02,
            ax_b.get_position().height,
        ])
        btn = Button(btn_ax, btn_txt, color=colour, hovercolor=colour)
        btn.label.set_color("white")
        btn.label.set_fontweight("bold")
        btn.on_clicked(lambda _, l=lbl: _label(l))
        _buttons[lbl] = btn

    # ── Rendering ─────────────────────────────────────────────────────────
    def _update_plot(pred, probs, img_arr):
        i  = state["current"]
        tw, xw = _get_window(i)
        line.set_xdata(tw)
        line.set_ydata(xw)
        ax_sig.relim()
        ax_sig.autoscale_view()

        im_handle.set_data(img_arr)
        im_handle.set_clim(img_arr.min(), img_arr.max())

        for bar, p in zip(bars, probs):
            bar.set_height(p)

        s  = starts[i]
        ni = len(this_session["interesting"])
        nn = len(this_session["notinteresting"])
        nf = len(this_session["flag"])
        pred_name = class_names[pred] if pred < len(class_names) else str(pred)
        fig.suptitle(
            f"Window {i + 1} / {N}   start={s}   t={t[s]:.4f}   "
            f"CNN → {pred_name} ({probs[pred]:.2%})\n"
            f"i:{ni}  n:{nn}  f:{nf}   remaining:{N - i - 1}   [z] undo",
            fontsize=10,
        )
        fig.canvas.draw_idle()

    # ── Labelling / undo ──────────────────────────────────────────────────
    def _label(lbl):
        i = state["current"]
        if i >= N:
            return
        s = starts[i]

        # Store CNN prediction for this window
        pred, probs, _ = _infer_window(i)
        cnn_predictions[str(s)] = {
            "predicted_class":  pred,
            "predicted_name":   class_names[pred] if pred < len(class_names) else str(pred),
            "probabilities":    probs,
            "user_label":       lbl,
        }

        state["undo_stack"].append({"label": lbl, "start": s, "pos": i,
                                    "pred": pred, "probs": probs})
        if len(state["undo_stack"]) > MAX_UNDO:
            state["undo_stack"].pop(0)

        this_session[lbl].append(s)
        state["current"]    += 1
        state["since_save"] += 1

        if state["current"] >= N:
            _finish()
            return

        next_pred, next_probs, next_img = _infer_window(state["current"])
        _update_plot(next_pred, next_probs, next_img)

        if state["since_save"] >= SAVE_EVERY:
            _save_label_index()
            _save_session()
            _save_predictions()
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
        cnn_predictions.pop(str(s), None)
        state["current"] = entry["pos"]

        pred, probs, img_arr = _infer_window(state["current"])
        _update_plot(pred, probs, img_arr)
        _save_label_index()
        _save_session()
        _save_predictions()
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
        i  = state["current"]
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

    # Initial render
    _update_plot(pred0, probs0, img0)
    plt.show()
