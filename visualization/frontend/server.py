# -*- coding: utf-8 -*-
"""智能床垫可视化一体化服务（前端静态资源 + 身体部位划分实时接口）。

用途：
    - 在 http://127.0.0.1:8000 提供 visualization/frontend 页面；
    - 按 docs/api_docs.md 约定提供 POST /api/segment：
      前端把每帧 44×24 压力矩阵发来，服务加载 src/body_segmentation 的 UNet
      (best.pt) 推理并返回 segmentation_mask JSON，前端再叠加到热力图。

运行方式（仓库根目录或任意目录均可）：

    python visualization/frontend/server.py
    # 指定模型与端口
    python visualization/frontend/server.py --model src/body_segmentation/models/best.pt --port 8000
    # 没有模型权重时用于前端联调（mock 掩码，非模型输出）
    python visualization/frontend/server.py --mock

浏览器打开 http://127.0.0.1:8000，然后选择本地 txt 或内置样例即可看到
身体部位划分结果实时叠加；页面左上角“身体区域”会标明来源。
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
            self._send_json(self.server.segmentation.status())
            return
        self._serve_static(unquote(parsed.path))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/segment":
            self._send_json({"ok": False, "error": "接口不存在"}, HTTPStatus.NOT_FOUND)
            return
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
            results = self.server.segmentation.segment(matrices, list(frame_ids))
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
                {"ok": False, "error": f"分割推理失败: {exc}"},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

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
        description="前端静态资源 + 身体部位划分 UNet 实时接口服务",
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
        "--mock",
        action="store_true",
        help="不使用模型，返回矩形模拟掩码（仅用于前端联调）",
    )
    parser.add_argument("--debug", action="store_true", help="打印每个请求日志")
    args = parser.parse_args()

    segmentation = SegmentationServer(args.model, mock=args.mock)
    handler = FrontendHandler
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    httpd.segmentation = segmentation  # type: ignore[attr-defined]
    httpd.debug = args.debug  # type: ignore[attr-defined]
    mode = "mock（前端联调）" if args.mock else "UNet 模型"
    print(f"[frontend-server] 页面: http://{args.host}:{args.port}")
    print(f"[frontend-server] 分割模式: {mode}")
    if not args.mock:
        print(f"[frontend-server] 模型: {segmentation.model_path}")
        if not segmentation.model_path.exists():
            print("[frontend-server] 提示: 未找到 best.pt，页面将回退到区域矩形演示；"
                  "也可加 --mock 用模拟掩码联调前端。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[frontend-server] 已停止")
        httpd.server_close()


if __name__ == "__main__":
    main()
