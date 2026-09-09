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

新增 `src/data_process/preprocess.py`：支持 NumPy、CSV/TXT/DAT 和 MAT 输入；按用户划分数据；使用 3x3x3 中值滤波和 Viridis RGB 映射；仅增强训练集并保存数据集清单。

### 采纳内容

采用按用户划分策略，避免增强样本泄漏到测试集，并记录样本来源和增强类型。

### 人工修改与验证

完成静态代码检查和 Git 空白检查；确认本机安装 Python 3.12，并在 CUDA 环境完成运行时训练验证。

## 2026-09-03

### 使用工具

Python、NumPy、SciPy、Matplotlib、h5py、PyTorch，以及代码浏览与补丁编辑工具。

### 提问或任务

修复原始压力序列维度不一致问题，并将预处理结果改为适合大规模数据的 HDF5 落盘格式。

### AI 输出摘要

更新 `src/data_process/preprocess.py`：去除每段序列前 3 个过渡帧，再沿时间轴拆分为单帧；以文件父目录名作为用户标识，随机按用户 70/30 划分训练集和测试集；使用 h5py 分批追加写入，避免百万帧数据在 `numpy.stack` 时占满内存。

### 采纳内容

采用按用户而非按帧随机划分的策略，避免同一用户的相邻帧同时进入训练集和测试集。输出为 `data/processed/train_data.h5`、`data/processed/test_data.h5` 和 `manifest.json`。

### 人工修改与验证

预处理数据已成功落盘为 HDF5；生成文件和后续模型权重均由 `.gitignore` 排除，不纳入版本控制。

## 2026-09-04

### 使用工具

PyTorch、h5py、CUDA、Ultralytics YOLOv8-Pose、tqdm，以及代码浏览与补丁编辑工具。

### 提问或任务

实现 PolishNetU 训练管道，并尝试为压力图生成 Heatmap 和 PAF 姿态伪标签。

### AI 输出摘要

更新 `src/pressure_enhancement/enhance.py`：实现 HDF5 懒加载数据集、单进程 DataLoader、8 层编码器和解码器、跳跃连接、tanh 输出、热图/PAF/像素复合损失、Adam、StepLR 和模型权重保存。新增 `src/data_process/generate_pseudo_labels.py`：使用 YOLOv8-Pose 在 CUDA 上推理，将 COCO 17 关节映射到 14 关节，并生成 Heatmap 和 PAF。

### 采纳内容

数据集在缺少真实标签时返回形状匹配的零值 Heatmap 和 PAF 占位张量；存在真实 HDF5 标签时读取对应数据集。伪标签脚本支持 `--max-samples`，可先在原型数据上验证。

### 人工修改与验证

确认 PyTorch 已启用 CUDA，并完成 40 epoch 训练运行，模型权重成功保存。对 100 帧原型集运行 YOLOv8-Pose 未产生有效人体关键点，说明低分辨率 Viridis 压力图与 COCO RGB 姿态模型存在显著域差异；伪标签写入流程已验证，但全零结果不能作为真实姿态监督使用。

## 2026-09-05 (数据集调研)

### 使用工具

本地文件检索、文献检索与网页搜索工具。

### 提问或任务

核对公开 PmatData 数据集是否包含论文所用关节标注，并准备向论文作者请求数据的邮件。

### AI 输出摘要

检查下载的 `a-pressure-map-dataset-for-in-bed-posture-classification-1.0.0`：其中包含压力矩阵 `.txt`、受试者信息 `.csv` 和实验说明 `.docx`，未发现关节坐标、关键点、Heatmap 或 PAF 标注文件。文献说明作者曾为 18,256 个 PmatData 样本人工标注 14 个关节，但标注未随 PhysioNet 原始数据公开发布。已生成英文邮件草稿，请求非商业学术用途的标注、关节顺序、坐标约定和样本索引映射。

### 采纳内容

暂停对全量压力图执行 COCO 模型伪标注，优先联系论文作者获取真实标注；若无法取得，将设计人工标注或采用带同步视觉/动作捕捉真值的数据集。

### 人工修改与验证

使用 Python 3.12 对 `utils.py`、`preprocess.py`、`enhance.py` 和 `generate_pseudo_labels.py` 执行 `py_compile`，通过；`numpy`、`scipy`、`h5py` 与 `torch` 可正常导入。

## 2026-09-05 (SLP 配对去噪)

### 使用工具

Python 3.12、NumPy、SciPy、Matplotlib、h5py、PyTorch CUDA、tqdm，以及代码浏览与补丁编辑工具。

### 提问或任务

将原先的“输入图像重建输入图像”训练方式改为有明确监督目标的压力图去噪增强流程，并利用已下载的 SLP 数据集完成训练和测试。

