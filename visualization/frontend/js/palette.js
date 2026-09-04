/**
 * turbo 风格色带（与数据集说明中 matplotlib turbo 近似）。
 * 0 → 深紫/黑，中低压力 → 青/绿，高压 → 黄/橙/红。
 */
(function (global) {
  "use strict";

  let paletteCache = null;

  const STOPS = [
    [0.0, "#30123b"],
    [1 / 15, "#4145ab"],
    [2 / 15, "#4675ed"],
    [3 / 15, "#39a2fc"],
    [4 / 15, "#1bcfd4"],
    [5 / 15, "#24eca6"],
    [6 / 15, "#61fc6c"],
    [7 / 15, "#a4fc3b"],
    [8 / 15, "#d1e834"],
    [9 / 15, "#f3c63a"],
    [10 / 15, "#fe9b2d"],
    [11 / 15, "#f36315"],
    [12 / 15, "#d93806"],
    [13 / 15, "#b11901"],
    [14 / 15, "#7a0402"],
    [1.0, "#1f0000"],
  ];

  function palette() {
    if (paletteCache) return paletteCache;
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 1;
    const ctx = canvas.getContext("2d");
    const gradient = ctx.createLinearGradient(0, 0, 256, 0);
    for (const [position, color] of STOPS) {
      gradient.addColorStop(position, color);
    }
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 256, 1);
    const pixels = ctx.getImageData(0, 0, 256, 1).data;
    paletteCache = [];
    for (let i = 0; i < 256; i += 1) {
      paletteCache.push([pixels[i * 4], pixels[i * 4 + 1], pixels[i * 4 + 2]]);
    }
    return paletteCache;
  }

  function ratioToColor(ratio, alpha) {
    const pal = palette();
    const index = Math.max(0, Math.min(255, Math.round(ratio * 255)));
    const [r, g, b] = pal[index];
    return alpha == null ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${alpha})`;
  }

  global.SmartMattressPalette = {
    get palette() {
      return palette();
    },
    ratioToColor,
    drawColorbar: function (canvas) {
      const ctx = canvas.getContext("2d");
      const pal = palette();
      for (let x = 0; x < canvas.width; x += 1) {
        const index = Math.floor((x / canvas.width) * 255);
        const [r, g, b] = pal[index];
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fillRect(x, 0, 1, canvas.height);
      }
    },
  };
})(window);
