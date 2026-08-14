
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

from Working.Preprocessing.window_matrix.matrix_calc import *
import os
import numpy as np
from Working.Preprocessing.manage_data.load_data import load_raw_data
from PIL import Image
from Working.Catalogue.cnn.apply_cnn import *


def make_bins(start,end,multa,multb):
    # bins
    # avg abs difference to next data point for current 0.01_percent_M2_concat_fs1.mat is 2.5e-03
    # Semi-log bins: start 1e-8, alternate ×5 and ×2 up to 1e-1, then symmetric about 0
    _pos = [start]
    while _pos[-1] < end:
        _pos.append(_pos[-1] * (multa if len(_pos) % 2 == 1 else multb))
    bins = np.array([-v for v in reversed(_pos)] + [0.0] + _pos)
    # bins: [-1e-1, -5e-2, ..., -1e-6, 0, 1e-6, ..., 5e-2, 1e-1]  (23 edges)
    print("categories:",len(bins))
    return bins

def _fmt_val(v):
    """Format a positive float for a category name. e.g. 5e-7 → '5e7'"""
    if v == 0.0:
        return "0"
    mantissa, exp = f"{v:.0e}".split("e")
    return f"{mantissa}e{abs(int(exp))}"


def make_category_names(bins):
    """
    Return a list of len(bins)+1 human-readable category names matching
    the index that np.digitize returns for each bin.
    """
    names = [f"below_neg_{_fmt_val(abs(bins[0]))}"]

    for k in range(1, len(bins)):
        lo, hi = bins[k - 1], bins[k]
        if lo < 0 and hi <= 0:
            lo_s = f"neg_{_fmt_val(abs(lo))}"
            hi_s = "zero" if hi == 0.0 else f"neg_{_fmt_val(abs(hi))}"
        elif lo >= 0:
            lo_s = "zero" if lo == 0.0 else f"pos_{_fmt_val(lo)}"
            hi_s = f"pos_{_fmt_val(hi)}"
        else:                          # lo < 0, hi > 0  (spans zero)
            lo_s = f"neg_{_fmt_val(abs(lo))}"
            hi_s = f"pos_{_fmt_val(hi)}"
        names.append(f"{lo_s}_to_{hi_s}")

    names.append(f"above_pos_{_fmt_val(bins[-1])}")
    return names


def sort_fusion(x, bins, window_samples, step_samples):
    """
    For each sliding window, compute the fusion gramian image, determine
    which bin the post-window change falls into, and save the image to:
        fusion_prediction/<category_name>/fusion_<start_idx>.png

    The label is the change from the last sample in the window to the
    immediate next sample — i.e. x[i+window_samples] - x[i+window_samples-1].
    """
    cat_names = make_category_names(bins)
    for name in cat_names:
        os.makedirs(os.path.join("fusion_prediction", name), exist_ok=True)

    for i in range(0, len(x) - window_samples, step_samples):
        x_win = x[i : i + window_samples]

        # Change from the last sample in the window to the immediate next sample
        diff = x[i + window_samples] - x[i + window_samples - 1]

        # Bin assignment (returns 0..len(bins) inclusive)
        cat_idx  = int(np.digitize(diff, bins))
        cat_name = cat_names[cat_idx]

        # Compute fusion image and save as RGB PNG
        fusion    = compute_fusion(x_win)                              # (H, W, 3) float [0,1]
        img_uint8 = (fusion * 255).clip(0, 255).astype(np.uint8)
        Image.fromarray(img_uint8, mode="RGB").save(
            os.path.join("fusion_prediction", cat_name, f"fusion_{i}.png")
        )

# ------------------------------------------------------------------ #
#  fusion_prediction distribution
# ------------------------------------------------------------------ #

def count_fusion_categories(fusion_dir="fusion_prediction"):
    counts = {}
    for cat in sorted(os.listdir(fusion_dir)):
        cat_path = os.path.join(fusion_dir, cat)
        if os.path.isdir(cat_path):
            counts[cat] = sum(1 for f in os.listdir(cat_path) if f.endswith(".png"))

    total = sum(counts.values())
    print(f"{'Category':<40}  {'Count':>6}  {'%':>6}")
    print("-" * 56)
    for cat, n in counts.items():
        print(f"{cat:<40}  {n:>6}  {n/total*100:>5.1f}%")
    print("-" * 56)
    print(f"{'TOTAL':<40}  {total:>6}")
    return counts

def merge_fusion_categories(cat_name_a, cat_name_b, fusion_dir="fusion_prediction"):
    """
    Merge all PNG images from cat_name_b into cat_name_a, then delete the
    empty cat_name_b folder. cat_name_a (the lower bound) is kept as the
    merged category name.

    Filenames that collide are made unique by prefixing the source category.
    """
    cat_a_path = os.path.join(fusion_dir, cat_name_a)
    cat_b_path = os.path.join(fusion_dir, cat_name_b)

    if not os.path.isdir(cat_a_path):
        raise FileNotFoundError(f"Category folder not found: '{cat_a_path}'")
    if not os.path.isdir(cat_b_path):
        raise FileNotFoundError(f"Category folder not found: '{cat_b_path}'")

    existing = set(os.listdir(cat_a_path))
    moved = 0
    for fname in os.listdir(cat_b_path):
        if not fname.endswith(".png"):
            continue
        dest_name = fname if fname not in existing else f"{cat_name_b}__{fname}"
        os.rename(
            os.path.join(cat_b_path, fname),
            os.path.join(cat_a_path, dest_name),
        )
        existing.add(dest_name)
        moved += 1

    os.rmdir(cat_b_path)
    print(f"Merged {moved} images from '{cat_name_b}' into '{cat_name_a}' and removed '{cat_name_b}'")


filename = "0.01_percent_M2_concat_fs1.mat"
x, t = load_raw_data(filename,1,"VECTOR")

# for each window of length 10 minutes (600 samples) generate fusion plot
# stepfrac = 9/600
# window_samples = 1 * 10 * 60
# step_samples = int(stepfrac*window_samples)
#bins = make_bins(1e-08,1e-01,5,2)
#sort_fusion(x,bins,window_samples,step_samples)