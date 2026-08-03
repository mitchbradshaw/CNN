# ============================================================
#  CONFIG  — change these without touching the rest of the code
# ============================================================
CFG = {
    "data_root":    "fusion_prediction",  # output of sort_fusion() in cnn_prediction.py
    "img_size":     224,
    "val_split":    0.2,
    "epochs":       50,
    "batch_size":   256,          # A100 40GB — EfficientNet-B0 fits easily
    "lr":           1e-3,
    "patience":     7,
    "num_workers":  8,            # keep A100 fed; set 0 on Windows
    "models_dir":   "MODELS",
    "metrics_dir":  "metrics",
    "seed":         42,
}
# ============================================================

import os
import json
import argparse
import time
import random
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, random_split
from PIL import Image
from torchvision import datasets, transforms
from torchvision.models import efficientnet_b0, EfficientNet_B0_Weights


# ── Reproducibility ────────────────────────────────────────────────────────
def set_seed(seed: int):
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


# ── Data ───────────────────────────────────────────────────────────────────

def get_transforms(img_size: int, is_train: bool):
    """
    Returns transform pipeline.
    Training set gets light augmentation; val set does not.
    All fusion images are RGB so normalisation is always 3-channel.
    """
    norm_mean = [0.5, 0.5, 0.5]
    norm_std  = [0.5, 0.5, 0.5]

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

    return transforms.Compose(base)


def clean_corrupt_images(data_root: str) -> int:
    """
    Walk all PNG files under data_root, attempt to open and verify each one,
    and delete any that PIL cannot read. Returns the number of files removed.
    """
    from PIL import UnidentifiedImageError
    removed = 0
    for dirpath, _, filenames in os.walk(data_root):
        for fname in filenames:
            if not fname.endswith(".png"):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with Image.open(fpath) as img:
                    img.verify()      # catches truncated / structurally broken files
            except (UnidentifiedImageError, Exception):
                print(f"  Removing corrupt file: {fpath}")
                os.remove(fpath)
                removed += 1
    if removed:
        print(f"[clean_corrupt_images] Removed {removed} corrupt file(s).")
    else:
        print("[clean_corrupt_images] No corrupt files found.")
    return removed


def load_datasets(data_root: str, img_size: int, val_split: float, seed: int):
    """
    Load the fusion_prediction directory as an ImageFolder dataset and
    split into train / val subsets.

    Expected layout (created by sort_fusion in cnn_prediction.py):
        fusion_prediction/
            neg_1e1_to_neg_5e2/
                fusion_0.png
                ...
            zero_to_pos_1e8/
                ...
    """
    root = Path(data_root)
    if not root.is_dir():
        raise FileNotFoundError(
            f"Data directory '{root}' not found. "
            "Run sort_fusion() in cnn_prediction.py first."
        )

    # Two separate ImageFolder instances so each subset gets its own transform
    train_full = datasets.ImageFolder(str(root), transform=get_transforms(img_size, is_train=True))
    val_full   = datasets.ImageFolder(str(root), transform=get_transforms(img_size, is_train=False))

    n_val   = max(1, int(len(train_full) * val_split))
    n_train = len(train_full) - n_val
    gen     = torch.Generator().manual_seed(seed)

    train_subset, _ = random_split(train_full, [n_train, n_val], generator=gen)
    _,  val_subset  = random_split(val_full,   [n_train, n_val], generator=gen)

    return train_subset, val_subset, train_full.classes


# ── Model ──────────────────────────────────────────────────────────────────

