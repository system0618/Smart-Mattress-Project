"""Run a trained PolishNetU checkpoint over an HDF5 pressure-image dataset."""
from __future__ import annotations

import argparse
from pathlib import Path

import h5py
import numpy as np
import torch
from tqdm import tqdm

from .enhance import PolishNetU


def images_to_tensor(images: np.ndarray) -> torch.Tensor:
    """Convert uint8/float HWC images into the tanh-compatible BCHW tensor."""
    source_is_integer = np.issubdtype(images.dtype, np.integer)
    values = np.asarray(images)
    if values.ndim != 4:
        raise ValueError(f"Expected images shaped (B, H, W, C), got {values.shape}")
    if values.shape[-1] == 1:
        values = np.repeat(values, 3, axis=-1)
    if values.shape[-1] != 3:
        raise ValueError(f"Expected 3 image channels, got {values.shape[-1]}")
    values = values.astype(np.float32, copy=False)
    if source_is_integer or float(np.nanmax(values)) > 1.0:
        values = values / 255.0
    return torch.from_numpy(values.copy()).permute(0, 3, 1, 2) * 2.0 - 1.0


def run_enhancement(
    input_h5: str | Path,
    checkpoint_path: str | Path,
    output_h5: str | Path,
    batch_size: int = 16,
    base_channels: int | None = None,
    device: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write PolishNetU RGB outputs to a separate HDF5 file in uint8 HWC form."""
    source_path = Path(input_h5)
    checkpoint = Path(checkpoint_path)
    destination = Path(output_h5)
    if not source_path.is_file():
        raise FileNotFoundError(f"Input HDF5 does not exist: {source_path}")
    if not checkpoint.is_file():
        raise FileNotFoundError(f"Checkpoint does not exist: {checkpoint}")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"{destination} already exists; pass --overwrite to replace it")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    state = torch.load(checkpoint, map_location="cpu", weights_only=False)
    if state.get("model") == "PaperPolishNetU" or "polish_state_dict" in state:
        raise ValueError(
            "This is a paper-pipeline model. Run "
            "'python -m src.pressure_enhancement.paper_pipeline export' instead."
        )
    if "model_state_dict" not in state:
        raise KeyError(f"{checkpoint} does not contain a PolishNetU state dictionary")
    inferred_channels = int(state.get("base_channels", 8))
    inferred_scale = float(state.get("residual_scale", 0.125))
    inference_device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = PolishNetU(
        base_channels=base_channels if base_channels is not None else inferred_channels,
        residual_scale=inferred_scale,
    ).to(inference_device)
    model.load_state_dict(state["model_state_dict"])
    model.eval()
    destination.parent.mkdir(parents=True, exist_ok=True)

    with h5py.File(source_path, "r") as source:
        input_key = "input_images" if "input_images" in source else "images"
        if input_key not in source:
            raise KeyError(f"HDF5 file has neither 'input_images' nor 'images': {source_path}")
        image_data = source[input_key]
        if image_data.ndim != 4:
            raise ValueError(f"Expected HDF5 images shaped (N, H, W, C), got {image_data.shape}")
        count, height, width, _ = image_data.shape
        with h5py.File(destination, "w") as output:
            enhanced = output.create_dataset(
                "images", shape=(count, height, width, 3), dtype=np.uint8,
                chunks=(min(batch_size, count), height, width, 3), compression="gzip", compression_opts=4,
            )
            output.create_dataset("source_index", data=np.arange(count, dtype=np.int64), compression="gzip")
            output.attrs["source_h5"] = str(source_path)
            output.attrs["source_image_key"] = input_key
            output.attrs["checkpoint"] = str(checkpoint)
            output.attrs["model"] = "PolishNetU"
            output.attrs["image_encoding"] = "Viridis RGB uint8, enhanced by PolishNetU"
            print(f"Enhancement device: {inference_device}")
            with torch.inference_mode():
                for start in tqdm(range(0, count, batch_size), desc=f"Enhancing {source_path.name}", unit="batch"):
                    stop = min(start + batch_size, count)
                    batch = images_to_tensor(np.asarray(image_data[start:stop])).to(inference_device, non_blocking=True)
                    prediction = model(batch)
                    rgb = ((prediction.clamp(-1, 1) + 1.0) * 127.5)
                    enhanced[start:stop] = rgb.round().to(torch.uint8).permute(0, 2, 3, 1).cpu().numpy()
    print(f"Enhanced test data saved to: {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a PolishNetU checkpoint over a pressure HDF5 file")
    parser.add_argument("input_h5")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--base-channels", type=int, default=None,
        help="Override the channel count stored in a legacy checkpoint when needed",
    )
    parser.add_argument("--device", default=None, help="Defaults to CUDA when available")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    run_enhancement(
        args.input_h5, args.checkpoint, args.output, args.batch_size,
        args.base_channels, args.device, args.overwrite,
    )


if __name__ == "__main__":
    main()
