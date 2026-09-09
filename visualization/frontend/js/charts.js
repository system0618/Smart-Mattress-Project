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

  // ---- 区域轮廓（平滑彩色线条）----

  function regionLabelColor(label) {
    const region = Config.regions[label - 1];
    return region ? region.color : "#64748b";
  }

  /** 收集某个 label 的所有边界线段（44x24 网格坐标，线段端点为整数）。 */
  function collectBoundarySegments(mask, rows, cols, label) {
    const edgeMap = new Map();
    const inside = (r, c) =>
      r >= 0 && r < rows && c >= 0 && c < cols && (mask[r * cols + c] || 0) === label;
    const addEdge = (x1, y1, x2, y2) => {
      const p1 = `${x1},${y1}`;
      const p2 = `${x2},${y2}`;
      const key = p1 < p2 ? p1 + "|" + p2 : p2 + "|" + p1;
      if (!edgeMap.has(key)) edgeMap.set(key, [x1, y1, x2, y2]);
    };

    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        if (!inside(r, c)) continue;
        if (!inside(r - 1, c)) addEdge(c, r, c + 1, r); // 上边界
        if (!inside(r + 1, c)) addEdge(c, r + 1, c + 1, r + 1); // 下边界
        if (!inside(r, c - 1)) addEdge(c, r, c, r + 1); // 左边界
        if (!inside(r, c + 1)) addEdge(c + 1, r, c + 1, r + 1); // 右边界
      }
    }
    return Array.from(edgeMap.values());
  }

  /** 把首尾相连的边界线段拼成封闭环。 */
  function traceBoundaryLoops(segments) {
    const items = segments.map((seg) => ({ x1: seg[0], y1: seg[1], x2: seg[2], y2: seg[3], used: false }));
    const buckets = new Map();
    const keyOf = (x, y) => `${x},${y}`;
    for (const item of items) {
      for (const point of [
        [item.x1, item.y1],
        [item.x2, item.y2],
      ]) {
        const key = keyOf(point[0], point[1]);
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push(item);
      }
    }

    const loops = [];
    for (const first of items) {
      if (first.used) continue;
      first.used = true;
      const points = [
        [first.x1, first.y1],
        [first.x2, first.y2],
      ];
      let curX = first.x2;
      let curY = first.y2;
      const startX = first.x1;
      const startY = first.y1;
      let guard = 0;
      while (!(curX === startX && curY === startY)) {
        const candidates = buckets.get(keyOf(curX, curY)) || [];
        let next = null;
        for (const candidate of candidates) {
          if (candidate.used) continue;
          if (
            (candidate.x1 === curX && candidate.y1 === curY) ||
            (candidate.x2 === curX && candidate.y2 === curY)
          ) {
            next = candidate;
            break;
          }
        }
        if (!next) break;
        next.used = true;
        const isFromStart = next.x1 === curX && next.y1 === curY;
        curX = isFromStart ? next.x2 : next.x1;
        curY = isFromStart ? next.y2 : next.y1;
        points.push([curX, curY]);
        guard += 1;
        if (guard > segments.length * 4) break;
      }
      if (
        points.length > 1 &&
        points[0][0] === points[points.length - 1][0] &&
        points[0][1] === points[points.length - 1][1]
      ) {
        points.pop();
      }
      loops.push(points);
    }
    return loops;
  }

  function loopCentroid(points) {
    let x = 0;
    let y = 0;
    for (const point of points) {
      x += point[0];
      y += point[1];
    }
    return [x / points.length, y / points.length];
  }

  function shrinkTowardCentroid(points, factor) {
    const [cx, cy] = loopCentroid(points);
    return points.map((point) => [
      cx + (point[0] - cx) * factor,
      cy + (point[1] - cy) * factor,
    ]);
  }

  /** Chaikin 细分平滑，把网格直角边变成圆润曲线。 */
  function smoothClosedLoop(points, iterations) {
    if (points.length < 3) return points;
    let current = points;
    for (let iteration = 0; iteration < iterations; iteration += 1) {
      const next = [];
      for (let i = 0; i < current.length; i += 1) {
        const a = current[i];
        const b = current[(i + 1) % current.length];
        next.push([
          a[0] * 0.75 + b[0] * 0.25,
          a[1] * 0.75 + b[1] * 0.25,
        ]);
        next.push([
          a[0] * 0.25 + b[0] * 0.75,
          a[1] * 0.25 + b[1] * 0.75,
        ]);
      }
      current = next;
    }
    return current;
  }

  function isUsableLoop(points) {
    if (points.length < 4) return false;
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const point of points) {
      minX = Math.min(minX, point[0]);
      maxX = Math.max(maxX, point[0]);
      minY = Math.min(minY, point[1]);
      maxY = Math.max(maxY, point[1]);
    }
    const width = maxX - minX;
    const height = maxY - minY;
    return width >= 1.5 || height >= 1.5;
  }

  function drawRegionOutline(ctx, points, cell, color, fillAlpha) {
    const scaled = shrinkTowardCentroid(points, 0.955);
    const smooth = smoothClosedLoop(scaled, 2);
    if (smooth.length < 3) return;
    ctx.beginPath();
    ctx.moveTo(smooth[0][0] * cell, smooth[0][1] * cell);
    for (let i = 1; i < smooth.length; i += 1) {
      ctx.lineTo(smooth[i][0] * cell, smooth[i][1] * cell);
    }
    ctx.closePath();
    if (fillAlpha > 0) {
      ctx.globalAlpha = fillAlpha;
      ctx.fillStyle = color;
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();
  }

  function labelBounds(mask, rows, cols, label) {
    let minRow = Infinity;
    let maxRow = -Infinity;
    let minCol = Infinity;
    let maxCol = -Infinity;
    for (let r = 0; r < rows; r += 1) {
      for (let c = 0; c < cols; c += 1) {
        if ((mask[r * cols + c] || 0) !== label) continue;
        minRow = Math.min(minRow, r);
        maxRow = Math.max(maxRow, r);
        minCol = Math.min(minCol, c);
        maxCol = Math.max(maxCol, c);
      }
    }
    if (minRow === Infinity) return null;
    return { minRow, maxRow, minCol, maxCol };
  }

  /** 在线框左侧绘制部位名称（带深色底、部位色文字）。 */
  function drawRegionNameLabels(ctx, mask, rows, cols, cell) {
    const canvasWidth = ctx.canvas.width;
    const canvasHeight = ctx.canvas.height;
    ctx.font = "600 13px 'Segoe UI', 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    for (let label = 1; label <= Config.regions.length; label += 1) {
      const region = Config.regions[label - 1];
      const bounds = labelBounds(mask, rows, cols, label);
      if (!bounds) continue;
      const lineLeft = bounds.minCol * cell;
      const centerY = ((bounds.minRow + bounds.maxRow + 1) / 2) * cell;
      const textWidth = ctx.measureText(region.name).width;
      const padX = 5;
      const padY = 3;
      const chipHeight = 13 + padY * 2;
      let chipRight = Math.min(canvasWidth - 3, lineLeft - 4);
      let chipLeft = chipRight - textWidth - padX * 2;
      if (chipLeft < 2) {
        chipLeft = 2;
        chipRight = Math.min(canvasWidth - 2, chipLeft + textWidth + padX * 2);
      }
      const chipTop = Math.max(2, Math.min(canvasHeight - chipHeight - 2, centerY - chipHeight / 2));
      ctx.fillStyle = "rgba(7, 13, 24, 0.78)";
      roundRectPath(ctx, chipLeft, chipTop, chipRight - chipLeft, chipHeight, 5);
      ctx.fill();
      ctx.fillStyle = region.color;
      ctx.fillText(region.name, chipLeft + padX, chipTop + chipHeight / 2);
    }
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
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
      showRegionLabels = true,
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
      const mask = segmentation.mask;
      for (let label = 1; label <= Config.regions.length; label += 1) {
        const color = regionLabelColor(label);
        const segments = collectBoundarySegments(mask, rows, cols, label);
        const loops = traceBoundaryLoops(segments);
        for (const loop of loops) {
          if (!isUsableLoop(loop)) continue;
          drawRegionOutline(ctx, loop, cell, color, 0.16);
        }
      }
      if (showRegionLabels) {
        drawRegionNameLabels(ctx, mask, rows, cols, cell);
      }
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
        if (showRegionLabels && w > 60 && h > 22) {
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

      ctx.fillStyle = "#ffffff";
      roundRectPath(ctx, x, y, cellW, cellH, 5);
      ctx.fill();

      // 充气高度：level 0~1
      const level = Math.max(0, Math.min(1, state.level || 0));
      if (level > 0.02) {
        const fillH = Math.max(3, (cellH - 3) * level);
        const color =
          state.status === "inflating"
            ? "rgba(5,150,105,0.9)"
            : state.status === "deflating"
              ? "rgba(234,88,12,0.9)"
              : "rgba(2,132,199,0.9)";
        ctx.fillStyle = color;
        roundRectPath(ctx, x + 1.5, y + cellH - fillH + 1, cellW - 3, fillH - 2, 4);
        ctx.fill();
      }

      ctx.strokeStyle = active ? "#d97706" : "#c2d3e5";
      ctx.lineWidth = active ? 2 : 1;
      roundRectPath(ctx, x + 0.5, y + 0.5, cellW - 1, cellH - 1, 5);
      ctx.stroke();

      ctx.fillStyle = "#334155";
      const label = active ? zone.label : zone.label.replace("·", "");
      const fontSize = cellW > 70 ? 11 : 9;
      ctx.font = `${fontSize}px 'Segoe UI', 'Microsoft YaHei', sans-serif`;
      ctx.fillText(label, x + cellW / 2, y + cellH / 2 - 5);
      ctx.fillStyle = "#64748b";
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

  /**
   * 气囊侧视图：按 肩/背/腰/臀 横放四个扁气囊（宽 > 高），
   * 不画人形与气囊框线，仅用统一的 #32b5ff 填充表示实时支撑程度。
   * 每个大区域取左/中/右分区中当前支撑程度最高的气囊作为代表。
   */
  function drawAirbagSideView(canvas, states) {
    const zones = Config.airbagZones;
    const { ctx, cssWidth, cssHeight } = prepareCanvas(canvas);
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    const bands = [];
    const bandMap = new Map();
    for (const zone of zones) {
      if (!bandMap.has(zone.bandId)) {
        const band = { id: zone.bandId, name: zone.label.split("·")[0], zones: [] };
        bandMap.set(zone.bandId, band);
        bands.push(band);
      }
      bandMap.get(zone.bandId).zones.push(zone);
    }
    if (!bands.length) return;

    const count = bands.length;
    const marginX = 16;
    const bagGap = 10;
    const bagW = (cssWidth - marginX * 2 - bagGap * (count - 1)) / count;
    const centers = [];
    for (let i = 0; i < count; i += 1) {
      centers.push(marginX + bagW * (i + 0.5) + bagGap * i);
    }

    const bagBottomY = cssHeight - 32;
    const maxBagH = Math.min(64, bagBottomY - 14);

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    bands.forEach((band, index) => {
      const centerX = centers[index];
      const bagX = centerX - bagW / 2;

      let support = null;
      for (const zone of band.zones) {
        const current = states[zone.id] || { level: 0, status: "stable" };
        if (!support || (current.level || 0) > (support.level || 0)) {
          support = current;
        }
      }
      support = support || { level: 0, status: "stable" };
      const level = Math.max(0, Math.min(1, support.level || 0));

      // 仅填充，不画框线；高度表示支撑程度
      if (level > 0.02) {
        const fillH = Math.max(4, (maxBagH - 3) * level);
        const fillY = bagBottomY - fillH + 1;
        ctx.fillStyle = "#32b5ff";
        roundRectPath(ctx, bagX, fillY, bagW, fillH - 2, 8);
        ctx.fill();
      }

      const regionName = band.name.replace(/部$/, "") || band.name;
      const labelText = `${regionName} ${Math.round(level * 100)}%`;
      ctx.font = "700 10px 'Segoe UI', 'Microsoft YaHei', sans-serif";
      const labelWidth = ctx.measureText(labelText).width;
      ctx.fillStyle = "rgba(15,42,72,0.88)";
      roundRectPath(ctx, centerX - labelWidth / 2 - 6, cssHeight - 21, labelWidth + 12, 15, 7);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.fillText(labelText, centerX, cssHeight - 13);
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
    ctx.strokeStyle = "rgba(15,42,72,0.09)";
    ctx.fillStyle = "#64748b";
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
    drawAirbagSideView,
    drawLineChart,
  };
})(window);
