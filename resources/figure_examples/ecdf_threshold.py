"""ECDF + threshold/exceedance band: use with real repeated observations."""
import numpy as np
import matplotlib.pyplot as plt
from _utils.plot_utils import setup_style, save_fig, PALETTE, COLORS

setup_style()
# Replace these arrays with repeated observations from the result manifest.
rng = np.random.default_rng(2026)
groups = {"方案A": rng.normal(0.38, 0.08, 180), "方案B": rng.normal(0.48, 0.10, 180)}
threshold = 0.55
fig, ax = plt.subplots(figsize=(7.2, 4.4))
for i, (name, vals) in enumerate(groups.items()):
    x = np.sort(vals)
    y = np.arange(1, len(x) + 1) / len(x)
    ax.step(x, y, where="post", color=PALETTE[i], lw=2.0, label=f"{name}（n={len(x)}）")
    ax.scatter(x[::12], y[::12], color=PALETTE[i], s=14, edgecolor="white", lw=.4, zorder=3)
ax.axvline(threshold, color=COLORS["highlight"], ls="--", lw=1.4, label=f"阈值={threshold:g}")
ax.axhspan(0, 1, xmin=0, xmax=1, color=COLORS["surface"] if "surface" in COLORS else "#F7F8FA", alpha=.35, zorder=-2)
ax.set(xlabel="风险指标（原始单位）", ylabel="经验累积分布 F(x)")
ax.grid(axis="y", alpha=.12, color=COLORS["grid"])
ax.legend(frameon=False, loc="best")
fig.tight_layout()
save_fig(fig, "figures/fig_ecdf_threshold.pdf")
