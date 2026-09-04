# Modex 科研绘图能力升级与 eb6205e0eecb 审计

日期：2026-09-02
工作流：`eb6205e0eecb`

## 结论摘要

这次未直接改写历史工作流的数值图，而是完成了全局能力升级，避免破坏既有视觉母版和研究数据。当前瓶颈主要有四层：

1. 图形选择：把离散扫描、响应曲线和真正 Pareto 前沿混用。
2. 版式编辑：复合图缺少主次，流程/机制图信息装载过满。
3. 3D 适配：尖峰、离散类别和前后遮挡不适合直接做曲面/柱体。
4. 质检闭环：已有像素 critic 和浏览器几何探针，但此前缺少 PDF 文字几何、最终版面缩放和 HTML/PDF 来源分流。

换更强模型有帮助，但不会单独解决这些问题。高端模型负责提出更好的视觉结构，Modex 必须用数据形状、视觉合同和渲染 QA 把结构稳定下来。

## 1. eb6205e0eecb 图形审计

真实工作区：`D:\C盘迁移\MHAgent-workspaces\eb6205e0eecb`

图形脚本：`D:\C盘迁移\MHAgent-workspaces\eb6205e0eecb\figures\gen_fig_*.py`

视觉审查：`D:\C盘迁移\MHAgent-workspaces\eb6205e0eecb\_tmp\FIGURE_VISION_REVIEW.json`

### 最确定的问题

- `fig_q1_resid3d`：校正前后 3D 曲面都有前后遮挡，后方尖峰被前景覆盖；2D 投影更适合作为主证据。
- `fig_q2_beta3d`：区域×月份的 3D 曲面/柱形前后遮挡，后排高度难比较；该数据已有 `fig_q2_beta_month` 这类 2D 小 multiples，3D 的增量证据不足。
- `fig_flow_overall`、`fig_arch_robust`、`fig_gptimage`：框体密度高、路径分支多、绿色说明框字号偏小，形成“信息墙/瓷砖墙”。问题在结构和文字分层，不在颜色不够炫。
- `fig_flow_q3`、`fig_mech_balance`、`fig_mech_cef`：公式、说明框和流程主体的留白分隔不足，公式块成为拥挤区域。
- `fig_q2_sankey`：右端节点标签偏小，流带与标签的阅读关系不够稳定。
- `fig_q3_gantt`：单元格数字过密，缩小后确认困难。
- `fig_q3_priority`：条末数字、折线端点和图例映射需要更稳定的锚定。
- `fig_q4_roll`：右侧 Y 轴存在被截断/缺失风险，双轴变量必须明确且留出边界。

### Pareto 图为何丑

源脚本：`figures/gen_fig_q3_pareto.py`

该图自述为“投资—碳缺口权衡”，并明确说明“非严格 Pareto 前沿”。因此问题不只是画得散，而是命名和视觉语义容易误导：

- 60 个扫描格点全部保留，点云和多条曲线同时抢主视觉。
- 每个 `m_C` 都连成曲线，读者容易把离散参数扫描误认为连续可行路径。
- `viridis` 同时承担参数编码，前沿边界、基准点和可行性没有分层。
- 基准星标与批注虽存在，但前沿边界、可行区/被支配区和最终选择未形成清晰的阅读路径。
- 没有显式的 feasible/infeasible/non-dominated 分层，因此不能把它当标准 Pareto 图。

后续真正的 Pareto 图必须：先统一目标方向，再先筛可行解，再计算非支配集；背景候选浅灰，前沿单一强调色，最终选择和膝点各自使用统一 marker；最多标 4 个关键点。若仍是参数扫描，应改名为“权衡扫描/响应曲线族”。

### 3D 判断

你的判断是对的。对于尖锐、离散、前后遮挡明显的图，3D 会把数据问题放大成视觉问题：透视会改变高度比较，前景会遮住后景，尖峰会成为视觉噪声。今后的默认路线是：

