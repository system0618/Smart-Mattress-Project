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
  "segmentation_shape": [32, 64],
  "segmentation_mask": [[0, 1, 1, 2]],
  "labels": {
    "0": "background",
    "1": "head",
    "2": "trunk",
    "3": "left_arm",
    "4": "right_arm",
    "5": "left_leg",
    "6": "right_leg"
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

## File Naming

建议训练数据文件名包含用户、睡姿和采集序号：

```text
user001_supine_0001.npy
user001_left_lateral_0002.npy
```
