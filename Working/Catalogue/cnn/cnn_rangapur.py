"""
cnn_rangapur.py

Trains four CNNs (one per image type: fusion, recurrence, GADF, GASF)
on the EEG gramian dataset stored on the HPC.

Usage:
    python cnn_rangapur.py
    python cnn_rangapur.py --epochs 30 --batch_size 64 --lr 1e-4
    python cnn_rangapur.py --resume          # resume all models from last checkpoint
    python cnn_rangapur.py --image_type GASF # train only one image type
"""

# ============================================================
#  CONFIG  — change these without touching the rest of the code
# ============================================================
CFG = {
    "data_root":    "DATA/derived/windows",
    "timescale":    "10min",
    "fs":           "1.0",
    "image_types":  ["fusion", "recurrence", "GADF", "GASF"],
    "img_size":     224,          # resize all images to img_size x img_size
    "val_split":    0.2,          # fraction of data held out for validation
    "epochs":       25,
    "batch_size":   256,          # A100 40GB — EfficientNet-B0 fits easily
    "lr":           1e-3,
    "patience":     7,            # early stopping: stop after N epochs without improvement
    "num_workers":  8,            # keep A100 fed; set 0 on Windows
    "models_dir":   "models",
    "metrics_dir":  "metrics",
    "seed":         42,
}
# ============================================================

import os
import re
import sys
import json
import argparse
import time
import random
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, random_split
from torchvision import datasets, transforms
from torchvision.models import efficientnet_b0, EfficientNet_B0_Weights


# ── Reproducibility ────────────────────────────────────────────────────────
def set_seed(seed: int):
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


# ── Data ───────────────────────────────────────────────────────────────────

def get_transforms(img_size: int, is_train: bool, is_rgb: bool):
    """
    Returns a transform pipeline.
    fusion images are RGB (3-channel); all others are grayscale (1-channel).
    Training set gets light augmentation; val set does not.
    """
    norm_mean = [0.5, 0.5, 0.5] if is_rgb else [0.5]
    norm_std  = [0.5, 0.5, 0.5] if is_rgb else [0.5]

    base = [transforms.Resize((img_size, img_size))]

    if is_train:
        base += [
            transforms.RandomHorizontalFlip(),
            transforms.RandomVerticalFlip(),
            transforms.ColorJitter(brightness=0.2, contrast=0.2),
        ]

    base += [
        transforms.ToTensor(),
        transforms.Normalize(mean=norm_mean, std=norm_std),
    ]

    # Grayscale images: convert to 1-channel, then repeat to 3 for the model
    if not is_rgb:
        base.insert(0, transforms.Grayscale(num_output_channels=3))
        # Normalize now needs 3-channel stats
        base[-1] = transforms.Normalize(mean=[0.5, 0.5, 0.5],
                                         std= [0.5, 0.5, 0.5])

    return transforms.Compose(base)


def build_dataset_path(data_root: str, timescale: str, fs: str,
                       image_type: str) -> Path:
    """
    Return the ImageFolder root for one image type:
        {data_root}/{timescale}_fs{fs}/{image_type}/

    e.g. DATA/derived/windows/10min_fs1.0/GASF/

    That directory contains one subdirectory per class
    (interesting/, notinteresting/), which is exactly the layout
    torchvision's ImageFolder expects.
    """
    root = Path(data_root) / f"{timescale}_fs{fs}" / image_type
    if not root.is_dir():
        raise FileNotFoundError(
            f"Dataset root '{root}' not found. Expected "
            f"<data_root>/<timescale>_fs<fs>/<image_type>/<class>/*.png"
        )

    classes = sorted(d.name for d in root.iterdir() if d.is_dir())
    if not classes:
        raise FileNotFoundError(f"No class subdirectories found under '{root}'")
    return root


def make_image_folder_dataset(data_root: str, timescale: str, fs: str,
                               image_type: str, img_size: int):
    """
    Build train/val ImageFolder datasets for one image type.

    The on-disk layout puts encoding as parent and class as child, so each
    encoding directory is directly a valid ImageFolder root — no symlink
    staging needed. (An earlier layout stored class and encoding fused into a
    single flat folder name, which required staging symlinks to synthesise the
    nested structure; that indirection is gone, along with the Windows
    incompatibility it caused.)

    Class indices remain alphabetical — interesting=0, notinteresting=1 —
    matching every trained model and the hardcoded ordering in apply_cnn.py.
    """
    root = build_dataset_path(data_root, timescale, fs, image_type)
    is_rgb = (image_type == "fusion")

    # Two instances so train and val each get their own transform
    train_ds = datasets.ImageFolder(
        str(root),
        transform=get_transforms(img_size, is_train=True,  is_rgb=is_rgb),
    )
    val_ds = datasets.ImageFolder(
        str(root),
        transform=get_transforms(img_size, is_train=False, is_rgb=is_rgb),
    )
    return train_ds, val_ds, root


