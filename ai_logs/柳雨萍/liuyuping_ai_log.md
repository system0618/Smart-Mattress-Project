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

## 2026-09-10

### 使用工具

Codex：`git`（远程同步与状态核对）、无头 Edge + 本地 HTTP（页面渲染、截图与几何测量）、
PyMuPDF + Windows OCR（课程 PDF 第 10 页内容提取）、Node（JS 语法检查）、Python（依赖核对）。

### 提问或任务

1. 将 Smart-Mattress-Project 与 GitHub 远程仓库同步到本地。
2. 明确“指标趋势”卡片中展示的指标并整卡移除。
3. 把“数据回放控制”卡片移动到“实时压力热力图”下方，与热力图卡片同宽且紧凑无大留白。
4. 新增“气囊侧视图”卡片：只显示肩/背/腰/臀四个气囊，支撑程度随实时数据变化；
   样式先后参考课程 PDF 第 10 页（横躺人形 + 横放扁气囊）并最终简化为仅保留填充。
5. 将整页切换为白天（浅色）主题，但热力图显示区域保留原深色风格。
6. 核对 `requirements.txt` 是否需要补充依赖。

### AI 输出摘要

- 远程同步：当前分支 `feature/visualization` 已与远程一致；本次同步抓取到
  `origin/main`（`582b9fa → 8f689cd`）与 `origin/feature/pressure-enhancement`
  （`00e4dfc → 4e24aac`），无需新提交即已是最新。
- “指标趋势”原包含最大压力、接触面平均压力、接触面指数三条曲线（由 `app.js`
  中 `state.history.max/mean/contact` 累积），确认可去掉后整卡删除，并同步清理
  DOM 引用、绘制调用、每帧历史记录与 CSS。
- 布局调整：把“数据回放控制”从页面底部移入 `dashboard`，先采用 `grid-template-areas`
  方案，但右侧列跨两行会把第二行撑高造成留白；改为 `.left-column` 纵向 flex 包装后，
  热力图与控制卡片间距固定 16px、宽度一致，无多余空隙。
- 新增“气囊侧视图”：读取现有 12 个气囊分区（肩/背/腰/臀 × 左/中/右）的实时状态，
  每个大区域取当前支撑程度最高的气囊作为代表，绘制成四个横放扁气囊，高度随支撑度变化。
  视觉迭代过程：含人形 + 框线 → 参考 PDF 第 10 页调整人形/扁气囊 → 按人工反馈移除人形
  与气囊框线、填充统一为 `#32b5ff`、文字白色加粗，再压缩卡片空隙。
- 主题切换：页面底色、卡片、控件、气囊/曲线等 Canvas 全部改为浅色体系；按人工反馈，
  热力图画面恢复为原深蓝底 + 原色带，形成“白天页面 + 深色热力图”的组合；
  侧视图白色加粗文字以深色小圆片衬底保证在浅色画布上可读。
- `requirements.txt` 核对：代码实际 import 的 numpy/pandas/scipy/sklearn/matplotlib/
  h5py/torch/ultralytics/tqdm 均已列出，无缺失项；torchvision/opencv-python/seaborn/
  joblib/pytest 当前未直接使用但建议保留备用。

### 采纳内容

- `visualization/frontend/index.html`：移除“指标趋势”卡片；新增“气囊侧视图”卡片；
  数据回放控制移入热力图下方；浅色主题相关页面结构。
- `visualization/frontend/css/style.css`：dashboard 左侧列布局、气囊侧视图画布尺寸与
  卡片间距、整页浅色配色及热力图深色区域。
- `visualization/frontend/js/app.js`：移除指标趋势绘制与历史数组；新增侧视图 DOM/绘制
  接入；状态色/曲线色改为浅色主题可读色。
- `visualization/frontend/js/charts.js`：新增 `drawAirbagSideView` 及多轮样式迭代；
  Canvas 颜色按浅色主题调整，热力图部分保留深色。
- `visualization/frontend/README.md`：功能清单同步（指标趋势移除、侧视图说明等）。

### 人工修改与验证

- 每轮视觉改动均生成整页预览截图，由本人（柳雨萍）逐项确认后继续迭代
  （去掉人形与框线、`#32b5ff` 统一填充、白色加粗文字、压缩气囊上方空隙等）。
- 用无头 Edge 实测：控制卡片紧贴热力图下方，间距 16px，两卡宽度一致；
  新增侧视图 Canvas 正常绘制且无脚本报错。
- 用无头 Edge + DOM 读取确认浅色主题生效（body 背景 `rgb(238,243,249)`、画布浅色、
  侧视图填充仍为 `#32b5ff`），热力图画面经截图人工确认为原深色风格。
- 修改涉及的全部 JS 通过 `node --check` 语法检查；`requirements.txt` 经与代码 import
  对照后判定无需新增依赖。以上改动均未提交/推送。

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
  高压区（如臀/肩）放气减压”；每个大区域先取压力最大的“主气囊”做横向比较，同大区域附属气囊
  支撑不超过主气囊，避免侧卧时附属区因附带压力被误判；无身体接触的区域不充气；真实设备数据接入后仍可通过
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
