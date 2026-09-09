"""将带 region/spine 标注的压力记录转换为 PolishNetU 配对 HDF5 数据集。

标注文件的每条记录包含一个 24x44 压力矩阵。region 由成对的列范围组成，
spine 是人体中线提示。脚本把这些标注解析为软人体掩膜，供增强损失加权。
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import h5py
import numpy as np
from scipy.ndimage import gaussian_filter, median_filter

PAF_LIMBS: tuple[tuple[int, int], ...] = (
    (0, 1),
    (1, 2), (2, 4), (4, 6),
    (1, 3), (3, 5), (5, 7),
    (1, 8), (8, 10), (10, 12),
    (1, 9), (9, 11), (11, 13),
    (8, 9),
)


def parse_pressure(record: dict, height: int = 24, width: int = 44) -> np.ndarray:
    values = np.asarray([float(v) for v in record["data"].split(",")], dtype=np.float32)
    if values.size != height * width:
        raise ValueError(f"pressure length {values.size} != {height}x{width}")
    # The source stream is column-major with respect to the 24x44 sensor mat.
    # A direct reshape(height, width) creates diagonal stripes and destroys the
    # human silhouette; reshape(width, height).T restores sensor coordinates.
    return values.reshape(width, height).T


def parse_numbers(value: str) -> np.ndarray:
    numbers = []
    for item in value.split():
        try:
            numbers.append(float(item))
        except ValueError:
            # The annotation export uses 'na' for unavailable coordinates.
            continue
    return np.asarray(numbers, dtype=np.float32)


def annotation_mask(record: dict, height: int = 24, width: int = 44) -> np.ndarray:
    """将 kpts/state 关节标注转换成平滑的人体区域掩膜。"""
    mask = np.zeros((height, width), dtype=np.float32)
    keypoints = record.get("kpts")
    states = record.get("state", [])
    valid_points: dict[int, tuple[float, float]] = {}
    if isinstance(keypoints, list):
        for index, point in enumerate(keypoints[:14]):
            if point is None or len(point) < 2 or (index < len(states) and states[index]):
                continue
            row, column = float(point[0]), float(point[1])
            if 0 <= row < height and 0 <= column < width:
                valid_points[index] = (row, column)
                mask[int(round(row)), int(round(column))] = 1.0
    if valid_points:
        # Connect only anatomical limbs; list adjacency is not anatomical order.
        for start_index, end_index in PAF_LIMBS:
            if start_index not in valid_points or end_index not in valid_points:
                continue
            start, end = valid_points[start_index], valid_points[end_index]
            steps = max(2, int(np.hypot(end[0] - start[0], end[1] - start[1]) * 2))
            rows = np.rint(np.linspace(start[0], end[0], steps)).astype(np.int32).clip(0, height - 1)
            columns = np.rint(np.linspace(start[1], end[1], steps)).astype(np.int32).clip(0, width - 1)
            mask[rows, columns] = 1.0
        mask = gaussian_filter(mask, sigma=2.0)
        return (mask / max(float(mask.max()), 1e-6)).astype(np.float32)

    # Backward-compatible fallback for older region/spine exports.
    region = parse_numbers(record.get("region", ""))
    pairs = region[: len(region) - len(region) % 2].reshape(-1, 2)
    # Each pair describes one successive body band in the supplied annotation.
    # The band interpretation is explicit and deterministic for this file format.
    for index, (left, right) in enumerate(pairs):
        top = int(round(index * height / max(len(pairs), 1)))
        bottom = int(round((index + 1) * height / max(len(pairs), 1)))
        lo, hi = sorted((int(round(left)), int(round(right))))
        lo, hi = max(0, lo), min(width, hi + 1)
        if hi > lo:
            mask[top:bottom, lo:hi] = 1.0
    spine = parse_numbers(record.get("spine", ""))
    if spine.size:
        for row, column in enumerate(np.linspace(0, height - 1, spine.size).round().astype(int)):
            center = int(round(spine[row]))
            if 0 <= center < width:
                mask[max(0, row - 1):min(height, row + 2), max(0, center - 3):min(width, center + 4)] = 1.0
    if not mask.any():
        # Missing annotation: retain only non-background pressure pixels.
        pressure = parse_pressure(record, height, width)
        threshold = np.percentile(pressure, 70.0)
        mask = (pressure > threshold).astype(np.float32)
    return gaussian_filter(mask, sigma=1.5).clip(0.0, 1.0).astype(np.float32)


def viridis_rgb(pressure: np.ndarray, low: float, high: float) -> np.ndarray:
    import matplotlib

    normalized = np.clip((pressure - low) / max(high - low, 1e-6), 0.0, 1.0)
    return matplotlib.colormaps["viridis"](normalized)[..., :3].astype(np.float32)


def enhanced_target_rgb(
    pressure: np.ndarray,
    mask: np.ndarray,
    low: float,
    high: float,
    strength: float,
    zero_pressure_floor: float,
) -> np.ndarray:
    """Enhance existing weak pressure inside the annotated body region.

    sqrt(p) gives weak readings more gain than already strong pressure.  The
    small floor allows annotated joints/limbs to recover a missing zero-valued
    sensor response, while the body mask prevents global background brightening.
    """
    import matplotlib

    normalized = np.clip((pressure - low) / max(high - low, 1e-6), 0.0, 1.0)
    weak_signal = zero_pressure_floor + (1.0 - zero_pressure_floor) * np.sqrt(normalized)
    gain = strength * mask * weak_signal * (1.0 - normalized)
    enhanced = np.clip(normalized + gain, 0.0, 1.0)
    return matplotlib.colormaps["viridis"](enhanced)[..., :3].astype(np.float32)


def prepare(
    input_json: str | Path,
    output_dir: str | Path,
    train_ratio: float = 0.7,
    seed: int = 42,
    target_enhancement_strength: float = 0.0,
    zero_pressure_floor: float = 0.0,
) -> dict:
    records = json.loads(Path(input_json).read_text(encoding="utf-8"))
    by_user: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        user = record.get("folder") or record.get("people_name") or "unknown"
        by_user[str(user)].append(record)
    users = sorted(by_user)
    np.random.default_rng(seed).shuffle(users)
    cut = max(1, min(len(users) - 1, round(len(users) * train_ratio)))
    split_users = {"train": users[:cut], "test": users[cut:]}
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    # Use one calibration range for every frame. Per-frame min/max scaling can
    # make an almost empty mattress look strongly activated and is inconsistent
    # with the fixed pressure range used by the paper's sensor mat.
    calibration_values = np.concatenate([parse_pressure(record).ravel() for record in records])
    global_low = 0.0
    global_high = float(np.percentile(calibration_values, 99.5))

    def filtered_sequences(selected_records: list[dict]) -> list[tuple[np.ndarray, dict]]:
        """Apply the paper's 3x3x3 filter and remove 3 transition frames."""
        sequences: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for current in selected_records:
            user = str(current.get("folder") or current.get("people_name") or "unknown")
            sequences[(user, str(current.get("action", "unknown")))].append(current)
        result: list[tuple[np.ndarray, dict]] = []
        for sequence_records in sequences.values():
            sequence_records.sort(key=lambda item: int(item.get("frame", 0)))
            if len(sequence_records) <= 3:
                continue
            sequence = np.stack([parse_pressure(item) for item in sequence_records])
            denoised = median_filter(sequence, size=(3, 3, 3), mode="nearest")
            result.extend((denoised[index], sequence_records[index]) for index in range(3, len(sequence_records)))
        return result

    manifest = {
        "source": str(input_json),
        "train_users": split_users["train"],
        "test_users": split_users["test"],
        "preprocessing": "remove first 3 frames per user/action; 3x3x3 spatio-temporal median; Viridis",
        "viridis_range": [global_low, global_high],
    }
    for split, selected_users in split_users.items():
        selected = [record for user in selected_users for record in by_user[user]]
        if not selected:
            raise ValueError(f"empty {split} split")
        filtered = filtered_sequences(selected)
        if not filtered:
            raise ValueError(f"no usable sequences in {split} split after removing transition frames")
        images, targets, masks, joints, valid_joints = [], [], [], [], []
        kept_records: list[dict] = []
        for denoised, record in filtered:
            mask = annotation_mask(record)
            images.append(viridis_rgb(denoised, global_low, global_high))
            targets.append(enhanced_target_rgb(
                denoised, mask, global_low, global_high,
                target_enhancement_strength, zero_pressure_floor,
            ))
            masks.append(mask)
            kept_records.append(record)
            points = np.full((14, 2), np.nan, dtype=np.float32)
            valid = np.zeros(14, dtype=np.float32)
            for index, point in enumerate(record.get("kpts", [])[:14]):
                state = record.get("state", [])
                if point is not None and len(point) >= 2 and (index >= len(state) or not state[index]):
                    points[index] = (float(point[1]), float(point[0]))  # x=column, y=row
                    valid[index] = 1.0
            joints.append(points)
            valid_joints.append(valid)
        destination = output / f"annotated_{split}.h5"
        with h5py.File(destination, "w") as file:
            file.create_dataset("input_images", data=np.asarray(images, dtype=np.float32), compression="gzip")
            file.create_dataset("target_images", data=np.asarray(targets, dtype=np.float32), compression="gzip")
            file.create_dataset("body_mask", data=np.asarray(masks, dtype=np.float32), compression="gzip")
            file.create_dataset("joints", data=np.asarray(joints, dtype=np.float32), compression="gzip")
            file.create_dataset("joint_valid", data=np.asarray(valid_joints, dtype=np.float32), compression="gzip")
            file.create_dataset("user", data=np.asarray([str(r.get("folder") or r.get("people_name") or "unknown").encode() for r in kept_records]))
            file.attrs["image_encoding"] = "Viridis RGB float32 in [0,1]"
            file.attrs["annotation_source"] = "joint positions JSON: kpts/state"
            file.attrs["preprocessing"] = "3x3x3 spatio-temporal median; first 3 frames removed"
            file.attrs["viridis_low"] = global_low
            file.attrs["viridis_high"] = global_high
            file.attrs["target_enhancement_strength"] = target_enhancement_strength
            file.attrs["zero_pressure_floor"] = zero_pressure_floor
        manifest[f"{split}_samples"] = len(kept_records)
        manifest[f"{split}_path"] = str(destination)
    (output / "annotated_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare annotated pressure HDF5 data")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-dir", default="data/processed/annotated")
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-enhancement-strength", type=float, default=0.0)
    parser.add_argument("--zero-pressure-floor", type=float, default=0.0)
    args = parser.parse_args()
    prepare(
        args.input_json, args.output_dir, args.train_ratio, args.seed,
        args.target_enhancement_strength, args.zero_pressure_floor,
    )


if __name__ == "__main__":
    main()
