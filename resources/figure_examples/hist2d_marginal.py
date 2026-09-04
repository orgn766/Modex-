"""二维直方图 + 边际直方图：大样本二维分布密度。

适用：大样本（>1000 点）的二维联合分布，散点会过绘时的替代。
      与 hexbin 的区别：矩形网格更适合与坐标轴语义对齐。
要点：hist2d 对数色标（密度跨度大时），
      顶部/右侧边际直方图展示单维分布，
      峰值区域标注。
"""
import numpy as np
import matplotlib.pyplot as plt
from _utils.plot_utils import setup_style, save_fig, PALETTE, COLORS, _lighten

setup_style()

rng = np.random.default_rng(59)
n = 8000
# 合成：两个相关簇
theta = np.radians(35)
rot = np.array([[np.cos(theta), -np.sin(theta)],
                [np.sin(theta), np.cos(theta)]])
pts1 = rng.normal([3.5, 3.5], [1.1, 0.6], (n // 2, 2)) @ rot.T
pts2 = rng.normal([7.0, 6.5], [0.8, 1.0], (n // 2, 2)) @ rot.T
data = np.vstack([pts1, pts2])
x, y = data[:, 0], data[:, 1]

fig = plt.figure(figsize=(9.5, 8))
ax = fig.add_axes([0.10, 0.12, 0.72, 0.72])
ax_top = fig.add_axes([0.10, 0.86, 0.72, 0.10])
ax_right = fig.add_axes([0.84, 0.12, 0.10, 0.72])

# 主图：hist2d（对数色标）
h, xe, ye, im = ax.hist2d(x, y, bins=60, cmap='viridis',
                          norm='log', range=[[0, 11], [0, 11]])
cb = fig.colorbar(im, cax=fig.add_axes([0.96, 0.12, 0.02, 0.72]))
cb.set_label('样本数 (log)', fontsize=9)

# 边际直方图
ax_top.hist(x, bins=60, range=[0, 11], color=_lighten(PALETTE[0], 0.45),
            edgecolor=PALETTE[0], linewidth=0.6, alpha=0.9)
ax_right.hist(y, bins=60, range=[0, 11], orientation='horizontal',
              color=_lighten(PALETTE[1], 0.45), edgecolor=PALETTE[1],
              linewidth=0.6, alpha=0.9)
ax_top.set_xticks([])
ax_right.set_yticks([])
for a in (ax_top, ax_right):
    a.spines['top'].set_visible(False)
    a.spines['right'].set_visible(False)
ax_top.spines['bottom'].set_visible(False)
ax_right.spines['left'].set_visible(False)

# 峰值标注
peak = np.unravel_index(np.argmax(h), h.shape)
px = (xe[peak[0]] + xe[peak[0] + 1]) / 2
py = (ye[peak[1]] + ye[peak[1] + 1]) / 2
ax.scatter([px], [py], s=55, facecolors='none', edgecolors='white',
           linewidths=1.4, zorder=5)
ax.text(px + 0.3, py + 0.3, '密度峰值', fontsize=9, color='white',
        fontweight='bold')

ax.set_xlabel('维度 x', fontsize=11)
ax.set_ylabel('维度 y', fontsize=11)
ax.set_xlim(0, 11)
ax.set_ylim(0, 11)
ax.set_title('二维直方图 + 边际分布（示例：8000 点双簇）', fontsize=12)
save_fig(fig, 'figures/fig_hist2d_marginal.pdf')
