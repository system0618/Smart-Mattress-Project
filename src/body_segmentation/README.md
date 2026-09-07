# Body Segmentation

身体部位划分模块。课程要求为：

- 对原始压力数据进行增强处理。
- 数据集按 70% 训练集、30% 验证集划分,验证集准确率目标大于 95%。
- 面对新用户数据时准确率目标大于 70%。
- 前端需要展示不同睡姿下的身体区域划分效果。

输出类别(以数据集实际标注为准,共 6 类):

| id | 类别 | 说明 |
| --- | --- | --- |
| 0 | background | 背景/无压力 |
| 1 | shoulder | 肩部 |
| 2 | back | 背部 |
| 3 | waist | 腰部 |
| 4 | hip | 臀部 |
| 5 | thigh | 大腿部 |

> 小腿部仅前 3 人标注(其余为 na),不使用。区域划分数据集已包含左右对称翻转样本,数据增强时禁止再翻转。

## 数据准备

1. 将数据集压缩包中的 `区域划分2026(30人).json` 解压到 `data/raw/`(保持原始目录结构即可,脚本会自动查找)。
2. 解析并生成 HDF5 + manifest:

```bash
python -m src.body_segmentation.dataset \
  --json "data/raw/睡姿 区域划分data/区域划分/区域划分2026（30人）.json" \
  --out data/processed/segmentation
```

产物:

- `data/processed/segmentation/dataset.h5`:images/masks 数组
- `data/processed/segmentation/manifest.json`:元信息 + 样本级/用户级两种划分

## 训练

```bash
# 用户级划分(新用户泛化口径,验收指标 2)
python -m src.body_segmentation.train --data-dir data/processed/segmentation --split user

# 样本级 70/30 划分(验收指标 1)
python -m src.body_segmentation.train --data-dir data/processed/segmentation --split sample
```

常用参数:`--epochs 100 --batch-size 64 --lr 1e-3 --patience 15 --device cuda`。

## 评估

```bash
python -m src.body_segmentation.evaluate \
  --data-dir data/processed/segmentation \
  --model-path src/body_segmentation/models/best.pt
```

两个口径(样本级/用户级)都会评估,输出像素准确率、mIoU、每类 precision/recall/F1、按睡姿分组指标与混淆矩阵,保存到 `data/processed/segmentation/evaluation_metrics.json`。

## 前端导出

```bash
python -m src.body_segmentation.export \
  --data-dir data/processed/segmentation \
  --model-path src/body_segmentation/models/best.pt
```

按 `docs/api_docs.md` 约定输出 segmentation JSON 与效果图到 `data/processed/segmentation/export/`。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `dataset.py` | JSON 流式解析、region→mask、清洗、双口径划分 |
| `augment.py` | 在线增强(噪声/平移/扰动/Cutout,无翻转) |
| `unet.py` | UNet 分割模型 |
| `train.py` | 训练入口(加权 CE + Dice) |
| `evaluate.py` | 双口径评估入口 |
| `visualize.py` | 热力图+区域叠加渲染 |
| `export.py` | 前端对接数据导出 |

完整设计与实现细节见 `资料/身体部位划分算法实现方案.md`。
