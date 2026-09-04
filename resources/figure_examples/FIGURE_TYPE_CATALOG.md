# Modex Figure Type Catalog V1

用途：绘图前按数据形状、读者问题和证据角色选择图型。这里的图型是可执行示例的索引，不是要求每篇论文全部使用。

## 选择原则

1. 先运行 `tools/figure_data_shape_profile.py`，再写读者问题和选几何编码；位置和共同尺度优先于面积、体积、色相。
2. 先判断数据是否有足够的真实变化、对比、例外或不确定性，再决定是否画、画多大以及是否使用复杂模板。
3. 组合图只在 panel 共享对象、时间/空间锚点和研究问题时使用；每个 panel 必须增加独立证据。
4. 少量汇总数据不伪造密度；稀疏网格不伪造连续曲面；重构分布必须标注 reconstructed/simulated。
5. 同一篇论文中避免同一种图型超过 3 次；避免为了“看起来高级”强行使用 3D、雷达或网络图。
6. 模板是候选方案，不是交付配额。允许使用紧凑单图、表格、inset、例外图或将图降为附录/artifact。

## 图型矩阵

| 数据形状/问题 | 首选图型 | 可组合的互补 panel | 关键限制 | 示例 |
|---|---|---|---|---|
| 类别单指标排序 | 棒棒糖、点图 | 置信区间/排名变化 | 不能用面积制造排名差异 | grouped_bar |
| 两条件配对比较 | 哑铃、paired dot | 变化率/分布 | 必须保持配对关系 | forest_plot |
| 多方法×多指标 | 分组点图/矩阵热图 | 稳健性/误差 | 方法≤5时避免无解释深色热图 | bubble_matrix |
| 时间/迭代趋势 | 折线+真实点+区间 | 残差/终点分布 | 禁止无观测依据平滑 | trend_confidence |
| 多序列趋势 | small multiples | 共同终点/整体摘要 | 跨 panel 轴尺度需一致或显式说明 | multi_panel_grid |
| 单变量分布 | raincloud、violin+box+raw | 分组比较/均值区间 | n<8 不用 KDE/violin | distribution_raincloud |
| 大样本二维关系 | hexbin+边际 | 回归/局部残差 | bin 规则与 n 必须说明 | hexbin_joint |
| 小样本二维关系 | scatter+回归/CI | 边际分布 | 不把回归线写成因果 | trend_confidence |
| 相关矩阵 | 热图+dendrogram | 关键变量散点 | 相关方向与中心必须明确 | attention_heatmap |
| 分类误差 | confusion matrix | PR/ROC/校准 | 指标、正类和样本数要清楚 | confusion_matrix, pr_curve |
| 特征解释 | SHAP beeswarm/importance | PDP/ICE | 重要性不等于因果效应 | shap_importance |
| 参数不确定性 | forest interval | 敏感性/分布 | CI/SE/预测区间不能混写 | forest_plot |
| 优化收敛 | 收敛曲线+终点 | 预算/鲁棒性 | 只能使用真实迭代轨迹 | training_curves |
| 多目标权衡 | Pareto+候选/膝点 | 可行域/敏感性 | 前沿、候选、不可行需分层 | bubble_matrix |
| 真实二维网格响应 | contour/response surface | 观测点/切片 | 稀疏网格不得连续化 | contour_quiver |
| 三维真实变量 | 3D scatter/surface | 二维投影/切片/离平面残差 | 先做线性/平面性诊断；平面型真实空间仍可保留 3D，第三维为类别或重复编码时降为二维 | cluster_3d |
| 状态转移/流向 | Sankey/chord/network | 节点指标/时间 | 边权、方向和汇总口径必标 | chord_diagram |
| 空间点与强度 | 地图+bubble | 时间切片/分布 | 不能用散点冒充地图 | map_bubble |
| 方向/角度 | polar rose | 方向随时间/类别 | 角度是周期变量 | polar_rose |
| 矢量场 | streamplot/contour+quiver | 关键轨迹/源汇点 | 必须有真实矢量数据 | streamplot_field, contour_quiver |
| 集合交集 | UpSet/Venn | 规模/边界 | Venn 只适合少量集合 | upset_sets, venn_diagram |
| 三成分组成 | ternary | 密度/分类边界 | 三个分量必须可归一化 | ternary_plot |
| 分类×分类强度 | bubble matrix | 边际条形/排序 | 面积比较需数值标签 | bubble_matrix |
| 时序相关 | ACF/PACF | 原序列/频谱 | 滞后范围和置信界限要标 | acf_pacf |
| 非平稳信号 | spectrogram | 原始波形/频带摘要 | 窗长、步长和频率单位必标 | spectrogram_2d |
| 预测误差 | 残差诊断 | 实际-预测/分布 | 不能只报均值误差 | residual_diagnostics |
| 脉冲/动态响应 | IRF+区间 | 基线/累计效应 | 冲击定义和区间来源必标 | irf_response |

## 长尾/小众图型扩展 V2

以下图型不允许为了稀有而使用，只有数据结构满足条件时才进入候选；它们的作用是让模型在传统柱线图之外有真正可解释的选择。

