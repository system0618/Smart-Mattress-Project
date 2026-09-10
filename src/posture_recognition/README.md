# 睡姿识别

本模块根据床垫的单帧压力矩阵识别睡姿。输入数据来自 `data.json`，每条记录包含 `44×24` 压力图、用户标识、动作序列和 `sleep_pos` 标签。当前数据集中有 4 个实际睡姿类别。

## 已完成工作

- 实现数据读取与用户级 70/30 训练/测试划分，避免同一用户相邻帧同时进入训练集与测试集。
- 实现压力图统计特征提取。
- 实现 RBF SVM、类别平衡随机森林和轻量 CNN 三种分类算法。
- 实现 CNN 的随机幅值扰动与高斯噪声增强。
- 实现 Accuracy、Macro Precision、Macro Recall、Macro F1、分类报告和混淆矩阵评估。

当前模块已具备训练与评估代码，但 `src/posture_recognition/models/` 中尚未保存正式训练完成的 `svm.joblib`、`random_forest.joblib` 或 `cnn.pt`。模型文件同样不应直接提交 Git；训练后应以 Release 附件或团队共享盘方式保存。

## 使用指南

以下命令在 `E:\workplace\Smart-Mattress-Project` 中执行。数据文件为：

```text
data/raw/睡姿 区域划分data/区域划分/data.json
```

### SVM 基线

训练：

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.posture_recognition.train --json 'data/raw/睡姿 区域划分data/区域划分/data.json' --model-dir 'src/posture_recognition/models' --algorithm svm --seed 42
```

评估：

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.posture_recognition.evaluate --json 'data/raw/睡姿 区域划分data/区域划分/data.json' --model-path 'src/posture_recognition/models/svm.joblib' --algorithm svm --seed 42
```

### 随机森林对照模型

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.posture_recognition.train --json 'data/raw/睡姿 区域划分data/区域划分/data.json' --model-dir 'src/posture_recognition/models' --algorithm random_forest --seed 42
```

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.posture_recognition.evaluate --json 'data/raw/睡姿 区域划分data/区域划分/data.json' --model-path 'src/posture_recognition/models/random_forest.joblib' --algorithm random_forest --seed 42
```

### CNN

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -u -m src.posture_recognition.train --json 'data/raw/睡姿 区域划分data/区域划分/data.json' --model-dir 'src/posture_recognition/models' --algorithm cnn --epochs 30 --device auto --seed 42
```

```powershell
& 'C:\Users\system0618\AppData\Local\Programs\Python\Python312\python.exe' -m src.posture_recognition.evaluate --json 'data/raw/睡姿 区域划分data/区域划分/data.json' --model-path 'src/posture_recognition/models/cnn.pt' --algorithm cnn --device auto --seed 42
```

训练会额外生成 `<algorithm>_split.json`，记录用户划分、样本数量、随机种子和测试索引，以便后续复现实验。

## 与压力增强的衔接

当前 SVM、随机森林和 CNN 都接收单通道 `44×24` 压力矩阵。压力增强模块导出的 Viridis RGB 图不能直接作为本模块输入；整合时应保留或从增强结果恢复对应的单通道压力值，再送入睡姿分类器。
