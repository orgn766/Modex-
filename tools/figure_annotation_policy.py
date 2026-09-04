#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence-triggered annotation policy for Modex figures.

This module does not place labels. It decides which annotation candidates are
justified by data relations, so plotting scripts can keep typography restrained
without inventing explanatory prose.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Iterable

try:
    from tools.figure_visual_semantics import get_role
except ImportError:  # Direct execution from the tools directory.
    from figure_visual_semantics import get_role


@dataclass(frozen=True)
class AnnotationCandidate:
    kind: str
    text: str
    index: int | None = None
    priority: int = 0
    evidence: str = ""
    anchor: str = "data"
    visual_role: str = "ordinary"


ALLOWED_KINDS = {
    "object_label",       # identifies a selected object, endpoint, or path node
    "value_label",        # gives a value when direct reading is difficult
    "threshold",           # marks a known constraint or reference level
    "turning_point",       # marks an observed/local extremum or change point
    "outlier",             # marks an evidence-backed exception
    "difference",          # marks a measured pair/group difference
    "selection",           # marks selected/baseline/rejected decision
    "mechanism",           # marks a geometric/causal-mechanistic anchor
}


def candidate(kind: str, text: str, *, index: int | None = None,
              priority: int = 50, evidence: str = "",
              anchor: str = "data", visual_role: str | None = None) -> AnnotationCandidate:
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"unsupported annotation kind: {kind}")
    role = visual_role or {
        "threshold": "threshold",
        "turning_point": "turning_point",
        "outlier": "outlier",
        "difference": "difference",
        "selection": "optimum",
        "mechanism": "mechanism",
    }.get(kind, "ordinary")
    # Fail fast on a typo so a renderer never silently falls back to a wrong role.
    get_role(role)
    return AnnotationCandidate(kind, text.strip(), index, priority, evidence, anchor, role)


def select_candidates(candidates: Iterable[AnnotationCandidate], budget: int = 6) -> list[AnnotationCandidate]:
    """Keep evidence-backed labels, deduplicate text, and enforce a budget."""
    chosen: list[AnnotationCandidate] = []
    seen = set()
    for item in sorted(candidates, key=lambda x: (-x.priority, x.kind, x.index or -1)):
        if not item.text or not item.evidence or item.text in seen:
            continue
        seen.add(item.text)
        chosen.append(item)
        if len(chosen) >= max(0, budget):
            break
    return chosen


def trend_candidates(x: list[float], y: list[float], labels: list[str] | None = None,
                     *, threshold: float | None = None, threshold_text: str | None = None,
                     budget: int = 5) -> list[AnnotationCandidate]:
    """Generate sparse labels for extrema, endpoints, and a supplied threshold.

    Labels are intentionally short. A caption should carry interpretation and
    limitations; the plot should only mark where the evidence lives.
    """
    if len(x) != len(y) or not y:
        return []
    out: list[AnnotationCandidate] = []
    if threshold is not None:
        text = threshold_text or f"阈值 {threshold:g}"
        out.append(candidate("threshold", text, priority=100, evidence="declared threshold", anchor="threshold", visual_role="threshold"))
    if len(y) >= 3:
        imax = max(range(len(y)), key=y.__getitem__)
        imin = min(range(len(y)), key=y.__getitem__)
        name_max = labels[imax] if labels and imax < len(labels) else f"x={x[imax]:g}"
        name_min = labels[imin] if labels and imin < len(labels) else f"x={x[imin]:g}"
        if imax != imin:
            out.append(candidate("turning_point", f"峰值：{name_max}", index=imax, priority=80, evidence="observed maximum", anchor="data"))
            out.append(candidate("turning_point", f"低点：{name_min}", index=imin, priority=70, evidence="observed minimum", anchor="data"))
    if labels and len(labels) == len(y):
        out.append(candidate("value_label", f"{labels[0]}：{y[0]:.3g}", index=0, priority=35, evidence="endpoint value", anchor="data"))
        if len(y) > 1:
            out.append(candidate("value_label", f"{labels[-1]}：{y[-1]:.3g}", index=len(y) - 1, priority=35, evidence="endpoint value", anchor="data"))
    return select_candidates(out, budget)


def pair_difference_candidates(labels: list[str], left: list[float], right: list[float],
                               *, min_relative_difference: float = 0.05,
                               budget: int = 5) -> list[AnnotationCandidate]:
    """Annotate only pairs with meaningful measured differences."""
    out = []
    for i, (label, a, b) in enumerate(zip(labels, left, right)):
        scale = max(abs(a), abs(b), 1e-12)
        rel = abs(b - a) / scale
        if rel >= min_relative_difference:
            out.append(candidate("difference", f"{label}：Δ={b-a:+.3g}", index=i,
                                  priority=int(50 + min(45, rel * 100)),
                                  evidence=f"paired difference relative={rel:.3g}", anchor="pair"))
    return select_candidates(out, budget)


def exception_candidates(labels: list[str], values: list[float], baseline: float,
                         *, tolerance: float = 0.05, budget: int = 6) -> list[AnnotationCandidate]:
    """Annotate exceptions and summarize the invariant outside this module."""
    out = []
    scale = max(abs(baseline), 1e-12)
    for i, (label, value) in enumerate(zip(labels, values)):
        rel = abs(value - baseline) / scale
        if rel >= tolerance:
            out.append(candidate("outlier", f"{label}：{value:.3g}", index=i,
                                  priority=int(50 + min(45, rel * 100)),
                                  evidence=f"deviation from baseline relative={rel:.3g}", anchor="data"))
    return select_candidates(out, budget)


def serialize(candidates: Iterable[AnnotationCandidate]) -> list[dict[str, Any]]:
    return [asdict(item) for item in candidates]


if __name__ == "__main__":
    demo = trend_candidates([0, 1, 2, 3], [0.2, 0.7, 0.9, 0.88], labels=["A", "B", "C", "D"], threshold=0.9, threshold_text="P=0.90")
    print(serialize(demo))
