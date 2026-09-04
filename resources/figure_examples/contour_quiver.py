"""等值线 + 矢量场叠加图：标量场（填色等值线）+ 梯度/流场（箭头）。

适用：相场模拟、温度场、势能面、流函数-速度场联合展示。
要点：contourf 用感知均匀 colormap（viridis），contour 用细黑线标层，
      箭头颜色/长度编码矢量强度，叠加颜色条与比例参考。
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from _utils.plot_utils import setup_style, save_fig, PALETTE

setup_style()

# 合成标量场：双势阱（相场自由能密度风格）
x = np.linspace(-3, 3, 120)
y = np.linspace(-3, 3, 120)
X, Y = np.meshgrid(x, y)
R = np.sqrt(X ** 2 + Y ** 2)
phi = np.arctan2(Y, X)
# 自由能密度：双阱势 + 各向异性
F = (X ** 2 - 1) ** 2 + (Y ** 2 - 1) ** 2 - 0.6 * np.cos(3 * phi) * np.exp(-R / 2)

# 梯度场（负梯度 = 驱动力方向）
dFdx, dFdy = np.gradient(F, x, y)
U, V = -dFdx, -dFdy
# 下采样箭头密度
step = 6
U_s, V_s = U[::step, ::step], V[::step, ::step]
X_s, Y_s = X[::step, ::step], Y[::step, ::step]
mag = np.hypot(U_s, V_s)

fig, ax = plt.subplots(figsize=(9.5, 8))
cf = ax.contourf(X, Y, F, levels=22, cmap='viridis', alpha=0.85)
cs = ax.contour(X, Y, F, levels=10, colors='#222222', linewidths=0.5, alpha=0.6)
ax.clabel(cs, inline=True, fontsize=6.5, fmt='%.1f')

# 矢量场：颜色编码强度
qv = ax.quiver(X_s, Y_s, U_s, V_s, mag, cmap='plasma', width=0.0035,
               scale=55, alpha=0.92, edgecolor='white', linewidth=0.15)

# 颜色条
cbar = fig.colorbar(cf, ax=ax, pad=0.02)
cbar.set_label('自由能密度 F (a.u.)', fontsize=10)
fig.colorbar(qv, ax=ax, pad=0.02)

ax.set_xlabel('x', fontsize=11)
ax.set_ylabel('y', fontsize=11)
ax.set_title('相场自由能等值线 + 驱动力矢量场（示例）', fontsize=12)
ax.set_aspect('equal')
save_fig(fig, 'figures/fig_contour_quiver.pdf')
