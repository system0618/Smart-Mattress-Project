# 姿态识别模型使用说明

本目录保存 `src.posture_recognition` 模块训练得到的睡姿分类模型。模型输入为单帧 `44 x 24` 压力矩阵，输出为睡姿类别 ID。

## 模型文件

| 文件 | 算法 | 推荐用途 |
| --- | --- | --- |
| `cnn.pt` | 轻量卷积神经网络 | 默认部署模型，泛化效果最佳 |
| `svm.joblib` | RBF SVM | 传统机器学习基线或无需 PyTorch 的环境 |
| `random_forest.joblib` | 随机森林 | 传统机器学习对比实验 |
| `*_split.json` | 训练划分元数据 | 查看数据来源、随机种子和训练/测试受试者 |
| `cnn_test_metrics.json` | CNN 测试指标 | 查看 CNN 的分类报告和混淆矩阵 |

当前训练集包含 13,140 帧、20 位受试者。按照受试者进行 70%/30% 划分，以避免同一受试者同时出现在训练和测试中。

| 模型 | 测试准确率 | Macro F1 |
| --- | ---: | ---: |
| CNN | 98.66% | 98.66% |
| SVM | 87.62% | 87.79% |
| 随机森林 | 86.76% | 86.96% |

## 类别定义

本批数据实际包含以下四类；模型输出 ID 与类别名称的映射如下。

| ID | 名称 | 含义 |
| ---: | --- | --- |
| 0 | `supine` | 仰卧 |
| 1 | `prone` | 俯卧 |
| 2 | `left_lateral` | 左侧卧（采集动作 10–15） |
| 3 | `right_lateral` | 右侧卧（采集动作 16–21） |

类别顺序来自采集协议与 `data.json` 中 `action → sleep_pos` 的对应关系：动作 1–6 →
标签 0、7–9 → 1、10–15 → 2、16–21 → 3，`action → sleep_pos` 的映射详见
`图片和附件/睡姿采集2026.docx`。参考论文最多支持 6 类，代码中另预留了
`unknown_4`、`unknown_5` 两个类别位，但当前数据没有对应样本，模型不能识别。

注意：`cnn.pt` 内的 `classes` 字段是训练时写入的旧名称（`left_extended` /
`left_fetal` 等），只作元数据保留，**不要用它做标签名映射**。权威映射见
`src/posture_recognition/dataset.py` 的 `POSTURE_NAMES` 与
`src/posture_recognition/infer.py` 的 `CLASS_NAMES`。

## 使用 CNN

从仓库根目录运行。输入矩阵必须是数值型的 `numpy.ndarray`，形状为 `(44, 24)`；单帧会按自身最小值和最大值归一化，这与训练阶段一致。

```python
from pathlib import Path

import numpy as np
import torch

from src.posture_recognition.models import TinyPostureCNN
from src.posture_recognition.train import normalize

model_path = Path("src/posture_recognition/models/cnn.pt")
device = "cuda" if torch.cuda.is_available() else "cpu"
checkpoint = torch.load(model_path, map_location=device, weights_only=True)

model = TinyPostureCNN(num_classes=4).to(device)
model.load_state_dict(checkpoint["model_state"])
model.eval()

pressure_frame = np.zeros((44, 24), dtype=np.float32)  # 替换为传感器数据
input_tensor = torch.from_numpy(normalize(pressure_frame[None, ...])).unsqueeze(1).to(device)

with torch.no_grad():
    label_id = int(model(input_tensor).argmax(dim=1).item())

from src.posture_recognition.infer import CLASS_NAMES

label_name = CLASS_NAMES[label_id]   # checkpoint["classes"] 是训练时的旧名称，勿用
print(label_id, label_name)
```

## 使用传统模型

SVM 和随机森林使用人工提取的压力分布特征，不能直接将展平后的矩阵传入模型。请使用项目的 `extract_features` 函数。

```python
from pathlib import Path

import joblib
import numpy as np

from src.posture_recognition.features import extract_features

artifact = joblib.load(Path("src/posture_recognition/models/svm.joblib"))
pressure_frame = np.zeros((44, 24), dtype=np.float32)  # 替换为传感器数据

label_id = int(artifact["model"].predict(extract_features(pressure_frame))[0])
label_name = CLASS_NAMES[label_id]   # 同上，artifact["classes"] 为旧名称
print(label_id, label_name)
```

将路径改为 `random_forest.joblib` 即可加载随机森林模型。

## 重新训练

在仓库根目录安装依赖后，使用原始标注数据重新训练。训练会覆盖同名模型及其 `*_split.json` 文件。

```powershell
python -m src.posture_recognition.train --json "data/raw/睡姿 区域划分data/区域划分/data.json" --algorithm cnn --epochs 30
python -m src.posture_recognition.train --json "data/raw/睡姿 区域划分data/区域划分/data.json" --algorithm svm
python -m src.posture_recognition.train --json "data/raw/睡姿 区域划分data/区域划分/data.json" --algorithm random_forest
```

默认使用随机种子 `42`、每个动作跳过前 3 帧，并按受试者进行 70%/30% 训练测试划分。若替换数据集，应重新训练并评估，不应直接沿用本批模型指标。

## 评估

```powershell
python -m src.posture_recognition.evaluate --json "data/raw/睡姿 区域划分data/区域划分/data.json" --algorithm cnn --model-path src/posture_recognition/models/cnn.pt
```

将 `cnn` 和 `cnn.pt` 分别替换为 `svm`/`svm.joblib` 或 `random_forest`/`random_forest.joblib`，可评估对应传统模型。评估输出准确率、宏平均 Precision/Recall/F1、分类报告和混淆矩阵。
