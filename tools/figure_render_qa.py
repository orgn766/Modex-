#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic rendered-figure QA.

Checks PDF text geometry and final-size legibility without requiring OCR or a
network model. It complements visual_critic: PDF text blocks provide reliable
font-size and overlap evidence, while raster checks cover grayscale contrast.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


FINAL_FONT_RANGE_PT = (7.5, 9.0)
TEXTWIDTH_PT = 6.5 * 72.0
TEXTHEIGHT_PT = 9.0 * 72.0


def overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> tuple[float, float]:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = ix * iy
    aa = max(0.0, (a[2] - a[0]) * (a[3] - a[1]))
    ab = max(0.0, (b[2] - b[0]) * (b[3] - b[1]))
    return area, area / max(1e-9, min(aa, ab))


def _hunan_graduate_rules(workspace: Path) -> bool:
    for name in ("CLAUDE.md", "PROBLEM_ANALYSIS.md"):
        path = workspace / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if "hunan_graduate" in text or "湖南省研究生数学建模竞赛" in text:
                return True
    return False


def _dimension_pt(options: str, key: str, reference: float) -> float | None:
    match = re.search(rf"\b{key}\s*=\s*([0-9.]+)?\s*(\\textwidth|\\textheight|in|cm|mm|pt)\b", options)
    if not match:
        return None
    value = float(match.group(1) or 1.0)
    unit = match.group(2)
    return value * ({"in": 72.0, "cm": 72.0 / 2.54, "mm": 72.0 / 25.4, "pt": 1.0}.get(unit, reference))


def _planned_scale(workspace: Path, pdf: Path, width_pt: float, height_pt: float) -> tuple[float, str]:
    includes = workspace / "figures" / "latex_includes.tex"
    if includes.is_file():
        text = includes.read_text(encoding="utf-8", errors="replace")
        match = re.search(
            rf"\\includegraphics\s*\[([^\]]*)\]\s*\{{[^}}]*{re.escape(pdf.stem)}(?:\.(?:pdf|png))?\}}",
            text,
        )
        if match:
            options = match.group(1)
            width = _dimension_pt(options, "width", TEXTWIDTH_PT)
            height = _dimension_pt(options, "height", TEXTHEIGHT_PT)
            scales = [target / source for target, source in ((width, width_pt), (height, height_pt)) if target]
            if scales:
                return min(scales), "latex_includes.tex"
    ratio = height_pt / max(width_pt, 1e-9)
    target_in = 5.53 if ratio <= 0.80 else 4.55 if ratio <= 1.20 else 3.25 if ratio <= 1.60 else 2.73
    return target_in * 72.0 / max(width_pt, 1e-9), "standard aspect-ratio inclusion rule"


def pdf_text_checks(pdf: Path, workspace: Path | None = None) -> dict[str, Any]:
    # HTML/SVG figures have a browser-side geometry probe in capture.js; their
    # exported PDF text layer can contain glyph fragments and KaTeX replicas.
    html_canonical = pdf.with_suffix(".html").is_file()
    try:
        import fitz  # type: ignore
    except Exception as exc:
        return {"file": str(pdf), "status": "REVIEW", "reason": f"PyMuPDF unavailable: {exc}"}
    try:
        doc = fitz.open(str(pdf))
        if not doc:
            return {"file": str(pdf), "status": "BLOCK", "issues": [{"type": "empty_pdf", "severity": "block"}]}
        page = doc[0]
        strict_size = bool(workspace and _hunan_graduate_rules(workspace))
        scale, scale_source = _planned_scale(workspace, pdf, page.rect.width, page.rect.height) if strict_size else (1.0, "source PDF")
        blocks = []
        for raw in page.get_text("blocks"):
            x0, y0, x1, y1, text = raw[:5]
            text = str(text).strip()
            if not text:
                continue
            spans = []
            try:
                detail = page.get_text("dict", clip=fitz.Rect(x0, y0, x1, y1))
                for block in detail.get("blocks", []):
                    for line in block.get("lines", []):
                        spans.extend(line.get("spans", []))
            except Exception:
                pass
            sizes = [float(s.get("size", 0)) for s in spans if s.get("size")]
            blocks.append({
                "bbox": [x0, y0, x1, y1], "text": text[:180],
                "min_pt": min(sizes) if sizes else None, "max_pt": max(sizes) if sizes else None,
            })
        issues = []
        for i, item in enumerate(blocks):
            if strict_size and item["min_pt"] is not None:
                final_min = item["min_pt"] * scale
                final_max = item["max_pt"] * scale
                item.update({"final_min_pt": round(final_min, 2), "final_max_pt": round(final_max, 2)})
                if final_min < FINAL_FONT_RANGE_PT[0] - 0.05 or final_max > FINAL_FONT_RANGE_PT[1] + 0.05:
                    issues.append({
                        "type": "final_text_outside_7_5_to_9pt", "severity": "block",
                        "text": item["text"], "final_min_pt": round(final_min, 2),
                        "final_max_pt": round(final_max, 2), "scale": round(scale, 4),
                    })
            elif item["min_pt"] is not None and item["min_pt"] < 5.0:
                issues.append({"type": "text_below_5pt", "severity": "review", "text": item["text"], "min_pt": round(item["min_pt"], 2)})
            for other in blocks[i + 1:]:
                area, ratio = overlap(tuple(item["bbox"]), tuple(other["bbox"]))
                # PDF extractors often return adjacent wrapped lines with tiny
                # bbox intersections. Block only when the intersection is both
                # material and large relative to one text box.
                if area > 1.0 and ratio > 0.18:
                    issues.append({"type": "text_block_overlap", "severity": "review", "a": item["text"], "b": other["text"], "area": round(area, 2), "overlap_ratio": round(ratio, 3), "source": "canonical_html_browser_probe" if html_canonical else "quantitative_pdf"})
                elif area > 1.0 and ratio > 0.05:
                    issues.append({"type": "text_block_overlap_possible", "severity": "review", "a": item["text"], "b": other["text"], "area": round(area, 2), "overlap_ratio": round(ratio, 3)})
        page_rect = page.rect
        for item in blocks:
            x0, y0, x1, y1 = item["bbox"]
            if x0 < 1 or y0 < 1 or x1 > page_rect.width - 1 or y1 > page_rect.height - 1:
                issues.append({"type": "text_near_or_beyond_page_edge", "severity": "review", "text": item["text"]})
        if strict_size and not any(item["min_pt"] is not None for item in blocks):
            issues.append({"type": "final_font_size_unverifiable", "severity": "review", "reason": "PDF has no measurable text layer"})
        doc.close()
        return {"file": str(pdf), "status": "BLOCK" if any(i["severity"] == "block" for i in issues) else ("REVIEW" if issues else "PASS"), "text_blocks": len(blocks), "issues": issues, "canonical_html": html_canonical, "planned_scale": round(scale, 4), "scale_source": scale_source, "final_font_range_pt": list(FINAL_FONT_RANGE_PT) if strict_size else None, "note": "PDF text-layer collisions remain advisory because extractors can merge adjacent axes, glyph fragments, and browser text layers; canonical HTML figures should use capture.js browser geometry as the primary collision check. Raster OCR is unavailable unless a configured OCR engine is present."}
    except Exception as exc:
        return {"file": str(pdf), "status": "REVIEW", "reason": str(exc)}


