# Modex 画图代码包 Skills 说明

更新时间：2026-09-05

## 状态


- 视觉类 Skill 的内部 `name` 保留 `visual-*-main` 格式，目录名采用简化命名（如 `paper-figure` 对应 `visual-paper-figure-main`）。

## 目录与命名

本代码包专注于**学术论文可视化**相关功能，包含以下 10 个 Skill：

| 目录名 | 内部 Skill 名称 | 功能说明 |
|---|---|---|
| `mermaid-diagram` | `visual-mermaid-diagram-main` | 生成 Mermaid 图表（流程图、时序图、类图、ER 图、甘特图等 18+ 类型） |
| `nature-figure` | `visual-nature-figure-main` | 生成符合 Nature 期刊规范的出版级 matplotlib 图表 |
| `paper-figure` | `visual-paper-figure-main` | 根据实验结果生成论文级数据图表与统计表格 |
| `paper-figure-drawio` | `visual-paper-figure-drawio-main` | 生成 DrawIO 架构图、技术路线图、流程图及 TikZ 非数据图 |
| `paper-figure-html` | `visual-paper-figure-html-main` | 用 HTML/CSS 绘制论文流程图、架构图，通过 Electron 输出矢量 PDF |
| `paper-illustration` | `visual-paper-illustration-main` | 借助图像生成模型制作架构图、方法图等学术插图 |
| `patent-build` | `writing-patent-build-main` | 渲染专利技术交底书中的 HTML 系统框图和流程图为 PNG |
| `shared-scripts` | （工具集合） | 共享绘图工具脚本（plot_utils.py、figure_check.sh 等） |
| `skills-codex` | （工具集合） | Codex 工作流相关配置与变体 |
| `skills-codex-claude-review` | （工具集合） | 使用 Claude Review 交叉评审的覆盖变体 |

## 功能分类

### 视觉类 Skills（7 个）

#### 数据图表
- **paper-figure** — 学术论文核心数据图表生成（柱状图、折线图、热力图、雷达图等）
- **nature-figure** — Nature/高影响因子期刊风格图表（严格配色、字体、排版规范）

#### 流程与架构图
- **mermaid-diagram** — 基于文本的结构化图表（Markdown 友好）
- **paper-figure-drawio** — 矢量架构图与技术路线图（DrawIO + TikZ）
- **paper-figure-html** — HTML/CSS 实现的复杂流程图（适合多层嵌套结构）

#### 学术插图
- **paper-illustration** — AI 辅助生成学术插图（方法示意图、系统概览图）

### 写作类 Skills（1 个）

- **patent-build** — 专利交底书图示渲染与文档导出

### 工具与配置（2 个）

- **shared-scripts** — 共享绘图工具库（配色方案、样式检查、格式验证）
- **skills-codex** / **skills-codex-claude-review** — 工作流集成配置

## 使用场景

### 数学建模竞赛论文
1. **赛题分析图** — `mermaid-diagram` 绘制问题拆解流程图
2. **数据结果图** — `paper-figure` 生成实验结果对比图、参数敏感性分析图
3. **技术路线图** — `paper-figure-drawio` 生成 DrawIO 技术路线图
4. **模型架构图** — `paper-figure-html` 或 `paper-illustration` 生成复杂模型结构图

### 学术论文投稿
1. **Nature 系列期刊** — `nature-figure` 生成符合 Nature 规范的图表
2. **会议论文（ICLR/NeurIPS/ICML）** — `paper-figure` 生成标准学术图表
3. **流程与架构** — `mermaid-diagram` + `paper-figure-drawio` 组合使用

### 专利申请
- `patent-build` 渲染技术方案图示并导出正式交底书

## 与完整 Skill 库的关系

本代码包是从 `modex-skills-final`（127 个 Skill）中精选的**可视化子集**，专注于论文图表生成。

完整 Skill 库包含：
- **Competition**（11）— 数学建模竞赛全流程
- **Development**（7）— 软件开发与项目报告
- **Experiments**（16）— 实验规划、执行、监控与分析
- **Research**（26）— 文献调研、构想生成、查新与评审
- **Writing**（34）— 论文、报告、专利、基金申请写作
- **Visual**（15）— **本代码包的来源类别**
- 其他类别（Orchestration、Integration、Documentation Assets 等）

## 技术说明

### Skill 文件结构
- 每个 Skill 目录包含 `SKILL.md` 或 `skill.md` 文件（YAML frontmatter + Markdown 正文）
- `shared-scripts` / `skills-codex` / `skills-codex-claude-review` 为工具目录，无独立 Skill 文件属正常

### 调用方式
Skill 通过 Claude Code CLI 或兼容工具链调用，语法：
```bash
# 示例：生成 Mermaid 流程图
/mermaid-diagram "绘制赛题分析流程图"

# 示例：生成论文数据图
/paper-figure "根据 results.json 生成图表"
```

### 依赖环境
- Python 3.8+（matplotlib、seaborn、pandas 等）
- Node.js（Mermaid CLI、Electron 渲染）
- DrawIO Desktop / CLI（架构图导出）
- LaTeX（TikZ 图形编译）

## 已知问题

- `shared-scripts/figure_check.py` 来自固定公开提交，未经密码学认证（原版本无法通过 AES-GCM 校验）
- `research-research-refine-codex-review` 和 `visual-paper-figure-codex-review` 正文中仍存在少量 "GPT-5.4/Codex" 历史字样，但实际评审配置指向 `claude-review` MCP

