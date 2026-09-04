"""Global figure lifecycle adapter for Modex.

This adapter is intentionally separate from the historical monolithic runner
patch. It wraps only figure-related run_skill calls and therefore composes with
runtime_config_patch and review_repair_patch without changing provider routing,
checkpoints, or ordinary research/writing steps.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

log = logging.getLogger(__name__)
_PATCHED = False
_APP_DIR = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _APP_DIR / "tools"
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_FIGURE_SKILLS = {
    "nature-figure", "paper-figure", "paper-figure-html", "paper-figure-drawio",
    "paper-illustration", "experiment-bridge",
}
_TOOL_HINT_MARKER = "LOCAL TOOL AVAILABILITY v5"
_QUALITY_HEADING_RE = re.compile(
    r"\n## LOCAL FIGURE QUALITY CONTRACT V\d+.*?(?=\n## |\Z)", re.S
)
_TOOL_HINT_RE = re.compile(
    r"\n## LOCAL TOOL AVAILABILITY.*?(?=\n## |\Z)", re.S
)


def _workspace(root: Union[str, Path]) -> Path:
    return Path(root).resolve()


def _figure_master() -> str:
    """Load the compact global visual master for direct runner delivery."""
    path = _PROMPT_DIR / "local_figure_quality_overlay.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _is_workspace(root: Union[str, Path]) -> bool:
    path = _workspace(root)
    return path.is_dir() and (path / "CLAUDE.md").is_file()


def _refresh_workspace_claude(root: Path) -> None:
    """Refresh only global figure sections; preserve all user/project text."""
    md = root / "CLAUDE.md"
    quality = _PROMPT_DIR / "local_figure_quality_overlay.md"
    if not md.is_file() or not quality.is_file():
        return
    try:
        text = md.read_text(encoding="utf-8", errors="ignore")
        text = _TOOL_HINT_RE.sub("", text).rstrip()
        text = _QUALITY_HEADING_RE.sub("", text).rstrip()
        hints = (
            f"\n## {_TOOL_HINT_MARKER} (reference only, not a rule)\n"
            "当前工作区已同步 Modex 图表系统：\n"
            "1. `tools/figure_system_controller.py`：图表 pre/post 生命周期检查。\n"
            "2. `tools/figure_decision_planner.py`：逐图图型、证据层、批注预算和降级决策。\n"
            "3. `tools/figure_data_shape_profile.py`：近常量、重复、饱和、相似 panel 和 3D 形状分析。\n"
            "4. `tools/figure_annotation_policy.py` + `tools/figure_visual_semantics.py`：证据触发式批注与统一特殊点/线语义。\n"
            "5. 复合图只在 panel 提供互补证据时使用；3D 保留真实空间/时间/第三变量语义，平面型 3D 增加投影或残差。\n"
            "6. 视觉检查未完成时保留 REVIEW；代理结果、占位结果和不可追溯数值不得发布。\n"
        )
        quality_text = quality.read_text(encoding="utf-8").strip()
        updated = text + hints + "\n\n" + quality_text + "\n"
        if updated != md.read_text(encoding="utf-8", errors="ignore"):
            md.write_text(updated, encoding="utf-8")
    except Exception as exc:
        log.warning("[figure-lifecycle] workspace contract refresh failed: %s", exc)


def _run_tool(command: list[str], root: Path, timeout: int = 300) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command, cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-4000:],
        }
    except Exception as exc:
        return {"returncode": 1, "error": str(exc)}


def _bootstrap(root: Path) -> dict[str, Any]:
    """Validate global figure resources without writing into the workspace.

    Workspace-local tools and CLAUDE.md are project artifacts. The global
    lifecycle must supply its rules through the runner prompt and keep reports
    under _tmp; silently copying tools or rewriting project instructions made
    reruns look like unrelated project edits.
    """
    required = (
        "figure_system_controller.py",
        "figure_quality_gate.py",
        "figure_data_shape_profile.py",
        "figure_visual_critic.py",
        "figure_render_qa.py",
    )
    missing = [name for name in required if not (_TOOLS_DIR / name).is_file()]
    if missing:
        return {"returncode": 1, "error": "global figure resources missing: " + ", ".join(missing)}
    return {"returncode": 0, "workspace": str(root), "mode": "global-resources-no-workspace-write"}


def _sync_png_previews(root: Path) -> dict[str, Any]:
    """Create canonical high-DPI PNG previews beside every figure PDF."""
    result: dict[str, Any] = {"created": [], "failed": []}
    figdir = root / "figures"
    if not figdir.is_dir():
        return result
    try:
        import fitz  # PyMuPDF is bundled with Modex
    except Exception as exc:
        return {"created": [], "failed": [f"PyMuPDF unavailable: {exc}"]}
    # Include quantitative figures and HTML-produced flow/architecture/
    # mechanism PDFs. The prefix is intentionally shared so every formal
    # figure has the same PDF+PNG contract, regardless of rendering engine.
    for pdf in sorted(figdir.glob("fig_*.pdf")):
        png = pdf.with_suffix(".png")
        try:
            if png.exists() and png.stat().st_mtime_ns >= pdf.stat().st_mtime_ns:
                continue
            document = fitz.open(str(pdf))
            if not document:
                result["failed"].append(f"{pdf.name}: empty PDF")
                continue
            page = document[0]
            # 350 dpi matches the existing Word/PNG quality contract.
            scale = 350.0 / 72.0
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pixmap.save(str(png))
            document.close()
            result["created"].append(png.name)
        except Exception as exc:
            result["failed"].append(f"{pdf.name}: {exc}")
    return result


def _normalize_nested_outputs(root: Path) -> dict[str, Any]:
    """Recover outputs written as figures/figures by a script run from figures/."""
    nested = root / "figures" / "figures"
    result: dict[str, Any] = {"moved": [], "duplicates": [], "conflicts": []}
    if not nested.is_dir():
        return result
    destination_root = root / "figures"
    for source in sorted(nested.iterdir()):
        if not source.is_file():
            continue
        destination = destination_root / source.name
        try:
            if not destination.exists():
                source.replace(destination)
                result["moved"].append(source.name)
            elif destination.read_bytes() == source.read_bytes():
                source.unlink()
                result["duplicates"].append(source.name)
            else:
                result["conflicts"].append(source.name)
        except OSError as exc:
            result["conflicts"].append(f"{source.name}: {exc}")
    try:
        if nested.is_dir() and not any(nested.iterdir()):
            nested.rmdir()
    except OSError:
        pass
    return result


def _controller(root: Path, stage: str) -> dict[str, Any]:
    tool = _TOOLS_DIR / "figure_system_controller.py"
    output = root / "_tmp" / f"FIGURE_SYSTEM_{stage.upper()}.json"
    if not tool.is_file():
        return {"returncode": 1, "error": "figure_system_controller.py missing", "output": str(output)}
    return _run_tool(
        [sys.executable, str(tool), "--workspace", str(root), "--stage", stage, "--output", str(output)],
        root,
        timeout=360,
    ) | {"output": str(output)}


def _regression(
    root: Path,
    stage: str,
    baseline: Optional[Path] = None,
    output: Optional[Path] = None,
) -> dict[str, Any]:
    """Run visual-continuity checks without modifying project deliverables."""
    tool = _TOOLS_DIR / "figure_regression_guard.py"
    output = output or root / "_tmp" / f"FIGURE_REGRESSION_{stage.upper()}.json"
    if not tool.is_file():
        return {"returncode": 1, "error": "figure_regression_guard.py missing", "output": str(output)}
    command = [sys.executable, str(tool), "--workspace", str(root), "--stage", stage, "--output", str(output)]
    if baseline is not None:
        command.extend(["--baseline", str(baseline)])
    return _run_tool(command, root, timeout=180) | {"output": str(output)}


def _render_qa(root: Path) -> dict[str, Any]:
    tool = _TOOLS_DIR / "figure_render_qa.py"
    output = root / "_tmp" / "FIGURE_RENDER_QA.json"
    if not tool.is_file():
        return {"returncode": 1, "error": "figure_render_qa.py missing", "output": str(output)}
    return _run_tool(
        [sys.executable, str(tool), "--workspace", str(root), "--output", str(output)],
        root,
        timeout=240,
    ) | {"output": str(output)}


def _read_report(root: Path, name: str) -> dict[str, Any]:
    path = root / "_tmp" / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_rework_feedback(root: Path, skill: str, report: dict[str, Any]) -> None:
    reviews = list(report.get("reviews") or [])
    if not reviews:
        return
    path = root / "_tmp" / "FIGURE_REWORK_FEEDBACK.md"
    lines = [
        "# 图表视觉重构反馈",
        f"target_skill={skill}",
        "下次重跑该图表步骤时，先处理以下反馈；不要用新增文字掩盖结构问题：",
        "",
    ]
    for item in reviews[:30]:
        if isinstance(item, dict):
            figure = item.get("figure", "")
            kind = item.get("type", "review")
            action = item.get("action", "")
            evidence = item.get("evidence", "")
            lines.append(f"- [{figure}] {kind}: {action}")
            if evidence:
                lines.append(f"  证据：{str(evidence)[:600]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _remove_rework_feedback(root: Path, skill: str) -> None:
    path = root / "_tmp" / "FIGURE_REWORK_FEEDBACK.md"
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if f"target_skill={skill}" in text:
            path.unlink()
    except Exception:
        pass


def _read_feedback(root: Path, skill: str) -> str:
    path = root / "_tmp" / "FIGURE_REWORK_FEEDBACK.md"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text[:8000] if f"target_skill={skill}" in text else ""
    except Exception:
        return ""


def _vision_enabled(root: Path) -> bool:
    md = root / "CLAUDE.md"
    try:
        return "MH_DATA_FIG_VISION=1" in md.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False


def _run_optional_vision(root: Path) -> dict[str, Any]:
    tool = _TOOLS_DIR / "figure_vision_review.py"
    output = root / "_tmp" / "FIGURE_VISION_REVIEW.json"
    if not tool.is_file():
        return {"returncode": 1, "error": "figure_vision_review.py missing"}
    return _run_tool(
        [sys.executable, str(tool), "--workspace", str(root), "--enable-network", "--output", str(output)],
        root,
        timeout=360,
    ) | {"output": str(output)}


async def _run_async(function: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, function, *args)


def _result_error(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("ok") is False or result.get("success") is False:
        return True
    status = str(result.get("status") or "").lower()
    return status in {"failed", "error", "blocked"}


def install() -> bool:
    global _PATCHED
    if _PATCHED:
        return True
    try:
        from services import claude_runner as runner
    except Exception as exc:
        log.warning("[figure-lifecycle] import failed: %s", exc)
        return False

    original_run_skill = runner.claude_runner.run_skill

    async def patched_run_skill(
        skill_name: str,
        arguments: str,
        cwd: Union[str, Path],
        workflow_id: str,
        on_output: Optional[Callable[[str], Awaitable[None]]] = None,
        extra_params: Optional[dict[str, Any]] = None,
        workspace_files: Optional[list[str]] = None,
        context_summary: Optional[str] = None,
        inactivity_timeout: int = 5400,
        resume_session_id: Optional[str] = None,
        step_model: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        if skill_name not in _FIGURE_SKILLS or not _is_workspace(cwd):
            return await original_run_skill(
                skill_name, arguments, cwd, workflow_id, on_output=on_output,
                extra_params=extra_params, workspace_files=workspace_files,
                context_summary=context_summary, inactivity_timeout=inactivity_timeout,
                resume_session_id=resume_session_id, step_model=step_model,
            )

        root = _workspace(cwd)
        feedback = _read_feedback(root, skill_name)
        if feedback:
            arguments = (arguments or "").rstrip() + "\n\n" + feedback
        master = _figure_master()
        if master and "MODEX GLOBAL FIGURE MASTER V3" not in (arguments or ""):
            arguments = (arguments or "").rstrip() + "\n\n" + master + "\n"
        bootstrap_result = await _run_async(_bootstrap, root)
        # Normalize legacy figures/figures outputs before the preflight. This
        # keeps historical path mistakes from poisoning every later rerun.
        normalized_pre = await _run_async(_normalize_nested_outputs, root)
        if normalized_pre.get("conflicts"):
            log.error("[figure-lifecycle] preflight nested output conflicts workspace=%s conflicts=%s", root, normalized_pre["conflicts"])
            raise RuntimeError("图表输出路径冲突：请读取 figures/ 下的同名文件并手动处理")
        baseline_path = root / "_tmp" / "FIGURE_REGRESSION_BASELINE.json"
        regression_pre = await _run_async(_regression, root, "snapshot", None, baseline_path)
        pre_result = await _run_async(_controller, root, "pre")
        log.info("[figure-lifecycle] preflight skill=%s workspace=%s rc=%s", skill_name, root, pre_result.get("returncode"))
        try:
            result = await original_run_skill(
                skill_name, arguments, cwd, workflow_id, on_output=on_output,
                extra_params=extra_params, workspace_files=workspace_files,
                context_summary=context_summary, inactivity_timeout=inactivity_timeout,
                resume_session_id=resume_session_id, step_model=step_model,
            )
        except Exception:
            raise
        if _result_error(result):
            return result

        normalized = await _run_async(_normalize_nested_outputs, root)
        if normalized.get("conflicts"):
            log.error("[figure-lifecycle] nested output conflicts workspace=%s conflicts=%s", root, normalized["conflicts"])
            raise RuntimeError("图表输出路径冲突：请读取 figures/ 下的同名文件并手动处理")
        if normalized.get("moved") or normalized.get("duplicates"):
            log.warning("[figure-lifecycle] normalized nested outputs workspace=%s moved=%s duplicates=%s", root, normalized.get("moved"), normalized.get("duplicates"))
        png_sync = await _run_async(_sync_png_previews, root)
        if png_sync.get("failed"):
            log.warning("[figure-lifecycle] PNG preview sync failures workspace=%s failed=%s", root, png_sync["failed"])
        if png_sync.get("created"):
            log.info("[figure-lifecycle] PNG previews created workspace=%s files=%s", root, png_sync["created"])

        # The controller owns rendered-image QA so the report has one source of
        # truth; do not run the render checker a second time here.
        post_result = await _run_async(_controller, root, "post")
        post_report = _read_report(root, "FIGURE_SYSTEM_POST.json")
        regression_result = await _run_async(_regression, root, "compare", baseline_path)
        regression_report = _read_report(root, "FIGURE_REGRESSION_COMPARE.json")
        regression_verdict = str(regression_report.get("verdict") or "").upper()
        if regression_verdict == "BLOCK":
            post_report = dict(post_report)
            post_report.setdefault("blocks", []).extend(regression_report.get("blocks") or [])
            post_report["verdict"] = "BLOCK"
        elif regression_verdict == "REVIEW":
            post_report = dict(post_report)
            post_report.setdefault("reviews", []).extend(regression_report.get("reviews") or [])
            if str(post_report.get("verdict") or "").upper() == "PASS":
                post_report["verdict"] = "REVIEW"
        try:
            (root / "_tmp" / "FIGURE_SYSTEM_POST.json").write_text(
                json.dumps(post_report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
        vision_report: dict[str, Any] = {}
        if _vision_enabled(root):
            vision_result = await _run_async(_run_optional_vision, root)
            vision_report = _read_report(root, "FIGURE_VISION_REVIEW.json")
            if vision_report.get("verdict") in {"REVIEW", "SKIP", "SKIPPED"}:
                log.warning("[figure-lifecycle] vision review=%s workspace=%s", vision_report.get("verdict"), root)
            elif vision_result.get("returncode"):
                log.warning("[figure-lifecycle] vision command failed workspace=%s", root)
        # A successful deterministic postflight may still require human/model
        # review when the optional visual model is unavailable or returns REVIEW.
        if vision_report and str(vision_report.get("verdict") or "").upper() == "REVIEW":
            post_report = dict(post_report)
            post_report.setdefault("reviews", []).append({
                "type": "multimodal_vision_review", "severity": "review",
                "action": "resolve visual-model review before declaring figures final",
                "evidence": vision_report.get("reason", "vision review returned REVIEW"),
            })
            post_report["verdict"] = "REVIEW" if str(post_report.get("verdict") or "").upper() == "PASS" else post_report.get("verdict")
            try:
                (root / "_tmp" / "FIGURE_SYSTEM_POST.json").write_text(
                    json.dumps(post_report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass
        verdict = str(post_report.get("verdict") or "").upper()
        if verdict == "BLOCK":
            log.error("[figure-lifecycle] BLOCK skill=%s workspace=%s", skill_name, root)
            raise RuntimeError("图表生命周期检查 BLOCK：请读取 _tmp/FIGURE_SYSTEM_POST.json 修正后重跑")
        if verdict == "REVIEW":
            _write_rework_feedback(root, skill_name, post_report)
            log.warning("[figure-lifecycle] REVIEW skill=%s workspace=%s", skill_name, root)
        else:
            _remove_rework_feedback(root, skill_name)
        # Preserve the official runner result while making the figure gate
        # state visible to the workflow/UI caller. REVIEW is not silently
        # converted into a completed figure claim.
        if isinstance(result, dict):
            result = dict(result)
            result["figure_postflight_verdict"] = verdict or "UNKNOWN"
            result["figure_postflight_report"] = str(root / "_tmp" / "FIGURE_SYSTEM_POST.json")
            result["figure_render_qa_report"] = str(root / "_tmp" / "FIGURE_RENDER_QA.json")
            result["figure_number_consistency_report"] = str(root / "_tmp" / "FIGURE_NUMBER_CONSISTENCY_GATE.json")
            if verdict == "REVIEW":
                result["status"] = "review"
        return result

    setattr(patched_run_skill, "_figure_lifecycle_original", original_run_skill)
    runner.claude_runner.run_skill = patched_run_skill
    _PATCHED = True
    log.info("[figure-lifecycle] installed for %s", sorted(_FIGURE_SKILLS))
    return True