def split_dataset(dataset, val_fraction: float, seed: int):
    """Split a dataset into train / val subsets."""
    n_val   = max(1, int(len(dataset) * val_fraction))
    n_train = len(dataset) - n_val
    return random_split(
        dataset, [n_train, n_val],
        generator=torch.Generator().manual_seed(seed),
    )


# ── Model ──────────────────────────────────────────────────────────────────

class EEG_CNN(nn.Module):
    """
    Lightweight CNN built on EfficientNet-B0 with a replaced classifier head.

    EfficientNet-B0 is small (~5M params), converges fast, and outperforms
    a hand-rolled conv stack on small datasets. The pretrained ImageNet
    weights give a strong starting point even for gramian images.
    """

    def __init__(self, num_classes: int):
        super().__init__()
        self.backbone = efficientnet_b0(weights=EfficientNet_B0_Weights.DEFAULT)
        in_features = self.backbone.classifier[1].in_features
        self.backbone.classifier = nn.Sequential(
            nn.Dropout(p=0.3),
            nn.Linear(in_features, num_classes),
        )

    def forward(self, x):
        return self.backbone(x)


# ── Training utilities ─────────────────────────────────────────────────────

class EarlyStopping:
    def __init__(self, patience: int, model_path: str):
        self.patience   = patience
        self.model_path = model_path
        self.best_acc   = -1.0
        self.counter    = 0
        self.best_state = None

    def step(self, val_acc: float, model: nn.Module) -> bool:
        """Returns True if training should stop."""
        if val_acc > self.best_acc:
            self.best_acc   = val_acc
            self.counter    = 0
            self.best_state = {k: v.cpu().clone()
                               for k, v in model.state_dict().items()}
            torch.save(self.best_state, self.model_path)
        else:
            self.counter += 1
        return self.counter >= self.patience

    def restore_best(self, model: nn.Module):
        if self.best_state is not None:
            model.load_state_dict(self.best_state)


def train_one_epoch(model, loader, criterion, optimizer, scaler, device) -> float:
    model.train()
    total_loss = 0.0
    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        optimizer.zero_grad()
        with torch.autocast(device_type=device.type):
            loss = criterion(model(imgs), labels)
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        total_loss += loss.item() * imgs.size(0)
    return total_loss / len(loader.dataset)


@torch.no_grad()
def validate(model, loader, criterion, device) -> tuple[float, float]:
    model.eval()
    total_loss, correct = 0.0, 0
    for imgs, labels in loader:
        imgs, labels = imgs.to(device), labels.to(device)
        logits = model(imgs)
        total_loss += criterion(logits, labels).item() * imgs.size(0)
        correct    += (logits.argmax(1) == labels).sum().item()
    n = len(loader.dataset)
    return total_loss / n, correct / n


def load_checkpoint(model, optimizer, scheduler, ckpt_path: str, device):
    """Load a mid-training checkpoint. Returns the epoch to resume from."""
    ckpt = torch.load(ckpt_path, map_location=device)
    model.load_state_dict(ckpt["model"])
    optimizer.load_state_dict(ckpt["optimizer"])
    if scheduler and "scheduler" in ckpt:
        scheduler.load_state_dict(ckpt["scheduler"])
    print(f"  Resumed from epoch {ckpt['epoch']} (best val acc: {ckpt['best_acc']:.4f})")
    return ckpt["epoch"] + 1, ckpt["best_acc"]


def save_checkpoint(model, optimizer, scheduler, epoch: int,
                    best_acc: float, ckpt_path: str):
    torch.save({
        "epoch":     epoch,
        "model":     model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict() if scheduler else None,
        "best_acc":  best_acc,
    }, ckpt_path)


# ── Main training routine ──────────────────────────────────────────────────

