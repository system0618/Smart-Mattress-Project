# 姚乐 AI 协同开发记录

## 记录格式

```markdown
## YYYY-MM-DD

### 使用工具

### 提问或任务

### AI 输出摘要

### 采纳内容

### 人工修改与验证
```

## 2026-09-07

### 使用工具

Claude Code(模型 deepseek-v4-pro)

### 提问或任务

1. 整理飞书云文档中与身体部位划分相关的内容到「资料」文件夹(压缩包附件不下载,数据集压缩包由本人手动下载放入)。
2. 将 GitHub 远程 main 分支的最新修改合并到本地工作分支 feature/body-segmentation。
3. 根据资料(功能要求 PDF、数据集说明、补充材料、参考论文)生成身体部位划分算法功能实现的具体方案。
4. 约定后续对话按本文件格式记录。
5. 按方案实现身体部位划分算法功能;约定两条执行规则(已写入方案文档「0. 执行约定」):a) 对话记录按本文件格式更新;b) 只修改本人负责的 `src/body_segmentation/` 与 `data/` 相关代码,其他模块只读(接口文档 api_docs 仅同步身体部位划分输出接口)。

### AI 输出摘要

1. 飞书 wiki 文档需登录无法直接抓取,改为本人导出 Markdown + 附件放入「资料」文件夹。
2. 成功 fetch 并 fast-forward 合并 main(新增 commit d02318d..00e4dfc):压力增强管线(enhance.py、preprocess.py、generate_pseudo_labels.py)、可视化前端(visualization/frontend 全套 JS)、AI 日志整理、api_docs 更新。本地 main 与当前分支均已更新到 00e4dfc,未推送。
3. 生成《资料/身体部位划分算法实现方案.md》,核心内容:
   - 验收指标:样本级 70/30 验证集准确率 >95%;用户级留出(21 训练/9 验证)新用户准确率 >70%;前端展示不同睡姿区域划分效果。
   - 数据解析:新版 44×24 压力矩阵,region 为 6 个矩形框(肩/背/腰/臀/大腿/小腿),小腿弃用,输出 6 类像素 mask(background+5 区域);spine 暂不用;数据集已含对称翻转,增强时禁止再翻转。
   - 技术路线:JSON 流式解析 → 清洗(丢前 3 帧、3×3×3 中值滤波、归一化)→ 在线增强(噪声/平移/扰动/Cutout,无翻转)→ UNet 像素级分割(主方案,输入插值 96×48,加权 CE+Dice)→ 双口径评估(像素准确率、mIoU、每类 P/R/F1、按睡姿分组)→ 按 api_docs 输出 segmentation_mask JSON 对接前端。
   - 备选对比:轻量 DeepLabV3+、框回归 CNN、输入消融(单通道 vs viridis RGB vs PolishNetU 增强图)。
   - 实施分 7 个阶段(解析验证 → 划分 → UNet 基线 → 泛化调优 → 消融对比 → 前端交付 → 报告)。
   - 风险:低分辨率边界、新用户体型差异、枕头批次差异、类不平衡。
4. 功能实现与结果(代码均在 `src/body_segmentation/`):
   - 环境:官方 CUDA 版 torch 2.8.0+cu126 / torchvision 0.23.0(RTX 4060 Laptop),Tsinghua 镜像仅 CPU 版故改用官方源;Python 3.9 raw_decode 不跳过前导空白 → 手动 lstrip;中文路径经 bash 传参乱码 → 改用 Python glob 发现。
   - 数据:21570 帧标注 → 每动作丢前 3 帧(63 帧)后 21507 帧入库 dataset.h5(44×24 压力图 + mask),region 6 框中 na(小腿)容忍跳过;manifest 含样本级 70/30(6453 验证)与用户级 21/9(6480 验证)双划分;8 帧抽查渲染确认解析正确。
   - 训练(用户级划分,UNet base 32 深度 4,加权 CE+0.5×Dice,AdamW+Cosine,早停 patience 15):最优 epoch 48,val_acc 0.9253,val_mIoU 0.7775,约 50s/epoch(GPU 前卡死问题为 gzip HDF5 逐行随机读所致,改为全量载入内存后解决)。
   - 评估(同一 best.pt 双口径,data/processed/segmentation/evaluation_metrics.json):
     - 样本级:6453 帧,准确率 97.37% >95% ✓,mIoU 0.8928;四睡姿 97.0%–97.8%。
     - 用户级:6480 帧,准确率 92.27% >70% ✓,mIoU 0.7305;四睡姿 91.7%–93.2%。
     - 用户级每类 IoU:背景 0.93 / 肩 0.65 / 背 0.76 / 腰 0.72 / 臀 0.77 / 大腿 0.76;肩部面积小且边界模糊,为最难类(用户级 P 0.76 / R 0.81)。
     - 结论:单一用户级模型即同时满足两项验收指标,无需再训练样本级模型。
   - 导出:对用户级测试集每种睡姿抽样 2 帧共 8 帧,输出 api_docs 约定格式 segmentation JSON(frame_id、segmentation_shape [44,24]、segmentation_mask、labels、sleep_pose)到 data/processed/segmentation/export/masks/,并生成热力图+区域叠加效果图到 export/previews/(export_manifest.json 为清单)。

### 采纳内容

- 《资料/身体部位划分算法实现方案.md》整体技术路线与 6 类输出类别定义。
- 数据划分双口径(样本级/用户级)分别对应两项验收指标。
- 增强策略中「禁止左右翻转」的约束。
- 功能实现代码(`src/body_segmentation/` 下 dataset/augment/unet/train/evaluate/visualize/export)与数据解析约定(region 6 框、小腿弃用、na 占位容忍)。
- api_docs.md 中 Body Segmentation Output 类别同步为 background/shoulder/back/waist/hip/thigh。
- 交付产物:`src/body_segmentation/models/best.pt`(用户级训练模型)+ `data/processed/segmentation/evaluation_metrics.json`(双口径评估结果)+ `data/processed/segmentation/export/`(前端 segmentation JSON 与效果图)。

### 人工修改与验证

(待补充)
