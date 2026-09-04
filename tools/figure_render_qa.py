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
from pathlib import Path
from typing import Any


def overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> tuple[float, float]:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = ix * iy
    aa = max(0.0, (a[2] - a[0]) * (a[3] - a[1]))
    ab = max(0.0, (b[2] - b[0]) * (b[3] - b[1]))
    return area, area / max(1e-9, min(aa, ab))


def pdf_text_checks(pdf: Path) -> dict[str, Any]:
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
            return {"file": str(pdf), "status": "BLOCK", "issues": [{"type": "empty_pdf"}]}
        page = doc[0]
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
            blocks.append({"bbox": [x0, y0, x1, y1], "text": text[:180], "min_pt": min(sizes) if sizes else None})
        issues = []
        for i, item in enumerate(blocks):
            if item["min_pt"] is not None and item["min_pt"] < 5.0:
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
        doc.close()
        return {"file": str(pdf), "status": "BLOCK" if any(i["severity"] == "block" for i in issues) else ("REVIEW" if issues else "PASS"), "text_blocks": len(blocks), "issues": issues, "canonical_html": html_canonical, "note": "PDF text-layer collisions remain advisory because extractors can merge adjacent axes, glyph fragments, and browser text layers; canonical HTML figures should use capture.js browser geometry as the primary collision check. Raster OCR is unavailable unless a configured OCR engine is present."}
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


def inspect(workspace: Path) -> dict[str, Any]:
    figdir = workspace / "figures"
    results = []
    for pdf in sorted(figdir.glob("fig_*.pdf")):
        results.append({"pdf": pdf_text_checks(pdf), "png": raster_checks(pdf.with_suffix(".png")) if pdf.with_suffix(".png").is_file() else None})
    issues = []
    for item in results:
        for part in (item.get("pdf"), item.get("png")):
            if isinstance(part, dict):
                issues.extend({"file": part.get("file"), **issue} for issue in part.get("issues", []))
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
