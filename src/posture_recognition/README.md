# Posture Recognition

This module implements only sleep-posture recognition. It uses the labelled
`data.json` records from the region dataset; each record contains a `44 x 24`
pressure frame, `people_name`, `action`, and `sleep_pos`. The model supports
up to six label IDs; the current JSON contains four populated labels (`0..3`).

Algorithms:

- `svm`: hand-crafted pressure features followed by StandardScaler + RBF SVM.
- `random_forest`: the same features with a class-balanced random forest.
- `cnn`: a small CNN that classifies the normalized pressure map.

The split is user-level and defaults to 70% training / 30% testing. Evaluation
reports accuracy, macro precision, macro recall, macro F1, per-class metrics,
and a confusion matrix.

```powershell
python -m src.posture_recognition.train --json "data/raw/睡姿 区域划分data/区域划分/data.json" --algorithm svm
python -m src.posture_recognition.evaluate --json "data/raw/睡姿 区域划分data/区域划分/data.json" --algorithm svm --model-path src/posture_recognition/models/svm.joblib
```

For the CNN, use `--algorithm cnn --epochs 30`; its checkpoint is saved as
`src/posture_recognition/models/cnn.pt`.

睡姿识别模块。课程要求为：

- 至少实现 2 个睡姿识别算法并对比。
- 使用数据增强扩充数据。
- 按 70% 训练集、30% 测试集划分。
- 准确率目标大于 95%。
- 输出最优模型的 precision、recall、F1 score。
- 为可视化端提供不同组别睡姿热力图数据。

建议先实现一个传统机器学习基线，例如 SVM、Random Forest 或 KNN，再实现一个 CNN/轻量深度学习模型。
