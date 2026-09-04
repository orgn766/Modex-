#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared semantic visual roles for Modex figures.

A role controls color, marker, line style, and visual weight together.  The
module keeps highlighting sparse and meaningful: a role is a visual contract,
not a claim of statistical significance.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class VisualRole:
    name: str
    color: str
    soft_color: str
    marker: str
    linestyle: str
    linewidth: float
    alpha: float
    zorder: int
    meaning: str


ROLES: dict[str, VisualRole] = {
    "ordinary": VisualRole("ordinary", "#7895B2", "#C7D4E0", "o", "-", 1.2, 0.68, 2, "普通数据或结构"),
    "uncertainty": VisualRole("uncertainty", "#AFC3D6", "#DCE6EE", "", "-", 0.8, 0.28, 1, "置信区间/误差带"),
    "baseline": VisualRole("baseline", "#59636E", "#B9C0C7", "D", "--", 1.3, 0.86, 4, "基准方案或参考状态"),
    "threshold": VisualRole("threshold", "#59636E", "#B9C0C7", "", "--", 1.6, 0.92, 5, "已声明的阈值或约束"),
    "optimum": VisualRole("optimum", "#C4495A", "#E5AAB2", "*", "-", 2.2, 1.0, 10, "最终选择/最优候选"),
    "turning_point": VisualRole("turning_point", "#D88932", "#F0C995", "o", "-", 1.8, 0.98, 8, "峰值、低点或转折"),
    "outlier": VisualRole("outlier", "#B85C38", "#E1B09D", "X", ":", 1.6, 0.92, 8, "偏离基准的异常对象"),
    "difference": VisualRole("difference", "#7B61A8", "#C8BCE0", "|", "-", 1.8, 0.94, 7, "有证据的组间/配对差异"),
    "mechanism": VisualRole("mechanism", "#238B70", "#A8D4C8", "o", "-", 2.0, 0.94, 8, "真实机制节点或关键路径"),
    "rejected": VisualRole("rejected", "#A7AEB6", "#D9DDE1", "x", ":", 1.1, 0.72, 3, "经约束或复核淘汰的候选"),
}


def get_role(name: str = "ordinary") -> VisualRole:
    return ROLES.get(name, ROLES["ordinary"])


def style_for(name: str = "ordinary") -> dict[str, Any]:
    role = get_role(name)
    return {
        "color": role.color,
        "soft_color": role.soft_color,
        "marker": role.marker,
        "linestyle": role.linestyle,
        "linewidth": role.linewidth,
        "alpha": role.alpha,
        "zorder": role.zorder,
    }


def role_manifest() -> dict[str, dict[str, Any]]:
    return {name: asdict(role) for name, role in ROLES.items()}


if __name__ == "__main__":
    import json
    print(json.dumps(role_manifest(), ensure_ascii=False, indent=2))
