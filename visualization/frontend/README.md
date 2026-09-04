# Frontend（JS 实时可视化基础版）

基于原生 HTML/CSS/JS + Canvas 实现的智能床垫实时可视化，无框架、无外部 CDN 依赖，本地浏览器即可运行。

## 已实现功能

- **实时压力热力图**：44 行 × 24 列压力阵列，turbo 风格色带，支持鼠标悬停查看单点压力、点击选择传感器点。
- **热力图色标固定为 0–300**，符合课程对压力显示范围的要求。
- **本地数据选择**：点击“打开本地数据…”选择一个 txt 数据组（单个动作），自动按文件名动作编号给出睡姿演示结果、按五区域标注生成区域划分演示结果并叠加到热力图。
- **睡眠状态显示**：展示睡姿（预设接口结果/文件名规则）与体动状态（动态文件 0=静态躺 / 1=体动 / 2=翻身 标签）。
- **压力指标**：最大压力、平均压力、接触面指数、接触传感器数。
- **气囊状态可视化**：按肩背/腰/臀/大腿 × 左/中/右划分 12 个虚拟气囊分区，根据分区压力自动“充气/放气/保持”，并高亮对应传感器点。
- **传感器点压力曲线**：点击热力图或气囊分区后，实时跟踪该点压力变化。
- **指标趋势曲线**：最近 120 帧的最大/平均压力和接触面指数。
- **数据回放控制**：数据源切换、播放/暂停、单帧、复位、倍速、帧滑条。

## 目录说明

```text
visualization/frontend/
├── index.html            # 页面入口
├── css/style.css
├── js/
│   ├── config.js         # 矩阵尺寸、身体区域、气囊分区配置
│   ├── palette.js        # turbo 色带
│   ├── metrics.js        # 压力指标与分区统计
│   ├── charts.js         # Canvas 热力图 / 气囊面板 / 折线图
│   └── app.js            # 回放控制、实时推送接口、主逻辑
├── data/
│   └── samples.js        # 内置小样例（自动生成，不入正式数据集）
└── tools/
    └── export_sample.py  # 把 txt 数据集转成前端样例
```

## 运行方式

仓库已经内置 `dgs` 的动态过程样例和四种睡姿静帧样例，因此可以直接运行：

```powershell
cd visualization/frontend
python -m http.server 8000
```

浏览器打开 <http://localhost:8000>。页面不依赖 fetch，也可以直接双击 `index.html` 打开。

页面默认回放内置样例；也可以点击 **“打开本地数据…”**，从 `睡姿 区域划分data/睡姿数据/<人名>/` 目录选择一个 `xxx_N.txt` 或 `xxx_动态N.txt`。

如果需要重新生成/补充样例，在仓库根目录执行：

```powershell
python visualization/frontend/tools/export_sample.py `
  "D:/.../睡姿 区域划分data/睡姿数据/dgs/dgs_动态一.txt" `
  "D:/.../睡姿 区域划分data/睡姿数据/dgs/dgs_1.txt"
```

## 接入后端 / 算法结果（预设接口）

算法/后端模块就绪后，前端保留了一个统一入口，按 `docs/api_docs.md` 的帧格式推送即可：

```js
// 1) 压力帧 Pressure Frame
SmartMattressViewer.pushFrame({
  pressure_matrix: [[...], [...]],   // 44x24
  movement: 0,                       // 0=静态躺 1=体动 2=翻身（动态数据标签）
  timestamp: "2026-09-04T10:00:00+08:00",
});

// 2) 睡姿识别输出 Posture Recognition Output
SmartMattressViewer.setPostureResult({
  frame_id: "frame_000001",
  posture: "supine",                 // supine/prone/left_lateral/right_lateral/unknown
  confidence: 0.98,
  source: "posture_recognition",
});

// 3) 身体部位划分输出 Body Segmentation Output
SmartMattressViewer.setSegmentationResult({
  frame_id: "frame_000001",
  segmentation_mask: [[0, 1, 1, 2]], // 44x24 掩码
  labels: { "0": "background", "1": "shoulder", "2": "back" },
  source: "body_segmentation",
});

// 4) 实时可视化状态 Realtime Visualization State（可同时带气囊状态）
SmartMattressViewer.setRealtimeState({
  pressure_stats: { max_pressure: 0.93, mean_pressure: 0.28, contact_area_index: 0.41 },
  airbags: [{ airbag_id: "zone_01", status: "inflating", pressure: 0.62 }],
});
```

后续可把以上调用接到 WebSocket / HTTP 轮询，无需改动已有画布逻辑。尚未接入算法时，本地 txt 演示会使用“文件名规则（睡姿）+ 区域矩形（身体划分）”作为占位结果，并在页面上标注来源。

## 待确认项

- **气囊-传感器真实对应关系**：当前 12 个气囊分区是演示用配置，位于 `js/config.js` 的 `airbagZones`。待依据《气囊-传感器 标注 布置图20240624.pdf》确认后只替换该配置即可。
- **睡姿识别结果**：静帧样例来自文件编号；动态样例的睡姿待接入 `src/posture_recognition` 输出。
- **身体区域坐标**：演示用区域掩码参考新版区域划分 JSON 中 `region` 字段的前 5 个矩形；真实模型输出应通过 `setSegmentationResult` 推送。
- **接触阈值**：接触面指数目前按 `js/config.js` 中 `contactThreshold`（原始 ADC=2）统计，可根据真实标定调整。
