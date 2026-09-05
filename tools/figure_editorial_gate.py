#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Editorial gate for figure choice, density, hierarchy, and template fit.

This complements figure_quality_gate.py. It is advisory by default because a
reviewer may intentionally keep a dense or unusual figure. Use --strict when a
workflow checkpoint should stop on unresolved BLOCK items.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from figure_data_shape_profile import profile_workspace


def compact(value: object, n: int = 180) -> str:
    return str(value).replace("\n", " ")[:n]


def walk_profiles(obj: object):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_profiles(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_profiles(value)


def summarize_profile(report: dict) -> dict:
    stats = {
        "near_constant": 0,
        "highly_repeated": 0,
        "highly_saturated": 0,
        "highly_similar_panels": 0,
        "arrays": 0,
        "plane_like_3d": 0,
        "line_like_3d": 0,
        "volumetric_3d": 0,
    }
    for item in walk_profiles(report):
        summary = item.get("summary") if isinstance(item, dict) else None
        matrix = item.get("matrix") if isinstance(item, dict) else None
        for source in (summary, matrix.get("overall") if isinstance(matrix, dict) else None):
            if not isinstance(source, dict):
                continue
            stats["arrays"] += 1
            for key in ("near_constant", "highly_repeated", "highly_saturated"):
                if source.get(key):
                    stats[key] += 1
        if isinstance(matrix, dict) and matrix.get("highly_similar_panels"):
            stats["highly_similar_panels"] += 1
        geometry = item.get("geometry_3d") if isinstance(item, dict) else None
        if isinstance(geometry, dict):
            kind = geometry.get("shape_class")
            if kind in {"plane_like", "line_like", "volumetric"}:
                stats[f"{kind}_3d"] += 1
    return stats


def scan_script(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    weak_phrases = re.findall(r"趋势明显|效果良好|结果优越|影响显著|性能提升|表现优秀|显著提升", text)
    proxy_hits = re.findall(
        r"\b(?:\w+_proxy|proxy_[A-Za-z_]*)\b|粗略估|虚拟构造|假设全投满|"
        r"THIS\s+IS\s+A\s+PLACEHOLDER|\bplaceholder\b|待\s*(?:后续|下一步).*?(?:绘制|替换)",
        text, re.I,
    )
    html_source = path.with_name(path.stem[4:] + ".html") if path.stem.startswith("gen_") else path.with_suffix(".html")
    formal_html_supersedes = html_source.is_file() and "placeholder" not in html_source.read_text(encoding="utf-8", errors="ignore").lower()
    source_mismatch = bool(proxy_hits) and formal_html_supersedes
    if source_mismatch:
        proxy_hits = []
    return {
        "file": str(path),
        "has_3d": bool(re.search(r"projection\s*=\s*['\"]3d['\"]|add_subplot\([^\n]*3d", text, re.I)),
        "has_heatmap": bool(re.search(r"heatmap|imshow\s*\(|pcolormesh\s*\(", text, re.I)),
        "has_bar": bool(re.search(r"\.barh?\s*\(", text, re.I)),
        "has_dumbbell_hint": bool(re.search(r"dumbbell|paired|哑铃", text, re.I)),
        "has_multi_panel": bool(re.search(r"subplots\s*\(|GridSpec|add_subplot", text, re.I)),
        "fixed_figsize": bool(re.search(r"figsize\s*=\s*\([^)]*\)", text, re.I)),
        "annotation_calls": len(re.findall(r"\.annotate\s*\(|\.text\s*\(", text)),
        "weak_annotation_phrases": weak_phrases,
        "proxy_or_placeholder_hits": sorted(set(proxy_hits)),
        "formal_html_supersedes": formal_html_supersedes,
        "source_mismatch_review": source_mismatch,
        "loads_json": bool(re.search(r"json\.load|read_text\([^\n]*json|load_json", text, re.I)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--stage", choices=("pre", "post"), default="pre")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--output", default="_tmp/figure_editorial_report.json")
    args = ap.parse_args()
    ws = Path(args.workspace).resolve()
    figdir = ws / "figures"
    report = profile_workspace(ws)
    profile_stats = summarize_profile(report)
    scripts = [scan_script(p) for p in sorted(figdir.glob("gen_fig_*.py"))] if figdir.exists() else []
    reviews: list[str] = []
    blocks: list[str] = []

    if profile_stats["highly_repeated"]:
        reviews.append("data contains highly repeated values/rows: compress invariant, expose exceptions")
    if profile_stats["highly_saturated"]:
        reviews.append("data contains a high 0/1 saturation share: avoid a full saturated heatmap")
    if profile_stats["near_constant"]:
        reviews.append("data contains near-constant arrays: prefer a common-scale point/delta view over bars")
    if profile_stats["highly_similar_panels"]:
        reviews.append("panel-like arrays are highly similar: replace repeated panels with delta/convergence evidence")
    if profile_stats["plane_like_3d"]:
        reviews.append("3D point-cloud data includes plane-like structure: keep 3D when spatial semantics matter, and add a projection or off-plane residual panel")
    if profile_stats["line_like_3d"]:
        reviews.append("3D point-cloud data includes line-like structure: inspect collinearity; use 3D only when spatial context or trajectory semantics add evidence")

    for item in scripts:
        if item["has_3d"]:
            reviews.append(f"{Path(item['file']).name}: declare real spatial/continuous third dimension; for plane-like data add projection/residual evidence rather than forcing volume")
        if item["has_bar"] and item["fixed_figsize"] and profile_stats["near_constant"]:
            reviews.append(f"{Path(item['file']).name}: fixed-size bars with near-constant data may form a flag-like wall; use dot/delta view")
        if item["has_heatmap"] and profile_stats["highly_saturated"]:
            reviews.append(f"{Path(item['file']).name}: saturated heatmap may become a tile wall; aggregate invariant rows")
        if item["has_dumbbell_hint"] and profile_stats["highly_repeated"]:
            reviews.append(f"{Path(item['file']).name}: repeated paired values may become a fence; plot exceptions and aggregate common pattern")
        if item["annotation_calls"] > 18:
            reviews.append(f"{Path(item['file']).name}: {item['annotation_calls']} annotation calls; set an annotation budget and move detail to caption/table")
        if item["weak_annotation_phrases"]:
            reviews.append(f"{Path(item['file']).name}: generic conclusion annotations found {item['weak_annotation_phrases']}; replace with an evidence-triggered short label or move claim to caption")
        if item["proxy_or_placeholder_hits"]:
            blocks.append(f"{Path(item['file']).name}: proxy/placeholder result source found {item['proxy_or_placeholder_hits']}; recompute from traceable data before release")
        if item.get("source_mismatch_review"):
            reviews.append(f"{Path(item['file']).name}: obsolete Python wrapper has a formal HTML sibling; declare the HTML source canonical and prevent overwrite")

    contracts = list(ws.glob("FIGURE_CONTRACT.json")) + list(figdir.glob("*.contract.json"))
    if args.stage == "post" and not contracts:
        reviews.append("post-check: no figure contract found; editorial role and composition cannot be audited")
    if not figdir.exists():
        reviews.append("figures/ does not exist yet")

    result = {
        "schema": "modex.figure_editorial_gate.v1",
        "workspace": str(ws),
        "stage": args.stage,
        "verdict": "BLOCK" if blocks else ("REVIEW" if reviews else "PASS"),
        "profile_stats": profile_stats,
        "scripts": scripts,
        "blocks": blocks,
        "reviews": reviews,
        "actions": [
            "select chart from data shape, not topic name",
            "compress invariants and expand exceptions",
            "use composite panels only when each adds independent evidence",
            "allow compact single figure/table/inset/appendix exits",
        ],
    }
    out = (ws / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FIGURE_EDITORIAL_{result['verdict']}=true")
    print(f"workspace={ws}")
    print(f"stage={args.stage} scripts={len(scripts)} arrays={profile_stats['arrays']}")
    for item in blocks:
        print(f"BLOCK: {compact(item)}")
    for item in reviews:
        print(f"REVIEW: {compact(item)}")
    if not reviews and not blocks:
        print("PASS: no editorial risk detected by static/data-shape checks")
    # Advisory by default; strict mode turns unresolved editorial reviews into
    # a checkpoint failure, while still leaving existing quality BLOCK rules
    # unchanged in figure_quality_gate.py.
    return 2 if args.strict and (blocks or reviews) else 0


if __name__ == "__main__":
    raise SystemExit(main())
