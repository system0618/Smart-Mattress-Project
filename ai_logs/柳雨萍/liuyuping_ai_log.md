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

## 2026-09-10（第二次会话：睡姿识别与弱力增强接入）

### 使用工具

Codex：`git`（fetch / 快进同步 / 分支与 tag 核对 / 指定路径取文件）、GitHub API 与
Release 附件下载、Python（PyTorch CPU 推理、HDF5、SHA-256 与指标复算、matplotlib
Viridis 上色）、Node（JS 语法检查与非浏览器 DOM 桩跑通前端逻辑）、无头 Edge
（尝试页面渲染，未取到输出后改用 DOM 桩）、PowerShell（服务进程与端口清理）。

### 提问或任务

1. 把远端 `main` 同步到本地。
2. 明确弱力增强与睡姿识别两个模型是否已有权重，并把它们接入可视化。
3. 先做睡姿识别接入。
4. 盘点弱力增强还缺哪些文件；确认有权重后能否直接推理。
5. 检查 GitHub Release 上的弱力增强整合包。
6. 用提供的 `pressure_enhancement_models.zip` 完成接入，并按要求把默认模型换成
   `annotated_pressure_strong_v0.pt`。
7. 再次从远端同步（弱力增强有更新），并按第 2 方案实现门控融合模式。
8. 一并更正睡姿类别命名不一致的问题。

### AI 输出摘要

- 远程同步：`main` 先由 `d02318d` 快进到 `7a1a69e`（29 个提交，PR #9），后续又同步到
  `cd2b536`（PR #11）与 `74ae2e6`（PR #12）；顺带同步了 `feature/posture-recognition`
  与 `feature/pressure-enhancement`。仓库目录存在 Git 所有权告警（目录属主与沙箱账户
  不同），改用单次命令参数 `safe.directory` 解决，未改动全局配置。
- 睡姿识别接入：从 `origin/feature/posture-recognition` 取回 `cnn.pt`(0.1 MB)、
  `random_forest.joblib`(7.0 MB)、`svm.joblib`(0.44 MB) 及配套代码；新增
  `src/posture_recognition/infer.py`（单帧/多帧推理、按分类头形状推断类别数、CLI 自测）；
  `server.py` 新增 `POST /api/posture` 与 `GET /api/posture/status`；前端加载样例后自动
  逐帧识别并覆盖文件名规则。复现测试集准确率 98.66%（3942 帧、20 位受试者按人划分），
  与分支记录一致，`dgs_1/7/10/16` 四组 150 帧全部命中。
- 类别命名修正：核对 `睡姿采集2026.docx` 与 `data.json` 的 `action → sleep_pos`
  （动作 1–6→0、7–9→1、10–15→2、16–21→3），确认标签 2/3 是左侧卧/右侧卧，而不是分支
  代码里的 `left_extended`/`left_fetal`，统一为 `supine/prone/left_lateral/right_lateral`。
- 弱力增强盘点：仓库与磁盘上都没有增强权重，Release `pressure-enhancement-v1.0`
  的 assets 数为 0（只挂了 7 个 manifest 与 README）；确认需要「权重 + 配套代码 +
  训练色标范围」三样才能直接推理，且论文流程与早期基线两种权重格式不通用。
- 权重落地：解压 `pressure_enhancement_models.zip` 到 `models/`，7 个 `.pt`
  逐个核对字节数与 SHA-256，全部与 manifest 匹配；从 `main` 取回 `paper_pipeline.py`
  等配套代码。
- 端到端跑通：用现有 `睡姿数据` 造出模型要求的 `(312, 24, 44, 3)` Viridis RGB 输入 H5
  （色标 `0–300`，与训练用的 99.5 分位一致，也与前端色标一致），CPU 上 312 帧约 3 秒；
  `paper_pipeline export` 产出增强 H5 与对比图。实测增强与输入相关性 0.96，横向相邻差
  0.0478 → 0.0321，属细节平滑而非重绘。
- 换用 `annotated_pressure_strong_v0.pt`：`server.py` 改为自动识别两种发布格式
  （`polish_state_dict`+`PaperPolishNetU` / `model_state_dict`+`PolishNetU`），默认模型
  切到 strong_v0。312 帧实测：strong_v0 整体 +20.75、弱压区 +36.55、强压区 +45.02、
  背景 +6.20、相邻差升到 15.97；v1 整体 +0.57、弱压区 −2.28、相邻差降到 10.90。
