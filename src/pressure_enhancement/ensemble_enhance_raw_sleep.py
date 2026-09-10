"""Fuse structural and strong pressure-enhancement models using real joints.

The two models always process the same original Viridis RGB pressure frame.
Their outputs are never cascaded.  A soft mask derived from 14 real joints
limits the positive fused residual to the torso and limb-connection regions.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import h5py
import matplotlib
import numpy as np
import torch
from scipy.spatial import cKDTree
from torch.utils.data import DataLoader, TensorDataset
from tqdm import tqdm

from .enhance import PolishNetU
from .enhance_raw_sleep_heatmaps import _load_frames
from .paper_pipeline import PaperPolishNetU


def _to_uint8(value: torch.Tensor) -> np.ndarray:
    return ((value + 1.0) * 127.5).clamp(0, 255).byte().permute(0, 2, 3, 1).cpu().numpy()


def _viridis_lut() -> np.ndarray:
    """Return the 256 exact RGB values used by the project's Viridis mapping."""
    return matplotlib.colormaps["viridis"](np.linspace(0.0, 1.0, 256, dtype=np.float32))[..., :3].astype(np.float32)


def _rgb_to_pressure(images: np.ndarray, lookup: cKDTree) -> np.ndarray:
    """Project RGB model outputs to their nearest Viridis pressure level."""
    shape = images.shape[:-1]
    _, indices = lookup.query(images.astype(np.float32).reshape(-1, 3) / 255.0, workers=-1)
    return (indices.reshape(shape).astype(np.float32) / 255.0)


def _pressure_to_rgb(pressure: np.ndarray, lut: np.ndarray) -> np.ndarray:
    indices = np.rint(np.clip(pressure, 0.0, 1.0) * 255.0).astype(np.uint8)
    return np.rint(lut[indices] * 255.0).astype(np.uint8)


def _load_v1(path: str | Path, device: torch.device) -> PaperPolishNetU:
    state = torch.load(path, map_location="cpu", weights_only=False)
    if "polish_state_dict" not in state:
        raise KeyError(f"{path} is not a PaperPolishNetU checkpoint")
    model = PaperPolishNetU(base_channels=int(state.get("base_channels", 24))).to(device)
    model.load_state_dict(state["polish_state_dict"])
    return model.eval()


def _load_strong(path: str | Path, device: torch.device, strength: float) -> PolishNetU:
    state = torch.load(path, map_location="cpu", weights_only=False)
    if "model_state_dict" not in state:
        raise KeyError(f"{path} is not a PolishNetU checkpoint")
    model = PolishNetU(
        base_channels=int(state.get("base_channels", 8)),
        residual_scale=float(state.get("residual_scale", 0.125)) * strength,
    ).to(device)
    model.load_state_dict(state["model_state_dict"])
    return model.eval()


def _save_comparison(
    inputs: np.ndarray,
    v1_outputs: np.ndarray,
    strong_outputs: np.ndarray,
    fused_outputs: np.ndarray,
    gates: np.ndarray,
    metadata: list[dict],
    output_path: str | Path,
    count: int,
) -> None:
    """Save a compact, diverse comparison page selected by gated change."""
    import matplotlib.pyplot as plt

    score = (np.abs(fused_outputs.astype(np.float32) - inputs.astype(np.float32)).mean(axis=-1) * gates).mean(axis=(1, 2))
    ranked = np.argsort(score)[::-1]
    selected: list[int] = []
    for index in ranked:
        if all(abs(int(index) - previous) >= 15 for previous in selected):
            selected.append(int(index))
        if len(selected) == count:
            break
    if not selected:
        return

    figure, axes = plt.subplots(len(selected), 5, figsize=(15, 3.1 * len(selected)), squeeze=False)
    headings = ("Original", "v1 structural", "Strong model", "Joint-gated fusion", "Soft joint gate")
    for row, index in enumerate(selected):
        # Network tensors are 24x44; transpose only for the upright display.
        views = (
            inputs[index].transpose(1, 0, 2),
            v1_outputs[index].transpose(1, 0, 2),
            strong_outputs[index].transpose(1, 0, 2),
            fused_outputs[index].transpose(1, 0, 2),
            gates[index].T,
        )
        label = metadata[index]
        for column, (axis, view, heading) in enumerate(zip(axes[row], views, headings)):
            if column == 4:
                axis.imshow(view, cmap="magma", vmin=0.0, vmax=1.0)
            else:
                axis.imshow(view)
            axis.set_title(
                f"{heading}\n{label['user']} A{label['action']} F{label['frame']}" if column == 0 else heading
            )
            axis.axis("off")
    figure.tight_layout()
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(figure)
    print(f"Comparison saved: {destination}")


