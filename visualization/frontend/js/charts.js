/**
 * Canvas 绘制：压力热力图、气囊状态面板、折线图。
 */
(function (global) {
  "use strict";

  const Config = global.SmartMattressConfig;
  const Palette = global.SmartMattressPalette;
  const Metrics = global.SmartMattressMetrics;

  const HEATMAP_CELL = 18;

  function roundRectPath(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }

  function drawHeatmap(canvas, options) {
    const {
      values,
      maxValue,
      showRegions,
      showAirbags,
      segmentation,
      selectedZone,
      selectedPoint,
    } = options;
    const rows = Config.rows;
    const cols = Config.cols;
    const cell = HEATMAP_CELL;
    canvas.width = cols * cell;
    canvas.height = rows * cell;
    const ctx = canvas.getContext("2d");

    ctx.fillStyle = "#070d18";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // 先生成 44x24 的离散采样图，再平滑插值放大，
    // 使相邻色块自然融合，不再显示单元格边界。
    const source = document.createElement("canvas");
    source.width = cols;
    source.height = rows;
    const sourceCtx = source.getContext("2d");
    const background = [7, 13, 24];
    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        const value = values[r * cols + c] || 0;
        let red = background[0];
        let green = background[1];
        let blue = background[2];
        if (value > 0 && maxValue > 0) {
          const ratio = Math.min(1, value / maxValue);
          const index = Math.min(255, Math.max(0, Math.round(ratio * 255)));
          const [pr, pg, pb] = Palette.palette[index];
          if (ratio < 0.015) {
            // 极低值向背景色靠拢，避免床面被色带底色污染
            const alpha = 0.35 + ratio * 20;
            red = Math.round(background[0] * (1 - alpha) + pr * alpha);
            green = Math.round(background[1] * (1 - alpha) + pg * alpha);
            blue = Math.round(background[2] * (1 - alpha) + pb * alpha);
          } else {
            red = pr;
            green = pg;
            blue = pb;
          }
        }
        sourceCtx.fillStyle = `rgb(${red},${green},${blue})`;
        sourceCtx.fillRect(c, r, 1, 1);
      }
    }
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(source, 0, 0, cols, rows, 0, 0, canvas.width, canvas.height);

    if (showAirbags) {
      ctx.lineWidth = 1.4;
      for (const zone of Config.airbagZones) {
        const active = selectedZone && zone.id === selectedZone.id;
        ctx.strokeStyle = active ? "rgba(251,191,36,0.95)" : "rgba(255,255,255,0.28)";
        const x = zone.cols[0] * cell;
        const y = zone.rows[0] * cell;
        const w = (zone.cols[1] - zone.cols[0]) * cell;
        const h = (zone.rows[1] - zone.rows[0]) * cell;
        ctx.strokeRect(x + 0.5, y + 0.5, w, h);
        if (active) {
          ctx.fillStyle = "rgba(251,191,36,0.15)";
          ctx.fillRect(x + 0.5, y + 0.5, w, h);
        }
      }
    }

    if (showRegions && segmentation && segmentation.mask) {
      const colors = [
        "",
        "rgba(244,114,182,0.28)",
        "rgba(167,139,250,0.28)",
        "rgba(56,189,248,0.28)",
        "rgba(52,211,153,0.28)",
        "rgba(251,191,36,0.28)",
        "rgba(251,113,133,0.28)",
        "rgba(96,165,250,0.28)",
      ];
      const mask = segmentation.mask;
      for (let r = 0; r < rows; r += 1) {
        for (let c = 0; c < cols; c += 1) {
          const label = mask[r * cols + c] || 0;
          if (!label) continue;
          const color = colors[Math.min(label, colors.length - 1)];
          ctx.fillStyle = color;
          ctx.fillRect(c * cell, r * cell, cell + 0.5, cell + 0.5);
        }
      }
      ctx.strokeStyle = "rgba(255,255,255,0.5)";
      ctx.lineWidth = 1;
      const edges = new Set();
      for (let r = 0; r < rows; r += 1) {
        for (let c = 0; c < cols; c += 1) {
          const label = mask[r * cols + c] || 0;
          if (!label) continue;
          if (
            r === 0 ||
            c === 0 ||
            (mask[(r - 1) * cols + c] || 0) !== label ||
            (mask[(r + 1) * cols + c] || 0) !== label ||
            (mask[r * cols + c - 1] || 0) !== label ||
            (mask[r * cols + c + 1] || 0) !== label
          ) {
            edges.add(`${r},${c}`);
          }
        }
      }
      ctx.beginPath();
      for (const key of edges) {
        const [r, c] = key.split(",").map(Number);
        ctx.rect(c * cell + 0.5, r * cell + 0.5, cell, cell);
      }
      ctx.stroke();
    } else if (showRegions) {
      ctx.font = "500 12px 'Segoe UI', 'Microsoft YaHei', sans-serif";
      for (const region of Config.regions) {
        const x = region.cols[0] * cell;
        const y = region.rows[0] * cell;
        const w = (region.cols[1] - region.cols[0]) * cell;
        const h = (region.rows[1] - region.rows[0]) * cell;
        ctx.strokeStyle = region.color;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x + 1, y + 1, w - 2, h - 2);
        ctx.fillStyle = region.color;
        ctx.globalAlpha = 0.18;
        ctx.fillRect(x + 1, y + 1, w - 2, h - 2);
        ctx.globalAlpha = 1;
        if (w > 60 && h > 22) {
          ctx.fillStyle = region.color;
          ctx.fillText(region.name, x + 5, y + 14);
        }
      }
    }

    if (selectedPoint) {
      const x = selectedPoint.col * cell + cell / 2;
      const y = selectedPoint.row * cell + cell / 2;
      ctx.beginPath();
      ctx.arc(x, y, cell * 0.42, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(255,255,255,0.92)";
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#111827";
      ctx.stroke();
    }
  }

  function prepareCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const cssWidth = Math.max(10, rect.width);
    const cssHeight = Math.max(10, rect.height);
    const width = Math.round(cssWidth * dpr);
    const height = Math.round(cssHeight * dpr);
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, cssWidth, cssHeight };
  }

  function drawAirbagGrid(canvas, states, selectedZoneId) {
    const zones = Config.airbagZones;
    const { ctx, cssWidth, cssHeight } = prepareCanvas(canvas);
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    const cols = 3;
    const rows = zones.length / cols;
    const gap = 4;
    const pad = 6;
    const topPad = 12;
    const cellW = (cssWidth - pad * 2 - gap * (cols - 1)) / cols;
    const cellH = (cssHeight - pad * 2 - topPad - gap * (rows - 1)) / rows;
    ctx.font = "10px 'Segoe UI', 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";

    zones.forEach((zone, index) => {
      const rowIndex = Math.floor(index / cols);
      const colIndex = index % cols;
      const x = pad + colIndex * (cellW + gap);
      const y = pad + topPad + rowIndex * (cellH + gap);
      const state = states[zone.id] || { level: 0, status: "stable" };
      const active = selectedZoneId === zone.id;

      ctx.fillStyle = "#0a1322";
      roundRectPath(ctx, x, y, cellW, cellH, 5);
      ctx.fill();

      // 充气高度：level 0~1
      const level = Math.max(0, Math.min(1, state.level || 0));
      if (level > 0.02) {
        const fillH = Math.max(3, (cellH - 3) * level);
        const color =
          state.status === "inflating"
            ? "rgba(74,222,128,0.9)"
            : state.status === "deflating"
              ? "rgba(251,146,60,0.9)"
              : "rgba(56,189,248,0.85)";
        ctx.fillStyle = color;
        roundRectPath(ctx, x + 1.5, y + cellH - fillH + 1, cellW - 3, fillH - 2, 4);
        ctx.fill();
      }

      ctx.strokeStyle = active ? "#fbbf24" : "#2b405f";
      ctx.lineWidth = active ? 2 : 1;
      roundRectPath(ctx, x + 0.5, y + 0.5, cellW - 1, cellH - 1, 5);
      ctx.stroke();

      ctx.fillStyle = "#c6d6ea";
      const label = active ? zone.label : zone.label.replace("·", "");
      const fontSize = cellW > 70 ? 11 : 9;
      ctx.font = `${fontSize}px 'Segoe UI', 'Microsoft YaHei', sans-serif`;
      ctx.fillText(label, x + cellW / 2, y + cellH / 2 - 5);
      ctx.fillStyle = "#7f96b3";
      ctx.font = "9px 'Segoe UI', sans-serif";
      ctx.fillText(
        `${Math.round(level * 100)}% · ${statusText(state.status)}`,
        x + cellW / 2,
        y + cellH / 2 + 6
      );
    });

    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
  }

  function statusText(status) {
    if (status === "inflating") return "充气";
    if (status === "deflating") return "放气";
    return "保持";
  }

  function drawLineChart(canvas, series, options) {
    const { ctx, cssWidth, cssHeight } = prepareCanvas(canvas);
    const opts = options || {};
    const margin = opts.margin || { left: 44, right: 10, top: 8, bottom: 20 };
    const plotW = cssWidth - margin.left - margin.right;
    const plotH = cssHeight - margin.top - margin.bottom;
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    let maxY = opts.maxY || 0;
    const allValues = series.flatMap((s) => s.values || []);
    if (!maxY && allValues.length) {
      maxY = Math.max(...allValues) * 1.15;
    }
    if (!maxY) maxY = 1;

    // 网格与纵轴
    ctx.strokeStyle = "rgba(255,255,255,0.07)";
    ctx.fillStyle = "#7f96b3";
    ctx.font = "10px 'Segoe UI', sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i <= 4; i += 1) {
      const y = margin.top + (plotH * i) / 4;
      ctx.beginPath();
      ctx.moveTo(margin.left, y);
      ctx.lineTo(cssWidth - margin.right, y);
      ctx.stroke();
      const value = maxY * (1 - i / 4);
      ctx.fillText(formatNumber(value), margin.left - 5, y);
    }

    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(opts.xLabel || "", margin.left, cssHeight - 6);

    // 数据线
    const maxPoints = opts.maxPoints || Infinity;
    for (const s of series) {
      const values = (s.values || []).slice(-maxPoints);
      if (!values.length) continue;
      ctx.beginPath();
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.width || 1.8;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      for (let i = 0; i < values.length; i += 1) {
        const x =
          values.length === 1
            ? margin.left
            : margin.left + (plotW * i) / (values.length - 1);
        const ratio = Math.max(0, Math.min(1, values[i] / maxY));
        const y = margin.top + plotH * (1 - ratio);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
  }

  function formatNumber(value) {
    if (value >= 100) return String(Math.round(value));
    if (value >= 10) return value.toFixed(1);
    return value.toFixed(2);
  }

  global.SmartMattressCharts = {
    drawHeatmap,
    drawAirbagGrid,
    drawLineChart,
  };
})(window);