- 门控融合模式（第 2 方案）：新增 `--enhance-mode gated`，同时加载 v1 结构分支与
  strong 强增强分支（都用原始帧，不做级联），在归一化压力空间取加权残差、只保留正向
  增益并限幅，再用压力自身构造的软掩膜门控（5×5 最大值滤波 + 高斯 + 阈值 + 弱压加权），
  门控外逐像素保持原值。第一版门控半径过小导致强压区被抬得比弱压区还多，定位到本批
  数据存在约 14 ADC 床垫底噪后改为「局部覆盖度 + 弱压优先」。调参后 312 帧：门控覆盖
  0.24、22.9% 像素门控严格为 0、整体 +11.9、弱压区 +22.4、强压区 +20.0、相邻差
  14.06 → 14.09，比单用 strong 模型更保守且不放大噪点。
- 门控模式的上游依据：同步了 PR #12 新增的 `ensemble_enhance_raw_sleep.py`，其思路是
  用真实 14 关节掩膜限制正向残差；因实时帧无关节标注，服务端用压力软掩膜做近似，
  并用我们的 `data.json`（无 kpts，回退 region/spine 门控）跑过 64 帧烟雾测试：
  门控内 +0.0724、门控外约 3e-6。
- 命名更正落地：`src/posture_recognition/models/README.md` 类别表与示例代码、三个
  `*_split.json` 的 `classes`、`cnn_test_metrics.json` 的 `class_names` 与分类报告键
  全部改为新命名；该 metrics 文件原本是 UTF-16（当年用 PowerShell 重定向写出），
  一并转为 UTF-8。

### 采纳内容

- `src/posture_recognition/infer.py`（新增）、`dataset.py`（类别命名）、
  `models/README.md`、`models/*_split.json`、`models/cnn_test_metrics.json`，
  以及从睡姿分支取回的 `models.py`、`features.py`、`train.py`、`evaluate.py` 与三个模型权重。
- `src/pressure_enhancement/`：`paper_pipeline.py`、`infer.py`、`train_annotated.py`、
  `enhance_raw_sleep_heatmaps.py`、`evaluate_denoising.py`、`visualize_enhancement.py`、
  `ensemble_enhance_raw_sleep.py`、`enhance.py`、`utils.py`、`README.md`；
  `src/data_process/prepare_annotated_pressure_dataset.py` 与 README。
- `models/`：7 个发布权重的 manifest 与 README（`.pt` 被 `.gitignore` 排除，仅本地保留）；
  `reports/paper_target_metrics.json`。
- `visualization/frontend/server.py`：`PostureService`、`EnhanceService`（单模型与门控两种
  模式、两种权重格式自动识别）、`POST /api/posture`、`POST /api/enhance` 及两个状态接口。
- `visualization/frontend/js/config.js`、`js/app.js`、`index.html`：睡姿识别与弱力增强的
  自动请求、逐帧缓存、来源显示与“弱力增强”开关。
- `docs/api_docs.md`：新增 Local Posture Bridge 与 Local Enhancement Bridge 章节；
  `.gitignore`：补充 `checkpoints/` 与 `!src/**/models/README.md`。

### 人工修改与验证

- 权重可信度：7 个 `.pt` 的 SHA-256 与字节数全部与 manifest 一致；未改写任何二进制
  训练产物。
- 睡姿识别：用真实测试集重跑推理复现 accuracy 0.986555、混淆矩阵与记录一致；
  更正命名后再次复算，数值未变。
- 弱力增强：真实模型 + 真实帧端到端跑通（312 帧约 3 秒），生成前后对比图
  （`压力增强对比图/部署结果/`）由人工查看确认；单模型模式在重构前后输出逐像素比对
  最大差为 0，确认改动未破坏原有行为。
- 前端：JS 全部通过 `node --check`；用 Node 挂 DOM 桩完整跑通 `app.js`，确认初始化会
  调用 `/api/segment` 与 `/api/posture`，打开“弱力增强”开关后调用 `/api/enhance` 且
  指标切换到增强矩阵，关闭后回到原始矩阵。
- 过程清理：排查时发现两个残留服务进程占用同一端口（Windows 允许重复绑定，导致请求
  随机落到旧进程），已按端口定位并结束，测试端口均已释放。
- 已知限制（如实记录）：无关节标注时门控只能保证远离人体的背景不变，靠近人体的床垫
  底噪仍会被轻微抬升（5–15 ADC 区间平均 +5.7）；要与论文结果严格对齐，仍需使用带真实
  关节标注的 `ensemble_enhance_raw_sleep.py` 离线生成 HDF5。
- 以上改动均未提交/推送。

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
