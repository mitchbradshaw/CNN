"""
apply_cnn.py
============
Apply a trained EEG CNN to sliding windows of raw time-series data and
store a per-window confidence score for the "interesting" class.

Pipeline
--------
  1. Load .mat file  →  raw signal at fs_raw Hz
  2. Downsample      →  target fs (default 1 Hz)
  3. Sliding windows (configurable length + step)
  4. compute_fusion  →  RGB gramian image
  5. CNN inference   →  softmax probabilities
  6. Save scores dict  {window_start_sample: interesting_confidence}

Usage
-----
  # Default (matches training setup)
  python cnn/apply_cnn.py

  # Custom
  python cnn/apply_cnn.py \\
      --mat   DATA/RAW/M2_aug_concat_fs2.mat \\
      --model MODELS/fusion_cnn_3.pth        \\
      --fs_raw 2 --fs_target 1               \\
      --window_min 10 --step_min 3           \\
      --img_size 224                         \\
      --batch_size 32                        \\
      --out_dir DATA/10_MINUTES/10min_fs1_cnnscores

Assumptions
-----------
* The model was trained with image_type="fusion" (RGB, 3-channel).
* Class index 0 = "interesting", 1 = "notinteresting"
  (alphabetical order used by torchvision ImageFolder during training).
* The .mat file contains the signal in a variable called "x".
* Downsampling is simple decimation (every ds-th sample); suitable because
  the signal is already low-frequency (EEG at 1–2 Hz).
"""

import argparse
import os
import pickle
import sys

import numpy as np
import scipy.io
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

# ── Project imports ────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gramian.gramian_calc        import (
    compute_fusion, compute_GASF, compute_GADF, compute_recurrence, to_uint8,
)
from cnn.cnn_rangapur            import EEG_CNN, get_transforms
from cnn.cnn_fusion_prediction   import FusionPredictionCNN

# ── Optional progress bar ──────────────────────────────────────────────────────
try:
    from tqdm import tqdm
    TQDM = True
except ImportError:
    TQDM = False


# ══════════════════════════════════════════════════════════════════════════════
# Config / defaults
# ══════════════════════════════════════════════════════════════════════════════

DEFAULTS = dict(
    mat        = "DATA/RAW/M2_aug_concat_fs2.mat",
    model      = "MODELS/fusion_cnn_3.pth",
    fs_raw     = 2.0,
    fs_target  = 1.0,
    window_min = 10,
    step_min   = 3,
    img_size   = 224,
    batch_size = 32,
    out_dir    = "DATA/10_MINUTES/10min_fs1_cnnscores",
)


# ══════════════════════════════════════════════════════════════════════════════
# Step 1 – Data loading
# ══════════════════════════════════════════════════════════════════════════════

def load_signal(mat_path: str) -> np.ndarray:
    """Load raw time-series from a .mat file. Returns a 1-D float64 array."""
    mat = scipy.io.loadmat(mat_path)

    # Find the signal variable: prefer 'x', then pick the largest numeric array
    if "x" in mat:
        x = np.asarray(mat["x"], dtype=np.float64).ravel()
    else:
        candidates = {
            k: v for k, v in mat.items()
            if not k.startswith("_") and isinstance(v, np.ndarray) and v.ndim <= 2
        }
        key = max(candidates, key=lambda k: candidates[k].size)
        x   = np.asarray(candidates[key], dtype=np.float64).ravel()
        print(f"  Note: 'x' not found in .mat; using variable '{key}'")

    print(f"  Loaded signal: {len(x):,} samples from '{mat_path}'")
    return x


# ══════════════════════════════════════════════════════════════════════════════
# Step 2 – Downsampling
# ══════════════════════════════════════════════════════════════════════════════

