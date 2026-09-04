/**
 * 压力帧指标计算：最大/平均压力、接触面指数、区域与气囊分区统计。
 */
(function (global) {
  "use strict";

  function isFlat(values) {
    return values && Array.isArray(values) && values.length > 0 && typeof values[0] === "number";
  }

  /** 任意输入转一维数组（行优先）。 */
  function flatten(values) {
    if (isFlat(values)) return values;
    const flat = [];
    for (const row of values || []) {
      for (const value of row) flat.push(Number(value) || 0);
    }
    return flat;
  }

  /** 1D → 2D。 */
  function toMatrix(values, cols) {
    const flat = flatten(values);
    const matrix = [];
    for (let i = 0; i < flat.length; i += cols) {
      matrix.push(flat.slice(i, i + cols));
    }
    return matrix;
  }

  function pressureStats(values, rows, cols, threshold) {
    const flat = flatten(values);
    let sum = 0;
    let max = 0;
    let maxIndex = 0;
    let activeCount = 0;
    let activeSum = 0;

    for (let i = 0; i < flat.length; i += 1) {
      const value = flat[i];
      sum += value;
      if (value > max) {
        max = value;
        maxIndex = i;
      }
      if (value > threshold) {
        activeCount += 1;
        activeSum += value;
      }
    }

    const totalCells = rows * cols;
    const mean = sum / totalCells;
    const meanActive = activeCount > 0 ? activeSum / activeCount : 0;
    const contactAreaIndex = activeCount / totalCells;
    const maxRow = Math.floor(maxIndex / cols);
    const maxCol = maxIndex % cols;

    return {
      maxPressure: max,
      meanPressure: mean,
      meanActivePressure: meanActive,
      contactAreaIndex,
      contactAreaPercent: contactAreaIndex * 100,
      activeCells: activeCount,
      totalCells,
      maxRow,
      maxCol,
    };
  }

  function rectMean(flat, cols, rowRange, colRange) {
    let sum = 0;
    let count = 0;
    for (let r = rowRange[0]; r < rowRange[1]; r += 1) {
      for (let c = colRange[0]; c < colRange[1]; c += 1) {
        sum += flat[r * cols + c] || 0;
        count += 1;
      }
    }
    return count ? sum / count : 0;
  }

  function rectMaxPoint(flat, cols, rowRange, colRange) {
    let max = -Infinity;
    let point = [rowRange[0], colRange[0]];
    for (let r = rowRange[0]; r < rowRange[1]; r += 1) {
      for (let c = colRange[0]; c < colRange[1]; c += 1) {
        const value = flat[r * cols + c] || 0;
        if (value > max) {
          max = value;
          point = [r, c];
        }
      }
    }
    return { point, value: max };
  }

  global.SmartMattressMetrics = {
    flatten,
    toMatrix,
    pressureStats,
    rectMean,
    rectMaxPoint,
  };
})(window);
