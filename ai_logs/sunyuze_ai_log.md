# 孙瑜泽 AI 协同开发记录

## 记录格式

```markdown
## YYYY-MM-DD

### 使用工具

### 提问或任务

### AI 输出摘要

### 采纳内容

### 人工修改与验证
```

## 2026-09-02

### 使用工具

代码浏览与补丁编辑工具。

### 提问或任务

实现智能床垫压力数据的时空去噪、Viridis 彩色映射、水平翻转增强，以及按用户 70/30 划分并保存的预处理脚本。

### AI 输出摘要

新增 `src/data_process/preprocess.py`：支持 NumPy、CSV/TXT/DAT 和 MAT 输入；按用户划分数据；使用 3x3x3 中值滤波和 Viridis RGB 映射；仅增强训练集并保存 `train_images.npy`、`test_images.npy` 与 `manifest.json`。

### 采纳内容

采用按用户划分策略，避免增强样本泄漏到测试集，并记录样本来源和增强类型。

### 人工修改与验证

完成静态代码检查和 Git 空白检查。后续确认本机已安装 Python 3.12，并在 CUDA 环境完成运行时训练验证。

## 2026-09-03

### 使用工具

Python、NumPy、SciPy、Matplotlib、h5py、PyTorch，以及代码浏览与补丁编辑工具。

### 提问或任务

修复原始压力序列的维度不一致问题，并将预处理结果改为适合大规模数据的 HDF5 落盘格式。

### AI 输出摘要

更新 `src/data_process/preprocess.py`：从每个多帧压力序列中去除前 3 个过渡帧，再沿时间轴拆分为单帧；以文件父目录名作为用户标识，随机按用户 70/30 划分训练集和测试集；使用 h5py 分批追加写入，避免百万帧数据在 `numpy.stack` 时占满内存。

### 采纳内容

采用按用户划分而非按帧随机划分的策略，避免同一用户的相邻帧同时进入训练集和测试集。输出文件为 `data/processed/train_data.h5`、`data/processed/test_data.h5` 和 `manifest.json`。

### 人工修改与验证

预处理数据已成功落盘为 HDF5。生成文件和后续模型权重均由 `.gitignore` 排除，不纳入版本控制。

## 2026-09-04

### 使用工具

PyTorch、h5py、CUDA、Ultralytics YOLOv8-Pose、tqdm，以及代码浏览与补丁编辑工具。

### 提问或任务

实现 PolishNetU 训练管道，并尝试为压力图生成 Heatmap 和 PAF 姿态伪标签。

### AI 输出摘要

更新 `src/pressure_enhancement/enhance.py`：实现 HDF5 懒加载数据集、单进程 DataLoader、8 层编码器和解码器、跳跃连接、tanh 输出、热力图/PAF/像素复合损失、Adam 优化器、每 10 个 epoch 衰减一次的 StepLR，以及最终权重保存到 `checkpoints/polishnetu_final.pt`。新增 `src/data_process/generate_pseudo_labels.py`：使用 YOLOv8-Pose 在 CUDA 上批量推理，将 COCO 17 关节映射为 14 关节，并生成 14 通道 Heatmap 与 28 通道 PAF。

### 采纳内容

数据集在未提供真实标签时返回形状匹配的零值 Heatmap 和 PAF 占位张量；存在真实 HDF5 标签时读取对应数据集。伪标签脚本支持 `--max-samples` 生成独立原型 HDF5 文件，避免小样本试验覆盖全量数据。

### 人工修改与验证

确认 PyTorch 已启用 CUDA，并完成 40 个 epoch 的训练运行，模型权重成功保存。对 100 帧原型集运行 YOLOv8-Pose 后，未产生有效人体关键点；因此伪标签脚本的写入流程已验证，但当前低分辨率 Viridis 压力图与 COCO RGB 姿态模型存在明显域差异，生成的全零标签不能作为真实姿态监督使用。

## 2026-09-05

### 使用工具

本地文件检索、文献检索与网页搜索工具。

### 提问或任务

核对公开 PmatData 数据集是否包含论文所用的关节标注，并准备向论文作者请求数据的邮件。

### AI 输出摘要

检查下载的 `a-pressure-map-dataset-for-in-bed-posture-classification-1.0.0`：其中包含压力矩阵 `.txt`、受试者信息 `.csv` 和实验说明 `.docx`，未发现关节坐标、关键点、Heatmap 或 PAF 标注文件。文献说明作者曾为 18,256 个 PmatData 样本人工标注 14 个关节，但该标注未随 PhysioNet 原始数据公开发布。已生成英文邮件草稿，请求非商业学术用途的标注、关节顺序、坐标约定和样本索引映射。

### 采纳内容

暂停对全量压力图执行 COCO 模型伪标注，优先联系论文作者获取真实标注；若无法取得，将另行设计人工标注或采用带同步视觉/动作捕捉真值的数据集。

### 人工修改与验证

使用 Python 3.12 对 `utils.py`、`preprocess.py`、`enhance.py` 和 `generate_pseudo_labels.py` 进行 `py_compile` 语法检查，通过；`numpy`、`scipy`、`h5py` 与 `torch` 可正常导入。`requirements.txt` 已补充 `h5py>=3.10` 和 `ultralytics>=8.3`。
