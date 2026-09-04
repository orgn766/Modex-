# Figure Examples Index（图表示例索引）

画图前按图型读取对应 .py 源码作为参照；PNG 为渲染效果预览，可选择性查看（每次最多看 1-2 张，避免上下文膨胀）。

> **美术指导**：先读 `FIGURE_ART_DIRECTOR.md` 定视觉合同（每张主图 5 行）与矢量输出约定（SVG+PNG+PDF）。

| 图型 | 示例 | 适用场景 |
|---|---|---|
| 对比 | grouped_bar.py | 多方法×多指标分组柱状图：渐变填充、误差线、最优值高亮、均值参考线 |
| 分布 | distribution_raincloud.py | Rain Cloud：半小提琴+散点+箱线，展示完整分布 |
| 趋势 | trend_confidence.py | 多序列趋势线+置信带 |
| 多面板 | multi_panel_grid.py | 多面板组合（趋势+柱状+散点+直方图） |
| 相关 | hexbin_joint.py | Hexbin 联合分布+边际直方图（大样本二维关系） |
| 聚类 | cluster_3d.py | 3D 聚类散点：分组着色、原色边框、文本标注 |
| 训练 | training_curves.py | 训练曲线双轴（Loss+指标）+最佳 epoch 标注 |
| 热图 | attention_heatmap.py | 注意力热力图 |
| 分类 | confusion_matrix.py | 混淆矩阵（带数值标注） |
| 解释 | shap_importance.py | SHAP 风格特征重要性 |
| 统计 | forest_plot.py | 森林图：系数+置信区间+合并估计 |
| DID | parallel_trends.py | 平行趋势/事件研究 |
| 诊断 | residual_diagnostics.py | 2×2 回归诊断：残差vs拟合、Q-Q、直方图、Cook's distance |
| 动态 | irf_response.py | 脉冲响应 IRF：动态冲击+置信带 |
| 关系 | chord_diagram.py | 弦图：环形节点+贝塞尔连线的关系/转移矩阵 |
| 场图 | contour_quiver.py | 填充等值线+矢量场叠加（相场/温度场/势能面） |
| 方向 | polar_rose.py | 极坐标玫瑰图：风向/方向频率分布 |
| 流场 | streamplot_field.py | 流线图：矢量场流线+源汇点标记 |
| 分类 | pr_curve.py | PR 曲线：正类稀有场景 AP 对比（官方 ROC 的互补） |
| 集合 | venn_diagram.py | 韦恩图：2-3 集合交叠（手绘圆+交集基数） |
| 集合 | upset_sets.py | UpSet 图：多集合（4-8）交叠矩阵+基数柱 |
| 成分 | ternary_plot.py | 三元相图：三成分占比分布（手写三角坐标） |
| 矩阵 | bubble_matrix.py | 矩阵气泡图：分类×分类，面积∝数值 |
| 分布 | hist2d_marginal.py | 二维直方图+边际直方图（大样本密度） |
| 时序 | acf_pacf.py | ACF/PACF 双面板：自相关检验（Levinson-Durbin） |
| 时频 | spectrogram_2d.py | 时频谱图：非平稳信号 STFT 分析 |
| 空间 | map_bubble.py | 站点分布图：区域轮廓底图+经纬监测点，面积∝数值 |

规则：
1. 源码依赖 `_utils/plot_utils.py`（setup_style/save_fig/PALETTE/COLORS/_lighten），画图前确保该文件在工作区。
2. 示例为结构参照，数据与标签必须替换为本题真实数据；禁止照抄示例数据。
3. 所有示例遵守 figure_data_integrity 规则：数值可追溯、不确定性可见、小样本不伪造分布。
4. 矢量策略：每张图保存 PDF（LaTeX 主矢量）+ 高 DPI PNG（600 dpi，Word 兜底）；SVG 可选。