def downsample(x: np.ndarray, fs_raw: float, fs_target: float) -> np.ndarray:
    """
    Decimate x from fs_raw to fs_target by keeping every ds-th sample.
    Raises if the ratio is not an integer.
    """
    ratio = fs_raw / fs_target
    if ratio != int(ratio):
        raise ValueError(
            f"fs_raw / fs_target = {ratio} is not an integer; "
            "integer decimation only"
        )
    ds = int(ratio)
    if ds == 1:
        return x
    x_ds = x[::ds]
    print(f"  Downsampled {len(x):,} → {len(x_ds):,} samples  (÷{ds})")
    return x_ds


# ══════════════════════════════════════════════════════════════════════════════
# Step 3 – Window generation
# ══════════════════════════════════════════════════════════════════════════════

def generate_windows(
    x: np.ndarray,
    window_samples: int,
    step_samples: int,
) -> list[int]:
    """
    Return a list of start indices for all valid (non-truncating) windows.
    """
    starts = list(range(0, len(x) - window_samples + 1, step_samples))
    print(f"  Windows: {len(starts):,}  "
          f"(length={window_samples} samples, step={step_samples} samples)")
    return starts


# ══════════════════════════════════════════════════════════════════════════════
# Step 4 – Window → tensor
# ══════════════════════════════════════════════════════════════════════════════

def _window_to_pil(window: np.ndarray, image_type: str) -> Image.Image:
    """
    Convert a 1-D signal window to a PIL RGB image using the requested type.

    All types are returned as RGB so they match what ImageFolder produces during
    training (which always calls Image.open(...).convert("RGB")):
      - fusion     : native RGB gramian fusion
      - GASF/GADF/recurrence : computed as 2-D float, normalised to uint8 L-mode,
                               then converted to RGB (replicates the channel × 3)
    """
    if image_type == "fusion":
        arr       = compute_fusion(window)                         # (H, W, 3) [0,1]
        img_uint8 = (arr * 255).clip(0, 255).astype(np.uint8)
        return Image.fromarray(img_uint8, mode="RGB")
    elif image_type == "GASF":
        return Image.fromarray(to_uint8(compute_GASF(window)), mode="L").convert("RGB")
    elif image_type == "GADF":
        return Image.fromarray(to_uint8(compute_GADF(window)), mode="L").convert("RGB")
    elif image_type == "recurrence":
        return Image.fromarray(to_uint8(compute_recurrence(window)), mode="L").convert("RGB")
    else:
        raise ValueError(
            f"Unknown image_type {image_type!r}. "
            "Expected 'fusion', 'GASF', 'GADF', or 'recurrence'."
        )


def window_to_tensor(
    x: np.ndarray,
    start: int,
    window_samples: int,
    transform: transforms.Compose,
    image_type: str = "fusion",
) -> torch.Tensor:
    """
    Slice window → compute image (image_type) → PIL Image → transform → tensor (1, C, H, W).
    """
    window  = x[start: start + window_samples]
    pil_img = _window_to_pil(window, image_type)
    tensor  = transform(pil_img)                            # (C, H, W)
    return tensor.unsqueeze(0)                              # (1, C, H, W)


# ══════════════════════════════════════════════════════════════════════════════
# Step 5 – Model loading
# ══════════════════════════════════════════════════════════════════════════════

def load_model(
    model_path: str,
    device: torch.device,
) -> EEG_CNN:
    """Load a saved EEG_CNN state-dict and return the model in eval mode."""
    ckpt = torch.load(model_path, map_location=device, weights_only=True)

    # Infer num_classes from the classifier weight shape
    weight_key = "backbone.classifier.1.weight"
    if weight_key not in ckpt:
        raise KeyError(f"Expected key '{weight_key}' in checkpoint")
    num_classes = ckpt[weight_key].shape[0]
    print(f"  Model: {num_classes} classes  ←  {model_path}")

    model = EEG_CNN(num_classes=num_classes)
    model.load_state_dict(ckpt)
    model.to(device)
    model.eval()
    return model


# ══════════════════════════════════════════════════════════════════════════════
# Step 6 – Batch inference
# ══════════════════════════════════════════════════════════════════════════════

