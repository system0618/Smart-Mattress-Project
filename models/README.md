# 压力增强部署模型

本目录用于放置从 GitHub Release 或团队共享盘下载的模型权重，不将 `.pt` 文件提交到 Git。

## 当前发布版本

`pressure_enhancement_v1.pt` 是从 40 epoch 联合微调 checkpoint 中抽取的 PolishNetU 推理权重。它不包含 OpenPose、训练优化器或关节标注依赖。

下载模型后，使用同目录的 `pressure_enhancement_v1.manifest.json` 检查 SHA256。输入为 HDF5 中的 `input_images` 或 `images`，形状必须为 `(N, 24, 44, 3)`，编码为 Viridis RGB。

使用命令见 `src/pressure_enhancement/README.md` 的“团队直接使用”章节。
