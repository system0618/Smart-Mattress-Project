"""区域划分数据集解析与划分。

将新版区域划分 JSON(114MB,逐条流式解析)转换为 HDF5 数据集:
- images: (N, 44, 24) float32 压力矩阵
- masks:  (N, 44, 24) uint8 像素级区域标注(0=background, 1=肩, 2=背, 3=腰, 4=臀, 5=大腿)
- manifest.json: 每条记录元信息 + 样本级/用户级两种划分

约定:
- region 为 24 个数: 前 12 个 x、后 12 个 y,配对成 6 个矩形框对角点,
  依次为肩/背/腰/臀/大腿/小腿;小腿仅前 3 人标注,弃用(不写入 mask)。
- 每个动作丢弃开头 skip_frames 帧(过渡帧,参考论文 4.2 节)。
- 已标注数据含左右对称翻转,下游增强禁止再翻转。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterator

import numpy as np
from sklearn.model_selection import train_test_split

HEIGHT, WIDTH = 44, 24
NUM_REGIONS = 5  # 肩/背/腰/臀/大腿(小腿弃用)
REGION_NAMES = ["background", "shoulder", "back", "waist", "hip", "thigh"]
DROP_SMALL_LEG = True  # 小腿框(第 6 框)不参与标注


def parse_region(region: str) -> list[tuple[float, float] | None]:
    """解析 region 字段为 6 个矩形框,每框为对角点 ((x1,y1),(x2,y2))。

    region 为 24 个 token: 前 12 个为 x,后 12 个为 y,按顺序两两配对成 12 个点。
    小腿框(第 6 框)在多数人身上为 "na" 占位,返回 None。
    """
    tokens = region.split()
    if len(tokens) != 24:
        raise ValueError(f"region 应包含 24 个数,实际 {len(tokens)}: {region!r}")
    parsed: list[float | None] = []
    for token in tokens:
        try:
            parsed.append(float(token))
        except ValueError:
            if token.strip().lower() in {"na", "nan", "none", ""}:
                parsed.append(None)
            else:
                raise ValueError(f"region 含无法解析的值: {token!r}") from None
    xs, ys = parsed[:12], parsed[12:]
    boxes: list[tuple[float, float] | None] = []
    for i in range(0, 12, 2):
        corner = (xs[i], ys[i], xs[i + 1], ys[i + 1])
        if any(v is None for v in corner):
            boxes.append(None)
        else:
            x1, y1, x2, y2 = corner
            boxes.append(((x1, y1), (x2, y2)))  # type: ignore[arg-type]
    return boxes


def boxes_to_mask(
    boxes: list[tuple[tuple[float, float], tuple[float, float]] | None],
    height: int = HEIGHT,
    width: int = WIDTH,
    num_regions: int = NUM_REGIONS,
) -> np.ndarray:
    """将区域框转换为像素级 mask。

    框内(含边界)像素置为类别 id,相邻框共享边界时后框优先。
    坐标为 None 的框(未标注)跳过;坐标可能略超矩阵范围(如 y=44),统一钳制。
    """
    mask = np.zeros((height, width), dtype=np.uint8)
    for cls, box in enumerate(boxes[:num_regions], start=1):
        if box is None:
            continue
        (x1, y1), (x2, y2) = box
        x_lo = max(0, int(round(min(x1, x2))))
        x_hi = min(width - 1, int(round(max(x1, x2))))
        y_lo = max(0, int(round(min(y1, y2))))
        y_hi = min(height - 1, int(round(max(y1, y2))))
        mask[y_lo : y_hi + 1, x_lo : x_hi + 1] = cls
    return mask


def parse_record(record: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    """解析单条 JSON 记录,返回 (pressure, mask, meta);非法记录返回 None。"""
    region = record.get("region")
    if region is None or str(region).strip().lower() in {"na", "nan", "none", ""}:
        return None
    data = record.get("data")
    if data is None or str(data).strip().lower() in {"na", "nan", ""}:
        return None
    values = np.asarray([float(v) for v in str(data).split(",")], dtype=np.float32)
    if values.size != HEIGHT * WIDTH:
        return None
    pressure = values.reshape(HEIGHT, WIDTH)
    try:
        boxes = parse_region(str(region))
    except (ValueError, TypeError):
        return None
    mask = boxes_to_mask(boxes)
    meta = {
        "people": int(record.get("people", -1)),
        "people_name": str(record.get("people_name", "")),
        "action": int(record.get("action", -1)),
        "frame": int(record.get("frame", -1)),
        "sleep_pos": int(record.get("sleep_pos", -1)),
    }
    return pressure, mask, meta


def iter_records(path: str | Path) -> Iterator[dict[str, Any]]:
    """流式迭代 JSON 数组中的每条记录(不整文件加载,114MB 也可处理)。"""
    decoder = json.JSONDecoder()
    with open(path, encoding="utf-8") as stream:
        stream.seek(1)  # 跳过 '['
        buffer = stream.read(1024 * 1024)
        while True:
            chunk = stream.read(1024 * 1024)
            if chunk:
                buffer += chunk
            buffer = buffer.lstrip(" \t\r\n")
            if not buffer:
                if not chunk:
                    return  # 文件结束,残留的是空白或 ']'
                continue
            try:
                record, end = decoder.raw_decode(buffer)
                buffer = buffer[end:].lstrip(",\r\n ")
                yield record
            except json.JSONDecodeError:
                if not chunk:
                    return  # 文件结束,残留的是空白或 ']'
                continue


def build_dataset(
    json_path: str | Path,
    output_dir: str | Path,
    skip_frames: int = 3,
    seed: int = 42,
) -> dict[str, Any]:
    """解析 JSON 并写入 HDF5 与 manifest,返回统计信息。"""
    json_path = Path(json_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    images: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    skipped = {"no_region": 0, "bad_data": 0, "bad_region": 0, "transition": 0, "empty": 0}
    per_action_frame: dict[int, int] = {}

    for record in iter_records(json_path):
        parsed = parse_record(record)
        if parsed is None:
            if record.get("region") is None:
                skipped["no_region"] += 1
            elif record.get("data") is None:
                skipped["bad_data"] += 1
            else:
                skipped["bad_region"] += 1
            continue
        pressure, mask, meta = parsed
        action = meta["action"]
        # 丢弃每个动作开头的过渡帧
        frame_in_action = per_action_frame.get(action, 0)
        per_action_frame[action] = frame_in_action + 1
        if frame_in_action < skip_frames:
            skipped["transition"] += 1
            continue
        # 丢弃几乎全空的帧(平均压力过低)
        if float(pressure.mean()) < 1.0:
            skipped["empty"] += 1
            continue
        images.append(pressure)
        masks.append(mask)
        entries.append(meta)

    images_array = np.stack(images).astype(np.float32)
    masks_array = np.stack(masks).astype(np.uint8)

    # ---- 划分:样本级 70/30 ----
    indices = np.arange(len(entries))
    sample_train, sample_test = train_test_split(
        indices, test_size=0.3, random_state=seed, shuffle=True
    )
    # ---- 划分:用户级 21/9 ----
    people = np.asarray([e["people"] for e in entries])
    unique_people = np.unique(people)
    rng = np.random.default_rng(seed)
    shuffled_people = rng.permutation(unique_people)
    num_val = max(1, round(len(unique_people) * 0.3))
    val_people = set(shuffled_people[:num_val].tolist())
    train_people = set(shuffled_people[num_val:].tolist())
    user_train = np.asarray([i for i in indices if people[i] in train_people])
    user_test = np.asarray([i for i in indices if people[i] in val_people])

    import h5py

    h5_path = output_dir / "dataset.h5"
    with h5py.File(h5_path, "w") as h5:
        h5.create_dataset("images", data=images_array, compression="gzip", chunks=True)
        h5.create_dataset("masks", data=masks_array, compression="gzip", chunks=True)

    manifest = {
        "height": HEIGHT,
        "width": WIDTH,
        "num_regions": NUM_REGIONS,
        "region_names": REGION_NAMES,
        "skip_frames": skip_frames,
        "seed": seed,
        "num_samples": int(len(entries)),
        "skipped": skipped,
        "entries": entries,
        "sample_split": {
            "train": sample_train.astype(int).tolist(),
            "test": sample_test.astype(int).tolist(),
        },
        "user_split": {
            "train": user_train.astype(int).tolist(),
            "test": user_test.astype(int).tolist(),
            "train_people": sorted(int(p) for p in train_people),
            "test_people": sorted(int(p) for p in val_people),
        },
    }
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)

    stats = {
        "num_samples": len(entries),
        "h5_path": str(h5_path),
        "skipped": skipped,
        "sample_train": len(sample_train),
        "sample_test": len(sample_test),
        "user_train": len(user_train),
        "user_test": len(user_test),
        "train_people": sorted(int(p) for p in train_people),
        "test_people": sorted(int(p) for p in val_people),
    }
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse region dataset JSON into HDF5 + manifest.")
    parser.add_argument(
        "--json",
        type=Path,
        required=True,
        help="区域划分2026(30人).json 路径",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/processed/segmentation"),
        help="输出目录",
    )
    parser.add_argument("--skip-frames", type=int, default=3, help="每个动作丢弃的开头帧数")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    stats = build_dataset(args.json, args.out, skip_frames=args.skip_frames, seed=args.seed)
    print(f"解析完成: {stats['num_samples']} 帧 -> {stats['h5_path']}")
    print(f"跳过: {stats['skipped']}")
    print(f"样本级: train={stats['sample_train']}, test={stats['sample_test']}")
    print(f"用户级: train={stats['user_train']}, test={stats['user_test']}")
    print(f"验证用户: {stats['test_people']}")


if __name__ == "__main__":
    main()
