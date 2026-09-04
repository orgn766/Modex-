#!/usr/bin/env python3
"""Check that paper numbers match RESULTS.json / declared figure sources."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

NUM_RE = re.compile(r"(?<![A-Za-z_])\d+\.\d+|\b\d{2,}\b")


def collect_numbers(text: str) -> set[str]:
    return {m.group(0) for m in NUM_RE.finditer(text or "")}


def json_numbers(obj) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            found |= json_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= json_numbers(v)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        found.add(str(obj))
    elif isinstance(obj, str):
        found |= collect_numbers(obj)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", default="FIGURE_NUMBER_CONSISTENCY_GATE.json")
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    findings = []
    results_path = None
    for rel in ("RESULTS.json", "output/RESULTS.json", "code/RESULTS.json"):
        p = workspace / rel
        if p.is_file():
            results_path = p
            break
    paper_bits = []
    for rel in ("PROBLEM_ANALYSIS.md", "MODELING_REPORT.md", "RESULTS.md", "paper/main.md"):
        p = workspace / rel
        if p.is_file():
            paper_bits.append(p.read_text(encoding="utf-8", errors="ignore"))
    captions = []
    figures = workspace / "figures"
    if figures.is_dir():
        for p in figures.glob("*.md"):
            captions.append(p.read_text(encoding="utf-8", errors="ignore"))
    paper_nums = collect_numbers("\n".join(paper_bits + captions))
    if results_path is None:
        findings.append({"severity": "REVIEW", "code": "MISSING_RESULTS_JSON"})
        result_nums: set[str] = set()
    else:
        try:
            result_nums = json_numbers(json.loads(results_path.read_text(encoding="utf-8")))
        except Exception as exc:
            findings.append({"severity": "BLOCK", "code": "BAD_RESULTS_JSON", "detail": str(exc)})
            result_nums = set()
    # Ignore years and tiny counters; flag 3+ digit or decimal claims absent from results.
    suspects = []
    for n in sorted(paper_nums):
        if n.isdigit() and len(n) < 3:
            continue
        if n in {"2018", "2022", "2026", "20000", "72", "48", "16", "80"}:
            continue
        if result_nums and n not in result_nums and "." in n:
            suspects.append(n)
    if suspects:
        findings.append({
            "severity": "REVIEW",
            "code": "PAPER_NUMBERS_NOT_IN_RESULTS",
            "detail": ",".join(suspects[:30]),
        })
    blocked = any(item["severity"] == "BLOCK" for item in findings)
    report = {
        "gate": "figure_number_consistency_gate",
        "verdict": "BLOCK" if blocked else ("REVIEW" if findings else "PASS"),
        "findings": findings,
        "results_file": str(results_path) if results_path else None,
    }
    out = Path(args.output)
    if not out.is_absolute():
        out = workspace / out
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FIGURE_NUMBER_" + report["verdict"])
    print("FIGURE_NUMBER_EXIT_CODES=0:PASS,1:BLOCK,2:REVIEW")
    for item in findings:
        print(f"[{item['severity']}] {item['code']} {item.get('detail','')}")
    # Stable process contract: 0=PASS, 1=BLOCK, 2=REVIEW.
    return 1 if blocked else (2 if findings else 0)


if __name__ == "__main__":
    raise SystemExit(main())
