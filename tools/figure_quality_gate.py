#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static, data-lineage and export checks for Modex paper figures.

This gate is intentionally conservative: it blocks evidence-integrity failures
and reports visual/style risks for human review. It does not decide whether a
rare chart type is aesthetically good by itself.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from figure_data_shape_profile import profile_workspace


FIG_EXTS = {".png", ".pdf", ".svg"}
FORBIDDEN_CMAPS = {"jet", "rainbow", "nipy_spectral", "gist_rainbow", "RdYlGn"}
DEFAULT_COLORS = {"#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"}
RANDOM_RE = re.compile(r"\b(?:np\.)?random\.(?:default_rng|rand|randn|normal|uniform|choice|binomial|beta|poisson)\s*\(")
SYNTHETIC_RE = re.compile(r"\b(?:beta|normal|gaussian|synthetic|reconstruct|reconstructed|模拟重构|重构分布)\b", re.I)
PLOT_RE = re.compile(r"\b(?:barh?|plot|scatter|errorbar|fill_between|imshow|contourf?|hist|violinplot|boxplot|hexbin|pcolormesh)\s*\(")


def compact(v, n=180):
    return str(v).replace("\n", " ")[:n]


def _walk_shape_profiles(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_shape_profiles(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk_shape_profiles(value)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def inspect_png(path: Path):
    result = {}
    try:
        from PIL import Image
        with Image.open(path) as im:
            result["size"] = im.size
            result["mode"] = im.mode
            result["dpi"] = im.info.get("dpi")
    except Exception as exc:
        result["error"] = compact(exc)
    return result


def collect(workspace: Path):
    figdir = workspace / "figures"
    scripts = sorted(figdir.glob("gen_fig_*.py"))
    outputs = sorted(p for p in figdir.iterdir() if p.is_file() and p.suffix.lower() in FIG_EXTS) if figdir.exists() else []
    data = sorted(p for p in figdir.glob("*.json"))
    contracts = sorted(list(workspace.glob("FIGURE_CONTRACT.json")) + list(figdir.glob("*.contract.json")))
    manifests = sorted(list(workspace.glob("VISUALIZATION_DATA_MANIFEST.json")) + list(figdir.glob("VISUALIZATION_DATA_MANIFEST.json")))
    plans = sorted(list(workspace.glob("FIGURE_PLAN.md")) + list(workspace.glob("FIGURE_QA_REPORT.md")))
    return figdir, scripts, outputs, data, contracts, manifests, plans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--stage", choices=("pre", "post"), default="post")
    args = ap.parse_args()
    ws = Path(args.workspace).resolve()
    figdir, scripts, outputs, data, contracts, manifests, plans = collect(ws)
    blocks, reviews, passes = [], [], []
    # Existing gate now exposes content-shape risks as REVIEW without changing
    # the evidence-integrity BLOCK rules below.
    shape_report = profile_workspace(ws)
    shape_stats = {
        "arrays": 0,
        "near_constant": 0,
        "highly_repeated": 0,
        "highly_saturated": 0,
        "highly_similar_panels": 0,
        "plane_like_3d": 0,
        "line_like_3d": 0,
    }
    for item in _walk_shape_profiles(shape_report):
        summary = item.get("summary") if isinstance(item, dict) else None
        matrix = item.get("matrix") if isinstance(item, dict) else None
        sources = [summary]
        if isinstance(matrix, dict):
            sources.append(matrix.get("overall"))
            if matrix.get("highly_similar_panels"):
                shape_stats["highly_similar_panels"] += 1
        for source in sources:
            if not isinstance(source, dict):
                continue
            shape_stats["arrays"] += 1
            for key in ("near_constant", "highly_repeated", "highly_saturated"):
                if source.get(key):
                    shape_stats[key] += 1
        geometry = item.get("geometry_3d") if isinstance(item, dict) else None
        if isinstance(geometry, dict):
            kind = geometry.get("shape_class")
            if kind in {"plane_like", "line_like"}:
                shape_stats[f"{kind}_3d"] += 1

    if shape_stats["highly_repeated"]:
        reviews.append("content-shape: repeated values/rows detected; compress invariants and show exceptions")
    if shape_stats["highly_saturated"]:
        reviews.append("content-shape: high 0/1 saturation detected; avoid a full saturated heatmap")
    if shape_stats["near_constant"]:
        reviews.append("content-shape: near-constant arrays detected; prefer point/delta/interval views over large bars")
    if shape_stats["highly_similar_panels"]:
        reviews.append("content-shape: highly similar panel-like arrays detected; show differences or convergence")
    if shape_stats["plane_like_3d"] or shape_stats["line_like_3d"]:
        reviews.append("content-shape: 3D data has line/plane-like structure; retain 3D when spatial semantics matter and add projection/residual evidence")

    if not figdir.exists():
        if args.stage == "pre":
            print("REVIEW: figures/ does not exist yet; create it before rendering")
            return 0
        blocks.append("figures/ directory is missing")
    nested_dir = figdir / "figures"
    if nested_dir.is_dir() and any(nested_dir.iterdir()):
        blocks.append("figures/figures/ contains generated output; scripts must resolve the workspace figures directory explicitly")

    if args.stage == "pre":
        if not scripts:
            reviews.append("no gen_fig_*.py found yet; pre-check is advisory before implementation")
        if not (contracts or manifests or plans):
            reviews.append("no FIGURE_CONTRACT/FIGURE_PLAN/VISUALIZATION_DATA_MANIFEST found")
        if not data:
            reviews.append("no figures/*.json result source found")

    # Static source checks apply in both stages once scripts exist.
    for script in scripts:
        text = script.read_text(encoding="utf-8", errors="ignore")
        name = script.name
        if not PLOT_RE.search(text):
            reviews.append(f"{name}: no recognizable plotting call")
        cmap_names = re.findall(r"(?:cmap|colormap)\s*=\s*['\"]([^'\"]+)", text, re.I)
        for cmap in cmap_names:
            if cmap.lower() in FORBIDDEN_CMAPS:
                blocks.append(f"{name}: forbidden colormap {cmap}")
        literal_colors = {x.lower() for x in re.findall(r"#[0-9a-fA-F]{6}", text)}
        defaults = sorted(literal_colors & DEFAULT_COLORS)
        if defaults:
            reviews.append(f"{name}: matplotlib-default-like colors {defaults}")
        if RANDOM_RE.search(text):
            # Randomness is not always wrong, but it must be tied to observed
            # replicate data or explicitly labeled simulation/reconstruction.
            if not SYNTHETIC_RE.search(text):
                reviews.append(f"{name}: random generation found; verify it is observed replicate data")
            else:
                blocks.append(f"{name}: random/synthetic reconstruction may be presented as evidence")
        if re.search(r"contourf?\s*\(", text, re.I) and re.search(r"linspace\s*\(\s*[^,]+\s*,\s*[^,]+\s*,\s*[3-9]\s*\)", text):
            reviews.append(f"{name}: sparse contour grid detected; disclose interpolation or use point/facet view")
        if re.search(r"twinx\s*\(|secondary_y|secondary_yaxis", text, re.I):
            reviews.append(f"{name}: dual axis requires explicit 1:1 semantic link and units")
        if not re.search(r"(?:json\.load|read_text\s*\([^\n]*json|load\s*\()", text, re.I):
            reviews.append(f"{name}: could not find an obvious result-source read")
        if not re.search(r"(?:caption|contract|data_source|source_json|FIGURE_CONTRACT)", text, re.I):
            reviews.append(f"{name}: no visible contract/source metadata reference")
        if re.search(r"(?:savefig|save_fig|_save)\s*\([^\n]{0,180}['\"]figures[\\/]+fig_", text, re.I):
            reviews.append(f"{name}: fragile figures/fig_* relative output; use a workspace-root figure output resolver")

    if args.stage == "post":
        if not outputs:
            blocks.append("no figure output (.png/.pdf/.svg) found")
        else:
            by_stem = {}
            for p in outputs:
                by_stem.setdefault(p.stem, set()).add(p.suffix.lower())
            for stem, exts in sorted(by_stem.items()):
                if ".png" not in exts or ".pdf" not in exts:
                    reviews.append(f"{stem}: expected at least PNG + PDF, found {sorted(exts)}")
            for p in outputs:
                if p.suffix.lower() == ".png":
                    meta = inspect_png(p)
                    dpi = meta.get("dpi")
                    if meta.get("error"):
                        blocks.append(f"{p.name}: PNG unreadable ({meta['error']})")
                    elif dpi and isinstance(dpi, tuple) and min(dpi) < 299.5:
                        # Pillow often reports a nominal 300 dpi PNG as 299.9994
                        # because the pHYs integer conversion is lossy.
                        reviews.append(f"{p.name}: PNG dpi={dpi}, below 300")
        if not contracts:
            reviews.append("post-check: no figure contract found")
        if not manifests:
            reviews.append("post-check: no visualization data manifest found")

    # Basic JSON integrity check on compactly readable result files.
    for p in data:
        if p.stat().st_size > 20 * 1024 * 1024:
            reviews.append(f"{p.name}: very large source file; use compact manifest/lineage")
            continue
        obj = load_json(p)
        if obj is None:
            blocks.append(f"{p.name}: invalid JSON")

    if blocks:
        verdict = "BLOCK"
    elif reviews:
        verdict = "REVIEW"
    else:
        verdict = "PASS"
    print(f"FIGURE_QUALITY_{verdict}=true")
    print("FIGURE_QUALITY_EXIT_CODES=0:PASS,1:BLOCK,2:REVIEW")
    print(f"workspace={ws}")
    print(f"stage={args.stage} scripts={len(scripts)} outputs={len(outputs)} data_json={len(data)} shape_arrays={shape_stats['arrays']}")
    for item in blocks:
        print(f"BLOCK: {item}")
    for item in reviews:
        print(f"REVIEW: {item}")
    if not blocks and not reviews:
        print(f"PASS: figure quality {args.stage} checks passed")
    # Stable process contract consumed by figure_system_controller:
    # 0=PASS, 1=BLOCK, 2=REVIEW.
    return 1 if blocks else (2 if reviews else 0)


if __name__ == "__main__":
    sys.exit(main())
