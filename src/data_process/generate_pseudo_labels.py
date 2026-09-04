"""Generate pressure-image pose pseudo labels with YOLOv8-Pose.

For a prototype run, ``--max-samples`` writes independent HDF5 files so that
partial pseudo labels never overwrite the complete processed data files.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import h5py
import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm


# COCO-17 -> PolishNetU-14: head, neck, left/right shoulder through ankle.
COCO_TO_14 = (0, None, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)
PAF_LIMBS = (
    (0, 1), (1, 2), (1, 3), (2, 4), (4, 6), (3, 5), (5, 7),
    (1, 8), (1, 9), (8, 10), (10, 12), (9, 11), (11, 13), (2, 8),
)


def normalize_hwc(raw_image: np.ndarray) -> np.ndarray:
    """Convert legacy HDF5 image shapes to an uint8 HWC RGB image."""
    image = np.squeeze(np.asarray(raw_image, dtype=np.float32))
    if image.ndim == 2:
        image = np.repeat(image[..., None], 3, axis=-1)
    if image.ndim != 3:
        raise ValueError(f"Expected 2-D or HWC image, got shape {image.shape}")
    if image.shape[-1] == 1:
        image = np.repeat(image, 3, axis=-1)
    if image.shape[-1] != 3:
        raise ValueError(f"Expected RGB image, got shape {image.shape}")
    return np.rint(np.clip(image, 0.0, 1.0) * 255.0).astype(np.uint8)


class H5ImageDataset(Dataset):
    """HDF5 image reader with lazy file opening for Windows compatibility."""

    def __init__(self, path: Path, max_samples: int | None = None) -> None:
        self.path = str(path)
        self._file: h5py.File | None = None
        with h5py.File(self.path, "r") as stream:
            total = len(stream["images"])
        self.length = min(total, max_samples) if max_samples is not None else total

    def __len__(self) -> int:
        return self.length

    def __getitem__(self, index: int) -> tuple[np.ndarray, int]:
        if self._file is None:
            self._file = h5py.File(self.path, "r")
        return normalize_hwc(self._file["images"][index]), index

    def __del__(self) -> None:
        if self._file is not None:
            self._file.close()


def collate_images(batch: list[tuple[np.ndarray, int]]) -> tuple[list[np.ndarray], list[int]]:
    images, indices = zip(*batch)
    return list(images), list(indices)


def load_yolo_pose(model_name: str):
    """Load the lightweight one-stage YOLO pose estimator."""
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise ImportError(
            "Missing dependency 'ultralytics'. Install it with: pip install ultralytics"
        ) from exc
    return YOLO(model_name)


def coco_to_fourteen(keypoints_xy: np.ndarray, keypoint_confidence: np.ndarray, threshold: float) -> np.ndarray:
    """Map YOLO COCO-17 keypoints into the 14-joint PolishNetU convention."""
    joints = np.full((14, 3), np.nan, dtype=np.float32)
    for output_index, coco_index in enumerate(COCO_TO_14):
        if coco_index is not None and keypoint_confidence[coco_index] >= threshold:
            joints[output_index, :2] = keypoints_xy[coco_index]
            joints[output_index, 2] = keypoint_confidence[coco_index]

    left_shoulder, right_shoulder = joints[2], joints[3]
    if np.isfinite(left_shoulder).all() and np.isfinite(right_shoulder).all():
        joints[1] = (left_shoulder + right_shoulder) / 2.0
    return joints


def gaussian_heatmaps(joints: np.ndarray, height: int, width: int, sigma: float) -> np.ndarray:
    """Generate 14 joint Gaussian heatmaps in original pressure-image space."""
    y_grid, x_grid = np.mgrid[0:height, 0:width]
    heatmaps = np.zeros((14, height, width), dtype=np.float32)
    for index, (x, y, confidence) in enumerate(joints):
        if not np.isfinite((x, y, confidence)).all():
            continue
        heatmaps[index] = np.exp(-((x_grid - x) ** 2 + (y_grid - y) ** 2) / (2.0 * sigma**2))
    return heatmaps


def paf_fields(joints: np.ndarray, height: int, width: int, thickness: float) -> np.ndarray:
    """Generate 28 PAF channels: horizontal and vertical vectors for 14 limbs."""
    pafs = np.zeros((len(PAF_LIMBS) * 2, height, width), dtype=np.float32)
    y_grid, x_grid = np.mgrid[0:height, 0:width]
    for limb_index, (start_index, end_index) in enumerate(PAF_LIMBS):
        start, end = joints[start_index], joints[end_index]
        if not np.isfinite(start).all() or not np.isfinite(end).all():
            continue
        vector = end[:2] - start[:2]
        length = float(np.linalg.norm(vector))
        if length < 1e-6:
            continue
        unit = vector / length
        relative_x, relative_y = x_grid - start[0], y_grid - start[1]
        projection = relative_x * unit[0] + relative_y * unit[1]
        distance = np.abs(relative_x * unit[1] - relative_y * unit[0])
        mask = (projection >= 0.0) & (projection <= length) & (distance <= thickness)
        pafs[2 * limb_index][mask] = unit[0]
        pafs[2 * limb_index + 1][mask] = unit[1]
    return pafs


def result_to_joints(result, keypoint_threshold: float, detection_threshold: float) -> np.ndarray:
    """Extract the highest-confidence YOLO person detection as 14 joints."""
    joints = np.full((14, 3), np.nan, dtype=np.float32)
    if result.boxes is None or len(result.boxes) == 0 or result.keypoints is None:
        return joints
    detection_score = float(result.boxes.conf[0].detach().cpu())
    if detection_score < detection_threshold:
        return joints
    xy = result.keypoints.xy[0].detach().cpu().numpy()
    confidence = result.keypoints.conf[0].detach().cpu().numpy()
    return coco_to_fourteen(xy, confidence, keypoint_threshold)


def prototype_path(source: Path, max_samples: int | None) -> Path:
    """Choose a separate output file for partial prototype generation."""
    if max_samples is None:
        return source
    return source.with_name(f"{source.stem}_prototype_{max_samples}{source.suffix}")


def create_output_file(source_path: Path, output_path: Path, sample_count: int) -> h5py.File:
    """Open full source in-place or create an isolated prototype HDF5 copy."""
    if output_path == source_path:
        with h5py.File(source_path, "r") as source:
            source_count = len(source["images"])
        if sample_count != source_count:
            raise ValueError("Partial labeling must use a separate prototype HDF5 output file")
        return h5py.File(source_path, "r+")

    with h5py.File(source_path, "r") as source, h5py.File(output_path, "w") as target:
        images = source["images"]
        output_images = target.create_dataset(
            "images", shape=(sample_count,) + images.shape[1:], dtype=images.dtype,
            chunks=True, compression="gzip",
        )
        copy_batch = 4096
        for start in range(0, sample_count, copy_batch):
            end = min(start + copy_batch, sample_count)
            output_images[start:end] = images[start:end]
        for key, value in source.attrs.items():
            target.attrs[key] = value
    return h5py.File(output_path, "r+")


def generate_labels(
    source_path: Path,
    output_path: Path,
    model,
    device: str,
    batch_size: int,
    model_size: int,
    keypoint_threshold: float,
    detection_threshold: float,
    sigma: float,
    paf_thickness: float,
    max_samples: int | None,
) -> None:
    """Run batched YOLO inference and store aligned heatmap and PAF datasets."""
    dataset = H5ImageDataset(source_path, max_samples)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0, collate_fn=collate_images)
    with create_output_file(source_path, output_path, len(dataset)) as stream:
        first_image = normalize_hwc(stream["images"][0])
        height, width = first_image.shape[:2]
        for name in ("heatmap", "paf"):
            if name in stream:
                del stream[name]
        heatmap_store = stream.create_dataset("heatmap", shape=(len(dataset), 14, height, width), dtype="float32", chunks=True, compression="gzip")
        paf_store = stream.create_dataset("paf", shape=(len(dataset), 28, height, width), dtype="float32", chunks=True, compression="gzip")

        valid_samples = 0
        progress = tqdm(loader, desc=f"YOLO pose labels: {output_path.name}", unit="batch")
        for images, indices in progress:
            results = model.predict(
                source=images,
                imgsz=model_size,
                conf=detection_threshold,
                max_det=1,
                device=device,
                quantize=16 if device != "cpu" else 32,
                rect=False,
                verbose=False,
            )
            heatmaps, pafs = [], []
            for result, image in zip(results, images):
                image_height, image_width = image.shape[:2]
                joints = result_to_joints(result, keypoint_threshold, detection_threshold)
                valid_samples += int(np.isfinite(joints).any())
                heatmaps.append(gaussian_heatmaps(joints, image_height, image_width, sigma))
                pafs.append(paf_fields(joints, image_height, image_width, paf_thickness))
            start, end = indices[0], indices[-1] + 1
            heatmap_store[start:end] = np.stack(heatmaps)
            paf_store[start:end] = np.stack(pafs)
            progress.set_postfix(valid=f"{valid_samples}/{end}")

        stream.attrs["pseudo_label_model"] = "YOLOv8-Pose COCO pseudo labels"
        stream.attrs["pseudo_label_note"] = "All-zero labels mean no confident person/keypoint detection."
        stream.attrs["pseudo_label_source"] = str(source_path)
        stream.attrs["pseudo_label_valid_samples"] = valid_samples
        stream.attrs["pseudo_label_total_samples"] = len(dataset)
        print(f"Valid pose pseudo labels: {valid_samples}/{len(dataset)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate pose pseudo labels with YOLOv8-Pose")
    parser.add_argument("--train-h5", type=Path, default=Path("data/processed/train_data.h5"))
    parser.add_argument("--test-h5", type=Path, default=Path("data/processed/test_data.h5"))
    parser.add_argument("--train-output", type=Path, default=None)
    parser.add_argument("--test-output", type=Path, default=None)
    parser.add_argument("--pose-model", default="yolov8n-pose.pt")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--model-size", type=int, default=64)
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--keypoint-threshold", type=float, default=0.2)
    parser.add_argument("--detection-threshold", type=float, default=0.25)
    parser.add_argument("--sigma", type=float, default=1.5)
    parser.add_argument("--paf-thickness", type=float, default=1.0)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for practical YOLO pseudo-label generation")
    device = 0
    print("YOLO pseudo-label device: cuda:0")
    model = load_yolo_pose(args.pose_model)

    for source, configured_output in ((args.train_h5, args.train_output), (args.test_h5, args.test_output)):
        if not source.is_file():
            raise FileNotFoundError(f"Input HDF5 file not found: {source}")
        output = configured_output or prototype_path(source, args.max_samples)
        output.parent.mkdir(parents=True, exist_ok=True)
        generate_labels(
            source, output, model, device, args.batch_size, args.model_size,
            args.keypoint_threshold, args.detection_threshold, args.sigma,
            args.paf_thickness, args.max_samples,
        )
        print(f"Saved pseudo labels to: {output}")


if __name__ == "__main__":
    main()