- 真实空间/时间/第三连续变量且 2D 无法表达：保留 3D，但必须配投影/切片/残差。
- 3D 只是类别、阶段、编号或为了显得高级：降为 2D。
- 有尖峰或极端值：优先 2D 点图、热图、分面、局部 inset；不要用曲面把尖峰扩大成“山峰”。

## 2. 参考图与目标差距

本轮 10 张上传参考图已复制到当前工作台 `_tmp/reference_01.png` 至 `_tmp/reference_10.png`。由于附件在平台侧没有稳定的语义编号/来源标签，不能可靠声称哪张对应哪一种作者图型；因此不把它们硬分成“参考/Modex”并作虚假的逐张归因。

可可靠提炼的差距是：

| 维度 | 目前 eb6205e0eecb | 参考图应达到的状态 |
|---|---|---|
| 信息结构 | 信息都放进一张图，主次弱 | 一个主结论，辅助层只承担差异/机制/不确定性 |
| 留白 | 空白与组间关系未形成节奏，流程框体挤在一起 | 组内紧、组间松；留白承担分组和阅读换气 |
| 数据编码 | 颜色、线、点、标签同时表达多层信息 | 位置/长度优先；每个视觉通道单一职责 |
| 标注 | 关键点锚定不稳定，部分标签堆叠 | 只标阈值、转折、异常、选择和机制节点 |
| Pareto | 点和曲线全部用力，边界不突出 | 可行候选、被支配候选、前沿、膝点、选择点分层 |
| 3D | 尖峰和透视造成遮挡 | 只有不可替代的第三维才使用 3D，并配投影 |
| HTML | 框体多、文字小、主路径不够突出 | 显式 grid/viewBox、固定锚点、一条主阅读路径、短节点文本 |
| QA | 视觉模型可发现问题，但依赖可选网络审稿 | DOM、PDF、栅格三层分流，失败保留 REVIEW/BLOCK 证据 |

参考图的“高级感”更可能来自排版系统、信息层级和有意识的留白，而不只是模型档次。高端模型可以提高构图探索能力，但需要 Modex 提供可复用的 HTML 组件、视觉合同和图形回归，才能稳定超过“高端模型+普通 Modex”。

## 3. 网络调研得到的可执行原则

本轮进一步补充了艺术与信息设计的理论边界。可以迁移到科研绘图的是可验证的感知秩序，而不是一套固定审美模板：

- **论证路径**：多面板图可按“对象/方法 → 主要结果 → 统计或约束验证 → 机制/决策”组织；每个 panel 必须回答不同问题。
- **Gestalt 接近与相似**：组内间距小于组间间距；相同语义保持相同颜色、marker 和线型；空间距离本身承担分组作用。
- **连续与节奏**：时间、流程和轨迹保持连续；异常点只因数据证据打破重复节奏；不要让每个 panel 同时改变轴、颜色、标记和标签方式。
- **视觉层级**：一级是核心趋势/主要差异，二级是区间/参考线/统计结果，三级是网格/背景/补充注释；重要性通过对比度、位置和尺寸表达，避免装饰性阴影和渐变。
- **信息密度**：密度由元素数量、相似度、拥挤程度和读图任务共同决定，不能只按元素个数机械判定；复杂信息应使用分面、差值、inset、主图+补充图或交互筛选。
- **比例边界**：黄金比例、三分法和固定“漂亮”纵横比只能作为构图起点；真实数据尺度、最终栏宽、标签空间和比较任务优先。

其中，Cleveland–McGill、Gestalt 感知、注意容量和视觉杂乱属于较强的实证/理论依据；黄金比例、三分法和装饰性平衡属于构图启发，不能当成通用认知定律。

