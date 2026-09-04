"""矩阵气泡图：分类×分类的数值矩阵，气泡大小编码数值。

适用：混淆矩阵替代展示、类别间转移量、双分类交叉统计。
      相比热力图，气泡图在大动态范围下更易读（面积视觉编码）。
要点：气泡面积正比于数值（不是半径），背景格子线辅助定位，
      关键格（最大/最小）加标签。
"""
import numpy as np
import matplotlib.pyplot as plt
from _utils.plot_utils import setup_style, save_fig, PALETTE, COLORS

setup_style()

# 数据：6 个区域间转移量
regions = ['华东', '华北', '华南', '西南', '东北', '西北']
rng = np.random.default_rng(53)
base = rng.lognormal(mean=3.0, sigma=1.2, size=(6, 6))
np.fill_diagonal(base, 0)          # 区域内转移不展示
base[0, 2] = 260; base[2, 0] = 230  # 华东-华南 大流量

n = len(regions)
fig, ax = plt.subplots(figsize=(8.5, 8))
max_v = base.max()

for i in range(n):
    for j in range(n):
        v = base[i, j]
        if v <= 0:
            continue
        # 面积正比：r = R * sqrt(v / max)
        r = 0.36 * np.sqrt(v / max_v)
        color = PALETTE[0] if (i, j) in [(0, 2), (2, 0)] else '#6b8fb5'
        ax.scatter(j, i, s=(r * 120) ** 2, facecolors=color, alpha=0.55,
                   edgecolors=COLORS['text'], linewidths=0.5, zorder=3)
        if v > max_v * 0.55:  # 大流量标注
            ax.text(j, i, f'{v:.0f}', ha='center', va='center', fontsize=8,
                    color='white', fontweight='bold', zorder=4)

# 网格线
ax.set_xticks(range(n))
ax.set_yticks(range(n))
ax.set_xticklabels(regions, fontsize=9.5)
ax.set_yticklabels(regions, fontsize=9.5)
ax.set_xlim(-0.6, n - 0.4)
ax.set_ylim(n - 0.4, -0.6)
ax.grid(True, color=COLORS['grid'], alpha=0.5, linewidth=0.7, zorder=1)

# 气泡大小图例
for v, lab in [(50, '50'), (150, '150'), (250, '250')]:
    r = 0.36 * np.sqrt(v / max_v)
    ax.scatter([], [], s=(r * 120) ** 2, facecolors='#6b8fb5',
               edgecolors=COLORS['text'], linewidths=0.5, label=lab)
ax.legend(frameon=True, edgecolor=COLORS['grid'], fontsize=8.5,
          title='转移量', title_fontsize=8.5, loc='lower left',
          bbox_to_anchor=(1.01, 0.0))

ax.set_xlabel('目标区域', fontsize=11)
ax.set_ylabel('来源区域', fontsize=11)
ax.set_title('区域间转移量矩阵气泡图（示例：面积∝数值）', fontsize=12)
save_fig(fig, 'figures/fig_bubble_matrix.pdf')
