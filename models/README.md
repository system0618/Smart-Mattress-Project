# 压力增强模型发布清单

本目录保存模型说明文件和校验清单；二进制 `.pt` 权重由 `.gitignore`
排除，必须作为 GitHub Release 附件上传，不能直接提交到 Git 仓库。

## 推荐模型

`pressure_enhancement_v1.pt` 是当前默认发布版本。它由真实关节标注数据训练，经过 40
epoch 的冻结姿态阶段和 40 epoch 的联合微调阶段，并使用稳健压力 target。该模型只含
`PaperPolishNetU` 推理权重，不包含 OpenPose、优化器状态或训练标注；约 53 MB。

## Release 附件

在同一个 GitHub Release 中上传下列 7 个 `.pt` 文件，以及目录中的全部
`*.manifest.json` 文件。每个 manifest 包含文件大小和 SHA-256，可在下载后核验完整性。

| 权重文件 | 来源 | 发布定位 | 推理入口 |
| --- | --- | --- | --- |
| `pressure_enhancement_v1.pt` | 联合微调 + 稳健 target | **默认推荐** | `paper_pipeline export` |
| `pressure_enhancement_frozen_target_v1.pt` | 冻结姿态 + 稳健 target | 阶段一复现 | `paper_pipeline export` |
| `pressure_enhancement_joint_legacy_v0.pt` | 联合微调 + 早期 target | 历史消融 | `paper_pipeline export` |
| `pressure_enhancement_frozen_pose_legacy_v0.pt` | 冻结姿态 + 早期 target | 历史消融 | `paper_pipeline export` |
| `annotated_pressure_final_v0.pt` | 真实标注早期压力域模型 | 历史基线 | `infer` |
| `annotated_pressure_strong_v0.pt` | 强增益压力域模型 | 历史基线 | `infer` |
| `polishnetu_baseline_v0.pt` | 最早的自重建基线（2 epoch） | 仅用于回归对照 | `infer` |

`*_smoke.pt` 仅用于短样本训练验证，不能发布。`Smart-Mattress-Project_SLP_archive`
中的 SLP 权重是已归档的旧实验，也不属于当前真实标注数据集的发布版本。

## 团队直接推理

将从 Release 下载的权重放入本目录。输入 HDF5 必须包含 `(N, 24, 44, 3)` 的
`input_images` 或 `images` 数据集，颜色编码为 Viridis RGB；不需要重新训练，也不需要
关节标签或 OpenPose 依赖。

论文流程模型（包括推荐模型）使用：

```powershell
python -m src.pressure_enhancement.paper_pipeline export `
  --input-h5 data/processed/input_pressure_rgb.h5 `
  --checkpoint models/pressure_enhancement_v1.pt `
  --output-h5 data/processed/input_pressure_enhanced.h5 `
  --comparison-output ..\压力增强对比图\部署结果\comparison.png `
  --batch-size 128
```

早期 `PolishNetU` 基线使用：

```powershell
python -m src.pressure_enhancement.infer `
  data/processed/input_pressure_rgb.h5 `
  --checkpoint models/annotated_pressure_final_v0.pt `
  --output data/processed/input_pressure_enhanced.h5 `
  --batch-size 128
```

`infer` 会从打包权重自动读取 `base_channels` 和 `residual_scale`，无需额外传参。
完整的输入数据转换、输出可视化和训练说明见
[`src/pressure_enhancement/README.md`](../src/pressure_enhancement/README.md)。
