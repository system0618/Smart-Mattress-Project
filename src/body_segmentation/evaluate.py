"""身体部位划分模型评估。

按两种口径评估并输出 metrics.json:
- 样本级 70/30 验证集(验收指标 1:准确率 >95%)
- 用户级留出"新用户"验证集(验收指标 2:准确率 >70%)

同时输出每类 precision/recall/F1、按睡姿分组指标与混淆矩阵。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import torch
import torch.nn.functional as F

from .unet import UNet

SLEEP_POSE_NAMES = {0: "supine", 1: "prone", 2: "left_lateral", 3: "right_lateral"}


def load_model(model_path: Path, device: str) -> tuple[UNet, dict[str, Any]]:
    checkpoint = torch.load(model_path, map_location=device)
    model = UNet(
        in_channels=checkpoint.get("in_channels", 1),
        num_classes=checkpoint.get("num_classes", 6),
    ).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    return model, checkpoint


@torch.no_grad()
def predict(model: UNet, images: torch.Tensor, device: str, input_size: tuple[int, int]) -> torch.Tensor:
    """批量推理并插值回 (44, 24) 原网格。"""
    resized = F.interpolate(
        images, size=input_size, mode="bilinear", align_corners=True
    ).to(device)
    logits = model(resized)
    probs = F.interpolate(
        torch.softmax(logits, dim=1), size=(44, 24), mode="bilinear", align_corners=True
    )
    return torch.argmax(probs, dim=1).cpu()


def evaluate_split(
    model: UNet,
    h5_path: Path,
    indices: list[int],
    entries: list[dict[str, Any]],
    device: str,
    input_size: tuple[int, int],
    num_classes: int,
    batch_size: int = 256,
) -> dict[str, Any]:
    """对一个划分口径计算全部指标。"""
    preds_all: list[np.ndarray] = []
    targets_all: list[np.ndarray] = []
    sleep_poses: list[int] = []
    with h5py.File(h5_path, "r") as h5:
        all_images = np.asarray(h5["images"][:], dtype=np.float32)
        all_masks = np.asarray(h5["masks"][:], dtype=np.int64)
    for start in range(0, len(indices), batch_size):
        batch_indices = indices[start : start + batch_size]
        images = all_images[batch_indices]
        targets = all_masks[batch_indices]
        # 逐帧 min-max 归一化(与训练一致)
        lows = images.min(axis=(1, 2), keepdims=True)
        highs = images.max(axis=(1, 2), keepdims=True)
        images = (images - lows) / np.maximum(highs - lows, 1e-8)
        batch_preds = predict(
            model, torch.from_numpy(images).unsqueeze(1), device, input_size
        ).numpy()
        preds_all.append(batch_preds)
        targets_all.append(targets)
        sleep_poses.extend(entries[i]["sleep_pos"] for i in batch_indices)

    preds = np.concatenate(preds_all)
    targets = np.concatenate(targets_all)
    sleep_poses = np.asarray(sleep_poses)

    total = int(targets.size)
    accuracy = float((preds == targets).sum() / max(total, 1))

    # 每类 precision/recall/F1/IoU + 混淆矩阵
    per_class = {}
    confusions = np.zeros((num_classes, num_classes), dtype=np.int64)
    for cls in range(num_classes):
        tp = int(((preds == cls) & (targets == cls)).sum())
        fp = int(((preds == cls) & (targets != cls)).sum())
        fn = int(((preds != cls) & (targets == cls)).sum())
        precision = tp / (tp + fp) if tp + fp > 0 else 0.0
        recall = tp / (tp + fn) if tp + fn > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
        iou = tp / (tp + fp + fn) if tp + fp + fn > 0 else 0.0
        per_class[str(cls)] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "iou": round(iou, 4),
        }
        for true_cls in range(num_classes):
            confusions[cls, true_cls] = int(((preds == cls) & (targets == true_cls)).sum())

    # 按睡姿分组
    per_pose = {}
    for pose in sorted(set(sleep_poses.tolist())):
        mask = sleep_poses == pose
        pose_total = int(targets[mask].size)
        pose_acc = float((preds[mask] == targets[mask]).sum() / max(pose_total, 1))
        per_pose[SLEEP_POSE_NAMES.get(int(pose), str(pose))] = {
            "accuracy": round(pose_acc, 4),
            "num_frames": int(mask.sum()),
        }

    # mIoU(前景类别平均)
    foreground_ious = [per_class[str(c)]["iou"] for c in range(1, num_classes)]
    miou = float(np.mean(foreground_ious))

    return {
        "num_samples": len(indices),
        "accuracy": round(accuracy, 4),
        "miou": round(miou, 4),
        "per_class": per_class,
        "per_sleep_pose": per_pose,
        "confusion_matrix": confusions.tolist(),
    }


def evaluate(data_dir: Path, model_path: Path, device: str = "auto") -> dict[str, Any]:
    """对样本级与用户级两个口径分别评估,保存 metrics.json。"""
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[segmentation] evaluating model={model_path} on device={device}")

    data_dir = Path(data_dir)
    model_path = Path(model_path)
    with open(data_dir / "manifest.json", encoding="utf-8") as stream:
        manifest = json.load(stream)
    entries = manifest["entries"]
    num_classes = manifest["num_regions"] + 1

    model, checkpoint = load_model(model_path, device)
    input_size = tuple(checkpoint.get("input_size", [96, 48]))

    results: dict[str, Any] = {
        "model": str(model_path),
        "input_size": list(input_size),
        "num_classes": num_classes,
    }
    for split_name, key in (("sample_split", "sample"), ("user_split", "user")):
        indices = manifest[split_name]["test"]
        split_result = evaluate_split(
            model,
            data_dir / "dataset.h5",
            indices,
            entries,
            device,
            input_size,
            num_classes,
        )
        results[key] = split_result
        print(
            f"[segmentation] {key} 口径: 样本数={split_result['num_samples']} "
            f"准确率={split_result['accuracy']:.4f} mIoU={split_result['miou']:.4f}"
        )

    out_path = data_dir / "evaluation_metrics.json"
    with open(out_path, "w", encoding="utf-8") as stream:
        json.dump(results, stream, ensure_ascii=False, indent=2)
    print(f"[segmentation] 评估结果已保存到 {out_path}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a body segmentation model.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed/segmentation"))
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    evaluate(args.data_dir, args.model_path, device=args.device)


if __name__ == "__main__":
    main()
