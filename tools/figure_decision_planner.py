#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create figure-level decisions before rendering in a Modex workspace.

This planner does not choose scientific claims or alter plots. It turns the
available source scripts and data-shape signals into an auditable decision:
which route is preferred, which evidence layers are needed, and when a figure
must be compacted, demoted, or blocked.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from figure_data_shape_profile import profile_workspace
from figure_editorial_gate import scan_script, summarize_profile


SCHEMA = "modex.figure_decisions.v1"


def _source_files(script: Path) -> list[str]:
    text = script.read_text(encoding="utf-8", errors="ignore")
    names = sorted(set(re.findall(r"(?:problem[_-]\d+[_-]results|all_results|_plot_data|results|[A-Za-z0-9_-]+)\.json", text)))
    return names[:12]


def _decision_for(item: dict[str, Any], shape_stats: dict[str, int]) -> dict[str, Any]:
    name = Path(item["file"]).stem
    decisions: list[str] = []
    evidence: list[str] = []
    role = "support"
    if item.get("proxy_or_placeholder_hits"):
        decisions.append("BLOCK_PROXY_OR_PLACEHOLDER")
        evidence.append("traceable computed source is required")
    if item.get("has_3d"):
        role = "main" if any(token in name for token in ("path", "resid", "surface", "space", "3d")) else role
        decisions.append("retain_3d_with_semantic_check")
        evidence.append("declare third-dimension role; add projection/residual when line-like or plane-like")
    if item.get("has_heatmap"):
        if shape_stats.get("highly_saturated", 0):
            decisions.append("prefer_exception_or_annotated_matrix")
            evidence.append("compress saturated invariant cells and expose exceptions")
        else:
            decisions.append("retain_heatmap_if_scale_is_semantic")
    if item.get("has_bar"):
        if shape_stats.get("near_constant", 0):
            decisions.append("prefer_sorted_point_or_delta_view")
            evidence.append("avoid equal-height bar wall for near-constant values")
        else:
            decisions.append("bar_allowed_if_common_scale_is_meaningful")
    if item.get("has_dumbbell") and shape_stats.get("highly_repeated", 0):
        decisions.append("compress_invariant_pairs_show_exceptions")
        evidence.append("avoid repeated fence of identical paired segments")
    if item.get("has_multi_panel"):
        decisions.append("require_panel_complementarity")
        evidence.append("each panel must add result, difference, mechanism, uncertainty, or decision evidence")
    if not decisions:
        decisions.append("compact_single_or_evidence_layered_plot")
        evidence.append("do not add visual elements only to fill the canvas")
    if item.get("annotation_calls", 0) > 12:
        decisions.append("reduce_annotations_to_evidence_triggers")
        evidence.append("use threshold, turning point, outlier, difference, selection, or mechanism anchors")
    if any(d.startswith("BLOCK") for d in decisions):
        final = "BLOCK"
    elif any(d.startswith("prefer") or d.startswith("compress") or d.startswith("reduce") for d in decisions):
        final = "REVIEW"
    else:
        final = "PASS"
    return {
        "figure_id": name.replace("gen_fig_", "fig_"),
        "script": str(item["file"]),
        "role": role,
        "decision": final,
        "routes": decisions,
        "evidence_requirements": evidence,
        "source_files": _source_files(Path(item["file"])),
        "annotation_budget": 6 if item.get("has_multi_panel") else 4,
        "3d": {
            "detected": bool(item.get("has_3d")),
            "required_action": "declare geometry_semantics and projection_or_residual" if item.get("has_3d") else None,
        },
        "template_policy": "conditional_candidate_not_fixed_mold",
    }


def plan_workspace(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    profile = profile_workspace(workspace)
    shape_stats = summarize_profile(profile)
    figdir = workspace / "figures"
    scripts = [scan_script(p) for p in sorted(figdir.glob("gen_fig_*.py"))] if figdir.exists() else []
    decisions = [_decision_for(item, shape_stats) for item in scripts]
    return {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "workspace": str(workspace),
        "shape_stats": shape_stats,
        "decisions": decisions,
        "global_rules": [
            "data shape precedes template selection",
            "compress invariants and expose exceptions",
            "use evidence-triggered annotations only",
            "retain real spatial/time/third-variable 3D with semantic diagnostics",
            "proxy or placeholder result sources cannot be released",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--output", default="_tmp/FIGURE_DECISIONS.json")
    args = ap.parse_args()
    workspace = Path(args.workspace).resolve()
    report = plan_workspace(workspace)
    out = Path(args.output)
    if not out.is_absolute():
        out = workspace / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    blocks = sum(item["decision"] == "BLOCK" for item in report["decisions"])
    reviews = sum(item["decision"] == "REVIEW" for item in report["decisions"])
    print(f"FIGURE_DECISIONS_READY=true figures={len(report['decisions'])} blocks={blocks} reviews={reviews}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
