"""弦图：环形节点 + 贝塞尔连线的关系矩阵可视化。

适用：转移矩阵、共现矩阵、贸易/通信流量等成对关系。
无需第三方库：纯 matplotlib 圆弧 + 贝塞尔曲线实现。
数据：6 个部门之间的双向流量（对称矩阵可省略单向箭头）。
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, FancyArrowPatch
from matplotlib.path import Path
from _utils.plot_utils import setup_style, save_fig, PALETTE, COLORS

setup_style()

labels = ['研发', '生产', '销售', '物流', '售后', '管理']
# 部门间流量矩阵（对角为内部流量，不画弦）
flow = np.array([
    [0, 34, 12, 8, 6, 20],
    [28, 0, 45, 15, 9, 18],
    [10, 40, 0, 12, 22, 14],
    [7, 13, 11, 0, 5, 9],
    [5, 8, 18, 4, 0, 6],
    [16, 15, 12, 8, 5, 0],
], dtype=float)

n = len(labels)
total = flow.sum()
rng = np.random.default_rng(42)

# 节点角度区间：按行和（出流量）比例分配弧长
row_sum = flow.sum(axis=1)
theta_span = 2 * np.pi * row_sum / total
theta0 = np.zeros(n)
start = 0.0
for i in range(n):
    theta0[i] = start
    start += theta_span[i]

# 节点在圆上的位置（取区间中点）
theta_mid = theta0 + theta_span / 2
x_pos = np.cos(theta_mid)
y_pos = np.sin(theta_mid)

fig, ax = plt.subplots(figsize=(9, 9))
ax.set_aspect('equal')
ax.axis('off')

# 节点弧段（带宽 = 出流量占比）
for i in range(n):
    arc = Arc((0, 0), 2.0, 2.0, theta1=np.degrees(theta0[i]),
              theta2=np.degrees(theta0[i] + theta_span[i]),
              linewidth=0, facecolor=PALETTE[i % len(PALETTE)], alpha=0.9)
    ax.add_patch(arc)
    # 标签放在弧段中点外侧
    r_label = 1.13
    lx, ly = r_label * np.cos(theta_mid[i]), r_label * np.sin(theta_mid[i])
    ha = 'left' if lx >= 0 else 'right'
    ax.text(lx, ly, labels[i], ha=ha, va='center', fontsize=10,
            fontweight='bold', color=PALETTE[i % len(PALETTE)])

# 弦：每对 (i, j) 画一条贝塞尔，透明度/线宽编码流量大小
for i in range(n):
    for j in range(n):
        if j <= i or flow[i, j] == 0:
            continue
        w = flow[i, j] / flow.max()
        p1 = (np.cos(theta_mid[i]), np.sin(theta_mid[i]))
        p2 = (np.cos(theta_mid[j]), np.sin(theta_mid[j]))
        # 三次贝塞尔，控制点取圆心方向偏移（向内弯曲的弦）
        mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        c1 = (mid[0] * 0.35, mid[1] * 0.35)
        c2 = (mid[0] * 0.35, mid[1] * 0.35)
        verts = [p1, c1, c2, p2]
        codes = [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4]
        path = Path(verts, codes)
        patch = FancyArrowPatch(path=path, arrowstyle='-',
                                linewidth=0.8 + 3.2 * w,
                                color=PALETTE[i % len(PALETTE)],
                                alpha=0.25 + 0.45 * w,
                                connectionstyle="arc3,rad=0.15")
        ax.add_patch(patch)
        # 标注较大流量（> 30）
        if flow[i, j] >= 30:
            tx, ty = mid[0] * 0.82, mid[1] * 0.82
            ax.text(tx, ty, f'{flow[i, j]:.0f}', fontsize=7, ha='center',
                    va='center', color=COLORS['text'],
                    bbox=dict(boxstyle='round,pad=0.15', facecolor='white',
                              edgecolor='none', alpha=0.85))

ax.set_xlim(-1.45, 1.45)
ax.set_ylim(-1.45, 1.45)
ax.set_title('部门间流量弦图（示例：弦宽∝流量）', fontsize=12)
save_fig(fig, 'figures/fig_chord_diagram.pdf')
