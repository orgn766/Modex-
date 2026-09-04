"""Review-driven incremental repair for competition workflows.

The packaged workflow engine remains the scheduler. This adapter wraps the
Claude skill runner only after a completed competition review. A review with
findings is handled before the official engine receives the review result:

    review -> analysis document -> modeling document -> code/data -> data figures -> paper

The adapter never invokes the full paper-figure skill and never invokes a GPT
image tool. It runs only existing gen_fig_*.py scripts whose explicit JSON
input dependency changed. Each phase has a file-change contract and a durable
state record. Any violation or failed command blocks the workflow.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

log = logging.getLogger(__name__)
DB_PATH = Path.home() / "AppData" / "Roaming" / "MHAgent" / "db" / "aris.db"
RUNTIME_PYTHON = Path(
    os.environ.get(
        "MH_PYTHON",
        str(Path(__file__).resolve().parents[4] / "runtime" / "python" / "python.exe"),
    )
)

PATCHED = False
ORIGINAL_RUN_SKILL: Any = None
ORIGINAL_RUN_WORKFLOW: Any = None
ACTIVE: dict[str, asyncio.Task] = {}
ACTIVE_WORKFLOWS: set[str] = set()
RECENT_BLOCKS: dict[str, float] = {}
BLOCK_RETRY_WINDOW_SEC = 30.0
REVIEW_STEPS = {"comp-review", "comp-review-en"}
REPAIR_PHASES = {
    "analysis": "comp-prob-analysis",
    "modeling": "comp-modeling",
    "code": "comp-code",
    "figures": "affected-figure-data",
}
TRANSIENT_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".aux", ".out", ".toc", ".lof", ".lot",
    ".fls", ".fdb_latexmk", ".synctex", ".synctex.gz",
}
GPT_TOKENS = (
    "gpt_image", "gpt-image", "gptimg", "gptimage",
    "image_generation", "image-generation",
)
FIGURE_EXTENSIONS = (".pdf", ".png", ".svg", ".jpg", ".jpeg", ".html")
# Official Claude runner / workflow engine rewrite these on every skill spawn.
# They are not user repair targets and must not fail a file-change contract.
RUNTIME_ROOT_FILES = {
    "CLAUDE.md",
    ".env_skill",
    "_review_prompt.txt",
    "_gpt_image_config.json",
    "_user_palette_snapshot.json",
}
RUNTIME_ROOT_PREFIXES = (
    "CAPABILITY_",
    "AUDIT_",
    "SEMANTIC_REVIEW",
    "DELIVERABLES",
    "DATA_PROFILE",
    "DATA_FACTS",
    "PROBLEM_FACTS",
    "FIGURE_QA",
    "FIGURE_HTML",
    "FIGURE_CONTRACT",
    "PAPER_DATA_CHECK",
)


class DBContext:
    """A close-on-exit SQLite context; Windows keeps file handles strictly."""

    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(str(path), timeout=15)

    def __enter__(self) -> sqlite3.Connection:
        return self.connection

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()


def db_connect() -> DBContext:
    return DBContext(DB_PATH)


def canonical_workflow_id(value: str) -> str:
    """Map runner task IDs such as wf_comp-review back to the DB workflow ID."""
    candidate = str(value or "")
    if not candidate:
        return candidate
    try:
        with db_connect() as conn:
            if conn.execute("SELECT 1 FROM workflows WHERE id=?", (candidate,)).fetchone():
                return candidate
            suffixes = sorted(
                {"_" + name for name in REVIEW_STEPS | set(REPAIR_PHASES.values())},
                key=len,
                reverse=True,
            )
            for suffix in suffixes:
                if candidate.endswith(suffix):
                    base = candidate[: -len(suffix)]
                    if conn.execute("SELECT 1 FROM workflows WHERE id=?", (base,)).fetchone():
                        return base
    except Exception as exc:
        log.warning("[review-repair] workflow ID lookup failed: %s", exc)
    return candidate


def workspace_for(workflow_id: str, fallback: Any) -> Path:
    workflow_id = canonical_workflow_id(workflow_id)
    try:
        with db_connect() as conn:
            row = conn.execute(
                "SELECT workspace_dir FROM workflows WHERE id=?", (workflow_id,)
            ).fetchone()
        if row and row[0]:
            return Path(str(row[0])).resolve()
    except Exception as exc:
        log.warning("[review-repair] workspace lookup failed: %s", exc)
    return Path(str(fallback)).resolve()


def log_event(workflow_id: str, level: str, message: str) -> None:
    try:
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO workflow_logs(workflow_id,step_name,level,message) VALUES(?,?,?,?)",
                (canonical_workflow_id(workflow_id), "review-repair", level, message[:4000]),
            )
    except Exception as exc:
        log.warning("[review-repair] event log failed: %s", exc)


def set_workflow(
    workflow_id: str,
    status: Optional[str] = None,
    current_step: Optional[str] = None,
) -> None:
    workflow_id = canonical_workflow_id(workflow_id)
    fields: list[str] = []
    values: list[Any] = []
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if current_step is not None:
        fields.append("current_step=?")
        values.append(current_step)
    if not fields:
        return
    fields.append("updated_at=datetime('now')")
    values.append(workflow_id)
    with db_connect() as conn:
        cur = conn.execute(
            f"UPDATE workflows SET {','.join(fields)} WHERE id=?", values
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"workflow not found: {workflow_id}")


def set_step(
    workflow_id: str,
    skill_name: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    workflow_id = canonical_workflow_id(workflow_id)
    if status == "running":
        sql = (
            "UPDATE workflow_steps SET status='running',"
            "started_at=COALESCE(started_at,datetime('now')),"
            "completed_at=NULL,error_message=NULL "
            "WHERE workflow_id=? AND skill_name=?"
        )
        params = (workflow_id, skill_name)
    elif status == "completed":
        sql = (
            "UPDATE workflow_steps SET status='completed',"
            "completed_at=datetime('now'),error_message=NULL "
            "WHERE workflow_id=? AND skill_name=?"
        )
        params = (workflow_id, skill_name)
    elif status == "failed":
        sql = (
            "UPDATE workflow_steps SET status='failed',"
            "completed_at=datetime('now'),error_message=? "
            "WHERE workflow_id=? AND skill_name=?"
        )
        params = (error or "review repair failed", workflow_id, skill_name)
    else:
        raise ValueError(f"unsupported step status: {status}")
    with db_connect() as conn:
        cur = conn.execute(sql, params)
        if cur.rowcount != 1:
            # Some imported/legacy workflows retain only the review and paper
            # rows. Internal repair phases still have durable JSON state, while
            # the review and paper rows remain mandatory for scheduler safety.
            if skill_name in {"comp-prob-analysis", "comp-modeling", "comp-code"}:
                log.warning("[review-repair] internal step row absent: %s/%s", workflow_id, skill_name)
                return
            raise RuntimeError(f"workflow step not found: {workflow_id}/{skill_name}")


def next_paper_step(workflow_id: str) -> Optional[str]:
    workflow_id = canonical_workflow_id(workflow_id)
    with db_connect() as conn:
        row = conn.execute(
            "SELECT s2.skill_name FROM workflow_steps s1 "
            "JOIN workflow_steps s2 ON s2.workflow_id=s1.workflow_id "
            "WHERE s1.workflow_id=? AND s1.skill_name IN ('comp-review','comp-review-en') "
            "AND s2.step_order>s1.step_order "
            "AND s2.skill_name LIKE 'comp-paper%' "
            "AND s2.status IN ('pending','running') "
            "ORDER BY s2.step_order LIMIT 1",
            (workflow_id,),
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def workflow_step_status(workflow_id: str, skill_name: str) -> Optional[str]:
    workflow_id = canonical_workflow_id(workflow_id)
    with db_connect() as conn:
        row = conn.execute(
            "SELECT status FROM workflow_steps WHERE workflow_id=? AND skill_name=?",
            (workflow_id, skill_name),
        ).fetchone()
    return str(row[0]) if row and row[0] else None


def state_path(root: Path, create: bool = True) -> Path:
    path = root / "_tmp" / "REVIEW_REPAIR_STATE.json"
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_state(root: Path) -> dict[str, Any]:
    path = state_path(root, create=False)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def write_state(root: Path, **values: Any) -> None:
    state = read_state(root)
    state.update(values)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = state_path(root)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def backup_path(root: Path, fingerprint: str) -> Path:
    return root.parent / f".{root.name}.review-repair-{fingerprint}.backup"


def ensure_backup(root: Path, fingerprint: str) -> Path:
    """Create a reusable preimage for repair-owned workspace areas."""
    destination = backup_path(root, fingerprint)
    if destination.is_dir():
        return destination
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        shutil.rmtree(temporary, ignore_errors=True)
    shutil.copytree(
        root,
        temporary,
        ignore=shutil.ignore_patterns(".git", "_tmp", "__pycache__", "_utils", "_references", "user_data"),
    )
    os.replace(temporary, destination)
    return destination


def restore_changed(root: Path, backup: Optional[Path], changed: set[str]) -> None:
    """Restore changed files and remove newly-created unauthorized files."""
    if backup is None or not backup.is_dir():
        return
    for rel in sorted(changed):
        source = backup / rel
        target = root / rel
        try:
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            elif target.is_file() or target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
        except OSError as exc:
            log.error("[review-repair] restore failed for %s: %s", rel, exc)


def remove_backup(backup: Optional[Path]) -> None:
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


def restore_incomplete_phase(root: Path, backup: Path, phase: Any) -> None:
    """Reset an interrupted phase to its pre-repair inputs before retrying."""
    phase = str(phase or "")
    if phase in {"", "prepare"}:
        return
    if not backup.is_dir():
        raise RuntimeError(f"repair backup is missing for interrupted phase: {phase}")
    if phase == "comp-prob-analysis":
        relevant = {"PROBLEM_ANALYSIS.md"}
    elif phase == "comp-modeling":
        relevant = {"MODELING_REPORT.md"}
    else:
        current = tree_snapshot(root)
        baseline = tree_snapshot(backup)
        all_names = set(baseline) | set(current)
        if phase == "comp-code":
            relevant = {
                name for name in all_names
                if name.startswith("code/")
                or name == "RESULTS.md"
                or is_result_artifact(name)
                or name.startswith("figures/")
            }
        elif phase == "affected-figure-data":
            relevant = {name for name in all_names if name.startswith("figures/")}
        else:
            return
        restore_changed(root, backup, changed_files(baseline, current) & relevant)
        return
    current = tree_snapshot(root)
    baseline = tree_snapshot(backup)
    restore_changed(root, backup, changed_files(baseline, current) & relevant)


def review_token(root: Path) -> str:
    parts: list[str] = []
    for name in ("COMP_REVIEW.md", "COMP_REVIEW_VERDICT.json"):
        path = root / name
        if not path.is_file():
            parts.append(name + ":missing")
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            parts.append(f"{name}:{digest}")
        except OSError:
            parts.append(name + ":unreadable")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def finding_fingerprint(findings: list[dict[str, Any]]) -> str:
    payload = json.dumps(findings, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def load_plan(root: Path) -> dict[str, Any]:
    path = root / "COMP_REVIEW_VERDICT.json"
    if not path.is_file():
        raise RuntimeError("completed comp-review has no COMP_REVIEW_VERDICT.json")
    try:
        verdict = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"review verdict is not valid JSON: {exc}") from exc
    if not isinstance(verdict, dict):
        raise RuntimeError("review verdict top-level value must be an object")

    raw: Any = verdict.get("findings")
    if raw is None:
        raw = verdict.get("issues")
    if raw is None:
        raw = verdict.get("problems")
    if isinstance(raw, dict):
        flattened: list[Any] = []
        for value in raw.values():
            flattened.extend(value if isinstance(value, list) else [value])
        raw = flattened
    if raw is None:
        raw = []
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise RuntimeError("review findings must be a list of objects")
    findings = list(raw)

    declared = 0
    for key in ("fatal_count", "major_count", "minor_count"):
        value = verdict.get(key)
        if isinstance(value, int) and value > 0:
            declared += value
    if declared > 0 and not findings:
        raise RuntimeError("review declares findings but provides no executable findings")
    if declared and declared != len(findings):
        raise RuntimeError(
            f"review finding count mismatch: declared={declared}, listed={len(findings)}"
        )
    # A blocking review is precisely what this repair path is for. Fatal,
    # major, and minor findings all continue into the same repair sequence.
    gate = str(verdict.get("gate") or "").upper()
    if gate in {"BLOCK", "FAILED", "FAIL", "REJECT"} and not findings:
        raise RuntimeError("review gate blocks paper but provides no executable findings")

    counts: dict[str, int] = {}
    for item in findings:
        severity = str(item.get("severity") or "unspecified").lower()
        counts[severity] = counts.get(severity, 0) + 1
    return {
        "root": root,
        "findings": findings,
        "finding_count": len(findings),
        "has_findings": bool(findings),
        "severity_counts": counts,
        "finding_fingerprint": finding_fingerprint(findings),
        "review_token": review_token(root),
        "verdict_gate": verdict.get("gate"),
    }


def write_instructions(root: Path, plan: dict[str, Any]) -> Path:
    """Write a compact action list; full review evidence stays in verdict JSON."""
    lines = [
        "# Review repair instructions",
        "",
        "处理全部 finding；完整证据在 COMP_REVIEW_VERDICT.json，当前文件只给行动摘要。",
        "顺序：PROBLEM_ANALYSIS.md → MODELING_REPORT.md → code/results → affected data figures → paper。",
        "纸稿不可改；禁止 full paper-figure 与 GPT image。文字不能替代模型/代码修复。",
        "定义问题必须替换唯一主公式；禁止双主结果、实现口径并存或用开脱句关闭 BLOCK。",
        "主账本须与后问上限同边界；SCENARIO 参数须标注并给灵敏度。",
        "",
        "gate=" + str(plan.get("verdict_gate") or "unknown"),
        "findings=" + str(plan["finding_count"]),
        "severity=" + json.dumps(plan["severity_counts"], ensure_ascii=True, sort_keys=True),
        "full_evidence=COMP_REVIEW_VERDICT.json",
        "",
        "## Findings",
    ]
    for index, item in enumerate(plan["findings"], 1):
        evidence = str(item.get("evidence", "")).replace("\n", " ").strip()[:100]
        fix = str(item.get("fix", "")).replace("\n", " ").strip()[:180]
        lines.append(
            f"{index}. [{item.get('severity', '?')}/{item.get('category', 'finding')}] "
            f"where={item.get('where', 'unknown')} | evidence={evidence} | fix={fix}"
        )
    path = root / "_tmp" / "REVIEW_REPAIR_INSTRUCTIONS.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# File contracts
# ---------------------------------------------------------------------------
def relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def ignored_file(rel: str) -> bool:
    parts = set(rel.split("/"))
    if ".git" in parts or "__pycache__" in parts:
        return True
    if rel.startswith(("_utils/", "_references/", "user_data/", "_templates/")):
        return True
    name = Path(rel).name
    if "/" not in rel and (
        name in RUNTIME_ROOT_FILES or name.startswith(RUNTIME_ROOT_PREFIXES)
    ):
        return True
    suffix = Path(rel).suffix.lower()
    return suffix in TRANSIENT_SUFFIXES or rel.endswith(".synctex.gz")


def tree_snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not root.is_dir():
        return result
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = relative(path, root)
        if ignored_file(rel) or rel.startswith("_tmp/"):
            continue
        try:
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return result


def changed_files(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {name for name in set(before) | set(after) if before.get(name) != after.get(name)}


def is_result_artifact(rel: str) -> bool:
    path = Path(rel)
    if path.suffix.lower() != ".json":
        return False
    if rel.startswith("results/"):
        return True
    return rel.startswith("figures/") and (
        path.name == "all_results.json" or path.name.endswith("_results.json")
    )


def result_snapshot(root: Path) -> dict[str, str]:
    return {
        name: digest
        for name, digest in tree_snapshot(root).items()
        if is_result_artifact(name)
    }


def validate_json_files(root: Path, names: set[str]) -> None:
    for rel in sorted(names):
        if not is_result_artifact(rel):
            continue
        path = root / rel
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"result JSON missing or empty: {rel}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"result JSON invalid: {rel}: {exc}") from exc
        if not isinstance(value, (dict, list)):
            raise RuntimeError(f"result JSON top-level type invalid: {rel}")


def validate_result_mirrors(root: Path, changed: set[str]) -> None:
    """Check changed results/ files against their optional figure mirrors."""
    for rel in sorted(changed):
        if not rel.startswith("results/") or not rel.endswith(".json"):
            continue
        mirror = f"figures/{Path(rel).name}"
        source = root / rel
        target = root / mirror
        if not target.exists():
            continue
        if not target.is_file() or source.read_bytes() != target.read_bytes():
            raise RuntimeError(f"result mirror mismatch: {rel} vs {mirror}")


def validate_all_result_mirrors(root: Path) -> None:
    """Reject stale figure result mirrors even when only the mirror was edited."""
    results_dir = root / "results"
    if not results_dir.is_dir():
        return
    for source in sorted(results_dir.glob("*.json")):
        mirror = root / "figures" / source.name
        if mirror.is_file() and source.read_bytes() != mirror.read_bytes():
            raise RuntimeError(
                f"result mirror mismatch: results/{source.name} vs figures/{source.name}"
            )


def check_stage(
    before: dict[str, str],
    after: dict[str, str],
    allowed: set[str],
    stage: str,
    root: Optional[Path] = None,
    backup: Optional[Path] = None,
) -> set[str]:
    changed = changed_files(before, after)
    unexpected = sorted(changed - allowed)
    if unexpected:
        restore_changed(root, backup, changed)
        raise RuntimeError(f"{stage} changed files outside contract: {', '.join(unexpected[:30])}")
    return changed


async def run_direct_checked(
    original_run_skill: Callable[..., Awaitable[Any]],
    workflow_engine: Any,
    workflow_id: str,
    root: Path,
    skill_name: str,
    instruction: str,
    workspace_files: list[str],
    backup: Optional[Path],
) -> tuple[dict[str, str], dict[str, str]]:
    before = tree_snapshot(root)
    try:
        await run_direct_skill(
            original_run_skill, workflow_engine, workflow_id, root,
            skill_name, instruction, workspace_files,
        )
    except Exception:
        restore_changed(root, backup, changed_files(before, tree_snapshot(root)))
        raise
    return before, tree_snapshot(root)


def require_changed(changed: set[str], target: str, stage: str) -> None:
    if target not in changed:
        raise RuntimeError(f"{stage} did not change required file: {target}")


def missing_or_small(root: Path, sizes: dict[str, int]) -> list[str]:
    return [
        name for name, minimum in sorted(sizes.items())
        if not (root / name).is_file() or (root / name).stat().st_size < minimum
    ]


def script_dependencies(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    dependencies: set[str] = set()
    try:
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
            else:
                function_name = ""
            if function_name not in {"load_json", "read_result", "load_result"}:
                continue
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                dependencies.add(Path(argument.value).name)
    except SyntaxError:
        return set()
    for match in re.finditer(r"(?:results[/\\])([A-Za-z0-9_.-]+\.json)", text):
        dependencies.add(match.group(1))
    return dependencies


def forbidden_figure(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        text = ""
    haystack = path.name.lower() + " " + text
    return any(token in haystack for token in GPT_TOKENS)


def figure_candidates(root: Path, changed_results: set[str]) -> list[Path]:
    basenames = {Path(name).name for name in changed_results}
    directory = root / "figures"
    if not directory.is_dir():
        return []
    selected: list[Path] = []
    for path in sorted(directory.glob("gen_fig_*.py")):
        if forbidden_figure(path):
            continue
        if script_dependencies(path) & basenames:
            selected.append(path)
    return selected


def figure_expected_outputs(root: Path, scripts: list[Path]) -> set[str]:
    outputs: set[str] = set()
    for script in scripts:
        suffix = script.stem[len("gen_fig_") :]
        if suffix:
            outputs.update(f"figures/fig_{suffix}{ext}" for ext in FIGURE_EXTENSIONS)
    return outputs


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------
def result_ok(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("is_error") is True:
        return False
    if value.get("ok") is False or value.get("success") is False:
        return False
    status = str(value.get("status") or "").lower()
    if status in {"error", "failed", "failure", "cancelled", "canceled"}:
        return False
    code = None
    for key in ("return_code", "returncode", "exit_code"):
        if value.get(key) is not None:
            code = value.get(key)
            break
    return code in (None, 0)


async def step_model(workflow_engine: Any, workflow_id: str, skill_name: str) -> Any:
    try:
        with db_connect() as conn:
            row = conn.execute("SELECT params FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        params = json.loads(row[0] or "{}") if row and row[0] else {}
        resolver = getattr(workflow_engine, "_resolve_step_model", None)
        if resolver is None:
            return None
        value = resolver(params, skill_name)
        return await value if inspect.isawaitable(value) else value
    except Exception as exc:
        log.warning("[review-repair] model lookup failed: %s", exc)
        return None


async def run_direct_skill(
    original_run_skill: Callable[..., Awaitable[Any]],
    workflow_engine: Any,
    workflow_id: str,
    root: Path,
    skill_name: str,
    instruction: str,
    workspace_files: list[str],
) -> dict[str, Any]:
    task_id = f"{workflow_id}__review_repair_{skill_name}"
    context = (root / "_tmp" / "REVIEW_REPAIR_INSTRUCTIONS.md").read_text(encoding="utf-8")
    result = await original_run_skill(
        skill_name,
        instruction,
        root,
        task_id,
        on_output=None,
        extra_params=None,
        workspace_files=workspace_files,
        context_summary=context,
        inactivity_timeout=5400,
        resume_session_id=None,
        step_model=await step_model(workflow_engine, workflow_id, skill_name),
    )
    if not result_ok(result):
        raise RuntimeError(f"{skill_name} returned failure: {str(result)[:1000]}")
    return result


async def run_modeling_gate(root: Path, script_name: str, output_name: str) -> None:
    script = Path(__file__).resolve().parents[2] / "tools" / script_name
    output = root / "_tmp" / output_name
    if not script.is_file():
        raise RuntimeError(script_name + " is missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    python = RUNTIME_PYTHON if RUNTIME_PYTHON.is_file() else Path(sys.executable)
    process = await asyncio.create_subprocess_exec(
        str(python),
        str(script),
        "--workspace",
        str(root),
        "--output",
        str(output),
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        blob, _ = await asyncio.wait_for(process.communicate(), timeout=120)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError(script_name + " timed out") from exc
    text = blob.decode("utf-8", errors="replace")
    if process.returncode == 1:
        raise RuntimeError(
            "modeling gate BLOCK after repair (" + script_name + "): " + text[-2000:]
        )


async def execute_code(root: Path) -> str:
    entrypoint = root / "code" / "main.py"
    if not entrypoint.is_file() or entrypoint.stat().st_size == 0:
        raise RuntimeError("code/main.py is missing after comp-code")
    if not RUNTIME_PYTHON.is_file():
        raise RuntimeError(f"bundled Python does not exist: {RUNTIME_PYTHON}")
    process = await asyncio.create_subprocess_exec(
        str(RUNTIME_PYTHON),
        str(entrypoint),
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=1800)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError("code/main.py timed out") from exc
    text = output.decode("utf-8", errors="replace")
    if process.returncode != 0:
        raise RuntimeError(f"code/main.py failed rc={process.returncode}: {text[-2500:]}")
    return text[-2500:]


async def run_affected_figures(
    root: Path,
    changed_results: set[str],
    backup: Optional[Path] = None,
) -> dict[str, Any]:
    scripts = figure_candidates(root, changed_results)
    report: dict[str, Any] = {
        "changed_inputs": sorted(changed_results),
        "scripts": [],
        "full_paper_figure_called": False,
        "gpt_image_called": False,
    }
    report_path = root / "_tmp" / "FIGURE_DATA_PATCH_REPORT.json"
    if not scripts:
        report["script_count"] = 0
        report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
        return report
    if not RUNTIME_PYTHON.is_file():
        raise RuntimeError(f"bundled Python does not exist: {RUNTIME_PYTHON}")

    before = tree_snapshot(root)
    expected = figure_expected_outputs(root, scripts)
    for script in scripts:
        suffix = script.stem[len("gen_fig_") :]
        expected_for_script = {
            name for name in expected if name.startswith(f"figures/fig_{suffix}")
        }
        item: dict[str, Any] = {
            "script": relative(script, root),
            "expected_outputs": sorted(expected_for_script),
        }
        try:
            process = await asyncio.create_subprocess_exec(
                str(RUNTIME_PYTHON),
                str(script),
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output, _ = await asyncio.wait_for(process.communicate(), timeout=900)
        except asyncio.TimeoutError as exc:
            item["return_code"] = "timeout"
            item["output_tail"] = ""
            report["scripts"].append(item)
            report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
            restore_changed(root, backup, changed_files(before, tree_snapshot(root)))
            raise RuntimeError(f"figure script timed out: {script.name}") from exc
        item["return_code"] = process.returncode
        item["output_tail"] = output.decode("utf-8", errors="replace")[-1800:]
        report["scripts"].append(item)
        if process.returncode != 0:
            report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
            restore_changed(root, backup, changed_files(before, tree_snapshot(root)))
            raise RuntimeError(f"figure script failed: {script.name}: {item['output_tail']}")

    after = tree_snapshot(root)
    allowed = expected | {"_tmp/FIGURE_DATA_PATCH_REPORT.json", "_tmp/REVIEW_REPAIR_STATE.json"}
    changed = check_stage(
        before,
        after,
        allowed,
        "affected-figure-data",
        root=root,
        backup=backup,
    )
    for item in report["scripts"]:
        outputs = set(item["expected_outputs"])
        existing = sorted(name for name in outputs if (root / name).is_file())
        if not existing:
            restore_changed(root, backup, changed)
            raise RuntimeError(f"figure script produced no expected output: {item['script']}")
        # A successful rerun may legitimately produce byte-identical output
        # when the changed result field is not visually used by this script.
        # Execution and existence are the freshness evidence; byte difference
        # is not required.
        item["existing_outputs"] = existing
        item["changed_outputs"] = sorted(outputs & changed)
    report["script_count"] = len(scripts)
    report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# Durable repair state machine
# ---------------------------------------------------------------------------
def phase_complete(state: dict[str, Any], phase: str) -> bool:
    return phase in set(state.get("completed_phases") or [])


def mark_phase(root: Path, phase: str, **values: Any) -> None:
    state = read_state(root)
    completed = set(state.get("completed_phases") or [])
    completed.add(phase)
    values.update({"phase": phase, "completed_phases": sorted(completed)})
    write_state(root, **values)


async def repair_once(
    original_run_skill: Callable[..., Awaitable[Any]],
    workflow_engine: Any,
    workflow_id: str,
    root: Path,
    plan: dict[str, Any],
) -> None:
    instructions = write_instructions(root, plan)
    backup = ensure_backup(root, plan["review_token"])
    prior = read_state(root)
    same_run = prior.get("review_token") == plan["review_token"]
    if same_run and prior.get("repair_status") == "running":
        # A process may die after a model writes a phase but before the phase
        # is marked complete. Restore only that phase from the durable backup,
        # then retry it; completed earlier phases remain intact.
        restore_incomplete_phase(root, backup, prior.get("phase"))
    if not same_run or prior.get("repair_status") not in {"running", "blocked"}:
        write_state(
            root,
            repair_status="running",
            phase="prepare",
            completed_phases=[],
            mode="analysis_model_code_then_figure_data",
            finding_fingerprint=plan["finding_fingerprint"],
            review_token=plan["review_token"],
            finding_count=plan["finding_count"],
            severity_counts=plan["severity_counts"],
            sequence=[
                "comp-prob-analysis", "comp-modeling", "comp-code",
                "affected-figure-data", "comp-paper-zh",
            ],
            instruction_file=relative(instructions, root),
            backup_dir=str(backup),
        )
    else:
        write_state(root, repair_status="running", instruction_file=relative(instructions, root), backup_dir=str(backup))
    log_event(workflow_id, "info", f"repair started findings={plan['finding_count']} fp={plan['finding_fingerprint']}")

    if not phase_complete(read_state(root), "analysis"):
        set_workflow(workflow_id, "running", "comp-prob-analysis")
        set_step(workflow_id, "comp-prob-analysis", "running")
        write_state(root, phase="comp-prob-analysis")
        before, after = await run_direct_checked(
            original_run_skill, workflow_engine, workflow_id, root,
            "comp-prob-analysis",
            "Process every review finding. Edit only PROBLEM_ANALYSIS.md. Do not edit code, results, figures, paper, or any other file.",
            ["PROBLEM_ANALYSIS.md", "COMP_REVIEW_VERDICT.json", "_tmp/REVIEW_REPAIR_INSTRUCTIONS.md"],
            backup,
        )
        changed = check_stage(before, after, {"PROBLEM_ANALYSIS.md"}, "comp-prob-analysis", root, backup)
        require_changed(changed, "PROBLEM_ANALYSIS.md", "comp-prob-analysis")
        if missing_or_small(root, {"PROBLEM_ANALYSIS.md": 1500}):
            raise RuntimeError("PROBLEM_ANALYSIS.md is missing or below 1500 bytes")
        set_step(workflow_id, "comp-prob-analysis", "completed")
        mark_phase(root, "analysis")
    else:
        set_step(workflow_id, "comp-prob-analysis", "completed")

    if not phase_complete(read_state(root), "modeling"):
        set_workflow(workflow_id, "running", "comp-modeling")
        set_step(workflow_id, "comp-modeling", "running")
        write_state(root, phase="comp-modeling")
        before, after = await run_direct_checked(
            original_run_skill, workflow_engine, workflow_id, root,
            "comp-modeling",
            "Process every review finding. Edit only MODELING_REPORT.md and keep it consistent with PROBLEM_ANALYSIS.md. Replace unique primary definitions; do not add a second 实现口径 or justify a broken ledger as 固有性质. Do not edit code, results, figures, paper, or any other file.",
            ["PROBLEM_ANALYSIS.md", "MODELING_REPORT.md", "COMP_REVIEW_VERDICT.json", "_tmp/REVIEW_REPAIR_INSTRUCTIONS.md"],
            backup,
        )
        changed = check_stage(before, after, {"MODELING_REPORT.md"}, "comp-modeling", root, backup)
        require_changed(changed, "MODELING_REPORT.md", "comp-modeling")
        if missing_or_small(root, {"MODELING_REPORT.md": 2000}):
            raise RuntimeError("MODELING_REPORT.md is missing or below 2000 bytes")
        await run_modeling_gate(root, "boundary_contract_gate.py", "BOUNDARY_CONTRACT_GATE.json")
        await run_modeling_gate(root, "physics_semantic_gate.py", "PHYSICS_SEMANTIC_GATE.json")
        set_step(workflow_id, "comp-modeling", "completed")
        mark_phase(root, "modeling")

    state = read_state(root)
    changed_results: set[str]
    if not phase_complete(state, "code"):
        set_workflow(workflow_id, "running", "comp-code")
        set_step(workflow_id, "comp-code", "running")
        write_state(root, phase="comp-code")
        before = tree_snapshot(root)
        before_results = result_snapshot(root)
        existing_code = {
            name for name in before
            if name.startswith("code/") and (Path(name).suffix.lower() == ".py" or name == "code/requirements.txt")
        }
        existing_results = set(before_results)
        existing_dependencies = {
            name: script_dependencies(root / name)
            for name in before
            if name.startswith("figures/gen_fig_") and name.endswith(".py")
            and not forbidden_figure(root / name)
        }
        try:
            await run_direct_skill(
                original_run_skill, workflow_engine, workflow_id, root,
                "comp-code",
                "Use the repaired analysis and modeling to update existing computational code and rerun the data pipeline. Do not edit paper files, images, unrelated reports, or the full paper-figure workflow. Existing code sources, RESULTS.md, result JSON files, and only directly affected existing plot scripts may change. Do not generate GPT images.",
                [
                    "PROBLEM_ANALYSIS.md", "MODELING_REPORT.md", "code", "results",
                    "figures", "RESULTS.md", "_tmp/REVIEW_REPAIR_INSTRUCTIONS.md",
                ],
            )
            output_tail = await execute_code(root)
        except Exception:
            restore_changed(root, backup, changed_files(before, tree_snapshot(root)))
            raise
        after = tree_snapshot(root)
        after_results = result_snapshot(root)
        changed_all = changed_files(before, after)
        changed_results = {
            name for name in changed_files(before_results, after_results)
            if is_result_artifact(name)
        }
        changed_basenames = {Path(name).name for name in changed_results}
        affected_existing_scripts = {
            name for name, deps in existing_dependencies.items()
            if deps & changed_basenames
        }
        allowed = existing_code | {"RESULTS.md"} | existing_results
        allowed |= {
            name for name in changed_all
            if name.startswith("code/")
            and (Path(name).suffix.lower() == ".py" or name == "code/requirements.txt")
        }
        allowed |= {name for name in changed_all if is_result_artifact(name)}
        allowed |= affected_existing_scripts
        try:
            check_stage(before, after, allowed, "comp-code", root, backup)
            if "RESULTS.md" not in changed_all:
                raise RuntimeError("comp-code did not update RESULTS.md")
            if not changed_results:
                raise RuntimeError("comp-code did not update any result JSON")
            if missing_or_small(root, {name: 1 for name in existing_results}):
                raise RuntimeError("comp-code removed an existing result artifact")
            validate_json_files(root, changed_results)
            validate_result_mirrors(root, changed_results)
            validate_all_result_mirrors(root)
        except Exception:
            restore_changed(root, backup, changed_all)
            raise
        set_step(workflow_id, "comp-code", "completed")
        mark_phase(
            root, "code",
            changed_result_files=sorted(changed_results),
            code_output_tail=output_tail,
        )
    else:
        state = read_state(root)
        changed_results = set(state.get("changed_result_files") or [])
        if not changed_results:
            raise RuntimeError("repair state says code is complete but has no changed result files")

    if not phase_complete(read_state(root), "figures"):
        # Keep the public cursor on comp-review because affected-figure-data is
        # an internal phase, not a workflow_steps row.
        set_workflow(workflow_id, "running", "comp-review")
        write_state(root, phase="affected-figure-data", changed_result_files=sorted(changed_results))
        report = await run_affected_figures(root, changed_results, backup=backup)
        mark_phase(
            root, "figures",
            figure_script_count=report.get("script_count", 0),
            figure_report="_tmp/FIGURE_DATA_PATCH_REPORT.json",
        )
    else:
        report = {"script_count": read_state(root).get("figure_script_count", 0)}

    paper_step = next_paper_step(workflow_id)
    if not paper_step:
        raise RuntimeError("repair completed but no pending official paper step exists")
    set_step(workflow_id, "comp-review", "completed")
    set_workflow(workflow_id, "running", paper_step)
    write_state(
        root,
        repair_status="completed",
        phase="ready_for_paper",
        completed_before_paper=True,
        next_step=paper_step,
        figure_script_count=report.get("script_count", 0),
    )
    log_event(workflow_id, "info", f"repair completed; next={paper_step}; figures={report.get('script_count', 0)}")
    remove_backup(backup)


async def repair_guarded(
    original_run_skill: Callable[..., Awaitable[Any]],
    workflow_engine: Any,
    workflow_id: str,
    root: Path,
    plan: Optional[dict[str, Any]] = None,
) -> None:
    workflow_id = canonical_workflow_id(workflow_id)
    plan = plan or load_plan(root)
    if not plan.get("has_findings"):
        return
    fingerprint = plan["finding_fingerprint"]
    token = plan["review_token"]
    previous = read_state(root)
    if previous.get("review_token") == token:
        if previous.get("repair_status") == "completed":
            remove_backup(Path(str(previous["backup_dir"]))) if previous.get("backup_dir") else None
            return
        if previous.get("repair_status") == "blocked":
            # Official engine retries the same review skill immediately after a
            # raised error. Re-entering repair here would spend another full
            # model chain. A later user rerun is outside this short window.
            blocked_at = RECENT_BLOCKS.get(workflow_id, 0.0)
            if time.monotonic() - blocked_at < BLOCK_RETRY_WINDOW_SEC:
                raise RuntimeError(
                    f"repair is blocked for fingerprint {fingerprint}: {previous.get('error', '')}"
                )
            write_state(
                root,
                repair_status="running",
                error=None,
                resume_from_block=True,
            )
    active = ACTIVE.get(workflow_id)
    if active is not None:
        await active
        return
    task = asyncio.create_task(repair_once(original_run_skill, workflow_engine, workflow_id, root, plan))
    ACTIVE[workflow_id] = task
    try:
        await task
    except Exception as exc:
        current = read_state(root).get("phase") or "comp-review"
        write_state(
            root,
            repair_status="blocked",
            phase=current,
            error=str(exc),
            finding_fingerprint=fingerprint,
            review_token=token,
        )
        try:
            phase_skill = current if current in set(REPAIR_PHASES.values()) else "comp-review"
            set_step(workflow_id, phase_skill, "failed", str(exc))
            if phase_skill != "comp-review":
                set_step(workflow_id, "comp-review", "failed", str(exc))
            set_workflow(workflow_id, "failed", "comp-review")
        except Exception as state_exc:
            log.error("[review-repair] failed to persist blocked state: %s", state_exc)
        log_event(workflow_id, "error", f"repair blocked at {current}: {exc}")
        RECENT_BLOCKS[workflow_id] = time.monotonic()
        raise
    finally:
        ACTIVE.pop(workflow_id, None)


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
def install() -> bool:
    global PATCHED, ORIGINAL_RUN_SKILL, ORIGINAL_RUN_WORKFLOW
    if PATCHED:
        return True
    try:
        from services import claude_runner as runner
        from services import workflow_engine
    except Exception as exc:
        log.warning("[review-repair] import failed: %s", exc)
        return False

    existing = getattr(runner.claude_runner.run_skill, "_review_repair_wrapper", False)
    if existing:
        PATCHED = True
        return True
    original_run_skill = runner.claude_runner.run_skill
    original_run_workflow = workflow_engine.run_workflow
    original_run_single_step = workflow_engine.run_single_step
    ORIGINAL_RUN_SKILL = original_run_skill
    ORIGINAL_RUN_WORKFLOW = original_run_workflow

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
        if skill_name not in REVIEW_STEPS:
            return await original_run_skill(
                skill_name, arguments, cwd, workflow_id,
                on_output=on_output,
                extra_params=extra_params,
                workspace_files=workspace_files,
                context_summary=context_summary,
                inactivity_timeout=inactivity_timeout,
                resume_session_id=resume_session_id,
                step_model=step_model,
            )

        canonical_id = canonical_workflow_id(workflow_id)
        root = workspace_for(canonical_id, cwd)
        before_token = review_token(root)
        try:
            result = await original_run_skill(
                skill_name, arguments, cwd, workflow_id,
                on_output=on_output,
                extra_params=extra_params,
                workspace_files=workspace_files,
                context_summary=context_summary,
                inactivity_timeout=inactivity_timeout,
                resume_session_id=resume_session_id,
                step_model=step_model,
            )
            if not result_ok(result):
                raise RuntimeError(f"{skill_name} returned failure: {str(result)[:1000]}")
            plan = load_plan(root)
            after_token = review_token(root)
            state = read_state(root)
            if before_token == after_token and not (
                state.get("repair_status") == "completed"
                and state.get("review_token") == plan["review_token"]
            ):
                raise RuntimeError("review artifacts were not refreshed; refusing stale verdict")
            await repair_guarded(original_run_skill, workflow_engine, canonical_id, root, plan)
            return result
        except Exception as exc:
            state = read_state(root)
            if state.get("repair_status") != "blocked":
                write_state(root, repair_status="blocked", phase="comp-review", error=str(exc))
                try:
                    set_step(canonical_id, "comp-review", "failed", str(exc))
                    set_workflow(canonical_id, "failed", "comp-review")
                except Exception:
                    pass
            raise

    setattr(patched_run_skill, "_review_repair_wrapper", True)
    setattr(patched_run_skill, "_review_repair_original", original_run_skill)
    runner.claude_runner.run_skill = patched_run_skill

    async def invoke_original_workflow(workflow_id: str) -> Any:
        canonical_id = canonical_workflow_id(workflow_id)
        if canonical_id in ACTIVE_WORKFLOWS:
            return await original_run_workflow(workflow_id)
        ACTIVE_WORKFLOWS.add(canonical_id)
        try:
            return await original_run_workflow(workflow_id)
        finally:
            ACTIVE_WORKFLOWS.discard(canonical_id)

    async def patched_run_workflow(workflow_id: str) -> Any:
        canonical_id = canonical_workflow_id(workflow_id)
        root = workspace_for(canonical_id, "")
        state = read_state(root) if root else {}
        if state.get("repair_status") == "blocked":
            plan = load_plan(root)
            if plan["review_token"] != state.get("review_token"):
                raise RuntimeError("review content changed while recovering a blocked repair")
            await repair_guarded(original_run_skill, workflow_engine, canonical_id, root, plan)
            return await invoke_original_workflow(canonical_id)
        if state.get("repair_status") == "running":
            plan = load_plan(root)
            if plan["review_token"] != state.get("review_token"):
                raise RuntimeError("review content changed while recovering repair")
            await repair_guarded(original_run_skill, workflow_engine, canonical_id, root, plan)
        return await invoke_original_workflow(canonical_id)

    async def patched_run_single_step(workflow_id: str, skill_name: str) -> Any:
        canonical_id = canonical_workflow_id(workflow_id)
        result = await original_run_single_step(canonical_id, skill_name)
        if skill_name not in REVIEW_STEPS:
            return result
        # The compiled single-step API may return None on both success and
        # failure. Its persisted step status is the authoritative gate.
        if workflow_step_status(canonical_id, skill_name) != "completed":
            return result
        root = workspace_for(canonical_id, "")
        state = read_state(root)
        if state.get("repair_status") == "blocked":
            plan = load_plan(root)
            if plan.get("has_findings"):
                await repair_guarded(original_run_skill, workflow_engine, canonical_id, root, plan)
                state = read_state(root)
        else:
            plan = load_plan(root)
        if plan.get("has_findings") and state.get("repair_status") != "completed":
            raise RuntimeError("review step returned before repair completed")
        paper_step = next_paper_step(canonical_id)
        if paper_step:
            set_step(canonical_id, skill_name, "completed")
            set_workflow(canonical_id, "running", paper_step)
            return await invoke_original_workflow(canonical_id)
        return result

    setattr(patched_run_workflow, "_review_repair_original", original_run_workflow)
    setattr(patched_run_single_step, "_review_repair_original", original_run_single_step)
    workflow_engine.run_workflow = patched_run_workflow
    workflow_engine.run_single_step = patched_run_single_step
    router_module = sys.modules.get("routers.workflows")
    if router_module is not None:
        router_module.run_workflow = patched_run_workflow
        router_module.run_single_step = patched_run_single_step
    PATCHED = True
    log.info("[review-repair] installed")
    return True
