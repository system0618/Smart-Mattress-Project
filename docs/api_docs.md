# API Docs

本文档约定算法模块与可视化模块之间的数据接口。后续如字段变化，请同步更新。

## Pressure Frame

单帧压力数据建议使用 JSON 表示：

```json
{
  "frame_id": "frame_000001",
  "timestamp": "2026-08-31T20:30:00+08:00",
  "user_id": "user_001",
  "sensor_shape": [32, 64],
  "pressure_matrix": [[0.0, 0.1, 0.2]],
  "unit": "normalized"
}
```

## Posture Recognition Output

```json
{
  "frame_id": "frame_000001",
  "posture": "supine",
  "confidence": 0.98,
  "metrics": {
    "accuracy": 0.96,
    "precision": 0.95,
    "recall": 0.96,
    "f1": 0.95
  }
}
```

建议睡姿标签先统一为：

- `supine`：仰卧
- `left_lateral`：左侧卧
- `right_lateral`：右侧卧
- `prone`：俯卧
- `unknown`：未知或无效姿态

## Body Segmentation Output

```json
{
  "frame_id": "frame_000001",
  "segmentation_shape": [44, 24],
  "segmentation_mask": [[0, 1, 1, 2]],
  "labels": {
    "0": "background",
    "1": "shoulder",
    "2": "back",
    "3": "waist",
    "4": "hip",
    "5": "thigh"
  }
}
```

## Realtime Visualization State

```json
{
  "frame_id": "frame_000001",
  "pressure_stats": {
    "max_pressure": 0.93,
    "mean_pressure": 0.28,
    "contact_area_index": 0.41
  },
  "airbags": [
    {
      "airbag_id": "zone_01",
      "status": "inflating",
      "pressure": 0.62,
      "related_sensor_points": [[10, 20], [10, 21]]
    }
  ]
}
```

## Frontend Consumption（前端如何接收以上接口）

JS 前端（`visualization/frontend/`）已按上述 JSON 结构预留全局入口，算法模块只需把输出推送给页面：

| 数据 | 全局方法 |
| --- | --- |
| Pressure Frame | `SmartMattressViewer.pushFrame(payload)` |
| Posture Recognition Output | `SmartMattressViewer.setPostureResult(payload)` |
| Body Segmentation Output | `SmartMattressViewer.setSegmentationResult(payload)` |
| Realtime Visualization State | `SmartMattressViewer.setRealtimeState(payload)` |

推荐通过 WebSocket 在后端转发原始 JSON，前端仅做字段映射。热力图色标固定为 0–300。

## Local Segmentation Bridge（可视化本机联调）

`visualization/frontend/server.py` 提供一体化 HTTP 服务，方便直接联调身体部位划分
（无需再单独起 WebSocket 服务）：

- `GET /api/status`：返回模型文件是否存在、是否已加载、6 类 labels。
- `POST /api/segment`：请求体为 `{ "frames": [{ "pressure_matrix": [[...]] }] }`
  （也接受 1056 长度一维数组），服务加载 `src/body_segmentation/models/best.pt`
  后逐帧返回 Body Segmentation Output 数组：

```json
{
  "ok": true,
  "num_frames": 1,
  "results": [
    {
      "frame_id": "sample_0",
      "segmentation_shape": [44, 24],
      "segmentation_mask": [[0, 0, 1, 1]],
      "labels": {
        "0": "background", "1": "shoulder", "2": "back",
        "3": "waist", "4": "hip", "5": "thigh"
      },
      "source": "body_segmentation · UNet"
    }
  ]
}
```

启动方式：`python visualization/frontend/server.py`（`--mock` 可无模型联调前端）。

## Local Posture Bridge（睡姿识别本机联调）

同一个 `visualization/frontend/server.py` 也提供睡姿识别接口，前端会随着样例
自动请求，无需手动推送：

- `GET /api/status`：同时返回 `segmentation` 与 `posture` 两段模型状态。
- `GET /api/posture/status`：只返回睡姿模型状态（算法、类别、模型是否加载）。
- `POST /api/posture`：请求体与 `/api/segment` 相同，
  `{ "frames": [{ "pressure_matrix": [[...]] }] }`，服务加载
  `src/posture_recognition/models/cnn.pt`（或 `--posture-algorithm svm/random_forest`）
  后逐帧返回：

```json
{
  "ok": true,
  "num_frames": 1,
  "results": [
    {
      "frame_id": "sample_0",
      "posture": "left_lateral",
      "label_index": 2,
      "confidence": 0.9999,
      "scores": {"supine": 0.0, "prone": 0.0, "left_lateral": 0.9999, "right_lateral": 0.0},
      "sensor_shape": [44, 24],
      "source": "睡姿识别 · cnn.pt（TinyPostureCNN）"
    }
  ]
}
```

