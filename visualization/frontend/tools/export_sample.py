# -*- coding: utf-8 -*-
"""把智能床垫压力阵列 txt 导出为前端可回放的 JS 样例。

用法示例（在本目录下执行）：

    python tools/export_sample.py ^
        "D:/.../睡姿 区域划分data/睡姿数据/dgs/dgs_动态一.txt" ^
        "D:/.../睡姿 区域划分data/睡姿数据/dgs/dgs_1.txt"

默认生成 ../data/samples.js，前端 index.html 会自动读取该文件。
生成的样例体积很小（仅演示帧），完整数据集不需要提交到 Git。
"""

import argparse
import json
import os
import re


SENSOR_COLS = 24
FRAME_ROWS = 44

POSTURE_BY_ACTION = {
    **{action: "supine" for action in range(1, 7)},
    **{action: "prone" for action in range(7, 10)},
    **{action: "left_lateral" for action in range(10, 16)},
    **{action: "right_lateral" for action in range(16, 22)},
}

POSTURE_CN = {
    "supine": "仰卧",
    "prone": "俯卧",
    "left_lateral": "左侧卧",
    "right_lateral": "右侧卧",
    "unknown": "未知",
}


def parse_txt(path):
    """解析一个 txt：返回 44x24 帧列表，每帧附带动态标签 m(0静态/1体动/2翻身)。"""
    frames = []
    current_rows = []
    current_label = 0

    def push_completed(movement=None):
        if len(current_rows) == FRAME_ROWS:
            values = []
            for row in current_rows:
                values.extend(row)
            frames.append(
                {"m": current_label if movement is None else movement, "v": values}
            )
            current_rows.clear()
            return True
        return False

    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) == 1 and parts[0] in ("0", "1", "2"):
                # 动态文件在每帧结束后紧跟 0/1/2 标签行，表示刚完成这一帧的状态
                movement = int(parts[0])
                if not push_completed(movement):
                    current_label = movement
                continue
            if len(parts) != SENSOR_COLS:
                continue
            if len(current_rows) == FRAME_ROWS:
                push_completed()
            current_rows.append([int(x) for x in parts])

    push_completed()
    if not frames:
        raise ValueError("未解析到 44 行 x 24 列的帧数据: " + path)
    return frames


def sample_meta(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    action_match = re.search(r"_(\d+)$", stem)
    if "动态" in stem:
        action = None
        posture = "unknown"
    elif action_match:
        action = int(action_match.group(1))
        posture = POSTURE_BY_ACTION.get(action, "unknown")
    else:
        action = None
        posture = "unknown"
    user = re.sub(r"_\d+$", "", stem).split("_")[0]
    return {
        "stem": stem,
        "user": user,
        "action": action,
        "posture": posture,
        "display": f"{stem} · {POSTURE_CN.get(posture, '动态')}",
    }


def build_sample(path, step, max_frames):
    frames = parse_txt(path)
    if step and step > 1:
        frames = frames[::step]
    if max_frames:
        frames = frames[:max_frames]
    meta = sample_meta(path)
    max_value = 0
    for frame in frames:
        max_value = max(max_value, max(frame["v"]))
    return {
        "id": meta["stem"],
        "label": meta["display"],
        "user_id": meta["user"],
        "action": meta["action"],
        "posture": meta["posture"],
        "rows": FRAME_ROWS,
        "cols": SENSOR_COLS,
        "has_movement_label": any(f["m"] != 0 for f in frames),
        "max_value": max_value,
        "frames": [
            {"i": idx * (step or 1), "m": frame["m"], "v": frame["v"]}
            for idx, frame in enumerate(frames)
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="一个或多个原始 txt 文件路径")
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(__file__), "..", "data", "samples.js"),
        help="输出 JS 文件路径",
    )
    parser.add_argument("--step", type=int, default=2, help="隔多少帧取一帧，默认 2")
    parser.add_argument("--max-frames", type=int, default=0, help="每个文件最多导出帧数")
    args = parser.parse_args()

    samples = [build_sample(p, args.step, args.max_frames) for p in args.inputs]
    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    body = (
        "/* 本文件由 tools/export_sample.py 自动生成，请勿手工编辑。 */\n"
        "window.SMART_MATTRESS_SAMPLES = "
        + json.dumps(samples, ensure_ascii=False)
        + ";\n"
    )
    with open(output, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"已导出 {len(samples)} 个样例到 {output}")
    for sample in samples:
        print(
            f"  - {sample['id']}: {len(sample['frames'])} 帧, "
            f"shape=({sample['rows']}x{sample['cols']})"
        )


if __name__ == "__main__":
    main()
