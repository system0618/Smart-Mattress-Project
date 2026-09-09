# 压力图增强

论文复现入口为 `src.pressure_enhancement.paper_pipeline`。该流程不使用人工构造的
亮度目标、推理倍增或关节区域门控，而是让 PolishNetU 通过预训练 OpenPose 的
Heatmap/PAF 损失学习图像域表示。

## 数据准备

下面的命令会按用户划分数据，删除每个动作序列的前 3 帧，应用 `3x3x3` 时空
中值滤波，并使用固定范围的 Viridis 色图生成 HDF5：

```powershell
python -m src.data_process.prepare_annotated_pressure_dataset `
  --input-json "E:\workplace\数据集\关节位置\关节位置.json" `
  --output-dir data/processed/paper_annotated `
  --train-ratio 0.7 `
  --seed 42
```

## 论文主流程

先冻结原始自然图像预训练 OpenPose，只训练 PolishNetU。像素损失权重从 1
线性降至 0.01：

```powershell
python -m src.pressure_enhancement.paper_pipeline train-polish `
  --train-h5 data/processed/paper_annotated/annotated_train.h5 `
  --checkpoint checkpoints/paper_polish_frozen_pose.pt `
  --epochs 40 `
  --batch-size 16
```

再联合微调 PolishNetU 和 OpenPose，这是论文效果最好的配置：

```powershell
python -m src.pressure_enhancement.paper_pipeline finetune `
  --train-h5 data/processed/paper_annotated/annotated_train.h5 `
  --input-checkpoint checkpoints/paper_polish_frozen_pose.pt `
  --checkpoint checkpoints/paper_polish_joint_final.pt `
  --epochs 40 `
  --batch-size 16
```

`train-pose` 是论文“仅重训练姿态估计器”方案的独立对照实验，不是主流程的
前置步骤。需要复现实验对照时单独运行：

```powershell
python -m src.pressure_enhancement.paper_pipeline train-pose `
  --train-h5 data/processed/paper_annotated/annotated_train.h5 `
  --checkpoint checkpoints/paper_pose_retrained.pt `
  --epochs 40 `
  --batch-size 16
```

## 评估与导出

```powershell
python -m src.pressure_enhancement.paper_pipeline evaluate `
  --test-h5 data/processed/paper_annotated/annotated_test.h5 `
  --checkpoint checkpoints/paper_polish_joint_final.pt `
  --output reports/paper_pressure_enhancement_metrics.json `
  --batch-size 16

python -m src.pressure_enhancement.paper_pipeline export `
  --input-h5 data/processed/paper_annotated/annotated_test.h5 `
  --checkpoint checkpoints/paper_polish_joint_final.pt `
  --output-h5 data/processed/paper_annotated/annotated_test_enhanced.h5 `
  --comparison-output ../压力增强对比图/论文流程/paper_final_comparison.png `
  --batch-size 128
```

预训练 OpenPose 权重来自 ControlNet 的 PyTorch 转换版本，继承 OpenPose 的
非商业许可。第一次运行 `train-pose` 时会下载约 200 MB 权重。