### AI 输出摘要

新增 `src/data_process/prepare_slp_denoising_dataset.py`：从 SLP `PMarray` 读取压力帧，以 3x3 空间中值滤波结果作为干净目标；在保留原始噪声基础上模拟读出噪声、稀疏尖峰、局部失效块和偶发整行失效，生成退化输入。输入与目标使用同一帧的压力范围转换为 Viridis RGB，避免归一化掩盖噪声差异。数据按受试者划分为 71 名训练、31 名测试，训练集仅增加水平翻转样本。

更新 `src/pressure_enhancement/enhance.py`：Dataset 支持 `input_images`/`target_images` 配对数据；像素 MSE 改为输出对干净目标而非输入计算。网络输出改为残差形式并以恒等映射初始化，避免从零重建整幅压力图；成对去噪时像素损失权重从 1 衰减到 0.5，Heatmap 和 PAF 辅助损失权重各为 0.1。新增 `infer.py`、`visualize_enhancement.py` 和 `evaluate_denoising.py` 用于批量推理、三方图像对比和量化评估。

### 采纳内容

全量生成 `data/processed/slp_denoise_train.h5`（19,170 帧）和 `slp_denoise_test.h5`（4,185 帧），均含退化输入、干净目标及真实 14 关节坐标。完成 10 epoch CUDA 训练，模型保存为 `checkpoints/polishnetu_denoise_v1.pt`；增强测试集保存为 `data/processed/slp_denoise_test_enhanced.h5`。

### 人工修改与验证

原型训练验证了改动必要性：旧直接输出结构在未见受试者上使 MAE 恶化；残差结构和损失权重调整后，原型 MAE 改善 14.75%。全量隔离测试集上，退化输入相对干净目标的 MAE 为 6.306/255、MSE 为 511.612；模型输出的 MAE 为 4.361/255、MSE 为 278.065，分别改善 30.84% 和 45.65%。对比图位于 `data/processed/visualizations/slp_denoise_test_comparison.png`，评估报告位于 `reports/slp_denoise_metrics.json`。新增或修改的 Python 文件均通过 `py_compile` 与 Git 空白检查。

## 2026-09-05 (SLP 姿态域适配)

### 使用工具

Python 3.12、PyTorch CUDA、h5py、OpenCV、NumPy、Matplotlib，以及代码浏览与补丁编辑工具。

### 提问或任务

按照 PolishNetU 论文的核心思想，改为“压力图 -> PolishNetU -> 冻结的 RGB 姿态估计器”的域适配训练，而不是让网络直接重建压力图。

### AI 输出摘要

新增 `src/data_process/prepare_slp_pose_adaptation_dataset.py`：读取 SLP 同步 PMarray、RGB 和 14 关节标注，使用 `align_PTr_RGB.npy` 将 RGB 图像与关节投影到压力垫坐标系，按受试者 70/30 划分训练集和测试集。新增 `src/pressure_enhancement/pose_adaptation.py`：先在对齐 RGB 上训练输出 14 个 Heatmap 和 28 个 PAF 的轻量姿态网络，再冻结其参数，以姿态损失和逐步衰减的像素保真损失共同训练 PolishNetU。新增 `visualize_pose_adaptation.py` 输出压力图、增强结果、差异图和对齐 RGB 参考图。

### 采纳内容

全量生成 `slp_pose_adapt_train.h5`（19,170 帧）和 `slp_pose_adapt_test.h5`（4,185 帧）。完成 RGB 姿态网络 16 epoch 预训练，权重为 `checkpoints/rgb_pose_slp_v1.pt`；完成 PolishNetU 8 epoch CUDA 适配训练，权重为 `checkpoints/polishnetu_pose_adapt_slp_v1.pt`。测试集增强输出保存为 `data/processed/slp_pose_adapt_test_polished.h5`，指标报告为 `reports/slp_pose_adaptation_metrics.json`，对比图为 `reports/slp_pose_adaptation_comparison.png`。

### 人工修改与验证

隔离测试受试者上，冻结 RGB 姿态网络直接处理压力图时 MPJPE 为 65.55 px、PCK@5% 为 1.78%；经 PolishNetU 后 MPJPE 降至 35.65 px、PCK@5% 升至 26.92%，可见关节数均为 58,305。对比图显示输出仍有条纹伪影：这是以轻量自训姿态网络替代论文中成熟 RGB 姿态估计器后出现的对抗性域适配现象，因此该实验验证了姿态监督链路与指标收益，但不能宣称已复现论文的视觉效果。新增 Python 文件已通过 `py_compile` 检查。

## 2026-09-05 (弱压力区域增强调整)

### 提问或任务

