#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Profile figure input data before a chart template is selected.

The profiler is deliberately dependency-light. It describes effective visual
variation rather than judging scientific validity: repeated rows, saturation,
near-constant values, panel similarity, and available uncertainty fields.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any



def is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def flatten_numbers(value: Any) -> list[float]:
    if is_num(value):
        return [float(value)]
    if isinstance(value, list):
        out: list[float] = []
        for item in value:
            out.extend(flatten_numbers(item))
        return out
    return []


def numeric_rows(value: Any) -> list[list[float]]:
    if not isinstance(value, list) or len(value) < 2:
        return []
    rows = []
    for row in value:
        vals = flatten_numbers(row)
        if len(vals) >= 3:
            rows.append(vals)
    widths = {len(row) for row in rows}
    return rows if len(widths) == 1 else []


def rounded_pattern(row: list[float]) -> tuple[float, ...]:
    return tuple(round(v, 8) for v in row)


def corr(a: list[float], b: list[float]) -> float | None:
    if len(a) != len(b) or len(a) < 3:
        return None
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    if da == 0 or db == 0:
        return 1.0 if a == b else 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (da * db)


def planarity_metrics(rows: list[list[float]]) -> dict[str, Any]:
    """Describe whether an n x 3 cloud is line-like, plane-like, or volumetric."""
    if len(rows) < 4 or any(len(row) != 3 for row in rows):
        return {"available": False}
    means = [sum(row[j] for row in rows) / len(rows) for j in range(3)]
    cov = [[sum((row[i] - means[i]) * (row[j] - means[j]) for row in rows) / (len(rows) - 1) for j in range(3)] for i in range(3)]
    try:
        # Symmetric 3x3 Jacobi diagonalization keeps this preflight usable
        # with the system Python as well as Modex's bundled Python.
        a = [row[:] for row in cov]
        for _ in range(64):
            p, q = max(((i, j) for i in range(3) for j in range(i + 1, 3)), key=lambda ij: abs(a[ij[0]][ij[1]]))
            if abs(a[p][q]) < 1e-12:
                break
            theta = 0.5 * math.atan2(2.0 * a[p][q], a[q][q] - a[p][p])
            c, s = math.cos(theta), math.sin(theta)
            app, aqq, apq = a[p][p], a[q][q], a[p][q]
            a[p][p] = c * c * app - 2.0 * s * c * apq + s * s * aqq
            a[q][q] = s * s * app + 2.0 * s * c * apq + c * c * aqq
            a[p][q] = a[q][p] = 0.0
            for k in range(3):
                if k in (p, q):
                    continue
                akp, akq = a[k][p], a[k][q]
                a[k][p] = a[p][k] = c * akp - s * akq
                a[k][q] = a[q][k] = s * akp + c * akq
        eig = sorted((max(0.0, a[i][i]) for i in range(3)), reverse=True)
        total = sum(eig)
        if total <= 1e-14:
            return {"available": True, "degenerate": True, "eigenvalues": eig}
        explained = [v / total for v in eig]
        return {
            "available": True,
            "eigenvalues": eig,
            "explained_variance": [round(v, 6) for v in explained],
            "linearity": round((eig[0] - eig[1]) / eig[0], 6) if eig[0] else 0.0,
            "planarity": round((eig[1] - eig[2]) / eig[0], 6) if eig[0] else 0.0,
            "volumetricity": round(eig[2] / eig[0], 6) if eig[0] else 0.0,
            "shape_class": (
                "line_like" if eig[1] / eig[0] < 0.05 else
                "plane_like" if eig[2] / eig[0] < 0.05 else
                "volumetric"
            ),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def summarize(values: list[float], label: str = "values") -> dict[str, Any]:
    if not values:
        return {"label": label, "n": 0}
    lo, hi = min(values), max(values)
    mean = sum(values) / len(values)
    scale = max(abs(mean), abs(lo), abs(hi), 1e-12)
    counts: dict[float, int] = {}
    for value in values:
        key = round(value, 8)
        counts[key] = counts.get(key, 0) + 1
    modal_count = max(counts.values())
    saturation = sum(abs(v) <= 1e-12 or abs(v - 1.0) <= 1e-12 for v in values) / len(values)
    return {
        "label": label,
        "n": len(values),
        "unique_count": len(counts),
        "unique_value_ratio": round(len(counts) / len(values), 6),
        "min": lo,
        "max": hi,
        "mean": mean,
        "relative_range": round((hi - lo) / scale, 6),
        "modal_value_share": round(modal_count / len(values), 6),
        "saturation_0_1_share": round(saturation, 6),
        "near_constant": (hi - lo) / scale < 0.03,
        "highly_repeated": modal_count / len(values) > 0.80,
        "highly_saturated": saturation > 0.70,
    }


def profile_rows(rows: list[list[float]], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {"label": label, "rows": len(rows), "columns": len(rows[0]) if rows else 0}
    if not rows:
        return result
    result["overall"] = summarize([v for row in rows for v in row], label)
    patterns = {}
    for row in rows:
        key = rounded_pattern(row)
        patterns[key] = patterns.get(key, 0) + 1
    result["unique_row_count"] = len(patterns)
    result["modal_row_share"] = round(max(patterns.values()) / len(rows), 6)
    result["repeated_row_pattern"] = result["modal_row_share"] > 0.80
    similarities = []
    for i in range(1, len(rows)):
        value = corr(rows[0], rows[i])
        if value is not None:
            similarities.append(value)
    result["panel_similarity_to_first"] = round(sum(similarities) / len(similarities), 6) if similarities else None
    result["highly_similar_panels"] = bool(similarities) and result["panel_similarity_to_first"] > 0.95
    if len(rows[0]) == 3:
        result["geometry_3d"] = planarity_metrics(rows)
    return result


def find_numeric_arrays(value: Any, path: str = "$") -> list[dict[str, Any]]:
    found = []
    if isinstance(value, list):
        vals = flatten_numbers(value)
        if len(vals) >= 3:
            item = {"path": path, "summary": summarize(vals, path)}
            rows = numeric_rows(value)
            if rows:
                item["matrix"] = profile_rows(rows, path)
            found.append(item)
        for i, child in enumerate(value):
            found.extend(find_numeric_arrays(child, f"{path}[{i}]"))
    elif isinstance(value, dict):
        for key, child in value.items():
            found.extend(find_numeric_arrays(child, f"{path}.{key}"))
    return found


def load_input(path: Path) -> Any:
    if path.suffix.lower() in {".csv", ".tsv"}:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=delimiter))
        return rows
    return json.loads(path.read_text(encoding="utf-8"))