def train_image_type(image_type: str, cfg: dict, device: torch.device,
                     resume: bool):
    print(f"\n{'='*60}")
    print(f"  IMAGE TYPE: {image_type}")
    print(f"{'='*60}")

    # ── Paths ────────────────────────────────────────────────────────────
    os.makedirs(cfg["models_dir"],  exist_ok=True)
    os.makedirs(cfg["metrics_dir"], exist_ok=True)
    model_path = os.path.join(cfg["models_dir"],  f"{image_type}_cnn.pth")
    ckpt_path  = os.path.join(cfg["models_dir"],  f"{image_type}_checkpoint.pth")
    metrics_path = os.path.join(cfg["metrics_dir"], f"{image_type}_metrics.json")

    # ── Dataset ──────────────────────────────────────────────────────────
    train_full, val_full, data_dir = make_image_folder_dataset(
        cfg["data_root"], cfg["timescale"], cfg["fs"],
        image_type, cfg["img_size"],
    )
    num_classes = len(train_full.classes)
    print(f"  Dataset root: {data_dir}")
    print(f"  Classes ({num_classes}): {train_full.classes}")
    print(f"  Total images: {len(train_full)}")

    train_subset, _ = split_dataset(train_full, cfg["val_split"], cfg["seed"])
    _,  val_subset  = split_dataset(val_full,   cfg["val_split"], cfg["seed"])

    train_loader = DataLoader(train_subset, batch_size=cfg["batch_size"],
                              shuffle=True,  num_workers=cfg["num_workers"],
                              pin_memory=True)
    val_loader   = DataLoader(val_subset,   batch_size=cfg["batch_size"],
                              shuffle=False, num_workers=cfg["num_workers"],
                              pin_memory=True)
    print(f"  Train: {len(train_subset)}  |  Val: {len(val_subset)}")

    # ── Model ─────────────────────────────────────────────────────────────
    model     = EEG_CNN(num_classes).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=cfg["lr"])
    scheduler = optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=cfg["epochs"], eta_min=1e-6
    )
    scaler     = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    early_stop = EarlyStopping(patience=cfg["patience"], model_path=model_path)

    start_epoch = 0
    if resume and os.path.isfile(ckpt_path):
        start_epoch, early_stop.best_acc = load_checkpoint(
            model, optimizer, scheduler, ckpt_path, device
        )

    # ── Training loop ─────────────────────────────────────────────────────
    history = {"train_loss": [], "val_loss": [], "val_acc": []}

    for epoch in range(start_epoch, cfg["epochs"]):
        t0 = time.time()

        train_loss          = train_one_epoch(model, train_loader, criterion, optimizer, scaler, device)
        val_loss, val_acc   = validate(model, val_loader, criterion, device)
        scheduler.step()

        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)
        history["val_acc"].append(val_acc)

        elapsed = time.time() - t0
        print(
            f"  Epoch {epoch+1:3d}/{cfg['epochs']}  "
            f"train_loss={train_loss:.4f}  "
            f"val_loss={val_loss:.4f}  "
            f"val_acc={val_acc:.4f}  "
            f"({elapsed:.1f}s)"
        )

        save_checkpoint(model, optimizer, scheduler, epoch,
                        early_stop.best_acc, ckpt_path)

        if early_stop.step(val_acc, model):
            print(f"  Early stopping at epoch {epoch+1} "
                  f"(best val acc: {early_stop.best_acc:.4f})")
            break

    # ── Finalise ──────────────────────────────────────────────────────────
    early_stop.restore_best(model)
    torch.save(model.state_dict(), model_path)
    print(f"  Saved best model → {model_path}")

    with open(metrics_path, "w") as f:
        json.dump(history, f, indent=2)
    print(f"  Saved metrics   → {metrics_path}")

    # (No staging cleanup needed — ImageFolder reads the dataset directly.)


# ── Entry point ────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Train EEG gramian CNNs on HPC")
    p.add_argument("--epochs",      type=int,   default=CFG["epochs"])
    p.add_argument("--batch_size",  type=int,   default=CFG["batch_size"])
    p.add_argument("--lr",          type=float, default=CFG["lr"])
    p.add_argument("--patience",    type=int,   default=CFG["patience"])
    p.add_argument("--img_size",    type=int,   default=CFG["img_size"])
    p.add_argument("--resume",      action="store_true",
                   help="Resume all models from their last checkpoint")
    p.add_argument("--image_type",  type=str,   default=None,
                   choices=CFG["image_types"],
                   help="Train only this image type (default: train all four)")
    return p.parse_args()


def main():
    args = parse_args()

    # Merge CLI args into config
    cfg = {**CFG}
    cfg["epochs"]     = args.epochs
    cfg["batch_size"] = args.batch_size
    cfg["lr"]         = args.lr
    cfg["patience"]   = args.patience
    cfg["img_size"]   = args.img_size

    set_seed(cfg["seed"])

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if device.type == "cuda":
        print(f"GPU:    {torch.cuda.get_device_name(0)}")
        torch.backends.cudnn.benchmark = True   # optimise kernels for fixed input size

    targets = [args.image_type] if args.image_type else cfg["image_types"]

    for image_type in targets:
        train_image_type(image_type, cfg, device, resume=args.resume)

    print("\nAll done.")


if __name__ == "__main__":
    main()
