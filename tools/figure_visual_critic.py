#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic visual preflight for Modex figure outputs.

This is a visual critic, not a scientific validator. It reads rendered PNGs
(and optionally renders PDFs with PyMuPDF when available) and reports canvas
occupancy, color-wall risk, low-contrast risk, and source-level annotation or
proxy risks. It deliberately returns REVIEW for aesthetic concerns; only
placeholders and proxy-result code are BLOCK conditions.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


FIGURE_RE = re.compile(r"^fig_.+\.(?:png|pdf|svg)$", re.I)
GENERIC_ANNOTATION_RE = re.compile(
    r"趋势明显|效果良好|结果优越|影响显著|性能提升|表现优秀|显著提升|证明.*优于"
)
PROXY_RE = re.compile(
    r"\b(?:\w+_proxy|proxy_[a-zA-Z_]*)\b|粗略估|虚拟构造|假设全投满|"
    r"THIS\s+IS\s+A\s+PLACEHOLDER|\bplaceholder\b|待\s*(?:后续|下一步).*?(?:绘制|替换)",
    re.I,
)


def compact(value: object, n: int = 240) -> str:
    return str(value).replace("\n", " ")[:n]


def source_risks(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    annotations = len(re.findall(r"\.annotate\s*\(|\.text\s*\(", text))
    proxy_hits = [compact(m.group(0), 100) for m in PROXY_RE.finditer(text)]
    generic_hits = [compact(m.group(0), 80) for m in GENERIC_ANNOTATION_RE.finditer(text)]
    # A formal HTML source may intentionally supersede an obsolete placeholder
    # Python wrapper. Do not block the valid HTML route, but keep a source
    # mismatch review so rerunning the stale wrapper cannot go unnoticed.
    sibling_html = path.with_suffix(".html")
    formal_html = sibling_html
    if path.stem.startswith("gen_"):
        formal_html = path.with_name(path.stem[4:] + ".html")
    formal_html = formal_html.is_file() and "placeholder" not in formal_html.read_text(encoding="utf-8", errors="ignore").lower()
    source_mismatch = bool(proxy_hits) and formal_html
    if source_mismatch:
        proxy_hits = []
    has_3d = bool(re.search(r"projection\s*=\s*['\"]3d['\"]|projection=['\"]3d['\"]", text, re.I))
    return {
        "script": str(path),
        "annotation_calls": annotations,
        "generic_annotation_hits": sorted(set(generic_hits)),
        "proxy_or_placeholder_hits": sorted(set(proxy_hits)),
        "formal_html_supersedes": formal_html,
        "source_mismatch_review": source_mismatch,
        "has_3d": has_3d,
        "has_heatmap": bool(re.search(r"heatmap|imshow\s*\(|pcolormesh\s*\(", text, re.I)),
        "has_bar": bool(re.search(r"\.barh?\s*\(", text, re.I)),
        "has_dumbbell": bool(re.search(r"dumbbell|哑铃", text, re.I)),
        "has_surface": bool(re.search(r"plot_surface\s*\(", text, re.I)),
    }


def _pixels(image):
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for rendered-image inspection") from exc
    if hasattr(image, "convert"):
        im = image.convert("RGB")
    else:
        im = Image.open(image).convert("RGB")
    max_side = 220
    if max(im.size) > max_side:
        scale = max_side / max(im.size)
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
    return im, list(im.getdata())


def image_stats(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image
        im, pixels = _pixels(Image.open(path))
    except Exception as exc:
        return {"file": str(path), "error": compact(exc)}
    w, h = im.size
    ink = []
    dark = 0
    chroma = 0
    for index, (r, g, b) in enumerate(pixels):
        if min(r, g, b) < 245:
            ink.append(index)
        if max(r, g, b) < 150:
            dark += 1
        if max(r, g, b) - min(r, g, b) > 70 and min(r, g, b) < 235:
            chroma += 1
    ink_fraction = len(ink) / max(1, len(pixels))
    dark_fraction = dark / max(1, len(pixels))
    chroma_fraction = chroma / max(1, len(pixels))
    # Estimate occupied bounds on the downsampled image.
    xs, ys = [], []
    for idx in ink:
        xs.append(idx % w)
        ys.append(idx // w)
    bbox = [min(xs), min(ys), max(xs), max(ys)] if xs else None
    issues = []
    if ink_fraction < 0.055:
        issues.append({"type": "underfilled_canvas", "severity": "review", "value": round(ink_fraction, 4), "action": "shrink canvas or add an evidence-bearing complementary layer"})
    if ink_fraction > 0.72:
        issues.append({"type": "overfilled_canvas", "severity": "review", "value": round(ink_fraction, 4), "action": "reduce background/color coverage and restore visual hierarchy"})
    if chroma_fraction > 0.45:
        issues.append({"type": "color_wall", "severity": "review", "value": round(chroma_fraction, 4), "action": "reserve saturated color for the primary relation; soften background layers"})
    if dark_fraction < 0.004 and ink_fraction > 0.08:
        issues.append({"type": "low_text_contrast", "severity": "review", "value": round(dark_fraction, 4), "action": "increase text/axis contrast without darkening the data field"})
    if bbox:
        margin = min(bbox[0], bbox[1], w - 1 - bbox[2], h - 1 - bbox[3]) / max(1, min(w, h))
        if margin < 0.005:
            issues.append({"type": "edge_tight", "severity": "review", "value": round(margin, 4), "action": "leave a small export margin so labels do not touch the edge"})
    return {
        "file": str(path),
        "width": w,
        "height": h,
        "aspect": round(w / max(1, h), 4),
        "ink_fraction": round(ink_fraction, 6),
        "dark_fraction": round(dark_fraction, 6),
        "chroma_fraction": round(chroma_fraction, 6),
        "ink_bbox": bbox,
        "issues": issues,
    }


def render_pdf_if_needed(pdf: Path, out_dir: Path) -> Path | None:
    """Render one PDF only when no same-stem PNG exists and PyMuPDF is present."""
    target = out_dir / (pdf.stem + ".png")
    if target.exists():
        return target
    try:
        import fitz  # type: ignore
    except ImportError:
        return None
    try:
        document = fitz.open(str(pdf))
        if not document:
            return None
        page = document[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        pix.save(str(target))
        document.close()
        return target
    except Exception:
        return None


def inspect_workspace(workspace: Path, max_images: int = 80, include_pdf: bool = True) -> dict[str, Any]:
    figures = workspace / "figures"
    tmp = workspace / "_tmp" / "figure_visual_critic"
    tmp.mkdir(parents=True, exist_ok=True)
    image_paths = sorted(p for p in figures.glob("fig_*.png") if p.is_file()) if figures.exists() else []
    if include_pdf and figures.exists():
        existing_stems = {p.stem for p in image_paths}
        for pdf in sorted(figures.glob("fig_*.pdf")):
            if pdf.stem in existing_stems:
                continue
            rendered = render_pdf_if_needed(pdf, tmp)
            if rendered:
                image_paths.append(rendered)
                existing_stems.add(pdf.stem)
    image_paths = image_paths[:max_images]
    images = [image_stats(p) for p in image_paths]
    scripts = []
    if figures.exists():
        for script in sorted(figures.glob("gen_fig_*.py")):
            scripts.append(source_risks(script))
    issues = []
    for item in images:
        issues.extend({"figure": Path(item["file"]).name, **issue} for issue in item.get("issues", []))
    for item in scripts:
        name = Path(item["script"]).name
        if item["proxy_or_placeholder_hits"]:
            issues.append({"figure": name, "type": "proxy_or_placeholder_source", "severity": "block", "evidence": item["proxy_or_placeholder_hits"], "action": "remove proxy/placeholder result and recompute from a traceable source"})
        if item.get("source_mismatch_review"):
            issues.append({"figure": name, "type": "obsolete_python_wrapper", "severity": "review", "evidence": "formal sibling HTML source exists", "action": "declare the HTML source as canonical and prevent the obsolete Python wrapper from overwriting it"})
        if item["generic_annotation_hits"]:
            issues.append({"figure": name, "type": "generic_annotation_source", "severity": "review", "evidence": item["generic_annotation_hits"], "action": "replace with a short evidence-triggered label or move the sentence to caption/body"})
        if item["annotation_calls"] > 18:
            issues.append({"figure": name, "type": "annotation_overhead", "severity": "review", "value": item["annotation_calls"], "action": "set an annotation budget and remove redundant labels"})
    blocks = [x for x in issues if x.get("severity") == "block"]
    reviews = [x for x in issues if x.get("severity") == "review"]
    verdict = "BLOCK" if blocks else ("REVIEW" if reviews else "PASS")
    return {
        "schema": "modex.figure_visual_critic.v1",
        "workspace": str(workspace),
        "verdict": verdict,
        "images": images,
        "scripts": scripts,
        "issues": issues,
        "counts": {"images": len(images), "scripts": len(scripts), "blocks": len(blocks), "reviews": len(reviews)},
        "note": "Deterministic visual metrics are a preflight signal; scientific validity remains the responsibility of numeric/semantic gates.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--output", default="_tmp/FIGURE_VISUAL_CRITIC.json")
    ap.add_argument("--max-images", type=int, default=80)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    workspace = Path(args.workspace).resolve()
    report = inspect_workspace(workspace, max_images=max(1, args.max_images), include_pdf=not args.no_pdf)
    out = Path(args.output)
    if not out.is_absolute():
        out = workspace / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FIGURE_VISUAL_{report['verdict']}=true")
    print(f"workspace={workspace} images={report['counts']['images']} scripts={report['counts']['scripts']}")
    for issue in report["issues"][:40]:
        print(f"{issue.get('severity','?').upper()}: {issue.get('figure','')} {issue.get('type','')} {compact(issue.get('action',''))}")
    if args.strict and report["verdict"] == "BLOCK":
        return 1
    if args.strict and report["verdict"] == "REVIEW":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
