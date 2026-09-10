# 压力图增强

本模块实现智能床垫压力图增强。目标是让躯干、髋部和大腿/小腿连接处等弱压力区域保持连续、可辨识的响应，同时抑制孤立传感器噪声和背景放大。

## 已完成工作

- 实现 `PaperPolishNetU`：8 层编码器/解码器、跳跃连接、上采样卷积和 `tanh` 输出。
- 接入预训练 OpenPose，在训练中生成 14 通道关节 Heatmap 与 28 通道 PAF 作为姿态监督。
- 使用真实 14 关节标注生成 `body_mask`，使人体区域的压力重建损失权重更高。
- 将单帧目标改为同一用户、同一动作连续帧的稳健压力 target：`0.7 × 时间中值 + 0.3 × 时间 75% 分位数`。生成 target 前应用 `3×3×3` 时空中值滤波并移除每段序列前 3 帧。
- 支持冻结 OpenPose 训练 PolishNetU、联合微调、测试集评估与 HDF5 批量导出。
- 已完成第一阶段权重 `checkpoints/paper_polish_frozen_target.pt`，以及 40 epoch 联合微调权重 `checkpoints/paper_polish_joint_target_final.pt`。
- 联合模型已在 3942 帧隔离测试集上完成评估：MPJPE 由 `6.469` 降至 `5.591` 像素，PCK@5% 由 `2.99%` 升至 `5.08%`。结果保存在 `reports/paper_target_metrics.json`，增强测试集保存在 `data/processed/paper_annotated/annotated_test_target_enhanced.h5`。

数据和模型权重不提交到 Git：`*.h5`、`*.pt` 均由 `.gitignore` 排除。代码、训练配置、指标 JSON 和模型说明在仓库中版本化；部署模型应作为 GitHub Release 附件或团队共享盘文件发放。

## 团队直接使用

团队成员无需准备关节标注、下载 OpenPose 或再次训练。只需从项目的 GitHub Release 或团队共享盘下载发布模型 `pressure_enhancement_v1.pt`，放到仓库根目录的 `models/` 下。该模型由 `paper_polish_joint_target_final.pt` 抽取而来，只保留 PolishNetU 的推理参数，不包含 OpenPose 和优化器状态。

发布模型的版本、输入输出约定和 SHA256 校验值记录在 `models/pressure_enhancement_v1.manifest.json`。当前版本模型大小约 53 MB，适合作为 GitHub Release 附件；不要将其直接提交到 Git 分支。

部署输入是一个 HDF5 文件，必须包含下列任意一个数据集：

```text
input_images 或 images: (N, 24, 44, 3)
```

图像可为 `float32` 的 Viridis RGB `[0, 1]`，或 `uint8` 的 Viridis RGB `[0, 255]`。推理不读取 `target_images`、`body_mask`、`joints` 或 `joint_valid`。

安装最小推理依赖后，直接执行：

```powershell
pip install torch numpy h5py matplotlib tqdm
```

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.pressure_enhancement.paper_pipeline export --input-h5 'data/processed/input_pressure_rgb.h5' --checkpoint 'models/pressure_enhancement_v1.pt' --output-h5 'data/processed/input_pressure_enhanced.h5' --comparison-output '..\压力增强对比图\部署结果\pressure_enhancement_comparison.png' --batch-size 128
```

输出 HDF5 包含 `images` 数据集，格式为 `(N, 24, 44, 3)` 的 `uint8` Viridis RGB。部署时仅加载 PolishNetU，因此 GPU 可用时会加速，CPU 也可以运行。

## 输入数据

论文流程使用 `data/processed/paper_annotated/` 中的数据集。每个 HDF5 文件包含：

```text
input_images  (N, 24, 44, 3)  原始压力图的 Viridis RGB 表示
target_images (N, 24, 44, 3)  多帧稳健统计得到的压力 target
body_mask     (N, 24, 44)     真实关节生成的软人体区域掩膜
joints        (N, 14, 2)      真实关节坐标，格式为 (x, y)
joint_valid   (N, 14)         关节有效标记
```

原始标注文件来自 `E:\workplace\数据集\关节位置\关节位置.json`。传感器一维流的正确布局为 `reshape(44, 24).T`；直接 `reshape(24, 44)` 会破坏人体轮廓。

## 使用指南

以下命令应在 `E:\workplace\Smart-Mattress-Project` 中执行。建议使用单行命令，避免 PowerShell 中反引号换行造成参数丢失。

### 1. 生成带稳健 target 的数据集

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.data_process.prepare_annotated_pressure_dataset --input-json 'E:\workplace\数据集\关节位置\关节位置.json' --output-dir 'data/processed/paper_annotated' --train-ratio 0.7 --seed 42
```

输出为 `annotated_train.h5`、`annotated_test.h5` 和 `annotated_manifest.json`。按用户进行 70/30 隔离划分，当前生成结果为训练集 9048 帧、测试集 3942 帧。

### 2. 第一阶段：冻结姿态网络训练 PolishNetU

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -u -m src.pressure_enhancement.paper_pipeline train-polish --train-h5 'data/processed/paper_annotated/annotated_train.h5' --checkpoint 'checkpoints/paper_polish_frozen_target.pt' --epochs 40 --batch-size 16
```

该阶段冻结自然图像预训练 OpenPose，仅更新 PolishNetU。像素重建对 `target_images` 计算，姿态损失保证输出对人体关节结构仍可识别。

### 3. 第二阶段：联合微调

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -u -m src.pressure_enhancement.paper_pipeline finetune --train-h5 'data/processed/paper_annotated/annotated_train.h5' --input-checkpoint 'checkpoints/paper_polish_frozen_target.pt' --checkpoint 'checkpoints/paper_polish_joint_target_final.pt' --epochs 40 --batch-size 16
```