def profile_file(path: Path) -> dict[str, Any]:
    obj = load_input(path)
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        numeric = {}
        for key in obj[0]:
            vals = []
            for row in obj:
                try:
                    value = float(row[key])
                except (KeyError, TypeError, ValueError):
                    continue
                if is_num(value):
                    vals.append(value)
            if vals:
                numeric[key] = summarize(vals, key)
        numeric_rows = []
        keys = list(numeric)
        if len(keys) == 3 and len(obj) >= 4:
            for row in obj:
                try:
                    numeric_rows.append([float(row[key]) for key in keys])
                except (TypeError, ValueError):
                    pass
        result = {"file": str(path), "kind": "tabular", "rows": len(obj), "columns": numeric}
        if numeric_rows:
            result["geometry_3d"] = planarity_metrics(numeric_rows)
        return result
    return {"file": str(path), "kind": "json", "arrays": find_numeric_arrays(obj)}


def profile_workspace(ws: Path) -> dict[str, Any]:
    figdir = ws / "figures"
    files = sorted([p for p in figdir.glob("*.json") if p.is_file()]) if figdir.exists() else []
    reports = []
    for path in files:
        try:
            reports.append(profile_file(path))
        except Exception as exc:
            reports.append({"file": str(path), "error": str(exc)})
    return {
        "schema": "modex.figure_data_shape_profile.v1",
        "workspace": str(ws),
        "files": reports,
        "interpretation": {
            "near_constant": "relative_range < 0.03; prefer point or delta views",
            "highly_repeated": "modal value/row share > 0.80; compress invariant and show exceptions",
            "highly_saturated": "0/1 share > 0.70; avoid full saturated heatmaps",
            "highly_similar_panels": "mean correlation > 0.95; show differences or convergence instead",
            "geometry_3d": "PCA-style eigenvalue ratios classify line-like/plane-like/volumetric; spatial semantics may justify retaining a plane-like 3D view",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", action="append", help="JSON/CSV/TSV input; repeatable")
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--output", help="write JSON report to this path")
    args = ap.parse_args()
    ws = Path(args.workspace).resolve()
    report = profile_workspace(ws) if not args.input else {
        "schema": "modex.figure_data_shape_profile.v1",
        "files": [profile_file(Path(p).resolve()) for p in args.input],
    }
    output = Path(args.output) if args.output else None
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
