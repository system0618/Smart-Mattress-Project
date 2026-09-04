/**
 * 智能床垫可视化 - 常量与布局配置
 *
 * 说明：
 * - rows/cols 来自新版 44 行 x 24 列压力传感器阵列；
 * - regions 参考新版“区域划分数据”中 5 个身体部位矩形（x 为列，y 为行）；
 * - airbagZones 为演示用虚拟分区（肩背/腰/臀/大腿 × 左/中/右）。
 *   真实“气囊-传感器 对应关系”确认后，只需在本文件替换 airbagZones。
 */
(function (global) {
  "use strict";

  const ROWS = 44;
  const COLS = 24;

  const Config = {
    rows: ROWS,
    cols: COLS,
    pressureUnit: "ADC",
    contactThreshold: 2.0, // 原始 ADC 压力下认为“接触”的阈值
    maxHeatmapValue: 300,  // 热力图统一色标上限，按课程要求固定为 300

    postureMap: {
      supine: { label: "仰卧", icon: "🙂" },
      prone: { label: "俯卧", icon: "😴" },
      left_lateral: { label: "左侧卧", icon: "🛌" },
      right_lateral: { label: "右侧卧", icon: "🛌" },
      unknown: { label: "识别中…", icon: "🛏️" },
    },

    movementMap: {
      0: { label: "静态躺", cls: "static" },
      1: { label: "体动", cls: "moving" },
      2: { label: "翻身", cls: "turning" },
    },

    // 区域坐标 [start, end)，来自新版区域划分数据样例
    regions: [
      { id: "shoulder", name: "肩部", rows: [3, 8], cols: [6, 18], color: "#f472b6" },
      { id: "back", name: "背部", rows: [8, 13], cols: [6, 18], color: "#a78bfa" },
      { id: "waist", name: "腰部", rows: [13, 18], cols: [6, 18], color: "#38bdf8" },
      { id: "hip", name: "臀部", rows: [18, 27], cols: [5, 20], color: "#34d399" },
      { id: "thigh", name: "大腿", rows: [27, 36], cols: [5, 20], color: "#fbbf24" },
    ],

    airbagZones: buildAirbagZones(),

    historyLength: 120,
  };

  function buildAirbagZones() {
    const bands = [
      { id: "upper", name: "肩背", rows: [3, 13], cols: [6, 18] },
      { id: "waist", name: "腰", rows: [13, 18], cols: [6, 18] },
      { id: "hip", name: "臀", rows: [18, 27], cols: [5, 20] },
      { id: "thigh", name: "大腿", rows: [27, 36], cols: [5, 20] },
    ];
    const sides = ["左", "中", "右"];
    const zones = [];
    let index = 1;

    for (const band of bands) {
      const [colStart, colEnd] = band.cols;
      const span = colEnd - colStart;
      sides.forEach((side, sideIndex) => {
        const s = colStart + Math.floor((span * sideIndex) / sides.length);
        const e =
          sideIndex === sides.length - 1
            ? colEnd
            : colStart + Math.floor((span * (sideIndex + 1)) / sides.length);
        zones.push({
          id: "zone_" + String(index++).padStart(2, "0"),
          label: band.name + "·" + side,
          bandId: band.id,
          rows: band.rows,
          cols: [s, e],
          relatedPoints: relatedPoints(s, e, band.rows),
        });
      });
    }
    return zones;
  }

  function relatedPoints(colStart, colEnd, rowRange) {
    const points = [];
    // 四个角 + 中心，用于“气囊对应的传感器点”示意
    const rows = [rowRange[0], Math.floor((rowRange[0] + rowRange[1] - 1) / 2), rowRange[1] - 1];
    const cols = [colStart, Math.floor((colStart + colEnd - 1) / 2), colEnd - 1];
    for (const r of rows) {
      for (const c of cols) points.push([r, c]);
    }
    return points;
  }

  global.SmartMattressConfig = Config;
})(window);
