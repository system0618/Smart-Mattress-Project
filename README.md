# Smart Mattress Project

哈尔滨工业大学 2026 秋季学期《专业方向实践》智能床垫项目仓库。

本项目面向智能床垫压力阵列数据分析，目标是识别用户睡姿与身体部位，辅助床垫气囊进行自适应调节，并提供实时可视化展示。项目背景、课程要求和暂定仓库结构已归档在 [docs/source](docs/source)。

## 核心任务

1. 睡姿识别：实现不少于 2 个算法并对比，按 70% 训练集、30% 测试集划分数据，输出准确率、精确率、召回率和 F1 分数。
2. 身体部位划分：基于增强后的压力数据完成区域划分，验证集准确率目标大于 95%，新用户数据准确率目标大于 70%。
3. 实时可视化：使用 JS 或 Unity 展示睡眠状态、压力热力图、最大压力、平均压力、接触面指数和气囊状态变化。
4. 扩展功能：暂定实现弱压力区域增强，优化人体弱压力区域和躯干连接处的显示效果。
5. 协作材料：保留 GitHub/Gitee 协作记录、每位成员的个人报告和 AI 协同开发会话记录。

## 目录说明

```text
Smart-Mattress-Project/
├── data/                       # 数据说明、少量样例或占位；大数据不提交
├── src/                        # 核心算法代码
│   ├── data_process/           # 数据清洗、增强、训练/测试划分
│   ├── posture_recognition/    # 睡姿识别
│   ├── body_segmentation/      # 身体部位划分
│   └── pressure_enhancement/   # 弱压力区域增强
├── visualization/              # Web 或 Unity 可视化
├── docs/                       # 接口文档、项目管理、最终报告
├── ai_logs/                    # 每位成员的 AI 会话记录
└── .github/                    # Issue 和 Pull Request 模板
```

## 环境准备

推荐使用 Python 3.10 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如果使用 Unity 或前端框架，请在 `visualization/` 下补充对应项目的安装和运行说明。

## 协作流程
git提交流程见git提交指南


## 暂定分工

| 方向 | 目录 | 负责人 |
| --- | --- | --- |
| 睡姿识别 | `src/posture_recognition/` | 邵博儒 |
| 身体部位划分 | `src/body_segmentation/` | 姚乐 |
| 弱压力区域增强 | `src/pressure_enhancement/` | 孙瑜泽 |
| 可视化与前端 | `visualization/` | 柳雨萍 |
| AI 记录与个人报告 | `ai_logs/`, `docs/final_reports/` | 全体成员 |