class FusionPredictionCNN(nn.Module):
    """
    EfficientNet-B0 backbone with a replaced classifier head.
    num_classes matches the number of semi-log bin categories produced
    by make_category_names() / sort_fusion() in cnn_prediction.py.
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


def save_checkpoint(model, optimizer, scheduler, epoch: int,
                    best_acc: float, ckpt_path: str):
    torch.save({
        "epoch":     epoch,
        "model":     model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict() if scheduler else None,
        "best_acc":  best_acc,
    }, ckpt_path)


def load_checkpoint(model, optimizer, scheduler, ckpt_path: str, device):
    """Load a mid-training checkpoint. Returns (start_epoch, best_acc)."""
    ckpt = torch.load(ckpt_path, map_location=device)
    model.load_state_dict(ckpt["model"])
    optimizer.load_state_dict(ckpt["optimizer"])
    if scheduler and "scheduler" in ckpt:
        scheduler.load_state_dict(ckpt["scheduler"])
    print(f"  Resumed from epoch {ckpt['epoch']} (best val acc: {ckpt['best_acc']:.4f})")
    return ckpt["epoch"] + 1, ckpt["best_acc"]


# ── Main training routine ──────────────────────────────────────────────────

def train(cfg: dict, device: torch.device, resume: bool):
    os.makedirs(cfg["models_dir"],  exist_ok=True)
    os.makedirs(cfg["metrics_dir"], exist_ok=True)
    model_path   = os.path.join(cfg["models_dir"],  "fusion_prediction_cnn.pth")
    ckpt_path    = os.path.join(cfg["models_dir"],  "fusion_prediction_checkpoint.pth")
    metrics_path = os.path.join(cfg["metrics_dir"], "fusion_prediction_metrics.json")

    # ── Sanitise dataset (remove any corrupt PNGs before loading) ────────
    clean_corrupt_images(cfg["data_root"])

    # ── Dataset ──────────────────────────────────────────────────────────
    train_subset, val_subset, classes = load_datasets(
        cfg["data_root"], cfg["img_size"], cfg["val_split"], cfg["seed"]
    )
    num_classes = len(classes)
    print(f"  Classes ({num_classes}): {classes}")
    print(f"  Train: {len(train_subset)}  |  Val: {len(val_subset)}")

    train_loader = DataLoader(train_subset, batch_size=cfg["batch_size"],
                              shuffle=True,  num_workers=cfg["num_workers"],
                              pin_memory=True)
    val_loader   = DataLoader(val_subset,   batch_size=cfg["batch_size"],
                              shuffle=False, num_workers=cfg["num_workers"],
                              pin_memory=True)

    # ── Model ─────────────────────────────────────────────────────────────
    model     = FusionPredictionCNN(num_classes).to(device)
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

        train_loss        = train_one_epoch(model, train_loader, criterion, optimizer, scaler, device)
        val_loss, val_acc = validate(model, val_loader, criterion, device)
        scheduler.step()

        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)
        history["val_acc"].append(val_acc)

        print(
            f"  Epoch {epoch+1:3d}/{cfg['epochs']}  "
            f"train_loss={train_loss:.4f}  "
            f"val_loss={val_loss:.4f}  "
            f"val_acc={val_acc:.4f}  "
            f"({time.time() - t0:.1f}s)"
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


# ── Entry point ────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Train a CNN to predict the next-step bin from fusion gramian images"
    )
    p.add_argument("--epochs",     type=int,   default=CFG["epochs"])
    p.add_argument("--batch_size", type=int,   default=CFG["batch_size"])
    p.add_argument("--lr",         type=float, default=CFG["lr"])
    p.add_argument("--patience",   type=int,   default=CFG["patience"])
    p.add_argument("--img_size",   type=int,   default=CFG["img_size"])
    p.add_argument("--data_root",  type=str,   default=CFG["data_root"],
                   help="Root directory produced by sort_fusion() (default: fusion_prediction)")
    p.add_argument("--resume",     action="store_true",
                   help="Resume from last checkpoint")
    return p.parse_args()


def main():
    args = parse_args()

    cfg = {**CFG}
    cfg["epochs"]     = args.epochs
    cfg["batch_size"] = args.batch_size
    cfg["lr"]         = args.lr
    cfg["patience"]   = args.patience
    cfg["img_size"]   = args.img_size
    cfg["data_root"]  = args.data_root

    set_seed(cfg["seed"])

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if device.type == "cuda":
        print(f"GPU:    {torch.cuda.get_device_name(0)}")

    train(cfg, device, resume=args.resume)
    print("\nDone.")


if __name__ == "__main__":
    main()
