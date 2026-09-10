# -*- coding: utf-8 -*-
"""睡姿识别推理封装：把训练好的模型跑在单帧或多帧 44x24 压力矩阵上。

标签语义来自 ``图片和附件/睡姿 区域划分data`` 的采集协议（动作 1-21 与
``data.json`` 中 ``sleep_pos`` 的对应关系）：

* 标签 0 = 动作 1-6   仰卧类 supine
* 标签 1 = 动作 7-9   俯卧类 prone
* 标签 2 = 动作 10-15 左侧卧类 left_lateral
* 标签 3 = 动作 16-21 右侧卧类 right_lateral

参考论文最多支持 6 类，当前数据集只有 4 类；多出的类别没有样本，不使用虚构名称。

命令行自测（txt 为 ``睡姿数据`` 目录下的原始采集文件）：

    python -m src.posture_recognition.infer --status
    python -m src.posture_recognition.infer --txt "图片和附件/睡姿 区域划分data/睡姿数据/dgs/dgs_1.txt"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

HEIGHT, WIDTH = 44, 24

# 与 visualization/frontend/js/config.js 的 postureMap 键保持一致
CLASS_NAMES = ("supine", "prone", "left_lateral", "right_lateral")

# 当前数据集实际出现的标签及其动作范围
LABEL_ACTIONS = {0: "1-6", 1: "7-9", 2: "10-15", 3: "16-21"}

ALGORITHMS = ("cnn", "svm", "random_forest")


def class_names(num_classes: int) -> list[str]:
    """按类别数返回标签名；超出已知 4 类的部分用占位名，不虚构语义。"""
    names = list(CLASS_NAMES)
    while len(names) < num_classes:
        names.append(f"class_{len(names)}")
    return names[:num_classes]


def normalize(images: np.ndarray) -> np.ndarray:
    """与训练/评估一致的逐帧 min-max 归一化。"""
    values = np.asarray(images, dtype=np.float32)
    low = values.min(axis=(1, 2), keepdims=True)
    high = values.max(axis=(1, 2), keepdims=True)
    return (values - low) / np.maximum(high - low, 1e-6)


def parse_frame_matrix(entry: Any) -> np.ndarray:
    """把一帧解析成 44x24 矩阵，兼容二维矩阵与 1056 长度一维数组。"""
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
    if values.ndim == 2 and values.shape == (HEIGHT, WIDTH):
        return values
    if values.size == HEIGHT * WIDTH:
        return values.reshape(HEIGHT, WIDTH)
    raise ValueError(
        f"压力矩阵形状应为 {HEIGHT}x{WIDTH} 或展开的 {HEIGHT * WIDTH} 个值"
    )


def load_txt_frames(path: str | Path) -> np.ndarray:
    """读取采集 txt（每帧 44 行 x 24 列）为 N x 44 x 24 数组。"""
    frames: list[list[list[float]]] = []
    current: list[list[float]] = []
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            parts = line.replace(",", " ").split()
            if len(parts) < WIDTH:
                continue
            values = [float(part) for part in parts[:WIDTH]]
            if len(current) == HEIGHT:
                frames.append(current)
                current = []
            current.append(values)
    if len(current) == HEIGHT:
        frames.append(current)
    if not frames:
        raise ValueError(f"未从 {path} 解析出 44x24 的压力帧")
    return np.asarray(frames, dtype=np.float32)


class PosturePredictor:
    """按算法加载睡姿模型并给出单帧预测（懒加载，便于服务复用）。"""

    def __init__(
        self,
        model_path: str | Path,
        algorithm: str = "cnn",
        device: str | None = None,
    ) -> None:
        if algorithm not in ALGORITHMS:
            raise ValueError(f"未知算法 {algorithm}，可选 {ALGORITHMS}")
        self.model_path = Path(model_path)
        self.algorithm = algorithm
        self.device_name = device
        self.device: Any = None
        self.model: Any = None
        self.model_loaded = False
        self.model_error: str | None = None
        self.num_classes = len(CLASS_NAMES)
        self.class_names: list[str] = list(CLASS_NAMES)
        self.source = f"睡姿识别 · {self.model_path.name}"

    @property
    def available(self) -> bool:
        return self.model_path.exists()

    def load(self) -> None:
        """加载模型；失败时记录错误而不抛出，交给调用方降级。"""
        if self.model_loaded or self.model_error:
            return
        if not self.model_path.exists():
            self.model_error = (
                f"未找到睡姿模型 {self.model_path}。请先训练，或从 "
                "feature/posture-recognition 分支获取 cnn.pt。"
            )
            return
        try:
            if self.algorithm == "cnn":
                self._load_cnn()
            else:
                self._load_sklearn()
            self.model_loaded = True
        except Exception as exc:  # noqa: BLE001 - 统一转成对前端友好的错误
            self.model_error = f"睡姿模型加载失败: {exc}"

    def _load_cnn(self) -> None:
        import torch

        from .models import TinyPostureCNN

        self.device = torch.device(
            self.device_name
            if self.device_name
            else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        checkpoint = torch.load(
            self.model_path, map_location=self.device, weights_only=False
        )
        state = (
            checkpoint.get("model_state", checkpoint)
            if isinstance(checkpoint, dict)
            else checkpoint
        )
        num_classes = self._infer_num_classes(
            state,
            checkpoint.get("num_classes") if isinstance(checkpoint, dict) else None,
        )
        model = TinyPostureCNN(num_classes).to(self.device)
        model.load_state_dict(state)
        model.eval()
        self.model = model
        self.num_classes = num_classes
        self.class_names = class_names(num_classes)
        self.source = f"睡姿识别 · {self.model_path.name}（TinyPostureCNN）"

    @staticmethod
    def _infer_num_classes(state: dict[str, Any], declared: Any = None) -> int:
        """优先按分类头权重推断类别数，避免 checkpoint 里的类别名列表失真。

        ``cnn.pt`` 的 ``classes`` 字段存的是参考论文的 6 类名称，而实际训练只有
        4 类；直接采用会与分类头形状（4）不一致，因此以权重形状为准。
        """
        heads = [
            int(value.shape[0])
            for key, value in state.items()
            if key.endswith("weight")
            and "classifier" in key
            and getattr(value, "ndim", 0) == 2
        ]
        if heads:
            return heads[-1]
        if declared:
            return int(declared)
        return len(CLASS_NAMES)

    def _load_sklearn(self) -> None:
        import joblib

        payload = joblib.load(self.model_path)
        model = payload.get("model") if isinstance(payload, dict) else payload
        if model is None:
            raise ValueError("模型文件缺少 model 字段")
        stored_classes = payload.get("classes") if isinstance(payload, dict) else None
        if stored_classes:
            num_classes = len(stored_classes)
        elif hasattr(model, "classes_"):
            num_classes = int(max(int(label) for label in model.classes_)) + 1
        else:
            num_classes = len(CLASS_NAMES)
        self.model = model
        self.num_classes = num_classes
        self.class_names = class_names(num_classes)
        self.source = f"睡姿识别 · {self.model_path.name}（{self.algorithm}）"

    def status(self) -> dict[str, Any]:
        self.load()
        return {
            "ok": True,
            "algorithm": self.algorithm,
            "available": self.available,
            "model_loaded": self.model_loaded,
            "model_path": str(self.model_path),
            "classes": self.class_names,
            "label_actions": LABEL_ACTIONS,
            "num_classes": len(self.class_names),
            "sensor_shape": [HEIGHT, WIDTH],
            "error": self.model_error,
        }

    def predict(self, frames: list[np.ndarray]) -> list[dict[str, Any]]:
        """输入 N 帧 44x24 压力矩阵，返回每帧的睡姿、置信度与各类别概率。"""
        self.load()
        if not self.model_loaded:
            raise RuntimeError(self.model_error or "睡姿模型尚未加载")
        images = np.stack([parse_frame_matrix(frame) for frame in frames]).astype(np.float32)
        probabilities = self._predict_proba(images)
        results: list[dict[str, Any]] = []
        for row in probabilities:
            index = int(np.argmax(row))
            scores = {
                name: float(score)
                for name, score in zip(self.class_names, row)
            }
            results.append(
                {
                    "posture": self.class_names[index],
                    "label_index": index,
                    "confidence": float(row[index]),
                    "scores": scores,
                    "source": self.source,
                }
            )
        return results

    def _predict_proba(self, images: np.ndarray) -> np.ndarray:
        if self.algorithm == "cnn":
            import torch

            batch = torch.from_numpy(normalize(images)).unsqueeze(1).to(self.device)
            with torch.inference_mode():
                probabilities = torch.softmax(self.model(batch), dim=1)
            return probabilities.cpu().numpy()

        from .features import extract_features

        features = extract_features(images)
        if hasattr(self.model, "predict_proba"):
            return np.asarray(self.model.predict_proba(features), dtype=np.float32)
        predicted = self.model.predict(features).astype(int)
        one_hot = np.zeros((len(predicted), len(self.class_names)), dtype=np.float32)
        one_hot[np.arange(len(predicted)), predicted] = 1.0
        return one_hot


def predict_txt(model_path, txt_path, algorithm: str = "cnn", device: str | None = None):
    """便捷函数：对采集 txt 的每一帧输出预测，返回 (frames, results)。"""
    frames = load_txt_frames(txt_path)
    predictor = PosturePredictor(model_path, algorithm=algorithm, device=device)
    return frames, predictor.predict(list(frames))


def main() -> None:
    parser = argparse.ArgumentParser(description="睡姿识别推理自测")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("src/posture_recognition/models/cnn.pt"),
        help="模型文件（cnn.pt / svm.joblib / random_forest.joblib）",
    )
    parser.add_argument("--algorithm", choices=ALGORITHMS, default="cnn")
    parser.add_argument("--txt", type=Path, help="采集 txt；给出时逐帧预测")
    parser.add_argument("--json", type=Path, help="data.json；给出时统计前 N 帧准确率")
    parser.add_argument("--limit", type=int, default=200, help="--json 模式采样的帧数")
    parser.add_argument("--device", default=None, help="cpu / cuda，默认自动选择")
    parser.add_argument("--status", action="store_true", help="只打印模型状态")
    args = parser.parse_args()

    if args.status:
        payload = PosturePredictor(args.model, args.algorithm, args.device).status()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.txt:
        frames, results = predict_txt(args.model, args.txt, args.algorithm, args.device)
        print(f"{args.txt.name}: {len(frames)} 帧")
        for index, result in enumerate(results[:10]):
            print(
                f"  frame {index:03d}: {result['posture']} "
                f"confidence={result['confidence']:.3f}"
            )
        return

    if args.json:
        from .dataset import load_json_dataset

        dataset = load_json_dataset(args.json)
        predictor = PosturePredictor(args.model, args.algorithm, args.device)
        limit = min(args.limit, len(dataset.images))
        results = predictor.predict(list(dataset.images[:limit]))
        correct = sum(
            result["label_index"] == int(label)
            for result, label in zip(results, dataset.labels[:limit])
        )
        print(f"{args.json.name}: 前 {limit} 帧准确率 {correct / limit:.4f}")
        return

    parser.error("请给出 --txt、--json 或 --status 之一")


if __name__ == "__main__":
    main()
