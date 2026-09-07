"""区域划分效果图渲染:压力热力图 + 真值框/预测区域叠加。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import h5py
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from .dataset import REGION_NAMES

# 区域类别配色(background 透明,1~5 为半透明着色)
REGION_COLORS = {
    0: (0, 0, 0, 0.0),
    1: (1.0, 0.6, 0.6, 0.45),  # 肩-红
    2: (0.6, 1.0, 0.6, 0.45),  # 背-绿
    3: (0.6, 0.6, 1.0, 0.45),  # 腰-蓝
    4: (1.0, 1.0, 0.5, 0.45),  # 臀-黄
    5: (0.7, 0.4, 1.0, 0.45),  # 大腿-紫
}


def plot_heatmap(data: np.ndarray, ax: plt.Axes, title: str = "") -> None:
    """按数据集说明推荐的方式绘制单张压力热力图。"""
    ax.imshow(data, cmap="turbo", interpolation="bilinear",
              extent=[0, data.shape[1], 0, data.shape[0]])
    ax.axes.xaxis.set_visible(False)
    ax.axes.yaxis.set_visible(False)
    ax.grid(True, alpha=0.3, linewidth=0.3)
    ax.set_title(title, fontsize=8)


def overlay_mask(mask: np.ndarray, ax: plt.Axes) -> None:
    """在热力图上叠加半透明区域着色与区域边界线。"""
    overlay = np.zeros((*mask.shape, 4))
    for cls, color in REGION_COLORS.items():
        overlay[mask == cls] = color
    ax.imshow(overlay, interpolation="nearest",
              extent=[0, mask.shape[1], 0, mask.shape[0]])
    # 绘制类别边界(相邻像素类别不同的位置)
    from scipy import ndimage
    for cls in range(1, 6):
        binary = (mask == cls).astype(np.float32)
        edges = binary - ndimage.binary_erosion(binary).astype(np.float32)
        ys, xs = np.nonzero(edges)
        if xs.size:
            ax.scatter(xs + 0.5, ys + 0.5, s=3, color=REGION_COLORS[cls][:3], marker="s", linewidths=0)


def render_frame(
    pressure: np.ndarray,
    true_mask: np.ndarray,
    pred_mask: np.ndarray | None,
    title: str,
    out_path: Path,
) -> None:
    """渲染单帧:左=真值,右=预测(可选)。"""
    cols = 2 if pred_mask is not None else 1
    fig, axes = plt.subplots(1, cols, figsize=(4.2 * cols, 7.6))
    if cols == 1:
        axes = [axes]
    plot_heatmap(pressure, axes[0], f"{title}\n(ground truth)")
    overlay_mask(true_mask, axes[0])
    if pred_mask is not None:
        plot_heatmap(pressure, axes[1], f"{title}\n(prediction)")
        overlay_mask(pred_mask, axes[1])
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def sample_frames_per_pose(
    h5_path: Path,
    indices: Iterable[int],
    entries: list[dict],
    num_per_pose: int = 2,
    rng: np.random.Generator | None = None,
) -> list[int]:
    """从每个睡姿随机挑 num_per_pose 帧,返回行号列表。"""
    rng = rng or np.random.default_rng(42)
    by_pose: dict[int, list[int]] = {}
    for idx in indices:
        by_pose.setdefault(entries[idx]["sleep_pos"], []).append(idx)
    picked: list[int] = []
    for pose in sorted(by_pose):
        pool = by_pose[pose]
        picked.extend(rng.choice(pool, size=min(num_per_pose, len(pool)), replace=False).tolist())
    return picked
