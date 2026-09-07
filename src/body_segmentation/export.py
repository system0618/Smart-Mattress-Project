"""区域划分结果导出:按 docs/api_docs.md 约定输出 segmentation JSON + 效果图。

输出目录结构:
    data/processed/segmentation/export/
    ├── masks/                  # 每帧一个 segmentation JSON(api_docs 约定格式)
    │   ├── frame_000001.json
    │   └── ...
    ├── previews/               # 热力图+区域叠加效果图
    └── export_manifest.json    # 导出清单(帧号->文件映射)
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

from .evaluate import load_model, predict
from .visualize import render_frame, sample_frames_per_pose

LABELS = {
    "0": "background",
    "1": "shoulder",
    "2": "back",
    "3": "waist",
    "4": "hip",
    "5": "thigh",
}


def export_masks(
    data_dir: Path,
    model_path: Path,
    output_dir: Path | None = None,
    num_per_pose: int = 2,
    seed: int = 42,
    device: str = "auto",
) -> dict[str, Any]:
    """对每种睡姿抽样帧,导出分割 JSON 与效果图。"""
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    data_dir = Path(data_dir)
    model_path = Path(model_path)
    output_dir = output_dir or data_dir / "export"
    masks_dir = output_dir / "masks"
    previews_dir = output_dir / "previews"
    masks_dir.mkdir(parents=True, exist_ok=True)
    previews_dir.mkdir(parents=True, exist_ok=True)

    with open(data_dir / "manifest.json", encoding="utf-8") as stream:
        manifest = json.load(stream)
    entries = manifest["entries"]
    num_classes = manifest["num_regions"] + 1

    model, checkpoint = load_model(model_path, device)
    input_size = tuple(checkpoint.get("input_size", [96, 48]))

    indices = manifest["user_split"]["test"]  # 导出新用户(未参与训练)的划分效果
    picked = sample_frames_per_pose(
        data_dir / "dataset.h5",
        indices,
        entries,
        num_per_pose=num_per_pose,
        rng=np.random.default_rng(seed),
    )

    exported: list[dict[str, Any]] = []
    with h5py.File(data_dir / "dataset.h5", "r") as h5:
        for row in picked:
            meta = entries[row]
            pressure = np.asarray(h5["images"][row], dtype=np.float32)
            true_mask = np.asarray(h5["masks"][row], dtype=np.int64)
            low, high = pressure.min(), pressure.max()
            norm = (pressure - low) / max(high - low, 1e-8)
            image = torch.from_numpy(norm).unsqueeze(0).unsqueeze(0)
            pred_mask = predict(model, image, device, input_size).squeeze(0).numpy()

            frame_id = f"user{meta['people']:02d}_action{meta['action']:02d}_frame{meta['frame']:02d}"
            payload = {
                "frame_id": frame_id,
                "segmentation_shape": [int(true_mask.shape[0]), int(true_mask.shape[1])],
                "segmentation_mask": pred_mask.astype(int).tolist(),
                "labels": LABELS,
                "sleep_pose": meta["sleep_pos"],
            }
            mask_path = masks_dir / f"{frame_id}.json"
            with open(mask_path, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)

            preview_path = previews_dir / f"{frame_id}.png"
            render_frame(
                pressure,
                true_mask,
                pred_mask,
                f"{frame_id} pose={meta['sleep_pos']}",
                preview_path,
            )
            exported.append(
                {
                    "frame_id": frame_id,
                    "mask_json": str(mask_path.relative_to(data_dir)),
                    "preview": str(preview_path.relative_to(data_dir)),
                }
            )

    export_manifest = {
        "model": str(model_path),
        "num_frames": len(exported),
        "labels": LABELS,
        "frames": exported,
    }
    with open(output_dir / "export_manifest.json", "w", encoding="utf-8") as stream:
        json.dump(export_manifest, stream, ensure_ascii=False, indent=2)
    print(f"[segmentation] 已导出 {len(exported)} 帧到 {output_dir}")
    return export_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Export segmentation masks for frontend.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed/segmentation"))
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--num-per-pose", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()
    export_masks(
        data_dir=args.data_dir,
        model_path=args.model_path,
        output_dir=args.output_dir,
        num_per_pose=args.num_per_pose,
        seed=args.seed,
        device=args.device,
    )


if __name__ == "__main__":
    main()
