"""Enhance the raw sleep-posture heatmaps stored in the region JSON export."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import h5py
import numpy as np
import torch
from scipy.ndimage import maximum_filter, median_filter
from torch.utils.data import DataLoader, TensorDataset
from tqdm import tqdm

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path as MatplotlibPath

from .enhance import PolishNetU
from src.data_process.prepare_annotated_pressure_dataset import annotation_mask, enhanced_target_rgb


FOCUSED_LIMBS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2),       # right lower/upper leg
    (3, 4), (4, 5),       # left upper/lower leg
    (2, 3),               # pelvis
    (2, 12), (3, 12),     # hips to thorax
    (8, 12), (9, 12),     # shoulders to thorax
    (8, 9),               # shoulder line
)


def _focused_pose_mask(record: dict, height: int = 24, width: int = 44) -> np.ndarray:
    """Build a tight torso/hip/knee/leg gate from true 14-joint labels."""
    points: dict[int, tuple[float, float]] = {}
    states = record.get("state", [])
    for index, point in enumerate(record.get("kpts", [])[:14]):
        if point is None or len(point) < 2 or (index < len(states) and states[index]):
            continue
        row, column = float(point[0]), float(point[1])
        if 0 <= row < height and 0 <= column < width:
            points[index] = (row, column)

    mask = np.zeros((height, width), dtype=np.float32)
    # Fill the shoulder/hip quadrilateral so torso enhancement is coherent.
    if all(index in points for index in (8, 9, 3, 2)):
        polygon = np.asarray([
            (points[index][1], points[index][0]) for index in (8, 9, 3, 2)
        ], dtype=np.float32)
        yy, xx = np.mgrid[:height, :width]
        inside = MatplotlibPath(polygon).contains_points(np.column_stack((xx.ravel(), yy.ravel())))
        mask[inside.reshape(height, width)] = 1.0

    for start_index, end_index in FOCUSED_LIMBS:
        if start_index not in points or end_index not in points:
            continue
        start, end = points[start_index], points[end_index]
        steps = max(2, int(np.hypot(end[0] - start[0], end[1] - start[1]) * 3))
        rows = np.rint(np.linspace(start[0], end[0], steps)).astype(np.int32).clip(0, height - 1)
        columns = np.rint(np.linspace(start[1], end[1], steps)).astype(np.int32).clip(0, width - 1)
        mask[rows, columns] = 1.0
    for index in (1, 2, 3, 4, 8, 9, 12):
        if index in points:
            row, column = points[index]
            mask[int(round(row)), int(round(column))] = 1.0
    mask = maximum_filter(mask, size=3, mode="nearest")
    from scipy.ndimage import gaussian_filter
    mask = gaussian_filter(mask, sigma=1.1)
    return (mask / max(float(mask.max()), 1e-6)).astype(np.float32)


def _load_frames(
    json_path: str | Path,
    max_samples: int | None,
    keypoint_records: dict[tuple[str, int, int], dict],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict]]:
    records = json.loads(Path(json_path).read_text(encoding="utf-8"))
    if max_samples is not None:
        records = records[:max_samples]
    frames = []
    targets = []
    gates = []
    metadata = []
    cmap = matplotlib.colormaps["viridis"]
    for record in records:
        values = np.fromstring(record["data"], sep=",", dtype=np.float32)
        if values.size != 44 * 24:
            continue
        # Existing page PNGs display 44x24 vertically. PolishNetU was trained
        # on the equivalent 24x44 orientation, so transpose before inference.
        pressure = values.reshape(44, 24).T
        low, high = float(pressure.min()), float(pressure.max())
        normalized = np.clip((pressure - low) / max(high - low, 1e-6), 0.0, 1.0)
        frames.append(cmap(normalized)[..., :3].astype(np.float32))
        clean_pressure = median_filter(pressure, size=3, mode="nearest")
        record_key = (
            str(record.get("people_name", "unknown")),
            int(record.get("action", -1)),
            int(record.get("frame", -1)),
        )
        pose_record = keypoint_records.get(record_key, record)
        body_mask = (
            _focused_pose_mask(pose_record, height=24, width=44)
            if "kpts" in pose_record else annotation_mask(pose_record, height=24, width=44)
        )
        # Remove the very weak Gaussian tail. Pixels outside this gate are
        # copied exactly from the input after inference.
        gate = np.clip((body_mask - 0.08) / 0.92, 0.0, 1.0) ** 0.7
        gates.append(gate.astype(np.float32))
        targets.append(enhanced_target_rgb(
            clean_pressure,
            body_mask,
            low,
            high,
            strength=1.0,
            zero_pressure_floor=0.18,
        ))
        metadata.append({
            "user": str(record.get("people_name", "unknown")),
            "action": int(record.get("action", -1)),
            "frame": int(record.get("frame", -1)),
        })
    if not frames:
        raise ValueError(f"No valid 44x24 pressure frames found in {json_path}")
    return np.stack(frames), np.stack(targets), np.stack(gates), metadata


def _save_groups(
    inputs: np.ndarray,
    outputs: np.ndarray,
    targets: np.ndarray,
    metadata: list[dict],
    output_dir: Path,
    groups: int,
    rows: int,
    min_frame_gap: int,
) -> None:
    difference = np.abs(outputs.astype(np.float32) - inputs.astype(np.float32)).mean(axis=(1, 2, 3))
    ranked = np.argsort(difference)[::-1]
    diverse: list[int] = []
    for index in ranked:
        if all(abs(int(index) - previous) >= min_frame_gap for previous in diverse):
            diverse.append(int(index))
        if len(diverse) >= groups * rows:
            break
    output_dir.mkdir(parents=True, exist_ok=True)
    for group in range(groups):
        indices = diverse[group * rows:(group + 1) * rows]
        if not indices:
            break
        figure, axes = plt.subplots(len(indices), 4, figsize=(12, 3.2 * len(indices)), squeeze=False)
        for row, index in enumerate(indices):
            before = inputs[index].transpose(1, 0, 2)
            after = outputs[index].transpose(1, 0, 2)
            target = targets[index].transpose(1, 0, 2)
            delta = np.abs(after.astype(np.float32) - before.astype(np.float32))
            label = metadata[index]
            axes[row, 0].imshow(before)
            axes[row, 0].set_title(f"Original: {label['user']} A{label['action']} F{label['frame']}")
            axes[row, 1].imshow(after)
            axes[row, 1].set_title("PolishNetU enhanced")
            axes[row, 2].imshow(target)
            axes[row, 2].set_title("Constructed reference target")
            axes[row, 3].imshow(np.clip(delta * 8.0, 0, 255).astype(np.uint8))
            axes[row, 3].set_title("Difference x8")
            for axis in axes[row]:
                axis.axis("off")
        figure.tight_layout()
        destination = output_dir / f"raw_sleep_enhancement_group_{group + 1:02d}.png"
        figure.savefig(destination, dpi=180, bbox_inches="tight")
        plt.close(figure)
        print(f"Comparison saved: {destination}")


def enhance(
    json_path: str | Path,
    checkpoint_path: str | Path,
    output_h5: str | Path,
    comparison_dir: str | Path,
    batch_size: int = 128,
    max_samples: int | None = 1500,
    groups: int = 4,
    inference_strength: float = 1.0,
    min_frame_gap: int = 15,
    keypoints_json: str | Path | None = None,
) -> None:
    keypoint_records: dict[tuple[str, int, int], dict] = {}
    if keypoints_json is not None:
        pose_data = json.loads(Path(keypoints_json).read_text(encoding="utf-8"))
        keypoint_records = {
            (str(item.get("folder", "unknown")), int(item.get("action", -1)), int(item.get("frame", -1))): item
            for item in pose_data
        }
    inputs_float, targets_float, gates, metadata = _load_frames(json_path, max_samples, keypoint_records)
    inputs_uint8 = np.rint(inputs_float * 255.0).clip(0, 255).astype(np.uint8)
    targets_uint8 = np.rint(targets_float * 255.0).clip(0, 255).astype(np.uint8)
    tensor = torch.from_numpy(inputs_float).permute(0, 3, 1, 2) * 2.0 - 1.0
    loader = DataLoader(TensorDataset(tensor), batch_size=batch_size, shuffle=False, num_workers=0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    model = PolishNetU(
        base_channels=int(state.get("base_channels", 8)),
        residual_scale=float(state.get("residual_scale", 0.125)) * inference_strength,
    ).to(device)
    model.load_state_dict(state["model_state_dict"])
    model.eval()

    predictions = []
    with torch.inference_mode():
        for (batch,) in tqdm(loader, desc=f"Enhancing raw sleep heatmaps on {device}", unit="batch"):
            output = model(batch.to(device, non_blocking=True))
            predictions.append(((output + 1.0) * 127.5).clamp(0, 255).byte().permute(0, 2, 3, 1).cpu().numpy())
    raw_outputs = np.concatenate(predictions)
    # Spatially gate the amplified residual. This preserves zero-background
    # pixels while still allowing missing pressure at annotated joints/limbs.
    blended = inputs_uint8.astype(np.float32) + gates[..., None] * (
        raw_outputs.astype(np.float32) - inputs_uint8.astype(np.float32)
    )
    outputs = np.rint(blended).clip(0, 255).astype(np.uint8)

    destination = Path(output_h5)
    destination.parent.mkdir(parents=True, exist_ok=True)
    string_type = h5py.string_dtype(encoding="utf-8")
    with h5py.File(destination, "w") as file:
        file.create_dataset("input_images", data=inputs_uint8, compression="gzip")
        file.create_dataset("enhanced_images", data=outputs, compression="gzip")
        file.create_dataset("target_images", data=targets_uint8, compression="gzip")
        file.create_dataset("enhancement_mask", data=gates, compression="gzip")
        file.create_dataset("user", data=np.asarray([item["user"] for item in metadata], dtype=object), dtype=string_type)
        file.create_dataset("action", data=np.asarray([item["action"] for item in metadata], dtype=np.int16))
        file.create_dataset("frame", data=np.asarray([item["frame"] for item in metadata], dtype=np.int32))
        file.attrs["source_json"] = str(json_path)
        file.attrs["orientation"] = "network arrays 24x44; comparison images displayed 44x24"
        file.attrs["model_checkpoint"] = str(checkpoint_path)
        file.attrs["inference_strength"] = inference_strength
        file.attrs["target_type"] = "constructed: 3x3 median + pose-mask strong enhancement; not measured ground truth"
        file.attrs["spatial_gating"] = "real 14-joint skeleton when keypoints_json match is available"
    print(f"Enhanced HDF5 saved: {destination}")
    _save_groups(
        inputs_uint8, outputs, targets_uint8, metadata, Path(comparison_dir),
        groups=groups, rows=6, min_frame_gap=min_frame_gap,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Enhance raw sleep-posture pressure heatmaps")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output-h5", required=True)
    # 对比图默认按睡姿原始数据类别保存到工作区目录；仍可通过命令行参数覆盖。
    parser.add_argument("--comparison-dir", default="../压力增强对比图/睡姿原始数据_基础")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--max-samples", type=int, default=1500, help="Use 0 for every JSON record")
    parser.add_argument("--groups", type=int, default=4)
    parser.add_argument("--inference-strength", type=float, default=1.0)
    parser.add_argument("--min-frame-gap", type=int, default=15)
    parser.add_argument("--keypoints-json")
    args = parser.parse_args()
    enhance(
        args.input_json,
        args.checkpoint,
        args.output_h5,
        args.comparison_dir,
        args.batch_size,
        None if args.max_samples == 0 else args.max_samples,
        args.groups,
        args.inference_strength,
        args.min_frame_gap,
        args.keypoints_json,
    )


if __name__ == "__main__":
    main()