@torch.no_grad()
def run_inference_batched(
    x: np.ndarray,
    starts: list[int],
    window_samples: int,
    model: EEG_CNN,
    transform: transforms.Compose,
    device: torch.device,
    batch_size: int,
) -> dict[int, float]:
    """
    Run model inference over all windows in batches.

    Returns
    -------
    scores : dict  {window_start_sample: P("interesting")}
    """
    scores       = {}
    n_windows    = len(starts)
    iterator     = range(0, n_windows, batch_size)

    if TQDM:
        iterator = tqdm(iterator, desc="Inference", unit="batch",
                        total=(n_windows + batch_size - 1) // batch_size)

    for batch_start in iterator:
        batch_starts  = starts[batch_start: batch_start + batch_size]
        tensors       = [
            window_to_tensor(x, s, window_samples, transform)
            for s in batch_starts
        ]
        batch_tensor  = torch.cat(tensors, dim=0).to(device)   # (B, 3, H, W)

        logits        = model(batch_tensor)                     # (B, num_classes)
        probs         = F.softmax(logits, dim=1)                # (B, num_classes)

        # Class 0 = "interesting" (alphabetical, matches ImageFolder training order)
        interesting_probs = probs[:, 0].cpu().numpy()

        for s, p in zip(batch_starts, interesting_probs):
            scores[int(s)] = float(p)

        if not TQDM and (batch_start // batch_size) % 50 == 0:
            done = min(batch_start + batch_size, n_windows)
            print(f"  [{done:>{len(str(n_windows))}}/{n_windows}] windows processed")

    return scores


# ══════════════════════════════════════════════════════════════════════════════
# Step 7 – Save results
# ══════════════════════════════════════════════════════════════════════════════

def save_scores(
    scores: dict[int, float],
    out_dir: str,
    filename: str = "scores.pkl",
) -> str:
    """Pickle the scores dict and return the saved path."""
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, filename)
    with open(out_path, "wb") as f:
        pickle.dump(scores, f)
    print(f"  Saved {len(scores):,} scores → {out_path}")
    return out_path


# ══════════════════════════════════════════════════════════════════════════════
# WindowMatrix integration
# ══════════════════════════════════════════════════════════════════════════════

def add_cnn_scores(
    wm,
    model_path: str,
    image_type: str   = "fusion",
    img_size:   int   = 224,
    batch_size: int   = 32,
    device:     torch.device | None = None,
    overwrite:  bool  = False,
) -> object:
    """
    Run batched CNN inference over every window in a WindowMatrix and add
    two score columns:

      ``cnn_p_interesting``
          Softmax probability assigned to the "interesting" class (class index 0).

      ``cnn_p_notinteresting``
          Softmax probability assigned to the "notinteresting" class (class index 1).

    Parameters
    ----------
    wm : WindowMatrix
        The matrix to add columns to.  Its ``._x``, ``._window_samples``,
        and ``._fs`` attributes are used to reconstruct each window.
    model_path : str
        Path to the saved ``.pth`` checkpoint (EEG_CNN state-dict).
    img_size : int
        CNN input image size in pixels (default 224).
    batch_size : int
        Number of windows to process per GPU/CPU batch (default 32).
    device : torch.device, optional
        Inference device.  Auto-detected (CUDA → CPU) if not supplied.
    overwrite : bool
        If False (default), skip silently if columns already exist.

    Returns
    -------
    wm  (for chaining)
    """
    COL_INTERESTING   = f"cnn_p_{image_type}_interesting"
    COL_1_MINUS_NOTINT = f"cnn_p_{image_type}_notinteresting"

    if COL_INTERESTING in wm.columns and not overwrite:
        return wm

    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print(f"[add_cnn_scores] device={device}  model={model_path}  image_type={image_type}")

    model     = load_model(model_path, device)
    transform = get_transforms(img_size, is_train=False, is_rgb=(image_type == "fusion"))

    starts         = list(wm.df.index)
    window_samples = wm._window_samples
    x              = wm._x

    p_interesting        = {}   # {start_idx: float}
    p_notinteresting     = {}

    iterator = range(0, len(starts), batch_size)
    if TQDM:
        iterator = tqdm(iterator, desc="CNN scores", unit="batch",
                        total=(len(starts) + batch_size - 1) // batch_size)

    with torch.no_grad():
        for batch_i in iterator:
            batch_starts = starts[batch_i: batch_i + batch_size]
            tensors = [
                window_to_tensor(x, s, window_samples, transform, image_type)
                for s in batch_starts
            ]
            batch_tensor = torch.cat(tensors, dim=0).to(device)   # (B, C, H, W)
            logits       = model(batch_tensor)                      # (B, num_classes)
            probs        = F.softmax(logits, dim=1).cpu().numpy()   # (B, num_classes)

            for s, row in zip(batch_starts, probs):
                p_interesting[int(s)]    = float(row[0])
                p_notinteresting[int(s)] = float(row[1])

            if not TQDM and (batch_i // batch_size) % 50 == 0:
                done = min(batch_i + batch_size, len(starts))
                print(f"  [{done}/{len(starts)}] windows scored")

    wm.add_external_column(COL_INTERESTING,    p_interesting,    overwrite=overwrite)
    wm.add_external_column(COL_1_MINUS_NOTINT, p_notinteresting, overwrite=overwrite)

    print(f"[add_cnn_scores] done — added '{COL_INTERESTING}' and '{COL_1_MINUS_NOTINT}'")
    return wm


def _load_fusion_prediction_model(model_path: str, device: torch.device) -> FusionPredictionCNN:
    """
    Load a FusionPredictionCNN state-dict and return the model in eval mode.
    num_classes is inferred from the saved weight shape.
    """
    ckpt = torch.load(model_path, map_location=device, weights_only=True)
    weight_key = "backbone.classifier.1.weight"
    if weight_key not in ckpt:
        raise KeyError(f"Expected key '{weight_key}' in checkpoint '{model_path}'")
    num_classes = ckpt[weight_key].shape[0]
    print(f"  FusionPredictionCNN: {num_classes} classes  ←  {model_path}")
    model = FusionPredictionCNN(num_classes=num_classes)
    model.load_state_dict(ckpt)
    model.to(device)
    model.eval()
    return model


def _bin_error(actual: float, bins: np.ndarray, bin_idx: int) -> float:
    """
    Compute prediction error for a single window.

    bin_idx is the raw np.digitize output (1-based, clamped to valid range).
    The predicted interval is [bins[bin_idx-1], bins[bin_idx]] for interior
    bins, or an open-ended half-line for the two overflow buckets.

    Returns 0.0 if actual falls within the predicted interval, otherwise
    the distance to the nearer edge.
    """
    n = len(bins)

    # Overflow buckets: below first edge or above last edge
    if bin_idx == 0:
        edge = bins[0]
        return 0.0 if actual <= edge else abs(actual - edge)
    if bin_idx >= n:
        edge = bins[-1]
        return 0.0 if actual >= edge else abs(actual - edge)

    # Interior bin: interval is [bins[bin_idx-1], bins[bin_idx]]
    lo, hi = bins[bin_idx - 1], bins[bin_idx]
    if lo <= actual <= hi:
        return 0.0
    return float(min(abs(actual - lo), abs(actual - hi)))


def add_fusion_prediction_v1_scores(
    wm,
    model_path: str,
    img_size:   int              = 224,
    batch_size: int              = 32,
    device:     torch.device | None = None,
    overwrite:  bool             = False,
):
    """
    Run batched inference with a trained FusionPredictionCNN (v1) over every
    window in a WindowMatrix and add two columns:

      ``fusion_pred_v1``
          Predicted class index (argmax over model outputs).  Class indices
          are assigned alphabetically by ImageFolder, matching the 14 merged
          categories the v1 model was trained on (see V1_CLASS_INTERVALS).

      ``fusion_pred_v1_error``
          Distance from the true next-step diff to the nearest edge of the
          predicted interval.  Zero if the true diff lies within the interval.
          The true diff is x[start + window_samples] - x[start + window_samples - 1],
          matching the labelling convention in sort_fusion().

    Parameters
    ----------
    wm : WindowMatrix
        The matrix to add columns to.
    model_path : str
        Path to the saved FusionPredictionCNN v1 ``.pth`` state-dict.
    img_size : int
        CNN input image size in pixels (default 224).
    batch_size : int
        Windows per GPU/CPU batch (default 32).
    device : torch.device, optional
        Inference device.  Auto-detected (CUDA → CPU) if not supplied.
    overwrite : bool
        If False (default), skip and warn if columns already exist.

    Returns
    -------
    wm  (for chaining)
    """
    # ── V1 class intervals (sorted alphabetically = ImageFolder class order) ──
    # Each entry is (lo, hi) for the interval [lo, hi].
    # Class index → folder name → interval:
    #   0  neg_1e3_to_neg_5e4   [-1e-3,  -5e-4]
    #   1  neg_1e4_to_neg_5e5   [-1e-4,  -5e-5]
    #   2  neg_1e5_to_neg_5e6   [-1e-5,  -5e-6]
    #   3  neg_1e8_to_zero      [-1e-8,   0   ]
    #   4  neg_5e4_to_neg_1e4   [-5e-4,  -1e-4]
    #   5  neg_5e5_to_neg_1e5   [-5e-5,  -1e-5]
    #   6  neg_5e6_to_neg_1e6   [-5e-6,  -1e-6]
    #   7  pos_1e4_to_pos_5e4   [ 1e-4,   5e-4]
    #   8  pos_1e5_to_pos_5e5   [ 1e-5,   5e-5]
    #   9  pos_1e6_to_pos_5e6   [ 1e-6,   5e-6]
    #  10  pos_5e4_to_pos_1e3   [ 5e-4,   1e-3]
    #  11  pos_5e5_to_pos_1e4   [ 5e-5,   1e-4]
    #  12  pos_5e6_to_pos_1e5   [ 5e-6,   1e-5]
    #  13  zero_to_pos_1e8      [ 0,      1e-8]
    V1_CLASS_INTERVALS = [
        (-1e-3, -5e-4),   #  0
        (-1e-4, -5e-5),   #  1
        (-1e-5, -5e-6),   #  2
        (-1e-8,  0.0  ),  #  3
        (-5e-4, -1e-4),   #  4
        (-5e-5, -1e-5),   #  5
        (-5e-6, -1e-6),   #  6
        ( 1e-4,  5e-4),   #  7
        ( 1e-5,  5e-5),   #  8
        ( 1e-6,  5e-6),   #  9
        ( 5e-4,  1e-3),   # 10
        ( 5e-5,  1e-4),   # 11
        ( 5e-6,  1e-5),   # 12
        ( 0.0,   1e-8),   # 13
    ]

    COL_PRED  = "fusion_pred_v1"
    COL_ERROR = "fusion_pred_v1_error"

    if COL_PRED in wm.columns and not overwrite:
        print(f"[add_fusion_prediction_v1_scores] columns already exist — skipping "
              f"(pass overwrite=True to recompute)")
        return wm

    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print(f"[add_fusion_prediction_v1_scores] device={device}  model={model_path}")

    model     = _load_fusion_prediction_model(model_path, device)
    # Use cnn_fusion_prediction's transform (RGB-only, no is_rgb param)
    from cnn.cnn_fusion_prediction import get_transforms as get_pred_transforms
    transform = get_pred_transforms(img_size, is_train=False)

    starts         = list(wm.df.index)
    window_samples = wm._window_samples
    x              = wm._x

    pred_classes = {}   # {start_idx: int}
    pred_errors  = {}   # {start_idx: float}

    iterator = range(0, len(starts), batch_size)
    if TQDM:
        iterator = tqdm(iterator, desc="Fusion prediction v1", unit="batch",
                        total=(len(starts) + batch_size - 1) // batch_size)

    with torch.no_grad():
        for batch_i in iterator:
            batch_starts = starts[batch_i : batch_i + batch_size]

            tensors = [
                window_to_tensor(x, s, window_samples, transform)
                for s in batch_starts
            ]
            batch_tensor = torch.cat(tensors, dim=0).to(device)   # (B, C, H, W)
            logits       = model(batch_tensor)                      # (B, num_classes)
            class_indices = logits.argmax(dim=1).cpu().numpy()      # (B,)

            for s, cls_idx in zip(batch_starts, class_indices):
                # True diff: last sample in window → immediate next sample
                end = s + window_samples
                actual_diff = float(x[end] - x[end - 1]) if end < len(x) else 0.0

                lo, hi = V1_CLASS_INTERVALS[int(cls_idx)]
                if lo <= actual_diff <= hi:
                    error = 0.0
                else:
                    error = float(min(abs(actual_diff - lo), abs(actual_diff - hi)))

                pred_classes[int(s)] = int(cls_idx)
                pred_errors[int(s)]  = error

            if not TQDM and (batch_i // batch_size) % 50 == 0:
                done = min(batch_i + batch_size, len(starts))
                print(f"  [{done}/{len(starts)}] windows scored")

    wm.add_external_column(COL_PRED,  pred_classes, overwrite=overwrite)
    wm.add_external_column(COL_ERROR, pred_errors,  overwrite=overwrite)

    print(f"[add_fusion_prediction_v1_scores] done — added '{COL_PRED}' and '{COL_ERROR}'")
    return wm


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="Apply CNN to sliding EEG windows")
    p.add_argument("--mat",        type=str,   default=DEFAULTS["mat"])
    p.add_argument("--model",      type=str,   default=DEFAULTS["model"])
    p.add_argument("--fs_raw",     type=float, default=DEFAULTS["fs_raw"],
                   help="Sampling rate of raw .mat data (Hz)")
    p.add_argument("--fs_target",  type=float, default=DEFAULTS["fs_target"],
                   help="Target sampling rate after downsampling (Hz)")
    p.add_argument("--window_min", type=float, default=DEFAULTS["window_min"],
                   help="Window length in minutes")
    p.add_argument("--step_min",   type=float, default=DEFAULTS["step_min"],
                   help="Step size in minutes")
    p.add_argument("--img_size",   type=int,   default=DEFAULTS["img_size"],
                   help="CNN input image size (pixels)")
    p.add_argument("--batch_size", type=int,   default=DEFAULTS["batch_size"])
    p.add_argument("--out_dir",    type=str,   default=DEFAULTS["out_dir"])
    return p.parse_args()


def main():
    args   = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\nDevice : {device}")
    if device.type == "cuda":
        print(f"GPU    : {torch.cuda.get_device_name(0)}")

    # ── Load & downsample ────────────────────────────────────────────────────
    print("\n[1/5] Loading data...")
    x_raw = load_signal(args.mat)

    print("\n[2/5] Downsampling...")
    x = downsample(x_raw, args.fs_raw, args.fs_target)
    fs = args.fs_target

    # ── Window parameters ────────────────────────────────────────────────────
    window_samples = int(args.window_min * 60 * fs)
    step_samples   = int(args.step_min   * 60 * fs)

    print(f"\n[3/5] Generating windows  "
          f"(window={args.window_min}min={window_samples}s, "
          f"step={args.step_min}min={step_samples}s)...")
    starts = generate_windows(x, window_samples, step_samples)

    # ── Model ────────────────────────────────────────────────────────────────
    print("\n[4/5] Loading model...")
    model     = load_model(args.model, device)
    transform = get_transforms(args.img_size, is_train=False, is_rgb=True)

    # ── Inference ────────────────────────────────────────────────────────────
    print(f"\n[5/5] Running inference  (batch_size={args.batch_size})...")
    scores = run_inference_batched(
        x, starts, window_samples,
        model, transform, device,
        args.batch_size,
    )

    # ── Save ─────────────────────────────────────────────────────────────────
    out_file = (
        f"scores_{args.window_min:g}min_step{args.step_min:g}min.pkl"
    )
    save_scores(scores, args.out_dir, filename=out_file)
    print("\nDone.")


if __name__ == "__main__":
    main()
