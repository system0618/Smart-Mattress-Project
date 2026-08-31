"""Baseline weak-pressure enhancement algorithm."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from .utils import box_blur, min_max_normalize


def enhance_weak_pressure(
    pressure_matrix: np.ndarray,
    weak_threshold: float = 0.25,
    gain: float = 1.8,
    smooth_kernel: int = 3,
) -> np.ndarray:
    """Enhance low but non-zero pressure areas while preserving strong contacts."""
    normalized = min_max_normalize(pressure_matrix)
    contact_mask = normalized > 0
    weak_mask = (normalized <= weak_threshold) & contact_mask

    enhanced = normalized.copy()
    enhanced[weak_mask] = np.clip(enhanced[weak_mask] * gain + weak_threshold * 0.15, 0, 1)

    if smooth_kernel > 1:
        enhanced = box_blur(enhanced, kernel_size=smooth_kernel)
    return np.clip(enhanced, 0, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enhance weak pressure regions in a .npy matrix.")
    parser.add_argument("--input", type=Path, required=True, help="Input .npy pressure matrix.")
    parser.add_argument("--output", type=Path, required=True, help="Output .npy enhanced matrix.")
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--gain", type=float, default=1.8)
    parser.add_argument("--smooth-kernel", type=int, default=3)
    args = parser.parse_args()

    matrix = np.load(args.input)
    enhanced = enhance_weak_pressure(matrix, args.threshold, args.gain, args.smooth_kernel)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.output, enhanced)
    print(f"Saved enhanced pressure matrix to {args.output}")


if __name__ == "__main__":
    main()
