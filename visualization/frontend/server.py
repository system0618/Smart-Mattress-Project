# -*- coding: utf-8 -*-
"""智能床垫可视化一体化服务（前端静态资源 + 身体划分 / 睡姿识别实时接口）。

用途：
    - 在 http://127.0.0.1:8000 提供 visualization/frontend 页面；
    - 按 docs/api_docs.md 约定提供 POST /api/segment：
      前端把每帧 44×24 压力矩阵发来，服务加载 src/body_segmentation 的 UNet
      (best.pt) 推理并返回 segmentation_mask JSON，前端再叠加到热力图。
    - 按 docs/api_docs.md 约定提供 POST /api/posture：
      同样的 44×24 压力矩阵，服务加载 src/posture_recognition 的睡眠姿态模型
      (cnn.pt / svm.joblib / random_forest.joblib) 推理并返回睡姿与置信度。
    - 按 docs/api_docs.md 约定提供 POST /api/enhance：
      同样的 44×24 压力矩阵，服务加载 Release 发布权重
      (默认 models/annotated_pressure_strong_v0.pt，可换成
      models/pressure_enhancement_v1.pt 等) 做弱力增强，两种发布格式自动识别，
      把输出图反查回压力刻度后返回 enhanced_matrix。
      --enhance-mode gated 时改为双模型融合：v1 结构分支 + 强增强分支，残差用
      压力自身构造的软掩膜门控（无关节标注时的近似），门控外逐像素保留原值。

运行方式（仓库根目录或任意目录均可）：

    python visualization/frontend/server.py
    # 指定模型与端口
    python visualization/frontend/server.py --model src/body_segmentation/models/best.pt --port 8000
    python visualization/frontend/server.py --posture-model src/posture_recognition/models/cnn.pt
    python visualization/frontend/server.py --enhance-model models/pressure_enhancement_v1.pt
    python visualization/frontend/server.py --enhance-mode gated
    # 没有模型权重时用于前端联调（mock 掩码，非模型输出）
    python visualization/frontend/server.py --mock

浏览器打开 http://127.0.0.1:8000，然后选择本地 txt 或内置样例即可看到
身体部位划分结果实时叠加；页面左上角“身体区域”“识别来源”会标明来源。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import numpy as np

FRONTEND_ROOT = Path(__file__).resolve().parent
REPO_ROOT = FRONTEND_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LABELS = {
    "0": "background",
    "1": "shoulder",
    "2": "back",
    "3": "waist",
    "4": "hip",
    "5": "thigh",
}

# 与 src/body_segmentation/dataset.py 保持一致（仅供 mock / 校验使用）
SENSOR_SHAPE = (44, 24)

# 睡姿类别顺序与 src/posture_recognition/infer.py 的 CLASS_NAMES 一致
POSTURE_CLASSES = ("supine", "prone", "left_lateral", "right_lateral")
POSTURE_LABEL_ACTIONS = {"0": "1-6", "1": "7-9", "2": "10-15", "3": "16-21"}

# mock 演示用的固定五区域矩形 [start, end)，与 config.js 中 regions 一致
MOCK_REGIONS = [
    (3, 8, 6, 18),
    (8, 13, 6, 18),
    (13, 18, 6, 18),
    (18, 27, 5, 20),
    (27, 36, 5, 20),
]


class SegmentationServer:
    """持有模型句柄，提供 /api/status 与 /api/segment。"""

    def __init__(self, model_path: Path, mock: bool = False) -> None:
        self.model_path = Path(model_path)
        self.mock = mock
        self.model = None
        self.model_loaded = False
        self.model_error: str | None = None
        self.input_size = (96, 48)
        self.device = "cpu"

    @property
    def available(self) -> bool:
        """接口可用 = mock 模式，或模型文件存在。"""
        return self.mock or self.model_path.exists()

    def load_model(self) -> None:
        """懒加载 UNet（仅在非 mock 且首次请求划分时执行）。"""
        if self.model_loaded or self.model_error:
            return
        if not self.model_path.exists():
            self.model_error = (
                f"未找到模型权重 {self.model_path}。请先训练/获取 best.pt，"
                "或使用 --mock 进行前端联调。"
            )
            return
        try:
            import torch
            from src.body_segmentation.evaluate import load_model

            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model, checkpoint = load_model(self.model_path, self.device)
            self.model.eval()
            self.input_size = tuple(checkpoint.get("input_size", [96, 48]))
            self.model_loaded = True
        except Exception as exc:  # noqa: BLE001 - 统一转成对前端友好的错误
            self.model_error = f"模型加载失败: {exc}"

    def status(self) -> dict[str, Any]:
        self.load_model()
        return {
            "ok": True,
            "mode": "mock" if self.mock else "model",
            "available": self.available,
            "model_loaded": self.model_loaded,
            "model_path": str(self.model_path) if not self.mock else None,
            "input_size": list(self.input_size),
            "sensor_shape": list(SENSOR_SHAPE),
            "labels": LABELS,
            "error": self.model_error if not self.mock and not self.model_loaded else None,
        }

    def segment(self, frames: list[np.ndarray], frame_ids: list[str]) -> list[dict[str, Any]]:
        """输入 N×44×24 压力矩阵，返回 api_docs 约定的分割结果。"""
        arrays = np.stack(frames).astype(np.float32)
        if self.mock:
            masks = self._mock_masks(arrays)
            source = "body_segmentation · mock联调掩码"
        else:
            self.load_model()
            if not self.model_loaded:
                raise RuntimeError(self.model_error or "模型尚未加载")
            import torch
            from src.body_segmentation.evaluate import predict

            # 与训练/评估一致：逐帧 min-max 归一化
            lows = arrays.min(axis=(1, 2), keepdims=True)
            highs = arrays.max(axis=(1, 2), keepdims=True)
            arrays = (arrays - lows) / np.maximum(highs - lows, 1e-8)
            images = torch.from_numpy(arrays).unsqueeze(1)
            masks = predict(self.model, images, self.device, self.input_size).numpy()
            source = "body_segmentation · UNet"

        results: list[dict[str, Any]] = []
        for index, mask in enumerate(masks):
            results.append(
                {
                    "frame_id": frame_ids[index] if index < len(frame_ids) else f"frame_{index:06d}",
                    "segmentation_shape": list(SENSOR_SHAPE),
                    "segmentation_mask": mask.astype(int).tolist(),
                    "labels": LABELS,
                    "source": source,
                }
            )
        return results

    def _mock_masks(self, arrays: np.ndarray) -> np.ndarray:
        """模拟 UNet 输出：在五区域矩形内按接触阈值着色（仅用于无模型联调）。"""
        height, width = SENSOR_SHAPE
        masks = np.zeros((arrays.shape[0], height, width), dtype=np.int64)
        for frame_index, matrix in enumerate(arrays):
            max_value = float(matrix.max())
            threshold = max(2.0, max_value * 0.03)
            for label, (row_lo, row_hi, col_lo, col_hi) in enumerate(MOCK_REGIONS, start=1):
                region = matrix[row_lo:row_hi, col_lo:col_hi] > threshold
                masks[frame_index, row_lo:row_hi, col_lo:col_hi][region] = label
        return masks


class PostureService:
    """持有睡姿识别模型句柄，提供 /api/posture。"""

    def __init__(self, model_path: Path, algorithm: str = "cnn", mock: bool = False) -> None:
        self.model_path = Path(model_path)
        self.algorithm = algorithm
        self.mock = mock
        self.predictor = None
        self.model_error: str | None = None
        if not mock:
            try:
                from src.posture_recognition.infer import PosturePredictor

                self.predictor = PosturePredictor(self.model_path, algorithm=algorithm)
            except Exception as exc:  # noqa: BLE001 - 依赖缺失时降级为不可用
                self.model_error = f"睡姿识别模块导入失败: {exc}"

    @property
    def available(self) -> bool:
        """接口可用 = mock 模式，或模型文件存在且模块导入成功。"""
        return self.mock or (self.predictor is not None and self.predictor.available)

    def status(self) -> dict[str, Any]:
        if self.mock:
            return {
                "ok": True,
                "mode": "mock",
                "available": True,
                "algorithm": self.algorithm,
                "model_loaded": False,
                "model_path": None,
                "classes": list(POSTURE_CLASSES),
                "label_actions": POSTURE_LABEL_ACTIONS,
                "sensor_shape": list(SENSOR_SHAPE),
                "error": None,
            }
        payload = (
            self.predictor.status()
            if self.predictor is not None
            else {
                "ok": True,
                "available": False,
                "model_loaded": False,
                "classes": list(POSTURE_CLASSES),
                "label_actions": POSTURE_LABEL_ACTIONS,
                "sensor_shape": list(SENSOR_SHAPE),
            }
        )
        payload["mode"] = "model"
        payload["algorithm"] = self.algorithm
        payload["model_path"] = str(self.model_path)
        if self.model_error:
            payload["error"] = self.model_error
        return payload

    def predict(
        self, frames: list[np.ndarray], frame_ids: list[str]
    ) -> list[dict[str, Any]]:
        """输入 N×44×24 压力矩阵，返回 api_docs 约定的睡姿识别结果。"""
        if self.mock:
            results = [self._mock_result(index) for index in range(len(frames))]
        else:
            if self.predictor is None:
                raise RuntimeError(self.model_error or "睡姿识别模块不可用")
            results = self.predictor.predict(frames)

        payloads: list[dict[str, Any]] = []
        for index, result in enumerate(results):
            entry = dict(result)
            entry["frame_id"] = (
                frame_ids[index] if index < len(frame_ids) else f"frame_{index:06d}"
            )
            entry["sensor_shape"] = list(SENSOR_SHAPE)
            payloads.append(entry)
        return payloads

    @staticmethod
    def _mock_result(index: int) -> dict[str, Any]:
        """无模型时的联调结果：按帧轮换类别，明确标注不是模型输出。"""
        posture = POSTURE_CLASSES[index % len(POSTURE_CLASSES)]
        return {
            "posture": posture,
            "label_index": index % len(POSTURE_CLASSES),
            "confidence": 1.0,
            "scores": {name: 1.0 if name == posture else 0.0 for name in POSTURE_CLASSES},
            "source": "睡姿识别 · mock联调（非模型输出）",
        }


class EnhanceService:
    """持有弱力增强（PolishNetU）模型句柄，提供 /api/enhance。

    模型输入是固定范围的 Viridis RGB 图，形状 (N, 24, 44, 3)；这里把前端
    的 44×24 压力矩阵转置成 24×44 上色后推理，再把输出图反查回压力值，
    这样前端可以复用同一套热力图渲染与指标计算。
    """

    def __init__(
        self,
        model_path: Path,
        viridis_low: float = 0.0,
        viridis_high: float = 300.0,
        mock: bool = False,
        mode: str = "single",
        v1_model_path: Path | None = None,
        v1_weight: float = 0.15,
        strong_weight: float = 0.85,
        strong_strength: float = 2.0,
        max_gain: float = 0.75,
        gate_threshold: float = 0.10,
        gate_radius: int = 5,
        weak_exponent: float = 1.0,
    ) -> None:
        if mode not in ("single", "gated"):
            raise ValueError("enhance mode 只能是 single 或 gated")
        self.model_path = Path(model_path)
        self.v1_model_path = Path(v1_model_path) if v1_model_path else None
        self.viridis_low = float(viridis_low)
        self.viridis_high = float(viridis_high)
        self.mock = mock
        self.mode = mode
        self.v1_weight = float(v1_weight)
        self.strong_weight = float(strong_weight)
        self.strong_strength = float(strong_strength)
        self.max_gain = float(max_gain)
        self.gate_threshold = float(gate_threshold)
        self.gate_radius = int(gate_radius)
        self.weak_exponent = float(weak_exponent)
        self.model = None
        self.v1_model = None
        self.model_loaded = False
        self.model_error: str | None = None
        self.base_channels = None
        self.residual_scale = None
        self.model_name = None
        self.v1_model_name = None
        self.method = None
        self.device = "cpu"
        self._lut: np.ndarray | None = None
        self._gates: list[float] | None = None

    @property
    def available(self) -> bool:
        return self.mock or self.model_path.exists()

    def load_model(self) -> None:
        """懒加载发布权重（只含推理参数，不需要 OpenPose）。

        gated 模式需要同时加载结构模型（v1）与强增强模型，两者都只做推理。
        """
        if self.model_loaded or self.model_error or self.mock:
            return
        if not self.model_path.exists():
            self.model_error = (
                f"未找到增强模型 {self.model_path}。请从 GitHub Release 或团队"
                "共享盘获取发布权重后放入 models/。"
            )
            return
        try:
            import torch

            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            # gated 模式下强模型按论文融合脚本的做法放大推理强度
            scale = self.strong_strength if self.mode == "gated" else 1.0
            model, info = self._load_checkpoint(self.model_path, scale)
            self.model = model
            self.model_name = info["model_name"]
            self.base_channels = info["base_channels"]
            self.residual_scale = info["residual_scale"]
            self.method = info["method"]
            if self.mode == "gated":
                if self.v1_model_path is None:
                    raise ValueError("gated 模式需要 --enhance-v1-model")
                v1_model, v1_info = self._load_checkpoint(self.v1_model_path)
                if v1_info["model_name"] != "PaperPolishNetU":
                    raise ValueError(
                        f"门控融合的 v1 权重必须是论文流程格式，实际为 "
                        f"{v1_info['model_name']}"
                    )
                self.v1_model = v1_model
                self.v1_model_name = v1_info["model_name"]
            self._lut = self._build_viridis_lut()
            self.model_loaded = True
        except Exception as exc:  # noqa: BLE001 - 统一转成对前端友好的错误
            self.model_error = f"增强模型加载失败: {exc}"

    def _load_checkpoint(
        self, path: Path, residual_scale_scale: float = 1.0
    ) -> tuple[Any, dict[str, Any]]:
        """按顶层键自动识别两种发布格式并加载模型。"""
        import torch

        if not Path(path).exists():
            raise FileNotFoundError(f"未找到模型权重 {path}")
        state = torch.load(path, map_location="cpu", weights_only=False)
        if "polish_state_dict" in state:
            from src.pressure_enhancement.paper_pipeline import PaperPolishNetU

            base_channels = int(state.get("base_channels", 24))
            model = PaperPolishNetU(base_channels).to(self.device)
            model.load_state_dict(state["polish_state_dict"])
            info = {
                "model_name": "PaperPolishNetU",
                "base_channels": base_channels,
                "residual_scale": None,
            }
        elif "model_state_dict" in state:
            from src.pressure_enhancement.enhance import PolishNetU

            base_channels = int(state.get("base_channels", 8))
            residual_scale = float(state.get("residual_scale", 0.125)) * residual_scale_scale
            model = PolishNetU(
                base_channels=base_channels, residual_scale=residual_scale
            ).to(self.device)
            model.load_state_dict(state["model_state_dict"])
            info = {
                "model_name": "PolishNetU",
                "base_channels": base_channels,
                "residual_scale": residual_scale,
            }
        else:
            raise KeyError("权重缺少 polish_state_dict / model_state_dict，无法识别格式")
        model.eval()
        info["method"] = str(state.get("method", "unknown"))
        return model, info

    def status(self) -> dict[str, Any]:
        self.load_model()
        payload = {
            "ok": True,
            "mode": "mock" if self.mock else "model",
            "enhance_mode": self.mode,
            "available": self.available,
            "model_loaded": self.model_loaded,
            "model_path": None if self.mock else str(self.model_path),
            "model_name": self.model_name,
            "base_channels": self.base_channels,
            "residual_scale": self.residual_scale,
            "method": self.method,
            "viridis_range": [self.viridis_low, self.viridis_high],
            "sensor_shape": list(SENSOR_SHAPE),
            "model_shape": [SENSOR_SHAPE[1], SENSOR_SHAPE[0], 3],
            "error": self.model_error,
        }
        if self.mode == "gated":
            payload["v1_model_path"] = (
                str(self.v1_model_path) if self.v1_model_path else None
            )
            payload["v1_model_name"] = self.v1_model_name
            payload["fusion"] = {
                "v1_weight": self.v1_weight,
                "strong_weight": self.strong_weight,
                "strong_inference_strength": self.strong_strength,
                "max_gain": self.max_gain,
                "gate_threshold": self.gate_threshold,
                "gate_radius": self.gate_radius,
                "weak_exponent": self.weak_exponent,
                "gate_source": "pressure-derived soft mask (no joint labels)",
            }
        return payload

    def enhance(
        self, frames: list[np.ndarray], frame_ids: list[str]
    ) -> list[dict[str, Any]]:
        matrices = [parse_frame_matrix(frame) for frame in frames]
        if self.mock:
            enhanced = [matrix for matrix in matrices]
            source = "弱力增强 · mock联调（未过模型）"
        else:
            self.load_model()
            if not self.model_loaded:
                raise RuntimeError(self.model_error or "增强模型尚未加载")
            enhanced = self._run_model(matrices)
            if self.mode == "gated":
                source = (
                    f"弱力增强 · 门控融合 {self.v1_model_path.name} + "
                    f"{self.model_path.name}"
                )
            else:
                source = f"弱力增强 · {self.model_path.name}（{self.model_name}）"

        results: list[dict[str, Any]] = []
        for index, (raw, output) in enumerate(zip(matrices, enhanced)):
            gate_coverage = None
            if self._gates is not None and index < len(self._gates):
                gate_coverage = round(float(self._gates[index]), 4)
            results.append(
                {
                    "frame_id": (
                        frame_ids[index]
                        if index < len(frame_ids)
                        else f"frame_{index:06d}"
                    ),
                    "enhanced_shape": list(SENSOR_SHAPE),
                    "enhanced_matrix": np.round(output, 2).tolist(),
                    "raw_stats": {
                        "max": float(raw.max()),
                        "mean": float(raw.mean()),
                    },
                    "enhanced_stats": {
                        "max": float(output.max()),
                        "mean": float(output.mean()),
                    },
                    "gate_coverage": gate_coverage,
                    "source": source,
                }
            )
        return results

    def _run_model(self, matrices: list[np.ndarray]) -> list[np.ndarray]:
        """返回 44×24 的增强压力矩阵；门控模式下门控外逐像素保留原始值。"""
        # 44×24 -> 24×44，与训练时 reshape(44,24).T 的布局一致
        normalized = self._normalized_pressure(matrices)
        self._gates = None
        if self.mode == "gated":
            strong = self._model_pressure(self.model, normalized)
            structural = self._model_pressure(self.v1_model, normalized)
            residual = (
                self.v1_weight * (structural - normalized)
                + self.strong_weight * (strong - normalized)
            )
            # 融合模式只保留正向增益，避免把实测压力压掉
            residual = np.clip(residual, 0.0, self.max_gain)
            gate = self._pressure_gate(normalized)
            output = np.clip(normalized + gate * residual, 0.0, 1.0)
            self._gates = [float(value.mean()) for value in gate]
        else:
            output = self._model_pressure(self.model, normalized)
        scale = self.viridis_high - self.viridis_low
        return [
            (np.clip(frame, 0.0, 1.0) * scale + self.viridis_low).T
            for frame in output
        ]

    def _normalized_pressure(self, matrices: list[np.ndarray]) -> np.ndarray:
        stacked = np.stack([matrix.T for matrix in matrices]).astype(np.float32)
        return np.clip(
            (stacked - self.viridis_low)
            / max(self.viridis_high - self.viridis_low, 1e-6),
            0.0,
            1.0,
        )

    def _model_pressure(self, model: Any, normalized: np.ndarray) -> np.ndarray:
        """跑一次模型，并把输出 RGB 反查回归一化压力 (N, 24, 44)。"""
        if model is None:
            raise RuntimeError("增强模型尚未加载")
        import torch

        rgb = np.asarray(self._lut, dtype=np.float32)[
            np.rint(normalized * 255.0).astype(np.int32)
        ]
        batch = torch.from_numpy(rgb).permute(0, 3, 1, 2) * 2.0 - 1.0
        batch = batch.to(self.device)
        with torch.inference_mode():
            prediction = model(batch)
            output = ((prediction.clamp(-1.0, 1.0) + 1.0) * 127.5).round()
        images = output.to(torch.uint8).permute(0, 2, 3, 1).cpu().numpy()
        return self._rgb_to_pressure_normalized(images)

    def _rgb_to_pressure_normalized(self, images: np.ndarray) -> np.ndarray:
        """把增强后的 RGB 反查回归一化压力（近似，用 Viridis 色表最近邻）。"""
        colors = images.astype(np.float32).reshape(-1, 3) / 255.0
        lut = np.asarray(self._lut, dtype=np.float32)
        indices = np.empty(len(colors), dtype=np.int32)
        for start in range(0, len(colors), 4096):
            chunk = colors[start : start + 4096]
            distance = ((chunk[:, None, :] - lut[None, :, :]) ** 2).sum(axis=-1)
            indices[start : start + len(chunk)] = distance.argmin(axis=1)
        return indices.reshape(images.shape[:3]).astype(np.float32) / 255.0

    def _pressure_gate(self, normalized: np.ndarray) -> np.ndarray:
        """没有关节标注时，用压力自身的局部覆盖度构造软掩膜。

        先做 5×5 最大值滤波（把接触区外围的弱压力纳入门控），再高斯平滑，
        按 gate_threshold 截断使远离人体的背景门控值为 0，最后乘
        ``(1 - 归一化压力) ** weak_exponent`` 做弱压优先加权：压力越高附加
        增益越小，避免把已经很强的接触区继续抬高。
        """
        try:
            from scipy.ndimage import gaussian_filter, maximum_filter
        except ImportError as exc:  # pragma: no cover - 依赖缺失时的明确提示
            raise RuntimeError("门控模式需要 scipy：pip install scipy") from exc

        size = max(3, int(self.gate_radius) | 1)
        coverage = maximum_filter(normalized, size=(1, size, size), mode="nearest")
        coverage = gaussian_filter(coverage, sigma=(0.0, 1.5, 1.5), mode="nearest")
        gate = np.clip(
            (coverage - self.gate_threshold) / max(1.0 - self.gate_threshold, 1e-6),
            0.0,
            1.0,
        ) ** 0.7
        if self.weak_exponent:
            gate = gate * np.clip(1.0 - normalized, 0.0, 1.0) ** self.weak_exponent
        return gate.astype(np.float32)

    @staticmethod
    def _build_viridis_lut() -> np.ndarray:
        import matplotlib

        return np.asarray(
            matplotlib.colormaps["viridis"](np.linspace(0.0, 1.0, 256))[:, :3],
            dtype=np.float32,
        )


def parse_frame_matrix(entry: Any) -> np.ndarray:
    """把单个输入解析成 44×24 矩阵，兼容二维矩阵与 1056 长度一维数组。"""
    if isinstance(entry, dict):
        matrix = (
            entry.get("pressure_matrix")
            or entry.get("pressureMatrix")
            or entry.get("matrix")
            or entry.get("data")
        )
        if matrix is None:
            raise ValueError("帧缺少 pressure_matrix / matrix 字段")
    else:
        matrix = entry
    try:
        values = np.asarray(matrix, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError("压力矩阵不是合法数值数组") from exc
    if values.ndim == 2 and values.shape == SENSOR_SHAPE:
        return values
    if values.ndim == 1 and values.size == SENSOR_SHAPE[0] * SENSOR_SHAPE[1]:
        return values.reshape(SENSOR_SHAPE)
    raise ValueError(f"压力矩阵形状应为 {SENSOR_SHAPE[0]}x{SENSOR_SHAPE[1]} 或展开的 1056 个值")


class FrontendHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer  # type: ignore[assignment]

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            raise ValueError("请求体为空")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求体应为 JSON 对象")
        return payload

    # ---- 路由 ----
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json(self._status_payload())
            return
        if parsed.path in ("/api/posture", "/api/posture/status"):
            self._send_json(self.server.posture.status())
            return
        if parsed.path in ("/api/enhance", "/api/enhance/status"):
            self._send_json(self.server.enhance.status())
            return
        self._serve_static(unquote(parsed.path))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        routes = {
            "/api/segment": (self.server.segmentation, "segment", "分割推理失败"),
            "/api/posture": (self.server.posture, "predict", "睡姿识别失败"),
            "/api/enhance": (self.server.enhance, "enhance", "弱力增强失败"),
        }
        if parsed.path not in routes:
            self._send_json({"ok": False, "error": "接口不存在"}, HTTPStatus.NOT_FOUND)
            return
        service, method_name, failure_message = routes[parsed.path]
        action = getattr(service, method_name)
        started = time.time()
        try:
            payload = self._read_json()
            raw_frames = payload.get("frames")
            frame_ids = payload.get("frame_ids") or payload.get("frameIds") or []
            if raw_frames is None:
                if any(key in payload for key in ("pressure_matrix", "pressureMatrix", "matrix")):
                    raw_frames = [payload]
                else:
                    raw_frames = payload.get("matrices")
            if not raw_frames:
                raise ValueError("请求需要 frames 数组或单帧 pressure_matrix")
            matrices = [parse_frame_matrix(item) for item in raw_frames]
            results = action(matrices, list(frame_ids))
            self._send_json(
                {
                    "ok": True,
                    "num_frames": len(results),
                    "elapsed_ms": round((time.time() - started) * 1000, 1),
                    "results": results,
                }
            )
        except json.JSONDecodeError:
            self._send_json({"ok": False, "error": "JSON 解析失败"}, HTTPStatus.BAD_REQUEST)
        except (ValueError, TypeError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            self._send_json(
                {"ok": False, "error": f"{failure_message}: {exc}"},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def _status_payload(self) -> dict[str, Any]:
        """GET /api/status：同时汇报身体划分、睡姿识别与弱力增强的模型状态。"""
        segmentation = self.server.segmentation.status()
        posture = self.server.posture.status()
        enhance = self.server.enhance.status()
        return {
            "ok": True,
            "segmentation": segmentation,
            "posture": posture,
            "enhance": enhance,
            # 兼容早期只读顶层字段的调用方
            "mode": segmentation.get("mode"),
            "available": segmentation.get("available"),
            "model_loaded": segmentation.get("model_loaded"),
            "model_path": segmentation.get("model_path"),
            "input_size": segmentation.get("input_size"),
            "sensor_shape": segmentation.get("sensor_shape"),
            "labels": segmentation.get("labels"),
            "error": segmentation.get("error"),
        }

    # ---- 静态文件 ----
    def _serve_static(self, url_path: str) -> None:
        if url_path in ("", "/"):
            url_path = "/index.html"
        relative = Path(url_path.lstrip("/"))
        target = (FRONTEND_ROOT / relative).resolve()
        # 防目录穿越：目标必须仍在 frontend 目录内
        try:
            target.relative_to(FRONTEND_ROOT.resolve())
        except ValueError:
            self._send_text("Forbidden", HTTPStatus.FORBIDDEN)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists() or not target.is_file():
            self._send_text("Not Found", HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "application/json",
        ):
            content_type += "; charset=utf-8"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.server.debug:
            super().log_message(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="前端静态资源 + 身体划分 / 睡姿识别实时接口服务",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument(
        "--model",
        type=Path,
        default=REPO_ROOT / "src" / "body_segmentation" / "models" / "best.pt",
        help="身体部位划分模型权重 best.pt",
    )
    parser.add_argument(
        "--posture-model",
        type=Path,
        default=REPO_ROOT / "src" / "posture_recognition" / "models" / "cnn.pt",
        help="睡姿识别模型权重 cnn.pt / svm.joblib / random_forest.joblib",
    )
    parser.add_argument(
        "--posture-algorithm",
        choices=("cnn", "svm", "random_forest"),
        default="cnn",
        help="睡姿识别算法（需与 --posture-model 对应）",
    )
    parser.add_argument(
        "--enhance-model",
        type=Path,
        default=REPO_ROOT / "models" / "annotated_pressure_strong_v0.pt",
        help="弱力增强权重，支持论文流程与早期基线两种发布格式（自动识别）",
    )
    parser.add_argument(
        "--enhance-viridis-low",
        type=float,
        default=0.0,
        help="渲染增强模型输入用的 Viridis 色标下限（与训练一致）",
    )
    parser.add_argument(
        "--enhance-viridis-high",
        type=float,
        default=300.0,
        help="渲染增强模型输入用的 Viridis 色标上限（与训练一致）",
    )
    parser.add_argument(
        "--enhance-mode",
        choices=("single", "gated"),
        default="single",
        help="single=单模型直接输出；gated=v1+强模型按压力软掩膜门控融合（近似论文融合脚本）",
    )
    parser.add_argument(
        "--enhance-v1-model",
        type=Path,
        default=REPO_ROOT / "models" / "pressure_enhancement_v1.pt",
        help="gated 模式下作为结构分支的论文流程权重",
    )
    parser.add_argument("--enhance-v1-weight", type=float, default=0.15)
    parser.add_argument("--enhance-strong-weight", type=float, default=0.85)
    parser.add_argument(
        "--enhance-strong-strength",
        type=float,
        default=2.0,
        help="gated 模式下强模型的推理强度（论文融合脚本默认 2.0）",
    )
    parser.add_argument("--enhance-max-gain", type=float, default=0.75)
    parser.add_argument("--enhance-gate-threshold", type=float, default=0.10)
    parser.add_argument(
        "--enhance-gate-radius",
        type=int,
        default=5,
        help="压力门控的最大值滤波半径（奇数），越大覆盖范围越宽",
    )
    parser.add_argument(
        "--enhance-weak-exponent",
        type=float,
        default=1.0,
        help="弱压优先指数，0 表示不做弱压加权",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="不使用模型，返回矩形模拟掩码（仅用于前端联调）",
    )
    parser.add_argument("--debug", action="store_true", help="打印每个请求日志")
    args = parser.parse_args()

    segmentation = SegmentationServer(args.model, mock=args.mock)
    posture = PostureService(
        args.posture_model, algorithm=args.posture_algorithm, mock=args.mock
    )
    enhance = EnhanceService(
        args.enhance_model,
        viridis_low=args.enhance_viridis_low,
        viridis_high=args.enhance_viridis_high,
        mock=args.mock,
        mode=args.enhance_mode,
        v1_model_path=args.enhance_v1_model,
        v1_weight=args.enhance_v1_weight,
        strong_weight=args.enhance_strong_weight,
        strong_strength=args.enhance_strong_strength,
        max_gain=args.enhance_max_gain,
        gate_threshold=args.enhance_gate_threshold,
        gate_radius=args.enhance_gate_radius,
        weak_exponent=args.enhance_weak_exponent,
    )
    handler = FrontendHandler
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    httpd.segmentation = segmentation  # type: ignore[attr-defined]
    httpd.posture = posture  # type: ignore[attr-defined]
    httpd.enhance = enhance  # type: ignore[attr-defined]
    httpd.debug = args.debug  # type: ignore[attr-defined]
    mode = "mock（前端联调）" if args.mock else "UNet 模型"
    print(f"[frontend-server] 页面: http://{args.host}:{args.port}")
    print(f"[frontend-server] 分割模式: {mode}")
    print(
        "[frontend-server] 睡姿模式: "
        + ("mock（前端联调）" if args.mock else f"{args.posture_algorithm} 模型")
    )
    print(
        "[frontend-server] 增强模式: "
        + (
            "mock（前端联调）"
            if args.mock
            else f"{args.enhance_mode} · {args.enhance_model.name}"
        )
    )
    if not args.mock:
        print(f"[frontend-server] 模型: {segmentation.model_path}")
        if not segmentation.model_path.exists():
            print("[frontend-server] 提示: 未找到 best.pt，页面将回退到区域矩形演示；"
                  "也可加 --mock 用模拟掩码联调前端。")
        print(f"[frontend-server] 睡姿模型: {posture.model_path}")
        if not posture.model_path.exists():
            print("[frontend-server] 提示: 未找到睡姿模型，页面将回退到样例标注；"
                  "也可加 --mock 用模拟睡姿联调前端。")
        print(f"[frontend-server] 增强模型: {enhance.model_path}")
        if not enhance.model_path.exists():
            print("[frontend-server] 提示: 未找到增强权重，页面增强开关将回退到原始热力图。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[frontend-server] 已停止")
        httpd.server_close()


if __name__ == "__main__":
    main()
