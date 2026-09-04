#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Global figure lifecycle controller for Modex workspaces.

The controller makes figure quality a workflow stage rather than a prompt hint:
preflight profiles data and editorial choices; postflight runs integrity,
editorial, and deterministic rendered-image checks. It never edits figures or
invent numbers. REVIEW is preserved for human/model revision; BLOCK is reserved
for proxy/placeholder or hard integrity failures.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make direct execution reliable from any workspace cwd.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from figure_data_shape_profile import profile_workspace
from figure_decision_planner import plan_workspace
from figure_editorial_gate import summarize_profile, scan_script
from figure_visual_critic import inspect_workspace
from figure_render_qa import inspect as inspect_render_qa


SCHEMA = "modex.figure_system_controller.v1"


def _run_gate_script(workspace: Path, script_name: str, output_name: str) -> dict[str, Any]:
    script = Path(__file__).with_name(script_name)
    output = workspace / "_tmp" / output_name
    if not script.is_file():
        return {"returncode": 1, "verdict": "BLOCK", "error": f"{script_name} missing", "output": str(output)}
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--workspace", str(workspace), "--output", str(output)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        stdout = proc.stdout[-12000:]
        marker = re.search(r"(?:FIGURE_QUALITY|FIGURE_NUMBER)_(PASS|REVIEW|BLOCK)", stdout)
        verdict = marker.group(1) if marker else ({0: "PASS", 1: "BLOCK", 2: "REVIEW"}.get(proc.returncode, "BLOCK"))
        return {"returncode": proc.returncode, "verdict": verdict, "stdout": stdout, "stderr": proc.stderr[-3000:], "output": str(output)}
    except Exception as exc:
        return {"returncode": 1, "verdict": "BLOCK", "error": str(exc), "output": str(output)}