最终目标确定为增强压力传感器捕获的人体弱压力区域，尤其是躯干以及大腿与小腿连接处，而不是追求 RGB 外观迁移。

### 采纳内容

更新 `src/pressure_enhancement/enhance.py`：默认关闭姿态网络主监督；保留真实关节生成的 Heatmap/PAF 作为软人体区域掩膜，对人体区域加权重建损失，并增加弱信号增益约束、Charbonnier 损失和总变差平滑损失。残差幅度限制为 0.1，像素损失下限保持 0.5，避免背景放大和条纹伪影。

### 人工修改与验证

使用 64 帧原型集完成 CUDA 训练验证，损失正常下降并成功保存 `checkpoints/polishnetu_weak_region_prototype.pt`。已停止不包含该目标的旧版全量训练，后续全量训练应使用新的弱区域参数。

全量 5 epoch 训练完成，模型保存为 `checkpoints/polishnetu_weak_region_v1.pt`；测试集输出为 `data/processed/slp_denoise_test_weak_region.h5`，对比图为 `reports/slp_weak_region_comparison.png`。输出保持压力图的 Viridis 结构，并通过关节软掩膜提高躯干及四肢连接区域的训练权重。

## 2026-09-05（真实关节标注压力增强修复）

### 任务

使用 `E:\workplace\数据集\关节位置\关节位置.json` 中的 24x44 压力数据和 14 关节真实标注，修复增强结果没有人形的问题，并接入 PolishNetU 的 Heatmap/PAF 姿态辅助监督。

### 完成内容

确认原始 1056 点传感器流不能直接执行 `reshape(24, 44)`；正确的传感器布局为 `reshape(44, 24).T`。错误布局会把人体压力分布变成斜条纹。更新 `prepare_annotated_pressure_dataset.py`，按用户进行 70/30 划分，生成 9,930 个训练样本和 4,320 个测试样本，并保存输入图、去噪目标、人体软掩膜、14 关节坐标及有效标记。

更新 `train_annotated.py`，从 HDF5 读取真实关节坐标，在 GPU 上动态生成 14 通道高斯 Heatmap 和 28 通道 PAF；训练损失同时包含压力区域加权重建、弱信号增益、Charbonnier、TV、Heatmap MSE 和 PAF MSE。保留受限残差输出，防止背景整体放大。

### 验证

相关 Python 文件通过 `py_compile`。HDF5 形状为 `input_images=(9930,24,44,3)`、`joints=(9930,14,2)`，关节有效率约 95.6%。CUDA 小样本端到端训练完成，训练损失 0.03232、测试损失 0.03045，并成功保存及导出。布局诊断图位于 `src/pressure_enhancement/compare/raw_layout_diagnostic.png`，小样本输出对比图位于 `src/pressure_enhancement/compare/annotated_test_comparison_smoke.png`；修复后的图中已能看到头、躯干和四肢轮廓。
## 2026-09-07 论文方法对齐

重新核对论文《Estimating pose from pressure data for smart beds with deep image-based pose estimators》的方法与实验设置。确认明显人体轮廓来自 PolishNetU 与姿态估计器的图像域适配，而不是人工亮度目标、残差倍增或推理关节门控。

修复 14 关节骨架拓扑：当前数据的顺序为头、颈、左/右肩、左/右肘、左/右腕、左/右髋、左/右膝、左/右踝，旧代码错误沿用了 SLP/Leeds 顺序，导致 PAF 肢体连接错误。

新增 `src/pressure_enhancement/paper_pipeline.py`：接入 52.31M 参数的预训练 OpenPose，映射为 14 通道 Heatmap 和 28 通道 PAF；实现 13.27M 参数、8 层编码/解码及 tanh 输出的 PolishNetU；实现可见性掩码 MSE、像素 MSE 从 1 衰减到 0.01、Adam 1e-3、每 1000 步衰减 0.95。论文主流程先冻结原始自然图像 OpenPose 训练 PolishNetU，再联合微调两者；单独重训练姿态网络只作为论文方案 (ii) 的对照实验。评估包含 3x3 高斯平滑、水平翻转测试、MPJPE 和 PCK@5%。

修复混合精度损失归约：batch size 16 时掩码计数超过 float16 最大有限值会使损失静默变为 0，现强制使用 FP32 归约。三阶段训练均已使用 CUDA、batch size 16 完成小样本冒烟验证。

更新标注数据预处理：按用户/动作序列删除前 3 帧，应用 3x3x3 时空中值滤波，使用全数据固定 Viridis 范围 0-286。生成 `data/processed/paper_annotated/annotated_train.h5`（9048 帧）和 `annotated_test.h5`（3942 帧），按用户 70/30 隔离。正式 40 epoch 训练尚未执行，冒烟 checkpoint 与效果不能作为正式结果。
