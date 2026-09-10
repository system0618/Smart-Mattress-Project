"""Evaluate paired denoising outputs against their clean HDF5 targets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import h5py
import numpy as np


def _metrics(prediction: np.ndarray, target: np.ndarray) -> dict[str, float]:
    difference = prediction.astype(np.float32) - target.astype(np.float32)
    mse = float(np.square(difference).mean())
    return {
        "mae_8bit": float(np.abs(difference).mean()),
        "mse_8bit": mse,
        "rmse_8bit": float(np.sqrt(mse)),
    }


def evaluate_denoising(input_h5: str | Path, enhanced_h5: str | Path, output_json: str | Path) -> dict[str, object]:
    """Compare degraded input and model output with a paired clean target."""
    with h5py.File(input_h5, "r") as source, h5py.File(enhanced_h5, "r") as result:
        for key in ("input_images", "target_images"):
            if key not in source:
                raise KeyError(f"Paired denoising HDF5 has no '{key}' dataset")
        input_images = source["input_images"][:]
        target_images = source["target_images"][:]
        enhanced_images = result["images"][:]
    if input_images.shape != target_images.shape or enhanced_images.shape != target_images.shape:
        raise ValueError("Input, target, and enhanced image shapes must match")
    baseline = _metrics(input_images, target_images)
    output = _metrics(enhanced_images, target_images)
    report = {
        "sample_count": int(len(target_images)),
        "image_shape": list(target_images.shape[1:]),
        "baseline_input_to_target": baseline,
        "enhanced_output_to_target": output,
        "mae_improvement_percent": 100.0 * (1.0 - output["mae_8bit"] / baseline["mae_8bit"]),
        "mse_improvement_percent": 100.0 * (1.0 - output["mse_8bit"] / baseline["mse_8bit"]),
    }
    destination = Path(output_json)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate paired pressure denoising results")
    parser.add_argument("input_h5")
    parser.add_argument("enhanced_h5")
    parser.add_argument("--output", default="reports/slp_denoise_metrics.json")
    args = parser.parse_args()
    evaluate_denoising(args.input_h5, args.enhanced_h5, args.output)


if __name__ == "__main__":
    main()
