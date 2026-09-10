# 数据处理

本模块负责压力数据读取、清洗、按用户划分、HDF5 落盘，以及为压力增强生成真实关节和稳健压力 target。

## 已完成工作

- `preprocess.py`：遍历 NumPy、CSV、TXT、DAT 和 MAT 原始压力数据；删除每段序列前 3 帧；执行 `3×3×3` 时空中值滤波；按用户 70/30 划分；生成 Viridis RGB HDF5 数据集并在训练集使用水平翻转。
- `prepare_annotated_pressure_dataset.py`：读取真实 14 关节标注 JSON；恢复 1056 个传感器点的正确 `24×44` 物理布局；生成软人体掩膜；为每个序列生成 `0.7 × 中值 + 0.3 × 75% 分位数` 的多帧稳健压力 target。
- `generate_pseudo_labels.py`：保留 YOLOv8-Pose 伪标签生成工具，用于无真实标注的原型实验。当前低分辨率 Viridis 压力图与 COCO RGB 姿态模型存在域差异，正式压力增强训练优先使用真实关节 JSON。
- `split_dataset.py`：对普通文件数据集生成可复现的 70/30 文件级划分；需要严格防止用户泄漏时，应优先使用各算法模块的用户级划分逻辑。

数据、HDF5 和 NumPy 大文件由 `.gitignore` 排除，生成后保留在本地 `data/processed/`。

## 使用指南

### 通用原始压力预处理

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.data_process.preprocess --input-dir 'data/raw' --output-dir 'data/processed' --train-ratio 0.7 --seed 42
```

输出为 `train_data.h5`、`test_data.h5` 和 `manifest.json`。

### 真实关节标注压力数据准备

压力增强主流程使用下面的命令：

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.data_process.prepare_annotated_pressure_dataset --input-json 'E:\workplace\数据集\关节位置\关节位置.json' --output-dir 'data/processed/paper_annotated' --train-ratio 0.7 --seed 42
```

输出 HDF5 包含 `input_images`、`target_images`、`body_mask`、`joints` 和 `joint_valid`，供 `src.pressure_enhancement.paper_pipeline` 训练使用。

### 通用文件切分

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.data_process.split_dataset --input-dir 'data/raw/example' --output-dir 'data/splits/example' --test-size 0.3 --seed 42
```

该脚本会复制文件，因此对大型原始数据集应确保目标磁盘空间充足。
