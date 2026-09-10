"""Hand-crafted pressure features used by the traditional baseline."""
from __future__ import annotations
import numpy as np

def extract_features(images: np.ndarray) -> np.ndarray:
    """Extract scale-normalized spatial and pressure-distribution features."""
    values = np.nan_to_num(np.asarray(images, dtype=np.float32), nan=0.0)
    if values.ndim == 2: values = values[None, ...]
    if values.ndim != 3: raise ValueError(f"Expected (N,H,W) pressure images, got {values.shape}")
    height, width = values.shape[1:]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    output = []
    for image in values:
        positive = np.maximum(image, 0.0); total = float(positive.sum()); scale = max(float(positive.max()), 1e-6)
        weights = positive / max(total, 1e-6); row_profile = positive.sum(axis=1) / max(total, 1e-6); col_profile = positive.sum(axis=0) / max(total, 1e-6)
        active = positive > max(0.05 * scale, 1e-6); coords = np.argwhere(active)
        y0, x0, y1, x1 = (coords.min(axis=0).tolist() + coords.max(axis=0).tolist()) if len(coords) else (0, 0, 0, 0)
        center_y = float((weights * yy).sum() / max(height - 1, 1)); center_x = float((weights * xx).sum() / max(width - 1, 1))
        var_y = float((weights * (yy / max(height - 1, 1) - center_y) ** 2).sum()); var_x = float((weights * (xx / max(width - 1, 1) - center_x) ** 2).sum())
        left = float(positive[:, :width // 2].sum()); right = float(positive[:, width // 2:].sum())
        summary = np.asarray([positive.mean() / scale, positive.std() / scale, np.quantile(positive, .75) / scale, np.quantile(positive, .95) / scale, total / (height * width * scale), center_y, center_x, var_y, var_x, (y1-y0+1)/height, (x1-x0+1)/width, left/max(total,1e-6), right/max(total,1e-6), (left-right)/max(total,1e-6)], dtype=np.float32)
        output.append(np.concatenate([summary, row_profile.astype(np.float32), col_profile.astype(np.float32)]))
    return np.stack(output)