def raster_checks(png: Path) -> dict[str, Any]:
    try:
        from PIL import Image, ImageOps
        im = Image.open(png).convert("RGB")
        # Final-size proxy: 180 mm at 300 dpi, preserving aspect ratio.
        target_w = max(320, min(1800, round(180 / 25.4 * 300)))
        scale = target_w / max(1, im.width)
        small = im.resize((target_w, max(1, round(im.height * scale))))
        gray = ImageOps.grayscale(small)
        values = list(gray.getdata())
        dark_share = sum(v < 110 for v in values) / max(1, len(values))
        mid_share = sum(110 <= v < 210 for v in values) / max(1, len(values))
        issues = []
        if dark_share < 0.002 and mid_share < 0.03:
            issues.append({"type": "low_grayscale_contrast", "severity": "review"})
        return {"file": str(png), "width": im.width, "height": im.height, "final_size_width_px": target_w, "issues": issues, "status": "REVIEW" if issues else "PASS", "checks": ["final_size_raster", "grayscale_contrast"]}
    except Exception as exc:
        return {"file": str(png), "status": "REVIEW", "reason": str(exc)}


def _manifest_ids(workspace: Path) -> list[str]:
    path = workspace / "PROBLEM_ANALYSIS.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"<!--\s*BEGIN FIGURE_MANIFEST\s*-->(.*?)<!--\s*END FIGURE_MANIFEST\s*-->", text, re.S)
    if not match:
        return []
    ids = []
    for line in match.group(1).splitlines():
        item = re.fullmatch(r"\s*-\s+((?:fig|tikz)_[A-Za-z0-9_]+)\s*", line)
        if item:
            ids.append(item.group(1))
    return list(dict.fromkeys(ids))


def inspect(workspace: Path) -> dict[str, Any]:
    figdir = workspace / "figures"
    results = []
    expected = _manifest_ids(workspace)
    candidates = {path.stem for pattern in ("fig_*.pdf", "tikz_*.pdf", "fig_*.png", "tikz_*.png") for path in figdir.glob(pattern)}
    for figure_id in list(dict.fromkeys([*expected, *sorted(candidates - set(expected))])):
        pdf = figdir / f"{figure_id}.pdf"
        png = figdir / f"{figure_id}.png"
        pdf_result = pdf_text_checks(pdf, workspace) if pdf.is_file() else {
            "file": str(pdf), "status": "REVIEW", "reason": "PDF missing; planted text size cannot be verified",
        }
        png_result = raster_checks(png) if png.is_file() else None
        if not pdf.is_file() and not png.is_file():
            pdf_result["reason"] = "figure declared in FIGURE_MANIFEST but no PDF/PNG exists"
        results.append({"figure_id": figure_id, "pdf": pdf_result, "png": png_result})
    issues = []
    for item in results:
        for part in (item.get("pdf"), item.get("png")):
            if isinstance(part, dict):
                part_issues = part.get("issues", [])
                issues.extend({"figure": item.get("figure_id"), "file": part.get("file"), **issue} for issue in part_issues)
                status = str(part.get("status") or "").upper()
                if status in {"BLOCK", "REVIEW"} and not part_issues:
                    issues.append({
                        "figure": item.get("figure_id"), "file": part.get("file"),
                        "type": "render_check_failed" if status == "BLOCK" else "render_check_incomplete",
                        "severity": "block" if status == "BLOCK" else "review",
                        "reason": part.get("reason", f"render check returned {status}"),
                    })
    return {"schema": "modex.figure_render_qa.v1", "workspace": str(workspace), "verdict": "BLOCK" if any(i.get("severity") == "block" for i in issues) else ("REVIEW" if issues else "PASS"), "figures": results, "issues": issues}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--output", default="_tmp/FIGURE_RENDER_QA.json")
    args = ap.parse_args()
    ws = Path(args.workspace).resolve()
    report = inspect(ws)
    out = Path(args.output)
    if not out.is_absolute():
        out = ws / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FIGURE_RENDER_QA_{report['verdict']}=true workspace={ws} figures={len(report['figures'])} issues={len(report['issues'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