def enhance_ensemble(
    input_json: str | Path,
    keypoints_json: str | Path,
    v1_checkpoint: str | Path,
    strong_checkpoint: str | Path,
    output_h5: str | Path,
    comparison_output: str | Path,
    batch_size: int = 128,
    max_samples: int | None = 1500,
    v1_weight: float = 0.15,
    strong_weight: float = 0.85,
    strong_inference_strength: float = 2.0,
    max_gain: float = 0.75,
    gate_threshold: float = 0.20,
    v1_only: bool = False,
    comparison_count: int = 6,
) -> None:
    """Run both models on raw sleep frames and write their masked fusion."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if v1_only:
        v1_weight, strong_weight = 1.0, 0.0
    if v1_weight < 0 or strong_weight < 0 or v1_weight + strong_weight <= 0:
        raise ValueError("v1_weight and strong_weight must be non-negative with a positive sum")
    if not 0.0 < max_gain <= 1.0:
        raise ValueError("max_gain must be in (0, 1]")
    if not 0.0 <= gate_threshold < 1.0:
        raise ValueError("gate_threshold must be in [0, 1)")

    import json
    keypoint_records = {
        (str(item.get("folder", "unknown")), int(item.get("action", -1)), int(item.get("frame", -1))): item
        for item in json.loads(Path(keypoints_json).read_text(encoding="utf-8"))
    }
    inputs, _, gates, metadata = _load_frames(input_json, max_samples, keypoint_records)
    # The Gaussian edge makes the joint mask soft. Drop its low-confidence tail
    # so the structural model cannot brighten pixels outside the body region.
    gates = np.clip((gates - gate_threshold) / max(1.0 - gate_threshold, 1e-6), 0.0, 1.0)
    weights = np.asarray((v1_weight, strong_weight), dtype=np.float32)
    weights /= weights.sum()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Ensemble inference device: {device}; frames: {len(inputs)}")
    v1 = _load_v1(v1_checkpoint, device)
    strong = (
        _load_strong(strong_checkpoint, device, strong_inference_strength)
        if strong_weight > 0.0
        else None
    )
    loader = DataLoader(
        TensorDataset(torch.from_numpy(inputs).permute(0, 3, 1, 2) * 2.0 - 1.0),
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
        pin_memory=device.type == "cuda",
    )

    v1_batches: list[np.ndarray] = []
    strong_batches: list[np.ndarray] = []
    with torch.inference_mode():
        for (batch,) in tqdm(loader, desc="Joint-gated ensemble enhancement", unit="batch"):
            batch = batch.to(device, non_blocking=True)
            v1_batches.append(_to_uint8(v1(batch)))
            # In v1-only mode, retain the original frame for the diagnostic
            # strong-model column without allocating or loading that model.
            strong_batches.append(_to_uint8(strong(batch)) if strong is not None else _to_uint8(batch))
    original = np.rint(inputs * 255.0).clip(0, 255).astype(np.uint8)
    v1_images = np.concatenate(v1_batches)
    strong_images = np.concatenate(strong_batches)

    # Viridis is not channel-wise monotonic: higher pressure can reduce the
    # blue channel. Fuse in normalized pressure space, then color-map once.
    # This preserves a real increase that would be lost by RGB-only clipping.
    lut = _viridis_lut()
    viridis_lookup = cKDTree(lut)
    input_pressure = _rgb_to_pressure(original, viridis_lookup)
    v1_pressure = _rgb_to_pressure(v1_images, viridis_lookup)
    strong_pressure = _rgb_to_pressure(strong_images, viridis_lookup)
    residual = weights[0] * (v1_pressure - input_pressure) + weights[1] * (strong_pressure - input_pressure)
    # v1-only mode applies the model's complete body-region smoothing, while
    # fusion mode remains gain-only to prevent the strong model from erasing
    # measured pressure.
    residual = np.clip(residual, -max_gain if v1_only else 0.0, max_gain)
    fused_pressure = np.clip(input_pressure + gates * residual, 0.0, 1.0)
    fused_images = _pressure_to_rgb(fused_pressure, lut)

    destination = Path(output_h5)
    destination.parent.mkdir(parents=True, exist_ok=True)
    string_type = h5py.string_dtype(encoding="utf-8")
    with h5py.File(destination, "w") as file:
        file.create_dataset("input_images", data=original, compression="gzip")
        file.create_dataset("v1_images", data=v1_images, compression="gzip")
        file.create_dataset("strong_images", data=strong_images, compression="gzip")
        file.create_dataset("enhanced_images", data=fused_images, compression="gzip")
        file.create_dataset("input_pressure_normalized", data=input_pressure, compression="gzip")
        file.create_dataset("v1_pressure_normalized", data=v1_pressure, compression="gzip")
        file.create_dataset("strong_pressure_normalized", data=strong_pressure, compression="gzip")
        file.create_dataset("enhanced_pressure_normalized", data=fused_pressure, compression="gzip")
        file.create_dataset("enhancement_mask", data=gates, compression="gzip")
        file.create_dataset("user", data=np.asarray([item["user"] for item in metadata], dtype=object), dtype=string_type)
        file.create_dataset("action", data=np.asarray([item["action"] for item in metadata], dtype=np.int16))
        file.create_dataset("frame", data=np.asarray([item["frame"] for item in metadata], dtype=np.int32))
        file.attrs["v1_checkpoint"] = str(v1_checkpoint)
        file.attrs["strong_checkpoint"] = str(strong_checkpoint)
        file.attrs["v1_weight"] = float(weights[0])
        file.attrs["strong_weight"] = float(weights[1])
        file.attrs["strong_inference_strength"] = strong_inference_strength
        file.attrs["max_positive_gain"] = max_gain
        file.attrs["gate_threshold"] = gate_threshold
        file.attrs["v1_only"] = v1_only
        file.attrs["fusion"] = "Viridis-inverted pressure-space real-joint soft gate * bounded positive weighted residual"
    print(f"Ensemble-enhanced HDF5 saved: {destination}")
    _save_comparison(
        original, v1_images, strong_images, fused_images, gates, metadata,
        comparison_output, comparison_count,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse v1 and strong pressure-enhancement models with real joints")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--keypoints-json", required=True)
    parser.add_argument("--v1-checkpoint", default="models/pressure_enhancement_v1.pt")
    parser.add_argument("--strong-checkpoint", default="models/annotated_pressure_strong_v0.pt")
    parser.add_argument("--output-h5", required=True)
    parser.add_argument("--comparison-output", required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--max-samples", type=int, default=1500, help="Use 0 to process every input record")
    parser.add_argument("--v1-weight", type=float, default=0.15)
    parser.add_argument("--strong-weight", type=float, default=0.85)
    parser.add_argument("--strong-inference-strength", type=float, default=2.0)
    parser.add_argument("--max-gain", type=float, default=0.75)
    parser.add_argument("--gate-threshold", type=float, default=0.20)
    parser.add_argument(
        "--v1-only", action="store_true",
        help="Use only v1 inside the joint mask and preserve the raw background",
    )
    parser.add_argument("--comparison-count", type=int, default=6)
    args = parser.parse_args()
    enhance_ensemble(
        args.input_json, args.keypoints_json, args.v1_checkpoint, args.strong_checkpoint,
        args.output_h5, args.comparison_output, args.batch_size,
        None if args.max_samples == 0 else args.max_samples,
        args.v1_weight, args.strong_weight, args.strong_inference_strength,
        args.max_gain, args.gate_threshold, args.v1_only, args.comparison_count,
    )


if __name__ == "__main__":
    main()
