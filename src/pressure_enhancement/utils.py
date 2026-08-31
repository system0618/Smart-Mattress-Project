"""Utility functions for pressure matrix processing."""

from __future__ import annotations

import numpy as np


def min_max_normalize(matrix: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """Normalize a pressure matrix into the 0-1 range."""
    values = np.asarray(matrix, dtype=float)
    min_value = float(np.min(values))
    max_value = float(np.max(values))
    return (values - min_value) / (max_value - min_value + eps)


def box_blur(matrix: np.ndarray, kernel_size: int = 3) -> np.ndarray:
    """Apply a small mean filter without requiring OpenCV or SciPy."""
    if kernel_size <= 1:
        return np.asarray(matrix, dtype=float)
    if kernel_size % 2 == 0:
        raise ValueError("kernel_size must be odd")

    values = np.asarray(matrix, dtype=float)
    pad = kernel_size // 2
    padded = np.pad(values, pad_width=pad, mode="edge")
    blurred = np.empty_like(values, dtype=float)

    for row in range(values.shape[0]):
        for col in range(values.shape[1]):
            window = padded[row : row + kernel_size, col : col + kernel_size]
            blurred[row, col] = float(np.mean(window))
    return blurred
