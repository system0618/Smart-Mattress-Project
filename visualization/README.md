# Visualization

可视化模块负责展示压力热力图、睡姿识别结果、身体部位划分结果、压力指标和气囊状态。

可选实现路线：

- `frontend/`：Web 前端，适合使用 JS/TypeScript、Canvas、ECharts 或 Three.js。
- `unity_project/`：Unity 客户端，适合 Windows 部署和 3D 展示。

当前采用 **JS Web 前端** 路线，基础版本已完成，见 [frontend/README.md](frontend/README.md)。

```text
visualization/
├── frontend/        # JS Canvas 实时可视化（当前实现）
└── unity_project/   # Unity 路线备选（尚未启用）
```
