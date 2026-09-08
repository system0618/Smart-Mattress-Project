# 柳雨萍 AI 协同开发记录

## 记录格式

```markdown
## YYYY-MM-DD

### 使用工具

### 提问或任务

### AI 输出摘要

### 采纳内容

### 人工修改与验证
```

## 2026-09-08

### 使用工具

Codex：`git`（fetch/merge）、PyMuPDF（课程 PDF 解析）、Python（接口自测）、无头 Edge（页面冒烟测试）。

### 提问或任务

1. 阅读课程 PDF（2026 秋季《专业方向实践》），明确“基于实时数据的智能床垫可视化展示”功能要求。
2. 把远程仓库 https://github.com/system0618/Smart-Mattress-Project.git 的最新提交同步到本地。
3. 将队友姚乐实现的身体部位划分（UNet 像素分割）与可视化前端连接起来。

### AI 输出摘要

- 远程 `main` 已新增“身体部位划分 UNet 管线（样本级 97.4% / 用户级 92.3%）”，本地 `feature/visualization` 通过 `git fetch` + fast-forward 合并到最新 `582b9fa`；
- 身体划分输出沿用 `docs/api_docs.md` 的 6 类约定（background/shoulder/back/waist/hip/thigh，44×24 mask），前端据此叠加热力图；
- 新增一体化服务 `visualization/frontend/server.py`：同时提供页面静态资源和 `POST /api/segment`（加载 `src/body_segmentation/models/best.pt` 推理，按训练同款逐帧 min-max 归一化并插值回 44×24）；`GET /api/status` 返回模型状态；`--mock` 可在没有权重时用模拟掩码联调前端；
- 前端 `app.js` 接入：加载样例/本地 txt 时一次性请求全部帧掩码并按帧叠加；外部 `pushFrame` 模式逐帧请求分割结果；页面“身体区域”标注 UNet 来源，服务缺失时自动回退区域矩形占位；热力图下方新增肩/背/腰/臀/大腿图例；
- 更新 `visualization/frontend/README.md` 与 `docs/api_docs.md`（Local Segmentation Bridge 章节）。

### 采纳内容

- `visualization/frontend/server.py`（新增）
- `visualization/frontend/js/app.js`、`js/config.js`（分割服务接入、逐帧掩码缓存）
- `visualization/frontend/index.html`、`css/style.css`（区域图例）
- `visualization/frontend/README.md`、`docs/api_docs.md`（运行与接口说明）

### 人工修改与验证

- 用 `server.py --mock` + 无头 Edge 打开页面：区域图例正常显示，热力图叠加掩码，“身体区域”来源显示 `body_segmentation · mock联调掩码`，回放/指标/气囊均正常；
- 补充（同日）：从姚乐处获取 `body_segmentation_models.rar`，解压 `best.pt`（epoch 48，val_acc 0.9253）与 `metrics.json` 到 `src/body_segmentation/models/`；在本机 Miniconda base 安装 CPU 版 torch 2.8.0 + h5py 后，单帧 CPU 推理约 40 ms，`server.py` 页面“身体区域”已显示 `body_segmentation · UNet`，真实模型端到端验证通过。
- 视觉优化（同日）：区域划分由“逐格方框描边”改为“不同部位不同颜色的平滑闭合线框 + 半透明填充”，
  并新增“部位名称”开关控制是否在线框左侧显示肩/背/腰/臀/大腿名称；用真实 UNet 模型 + 无头 Edge
  验证页面运行正常，截图保存后人工确认样式。
- 气囊逻辑（同日）：气囊支撑区按肩/背/腰/臀 × 左中右 = 12 个虚拟气囊（大腿不设气囊支撑，
  与人体识别区域中的大腿区分开）；支撑度由“压力大→充气高”改为“低压接触区（如腰）充气支撑、
  高压区（如臀/肩）放气减压”，无身体接触的区域不充气；真实设备数据接入后仍可通过
  `setRealtimeState` 覆盖模拟值。

## 2026-09-04

### 使用工具

Codex：`git`（仓库克隆/分支切换）、`pypdf`/`PyMuPDF`（PDF 解析）、`zipfile`（docx 读取）、Python（样例数据转换）、无头 Edge（页面冒烟测试）。

### 提问或任务

阅读课程 PDF、智能床垫数据集说明与仓库文档，基于真实数据集在 `visualization/frontend/` 用 JS 实现一个“基于实时数据的智能床垫可视化”基础版本。

### AI 输出摘要

- 搭建无框架的 HTML/Canvas 前端：压力热力图、睡眠状态、最大/平均压力与接触面指数、气囊状态、传感器点压力曲线、指标趋势与回放控制。
- 内置由 `dgs` 真实 txt 转换的 5 个小样例（动态过程 + 四种睡姿），并给出 txt → JS 样例的导出脚本。
- 预留 `SmartMattressViewer.pushFrame()` 接口，便于后续接入 WebSocket/算法输出。

### 采纳内容

文件位于 `visualization/frontend/`，含 `index.html`、`css/style.css`、`js/*.js`、`data/samples.js`、`tools/export_sample.py`。

### 人工修改与验证

已用无头 Edge 打开页面并确认脚本运行正常；`js/config.js` 中的气囊分区为演示配置，待依据《气囊-传感器 标注 布置图》核对真实对应关系。

### 补充迭代（同日）

- 增加“打开本地数据…”功能，可在浏览器中直接选择 `睡姿数据` 目录下的 txt 动作文件并按帧回放；
- 热力图色标统一固定为 0–300；
- 按 `docs/api_docs.md` 预留接口实现 `SmartMattressViewer.pushFrame / setPostureResult / setSegmentationResult / setRealtimeState`，睡姿与身体划分结果可直接叠加到热力图；
- 未接入算法前，本地演示用“文件名动作编号 + 五区域矩形”生成占位结果，并在页面上明确标注来源。
