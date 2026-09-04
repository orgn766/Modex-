#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Visual-continuity guard for Modex figure reruns.

It does not score beauty mechanically.  It records the existing figure family
before a rerun and makes destructive, unexplained replacement visible after a
rerun.  Hard failures are limited to invalid output paths; all aesthetic or
editorial continuity risks remain REVIEW items for model repair.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "modex.figure_regression_guard.v1"
NESTED_OUTPUT_RE = re.compile(
    r"(?:savefig|save_fig|_save)\s*\([^\n]{0,160}['\"]figures[\\/]+fig_",
    re.I,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def snapshot(workspace: Path) -> dict[str, Any]:
    figdir = workspace / "figures"
    items: dict[str, dict[str, Any]] = {}
    if figdir.is_dir():
        candidates = list(figdir.glob("fig_*")) + list(figdir.glob("gen_fig_*.py"))
        for path in sorted(set(candidates)):
            if path.is_file() and path.suffix.lower() in {".py", ".pdf", ".png", ".svg", ".html"}:
                rel = path.relative_to(workspace).as_posix()
                items[rel] = {"digest": digest(path), "bytes": path.stat().st_size}
    return {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "workspace": str(workspace),
        "items": items,
    }


def inspect(workspace: Path, baseline: dict[str, Any] | None) -> dict[str, Any]:
    figdir = workspace / "figures"
    reviews: list[dict[str, str]] = []
    blocks: list[dict[str, str]] = []
    current = snapshot(workspace)
    nested = figdir / "figures"
    if nested.is_dir() and any(nested.iterdir()):
        blocks.append({
            "type": "nested_figure_output",
            "action": "move final outputs directly to figures/ and remove figures/figures/; scripts inside figures/ must save fig_<id>.pdf/png without a figures/ prefix",
            "evidence": str(nested),
        })
    for script in sorted(figdir.glob("gen_fig_*.py")) if figdir.is_dir() else []:
        text = script.read_text(encoding="utf-8", errors="ignore")
        if NESTED_OUTPUT_RE.search(text):
            reviews.append({
                "type": "fragile_relative_output_path",
                "figure": script.name,
                "action": "use a workspace-root resolver or save fig_<id>.pdf/png relative to the figures script directory; do not hard-code figures/fig_* in scripts run from figures/",
            })
    old = (baseline or {}).get("items") or {}
    changed_scripts = []
    for rel, before in old.items():
        if rel.startswith("figures/gen_fig_") and rel in current["items"]:
            if before.get("digest") != current["items"][rel].get("digest"):
                changed_scripts.append(rel)
    if changed_scripts:
        reviews.append({
            "type": "visual_master_replaced",
            "action": "confirm each rewritten script preserved the prior visual hierarchy or document why the old structure was invalid; do not replace a valid design merely to satisfy a new checklist",
            "evidence": ", ".join(changed_scripts[:20]),
        })
    return {
        "schema": SCHEMA,
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "workspace": str(workspace),
        "verdict": "BLOCK" if blocks else ("REVIEW" if reviews else "PASS"),
        "baseline_items": len(old),
        "current_items": len(current["items"]),
        "blocks": blocks,
        "reviews": reviews,
        "current": current,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--stage", choices=("snapshot", "compare"), required=True)
    parser.add_argument("--baseline")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = workspace / output
    if args.stage == "snapshot":
        report = snapshot(workspace)
    else:
        baseline: dict[str, Any] | None = None
        if args.baseline:
            path = Path(args.baseline)
            if not path.is_absolute():
                path = workspace / path
            try:
                baseline = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                baseline = None
        report = inspect(workspace, baseline)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FIGURE_REGRESSION_{report.get('verdict', 'PASS')}=true")
    return 1 if report.get("verdict") == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
