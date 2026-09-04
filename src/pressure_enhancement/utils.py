"""Utility functions for pressure matrix processing."""

from __future__ import annotations

import os
from typing import Dict, List, Union

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


def _read_pressure_file(file_path: str) -> List[np.ndarray]:
    """Read numeric arrays from one supported file.

    A two-dimensional file is treated as one pressure frame.  For a
    three-dimensional array, the first dimension is treated as samples.
    """
    extension = os.path.splitext(file_path)[1].lower()

    if extension == ".npy":
        return [np.asarray(np.load(file_path, allow_pickle=False))]
    if extension == ".npz":
        archive = np.load(file_path, allow_pickle=False)
        return [np.asarray(archive[name]) for name in archive.files]
    if extension in {".csv", ".txt", ".dat"}:
        try:
            import pandas as pd

            values = pd.read_csv(file_path, header=None).apply(
                pd.to_numeric, errors="coerce"
            ).to_numpy(dtype=float)
        except (ImportError, ValueError):
            values = np.loadtxt(file_path, delimiter=",", ndmin=2)
        return [values]
    if extension == ".mat":
        try:
            from scipy.io import loadmat
        except ImportError as exc:
            raise ImportError("读取 .mat 文件需要安装 scipy") from exc
        arrays = [
            np.asarray(value)
            for name, value in loadmat(file_path).items()
            if not name.startswith("__") and isinstance(value, np.ndarray)
            and np.issubdtype(value.dtype, np.number)
        ]
        return [max(arrays, key=lambda value: value.size)] if arrays else []
    return []


def load_and_inspect_data(path: str) -> Union[np.ndarray, Dict[str, List[np.ndarray]]]:
    """Recursively load pressure samples and print basic dataset statistics.

    Supported extensions are ``.npy``, ``.npz``, ``.csv``, ``.txt``, ``.dat``
    and ``.mat``.  Each 2-D file is interpreted as one ``(height, width)``
    frame; for 3-D arrays the first axis is interpreted as the sample axis.
    If every sample has the same shape, a stacked NumPy array is returned.
    Otherwise a dictionary keyed by shape is returned.

    Example::

        data = load_and_inspect_data("data/raw")
    """
    if not os.path.isdir(path):
        raise FileNotFoundError(f"数据目录不存在: {path}")

    samples: List[np.ndarray] = []
    supported = {".npy", ".npz", ".csv", ".txt", ".dat", ".mat"}
    for root, _, filenames in os.walk(path):
        for filename in sorted(filenames):
            if os.path.splitext(filename)[1].lower() not in supported:
                continue
            file_path = os.path.join(root, filename)
            for array in _read_pressure_file(file_path):
                array = np.asarray(array, dtype=float)
                if array.ndim == 0:
                    array = array.reshape(1)
                if array.ndim <= 2:
                    samples.append(array)
                else:
                    samples.extend(array.reshape((-1,) + array.shape[-2:]))

    if not samples:
        raise ValueError(f"在 {path} 中没有找到可读取的数值样本")

    grouped: Dict[str, List[np.ndarray]] = {}
    for sample in samples:
        grouped.setdefault(str(tuple(sample.shape)), []).append(sample)

    finite_values = [sample[np.isfinite(sample)] for sample in samples]
    finite_values = [values for values in finite_values if values.size]
    if finite_values:
        all_values = np.concatenate(finite_values)
        print(f"样本数: {len(samples)}")
        if len(grouped) == 1:
            print(f"总体形状: {tuple(np.stack(samples, axis=0).shape)}")
        else:
            print(f"总体形状: {len(samples)} 个样本（形状不一致）")
        print(f"最大压力值: {np.max(all_values):g}")
        print(f"最小压力值: {np.min(all_values):g}")
    else:
        print(f"样本数: {len(samples)}；数据不包含有限数值")

    if len(grouped) == 1:
        return np.stack(samples, axis=0)
    print("检测到不一致的样本形状:", {shape: len(values) for shape, values in grouped.items()})
    return grouped
