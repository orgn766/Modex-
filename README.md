# Modex 画图相关代码包

打包日期：2026-09-03  
来源安装目录：`D:\modex\Modex-MH-Agent\resources\app`

本包收录 Modex 当前安装版中与科研绘图 / 图表生命周期 / 视觉质检 / 图型配方相关的代码、提示词、skills 与示例库。不含第三方运行时（matplotlib / seaborn 等 site-packages），也不含历史 backups 与工作区临时产物。

## 目录结构

```
Modex_画图代码包_20260903/
├── tools/                         # 图表生命周期与门禁工具链（核心）
├── backend/
│   ├── bootstrap_backend.py       # 启动时安装 figure_lifecycle_patch
│   └── services/
│       ├── figure_lifecycle_patch.py
│       ├── claude_runner_env_patch.py   # 注入图表质量合同与配方提示（混合文件，含非图逻辑）
│       ├── review_repair_patch.py       # 含 figure 修复/重跑逻辑（混合文件）
│       └── prompts/
│           ├── local_figure_quality_overlay.md
│           ├── nature_figure_lang.md
│           └── paper_figure_lang_zh.md
├── resources/figure_examples/     # 可视化模型库 / 配方示例（含 polar_rose 等）
├── skills/
│   ├── nature-figure/
│   ├── paper-figure/
│   ├── paper-figure-html/
│   ├── paper-figure-drawio/
│   ├── paper-illustration/
│   ├── mermaid-diagram/
│   ├── skills-codex/paper-figure/
│   ├── skills-codex-claude-review/paper-figure/
│   ├── patent-build/tools/html_figure_render.py.enc
│   └── shared-scripts/            # figure/plot/drawio/tikz 辅助脚本与配方
└── docs/
    └── MODEX_FIGURE_UPGRADE_AUDIT_20260902.md
```

## 核心工具链（tools/）

| 文件 | 作用 |
|---|---|
| `figure_system_controller.py` | 图表 pre/post 生命周期总控 |
| `figure_decision_planner.py` | 图型、证据层、批注预算、降级决策 |
| `figure_data_shape_profile.py` | 绘图前数据形状分析 |
| `figure_annotation_policy.py` | 证据触发式批注候选 |
| `figure_visual_semantics.py` | 特殊点/线统一语义 |
| `figure_editorial_gate.py` | 编辑性门禁（重复/饱和/3D 必要性等） |
| `figure_quality_gate.py` | 数据/语义/视觉/导出门禁 |
| `figure_number_consistency_gate.py` | 图号一致性门禁 |
| `figure_render_qa.py` | 渲染 QA（PDF 文字盒、字号、边距、来源分流） |
| `figure_visual_critic.py` | 像素级视觉 critic |
| `figure_vision_review.py` | 视觉模型审图 |
| `figure_regression_guard.py` | 图表回归守卫 |
| `figure_workspace_bootstrap.py` | 工作区图表环境引导 |
| `test_figure_gate_contract.py` | 门禁合同回归测试 |

## 接线说明

1. `backend/bootstrap_backend.py` 在启动时调用 `figure_lifecycle_patch.install()`。
2. `figure_lifecycle_patch.py` 把图表 preflight / postflight / vision review / render QA 挂进 skill 运行链路。
3. `claude_runner_env_patch.py` 向运行环境注入 figure_examples、质量合同与各门禁路径说明。
4. `review_repair_patch.py` 在重大审稿回流时识别可修复图表脚本并触发重跑。

注意：`claude_runner_env_patch.py` 与 `review_repair_patch.py` 是混合文件，除画图外还含建模/审稿等逻辑；本包完整收录以便对照接线，不等于它们整文件都属于画图子系统。

## 图型示例库（resources/figure_examples/）

- 已验证示例脚本 + PNG 预览（含 `polar_rose.py` 玫瑰图）
- `INDEX.md`：索引
- `FIGURE_TYPE_CATALOG.md`：图型目录
- `FIGURE_ART_DIRECTOR.md`：视觉合同 / 美术导演规范 V2
- `generate_*_demos.py`：批量生成演示图脚本

## Skills

主要包括：

- `paper-figure` / `nature-figure`：论文与 Nature 风格绘图 skill
- `paper-figure-html`：HTML/SVG 结构图模板与检查
- `paper-figure-drawio`：draw.io 路线
- `paper-illustration` / `mermaid-diagram`：插图与流程图相关
- `shared-scripts` 中的 `figure_*`、`plot_utils`、`fig_*`、`drawio_*`、`tikz_*`

## 刻意未收录

- `runtime/python/Lib/site-packages/**`（matplotlib 等第三方库）
- `resources/app/backups/**`（历史备份）
- 工作流产物、`_tmp/**`、运行时生成的 FIGURE_*.json
- 前端打包产物 `dist/**`（仅有图表选项 UI 片段，无可独立维护的源码树）

## 快速清点

打包时统计约：

- tools: 14
- backend: 7
- resources: 62
- skills: 约 46+
- docs: 1
