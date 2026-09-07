"""身体部位划分 UNet 训练入口。

用法:
    python -m src.body_segmentation.train --data-dir data/processed/segmentation \
        --model-dir src/body_segmentation/models --split user --epochs 100

--split sample: 样本级 70/30 划分(验收指标 1:验证集准确率 >95%)
--split user:   用户级留出划分(验收指标 2:新用户准确率 >70%)
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn
from torch.utils.data import DataLoader, Dataset

from .augment import augment_pair
from .unet import UNet

INPUT_HEIGHT, INPUT_WIDTH = 96, 48


class SegmentationDataset(Dataset):
    """从 HDF5 + manifest 读取 (pressure, mask),按给定索引列表取样本。"""

    def __init__(
        self,
        data_dir: Path,
        indices: list[int],
        augment: bool = False,
        seed: int = 42,
    ) -> None:
        self.h5_path = Path(data_dir) / "dataset.h5"
        manifest_path = Path(data_dir) / "manifest.json"
        with open(manifest_path, encoding="utf-8") as stream:
            self.manifest = json.load(stream)
        self.indices = list(indices)
        self.augment = augment
        self.rng = np.random.default_rng(seed)
        # 全量载入内存(images ~91MB + masks ~23MB),避免逐行随机读压缩 HDF5
        with h5py.File(self.h5_path, "r") as h5:
            self.images = np.asarray(h5["images"][:], dtype=np.float32)
            self.masks = np.asarray(h5["masks"][:], dtype=np.int64)

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, item: int) -> tuple[torch.Tensor, torch.Tensor]:
        index = self.indices[item]
        pressure = self.images[index].copy()
        mask = self.masks[index].copy()
        if self.augment:
            pressure, mask = augment_pair(pressure, mask, self.rng)
        # 逐帧 min-max 归一化
        low, high = pressure.min(), pressure.max()
        pressure = (pressure - low) / max(high - low, 1e-8)
        image = torch.from_numpy(pressure).unsqueeze(0)
        image = F.interpolate(
            image.unsqueeze(0), size=(INPUT_HEIGHT, INPUT_WIDTH), mode="bilinear",
            align_corners=True,
        ).squeeze(0)
        target = torch.from_numpy(mask).unsqueeze(0).unsqueeze(0)
        target = F.interpolate(
            target.float(), size=(INPUT_HEIGHT, INPUT_WIDTH), mode="nearest"
        ).squeeze(0).squeeze(0).long()
        return image, target


def dice_loss(logits: torch.Tensor, target: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    """多类 soft Dice 损失(类别平均)。"""
    probs = torch.softmax(logits, dim=1)
    num_classes = logits.shape[1]
    target_one_hot = F.one_hot(target, num_classes=num_classes).permute(0, 3, 1, 2).float()
    intersection = (probs * target_one_hot).sum(dim=(2, 3))
    cardinality = probs.sum(dim=(2, 3)) + target_one_hot.sum(dim=(2, 3))
    dice = (2.0 * intersection + eps) / (cardinality + eps)
    return 1.0 - dice.mean()


def compute_metrics(logits: torch.Tensor, target: torch.Tensor) -> dict[str, float]:
    """在模型分辨率网格上计算像素准确率与 mIoU。"""
    pred = torch.argmax(logits, dim=1)
    num_classes = logits.shape[1]
    correct = (pred == target).sum().item()
    total = target.numel()
    ious = []
    for cls in range(num_classes):
        inter = ((pred == cls) & (target == cls)).sum().item()
        union = ((pred == cls) | (target == cls)).sum().item()
        ious.append(inter / union if union > 0 else float("nan"))
    valid_ious = [v for v in ious if not math.isnan(v)]
    return {
        "accuracy": correct / max(total, 1),
        "miou": float(np.nanmean(valid_ious)) if valid_ious else 0.0,
    }


def train(
    data_dir: Path,
    model_dir: Path,
    split: str = "user",
    epochs: int = 100,
    batch_size: int = 64,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    patience: int = 15,
    seed: int = 42,
    device: str = "auto",
) -> dict[str, Any]:
    """训练分割模型,保存 best.pt 与 metrics.json。"""
    torch.manual_seed(seed)
    np.random.seed(seed)
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[segmentation] device={device} split={split}")

    data_dir = Path(data_dir)
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    with open(data_dir / "manifest.json", encoding="utf-8") as stream:
        manifest = json.load(stream)
    split_key = {"sample": "sample_split", "user": "user_split"}[split]
    train_indices = manifest[split_key]["train"]
    val_indices = manifest[split_key]["test"]
    num_classes = manifest["num_regions"] + 1  # + background

    train_set = SegmentationDataset(data_dir, train_indices, augment=True, seed=seed)
    val_set = SegmentationDataset(data_dir, val_indices, augment=False, seed=seed)
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False, num_workers=0)

    model = UNet(in_channels=1, num_classes=num_classes).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # 类别加权:按训练集像素频率倒数(掩码已载入内存,直接用花式索引统计)
    with h5py.File(data_dir / "dataset.h5", "r") as h5:
        train_masks = np.asarray(h5["masks"][train_indices], dtype=np.int64)
    class_counts = np.asarray(
        [(train_masks == cls).sum() for cls in range(num_classes)], dtype=np.int64
    )
    class_counts = np.maximum(class_counts, 1)
    class_weights = class_counts.sum() / (num_classes * class_counts)
    ce_weight = torch.tensor(class_weights, dtype=torch.float32, device=device)
    criterion = nn.CrossEntropyLoss(weight=ce_weight)

    history: list[dict[str, float]] = []
    best_val = -1.0
    best_epoch = -1
    no_improve = 0

    for epoch in range(1, epochs + 1):
        model.train()
        running_loss = 0.0
        for image, target in train_loader:
            image, target = image.to(device), target.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(image)
            loss = criterion(logits, target) + 0.5 * dice_loss(logits, target)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * image.shape[0]
        scheduler.step()
        train_loss = running_loss / max(len(train_set), 1)

        model.eval()
        val_loss = 0.0
        acc_sum, iou_sum, count = 0.0, 0.0, 0
        with torch.no_grad():
            for image, target in val_loader:
                image, target = image.to(device), target.to(device)
                logits = model(image)
                val_loss += (criterion(logits, target) + 0.5 * dice_loss(logits, target)).item() * image.shape[0]
                metrics = compute_metrics(logits, target)
                acc_sum += metrics["accuracy"] * image.shape[0]
                iou_sum += metrics["miou"] * image.shape[0]
                count += image.shape[0]
        val_accuracy = acc_sum / max(count, 1)
        val_miou = iou_sum / max(count, 1)
        record = {
            "epoch": epoch,
            "train_loss": round(train_loss, 6),
            "val_loss": round(val_loss / max(count, 1), 6),
            "val_accuracy": round(val_accuracy, 4),
            "val_miou": round(val_miou, 4),
        }
        history.append(record)
        print(
            f"[segmentation] epoch {epoch:3d} | train_loss {train_loss:.4f} | "
            f"val_loss {record['val_loss']:.4f} | val_acc {val_accuracy:.4f} | val_mIoU {val_miou:.4f}"
        )
        if val_miou > best_val:
            best_val = val_miou
            best_epoch = epoch
            no_improve = 0
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "num_classes": num_classes,
                    "in_channels": 1,
                    "input_size": [INPUT_HEIGHT, INPUT_WIDTH],
                    "epoch": epoch,
                    "val_accuracy": val_accuracy,
                    "val_miou": val_miou,
                },
                model_dir / "best.pt",
            )
        else:
            no_improve += 1
            if no_improve >= patience:
                print(f"[segmentation] 早停:连续 {patience} 轮验证 mIoU 无提升(最优 epoch {best_epoch})")
                break

    summary = {
        "split": split,
        "best_epoch": best_epoch,
        "best_val_miou": best_val,
        "num_train": len(train_indices),
        "num_val": len(val_indices),
        "num_classes": num_classes,
        "class_weights": class_weights.tolist(),
        "history": history,
    }
    with open(model_dir / "metrics.json", "w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    print(f"[segmentation] 训练完成,best epoch={best_epoch} val_mIoU={best_val:.4f},模型已保存到 {model_dir / 'best.pt'}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a body segmentation model.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed/segmentation"))
    parser.add_argument("--model-dir", type=Path, default=Path("src/body_segmentation/models"))
    parser.add_argument("--split", choices=["sample", "user"], default="user")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    train(
        data_dir=args.data_dir,
        model_dir=args.model_dir,
        split=args.split,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        patience=args.patience,
        seed=args.seed,
        device=args.device,
    )


if __name__ == "__main__":
    main()
