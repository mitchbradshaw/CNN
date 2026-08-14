"""
test_cnn.py

Three modes:
  1. Single image  — predict class + confidence for one image file
  2. Flat folder   — run inference on a flat folder of images (no class subfolders)
  3. Class folder  — run inference on an ImageFolder (class subfolders) and report accuracy

Usage:
  python test_cnn.py --model models/fusion_cnn.pth --image path/to/img.png --image_type fusion
  python test_cnn.py --model models/fusion_cnn.pth --folder DATA/.../fusion_interesting --image_type fusion
  python test_cnn.py --model models/fusion_cnn.pth --folder path/to/test_dir --image_type fusion --class_folder
"""


import argparse
import os
import re
import sys
from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

# Allow running directly from inside the cnn/ subfolder or from the project root
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
from Working.Catalogue.cnn.cnn_rangapur import EEG_CNN, get_transforms


# ── Helpers ────────────────────────────────────────────────────────────────

def load_model(model_path: str, num_classes: int, device: torch.device) -> EEG_CNN:
    model = EEG_CNN(num_classes=num_classes)
    model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
    model.to(device)
    model.eval()
    return model


def detect_num_classes(model_path: str, device: torch.device) -> int:
    """Read num_classes directly from the saved weight shape."""
    ckpt = torch.load(model_path, map_location=device, weights_only=True)
    return ckpt["backbone.classifier.1.weight"].shape[0]


# ── Flat-folder dataset ────────────────────────────────────────────────────

class FlatImageDataset(Dataset):
    """Loads all images from a flat directory (no class subfolders required)."""
    EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}

    def __init__(self, folder: str, transform):
        self.paths     = sorted(
            p for p in Path(folder).iterdir()
            if p.suffix.lower() in self.EXTS
        )
        self.transform = transform
        if not self.paths:
            raise FileNotFoundError(f"No images found in {folder!r}")

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, idx):
        img = Image.open(self.paths[idx]).convert("RGB")
        return self.transform(img), str(self.paths[idx].name)


# ── Single image ───────────────────────────────────────────────────────────

def predict_single(model_path: str, image_path: str, image_type: str,
                   img_size: int, device: torch.device):
    num_classes = detect_num_classes(model_path, device)
    print(f"Detected num_classes: {num_classes}")

    model     = load_model(model_path, num_classes, device)
    transform = get_transforms(img_size, is_train=False, is_rgb=(image_type == "fusion"))

    img    = Image.open(image_path).convert("RGB")
    tensor = transform(img).unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(tensor)
        probs  = torch.softmax(logits, dim=1)[0]
        pred   = probs.argmax().item()

    print(f"Predicted class index : {pred}")
    print(f"Confidence            : {probs[pred]:.4f}")
    print("All class probabilities:")
    for i, p in enumerate(probs.tolist()):
        marker = " <--" if i == pred else ""
        print(f"  class {i}: {p:.4f}{marker}")


# ── Flat folder (inference only, no accuracy) ──────────────────────────────

def predict_flat_folder(model_path: str, folder_path: str, image_type: str,
                        img_size: int, batch_size: int, device: torch.device):
    num_classes = detect_num_classes(model_path, device)
    print(f"Detected num_classes: {num_classes}")

    model     = load_model(model_path, num_classes, device)
    transform = get_transforms(img_size, is_train=False, is_rgb=(image_type == "fusion"))

    dataset = FlatImageDataset(folder_path, transform)
    loader  = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    print(f"Total images: {len(dataset)}")

    counts = [0] * num_classes
    with torch.no_grad():
        for imgs, names in loader:
            imgs  = imgs.to(device)
            preds = torch.softmax(model(imgs), dim=1)
            for pred, name in zip(preds, names):
                cls = pred.argmax().item()
                counts[cls] += 1
                print(f"  {name}  ->  class {cls}  (conf {pred[cls]:.3f})")

    print(f"\nSummary over {len(dataset)} images:")
    for i, c in enumerate(counts):
        print(f"  class {i}: {c} ({100*c/len(dataset):.1f}%)")


# ── Category-aware test dataset ────────────────────────────────────────────

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".ppm", ".bmp", ".pgm", ".tif", ".tiff", ".webp"}