- Cleveland–McGill 图形感知研究：精确比较优先共同坐标中的位置和长度，谨慎使用面积、角度和体积。
- Midway, *Principles of Effective Data Visualization*：先确定视觉消息，再选几何；显示数据本身；减少非数据墨水。
- Franconeri 等：视觉系统适合快速提取总体模式，复杂设计应减少工作记忆和视觉搜索负担。
- Matplotlib colormap 指南：有序数据用感知均匀顺序色图，围绕有意义中心的偏差用发散色图，类别用定性色图。
- Crameri 科学色图：感知均匀、方向明确，减少颜色造成的视觉失真。
- Nature Figure Guide：最终图中文字通常保持 5–7 pt，字体要标准、可编辑、可读；避免彩色文字、装饰图标、复杂背景和重叠文字。
- Section 508/WCAG：颜色不能成为唯一编码；文本对比度应达到 4.5:1，关键图形对象至少 3:1。
- pymoo PCP 文档：高维候选使用平行坐标时，背景解低透明度，只高亮少数感兴趣解，轴范围和归一化必须显式。
- SciVisAgentBench：科研可视化 Agent 需要按真实工具链、多步骤任务和系统化指标评价，不能只凭一次图像主观评分。

来源：

- https://pmc.ncbi.nlm.nih.gov/articles/PMC7733875/
- https://doi.org/10.1080/01621459.1984.10478080
- https://doi.org/10.1177/15291006211051956
- https://matplotlib.org/stable/users/explain/colors/colormaps.html
- https://www.fabiocrameri.ch/colourmaps/
- https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/
- https://www.section508.gov/create/making-color-usage-accessible/
- https://pymoo.org/visualization/pcp.html
- https://arxiv.org/html/2603.29139
- https://pmc.ncbi.nlm.nih.gov/articles/PMC8041175/

## 4. 本轮已实施的 Modex 升级

安装目录：`D:\modex\Modex-MH-Agent\resources\app`

已修改/新增：

1. `tools/figure_render_qa.py`
   - 新增 PDF 文字盒、最小字号、页边和最终尺寸栅格检查。
   - HTML-canonical 图的 PDF 文本层碰撞只做 REVIEW，避免浏览器/KaTeX 文本层误报 BLOCK。
   - 真实定量 PDF 仍保留文字盒碰撞证据。
   - 无 OCR 引擎时明确写出能力边界，不把“没检查到”伪装成通过。

2. `tools/figure_system_controller.py`
   - 将渲染 QA 纳入 postflight 总报告，形成单一汇总源。

3. `backend/services/figure_lifecycle_patch.py`
   - preflight 检查必备 `figure_render_qa.py`。
   - 移除重复运行渲染 QA 的逻辑，避免一轮工作流生成多个互相覆盖的报告。

4. `backend/services/prompts/local_figure_quality_overlay.md`
   - 增加美术式留白、视觉重心、层级和节奏的执行规则。
   - 增加 Pareto 可行性/非支配集/膝点/标注预算规则。
   - 增加 HTML grid/viewBox、短节点文本和多宽度导出规则。
   - 增加尖峰/离散数据降级 2D 的规则。

5. `resources/figure_examples/FIGURE_ART_DIRECTOR.md`
   - 升级为 V2，加入 8 行视觉合同、美术理论工程化、Pareto 专门规则、HTML/SVG 规则和 QA 字段。

回滚备份：

- `backups/figure_lifecycle_patch.py.before-render-qa-20260902`
- `backups/FIGURE_ART_DIRECTOR.md.before-render-qa-20260902`
- `backups/figure_decision_planner.py.before-render-qa-20260902`
- 另有本轮此前生成的 `before-visual-master-20260902` 与 `before-global-visual-controller-20260902` 备份。

## 5. 回归结果与当前边界

已通过 Python 语法检查：

- `figure_render_qa.py`
- `figure_system_controller.py`
- `figure_lifecycle_patch.py`

对 `eb6205e0eecb` 运行结果：

- 原有确定性视觉 critic：`REVIEW`，能捕获低对比、过满画布、边缘贴近等问题。
- 网络视觉审查：`REVIEW`，明确指出两张 3D 高风险遮挡，以及流程/机制图高密度小字。
- 新渲染 QA：已成功运行；HTML/PDF 文本层误报已从 BLOCK 降为 REVIEW，但定量图仍保留真实文字碰撞风险。
- 图系统总控仍为 `BLOCK`，其核心阻断原因来自该工作流的研究质量复核：供能约束缺失、协同机制未接入、通道升级参数未使用、CEF 事后校验缺失、鲁棒方案不可达等。它不是单纯的画图美化问题，不能用重画图掩盖。

