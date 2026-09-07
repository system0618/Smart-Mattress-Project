"""身体部位划分训练数据在线增强。

注意:区域划分数据集已包含左右对称翻转样本,严禁再做左右翻转,
否则会与已有样本重复。这里只做不破坏人体结构语义的扰动类增强。
"""

from __future__ import annotations

import numpy as np


def augment_pair(
    pressure: np.ndarray,
    mask: np.ndarray,
    rng: np.random.Generator,
    noise_sigma: float = 0.05,
    shift_max: int = 2,
    cutout_p: float = 0.3,
    cutout_size: int = 3,
    scale_sigma: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """对 (pressure, mask) 同步做随机增强,返回增强后的 (H, W) 数组。

    增强项:
    - 高斯噪声(归一化后 σ=noise_sigma)
    - 平移 ±shift_max 格(mask 同步平移,边缘补 0/背景)
    - 压力值全局缩放(乘 1±scale_sigma)
    - Cutout:随机方块置 0,模拟传感器局部失效
    """
    pressure = pressure.astype(np.float32).copy()
    mask = mask.copy()

    # 1. 压力值全局缩放 + 高斯噪声
    pressure *= float(rng.normal(1.0, scale_sigma))
    pressure += rng.normal(0.0, noise_sigma, size=pressure.shape).astype(np.float32)
    pressure = np.clip(pressure, 0.0, None)

    # 2. 平移(mask 同步)
    if shift_max > 0:
        dy = int(rng.integers(-shift_max, shift_max + 1))
        dx = int(rng.integers(-shift_max, shift_max + 1))
        if dy != 0 or dx != 0:
            pressure = np.roll(pressure, shift=(dy, dx), axis=(0, 1))
            mask = np.roll(mask, shift=(dy, dx), axis=(0, 1))
            if dy > 0:
                pressure[:dy, :] = 0.0
                mask[:dy, :] = 0
            elif dy < 0:
                pressure[dy:, :] = 0.0
                mask[dy:, :] = 0
            if dx > 0:
                pressure[:, :dx] = 0.0
                mask[:, :dx] = 0
            elif dx < 0:
                pressure[:, dx:] = 0.0
                mask[:, dx:] = 0

    # 3. Cutout:随机方块置 0
    if rng.random() < cutout_p:
        h, w = pressure.shape
        y = int(rng.integers(0, h))
        x = int(rng.integers(0, w))
        y_lo, y_hi = max(0, y - cutout_size), min(h, y + cutout_size + 1)
        x_lo, x_hi = max(0, x - cutout_size), min(w, x + cutout_size + 1)
        pressure[y_lo:y_hi, x_lo:x_hi] = 0.0
        mask[y_lo:y_hi, x_lo:x_hi] = 0

    return pressure, mask
