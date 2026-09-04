#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional multimodal review for rendered Modex figures.

The deterministic critic remains the baseline. This tool uses the configured
reviewer endpoint only when --enable-network is explicitly passed, and writes
REVIEW/SKIP evidence instead of pretending that a missing vision model passed.
It sends at most a downscaled contact sheet plus figure names, never API keys.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any



def _figure_paths(workspace: Path) -> list[Path]:
    pngs = sorted((workspace / "figures").glob("fig_*.png"))
    paths = list(pngs)
    existing_stems = {path.stem for path in pngs}
    # HTML/vector figure steps may only have PDFs. Include those alongside PNG
    # outputs instead of letting the first PNG batch hide PDF-only diagrams.
    try:
        import fitz  # type: ignore
        for pdf in sorted((workspace / "figures").glob("fig_*.pdf")):
            if pdf.stem in existing_stems:
                continue
            document = fitz.open(str(pdf))
            if not document:
                continue
            pix = document[0].get_pixmap(matrix=fitz.Matrix(1.0, 1.0), alpha=False)
            preview = workspace / "_tmp" / "figure_vision_previews" / f"{pdf.stem}.png"
            preview.parent.mkdir(parents=True, exist_ok=True)
            pix.save(str(preview))
            document.close()
            paths.append(preview)
            existing_stems.add(pdf.stem)
    except Exception:
        pass
    return paths


def contact_sheets(workspace: Path, output_dir: Path, batch_size: int = 12) -> tuple[list[tuple[Path, list[str]]], int]:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return [], 0
    paths = _figure_paths(workspace)
    if not paths:
        return [], 0
    output_dir.mkdir(parents=True, exist_ok=True)
    sheets: list[tuple[Path, list[str]]] = []
    for batch_no in range(0, len(paths), max(1, batch_size)):
        batch = paths[batch_no:batch_no + max(1, batch_size)]
        cards = []
        names = []
        for path in batch:
            try:
                im = Image.open(path).convert("RGB")
                im.thumbnail((420, 300))
                card = Image.new("RGB", (440, 350), "white")
                card.paste(im, ((440 - im.width) // 2, 35))
                ImageDraw.Draw(card).text((8, 8), path.stem, fill="black")
                cards.append(card)
                names.append(path.stem)
            except Exception:
                continue
        if not cards:
            continue
        cols = 2
        rows = (len(cards) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 440, rows * 350), (232, 232, 232))
        for i, card in enumerate(cards):
            sheet.paste(card, ((i % cols) * 440, (i // cols) * 350))
        output = output_dir / f"contact_sheet_{batch_no // max(1, batch_size) + 1:02d}.png"
        sheet.save(output, format="PNG", optimize=True)
        sheets.append((output, names))
    return sheets, len(paths)


def contact_sheet(workspace: Path, output: Path, max_images: int = 24) -> tuple[Path | None, list[str]]:
    sheets, _ = contact_sheets(workspace, output.parent, batch_size=max_images)
    if not sheets:
        return None, []
    first, names = sheets[0]
    if first != output:
        try:
            first.replace(output)
            first = output
        except OSError:
            pass
    return first, names


def configured_reviewer() -> tuple[str, str, str]:
    db = Path.home() / "AppData" / "Roaming" / "MHAgent" / "db" / "aris.db"
    import sqlite3
    con = sqlite3.connect(str(db), timeout=5)
    try:
        values = dict(con.execute("SELECT key,value FROM settings").fetchall())
    finally:
        con.close()
    return (
        str(values.get("reviewer_base_url") or "").rstrip("/"),
        str(values.get("reviewer_api_key") or ""),
        str(values.get("reviewer_model_id") or ""),
    )


def call_vision(image: Path, names: list[str], prompt: str, timeout: int) -> str:
    base, key, model = configured_reviewer()
    if not base or not key or not model:
        raise RuntimeError("reviewer vision configuration is incomplete")
    data = base64.b64encode(image.read_bytes()).decode("ascii")
    body = {
        "model": model,
        "max_tokens": 1600,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
            {"type": "text", "text": prompt + "\n图名：" + ", ".join(names)},
        ]}],
    }
    req = urllib.request.Request(
        base + "/v1/messages",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-api-key": key, "Authorization": f"Bearer {key}", "anthropic-version": "2023-06-01", "User-Agent": "Mozilla/5.0"},
    )
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
        obj = json.loads(response.read().decode("utf-8"))
    return "".join(block.get("text", "") for block in obj.get("content", []) if isinstance(block, dict))


def _parse_review(text: str) -> dict[str, Any]:
    """Require a machine-readable verdict; prose alone is never PASS."""
    raw = text or ""
    match = re.search(r"\{.*\}", raw, re.S)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict) and str(obj.get("verdict", "")).upper() in {"PASS", "REVIEW"}:
                return {"verdict": str(obj["verdict"]).upper(), "structured": obj, "raw": raw[:4000]}
        except json.JSONDecodeError:
            pass
    return {"verdict": "REVIEW", "raw": raw[:4000], "parse_error": "vision response was not valid JSON with PASS/REVIEW verdict"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--output", default="_tmp/FIGURE_VISION_REVIEW.json")
    ap.add_argument("--enable-network", action="store_true")
    ap.add_argument("--max-images", type=int, default=12, help="figures per contact-sheet batch")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()
    ws = Path(args.workspace).resolve()
    out = Path(args.output)
    if not out.is_absolute():
        out = ws / out
    sheets, total = contact_sheets(ws, ws / "_tmp" / "figure_vision_sheets", batch_size=args.max_images)
    all_names = [name for _, names in sheets for name in names]
    report: dict[str, Any] = {
        "schema": "modex.figure_vision_review.v2",
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "workspace": str(ws),
        "figures": all_names,
        "figure_count": total,
        "batch_count": len(sheets),
        "mode": "network" if args.enable_network else "skipped",
    }
    if not sheets:
        report.update({"verdict": "REVIEW", "reason": "no rendered PNG/PDF figures available"})
    elif not args.enable_network:
        report.update({
            "verdict": "REVIEW",
            "reason": "network vision review not enabled; deterministic critic remains authoritative",
            "contact_sheets": [str(path) for path, _ in sheets],
        })
    else:
        prompt = (
            "你是科研论文图表视觉审稿人。只报告可观察的图面问题，不重算数据。"
            "检查主视觉焦点、结构性留白、重复柱墙/栅栏/瓷砖墙/空舞台、复合panel互补性、"
            "批注是否锚定证据、3D遮挡、字号和图例可读性。只输出一个 JSON 对象，格式为："
            '{"verdict":"PASS或REVIEW","issues":[{"figure":"图名","severity":"low/medium/high","reason":"具体观察"}]}'
            "。没有足够信息时输出 REVIEW，不要使用泛泛赞美。"
        )
        batches = []
        for sheet, names in sheets:
            try:
                raw = call_vision(sheet, names, prompt, args.timeout)
                batches.append({"sheet": str(sheet), "figures": names, **_parse_review(raw)})
            except Exception as exc:
                batches.append({"sheet": str(sheet), "figures": names, "verdict": "REVIEW", "reason": str(exc)})
        report["batches"] = batches
        report["contact_sheets"] = [str(path) for path, _ in sheets]
        report["verdict"] = "PASS" if batches and all(item.get("verdict") == "PASS" for item in batches) else "REVIEW"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FIGURE_VISION_{report['verdict']}=true workspace={ws} figures={total} batches={len(sheets)}")
    if report.get("reason"):
        print("REVIEW:", report["reason"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