def run_quality_gate(workspace: Path, stage: str) -> dict[str, Any]:
    gate = Path(__file__).with_name("figure_quality_gate.py")
    try:
        proc = subprocess.run(
            [sys.executable, str(gate), "--workspace", str(workspace), "--stage", stage],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        stdout = proc.stdout[-12000:]
        marker = re.search(r"FIGURE_QUALITY_(PASS|REVIEW|BLOCK)=true", stdout)
        verdict = marker.group(1) if marker else ({0: "PASS", 1: "BLOCK", 2: "REVIEW"}.get(proc.returncode, "BLOCK"))
        return {"returncode": proc.returncode, "verdict": verdict, "stdout": stdout, "stderr": proc.stderr[-3000:]}
    except Exception as exc:
        return {"returncode": 1, "verdict": "BLOCK", "error": str(exc)}


def run(workspace: Path, stage: str) -> dict[str, Any]:
    profile = profile_workspace(workspace)
    editorial = {
        "profile_stats": summarize_profile(profile),
        "scripts": [scan_script(p) for p in sorted((workspace / "figures").glob("gen_fig_*.py"))]
        if (workspace / "figures").exists() else [],
    }
    # Keep the decision artifact beside the visual report so the model and
    # release gate receive figure-specific actions, not only workspace totals.
    decisions = plan_workspace(workspace)
    # Lifecycle artifacts belong under _tmp. The project root is reserved for
    # declared research inputs and deliverables, not automatic controller state.
    decision_path = workspace / "_tmp" / "FIGURE_DECISIONS.json"
    decision_path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    if stage == "post":
        visual = inspect_workspace(workspace, include_pdf=True)
        render_qa = inspect_render_qa(workspace)
        visual["render_qa"] = render_qa
        visual.setdefault("issues", []).extend(render_qa.get("issues") or [])
        visual["counts"]["blocks"] += sum(1 for item in render_qa.get("issues", []) if item.get("severity") == "block")
        visual["counts"]["reviews"] += sum(1 for item in render_qa.get("issues", []) if item.get("severity") == "review")
        if render_qa.get("verdict") == "BLOCK":
            visual["verdict"] = "BLOCK"
        elif render_qa.get("verdict") == "REVIEW" and visual.get("verdict") == "PASS":
            visual["verdict"] = "REVIEW"
    else:
        visual = {
            "schema": "modex.figure_visual_critic.v1",
            "workspace": str(workspace),
            "verdict": "NOT_RUN",
            "images": [], "scripts": [], "issues": [],
            "counts": {"images": 0, "scripts": 0, "blocks": 0, "reviews": 0},
            "note": "Preflight does not judge stale rendered outputs; postflight performs image inspection.",
        }
    quality = run_quality_gate(workspace, "pre" if stage == "pre" else "post")
    number_gate = _run_gate_script(workspace, "figure_number_consistency_gate.py", "FIGURE_NUMBER_CONSISTENCY_GATE.json") if stage == "post" else {"returncode": 0, "verdict": "NOT_RUN"}
    blocks = [x for x in visual.get("issues", []) if x.get("severity") == "block"]
    reviews = [x for x in visual.get("issues", []) if x.get("severity") == "review"]
    nested_figure_dir = workspace / "figures" / "figures"
    if nested_figure_dir.is_dir() and any(nested_figure_dir.iterdir()):
        blocks.append({
            "type": "nested_figure_output",
            "severity": "block",
            "action": "write final outputs directly to workspace/figures; do not create figures/figures",
            "evidence": str(nested_figure_dir),
        })
    # Figure-specific planner decisions are authoritative for proxy/placeholder
    # sources and advisory for visual redesign routes.
    for decision in decisions.get("decisions", []):
        if decision.get("decision") == "BLOCK":
            blocks.append({"figure": decision.get("figure_id", ""), "type": "figure_decision_block", "severity": "block", "action": "; ".join(decision.get("evidence_requirements", []))})
        elif decision.get("decision") == "REVIEW":
            reviews.append({"figure": decision.get("figure_id", ""), "type": "figure_decision_review", "severity": "review", "action": "; ".join(decision.get("evidence_requirements", []))})
    if quality.get("verdict") == "BLOCK":
        blocks.append({"type": "figure_quality_gate_block", "severity": "block", "action": "resolve the figure quality gate BLOCK before release", "evidence": quality.get("stdout", "")[-3000:]})
    elif quality.get("verdict") == "REVIEW":
        reviews.append({"type": "figure_quality_gate_review", "severity": "review", "action": "inspect quality gate output", "evidence": quality.get("stdout", "")[-2000:]})
    if number_gate.get("verdict") == "BLOCK":
        blocks.append({"type": "figure_number_consistency_block", "severity": "block", "action": "resolve figure/text/result number consistency BLOCK before release", "evidence": number_gate.get("stdout", number_gate.get("error", ""))[-3000:]})
    elif number_gate.get("verdict") == "REVIEW":
        reviews.append({"type": "figure_number_consistency_review", "severity": "review", "action": "inspect figure number consistency output", "evidence": number_gate.get("stdout", "")[-2000:]})
    verdict = "BLOCK" if blocks else ("REVIEW" if reviews else "PASS")
    return {
        "schema": SCHEMA,
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "workspace": str(workspace),
        "stage": stage,
        "verdict": verdict,
        "data_shape": profile,
        "editorial": editorial,
        "decisions": decisions,
        "decision_path": str(decision_path),
        "visual": visual,
        "quality_gate": quality,
        "number_consistency_gate": number_gate,
        "blocks": blocks,
        "reviews": reviews,
        "policy": {
            "3d": "retain real spatial/time/third-variable 3D; plane-like data requires projection/residual decision",
            "annotations": "evidence-triggered only; no generic conclusion sentences",
            "templates": "conditional candidates with compact/table/appendix exits",
            "source": "proxy and placeholder result sources block release",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--stage", choices=("pre", "post"), default="pre")
    ap.add_argument("--output")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    workspace = Path(args.workspace).resolve()
    report = run(workspace, args.stage)
    out = Path(args.output) if args.output else workspace / "_tmp" / f"FIGURE_SYSTEM_{args.stage.upper()}.json"
    if not out.is_absolute():
        out = workspace / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FIGURE_SYSTEM_{report['verdict']}=true")
    print(f"workspace={workspace} stage={args.stage} images={report['visual']['counts']['images']} blocks={len(report['blocks'])} reviews={len(report['reviews'])}")
    for item in report["blocks"][:20]:
        print(f"BLOCK: {item.get('figure','')} {item.get('type','')} {item.get('action','')}")
    for item in report["reviews"][:30]:
        print(f"REVIEW: {item.get('figure','')} {item.get('type','')} {item.get('action','')}")
    if args.strict and report["verdict"] == "BLOCK":
        return 1
    if args.strict and report["verdict"] == "REVIEW":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