| 小众图型 | 适合的数据结构/问题 | 推荐互补层 | 当前状态 |
|---|---|---|---|
| ECDF / exceedance curve | 多组连续观测、比较分布或超过阈值的比例 | 分位数/阈值带/KS差异 | 计划新增 |
| Quantile dot plot | 概率、预测区间、离散不确定性 | 频率框架/区间摘要 | 计划新增 |
| Beeswarm / sina | 小到中等样本的原始点分布 | 箱线/中位数/区间 | 计划新增 |
| Ridgeline | 多组同尺度分布随时间/条件变化 | 中位数线/样本量 | 计划新增 |
| Horizon chart | 长时间序列、多组趋势、纵向空间有限 | 原始趋势缩略图/异常点 | 计划新增 |
| Parallel sets / alluvial | 多个离散阶段的类别流转 | 各阶段边际计数 | 计划新增 |
| Mosaic / association plot | 两个或多个分类变量的列联关系 | 残差/标准化偏差 | 计划新增 |
| Arc diagram | 有序节点之间的稀疏关系或依赖 | 节点度/社区色带 | 计划新增 |
| Hive plot | 网络节点有明确层级/角色/度数 | 节点属性边际 | 计划新增 |
| Matrix profile / recurrence plot | 周期、重复片段和时序相似性 | 原始序列/异常段 | 计划新增 |
| Phase portrait | 二维状态变量的动态轨迹 | 向量场/吸引子/边界 | 计划新增 |
| Calibration belt | 预测概率与观测频率的非线性校准 | 可靠性直方图/分箱 n | 计划新增 |
| Lorenz curve / concentration | 资源、收益或贡献集中度 | Gini/分位数条带 | 计划新增 |
| Dominance map | 多目标候选的支配关系与可行域 | Pareto front/约束边界 | 计划新增 |
| Glyph plot / star glyph | 少量候选的多指标结构 | 共同尺度点图 | 需谨慎，不能替代精确比较 |
| Small-multiple event strip | 事件时间、阶段和策略切换 | 结果趋势/风险带 | 计划新增 |
| Bivariate legend map | 两个空间变量的联合等级 | 边际分布/样本量 | 计划新增 |
| Sankey + uncertainty bands | 流量/状态转移且边权有区间 | 节点总量/流失率 | 计划新增 |

### 当前 MathorCup B 题优先候选

对于机器人攻防策略类题目，优先考虑以下低频但语义匹配的表达：

1. **攻防动作 ECDF + 阈值带**：比较 13 类攻击动作的失稳概率/冲量风险分布；只有存在重复仿真样本时使用。
2. **动作—防守 Parallel Sets / Alluvial**：展示攻击类型 → 防守响应 → 恢复/反击状态的多阶段转移；边宽必须来自真实转移计数或概率。
3. **状态 Phase Portrait + 代表轨迹**：展示比分状态/剩余时间/能量等状态变量的真实轨迹；静态状态表不得伪造时间。
4. **Dominance Map + Pareto front**：同时展示可行/不可行候选、支配关系和最终膝点；不可行必须有约束证据。
5. **Quantile dot plot + empirical CDF**：表达 BO3 胜率或资源消耗的不确定性；没有逐次模拟结果时不得使用。
6. **Strategy calendar / event strip**：把局间换电、维修、暂停和故障窗口映射到赛程时间轴；事件顺序必须源自规则与策略记录。
7. **Mosaic / association plot**：展示比分状态 × 策略选择 × 结果的列联结构；单元格面积和残差含义必须明确。
8. **Chord/arc diagram + marginal bars**：展示动作和防守动作的匹配/响应关系；关系矩阵必须来自模型输出，不能使用演示矩阵。

### 小众图型的淘汰条件

- 数据没有对应结构，只是为了与其他论文不同；
- 图型主要依赖面积、体积或颜色，而读者要做精确比较；
- 只有汇总均值却画 ECDF、raincloud、quantile dot 或 posterior；
- 没有真实第三维却使用 3D；
- 关系矩阵稠密到弦图/网络图不可读；
- 小样本或类别稀疏却使用复杂密度估计；
- 复杂图失败后删掉证据层却不记录降级理由。

## 推荐主图组合模板

- **模型证据**：拟合/预测主图 + 残差或频谱 + 指标区间。
- **优化证据**：Pareto 前沿 + 可行域/敏感性 + 预算或收敛。
- **分类证据**：混淆矩阵 + PR/ROC + 校准或错误案例分布。
- **时序证据**：趋势/预测带 + 残差分布 + 关键阶段放大图。
- **决策证据**：状态分区 + 代表轨迹/策略流向 + 胜率或风险分布。
- **空间证据**：地图/场图 + 边际分布或时间切片；CRS 和空间尺度必须明确。

## 模板适用性与退出条件

每个模板在使用前必须记录 `use_when` 和 `avoid_when`。至少遵守：

- 数值相对变化范围 < 3% 时，优先点图、差值图或区间图，不用大面积柱体放大微小差异；
- 最大重复模式占比 > 80% 时，压缩不变量，只展开例外；
- 0/1 饱和占比 > 70% 时，不直接铺满完整热图；
- panel 相似度 > 0.95 时，改画差值、收敛或排名变化；
- 第三维只是类别编号或分组标签时，不使用 3D 主图；
- 有效对象不超过 4 个且没有不确定性、阈值或机制层时，优先半栏图、inset 或表格；
- 允许的退出形式：`compact_plot`、`delta_plot`、`exception_summary`、`table`、`inset`、`appendix`、`artifact`。

## 禁用或需审查的退化

- 从一个均值、胜率或少量汇总量随机生成“稳定性曲线”“后验分布”。
- 用 3×3 或更稀疏点插值成连续等高面，却不展示观测点和插值说明。
- 用双 y 轴把没有一一对应关系的指标硬塞进一张图。
- 用大量透明点、网格线、颜色渐变和粗边框制造虚假信息密度。
- 仅通过颜色区分类别，且灰度或色盲条件下无法识别。
- 失败时静默退化成简单柱状图/折线图而不记录原因。
