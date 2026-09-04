#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed the global figure system into a Modex workspace.

The official figure skills run inside the workspace and can use the global
figure-system tools directly. By default this command only validates that the
global resources exist; workspace materialization is explicit and opt-in. It
never copies result data or changes figures.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

TOOL_NAMES = (
    "figure_data_shape_profile.py",
    "figure_editorial_gate.py",
    "figure_annotation_policy.py",
    "figure_visual_semantics.py",
    "figure_visual_critic.py",
    "figure_vision_review.py",
    "data_fig_vision_check.py",
    "figure_decision_planner.py",
    "figure_quality_gate.py",
    "figure_system_controller.py",
    "figure_workspace_bootstrap.py",
)
MARKER = "MODEx FIGURE SYSTEM BOOTSTRAP V2"
CONTRACT = f"""# {MARKER}

这是 Modex 全局图表系统在当前工作区的本地入口。图表任务必须遵循：

1. 先运行 `python tools/figure_system_controller.py --workspace . --stage pre`。
2. 先分析数据形状，再选择图型；数据不足时允许紧凑单图、表格、inset、例外摘要或附录。
3. 复合图只有在 panel 分别提供结果、差异/机制、不确定性或决策证据时才成立。
4. 3D 保留给真实空间、真实时间/第三变量或空间形态本身；平面型 3D 增加投影/离平面残差，不强行制造立体感。
5. 批注必须由阈值、转折、极值、异常、差异、选择或机制锚点触发；使用统一 visual role。
6. 绘图完成后运行 `python tools/figure_system_controller.py --workspace . --stage post`。
7. `FIGURE_SYSTEM_POST.json` 的 BLOCK 必须修正；REVIEW 必须写入 `FIGURE_QA_REPORT.md`，不能把跳过的视觉检查写成 PASS。

工具已从 Modex 安装目录同步到当前工作区 `tools/`，仅作为可重跑入口；数据和结果仍必须来自当前工作区的真实源文件。
"""


def bootstrap(
    workspace: Path,
    source_tools: Path | None = None,
    materialize: bool = False,
) -> dict:
    workspace = workspace.resolve()
    source_tools = (source_tools or Path(__file__).resolve().parent).resolve()
    copied = []
    skipped = []
    missing = []
    if materialize:
        target = workspace / "tools"
        target.mkdir(parents=True, exist_ok=True)
    for name in TOOL_NAMES:
        src = source_tools / name
        if not src.is_file():
            missing.append(name)
            continue
        if not materialize:
            skipped.append({"name": name, "reason": "global_resource"})
            continue
        dst = workspace / "tools" / name
        if not dst.exists() or src.stat().st_mtime_ns > dst.stat().st_mtime_ns or src.stat().st_size != dst.stat().st_size:
            shutil.copy2(src, dst)
            copied.append(name)
        else:
            skipped.append({"name": name, "reason": "up_to_date"})
    if missing:
        raise FileNotFoundError("global figure resources missing: " + ", ".join(missing))
    tmp = workspace / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    state = {
        "schema": "modex.figure_workspace_bootstrap.v2",
        "marker": MARKER,
        "workspace": str(workspace),
        "source_tools": str(source_tools),
        "materialize": materialize,
        "copied": copied,
        "skipped": skipped,
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    (tmp / "FIGURE_SYSTEM_BOOTSTRAP.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--source-tools")
    ap.add_argument("--materialize", action="store_true", help="explicitly copy global helpers into workspace/tools")
    args = ap.parse_args()
    state = bootstrap(
        Path(args.workspace),
        Path(args.source_tools) if args.source_tools else None,
        materialize=args.materialize,
    )
    print(f"FIGURE_BOOTSTRAP_PASS=true workspace={state['workspace']} copied={len(state['copied'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
