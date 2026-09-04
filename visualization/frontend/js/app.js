/**
 * 智能床垫实时可视化 - 主应用
 *
 * 本基础版默认使用 tools/export_sample.py 生成的本地样例循环回放；
 * 后端就绪后可直接调用 SmartMattressViewer.pushFrame() 推送实时帧。
 */
(function (global) {
  "use strict";

  const Config = global.SmartMattressConfig;
  const Metrics = global.SmartMattressMetrics;
  const Charts = global.SmartMattressCharts;
  const Palette = global.SmartMattressPalette;

  const samples = Array.isArray(global.SMART_MATTRESS_SAMPLES)
    ? global.SMART_MATTRESS_SAMPLES
    : [];

  const dom = {};
  const state = {
    sample: null,
    localSamples: [],
    externalMode: false,
    externalMeta: null,
    playing: false,
    timerId: null,
    currentFrame: 0,
    seeking: false,
    selectedPoint: { row: 20, col: 12 },
    selectedZoneId: null,
    showRegions: true,
    showAirbags: false,
    history: {
      max: [],
      mean: [],
      contact: [],
      point: [],
    },
    airbagStates: {},
    lastRendered: null,
    postureOverride: null,
    segmentation: null,
    demoSegmentation: true,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function init() {
    collectDom();
    populateSamples();
    populateAirbagLegend();
    Palette.drawColorbar($("colorbarCanvas"));
    bindEvents();
    if (samples.length) {
      loadSample(samples[0].id);
    } else {
      showNoDataHint();
    }
  }

  function collectDom() {
    [
      "sampleSelect",
      "localBtn",
      "fileInput",
      "playBtn",
      "stepBtn",
      "resetBtn",
      "speedSelect",
      "frameSlider",
      "frameProgressLabel",
      "movementLabel",
      "heatmapCanvas",
      "heatmapWrap",
      "cellTooltip",
      "colorbarMin",
      "colorbarMax",
      "sleepPosture",
      "sleepState",
      "postureSource",
      "postureConfidence",
      "segmentationSource",
      "postureIcon",
      "frameInfo",
      "metricMax",
      "metricMean",
      "metricContact",
      "metricCells",
      "airbagCanvas",
      "airbagLegend",
      "sensorChart",
      "sensorInfo",
      "metricChart",
      "toggleRegion",
      "toggleAirbag",
      "autoAirbag",
      "liveDot",
      "liveText",
    ].forEach((id) => {
      dom[id] = $(id);
    });
  }

  function populateSamples() {
    const select = dom.sampleSelect;
    select.innerHTML = "";
    for (const sample of getAllSamples()) {
      const option = document.createElement("option");
      option.value = sample.id;
      option.textContent = (state.localSamples.includes(sample) ? "📁 " : "") + sample.label;
      select.appendChild(option);
    }
  }

  function getAllSamples() {
    return state.localSamples.concat(samples);
  }

  function populateAirbagLegend() {
    dom.airbagLegend.innerHTML = "";
    Config.airbagZones.forEach((zone) => {
      const item = document.createElement("div");
      item.className = "airbag-item";
      item.dataset.zoneId = zone.id;
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = "#38bdf8";
      const name = document.createElement("span");
      name.textContent = zone.id.replace("zone_", "Z") + " " + zone.label;
      const pct = document.createElement("span");
      pct.className = "pct";
      pct.textContent = "--";
      item.append(dot, name, pct);
      item.addEventListener("click", () => selectAirbagZone(zone.id));
      dom.airbagLegend.appendChild(item);
    });
  }

  function bindEvents() {
    dom.sampleSelect.addEventListener("change", (event) => {
      loadSample(event.target.value);
    });

    dom.localBtn.addEventListener("click", () => {
      dom.fileInput.value = "";
      dom.fileInput.click();
    });
    dom.fileInput.addEventListener("change", handleLocalFile);

    dom.playBtn.addEventListener("click", togglePlay);
    dom.stepBtn.addEventListener("click", () => {
      if (!state.sample) return;
      pause();
      stepFrame(1, true);
    });
    dom.resetBtn.addEventListener("click", () => {
      if (!state.sample) return;
      pause();
      state.currentFrame = 0;
      renderFrame(0, false);
    });

    dom.speedSelect.addEventListener("change", () => {
      if (state.playing) {
        startTimer();
      }
    });

    dom.frameSlider.addEventListener("input", (event) => {
      state.seeking = true;
      const index = Number(event.target.value);
      state.currentFrame = index;
      renderFrame(index, false);
    });
    dom.frameSlider.addEventListener("change", () => {
      state.seeking = false;
    });

    dom.toggleRegion.addEventListener("change", (event) => {
      state.showRegions = event.target.checked;
      redrawLast();
    });
    dom.toggleAirbag.addEventListener("change", (event) => {
      state.showAirbags = event.target.checked;
      redrawLast();
    });

    dom.autoAirbag.addEventListener("change", () => {
      updateAirbagsFromLast();
      drawAirbags();
    });

    const heatmap = dom.heatmapCanvas;
    heatmap.addEventListener("pointermove", handleHeatmapMove);
    heatmap.addEventListener("pointerleave", () => {
      dom.cellTooltip.classList.add("hidden");
    });
    heatmap.addEventListener("click", handleHeatmapClick);
    window.addEventListener("resize", () => redrawLast());
  }

  async function handleLocalFile(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    try {
      for (const file of files) {
        const text = await file.text();
        const sample = parseLocalTxt(text, file.name);
        state.localSamples.unshift(sample);
        populateSamples();
        loadSample(sample.id);
      }
    } catch (error) {
      console.error(error);
      window.alert("读取本地数据失败：" + error.message);
    }
  }

  function parseLocalTxt(text, fileName) {
    const lines = String(text || "").split(/\r?\n/);
    const frames = [];
    let currentRows = [];
    let currentLabel = 0;

    const pushCompleted = (movement) => {
      if (currentRows.length !== Config.rows) return false;
      frames.push({ m: movement == null ? currentLabel : movement, v: currentRows.flat() });
      currentRows = [];
      return true;
    };

    for (const raw of lines) {
      const line = raw.trim();
      if (!line) continue;
      const parts = line.split(",");
      if (parts.length === 1 && ["0", "1", "2"].includes(parts[0].trim())) {
        // 每帧结束后紧跟 0/1/2 标签行，表示刚完成这一帧的状态
        const label = Number(parts[0].trim());
        if (!pushCompleted(label)) currentLabel = label;
        continue;
      }
      if (parts.length !== Config.cols) continue;
      if (currentRows.length === Config.rows) pushCompleted();
      currentRows.push(parts.map((part) => Number(part) || 0));
    }
    pushCompleted();
    if (!frames.length) {
      throw new Error("文件中没有找到 44 行 × 24 列的压力帧，请选择 睡姿数据 目录下的 txt");
    }

    const stem = fileName.replace(/\.txt$/i, "");
    const posture = postureFromFileName(stem);
    const maxValue = Math.max(...frames.flatMap((frame) => frame.v));
    return {
      id: "local_" + stem + "_" + state.localSamples.length,
      label: `${stem} · ${Config.postureMap[posture].label}`,
      user_id: stem.split("_")[0] || "local",
      action: actionFromFileName(stem),
      posture,
      rows: Config.rows,
      cols: Config.cols,
      max_value: maxValue,
      has_movement_label: frames.some((frame) => frame.m !== 0),
      frames,
    };
  }

  function postureFromFileName(stem) {
    const action = actionFromFileName(stem);
    if (action != null) {
      if (action >= 1 && action <= 6) return "supine";
      if (action >= 7 && action <= 9) return "prone";
      if (action >= 10 && action <= 15) return "left_lateral";
      if (action >= 16 && action <= 21) return "right_lateral";
    }
    return "unknown";
  }

  function actionFromFileName(stem) {
    if (stem.includes("动态")) return null;
    const match = stem.match(/_(\d+)$/);
    return match ? Number(match[1]) : null;
  }

  function loadSample(id) {
    const all = getAllSamples();
    const sample = all.find((item) => item.id === id) || all[0];
    if (!sample) return;
    pause(false);
    state.sample = sample;
    state.externalMode = false;
    state.externalMeta = null;
    state.postureOverride = null;
    state.segmentation = null;
    state.demoSegmentation = true;
    if (sample.posture && sample.posture !== "unknown") {
      state.postureOverride = {
        posture: sample.posture,
        confidence: null,
        source: "本地演示·文件名规则",
      };
    }
    updateSegmentationSource();
    state.currentFrame = 0;
    state.selectedPoint = { row: 20, col: 12 };
    state.selectedZoneId = Config.airbagZones[0].id;
    clearHistory();
    resetAirbagStates();

    dom.sampleSelect.value = sample.id;
    dom.frameSlider.min = 0;
    dom.frameSlider.max = sample.frames.length - 1;
    dom.frameSlider.value = 0;
    dom.colorbarMax.textContent = formatMetric(sample.max_value);
    renderFrame(0, true);
    play();
  }

  function renderFrame(index, record) {
    const sample = state.sample;
    if (!sample || !sample.frames.length) return;
    const frame = sample.frames[index % sample.frames.length];
    state.currentFrame = index % sample.frames.length;

    const flat = frame.v;
    const meta = {
      maxValue: sample.max_value,
      posture: sample.posture,
      movement: frame.m == null ? 0 : frame.m,
      source: sample.has_movement_label ? "动态标签" : "样例标注",
    };
    renderPressureData(flat, meta, record, sample);
  }

  function renderPressureData(flat, meta, record, sampleForStats) {
    const sample = state.sample || sampleForStats;
    const stats = Metrics.pressureStats(
      flat,
      sample ? sample.rows : Config.rows,
      sample ? sample.cols : Config.cols,
      Config.contactThreshold
    );

    if (!state.selectedPoint) {
      state.selectedPoint = { row: stats.maxRow, col: stats.maxCol };
    }

    updateMetricUI(stats);
    updateSleepUI(meta);
    updateHistory(flat, stats, record);
    updateAirbags(flat, sample, stats);

    state.lastRendered = { flat, meta, sample };
    if (state.demoSegmentation) {
      state.segmentation = buildDemoSegmentation(flat, sample);
      updateSegmentationSource();
    }
    dom.frameSlider.value = state.currentFrame;
    dom.frameSlider.max = sample ? sample.frames.length - 1 : 0;
    dom.frameProgressLabel.textContent = `${state.currentFrame} / ${
      sample ? sample.frames.length - 1 : 0
    }`;

    updateHeatmapUI();
    drawAirbags();
    drawCharts();
    updateLiveUI();
  }

  function updateMetricUI(stats) {
    dom.metricMax.textContent = formatMetric(stats.maxPressure);
    dom.metricMean.textContent = formatMetric(stats.meanPressure);
    dom.metricContact.textContent = stats.contactAreaPercent.toFixed(1) + "%";
    dom.metricCells.textContent = `${stats.activeCells} / ${stats.totalCells}`;
  }

  function updateSleepUI(meta) {
    const override = state.postureOverride;
    const postureKey = override && override.posture ? override.posture : meta.posture || "unknown";
    const posture = Config.postureMap[postureKey] || Config.postureMap.unknown;
    const movement = Config.movementMap[meta.movement] || Config.movementMap[0];

    dom.postureIcon.textContent = posture.icon;
    dom.sleepPosture.textContent =
      postureKey === "unknown"
        ? movement.label === "静态躺"
          ? "睡眠中（睡姿待识别）"
          : movement.label + "中"
        : posture.label;
    dom.sleepState.textContent =
      postureKey === "unknown" && movement.label !== "静态躺"
        ? movement.label
        : movement.label === "静态躺"
          ? "处于稳定睡眠状态"
          : movement.label;
    dom.sleepState.style.color =
      meta.movement === 2 ? "#fbbf24" : meta.movement === 1 ? "#fb923c" : "#22d3ee";

    dom.postureSource.textContent =
      (override && override.source) || meta.source || "样例标注";
    dom.postureConfidence.textContent = formatConfidence(
      override ? override.confidence : null,
      postureKey
    );
    dom.movementLabel.textContent = movement.label;
    dom.frameInfo.textContent = `${state.currentFrame} · ${formatTimeLabel()}`;
  }

  function formatConfidence(confidence, postureKey) {
    if (confidence == null) {
      return postureKey !== "unknown" ? "样例/规则" : "--";
    }
    if (confidence <= 1) return (confidence * 100).toFixed(1) + "%";
    return confidence.toFixed(1) + "%";
  }

  function buildDemoSegmentation(flat, sample) {
    const rows = sample ? sample.rows : Config.rows;
    const cols = sample ? sample.cols : Config.cols;
    const mask = new Array(rows * cols).fill(0);
    const maxValue = sample && sample.max_value ? sample.max_value : Math.max(...flat, 1);
    const threshold = Math.max(Config.contactThreshold, maxValue * 0.015);
    Config.regions.forEach((region, index) => {
      for (let r = region.rows[0]; r < region.rows[1]; r += 1) {
        for (let c = region.cols[0]; c < region.cols[1]; c += 1) {
          if ((flat[r * cols + c] || 0) > threshold) {
            mask[r * cols + c] = index + 1;
          }
        }
      }
    });
    return {
      mask,
      labels: { 0: "background", 1: "shoulder", 2: "back", 3: "waist", 4: "hip", 5: "thigh" },
      source: "区域矩形占位（演示）",
      demo: true,
    };
  }

  function updateSegmentationSource() {
    dom.segmentationSource.textContent = state.segmentation
      ? state.segmentation.source
      : "未接入";
  }

  function formatTimeLabel() {
    const now = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  }

  function updateHistory(flat, stats, record) {
    if (!record) return;
    const history = state.history;
    history.max.push(stats.maxPressure);
    history.mean.push(stats.meanPressure);
    history.contact.push(stats.contactAreaPercent);
    const pointValue =
      state.selectedPoint &&
      state.selectedPoint.row >= 0 &&
      state.selectedPoint.col >= 0
        ? flat[state.selectedPoint.row * Config.cols + state.selectedPoint.col] || 0
        : 0;
    history.point.push(pointValue);

    const keep = Config.historyLength;
    for (const key of Object.keys(history)) {
      if (history[key].length > keep) history[key].shift();
    }
  }

  function updateAirbags(flat, sample) {
    const zones = Config.airbagZones;
    const means = zones.map((zone) =>
      Metrics.rectMean(flat, Config.cols, zone.rows, zone.cols)
    );
    const maxMean = Math.max(1, ...means);
    const auto = dom.autoAirbag && dom.autoAirbag.checked;

    zones.forEach((zone, index) => {
      const target = means[index] / maxMean;
      const current = state.airbagStates[zone.id] || {
        level: 0,
        status: "stable",
        mean: 0,
      };
      if (auto) {
        const step = Math.max(0.04, Math.abs(target - current.level) * 0.45);
        const next =
          current.level < target
            ? Math.min(target, current.level + step)
            : Math.max(target, current.level - step);
        current.status =
          next > current.level + 0.005
            ? "inflating"
            : next < current.level - 0.005
              ? "deflating"
              : "stable";
        current.level = next;
      }
      current.mean = means[index];
      state.airbagStates[zone.id] = current;
    });

    state.airbagSampleMax = sample ? sample.max_value : 0;
  }

  function updateAirbagsFromLast() {
    if (!state.lastRendered) return;
    updateAirbags(state.lastRendered.flat, state.lastRendered.sample);
  }

  function resetAirbagStates() {
    state.airbagStates = {};
    Config.airbagZones.forEach((zone) => {
      state.airbagStates[zone.id] = { level: 0, status: "stable", mean: 0 };
    });
  }

  function updateHeatmapUI() {
    if (!state.lastRendered) return;
    const { flat, meta, sample } = state.lastRendered;
    Charts.drawHeatmap(dom.heatmapCanvas, {
      values: flat,
      maxValue: Config.maxHeatmapValue || sample.max_value || meta.maxValue || 1,
      showRegions: state.showRegions,
      showAirbags: state.showAirbags,
      segmentation: state.showRegions ? state.segmentation : null,
      selectedZone: state.selectedZoneId
        ? Config.airbagZones.find((zone) => zone.id === state.selectedZoneId)
        : null,
      selectedPoint: state.selectedPoint,
    });
    dom.colorbarMax.textContent = formatMetric(Config.maxHeatmapValue);
  }

  function drawAirbags() {
    Charts.drawAirbagGrid(dom.airbagCanvas, state.airbagStates, state.selectedZoneId);
    updateAirbagLegend();
  }

  function updateAirbagLegend() {
    const items = dom.airbagLegend.children;
    for (const item of items) {
      const zoneId = item.dataset.zoneId;
      const current = state.airbagStates[zoneId] || { level: 0, status: "stable" };
      const dot = item.querySelector(".dot");
      const pct = item.querySelector(".pct");
      dot.style.background = statusColor(current.status);
      pct.textContent = Math.round(current.level * 100) + "%";
      item.classList.toggle("active", zoneId === state.selectedZoneId);
    }
  }

  function statusColor(status) {
    if (status === "inflating") return "#4ade80";
    if (status === "deflating") return "#fb923c";
    return "#38bdf8";
  }

  function drawCharts() {
    const flat = state.lastRendered && state.lastRendered.flat;
    if (!flat) return;

    const pointValues = state.history.point;
    const pointMax = Math.max(...pointValues, 0) * 1.15;
    Charts.drawLineChart(
      dom.sensorChart,
      [{ color: "#38bdf8", values: pointValues }],
      {
        maxY: pointMax || 1,
        maxPoints: Config.historyLength,
        xLabel: "帧",
      }
    );

    Charts.drawLineChart(
      dom.metricChart,
      [
        { color: "#f87171", values: state.history.max },
        { color: "#22d3ee", values: state.history.mean },
        { color: "#a3e635", values: state.history.contact },
      ],
      {
        maxPoints: Config.historyLength,
        xLabel: "帧（最大/平均压力 ADC，接触面指数 %）",
      }
    );
  }

  function handleHeatmapMove(event) {
    const canvas = dom.heatmapCanvas;
    const rect = canvas.getBoundingClientRect();
    const cell = heatmapLogicalCell(event, rect);
    if (!cell || !state.lastRendered) {
      dom.cellTooltip.classList.add("hidden");
      return;
    }
    const flat = state.lastRendered.flat;
    const value = flat[cell.row * Config.cols + cell.col] || 0;
    dom.cellTooltip.textContent = `行 ${cell.row} · 列 ${cell.col}  压力 ${formatMetric(
      value
    )}`;
    const wrapRect = dom.heatmapWrap.getBoundingClientRect();
    dom.cellTooltip.style.left =
      Math.min(
        wrapRect.width - 130,
        Math.max(4, event.clientX - wrapRect.left + 10)
      ) + "px";
    dom.cellTooltip.style.top =
      Math.max(4, event.clientY - wrapRect.top - 34) + "px";
    dom.cellTooltip.classList.remove("hidden");
  }

  function heatmapLogicalCell(event, rect) {
    const x = ((event.clientX - rect.left) / rect.width) * Config.cols;
    const y = ((event.clientY - rect.top) / rect.height) * Config.rows;
    const row = Math.floor(y);
    const col = Math.floor(x);
    if (row < 0 || col < 0 || row >= Config.rows || col >= Config.cols) return null;
    return { row, col };
  }

  function handleHeatmapClick(event) {
    const rect = dom.heatmapCanvas.getBoundingClientRect();
    const cell = heatmapLogicalCell(event, rect);
    if (!cell) return;
    state.history.point = [];
    state.selectedPoint = cell;
    updateSensorInfo();
    if (state.lastRendered) {
      const value =
        state.lastRendered.flat[cell.row * Config.cols + cell.col] || 0;
      state.history.point.push(value);
      updateHeatmapUI();
      drawCharts();
    }
  }

  function selectAirbagZone(zoneId) {
    state.selectedZoneId = zoneId;
    const zone = Config.airbagZones.find((item) => item.id === zoneId);
    if (zone && state.lastRendered) {
      const best = Metrics.rectMaxPoint(
        state.lastRendered.flat,
        Config.cols,
        zone.rows,
        zone.cols
      );
      state.history.point = [];
      state.selectedPoint = { row: best.point[0], col: best.point[1] };
      state.history.point.push(best.value);
    }
    updateSensorInfo();
    updateHeatmapUI();
    drawAirbags();
    drawCharts();
  }

  function updateSensorInfo() {
    const point = state.selectedPoint;
    const zone = state.selectedZoneId
      ? Config.airbagZones.find((item) => item.id === state.selectedZoneId)
      : null;
    if (!point) {
      dom.sensorInfo.textContent = "点击热力图选择传感器点";
      return;
    }
    const value =
      state.lastRendered &&
      state.lastRendered.flat[point.row * Config.cols + point.col];
    dom.sensorInfo.innerHTML = `传感器点 行 <b>${point.row}</b> · 列 <b>${point.col}</b>${
      zone ? `（${zone.label}）` : ""
    }，当前压力 <b>${formatMetric(value)}</b>，历史曲线如下`;
  }

  function play() {
    state.playing = true;
    startTimer();
    updateLiveUI();
  }

  function pause(update = true) {
    state.playing = false;
    if (state.timerId) {
      clearInterval(state.timerId);
      state.timerId = null;
    }
    if (update) updateLiveUI();
  }

  function togglePlay() {
    if (state.playing) pause();
    else play();
  }

  function startTimer() {
    if (state.timerId) clearInterval(state.timerId);
    if (!state.playing || !state.sample) return;
    const fps = Number(dom.speedSelect.value) || 4;
    const interval = Math.max(30, Math.round(1000 / fps));
    state.timerId = setInterval(() => {
      if (state.seeking) return;
      stepFrame(1, true);
    }, interval);
  }

  function stepFrame(delta, record) {
    const sample = state.sample;
    if (!sample || !sample.frames.length) return;
    const next = (state.currentFrame + delta) % sample.frames.length;
    renderFrame(next, record);
  }

  function updateLiveUI() {
    dom.playBtn.textContent = state.playing ? "暂停" : "播放";
    dom.liveDot.classList.toggle("paused", !state.playing || state.externalMode);
    if (state.externalMode) {
      dom.liveText.textContent = "外部实时推送（等待下一帧）";
    } else if (state.sample) {
      dom.liveText.textContent = `本地样例回放 · ${state.sample.id}`;
    } else {
      dom.liveText.textContent = "未加载数据";
    }
  }

  function redrawLast() {
    if (!state.lastRendered) return;
    const oldPlaying = state.playing;
    updateAirbagsFromLast();
    updateHeatmapUI();
    drawAirbags();
    drawCharts();
    updateSensorInfo();
    if (oldPlaying !== state.playing) updateLiveUI();
  }

  function clearHistory() {
    state.history = { max: [], mean: [], contact: [], point: [] };
  }

  function formatMetric(value) {
    if (value == null || Number.isNaN(value)) return "--";
    if (value >= 100) return String(Math.round(value));
    return String(Math.round(value * 10) / 10);
  }

  function showNoDataHint() {
    const message = document.createElement("div");
    message.style.cssText =
      "padding:20px;color:#fbbf24;border:1px solid #fbbf24;border-radius:12px;margin:20px;";
    message.textContent =
      "未找到内置样例数据。请运行: python visualization/frontend/tools/export_sample.py <txt 路径> 后刷新页面。";
    document.querySelector(".dashboard").prepend(message);
  }

  function normalizePosture(value) {
    const alias = {
      supine: "supine",
      仰卧: "supine",
      prone: "prone",
      俯卧: "prone",
      left_lateral: "left_lateral",
      左侧卧: "left_lateral",
      right_lateral: "right_lateral",
      右侧卧: "right_lateral",
      unknown: "unknown",
      未知: "unknown",
    };
    return alias[value] || "unknown";
  }

  /** 睡姿识别结果（docs/api_docs.md 的 Posture Recognition Output）。 */
  function setPostureResult(payload) {
    if (!payload) return false;
    const posture = normalizePosture(
      payload.posture || payload.sleep_pose || payload.label || "unknown"
    );
    state.postureOverride = {
      posture,
      confidence: payload.confidence,
      source: payload.source || "睡姿识别接口",
    };
    if (state.lastRendered) {
      updateSleepUI(state.lastRendered.meta);
    }
    return true;
  }

  /** 身体部位划分结果（docs/api_docs.md 的 Body Segmentation Output）。 */
  function setSegmentationResult(payload) {
    if (!payload) return false;
    const maskRaw = payload.segmentation_mask || payload.mask;
    if (!maskRaw) return false;

    let mask;
    if (Array.isArray(maskRaw[0])) {
      mask = maskRaw.flat();
    } else {
      mask = Array.from(maskRaw);
    }
    state.demoSegmentation = false;
    state.segmentation = {
      mask,
      shape: payload.segmentation_shape || payload.shape,
      labels: payload.labels || {},
      source: payload.source || "身体划分接口",
      demo: false,
    };
    updateSegmentationSource();
    if (state.lastRendered) {
      updateHeatmapUI();
    }
    return true;
  }

  /** 实时可视化状态（docs/api_docs.md 的 Realtime Visualization State）。 */
  function setRealtimeState(payload) {
    if (!payload) return false;
    const stats = payload.pressure_stats;
    if (stats) {
      applyExternalStats(stats);
    }
    const airbagList = Array.isArray(payload.airbags) ? payload.airbags : [];
    if (payload.pressure_matrix || payload.pressureMatrix || payload.matrix) {
      pushFrame(payload);
    }
    if (airbagList.length) {
      for (const airbag of airbagList) {
        const zone = Config.airbagZones.find((item) => item.id === airbag.airbag_id);
        if (!zone) continue;
        const current = state.airbagStates[zone.id] || { level: 0, status: "stable" };
        if (airbag.pressure != null) {
          current.level = Math.max(0, Math.min(1, Number(airbag.pressure) || 0));
        }
        if (airbag.status) current.status = normalizeAirbagStatus(airbag.status);
        state.airbagStates[zone.id] = current;
      }
      drawAirbags();
    }
    return true;
  }

  function applyExternalStats(stats) {
    const mapping = [
      ["max", "max_pressure"],
      ["mean", "mean_pressure"],
    ];
    for (const [suffix, key] of mapping) {
      const value = stats[key] ?? stats[`${suffix}Pressure`];
      if (value != null) dom["metric" + cap(suffix)].textContent = formatMetric(value);
    }
    const contact =
      stats["contact_area_index"] ?? stats.contactAreaIndex ?? stats.contactIndex;
    if (contact != null) {
      dom.metricContact.textContent =
        (contact <= 1 ? contact * 100 : contact).toFixed(1) + "%";
    }
    const cells = stats["active_cells"] ?? stats.activeCells;
    if (cells != null) {
      dom.metricCells.textContent = `${cells} / ${Config.rows * Config.cols}`;
    }
  }

  function cap(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function normalizeAirbagStatus(status) {
    if (/充/.test(status) || status === "inflating") return "inflating";
    if (/放/.test(status) || status === "deflating") return "deflating";
    return "stable";
  }

  function pushFrame(frame, meta) {
    if (!frame) return false;
    const matrix = frame.pressure_matrix || frame.pressureMatrix || frame.matrix;
    const flat = matrix
      ? Metrics.flatten(matrix)
      : Metrics.flatten(frame.values || frame.data);
    if (!flat || !flat.length) return false;

    pause(false);
    state.externalMode = true;
    state.externalMeta = meta || {};
    state.sample = {
      id: "__external__",
      label: "外部实时帧",
      rows: Config.rows,
      cols: Config.cols,
      max_value: Math.max(...flat),
      posture: (meta && meta.posture) || "unknown",
      frames: [{ v: flat, m: (meta && meta.movement) || 0 }],
    };
    state.currentFrame = 0;
    dom.frameSlider.max = 0;
    dom.frameSlider.value = 0;
    dom.colorbarMax.textContent = formatMetric(Math.max(...flat));
    const movement =
      (meta && meta.movement) || (frame.movement && frame.movement === "turning" ? 2 : 0);
    renderPressureData(
      flat,
      {
        maxValue: Math.max(...flat),
        posture: state.sample.posture,
        movement,
        source: (meta && meta.source) || "外部实时",
      },
      true,
      state.sample
    );
    updateLiveUI();
    return true;
  }

  global.SmartMattressViewer = {
    loadSample,
    play,
    pause,
    pushFrame,
    setPressureFrame: pushFrame,
    setPostureResult,
    setSegmentationResult,
    setRealtimeState,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
