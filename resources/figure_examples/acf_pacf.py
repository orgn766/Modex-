"""ACF / PACF 双面板：时间序列自相关与偏自相关检验。

适用：时序建模前的平稳性/拖尾截尾判断（AR/MA 阶数选择）、
      残差白噪声检验。纯 numpy 手写（bundled 无 statsmodels）。
要点：ACF 用归一化自相关，PACF 用 Levinson-Durbin 递推；
      虚线 = 95% 置信带（±1.96/√n），显著柱用深色突出。
"""
import numpy as np
import matplotlib.pyplot as plt
from _utils.plot_utils import setup_style, save_fig, PALETTE, COLORS, _lighten

setup_style()

rng = np.random.default_rng(61)
n = 400

def acf_manual(x, nlags):
    """归一化自相关"""
    x = x - x.mean()
    v = np.dot(x, x)
    out = np.zeros(nlags + 1)
    for k in range(nlags + 1):
        out[k] = np.dot(x[: n - k], x[k:]) / v if k else 1.0
    return out

def pacf_manual(x, nlags):
    """Levinson-Durbin 递推求偏自相关"""
    x = x - x.mean()
    acv = np.zeros(nlags + 1)
    for k in range(nlags + 1):
        acv[k] = np.dot(x[: n - k], x[k:]) / n if k else np.dot(x, x) / n
    pacf = np.zeros(nlags + 1)
    pacf[0] = 1.0
    a = np.zeros(nlags + 1)   # AR 系数
    a[0] = 1.0
    for i in range(1, nlags + 1):
        # 计算 phi_i,i
        num = acv[i]
        for j in range(1, i):
            num -= a[j] * acv[i - j]
        den = acv[0]
        for j in range(1, i):
            den -= a[j] * acv[j]
        phi = num / den
        pacf[i] = phi
        # 更新 AR 系数（对称性）
        new_a = a.copy()
        for j in range(1, i):
            new_a[j] = a[j] - phi * a[i - j]
        new_a[i] = phi
        a = new_a
    return pacf

# 合成 AR(2) 过程：x_t = 0.6 x_{t-1} - 0.35 x_{t-2} + ε
nlags = 24
x = np.zeros(n)
eps = rng.normal(0, 1, n)
for t in range(2, n):
    x[t] = 0.6 * x[t - 1] - 0.35 * x[t - 2] + eps[t]

acf = acf_manual(x, nlags)
pacf = pacf_manual(x, nlags)
lags = np.arange(nlags + 1)
band = 1.96 / np.sqrt(n)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)

for ax, vals, title in [(ax1, acf, 'ACF 自相关'), (ax2, pacf, 'PACF 偏自相关')]:
    colors = [PALETTE[0] if abs(v) > band else _lighten(PALETTE[0], 0.55)
              for v in vals]
    ax.vlines(lags, 0, vals, color=colors, linewidth=2.2)
    ax.scatter(lags, vals, s=14, color=colors, zorder=3)
    ax.axhline(0, color=COLORS['text'], linewidth=0.8)
    ax.axhline(band, color=COLORS['ref_line'], linestyle='--', linewidth=0.9)
    ax.axhline(-band, color=COLORS['ref_line'], linestyle='--', linewidth=0.9)
    ax.set_ylabel(title, fontsize=11)
    ax.grid(axis='y', alpha=0.12, linestyle='--', color=COLORS['grid'])
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

ax2.set_xlabel('滞后阶数 k', fontsize=11)
ax2.set_xlim(-0.8, nlags + 0.8)
fig.suptitle('AR(2) 过程自相关检验（示例：ACF 拖尾 / PACF 二阶截尾，虚线=95% 置信带）',
             fontsize=12, y=0.98)
fig.tight_layout()
save_fig(fig, 'figures/fig_acf_pacf.pdf')