此阶段同时更新 PolishNetU 和 OpenPose，完成后应以 `paper_polish_joint_target_final.pt` 作为当前版本的最终模型。

### 4. 评估与导出

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.pressure_enhancement.paper_pipeline evaluate --test-h5 'data/processed/paper_annotated/annotated_test.h5' --checkpoint 'checkpoints/paper_polish_joint_target_final.pt' --output 'reports/paper_target_metrics.json' --batch-size 16
```

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.pressure_enhancement.paper_pipeline export --input-h5 'data/processed/paper_annotated/annotated_test.h5' --checkpoint 'checkpoints/paper_polish_joint_target_final.pt' --output-h5 'data/processed/paper_annotated/annotated_test_target_enhanced.h5' --comparison-output '..\压力增强对比图\论文流程\paper_target_comparison.png' --batch-size 128
```

导出后的压力图保存在 HDF5，效果图保存在 `E:\workplace\压力增强对比图\论文流程`。

### 5. 独立生成可视化对比图

`visualize_enhancement.py` 可对已导出的 HDF5 重新筛选并生成对比图，无需再次运行模型推理。图中从左到右依次为原始压力图、PolishNetU 输出和增强幅度图；不使用 `--hide-target` 时会额外显示训练用的 `Clean target`。

下面的命令优先选择人体区域变化明显的 6 个样本。`--hide-target` 适合展示增强前后的直接差异：

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.pressure_enhancement.visualize_enhancement 'data/processed/paper_annotated/annotated_test.h5' 'data/processed/paper_annotated/annotated_test_target_enhanced.h5' --output '..\压力增强对比图\论文流程\paper_target_body_focused_6.png' --count 6 --selection body-focused --selection-page 0 --hide-target
```

训练核对时可移除 `--hide-target`，让图中增加稳健压力 target 一列：

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.pressure_enhancement.visualize_enhancement 'data/processed/paper_annotated/annotated_test.h5' 'data/processed/paper_annotated/annotated_test_target_enhanced.h5' --output '..\压力增强对比图\论文流程\paper_target_with_clean_target.png' --count 4 --selection body-focused --selection-page 0
```

可用参数：

- `--selection body-focused`：优先选择人体掩膜区域内变化大的样本，推荐用于展示躯干和四肢连接区域。
- `--selection largest-difference`：选择全图变化最大的样本，适合检查模型是否改变了背景。
- `--selection representative`：从整个测试集均匀抽取样本。
- `--selection-page N`：展示第 `N` 页强变化样本；分页会避开相邻重复帧，可用于输出多张不同的对比图。
- `--count N`：每张图包含的样本数量。

## 依赖与限制

安装项目依赖：`pip install -r requirements.txt`。训练姿态监督依赖 `controlnet-aux` 和其预训练 OpenPose 权重；首次运行会读取本地缓存或下载权重。CUDA 可用时训练自动使用 GPU。

当前主流程使用真实关节标注和多帧压力伪真值。它比“输入重建输入”可靠，但稳健 target 仍由传感器序列统计构造，不能视为独立测得的无噪声压力真值。

## 双模型关节门控融合

`ensemble_enhance_raw_sleep.py` 同时运行最终论文流程模型
`pressure_enhancement_v1.pt` 和强增强模型
`annotated_pressure_strong_v0.pt`。两路模型均以原始压力图为输入，不会将一个模型的输出
传给另一个模型。脚本依据真实 14 关节坐标构建软掩膜，只在躯干、髋部和四肢连接区域保留
有上限的正向增强残差。

在仓库根目录执行以下单行命令。先使用 `--max-samples 200` 检查生成的对比图，确认关节
掩膜覆盖正确后，再将其改为 `0` 处理全部样本：

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.pressure_enhancement.ensemble_enhance_raw_sleep --input-json 'data/raw/睡姿 区域划分data/区域划分/data.json' --keypoints-json 'E:\workplace\数据集\关节位置\关节位置.json' --v1-checkpoint 'models/pressure_enhancement_v1.pt' --strong-checkpoint 'models/annotated_pressure_strong_v0.pt' --output-h5 'data/processed/raw_sleep_ensemble_enhanced.h5' --comparison-output '..\压力增强对比图\融合模型\ensemble_comparison.png' --max-samples 200 --batch-size 128
```

输出 HDF5 具有以下数据集：

```text
input_images       原始 Viridis RGB 压力图
v1_images          v1 的结构保持输出
strong_images      强增强模型输出
enhanced_images    真实关节门控后的最终融合图
enhancement_mask   用于融合的软掩膜
```

默认融合权重为 `v1=0.15`、`strong=0.85`，强模型推理强度为 `2.0`，正向增益上限为 `0.75`。
默认 `--gate-threshold 0.20` 会移除软掩膜低置信度边缘，确保背景保持原始压力值。
若躯干仍不够明显，可将 `--strong-weight` 调至 `0.9`；若边缘过硬，可将
`--gate-threshold` 降至 `0.15`，调整后应先复查对比图。

若只使用 `pressure_enhancement_v1.pt` 消除背景模糊，加入 `--v1-only`。该模式不加载强增强模型，
只在真实关节掩膜内使用 v1 输出，掩膜外逐像素保留原始压力：

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.pressure_enhancement.ensemble_enhance_raw_sleep --input-json 'data/raw/睡姿 区域划分data/区域划分/data.json' --keypoints-json 'E:\workplace\数据集\关节位置\关节位置.json' --v1-checkpoint 'models/pressure_enhancement_v1.pt' --output-h5 'data/processed/raw_sleep_v1_body_only.h5' --comparison-output '..\压力增强对比图\融合模型\v1_body_only_comparison.png' --max-samples 200 --batch-size 128 --v1-only --gate-threshold 0.20
```