重要边界：本轮没有重绘 `eb6205e0eecb` 的历史图，所以不能宣称这些 PNG 已经变漂亮；本轮完成的是“下一次画图会按更高标准生成和检查”。要实际看到 Pareto、3D 和 HTML 画面变化，需要下一次对目标工作流重新运行图形步骤。

OCR：当前环境没有 `tesseract`、`pytesseract` 或 `easyocr`。现在已覆盖 PDF 文字几何、浏览器 DOM 几何和栅格最终尺寸；中文错字/漏字/截断的自动识别仍需后续安装并接入 OCR，或者由配置好的视觉模型承担 REVIEW。

## 6. 本轮 P0 门禁修复

后续扫描发现并确认了一个发布正确性问题：`figure_quality_gate.py` 在 BLOCK 时曾返回退出码 `2`，而 controller 旧逻辑把 `2` 当作 REVIEW；同时数字一致性门禁原本未接入图表 controller。已完成修复：

- `figure_quality_gate.py`：统一 `0=PASS、1=BLOCK、2=REVIEW`。
- `figure_number_consistency_gate.py`：统一同一退出码协议；缺少结果源明确返回 REVIEW，结果 JSON 无法解析返回 BLOCK。
- `figure_system_controller.py`：优先解析结构化 stdout verdict，并把质量门与数字一致性门禁接入 postflight；工具缺失/异常按 BLOCK 处理。
- `figure_lifecycle_patch.py`：将最终图表 postflight verdict、渲染 QA 报告和数字一致性报告路径写回结果；REVIEW 不再静默表现为普通完成。
- `test_figure_gate_contract.py`：新增隔离回归，覆盖 PASS/REVIEW/BLOCK、退出码和结果源错误。

验证结果：

- `FIGURE_GATE_CONTRACT_PASS`
- 相关 Python 文件 `py_compile` 通过。
- `eb6205e0eecb` 真实工作区：`FIGURE_SYSTEM_REVIEW`，无新增 controller BLOCK；quality gate 为 REVIEW，number consistency 因缺少 `RESULTS.json` 为 REVIEW。
- `check_local_overlays.py`：`OFFICIAL_SKILL_BASELINE_PASS`。

### P0：先修图形选择

- Pareto 重画为“可行候选 + 非支配前沿 + 膝点/基准/最终选择 + 支配区域或权衡方向”。
- `fig_q1_resid3d`、`fig_q2_beta3d` 默认降为 2D 主图；如保留 3D，只做补充视图并配投影。
- HTML 流程图压缩为主路径 + 关键旁支，节点最多标题+一行副信息，详细说明转 caption/正文。

### P1：建立 Agent 图形评测集

建议加入 12 类真实 golden case：Pareto、热图、small multiples、残差诊断、森林图、网络/流图、时频、空间、3D、HTML 机制图、复杂多面板、百万点散点。

每类保存：输入数据、图形合同、期望图型、禁止图型、关键标签表、允许标注数、视觉 QA 结果和人工评分。评测指标分为：

- Numeric：数字与结果 JSON 一致。
- Lexical：标签、单位、图例、标题完整。
- Visual：碰撞、裁切、字号、对比度、留白、图例遮挡。
- Semantic：图型、编码和结论边界正确。

### P2：再考虑模型升级

先把同一个数据集交给当前模型和高端模型，在相同视觉合同与 QA 下比较：首次通过率、返工次数、重绘后审美评分、数字一致性和运行成本。否则无法知道模型升级是否真的带来收益。

## 7. 最终判断

你要的目标可以概括为：**像美术一样组织空间，像统计图一样诚实编码，像工程系统一样可验证。**

Modex 当前已经具备数据形状、图型决策、语义色、证据批注、HTML 几何探针和视觉 critic 的骨架；本轮把留白/层级/Pareto/3D/渲染 QA 的缺口补上了一部分。接下来最值得做的不是继续堆颜色或强行上 3D，而是重绘一张真正的 Pareto golden case，并把它作为 Modex 的视觉基准图。