类别顺序与采集协议一致：0 仰卧（动作 1-6）、1 俯卧（动作 7-9）、
2 左侧卧（动作 10-15）、3 右侧卧（动作 16-21）。当前数据集只有这 4 类。
命令行自测见 `src/posture_recognition/infer.py`。

## Local Enhancement Bridge（弱力增强本机联调）

如需在页面上查看弱力增强效果，把 GitHub Release 的发布权重及其同名 manifest
放进仓库根目录的 `models/` 后重启 `server.py` 即可。默认使用
`annotated_pressure_strong_v0.pt`（早期强增益基线），换模型只需改
`--enhance-model`，服务会自动识别两种发布格式：

| 权重 | 顶层键 | 网络 | 备注 |
| --- | --- | --- | --- |
| `annotated_pressure_strong_v0.pt`（默认） | `model_state_dict` | PolishNetU | 早期强增益基线，输出增益最明显 |
| `pressure_enhancement_v1.pt` | `polish_state_dict` | PaperPolishNetU | 论文流程最终模型，改动更保守 |

这些权重只含推理参数，不需要 OpenPose、关节标注或重新训练。

- `GET /api/enhance/status`：返回增强模型是否加载、`base_channels`、Viridis 色标范围。
- `POST /api/enhance`：请求体与 `/api/segment` 相同，返回逐帧增强后的压力矩阵：

```json
{
  "ok": true,
  "num_frames": 1,
  "results": [
    {
      "frame_id": "sample_0",
      "enhanced_shape": [44, 24],
      "enhanced_matrix": [[0.0, 12.5]],
      "raw_stats": {"max": 252.0, "mean": 43.94},
      "enhanced_stats": {"max": 224.7, "mean": 43.13},
      "source": "弱力增强 · annotated_pressure_strong_v0.pt（PolishNetU）"
    }
  ]
}
```

服务内部把 44×24 压力矩阵按 `reshape(44,24).T` 转成模型要求的 24×44，
用固定 Viridis 色标（默认 `0–300`，可用 `--enhance-viridis-low/high` 调整）
上色后送进 `PaperPolishNetU`，再把输出图反查回压力值刻度，因此前端可以直接
复用同一套热力图渲染与指标计算。前端开关为热力图卡片右上角的“弱力增强”，
打开后热力图与压力指标都会切换到增强结果，关闭即回到原始矩阵。

### 门控融合模式（近似论文融合脚本）

页面上播放的是没有关节标注的实时帧，而论文的融合脚本
`ensemble_enhance_raw_sleep.py` 依赖真实 14 关节掩膜。为此 `server.py` 提供了
一个用压力自身构造软掩膜的近似实现：

```powershell
python visualization/frontend/server.py --enhance-mode gated
```

该模式同时加载 v1 结构分支与强增强分支（都用原始帧作输入，不做级联），在归一化
压力空间里取加权残差，只保留正向增益并按软掩膜门控，最后重新映射回压力刻度。
门控由 5×5 最大值滤波 + 高斯平滑 + 阈值得到，再乘 `(1-压力)^weak_exponent`
做弱压加权。可用参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--enhance-v1-model` | `models/pressure_enhancement_v1.pt` | 结构分支权重（须为论文流程格式） |
| `--enhance-v1-weight` / `--enhance-strong-weight` | 0.15 / 0.85 | 两分支残差权重 |
| `--enhance-strong-strength` | 2.0 | 强模型推理强度，与论文融合脚本一致 |
| `--enhance-max-gain` | 0.75 | 单像素正向增益上限（归一化压力尺度） |
| `--enhance-gate-threshold` | 0.10 | 掩膜阈值，越大覆盖越窄 |
| `--enhance-gate-radius` | 5 | 掩膜最大值滤波半径（奇数） |
| `--enhance-weak-exponent` | 1.0 | 弱压优先指数，调到 1.5 弱压抬升更明显，0 表示关闭 |

实测（312 帧、四类睡姿 + 动态样例）：门控覆盖率约 0.24，22.9% 的像素门控严格为 0
（逐像素保持原值）；平均变化 +11.9，其中弱压力区（30–105 ADC）+22.4、强压力区
（>105）+20.0，横向相邻差 14.06 → 14.09（几乎不增加噪点）。相比单用强模型的
（+20.8，弱压 +36.6、强压 +45.0、相邻差升到 15.97），门控模式更保守、更偏向弱压、
也不会把噪点放大。

需要注意的限制：本数据集存在约 14 ADC 的床垫底噪，没有关节标注时无法把“人体内
的弱压力”与“人体附近的底噪”完全区分开，因此门控只能保证**远离人体**的背景不变；
如果要和论文结果严格对齐，仍应使用带真实关节标注的
`ensemble_enhance_raw_sleep.py` 离线生成 HDF5。

## File Naming

建议训练数据文件名包含用户、睡姿和采集序号：

```text
user001_supine_0001.npy
user001_left_lateral_0002.npy
```