def _extract_category(folder_name: str, image_type: str) -> str:
    """
    Extract the category label from a folder name following the pattern:
      [timescale]min_fs[fs]_[category]_[image_type]_test
    e.g. '10min_fs1.0_interesting_GASF_test'  →  'interesting'
    """
    m = re.match(
        rf"^\w+min_fs[\d.]+_(.+)_{re.escape(image_type)}_test$",
        folder_name,
        re.IGNORECASE,
    )
    return m.group(1) if m else folder_name


class CategoryImageDataset(Dataset):
    """
    Finds subfolders of folder_path whose names match
      *_[image_type]_test
    and treats the segment between 'fs[x.x]_' and '_{image_type}_test' as the
    class label (e.g. 'interesting', 'notinteresting').
    Class indices are assigned alphabetically to match ImageFolder training order.
    """

    def __init__(self, folder_path: str, image_type: str, transform):
        pattern = re.compile(
            rf"^\w+min_fs[\d.]+_.+_{re.escape(image_type)}_test$",
            re.IGNORECASE,
        )
        matched = sorted(
            sub for sub in Path(folder_path).iterdir()
            if sub.is_dir()
            and pattern.match(sub.name)
            and _extract_category(sub.name, image_type) != "flag"
        )
        if not matched:
            raise FileNotFoundError(
                f"No subfolders matching '*_{image_type}_test' found in {folder_path!r}.\n"
                f"Expected pattern: [timescale]min_fs[fs]_[category]_{image_type}_test"
            )

        categories = sorted({_extract_category(sub.name, image_type) for sub in matched})
        self.class_to_idx = {c: i for i, c in enumerate(categories)}
        print(f"  Matched subfolders : {[s.name for s in matched]}")
        print(f"  Class map          : {self.class_to_idx}")

        self.samples: list[tuple[str, int]] = []
        for sub in matched:
            cat = _extract_category(sub.name, image_type)
            idx = self.class_to_idx[cat]
            for f in sorted(sub.iterdir()):
                if f.is_file() and f.suffix.lower() in _IMG_EXTS:
                    self.samples.append((str(f), idx))

        if not self.samples:
            raise FileNotFoundError(
                f"No image files found in the matched subfolders of {folder_path!r}"
            )

        self.transform = transform

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        img = Image.open(path).convert("RGB")
        return self.transform(img), label


# ── Class folder (reports accuracy) ────────────────────────────────────────

def predict_class_folder(model_path: str, folder_path: str, image_type: str,
                         img_size: int, batch_size: int, device: torch.device):
    num_classes = detect_num_classes(model_path, device)
    print(f"Detected num_classes: {num_classes}")

    model     = load_model(model_path, num_classes, device)
    transform = get_transforms(img_size, is_train=False, is_rgb=(image_type == "fusion"))

    dataset = CategoryImageDataset(folder_path, image_type, transform)
    loader  = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    print(f"Total images: {len(dataset)}")

    correct = 0
    with torch.no_grad():
        for imgs, labels in loader:
            imgs, labels = imgs.to(device), labels.to(device)
            correct += (model(imgs).argmax(dim=1) == labels).sum().item()

    accuracy = correct / len(dataset)
    print(f"\nAccuracy: {correct}/{len(dataset)} = {accuracy:.4f} ({accuracy*100:.1f}%)")


# ── Entry point ────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Test a trained EEG CNN")
    p.add_argument("--model",        required=True,
                   help="Path to .pth model file")
    p.add_argument("--image_type",   required=True,
                   choices=["fusion", "recurrence", "GADF", "GASF"],
                   help="Image type the model was trained on")
    p.add_argument("--image",        default=None,
                   help="Path to a single image file")
    p.add_argument("--folder",       default=None,
                   help="Path to a folder of images")
    p.add_argument("--class_folder", action="store_true",
                   help="Treat --folder as an ImageFolder (class subfolders) and report accuracy")
    p.add_argument("--img_size",     type=int, default=224)
    p.add_argument("--batch_size",   type=int, default=32)
    return p.parse_args()


def main():
    args   = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    if args.image:
        predict_single(args.model, args.image, args.image_type,
                       args.img_size, device)
    elif args.folder:
        if args.class_folder:
            predict_class_folder(args.model, args.folder, args.image_type,
                                 args.img_size, args.batch_size, device)
        else:
            predict_flat_folder(args.model, args.folder, args.image_type,
                                args.img_size, args.batch_size, device)
    else:
        print("Provide either --image <path> or --folder <path>")


if __name__ == "__main__":
    main()
