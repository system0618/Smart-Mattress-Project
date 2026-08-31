# Data

本目录用于说明数据结构和保存少量样例数据。真实数据集、预处理结果、模型输入缓存等通常较大，默认不提交到 Git。

建议数据组织：

```text
data/
├── raw/          # 原始压力阵列数据
└── processed/    # 清洗、增强、划分后的数据
```

建议每条样本至少包含：

- `sample_id`：样本编号
- `user_id`：用户编号，评估新用户泛化能力时使用
- `posture_label`：睡姿类别
- `pressure_matrix`：二维压力阵列
- `timestamp`：采集时间，可选

如需共享小规模样例，请放在本目录下新建 `examples/`，并在 README 中说明来源和脱敏方式。
