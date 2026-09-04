"""Modex runtime patch: use the configured OpenAI-compatible endpoint consistently.

Covers settings persistence/readback, connection tests, direct LLM calls,
Claude CLI subprocesses, and Responses ImageGen environment variables.
"""
from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import logging
import os
import re
import ssl
import sqlite3
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

log = logging.getLogger(__name__)
_PATCHED = False
_PROMPT_CACHE: dict = {}  # filename -> (mtime_ns, content)
# Official-skill-first baseline (2026-08-11): local research/writing/figure
# overlays are disabled by default. Set MODEX_ENABLE_LOCAL_RESEARCH_OVERLAYS=1
# only for controlled A/B comparisons or temporary compatibility tests.
LOCAL_RESEARCH_OVERLAYS_ENABLED = os.environ.get(
    "MODEX_ENABLE_LOCAL_RESEARCH_OVERLAYS", "0"
).strip().lower() in {"1", "true", "yes", "on"}
# 工具/环境提示（2026-08-12）：告知 executor 本机专属参考资源（模型库、图表配方包）。
# 与科研 overlay 分离：这是"环境事实"（本机有什么工具），不是"论文质量规则"。
# 默认开启；设 MODEX_DISABLE_TOOL_HINTS=1 可关闭。极短、幂等、只提示存在性，不注入任何规则。
# 2026-08-14: default to a minimal-injection execution baseline.  Tool hints
# are optional reference text, not runtime requirements, and are disabled until
# an explicit controlled experiment enables them.
TOOL_HINTS_ENABLED = os.environ.get(
    "MODEX_ENABLE_TOOL_HINTS", "0"
).strip().lower() in {"1", "true", "yes", "on"}
USER_BASE_URL = "https://api.deepseek.com"
TEXT_BASE_URL = "https://api.deepseek.com"  # 文本三角色基线（2026-08-11 切到 DeepSeek 官方 deepseek-v4-flash）
IMAGE_BASE_URL = "https://ergouzi.life"      # 图片角色基线
# 官方残留/无效默认：healBeforeBackend 或官方初始化可能把 base_url 写回 mhcoding。
# 这些不是用户显式选择，读取/保存时都应按角色纠正到基线。
OFFICIAL_JUNK_BASES = {"https://www.mhcoding.xyz", "https://api.mhcoding.xyz", "https://www.mhcoding.xyz/"}


def _correct_base_url(key: str, value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if value in OFFICIAL_JUNK_BASES or value == "https://www.mhcoding.xyz":
        return TEXT_BASE_URL if key != "gpt_image_base_url" else IMAGE_BASE_URL
    return value


_PRESET_DB_PATH = Path.home() / "AppData" / "Roaming" / "MHAgent" / "db" / "aris.db"


def _load_preset_base_urls() -> dict:
    """读取 model_presets 表 id -> base_url 映射（2026-08-13：预设级中转站配置）。"""
    import sqlite3
    result: dict = {}
    try:
        conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT id, base_url FROM model_presets "
                "WHERE base_url IS NOT NULL AND base_url != ''"
            )
            result = {r[0]: str(r[1]).strip().rstrip("/") for r in cur.fetchall()}
        except sqlite3.OperationalError:
            pass  # 旧库无 base_url 列
        conn.close()
    except Exception as exc:
        log.warning("[local-api] load preset base_url failed: %s", exc)
    return result


def _load_preset_full() -> dict:
    """读取 model_presets 完整身份：id -> {model_id, base_url, api_key}。

    每个预设都是自洽的运行时身份（2026-08-15）：sol 的 key 只配 sol 的端点，
    deepseek 的 key 只配 deepseek 的端点。spawn 时按命令行 --model 反查预设，
    用预设自己的 key/url，避免“步骤选了 sol 模型却拿全局 deepseek key 打
    deepseek 端点”的错配。返回 {presets: id->entry, by_model: model_id->id}。
    """
    import sqlite3
    presets: dict = {}
    by_model: dict = {}
    try:
        conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
        cur = conn.cursor()
        try:
            cur.execute("SELECT id, model_id, api_key, base_url FROM model_presets")
            for pid, model_id, api_key, base_url in cur.fetchall():
                entry = {
                    "id": pid,
                    "model_id": (model_id or "").strip(),
                    "api_key": (api_key or "").strip(),
                    "base_url": normalize_base_url(base_url or ""),
                }
                presets[pid] = entry
                if entry["model_id"] and entry["model_id"] not in by_model:
                    by_model[entry["model_id"]] = pid
        except sqlite3.OperationalError:
            pass
        conn.close()
    except Exception as exc:
        log.warning("[local-api] load preset full failed: %s", exc)
    return {"presets": presets, "by_model": by_model}
APP_DIR = Path(__file__).resolve().parents[2]
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
REVIEWER_SCRIPT = APP_DIR / "tools" / "reviewer_client.py"
BASE_URL_KEYS = (
    "executor_base_url",
    "reviewer_base_url",
    "editor_ai_base_url",
    "gpt_image_base_url",
)
AGENT_KEYS = {
    "executor": {
        "api_key": "executor_api_key",
        "base_url": "executor_base_url",
        "model_id": "executor_model_id",
    },
    "reviewer": {
        "api_key": "reviewer_api_key",
        "base_url": "reviewer_base_url",
        "model_id": "reviewer_model_id",
    },
    "editor_ai": {
        "api_key": "editor_ai_api_key",
        "base_url": "editor_ai_base_url",
        "model_id": "editor_ai_model_id",
    },
}

# The figure skills can otherwise feed multiple full-resolution images and large
# JSON files back into one Claude Code session.  The resulting Base64 payloads
# are much larger than the actual task and eventually overflow the model's
# context window.  These instructions are appended at prompt construction time
# so they also apply when the encrypted official skill package is updated.
EXTERNAL_REVIEW_GUARD = r"""

## LOCAL EXTERNAL REVIEW OVERRIDE (mandatory)
This rerun must obtain fresh external-review scores. It overrides any fallback
instruction in the skill:

1. Do not reuse pre-existing `_round1_review.txt`, `_round2_review.txt`,
   `_round2_external_attempt.txt`, `_reviewer_thread.json`, score state, or an
   earlier self-review. Create fresh files during this run.
2. Run `REVIEWER_SCRIPT` for both Round 1 and Round 2. Round 2 must reuse only
   the new thread created by Round 1.
3. A successful review must contain a numeric score, verdict, substantive
   strengths/weaknesses, and actionable fixes. Merely finding an old file does
   not count as success.
4. If either external call fails, stop the step with a non-zero result. Do not
   substitute self-review and do not report the workflow as successfully scored.
5. Label scores accurately as `External Review`; never label a self-assigned
   score as external. Record the provider model and review-file modification
   time, but never expose the API key.
6. Preserve all frozen experimental numbers and evidence boundaries. Apply only
   review fixes supported by existing data and code; do not invent experiments.
"""


FIGURE_CONTEXT_GUARD = r"""

## LOCAL CONTEXT SAFETY OVERRIDE (mandatory)
This section overrides any conflicting inspection or reading instruction above.

1. NEVER call Read on PNG, JPG, JPEG, WEBP, GIF, BMP, PDF figure outputs, or any
   other binary image. Claude Code's Read tool returns image bytes as Base64 and
   can overflow the context window. Verify existing figures using file names,
   file sizes, Pillow metadata, or a short local Python validation script only.
2. NEVER read `figures/all_results.json` or another JSON/JSONL/CSV file larger
   than 200 KB in full. Use Python to extract only the exact aggregate fields
   required for a plot and print at most 200 lines / 20 KB of compact results.
3. For text files, call Read without a `pages` argument. The `pages` argument is
   reserved for paginated PDF reads; never pass `pages: ""`.
4. Do not load all reference manuals. Read at most one directly relevant
   reference section, in chunks no larger than 300 lines. Prefer the existing
   `FIGURE_REPORT.md`, `RESULTS.md`, and already generated scripts over rereading
   tutorials or API manuals.
5. Reuse valid existing figure files and scripts. If required PNG/PDF outputs
   already exist and pass a metadata check, do not regenerate or visually read
   them merely for confirmation.
6. Keep tool output compact: no Base64, no binary bytes, no full large-file
   dumps, and no more than 20 KB of diagnostic text per command.
7. If the API reports context-window overflow, do not repeat the same reads.
   Continue from existing files with a clean, minimal plan and finish the report.
8. The final response must summarize created/reused files and validation results
   in plain text; it must not embed any image data.
"""


FIGURE_PLANNING_OVERLAY = r"""

## LOCAL FIGURE PLANNING OVERLAY (mandatory for figure work)
Before writing any plotting, DrawIO, TikZ, or image-generation code:

1. Extract the project's core claims and map each claim to observable, model,
   comparison, uncertainty, or mechanism evidence.
2. Plan 3-5 primary Figures and assign each panel one distinct question.
3. Produce a compact Figure Contract for every primary Figure with:
   `figure_id`, `purpose`, `claim`, `layout`, `panels`, `data_source`, `route`,
   and `export`. Use `data_figure` for quantitative evidence,
   `drawio_diagram` for workflows, `tikz_mechanism` for precise mechanisms,
   and `concept_image` only for non-quantitative visual explanation.
4. Stop before rendering if a claim has no traceable data source, if panels
   duplicate one another, if uncertainty is available but omitted, or if a
   concept image is being used as quantitative evidence.
5. Use non-symmetric composite layouts when they improve evidence hierarchy:
   overview/mechanism -> deviation/comparison -> relationship/uncertainty.
6. For Chinese papers, keep axes, legends, annotations, and captions in
   Chinese; preserve variables, SI units, and standard abbreviations as needed.
7. Production output must include editable SVG and PDF plus a PNG preview;
   also save the contract, source-data manifest, and caption alongside the
   figure. Never hand-copy result numbers into plotting code.

## EXPRESSION MANDATE (mandatory, quality-driven not checkbox-driven)
The figure set must communicate findings with visual sophistication, not as
bare default matplotlib output. Judge by expression, not by counting 3-D
charts.

0. **Use the embedded scientific palettes below** (from the scientific-color
   system). Never fall back to raw matplotlib default colors. Pick by data
   scale: qualitative (<=8 groups) -> Okabe-Ito; sequential heatmap/contour ->
   Viridis/Magma; diverging (deviations) -> RdBu/PiYG; many groups (<=10) ->
   tab10. Embed the hex values directly in code:
   - Okabe-Ito: #000000 #0072B2 #E69F00 #009E73 #CC79A7 #56B4E9 #F0E442 #D55E00
   - Viridis:   #440154 #31688E #1F9E89 #35B779 #FDE725
   - Magma:     #000004 #420A68 #BB3754 #F9975B #FCFDBF
   - RdBu:      #D7191C #FFFFBF #2C7BB6
   - PiYG:      #C51B7D #F7F7F7 #4D9221
   - tab10:     #1f77b4 #ff7f0e #2ca02c #d62728 #9467bd #8c564b #e377c2 #7f7f7f #bcbd22 #17becf
   - Paul Tol high contrast: #004488 #DDAA33 #BB5566
   One figure = one main message; highlight color <=2; de-saturate the rest.
   Colorblind-friendly first: avoid pure red-green pairs, prefer blue-orange.

1. **Every figure makes a claim**: each figure must have one clear takeaway
   (comparison / trend / distribution / mechanism / uncertainty) stated in
   title and caption. If the reader cannot see the point in ~10 seconds, the
   figure needs rework.
2. **Multi-panel storytelling**: prefer composite figures (GridSpec, shared
   axes, inset/zoom panels, color-coded facets) that tell one complete story
   per figure: mechanism -> data -> model -> uncertainty. Single-axis figures
   are allowed but should not dominate the set; each chapter's main figure
   should be a composite.
3. **Visual sophistication**: apply a consistent scientific palette (the hex
   values above), clear visual hierarchy (highlight the key curve/region with
   color, size, or annotations), thoughtful typography, and high information
   density without overload. Avoid matplotlib defaults; use professional styles
   (journal-style spines, subtle grids, consistent fonts).
4. **Dimensional fit, not 3-D for its own sake**: use 3-D projections (mplot3d
   / plotly Scatter3d/Surface/Mesh3d), animations, network layouts,
   streamlines, or t-SNE/UMAP **only when the data genuinely has that
   dimensionality** (e.g. 3-D parameter surfaces, multi-objective fronts,
   high-dimensional feature structure, spatial fields). If the data is
   intrinsically 2-D, a polished 2-D figure beats a forced 3-D one.
5. **Advanced visual tools welcome**: when the data supports it, use heatmaps
   with annotations, ridgelines, dumbbell/slope plots, tornado plots, PDP/ICE
   grids, SHAP beeswarm, calibration curves with confidence bands, 3-D
   surfaces, or interactive plotly figures - choose the form that best exposes
   the claim.
6. **No downgrade on failure**: if an ambitious figure fails to render, do NOT
   silently replace it with a bare bar/line chart. Retry with an alternate
   sophisticated form (e.g. 3-D surface -> 3-D scatter with projection lines;
   GridSpec -> plotly subplots; annotation heatmap -> labeled faceted plot).
   If all attempts fail, mark the item BLOCKED in the Figure Contract and
   report it explicitly.
7. **Audit by expression**: the final figure audit must verify that (a) every
   figure has a claim-based title/caption, (b) chapter main figures are
   composite, (c) the set uses the embedded scientific palettes (no raw
   defaults), (d) the set shows >=3 distinct sophisticated chart families (not
   all basic), and (e) no figure was silently downgraded. Record the audit in
   the Figure Contract.

The contract is a planning artifact, not a replacement for the existing figure
skill. Preserve existing evidence boundaries and use the smallest relevant
reference section.
"""


WRITING_EVIDENCE_OVERLAY = r"""

## LOCAL WRITING EVIDENCE OVERLAY (mandatory for manuscript work)
Treat manuscript writing as claim-evidence engineering, not fluent text generation.
Before drafting a full section or paper:

1. Build a `paper_story` with the research question, gap, contribution boundary,
   claims to make, claims to avoid, and the evidence needed for each claim.
2. Build a claim-evidence ledger. Every major claim must link to one or more
   traceable sources: result JSON/table, analysis script, experiment log,
   figure/table, or verified literature record. Mark missing evidence instead
   of filling it with plausible prose.
3. Create a Section Contract before writing each section: purpose, reader
   question, paragraph roles, allowed claims, evidence sources, figures/tables,
   citations, and explicit limitations.
4. Write sections independently, then run a cross-section consistency pass for
   numbers, units, sample sizes, terminology, figure/table references,
   confidence intervals, p-values, and causal language.
5. Do not strengthen an association into a causal claim. Preserve the exact
   scope, population, model, metric, uncertainty and decision boundary in the
   source evidence.
6. Verify citations against authoritative metadata before treating them as
   references. If a citation's metadata or claim support is unverified, mark it
   as `[CITATION NEEDED]` and do not invent a BibTeX entry.
7. Run a skeptical reviewer pass before declaring completion. Report severity,
   location, why the issue matters, and the smallest evidence-supported fix.
8. Do not call the manuscript final until the manuscript, figures, tables,
   captions, references, source manifests and build/check logs agree.

Writing-quality passes should follow this order: argument and evidence ->
structure and paragraph flow -> terminology and numerical consistency ->
sentence clarity and concision -> venue/style polish. Style polish must never
change scientific meaning or silently add evidence.
"""

def _load_local_prompt(filename: str, fallback: str) -> str:
    """Load a maintainable local overlay with mtime-based caching."""
    path = PROMPT_DIR / filename
    try:
        st = path.stat()
        cached = _PROMPT_CACHE.get(filename)
        if cached is not None and cached[0] == st.st_mtime_ns:
            return cached[1]
        text = path.read_text(encoding="utf-8").strip()
        result = ("\n\n" + text + "\n") if text else fallback
        _PROMPT_CACHE[filename] = (st.st_mtime_ns, result)
        return result
    except FileNotFoundError:
        # Local overlays are optional and disabled by default. A package update
        # may omit their source files; fall back silently in that baseline.
        return fallback
    except Exception as exc:
        log.warning("[local-overlay] failed to load %s: %s", path, exc)
    return fallback


# The old figure planning/context overlays remain disabled. This new overlay is
# deliberately limited to the user-curated palette registry and does not alter
# official chart selection, evidence, or export behavior.
FIGURE_PLANNING_OVERLAY = ""
PALETTE_OVERLAY = ""  # official Modex now ships its own palette library
DATA_ANALYSIS_OVERLAY = _load_local_prompt("local_data_analysis_overlay.md", "")
FIGURE_DATA_INTEGRITY_OVERLAY = _load_local_prompt(
    "local_figure_data_integrity_overlay.md", ""
)
FIGURE_EVIDENCE_COMPOSITION_OVERLAY = _load_local_prompt(
    "local_figure_evidence_composition_overlay.md", ""
)
# Figure quality is always-on for figure skills. It is deliberately separate
# from the broad research overlays: disabling those overlays must not disable
# data/semantic/visual safeguards for generated figures.
FIGURE_QUALITY_OVERLAY = _load_local_prompt(
    "local_figure_quality_overlay.md", ""
)
WRITING_STYLE_OVERLAY = _load_local_prompt("local_writing_style_overlay.md", "")
WRITING_EVIDENCE_OVERLAY = _load_local_prompt(
    "local_writing_evidence_overlay.md", WRITING_EVIDENCE_OVERLAY
) + _load_local_prompt("local_writing_artifacts.md", "")
REQUIREMENT_CONTRACT_OVERLAY = _load_local_prompt(
    "local_requirement_contract_overlay.md", ""
)
COMPETITION_RELEASE_OVERLAY = _load_local_prompt(
    "local_competition_release_overlay.md", ""
)

# 通用科研质量底线：保持短小，约束数据、证据和结论等级。
RESEARCH_QUALITY_OVERLAY = _load_local_prompt(
    "local_research_quality_overlay.md", ""
)
RESEARCH_QUALITY_SKILLS = {
    "comp-modeling", "comp-code", "comp-prob-analysis", "comp-stats-topic",
    "dse-loop", "experiment-plan", "run-experiment",
    "monitor-experiment", "ablation-planner", "analyze-results",
    "experiment-bridge", "novelty-check", "idea-discovery", "idea-creator",
    "comp-review",
}

# 工具提示（默认开启，独立于科研 overlay 开关）。只提示资源存在性与用法，不注入规则。
MODEL_LIBRARY_HINT = (
    "\n\n## LOCAL TOOL AVAILABILITY (reference only, not a rule)\n"
    "本机提供候选模型库工具 `tools/model_lookup.py`：`--problem-type <题型> --topic <关键词>` "
    "查询候选模型池，`--verify <模型id>` 输出该模型的适用条件与反模式清单。"
    "建模选型前可运行作为参考，最终选型仍由题目机制、数据与消融证据决定。\n"
)
FIGURE_EXAMPLES_HINT = (
    "\n\n## LOCAL TOOL AVAILABILITY (reference only, not a rule)\n"
    "本机提供图表配方包 `resources/figure_examples/`（27 个已验证示例 .py + INDEX.md + "
    "FIGURE_ART_DIRECTOR.md 视觉合同与矢量输出约定），绘图前按数据形状读取对应示例源码。\n"
    f"图表质量门禁：`{APP_DIR / 'tools' / 'figure_quality_gate.py'}`，绘图前后按质量合同运行。\n"
    f"绘图前先运行数据形状分析：`{APP_DIR / 'tools' / 'figure_data_shape_profile.py'}`，再运行编辑性门禁：`{APP_DIR / 'tools' / 'figure_editorial_gate.py'}`；它们会识别近常量、重复模式、0/1饱和、相似panel，并建议点图/差值图/例外摘要/紧凑图/附录退出。\n"
    f"批注候选策略在 `{APP_DIR / 'tools' / 'figure_annotation_policy.py'}`：只从阈值、转折、极值、异常、差异、选择和机制锚点生成短批注，不为填空白添加泛化结论句。\n"
    f"特殊点/线的统一语义在 `{APP_DIR / 'tools' / 'figure_visual_semantics.py'}`：高亮色必须与 marker、线型、线宽和透明度成组使用，不得每个脚本临时换高亮色。\n"
)
FIGURE_HINT_SKILLS = {
    "nature-figure", "paper-figure", "paper-figure-html", "paper-figure-drawio",
    "paper-illustration", "experiment-bridge",
}

# CLAUDE.md 工具提示块：Claude Code 每次启动必读工作区 CLAUDE.md，这是
# executor 主角色唯一可靠的注入点（_load_skill_prompt 是盲区，2026-08-13 确认）。
# v4：即使通用工具提示关闭，也要让 executor 看到图表质量合同；旧 v1-v3 块会被清理。
_TOOL_HINTS_MARKER_V3 = "LOCAL TOOL AVAILABILITY v4"
_TOOL_HINTS_BLOCK_V3 = (
    "\n## " + _TOOL_HINTS_MARKER_V3 + " (reference only, not a rule)\n"
    "本机提供三个专属参考资源（本地增强层注入）：\n"
    f"1. `{APP_DIR / 'tools' / 'model_lookup.py'}`：候选模型库查询（--problem-type 查候选、--verify 输出适用条件与反模式），建模选型前可运行参考。\n"
    f"2. `{APP_DIR / 'resources' / 'figure_examples'}`：图表配方包（27 个已验证示例 + FIGURE_ART_DIRECTOR.md 视觉合同与矢量输出约定），绘图前按数据形状读取对应示例源码。\n"
    f"3. `{APP_DIR / 'tools' / 'formula_code_gate.py'}`：公式-代码一致性检查（条件概率分母子集、min(x,x) 自比较）。\n"
    f"4. `{APP_DIR / 'tools' / 'figure_quality_gate.py'}`：图表数据/语义/视觉/导出门禁，绘图前后运行。\n"
    f"4. `{APP_DIR / 'tools' / 'math_release_gate.py'}`：建模/编码后跑 `--workspace .`；另有 problem_contract / optimization_protocol / validation_protocol / figure_number_consistency 闸门。\n"
    f"5. `{APP_DIR / 'tools' / 'preset_smoke.py'}`：更新后或换预设后做协议连通冒烟。\n"
    f"6. `{APP_DIR / 'tools' / 'figure_quality_gate.py'}`：图表质量门禁；paper-figure 前后运行。\n"
    f"7. `{APP_DIR / 'tools' / 'figure_data_shape_profile.py'}`：绘图前的数据形状分析；先识别有效变化再选模板。\n"
    f"8. `{APP_DIR / 'tools' / 'figure_editorial_gate.py'}`：图表编辑性门禁；识别重复、不变量、饱和、相似panel、3D必要性与标注过量。\n"
    f"9. `{APP_DIR / 'tools' / 'figure_annotation_policy.py'}`：证据触发式批注候选；批注短、贴近数据、不重复正文。\n"
    f"10. `{APP_DIR / 'tools' / 'figure_visual_semantics.py'}`：统一特殊点/线的颜色、marker、线型、线宽和透明度语义。\n"
    "图表任务必须先做数据形状/读者问题映射；复合图只在每个panel增加独立证据时使用，不能为凑密度硬拼；数据不足时允许紧凑单图、表格、inset、例外摘要或附录。\n"
    "用户指定的 MH_DATA_FIG_PALETTE 优先于默认色；热图用感知均匀色图，稀疏网格不得伪造连续面；随机/重构分布必须明确标注且不能冒充观测证据。\n"
)
_OLD_TOOL_HINTS_RE = re.compile(r"\n## LOCAL TOOL AVAILABILITY.*?(?=\n## |\Z)", re.S)


def _ensure_claude_md_tool_hints(cwd: Any) -> None:
    """在 Claude Code 启动前把工具提示幂等地追加到工作区 CLAUDE.md。

    架构修正（2026-08-13）：executor 主角色是 Claude Code CLI 子进程，它读
    SKILL.md/CLAUDE.md 靠自己的文件读取机制，_load_skill_prompt 的 patch 是盲区。
    CLAUDE.md 是每次启动必读的文件，因此这里才是工具提示真正到达 executor 的注入点。
    """
    if not cwd or not TOOL_HINTS_ENABLED:
        return
    try:
        md_path = Path(cwd) / "CLAUDE.md"
        if not md_path.exists():
            return
        text = md_path.read_text(encoding="utf-8")
        if _TOOL_HINTS_MARKER_V3 in text:
            # Current block is already present. Do not remove it: the previous
            # implementation accidentally matched the current block with the
            # legacy cleanup regex, causing fresh figure instructions to vanish
            # on alternating executor spawns.
            return
        text = _OLD_TOOL_HINTS_RE.sub("", text)  # 清理旧 v1/v2 块
        md_path.write_text(text.rstrip() + "\n" + _TOOL_HINTS_BLOCK_V3, encoding="utf-8")
        log.info("[local-api] injected tool hints v3 into %s", md_path)
    except Exception as exc:
        log.warning("[local-api] CLAUDE.md tool hints injection failed: %s", exc)


def _inject_figure_quality_contract(cwd: Any) -> None:
    """Make the figure contract visible to Claude Code through CLAUDE.md.

    The compiled runner may bypass the Python skill-prompt loader, while Claude
    Code reliably reads CLAUDE.md. This keeps the quality contract effective on
    both paths without changing the encrypted official skill package.
    """
    if not cwd or not FIGURE_QUALITY_OVERLAY:
        return
    try:
        md_path = Path(cwd) / "CLAUDE.md"
        if not md_path.exists():
            return
        text = md_path.read_text(encoding="utf-8")
        marker = "## LOCAL FIGURE QUALITY CONTRACT V2"
        # Refresh V1/V2 in place so an existing workspace receives rule
        # changes without accumulating stale or contradictory contracts.
        section_re = re.compile(r"\n## LOCAL FIGURE QUALITY CONTRACT V[12].*?(?=\n## |\Z)", re.S)
        cleaned = section_re.sub("", text).rstrip()
        updated = cleaned + "\n\n" + FIGURE_QUALITY_OVERLAY.strip() + "\n"
        if updated != text:
            md_path.write_text(updated, encoding="utf-8")
            log.info("[local-api] refreshed figure quality contract V2 in %s", md_path)
    except Exception as exc:
        log.warning("[local-api] figure quality contract injection failed: %s", exc)


def _enforce_workspace_palette_precedence(cwd: Any) -> None:
    """Patch copied plot_utils so the user's palette marker beats hard-coded calls.

    Some generated scripts call setup_style('journal'), which otherwise bypasses
    CLAUDE.md's MH_DATA_FIG_PALETTE marker. The workspace copy is patched
    idempotently at spawn time; no generated figure data or official package is
    changed.
    """
    if not cwd:
        return
    try:
        path = Path(cwd) / "_utils" / "plot_utils.py"
        if not path.exists():
            return
        # Capture the user's pre-workflow setting once. The snapshot is the
        # authority for every later rerun, so mid-workflow script defaults and
        # palette rotation cannot change the visual identity of the paper.
        snapshot = path.parent / "_user_palette_snapshot.json"
        if not snapshot.exists():
            import re as _re
            md = Path(cwd) / "CLAUDE.md"
            md_text = md.read_text(encoding="utf-8", errors="ignore") if md.exists() else ""
            pm = _re.search(r"MH_DATA_FIG_PALETTE=([A-Za-z_]+)", md_text)
            cm = _re.search(r"MH_DATA_FIG_COLORS=([#0-9A-Fa-f,]+)", md_text)
            colors = _re.findall(r"#[0-9A-Fa-f]{6}", cm.group(1)) if cm else []
            snapshot.write_text(
                json.dumps({"palette": pm.group(1) if pm else None, "colors": colors}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        text = path.read_text(encoding="utf-8")
        marker = "# MODEX_USER_PALETTE_PRECEDENCE_V2"
        if marker in text:
            return
        needle = "    plt = _get_plt()\n"
        if needle not in text:
            return
        inject = (
            "    " + marker + "\n"
            "    # Freeze the palette selected before this workflow started.\n"
            "    # A later script-level setup_style('journal') cannot replace it.\n"
            "    try:\n"
            "        import json as _json\n"
            "        _snapshot = os.path.join(os.path.dirname(__file__), '_user_palette_snapshot.json')\n"
            "        if os.path.isfile(_snapshot):\n"
            "            with open(_snapshot, encoding='utf-8') as _sf:\n"
            "                _spec = _json.load(_sf)\n"
            "        else:\n"
            "            _spec = {'palette': _read_palette_marker(), 'colors': _read_custom_colors()}\n"
            "            with open(_snapshot, 'w', encoding='utf-8') as _sf:\n"
            "                _json.dump(_spec, _sf, ensure_ascii=False, indent=2)\n"
            "        _user_marker = _spec.get('palette')\n"
            "        if _user_marker == 'custom' and _spec.get('colors'):\n"
            "            palette = _spec['colors']\n"
            "        elif _user_marker and _user_marker in PALETTES and _user_marker != 'random':\n"
            "            palette = _user_marker\n"
            "    except Exception:\n"
            "        pass\n\n"
        )
        path.write_text(text.replace(needle, inject + needle, 1), encoding="utf-8")
        log.info("[local-api] enforced user palette precedence in %s", path)
    except Exception as exc:
        log.warning("[local-api] palette precedence patch failed: %s", exc)


def _inject_checkpoint_feedback(cwd: Any) -> None:
    """User checkpoint feedback injection, called on every executor spawn."

    CHECKPOINT_FEEDBACK.md is written by _mode_a_resolve_checkpoint when the
    user replies with feedback; appending it to CLAUDE.md makes the rerun of
    the same step actually see the requested changes. The file is removed on
    approve so it never leaks into later steps. Kept separate from
    _ensure_claude_md_tool_hints because that function returns early once the
    v3 marker exists, which would skip feedback entirely.
    """
    if not cwd:
        return
    try:
        fb_path = Path(cwd) / "_tmp" / "CHECKPOINT_FEEDBACK.md"
        if not fb_path.exists():
            return
        fb_text = fb_path.read_text(encoding="utf-8")
        md_path = Path(cwd) / "CLAUDE.md"
        text = md_path.read_text(encoding="utf-8")
        marker = "## USER CHECKPOINT FEEDBACK"
        header = marker + " (read and address every point before finishing)\n```\n"
        section = header + fb_text.rstrip() + "\n```\n"
        if marker in text:
            text = text.split(marker, 1)[0].rstrip() + "\n\n" + section
        else:
            text = text.rstrip() + "\n\n" + section
        md_path.write_text(text, encoding="utf-8")
        log.info("[local-api] refreshed checkpoint feedback in %s", md_path)
    except Exception as exc:
        log.warning("[local-api] checkpoint feedback injection failed: %s", exc)

# 竞赛创新层：只注入模型选择、创新发现和独立复核；代码/实验阶段使用
# 更短的 solver evidence overlay，避免重复占用上下文。
COMPETITION_INNOVATION_OVERLAY = _load_local_prompt(
    "local_competition_model_innovation_overlay.md", ""
)
COMPETITION_INNOVATION_SKILLS = {
    "comp-prob-analysis", "comp-modeling", "novelty-check",
    "idea-discovery", "idea-creator", "comp-review",
}
SOLVER_EVIDENCE_OVERLAY = _load_local_prompt(
    "local_solver_evidence_overlay.md", ""
)
SOLVER_EVIDENCE_SKILLS = {
    "comp-code", "comp-stats-topic", "experiment-plan", "run-experiment",
    "monitor-experiment", "ablation-planner", "analyze-results",
    "experiment-bridge", "dse-loop",
}


WRITING_SKILLS = {
    "paper-plan", "paper-plan-zh", "paper-writing", "paper-write", "paper-write-zh",
    "paper-write-docx", "paper-write-zh-docx", "paper-write-nature", "paper-write-nature-docx",
    "comp-paper-zh", "comp-paper-zh-docx", "comp-paper-en", "comp-paper-en-docx",
    "result-to-claim", "literature-review", "research-lit", "paper-analysis",
    "quality-check", "auto-review-loop", "auto-review-loop-llm", "auto-review-loop-minimax",
    "research-review", "editor-agent", "paper-compile", "paper-compile-zh",
}
REQUIREMENT_CONTRACT_SKILLS = {
    "comp-prob-analysis", "comp-modeling", "comp-review",
    "nature-figure", "paper-figure", "paper-figure-html", "paper-figure-drawio",
    "paper-illustration", "comp-paper-zh", "comp-paper-zh-docx",
    "comp-paper-en", "comp-paper-en-docx",
}
COMPETITION_RELEASE_SKILLS = {
    "comp-review", "comp-paper-zh", "comp-paper-zh-docx",
    "comp-paper-en", "comp-paper-en-docx",
}


def _append_tool_hints(skill_name: str, prompt: str) -> str:
    """注入极短的工具存在性提示（环境事实），独立于科研 overlay 开关。"""
    if not TOOL_HINTS_ENABLED:
        return prompt or ""
    result = prompt or ""
    if skill_name in RESEARCH_QUALITY_SKILLS and "model_lookup.py" not in result:
        result = result.rstrip() + MODEL_LIBRARY_HINT
    if skill_name in FIGURE_HINT_SKILLS and "figure_examples" not in result:
        result = result.rstrip() + FIGURE_EXAMPLES_HINT
    return result


def _append_local_skill_guards(skill_name: str, prompt: str) -> str:
    result = prompt or ""
    # 工具提示优先注入（默认开启，与科研 overlay 开关无关）。
    result = _append_tool_hints(skill_name, result)
    # The compact global figure master is appended by patched_load_skill_prompt.
    # Do not append a second legacy contract here: duplicate figure rules made
    # the executor over-focus on compliance and often degraded the composition.
    # Default path: preserve the encrypted official skill prompt byte-for-byte.
    # Quality overlays previously duplicated official workflow governance,
    # competed for context, and leaked gate vocabulary into manuscripts.
    if not LOCAL_RESEARCH_OVERLAYS_ENABLED:
        return result
    # Optional legacy path for controlled A/B comparisons only.
    # Palette-only figure overlay. The original Modex figure prompt remains the
    # base prompt; only the optional user palette registry is appended.
    if skill_name in {
        "nature-figure", "paper-figure", "paper-figure-html",
        "paper-figure-drawio", "paper-illustration", "experiment-bridge",
    }:
        if FIGURE_DATA_INTEGRITY_OVERLAY and "LOCAL FIGURE DATA INTEGRITY OVERLAY" not in result.upper():
            result = result.rstrip() + FIGURE_DATA_INTEGRITY_OVERLAY
        if FIGURE_EVIDENCE_COMPOSITION_OVERLAY and "LOCAL FIGURE EVIDENCE & COMPOSITION OVERLAY" not in result.upper():
            result = result.rstrip() + FIGURE_EVIDENCE_COMPOSITION_OVERLAY
    if skill_name in RESEARCH_QUALITY_SKILLS and DATA_ANALYSIS_OVERLAY:
        if "LOCAL DATA QUALITY AND ANALYSIS OVERLAY" not in result.upper():
            result = result.rstrip() + DATA_ANALYSIS_OVERLAY
    if skill_name in WRITING_SKILLS:
        if WRITING_EVIDENCE_OVERLAY and "LOCAL WRITING EVIDENCE OVERLAY" not in result.upper():
            result = result.rstrip() + WRITING_EVIDENCE_OVERLAY
        if WRITING_STYLE_OVERLAY and "LOCAL WRITING STYLE OVERLAY" not in result.upper():
            result = result.rstrip() + WRITING_STYLE_OVERLAY
    if skill_name == "auto-paper-improvement-loop":
        result = result.rstrip() + EXTERNAL_REVIEW_GUARD
    if skill_name in RESEARCH_QUALITY_SKILLS and RESEARCH_QUALITY_OVERLAY:
        if "LOCAL RESEARCH QUALITY OVERRIDE" not in result.upper():
            result = result.rstrip() + RESEARCH_QUALITY_OVERLAY
    if skill_name in COMPETITION_INNOVATION_SKILLS and COMPETITION_INNOVATION_OVERLAY:
        if "LOCAL_COMPETITION_INNOVATION_GATE_V1" not in result.upper():
            result = result.rstrip() + COMPETITION_INNOVATION_OVERLAY
    if skill_name in SOLVER_EVIDENCE_SKILLS and SOLVER_EVIDENCE_OVERLAY:
        if "LOCAL_SOLVER_EVIDENCE_GATE_V1" not in result.upper():
            result = result.rstrip() + SOLVER_EVIDENCE_OVERLAY
    if skill_name in REQUIREMENT_CONTRACT_SKILLS and REQUIREMENT_CONTRACT_OVERLAY:
        if "LOCAL_REQUIREMENT_CONTRACT_V1" not in result.upper():
            result = result.rstrip() + REQUIREMENT_CONTRACT_OVERLAY
    if skill_name in COMPETITION_RELEASE_SKILLS and COMPETITION_RELEASE_OVERLAY:
        if "LOCAL_COMPETITION_RELEASE_GATE_V1" not in result.upper():
            result = result.rstrip() + COMPETITION_RELEASE_OVERLAY
    return result


def normalize_base_url(value: str) -> str:
    value = (value or "").strip().rstrip("/")
    if not value:
        return USER_BASE_URL
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    path = (parsed.path or "").rstrip("/")
    for suffix in (
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/messages",
        "/messages",
        "/v1/responses",
        "/responses",
        "/v1",
    ):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")


def _chat_path(base_url: str):
    parsed = urlparse(normalize_base_url(base_url))
    scheme = parsed.scheme or "https"
    host = parsed.hostname or ""
    port = parsed.port or (443 if scheme == "https" else 80)
    prefix = (parsed.path or "").rstrip("/")
    path = f"{prefix}/v1/chat/completions" if prefix else "/v1/chat/completions"
    return scheme, host, port, path


def _call_openai_sync(
    base_url: str,
    api_key: str,
    model_id: str,
    prompt: str,
    timeout: int = 60,
) -> str:
    scheme, host, port, path = _chat_path(base_url)
    if not host:
        raise ValueError("API Base URL 格式错误")
    body = json.dumps(
        {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    kwargs: Dict[str, Any] = {"timeout": timeout}
    connection_type = http.client.HTTPConnection
    if scheme == "https":
        connection_type = http.client.HTTPSConnection
        kwargs["context"] = ssl.create_default_context()
    connection = connection_type(host, port, **kwargs)
    try:
        connection.request("POST", path, body=body, headers=headers)
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            raw = response.read().decode("utf-8", errors="replace")
            raise Exception(f"HTTP {response.status}: {raw[:1200]}")
        content_type = (response.getheader("Content-Type") or "").lower()
        if "text/event-stream" in content_type:
            parts = []
            while True:
                raw_line = response.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                text = (choices[0].get("delta") or {}).get("content")
                if isinstance(text, str):
                    parts.append(text)
            result = "".join(parts)
            if result.strip():
                return result
            raise Exception("流式响应未包含正文")
        raw = response.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        return payload["choices"][0]["message"]["content"]
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Workflow artifact and comp-code release guards (2026-08-14)
#
# Official workflow_engine is compiled.  Its old file-discovery path can append
# the whole workspace's untracked files to a step.  This runtime guard is
# intentionally independent of Git: it keeps only declared/generated artifacts
# and never lets inputs, caches, internal review traces or malformed comma-paths
# pollute a step's visible output list.
# ---------------------------------------------------------------------------
_ARTIFACT_GUARD_STARTED = False
_DENY_OUTPUT_PREFIXES = (
    "user_data/", "_internal_review/", "_references/", "_review",
    ".git/", "__pycache__/", "code/__pycache__/", "code/catboost_info/",
)
_CODE_ROOT_OUTPUTS = {
    "RESULTS.md", "CAPABILITY_AUDIT.md", "CAPABILITY_VERDICT.json",
    "DELIVERABLES.json", "SEMANTIC_REVIEW_TODO.md", "COMP_CODE_AUDIT.md",
    "COMP_CODE_RELEASE_GATE.json", "SYMBOL_CONTRACT.json",
    "SYMBOL_CONTRACT_GATE.json", "FORMULA_CODE_GATE.json",
    "MATH_RELEASE_GATE.json", "Q4_MAPPING_AUDIT.csv",
    "result_1_test_prediction.csv", "result_1_match_prediction.csv",
    "result_2_group_schedule.csv", "result_3_dynamic_strategy.csv",
    "result_4_schedule_comparison.csv",
}
_CODE_FILE_PREFIXES = ("code/",)
_CODE_FIGURE_OUTPUTS = {
    "figures/problem_1_results.json", "figures/problem_2_results.json",
    "figures/problem_3_results.json", "figures/problem_4_results.json",
    "figures/all_results.json", "figures/sensitivity_results.json",
}


def _clean_relpath(value: Any) -> str | None:
    """Return a safe workspace-relative artifact path, or None when excluded."""
    if not isinstance(value, str):
        return None
    path = value.replace("\\", "/").strip().lstrip("/")
    if not path or "\x00" in path or "," in path:
        return None
    if path.startswith("../") or "/../" in path or path.startswith("/"):
        return None
    low = path.lower()
    if any(low.startswith(p) for p in _DENY_OUTPUT_PREFIXES):
        return None
    if low.endswith((".pyc", ".pyo")):
        return None
    return path


def _sanitize_step_outputs(skill_name: str, raw: Any) -> list[str]:
    """Strip misclassified files; comp-code additionally uses a strict allowlist."""
    try:
        items = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except Exception:
        items = []
    result: list[str] = []
    for item in items:
        path = _clean_relpath(item)
        if not path:
            continue
        if skill_name == "comp-code":
            allowed = (
                path in _CODE_ROOT_OUTPUTS
                or path in _CODE_FIGURE_OUTPUTS
                or path.startswith(_CODE_FILE_PREFIXES)
                or (path.startswith("_tmp/") and path.endswith((".log", ".md", ".json")))
            )
            if not allowed:
                continue
        if path not in result:
            result.append(path)
    return result


async def _artifact_guard_loop() -> None:
    """Continuously normalize step state/output lists without moving user files."""
    while True:
        try:
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT s.id,s.skill_name,s.status,s.output_files,w.status,w.current_step "
                "FROM workflow_steps s JOIN workflows w ON w.id=s.workflow_id"
            ).fetchall()
            changed = 0
            for step_id, skill, step_status, output_files, wf_status, current_step in rows:
                clean = _sanitize_step_outputs(skill or "", output_files)
                try:
                    old = json.loads(output_files or "[]")
                except Exception:
                    old = []
                if clean != old:
                    cur.execute(
                        "UPDATE workflow_steps SET output_files=? WHERE id=?",
                        (json.dumps(clean, ensure_ascii=False), step_id),
                    )
                    changed += 1
                # The UI groups artifacts only for an active/completed step.  Keep
                # the database state in sync with a live runner's current_step.
                if wf_status == "running" and current_step == skill and step_status == "pending":
                    cur.execute(
                        "UPDATE workflow_steps SET status='running',"
                        "started_at=COALESCE(started_at,datetime('now')) WHERE id=?",
                        (step_id,),
                    )
                    changed += 1
            if changed:
                conn.commit()
                log.info("[artifact-guard] normalized %d workflow-step records", changed)
            conn.close()
        except Exception as exc:
            log.warning("[artifact-guard] scan failed: %s", exc)
        await asyncio.sleep(2)


MATH_CONTRACT_GUARD = r"""

## LOCAL MATHEMATICAL CONTRACT (mandatory, fail-closed)
This is a correctness condition, not a prose preference.

1. `comp-modeling` must create `SYMBOL_CONTRACT.json`. For every core objective,
   constraint, probability, normalization term and cross-question quantity,
   record: `math`, `code_var`, `unit`, `domain`, `aggregation`, `source`, and
   `consumers`. A solution-level quantity must also declare `solution_boundary`.
2. `comp-code` must keep the contract synchronized with final code and run:
   `python <MODEX_APP>/tools/math_release_gate.py --workspace .`.
3. A missing contract, missing code variable, invalid aggregation, formula-code
   REVIEW, or nonzero checker exit is BLOCK for mathematical release. Do not
   claim completion and do not let paper prose downgrade a computational error.
4. Preserve `SYMBOL_CONTRACT_GATE.json`, `FORMULA_CODE_GATE.json`, and
   `MATH_RELEASE_GATE.json` as audit evidence.
"""

COMP_CODE_RELEASE_GUARD = r"""

## LOCAL COMP-CODE RELEASE GATE (mandatory, fail-closed)
This is a release condition, not a writing suggestion.

1. Before claiming PASS/completion, create and run an independent audit script
   `code/constraint_audit.py` against final CSV/JSON outputs. It must recompute
   all implemented hard constraints from outputs, not inspect only solver state.
2. Run Python compilation, the audit script, the mathematical release gate, and
   `_utils/comp_code_release_gate.py`. Preserve actual stdout/stderr in `_tmp/`.
3. If an expected checker is missing, an audit script is missing, a required
   result file is absent, a check exits nonzero, or a formula/constraint cannot
   be independently tested, set the result to `REVIEW` or `BLOCK`. Never replace
   a missing audit with a file-exists check or write FINAL PASS.
4. Never use `git status`, a full workspace listing, or untracked files as a
   step deliverable list. Only register formal outputs declared in
   `DELIVERABLES.json`; inputs in `user_data/`, `_internal_review/`, caches and
   temporary working files are never deliverables.
5. For competition workflows, explicitly verify and report: information leakage
   boundaries, all stated hard constraints, independent static baseline,
   unit-consistent feedback ratios, output-row counts, and CSV/JSON agreement.
"""


def _ensure_comp_code_release_gate(cwd: Any) -> None:
    """Write a small fail-closed release checker into each workspace _utils/."""
    if not cwd:
        return
    try:
        root = Path(cwd)
        util = root / "_utils"
        util.mkdir(parents=True, exist_ok=True)
        gate = util / "comp_code_release_gate.py"
        source = r'''# Generated by Modex local runtime guard; deliverables come from DELIVERABLES.json.
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
core = [root/'code'/'main.py', root/'code'/'constraint_audit.py', root/'RESULTS.md', root/'DELIVERABLES.json']
missing = [str(p.relative_to(root)) for p in core if not p.is_file() or p.stat().st_size == 0]
if missing:
    print('COMP_CODE_RELEASE=BLOCK missing=' + ','.join(missing)); raise SystemExit(2)
try:
    manifest = json.loads((root/'DELIVERABLES.json').read_text(encoding='utf-8'))
    declared = []
    for item in manifest.get('deliverables', []):
        rel = str(item.get('path') or '').replace('\\','/').lstrip('./')
        if rel:
            declared.append(rel)
    absent = [rel for rel in declared if not (root/rel).is_file() or (root/rel).stat().st_size == 0]
    if absent:
        print('COMP_CODE_RELEASE=BLOCK missing_declared=' + ','.join(absent)); raise SystemExit(3)
except SystemExit: raise
except Exception as exc:
    print('COMP_CODE_RELEASE=BLOCK invalid_manifest=' + str(exc)); raise SystemExit(4)
py = sys.executable
py_files = sorted((root/'code').glob('*.py'))
compile_run = subprocess.run([py, '-m', 'py_compile', *map(str, py_files)], cwd=root, text=True, capture_output=True)
if compile_run.returncode:
    print('COMP_CODE_RELEASE=BLOCK py_compile'); print(compile_run.stdout + compile_run.stderr); raise SystemExit(5)
audit_run = subprocess.run([py, str(root/'code'/'constraint_audit.py')], cwd=root, text=True, capture_output=True)
print(audit_run.stdout + audit_run.stderr)
if audit_run.returncode or 'PASS=True' not in (audit_run.stdout or ''):
    print('COMP_CODE_RELEASE=BLOCK independent_audit'); raise SystemExit(6)
install_root = Path(sys.executable).resolve().parents[2]
math_gate = install_root/'resources'/'app'/'tools'/'math_release_gate.py'
if math_gate.is_file():
    math_run = subprocess.run([py, str(math_gate), '--workspace', str(root)], cwd=root, text=True, capture_output=True)
    print(math_run.stdout + math_run.stderr)
    if math_run.returncode:
        print('COMP_CODE_RELEASE=BLOCK mathematical_release'); raise SystemExit(8)
print('COMP_CODE_RELEASE=PASS')
'''
        if not gate.exists() or gate.read_text(encoding="utf-8") != source:
            gate.write_text(source, encoding="utf-8")
    except Exception as exc:
        log.warning("[comp-code-guard] release gate injection failed: %s", exc)


def install() -> bool:
    global _PATCHED
    if _PATCHED:
        return True

    try:
        from services import claude_runner as runner
        from services import llm_client
        from services import state_store as store
        from routers import settings as settings_router
        from routers import checkpoints as checkpoints_router
    except Exception as exc:
        log.warning("[local-api] patch import failed: %s", exc)
        return False

    original_get = store.get_all_settings
    original_save = store.save_settings
    original_get_workflows_to_resume = store.get_workflows_to_resume
    original_spawn = runner.asyncio.create_subprocess_exec
    original_load_skill_prompt = runner._load_skill_prompt
    # Compiled Modex resume/start may leave workflow.status=running while
    # current_step is NULL. Keep the original runner and repair that missing
    # cursor immediately before it selects the next step.
    try:
        from services import workflow_engine as workflow_engine
        from routers import workflows as workflows_router
        original_run_workflow = workflow_engine.run_workflow
        original_wait_checkpoint = workflow_engine.wait_checkpoint
    except Exception:
        workflow_engine = None
        workflows_router = None
        checkpoints_router = None
        original_run_workflow = None
        original_wait_checkpoint = None

    _DIAG_PATH = Path(r"C:\Users\27631\Desktop\OH-WorkSpace\_tmp_modex_patch_diag.log")
    def _diag_log(tag, msg):
        try:
            with open(_DIAG_PATH, "a", encoding="utf-8") as f:
                import datetime
                f.write(f"{datetime.datetime.now().isoformat()} [{tag}] {msg}\n")
        except Exception:
            pass

    def _disable_mode_a_checkpoint_overlay():
        """Return checkpoints to the official in-memory wait_checkpoint protocol.

        The local SQLite trigger/pending-row overlay raced the compiled engine:
        completed steps were flipped back to waiting_checkpoint, popups were
        rebroadcast, and resume forced waiting steps back to running. Keep the
        official 10-minute in-memory gate; drop the overlay on every boot.
        """
        try:
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            cur = conn.cursor()
            cur.execute("DROP TRIGGER IF EXISTS mode_a_checkpoint_after_completion")
            cur.execute(
                "UPDATE checkpoints SET status='resolved', resolved_at=datetime('now'), "
                "response='{\"action\":\"approve\",\"source\":\"official_checkpoint_protocol\"}' "
                "WHERE status='pending'"
            )
            cur.execute(
                "UPDATE workflow_steps SET status='completed' "
                "WHERE status='waiting_checkpoint'"
            )
            conn.commit()
            conn.close()
            log.info("[checkpoint] Mode-A overlay disabled; official in-memory gates restored")
        except Exception as exc:
            log.warning("[checkpoint] failed to disable Mode-A overlay: %s", exc)

    _disable_mode_a_checkpoint_overlay()

    async def _mode_a_current_checkpoint(wf_id: str):
        """SQLite-backed current gate; survives restart and compiled-engine loss."""
        conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
        try:
            row = conn.execute(
                "SELECT id,step_name,checkpoint_type,data,created_at FROM checkpoints "
                "WHERE workflow_id=? AND status='pending' ORDER BY id DESC LIMIT 1", (wf_id,)
            ).fetchone()
            if not row:
                return {"active": False}
            data = json.loads(row[3] or "{}")
            return {"active": True, "checkpoint": {
                "id": row[0], "workflow_id": wf_id, "step_name": row[1],
                "checkpoint_type": row[2], "data": data, "status": "pending",
                "created_at": row[4],
            }}
        finally:
            conn.close()

    def _persist_checkpoint_feedback(wf_id: str, step_name: str, text: str) -> None:
        """Write the user's review comments into the workspace for the rerun.

        The executor reads _tmp/CHECKPOINT_FEEDBACK.md on every spawn (see
        _ensure_claude_md_tool_hints), so a feedback-driven rerun of the same
        step actually sees the requested changes. The file is removed on
        approve so it never leaks into later steps.
        """
        try:
            import datetime as _dt
            ws_dir = Path.home() / "AppData" / "Roaming" / "MHAgent" / "workspaces" / wf_id
            tmp_dir = ws_dir / "_tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            (tmp_dir / "CHECKPOINT_FEEDBACK.md").write_text(
                f"# 用户核验意见（{step_name}，{_dt.datetime.now().isoformat(timespec='minutes')}）\n\n{text}\n",
                encoding="utf-8",
            )
            log.info("[mode-a] checkpoint feedback persisted for %s step=%s", wf_id, step_name)
        except Exception as exc:
            log.warning("[mode-a] feedback persist failed for %s: %s", wf_id, exc)

    def _drop_checkpoint_feedback(wf_id: str) -> None:
        try:
            fb = Path.home() / "AppData" / "Roaming" / "MHAgent" / "workspaces" / wf_id / "_tmp" / "CHECKPOINT_FEEDBACK.md"
            if fb.exists():
                fb.unlink()
        except Exception:
            pass

    _MAJOR_BACKFLOW_MAX_ROUNDS = 3
    _REVIEW_REPAIR_SEQUENCE = [
        "comp-prob-analysis",
        "comp-modeling",
        "comp-code",
    ]
    _REVIEW_SKIP_AFTER_FIGURES = {"comp-review", "comp-review-en"}
    _seen_review_verdicts: dict = {}

    def _major_review_backflow_plan(wf_id: str, step_name: str):
        """Build a repair loop from COMP_REVIEW_VERDICT.json.

        User rule: edit PROBLEM_ANALYSIS.md and MODELING_REPORT.md, rerun
        code/data, then patch only the affected figure data. Do not rerun the
        full paper-figure step. Skip a second review afterwards. Every finding
        is in scope: fatal, major, and minor. Do not rewind the paper.
        """
        if step_name != "comp-review":
            return None
        try:
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            row = conn.execute(
                "SELECT workspace_dir FROM workflows WHERE id=?", (wf_id,)
            ).fetchone()
            conn.close()
            root = Path(row[0]) if row and row[0] else (
                Path.home() / "AppData" / "Roaming" / "MHAgent" / "workspaces" / wf_id
            )
            verdict_path = root / "COMP_REVIEW_VERDICT.json"
            if not verdict_path.is_file():
                return None
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
            findings = list(verdict.get("findings") or [])
            if not findings:
                return None
            target = "comp-prob-analysis"
            counts = {}
            for item in findings:
                sev = str(item.get("severity") or "unspecified").lower() or "unspecified"
                counts[sev] = counts.get(sev, 0) + 1
            state_path = root / "_tmp" / "MAJOR_REVIEW_BACKFLOW.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state = {}
            if state_path.is_file():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                except Exception:
                    state = {}
            round_no = int(state.get("round", 0)) + 1
            fingerprint = hashlib.sha256(
                json.dumps(findings, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:16]
            feedback_lines = [
                "# 逻辑对抗复核修复（必须改问题分析与建模，再重跑数据与图）",
                f"来源：COMP_REVIEW_VERDICT.json；回流轮次：{round_no}",
                f"问题计数：{json.dumps(counts, ensure_ascii=False)}；合计 {len(findings)} 条。",
                "",
                "执行顺序（不要整段回退，不要重写论文，不要整步重跑画图）：",
                "1. 只修改 PROBLEM_ANALYSIS.md（赛题分析）",
                "2. 只修改 MODELING_REPORT.md（建模求解）",
                "3. 按修改后的分析/建模重跑代码与数据",
                "4. 只更新需要修改的图的数据源/脚本输入，保留原图构图与文件名；禁止重跑 paper-figure 完整步骤",
                "5. 数据补丁完成后跳过第二次逻辑复核，进入论文撰写",
                "",
                "fatal / major / minor 全部要修，禁止只改论文措辞来降级问题。",
            ]
            for idx, item in enumerate(findings, 1):
                feedback_lines.append(
                    f"{idx}. [{item.get('severity', '?')}/{item.get('category', 'finding')}] {item.get('where', 'unknown')}\n"
                    f"   证据：{item.get('evidence', '')}\n"
                    f"   修复要求：{item.get('fix', '')}"
                )
            feedback = "\n".join(feedback_lines) + "\n"
            state_path.write_text(
                json.dumps({
                    "round": round_no,
                    "mode": "analysis_model_data_then_figure_data_patch",
                    "target_stage": target,
                    "sequence": list(_REVIEW_REPAIR_SEQUENCE),
                    "finding_fingerprint": fingerprint,
                    "finding_count": len(findings),
                    "severity_counts": counts,
                    "status": "planned" if round_no <= _MAJOR_BACKFLOW_MAX_ROUNDS else "blocked",
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if round_no > _MAJOR_BACKFLOW_MAX_ROUNDS:
                (root / "_tmp" / "MAJOR_REVIEW_BLOCKED.md").write_text(
                    feedback + f"\n已达到 {_MAJOR_BACKFLOW_MAX_ROUNDS} 次自动回流上限；工作流保持阻断，需人工处理后再启动。\n",
                    encoding="utf-8",
                )
                return {"blocked": True, "root": root, "feedback": feedback, "round": round_no, "finding_count": len(findings)}
            (root / "_tmp" / "MAJOR_REVIEW_FEEDBACK.md").write_text(feedback, encoding="utf-8")
            _persist_checkpoint_feedback(wf_id, target, feedback)
            return {
                "blocked": False,
                "root": root,
                "target": target,
                "sequence": list(_REVIEW_REPAIR_SEQUENCE),
                "feedback": feedback,
                "round": round_no,
                "finding_count": len(findings),
                "finding_fingerprint": fingerprint,
            }
        except Exception as exc:
            log.warning("[major-backflow] plan failed for %s: %s", wf_id, exc)
            return None

    async def _cancel_live_workflow_task(wf_id: str) -> bool:
        """Stop the compiled main loop before a major backflow restart."""
        if workflows_router is None:
            return False
        try:
            tasks = getattr(workflows_router, "_tasks", {})
            task = tasks.get(wf_id) if isinstance(tasks, dict) else None
            current = asyncio.current_task()
            if task is not None and task is not current and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    log.info("[major-backflow] old workflow task stopped with %s", exc)
                _diag_log("MAJOR_BACKFLOW_CANCELLED", wf_id)
                return True
            if isinstance(tasks, dict):
                tasks.pop(wf_id, None)
        except Exception as exc:
            log.warning("[major-backflow] cancel old task failed for %s: %s", wf_id, exc)
        return False

    def _available_repair_steps(wf_id: str):
        conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
        try:
            rows = conn.execute(
                "SELECT skill_name FROM workflow_steps WHERE workflow_id=? ORDER BY step_order",
                (wf_id,),
            ).fetchall()
        finally:
            conn.close()
        present = {row[0] for row in rows}
        return [name for name in _REVIEW_REPAIR_SEQUENCE if name in present]

    def _prepare_review_repair_steps(wf_id: str, sequence):
        """Mark only the repair sequence pending; keep later paper/compile intact."""
        conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
        try:
            names = tuple(sequence)
            if not names:
                return None
            placeholders = ",".join("?" * len(names))
            conn.execute(
                f"UPDATE workflow_steps SET status='pending',started_at=NULL,completed_at=NULL,"
                "error_message=NULL,model_used=NULL "
                f"WHERE workflow_id=? AND skill_name IN ({placeholders})",
                (wf_id, *names),
            )
            conn.execute(
                "UPDATE workflow_steps SET status='running',started_at=datetime('now') "
                "WHERE workflow_id=? AND skill_name=?",
                (wf_id, names[0]),
            )
            conn.execute(
                "UPDATE workflows SET status='running',current_step=?,updated_at=datetime('now') WHERE id=?",
                (names[0], wf_id),
            )
            conn.commit()
            return names[0]
        finally:
            conn.close()

    def _skip_review_after_figures(wf_id: str) -> None:
        conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
        try:
            conn.execute(
                "UPDATE workflow_steps SET status='skipped',completed_at=datetime('now'),"
                "error_message='skipped after review-driven data/figure patch' "
                "WHERE workflow_id=? AND skill_name IN ('comp-review','comp-review-en') "
                "AND status IN ('pending','running')",
                (wf_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def _write_figure_data_patch_brief(wf_id: str, root: Path, feedback: str) -> None:
        """Tell the next executor to patch figure data only, never rerun paper-figure."""
        tmp_dir = Path(root) / "_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        brief = (
            "# 图表数据补丁（禁止整步重跑 paper-figure）\n\n"
            "只更新因复核修复而过时的图数据：JSON/CSV 输入、gen_fig_*.py 读入的结果文件。\n"
            "保留原图构图、配色、文件名和未受影响的图。需要重绘时，只重跑对应 gen_fig 脚本。\n"
            "不要启动 paper-figure / paper-figure-html 完整步骤，不要重新规划图清单。\n\n"
            + feedback
        )
        (tmp_dir / "FIGURE_DATA_PATCH.md").write_text(brief, encoding="utf-8")
        _persist_checkpoint_feedback(wf_id, "figure-data-patch", brief)

    def _next_step_after_repair(wf_id: str):
        conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
        try:
            row = conn.execute(
                "SELECT skill_name FROM workflow_steps WHERE workflow_id=? "
                "AND status='pending' AND skill_name NOT IN ('comp-review','comp-review-en') "
                "ORDER BY step_order LIMIT 1",
                (wf_id,),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    async def _run_review_repair_loop(wf_id: str, sequence, plan=None) -> None:
        """Run analysis → modeling → code/data, patch figure data, skip review."""
        if workflows_router is None:
            return
        run_step = getattr(workflow_engine, "run_single_step", None) if workflow_engine is not None else None
        _prepare_review_repair_steps(wf_id, sequence)
        for skill in sequence:
            _diag_log("REVIEW_REPAIR_STEP", f"{wf_id} {skill}")
            try:
                if run_step is not None:
                    await run_step(wf_id, skill)
                else:
                    await workflows_router.rerun_step(wf_id, skill)
            except Exception as trans:
                log.warning("[review-repair] step %s failed for %s: %s", skill, wf_id, trans)
                _diag_log("REVIEW_REPAIR_STEP_ERR", f"{wf_id} {skill} {trans}")
                return
        root = (plan or {}).get("root")
        feedback = (plan or {}).get("feedback") or ""
        if root:
            _write_figure_data_patch_brief(wf_id, Path(root), feedback)
            _diag_log("REVIEW_FIGURE_DATA_PATCH", wf_id)
        _skip_review_after_figures(wf_id)
        nxt = _next_step_after_repair(wf_id)
        _drop_checkpoint_feedback(wf_id)
        if nxt:
            _diag_log("REVIEW_REPAIR_CONTINUE", f"{wf_id} next={nxt}")
            try:
                conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
                conn.execute(
                    "UPDATE workflows SET status='running',current_step=?,updated_at=datetime('now') WHERE id=?",
                    (nxt, wf_id),
                )
                conn.commit()
                conn.close()
                await workflows_router.run_workflow(wf_id)
            except Exception as exc:
                log.warning("[review-repair] continue to %s failed for %s: %s", nxt, wf_id, exc)
        else:
            _diag_log("REVIEW_REPAIR_DONE", wf_id)

    async def _maybe_start_review_repair(wf_id: str, step_name: str) -> bool:
        if step_name != "comp-review":
            return False
        conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
        try:
            later = conn.execute(
                "SELECT skill_name, status FROM workflow_steps WHERE workflow_id=? "
                "AND skill_name IN ('comp-paper-zh','comp-paper-zh-docx','comp-compile-zh','comp-paper-en')",
                (wf_id,),
            ).fetchall()
        finally:
            conn.close()
        if any(status in ("completed", "running") for _, status in later):
            _diag_log("REVIEW_REPAIR_SKIP_PAPER_DONE", wf_id)
            return False
        plan = _major_review_backflow_plan(wf_id, step_name)
        if not plan:
            return False
        fingerprint = plan.get("finding_fingerprint") or ""
        if _seen_review_verdicts.get(wf_id) == fingerprint:
            return False
        _seen_review_verdicts[wf_id] = fingerprint
        if plan.get("blocked"):
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            conn.execute(
                "UPDATE workflows SET status='blocked',updated_at=datetime('now') WHERE id=?",
                (wf_id,),
            )
            conn.commit()
            conn.close()
            _diag_log("REVIEW_REPAIR_BLOCKED", wf_id)
            return True
        await _cancel_live_workflow_task(wf_id)
        sequence = plan.get("sequence") or _available_repair_steps(wf_id)
        asyncio.create_task(_run_review_repair_loop(wf_id, sequence, plan))
        _diag_log("REVIEW_REPAIR_STARTED", f"{wf_id} n={plan.get('finding_count')}")
        return True

    async def _mode_a_resolve_checkpoint(wf_id: str, response: dict):
        """Resolve a gate; major COMP_REVIEW findings route back to their source stage."""
        action = getattr(response, "action", None) or (response or {}).get("action")
        data = getattr(response, "data", None) if not isinstance(response, dict) else response.get("data", {})
        if action not in ("approve", "continue", "submit", "feedback"):
            return {"status": "ignored", "detail": "unsupported checkpoint action"}
        feedback_text = ""
        if isinstance(data, dict):
            feedback_text = str(data.get("feedback") or data.get("message") or "").strip()
        major_plan = None
        conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
        try:
            row = conn.execute(
                "SELECT id,step_name FROM checkpoints WHERE workflow_id=? AND status='pending' "
                "ORDER BY id DESC LIMIT 1", (wf_id,)
            ).fetchone()
            step_name = row[1] if row else None
            if not step_name:
                # 引擎内存态 checkpoint 但 SQLite 无行（旧版遗留）：按当前步骤兜底，
                # 否则弹窗永远无法闭合。
                cur_row = conn.execute(
                    "SELECT current_step FROM workflows WHERE id=?", (wf_id,)
                ).fetchone()
                step_name = cur_row[0] if cur_row else None
            if not step_name:
                return {"status": "no_pending_checkpoint"}
            # A review approval is itself a release decision. Major findings
            # must go back to the earliest producing stage instead of being
            # downgraded into prose-only feedback.
            if action in ("approve", "continue", "submit") and step_name == "comp-review":
                # Official competition templates have no review checkpoint.
                # Repair is started from step completion, not from this popup.
                major_plan = None
            if row:
                conn.execute(
                    "UPDATE checkpoints SET status='resolved',response=?,resolved_at=datetime('now') WHERE id=?",
                    (json.dumps({"action": action, "data": data or {}}, ensure_ascii=False), row[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO checkpoints(workflow_id,step_name,checkpoint_type,data,status,response,resolved_at) "
                    "VALUES(?,?,?,?, 'resolved',?, datetime('now'))",
                    (wf_id, step_name, "approve",
                     '{"policy":"mode_a","auto_created":true}',
                     json.dumps({"action": action, "data": data or {}}, ensure_ascii=False)),
                )
            if major_plan and major_plan.get("target"):
                target = major_plan["target"]
                target_order = conn.execute(
                    "SELECT step_order FROM workflow_steps WHERE workflow_id=? AND skill_name=?",
                    (wf_id, target),
                ).fetchone()
                if not target_order:
                    return {"status": "major_backflow_target_missing", "target": target}
                # Preserve earlier evidence, but invalidate the affected stage,
                # its downstream artifacts, and their checkpoints. The next
                # run must regenerate code/results/figures/paper from the fix.
                conn.execute(
                    "UPDATE workflow_steps SET status='pending',started_at=NULL,completed_at=NULL,"
                    "error_message=NULL,model_used=NULL,output_files='[]' "
                    "WHERE workflow_id=? AND step_order>=?",
                    (wf_id, target_order[0]),
                )
                conn.execute(
                    "DELETE FROM checkpoints WHERE workflow_id=? AND step_name IN ("
                    "SELECT skill_name FROM workflow_steps WHERE workflow_id=? AND step_order>=?)",
                    (wf_id, wf_id, target_order[0]),
                )
                conn.execute(
                    "UPDATE workflow_steps SET status='running',started_at=COALESCE(started_at,datetime('now')) "
                    "WHERE workflow_id=? AND skill_name=?",
                    (wf_id, target),
                )
                conn.execute(
                    "UPDATE workflows SET status='running',current_step=?,updated_at=datetime('now') WHERE id=?",
                    (target, wf_id),
                )
                rerun_mode = "major_backflow"
            elif action == "feedback":
                if feedback_text:
                    _persist_checkpoint_feedback(wf_id, step_name, feedback_text)
                conn.execute(
                    "UPDATE workflows SET status='running',current_step=?,updated_at=datetime('now') WHERE id=?",
                    (step_name, wf_id),
                )
                target = step_name
                rerun_mode = "rerun"
            else:
                _drop_checkpoint_feedback(wf_id)
                conn.execute(
                    "UPDATE workflows SET status='running',current_step=?,updated_at=datetime('now') WHERE id=?",
                    (step_name, wf_id),
                )
                conn.execute(
                    "UPDATE workflow_steps SET status='completed' "
                    "WHERE workflow_id=? AND skill_name=? AND status='waiting_checkpoint'",
                    (wf_id, step_name),
                )
                target = None
                rerun_mode = "mainloop"
            conn.commit()
        finally:
            conn.close()
        # 普通 checkpoint 继续走编译引擎协议。major 回流必须先停掉旧主循环，
        # 再从目标阶段重新启动，不能唤醒旧循环让它按原顺序继续。
        engine_waiting = False
        if major_plan and major_plan.get("target"):
            await _cancel_live_workflow_task(wf_id)
            try:
                if workflow_engine is not None:
                    workflow_engine._checkpoint_events.pop(wf_id, None)
                    workflow_engine._checkpoint_responses.pop(wf_id, None)
            except Exception as exc:
                log.info("[major-backflow] clear engine checkpoint state failed: %s", exc)
        else:
            try:
                ev = workflow_engine._checkpoint_events.get(wf_id)
                if ev is not None and not ev.is_set():
                    ev.set()
                    workflow_engine._checkpoint_responses[wf_id] = {"action": action, "data": data or {}}
                    engine_waiting = True
                    _diag_log("CHECKPOINT_ENGINE_WOKE", f"{wf_id} action={action}")
            except Exception as exc:
                log.warning("[mode-a] engine wake failed for %s: %s", wf_id, exc)
        if engine_waiting:
            return {"status": "resolved_engine", "next_step": None}
        if workflows_router is None:
            return {"status": "resolved", "next_step": None}
        if rerun_mode in ("rerun", "major_backflow") and target:
            # 普通 feedback 重跑当前步骤；major 回流从最早受影响阶段开始，
            # 并由主循环继续执行其全部下游步骤。
            try:
                if rerun_mode == "rerun":
                    await workflows_router.rerun_step(wf_id, target)
                else:
                    await workflows_router.run_workflow(wf_id)
            except Exception as exc:
                log.warning("[mode-a] %s dispatch failed for %s/%s: %s", rerun_mode, wf_id, target, exc)
            return {"status": "resolved_and_started", "next_step": target, "major_backflow": rerun_mode == "major_backflow"}
        # approve 且引擎主循环不在 → run_workflow 连续推进到下一个 checkpoint
        try:
            await workflows_router.run_workflow(wf_id)
        except Exception as exc:
            log.warning("[mode-a] mainloop dispatch failed for %s: %s", wf_id, exc)
        return {"status": "resolved_and_started", "next_step": None}

    def _patch_checkpoint_routes():
        # Official protocol: leave compiled /checkpoints/current and
        # /checkpoints/resolve on the in-memory wait_checkpoint event.
        # The SQLite-backed Mode-A overlay raced that waiter and reopened popups.
        _diag_log("CP_ROUTES_OFFICIAL", "kept compiled checkpoint routes")
        log.info("[checkpoint] official in-memory resolve routes kept")

    _patch_checkpoint_routes()

    def patched_get_workflows_to_resume():
        """Never auto-resume a workflow while a persisted Mode-A gate is pending."""
        workflow_ids = original_get_workflows_to_resume()
        try:
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            blocked = {
                row[0] for row in conn.execute(
                    "SELECT DISTINCT workflow_id FROM checkpoints WHERE status='pending'"
                ).fetchall()
            }
            conn.close()
            allowed = [wf_id for wf_id in workflow_ids if wf_id not in blocked]
            skipped = set(workflow_ids) - set(allowed)
            if skipped:
                log.info("[mode-a] skipped auto-resume for pending checkpoints: %s", sorted(skipped))
            return allowed
        except Exception as exc:
            log.warning("[mode-a] resume filter failed: %s", exc)
            return workflow_ids

    async def patched_get_all_settings():
        values = dict(await original_get())
        # 0) 预设 base_url 应用：角色选中某预设且该预设定义了 base_url → 用预设的
        #    （2026-08-13：sol 预设 gpt-5.6-sol 走 ergouzi 中转站 api.ergouzi.life）
        try:
            preset_base_urls = _load_preset_base_urls()
            for role_key in ("executor", "reviewer", "editor_ai"):
                preset_id = (values.get(f"{role_key}_preset_id") or "").strip()
                pbase = preset_base_urls.get(preset_id)
                if pbase:
                    values[f"{role_key}_base_url"] = pbase
        except Exception as exc:
            log.warning("[local-api] preset base_url apply failed: %s", exc)
        # 1) 官方残留（mhcoding 等）按角色纠正到基线；
        # 2) 显式配置保留；空值 fallback ergouzi。
        for key in BASE_URL_KEYS:
            current = (values.get(key) or "").strip()
            current = _correct_base_url(key, current)
            if not current:
                current = IMAGE_BASE_URL if key == "gpt_image_base_url" else TEXT_BASE_URL
            values[key] = current
        return values

    async def patched_save_settings(data: Dict[str, str]):
        values = dict(data or {})
        for key in BASE_URL_KEYS:
            if key in values:
                values[key] = _correct_base_url(key, normalize_base_url(values[key]))
        await original_save(values)

    async def patched_call_llm(agent: str, prompt: str, timeout: int = 60) -> str:
        keys = AGENT_KEYS.get(agent)
        if not keys:
            raise ValueError(f"未知 agent: {agent}")
        values = await patched_get_all_settings()
        api_key = (values.get(keys["api_key"]) or "").strip()
        base_url = normalize_base_url(values.get(keys["base_url"]) or "")
        model_id = (values.get(keys["model_id"]) or "gpt-5.6-sol").strip()
        if not api_key:
            raise ValueError(f"未配置 {agent} 的 API Key")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            _call_openai_sync,
            base_url,
            api_key,
            model_id,
            prompt,
            timeout,
        )

    async def patched_test_connection(agent: str) -> Dict[str, object]:
        try:
            reply = await patched_call_llm(agent, "Reply with Hello only.", timeout=60)
            return {"ok": True, "message": (reply or "OK")[:200], "agent": agent}
        except Exception as exc:
            return {"ok": False, "message": str(exc), "agent": agent}

    def patched_load_skill_prompt(
        skill_name: str,
        arguments: str,
        extra_params: Dict[str, Any] | None = None,
    ) -> str:
        """Preserve official prompts, then append the compact global figure master.

        Figure work needs a stable instruction channel, but large workspace
        CLAUDE.md injections caused prompt bloat and project-file pollution.
        The compact overlay is appended only to figure skills here.
        """
        prompt = original_load_skill_prompt(skill_name, arguments, extra_params)
        if skill_name in FIGURE_HINT_SKILLS and FIGURE_QUALITY_OVERLAY:
            marker = "MODEX GLOBAL FIGURE MASTER V3"
            # The figure lifecycle may already have delivered the same compact
            # master through arguments. Avoid duplicating it in the prompt.
            if marker not in prompt and marker not in (arguments or ""):
                prompt = prompt.rstrip() + "\n\n" + FIGURE_QUALITY_OVERLAY.strip() + "\n"
        return prompt

    async def patched_spawn(*args: Any, **kwargs: Any):
        env = kwargs.get("env")
        try:
            command = " ".join(str(item) for item in args[:3]).lower()
            if isinstance(env, dict) and "claude" in command:
                values = await patched_get_all_settings()
                # 按命令行 --model 反查预设：步骤级模型与预设身份对齐。
                # 预设自带 base_url+api_key，模型匹配时用预设自身的配置，
                # 避免“步骤选了 sol 模型、运行时却拿全局 deepseek 配置”的错配。
                cli_model = ""
                raw_args = [str(a) for a in args]
                for idx, a in enumerate(raw_args):
                    if a == "--model" and idx + 1 < len(raw_args):
                        cli_model = raw_args[idx + 1].strip()
                        break
                preset_full = _load_preset_full()
                preset_entry = None
                if cli_model:
                    pid = preset_full["by_model"].get(cli_model)
                    if pid:
                        preset_entry = preset_full["presets"].get(pid)
                # 找不到预设时回退全局设置（保持旧行为）
                api_key = (values.get("executor_api_key") or "").strip()
                model = (values.get("executor_model_id") or "").strip()
                executor_base = normalize_base_url(values.get("executor_base_url", ""))
                if preset_entry:
                    api_key = preset_entry["api_key"] or api_key
                    model = preset_entry["model_id"] or model
                    executor_base = preset_entry["base_url"] or executor_base
                    log.info(
                        "[preset-identity] spawn --model=%s -> preset %s (base=%s)",
                        cli_model, preset_entry["id"], executor_base,
                    )
                reviewer_key = (values.get("reviewer_api_key") or "").strip()
                reviewer_base = normalize_base_url(
                    values.get("reviewer_base_url") or executor_base
                )
                reviewer_model = (values.get("reviewer_model_id") or model).strip()
                editor_key = (values.get("editor_ai_api_key") or "").strip()
                editor_base = normalize_base_url(
                    values.get("editor_ai_base_url") or executor_base
                )
                editor_model = (values.get("editor_ai_model_id") or model).strip()
                image_base = normalize_base_url(
                    values.get("gpt_image_base_url") or executor_base
                )
                image_key = (values.get("gpt_image_api_key") or api_key).strip()
                if api_key:
                    env["ANTHROPIC_API_KEY"] = api_key
                    env.pop("ANTHROPIC_AUTH_TOKEN", None)
                # Claude Code / Anthropic protocol. DeepSeek exposes an Anthropic
                # endpoint under /anthropic while its OpenAI-compatible root lives
                # at the plain base. When the executor targets DeepSeek, point
                # ANTHROPIC_BASE_URL at the /anthropic subtree so /v1/messages is
                # resolved, not the OpenAI root (which returns 404 for model).
                # Claude Code speaks Anthropic Messages. OpenRouter and grok
                # presets speak OpenAI Chat Completions, so route them through
                # the local bridge in this final (last-installed) spawn patch.
                if (
                    str(model).lower().startswith("grok")
                    or executor_base.lower().startswith("https://openrouter.ai")
                ):
                    env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:18189"
                    env["ANTHROPIC_API_KEY"] = "bridge-local-key"
                    env.pop("ANTHROPIC_AUTH_TOKEN", None)
                    log.info("[preset-identity] OpenAI-compatible model routed via local bridge model=%s base=%s", model, executor_base)
                else:
                    env["ANTHROPIC_BASE_URL"] = executor_base + (
                        "/anthropic"
                        if executor_base.rstrip("/").endswith("api.deepseek.com")
                        and "/anthropic" not in executor_base
                        else ""
                    )
                if reviewer_key:
                    env["OPENAI_API_KEY"] = reviewer_key
                env["OPENAI_BASE_URL"] = reviewer_base
                if reviewer_model:
                    env["REVIEWER_MODEL_ID"] = reviewer_model
                env["REVIEWER_SCRIPT"] = str(REVIEWER_SCRIPT)
                if editor_key:
                    env["EDITOR_AI_API_KEY"] = editor_key
                env["EDITOR_AI_BASE_URL"] = editor_base
                if editor_model:
                    env["EDITOR_AI_MODEL_ID"] = editor_model
                if image_key:
                    env["GPT_IMAGE_API_KEY"] = image_key
                env["GPT_IMAGE_BASE_URL"] = image_base
                env["GPT_IMAGE_BACKEND"] = "images"
                env["GPT_IMAGE_MODEL"] = "gpt-image-2"
                # 纠正工作区 _utils/_gpt_image_config.json：官方写入逻辑可能把
                # base_url 回退为 mhcoding（键端错配：ergouzi key + mhcoding url），
                # 导致 GPT 作图全部失败。每次 claude 子进程启动时按 SQLite 纠正。
                try:
                    cwd = kwargs.get("cwd")
                    if cwd:
                        # Executor reads CLAUDE.md reliably; inject only the short,
                        # idempotent mathematical contract and the validated local
                        # release checker. This avoids changing the compiled engine.
                        # Keep project instructions and local helpers untouched.
                        # Figure rules arrive through the compact runner prompt;
                        # only explicit checkpoint feedback may be materialized.
                        _inject_checkpoint_feedback(cwd)
                        _ensure_comp_code_release_gate(cwd)
                        cfg_path = Path(cwd) / "_utils" / "_gpt_image_config.json"
                        if cfg_path.exists():
                            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                            cfg_base = str(cfg.get("base_url", "") or "")
                            if "mhcoding" in cfg_base:
                                cfg["base_url"] = image_base
                                if image_key:
                                    cfg["api_key"] = image_key
                                cfg_path.write_text(
                                    json.dumps(cfg, ensure_ascii=False, indent=2),
                                    encoding="utf-8",
                                )
                                log.info(
                                    "[local-api] corrected %s base_url to %s",
                                    cfg_path,
                                    image_base,
                                )
                except Exception as exc:
                    log.warning("[local-api] gpt_image_config fix failed: %s", exc)
                env["CLAUDE_CODE_SIMPLE"] = "1"
                if model:
                    env["ANTHROPIC_MODEL"] = model
                    env["ANTHROPIC_SMALL_FAST_MODEL"] = model
                arg_list = list(args)
                if "--bare" not in arg_list:
                    arg_list.insert(1, "--bare")
                    args = tuple(arg_list)
        except Exception as exc:
            log.warning("[local-api] subprocess env patch failed: %s", exc)
        try:
            proc = await original_spawn(*args, **kwargs)
        except Exception as exc:
            _diag_log(
                "CLAUDE_SPAWN_ERROR",
                f"type={type(exc).__name__} error={str(exc)[:500]} cwd={kwargs.get('cwd')}"
            )
            raise
        # Do not consume stdout/stderr here: the official runner owns those
        # pipes.  A wait watcher still records the decisive return code, which
        # was previously lost and left workflow_steps stuck at running.
        try:
            _diag_log(
                "CLAUDE_SPAWNED",
                f"pid={getattr(proc, 'pid', None)} cwd={kwargs.get('cwd')} "
                f"model={env.get('ANTHROPIC_MODEL') if isinstance(env, dict) else ''} "
                f"base={env.get('ANTHROPIC_BASE_URL') if isinstance(env, dict) else ''}"
            )
            async def _watch_claude_exit():
                try:
                    rc = await proc.wait()
                    _diag_log("CLAUDE_EXIT", f"pid={getattr(proc, 'pid', None)} returncode={rc}")
                except Exception as watch_exc:
                    _diag_log("CLAUDE_WAIT_ERROR", f"pid={getattr(proc, 'pid', None)} error={watch_exc}")
            asyncio.create_task(_watch_claude_exit())
        except Exception as exc:
            _diag_log("CLAUDE_WATCH_INSTALL_ERROR", str(exc)[:500])
        return proc

    async def patched_wait_checkpoint(workflow_id: str, timeout: int = 600):
        """Skip the official in-memory gate when the workflow opted out.

        enable_checkpoints=0 -> auto-approve and continue. Otherwise hand the
        wait straight to the compiled engine; do not persist a SQLite pending
        row, or the overlay and the engine will race the same popup.
        """
        if original_wait_checkpoint is None:
            raise RuntimeError("checkpoint waiter unavailable")
        try:
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            enabled = conn.execute(
                "SELECT COALESCE(enable_checkpoints,0) FROM workflows WHERE id=?",
                (workflow_id,),
            ).fetchone()
            conn.close()
            if not enabled or not enabled[0]:
                return {"action": "approve", "skipped": True, "reason": "checkpoints_disabled"}
        except Exception as exc:
            log.warning("[checkpoint] skip-check failed for %s: %s", workflow_id, exc)
        return await original_wait_checkpoint(workflow_id, timeout)

    async def patched_run_workflow(workflow_id: str):
        """Repair compiled runner's empty-current-step resume state, then run."""
        _diag_log("RUN_WORKFLOW_CALLED", workflow_id)
        if original_run_workflow is None:
            _diag_log("RUN_WORKFLOW_NO_ORIGINAL", workflow_id)
            raise RuntimeError("workflow runner unavailable")
        try:
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            cur = conn.cursor()
            row = cur.execute(
                "SELECT status,current_step FROM workflows WHERE id=?", (workflow_id,)
            ).fetchone()
            _diag_log("RUN_WORKFLOW_PRE", str(row))
            if row:
                enabled = cur.execute(
                    "SELECT COALESCE(enable_checkpoints,0) FROM workflows WHERE id=?", (workflow_id,)
                ).fetchone()
                if not enabled or not enabled[0]:
                    cur.execute(
                        "UPDATE workflow_steps SET has_checkpoint=0, checkpoint_type=NULL WHERE workflow_id=?",
                        (workflow_id,),
                    )
                    conn.commit()
                # 编译态主循环要求 status='running' 才会真正调度；
                # 直接以 paused 状态进入会挂起且永不返回（task 残留在 _tasks）。
                if row[0] != "running":
                    cur.execute(
                        "UPDATE workflows SET status='running',updated_at=datetime('now') WHERE id=?",
                        (workflow_id,),
                    )
                    conn.commit()
                    _diag_log("RUN_WORKFLOW_FORCE_RUNNING", row[0])
                # 主循环要求当前步骤为 running 才会 spawn。下一步若还停在 pending，
                # 置 running 让 resume 真正开跑。waiting_checkpoint 是官方核验态，
                # 绝不能改成 running，否则刚审完的步骤会被再跑一遍并重新弹窗。
                if row:
                    step_row = cur.execute(
                        "SELECT skill_name FROM workflow_steps WHERE workflow_id=? "
                        "AND skill_name=? AND status='pending'",
                        (workflow_id, row[1]),
                    ).fetchone()
                    if step_row:
                        cur.execute(
                            "UPDATE workflow_steps SET status='running' "
                            "WHERE workflow_id=? AND skill_name=?", (workflow_id, row[1]),
                        )
                        conn.commit()
                        _diag_log("RUN_WORKFLOW_FORCE_STEP_RUNNING", row[1])
            if row and row[0] == "running" and not row[1]:
                nxt = cur.execute(
                    "SELECT skill_name FROM workflow_steps WHERE workflow_id=? "
                    "AND status IN ('pending','running') ORDER BY step_order LIMIT 1",
                    (workflow_id,),
                ).fetchone()
                if nxt:
                    cur.execute(
                        "UPDATE workflows SET current_step=?,updated_at=datetime('now') WHERE id=?",
                        (nxt[0], workflow_id),
                    )
                    conn.commit()
                    log.info("[taskstate-repair] set workflow %s current_step=%s", workflow_id, nxt[0])
            conn.close()
        except Exception as exc:
            log.warning("[taskstate-repair] pre-run reconciliation failed for %s: %s", workflow_id, exc)
        try:
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            cur = conn.cursor()
            row = cur.execute(
                "SELECT status,current_step FROM workflows WHERE id=?", (workflow_id,)
            ).fetchone()
            _diag_log("RUN_WORKFLOW_PRE2", str(row))
            conn.close()
        except Exception as exc:
            _diag_log("RUN_WORKFLOW_PRE2_ERR", str(exc))
        _diag_log("RUN_WORKFLOW_CALL_ORIGINAL", workflow_id)
        result = await original_run_workflow(workflow_id)
        _diag_log("RUN_WORKFLOW_RETURNED", repr(result)[:300])
        try:
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            review_done = conn.execute(
                "SELECT 1 FROM workflow_steps WHERE workflow_id=? AND skill_name='comp-review' "
                "AND status='completed' LIMIT 1",
                (workflow_id,),
            ).fetchone()
            conn.close()
            if review_done:
                await _maybe_start_review_repair(workflow_id, "comp-review")
        except Exception as exc:
            log.warning("[review-repair] post-run hook failed for %s: %s", workflow_id, exc)
        return result

    if workflow_engine is not None:
        workflow_engine.wait_checkpoint = patched_wait_checkpoint
        workflow_engine.run_workflow = patched_run_workflow
    if workflows_router is not None:
        # Router endpoints resolve this module-global callable at invocation;
        # replacing it ensures start/resume/restart all use the same repair.
        workflows_router.run_workflow = patched_run_workflow
        # rerun_step 是单步调度：暂停后重跑某一步骤时，workflow 仍是 paused，
        # 该步骤完成后引擎主循环不会自动推进到下一步（跑完即停）。
        # 包装它：重跑前把 paused 工作流置回 running，使完成后能继续推进或
        # 进入 waiting_checkpoint 弹窗。
        original_rerun_step = workflows_router.rerun_step

    async def _broadcast_checkpoint_hit(wf_id: str) -> None:
        """Broadcast a checkpoint_hit for the currently waiting gate (rerun/boot).

        The compiled engine broadcasts checkpoint_hit itself on the main-loop
        path, but the single-step rerun path finishes without broadcasting, so
        the UI popup never appears. This re-broadcasts from SQLite state so the
        approval card shows up in both cases.
        """
        try:
            from routers.ws import manager as _ws_manager
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            row = conn.execute(
                "SELECT s.skill_name, s.display_name, s.checkpoint_type, s.output_files "
                "FROM workflow_steps s JOIN workflows w ON w.id=s.workflow_id "
                "WHERE s.workflow_id=? AND s.status='waiting_checkpoint' AND s.has_checkpoint=1 "
                "AND COALESCE(w.enable_checkpoints,0)=1 ORDER BY s.step_order DESC LIMIT 1",
                (wf_id,),
            ).fetchone()
            conn.close()
            if not row:
                return
            payload = {
                "type": "checkpoint_hit",
                "step": row[0],
                "checkpoint_type": row[2] or "approve",
                "display_name": row[1] or row[0],
            }
            if row[3]:
                try:
                    files = json.loads(row[3]) if isinstance(row[3], str) else list(row[3])
                    if files:
                        ws_dir = Path.home() / "AppData" / "Roaming" / "MHAgent" / "workspaces" / wf_id
                        p0 = ws_dir / str(files[0])
                        if p0.exists():
                            payload["primary_output_file"] = str(files[0])
                            payload["primary_output_content"] = p0.read_text(
                                encoding="utf-8", errors="ignore"
                            )[:1500]
                except Exception:
                    pass
            await _ws_manager.broadcast(wf_id, payload)
            _diag_log("CHECKPOINT_BROADCAST", f"{wf_id} step={row[0]}")
        except Exception as exc:
            log.warning("[mode-a] checkpoint_hit broadcast failed for %s: %s", wf_id, exc)

    async def patched_rerun_step(wf_id: str, skill_name: str):
        try:
            conn = sqlite3.connect(str(_PRESET_DB_PATH), timeout=5)
            conn.execute(
                "UPDATE workflows SET status='running', updated_at=datetime('now') "
                "WHERE id=? AND status='paused'", (wf_id,)
            )
            conn.commit()
            conn.close()
            _diag_log("RERUN_SET_RUNNING", wf_id)
        except Exception as exc:
            _diag_log("RERUN_SET_RUNNING_ERR", str(exc))
        result = await original_rerun_step(wf_id, skill_name)
        return result

    if workflows_router is not None:
        workflows_router.rerun_step = patched_rerun_step
        # 模块属性替换对已注册的 FastAPI 路由不生效（路由 endpoint 在 include_router
        # 时已绑定编译态原函数）。必须像 checkpoints 路由那样直接替换 APIRoute 的
        # endpoint 并重建依赖树，patched_rerun_step 才会真正被调用。
        try:
            from fastapi.dependencies.utils import get_dependant, get_flat_dependant, get_body_field
            from starlette.routing import request_response
            for route in workflows_router.router.routes:
                if getattr(route, "path", "").endswith("/steps/{skill_name}/rerun"):
                    route.endpoint = patched_rerun_step
                    route.dependant = get_dependant(path=route.path_format, call=patched_rerun_step)
                    route.body_field = get_body_field(
                        flat_dependant=get_flat_dependant(route.dependant),
                        name=route.unique_id,
                        embed_body_fields=False,
                    )
                    route.app = request_response(route.get_route_handler())
                    _diag_log("RERUN_ROUTE_REPLACED", "ok")
        except Exception as exc:
            _diag_log("RERUN_ROUTE_REPLACE_ERR", str(exc))

    store.get_all_settings = patched_get_all_settings
    store.save_settings = patched_save_settings
    store.get_workflows_to_resume = patched_get_workflows_to_resume
    llm_client.get_all_settings = patched_get_all_settings
    llm_client.call_llm = patched_call_llm
    llm_client.test_connection = patched_test_connection
    # 官方 describe_image（Vision）把 base_url 锁定为 _locked_url()=mhcoding，
    # 与本地 ergouzi 网关 key 错配 → Vision 全部 401 Invalid token，且预检重试
    # 拖住工作流主循环不 spawn 子进程。把锁定 URL 改指本地网关。
    try:
        llm_client._locked_url = lambda: "https://ergouzi.life/"
        log.info("[local-api] _locked_url redirected to ergouzi for vision")
    except Exception as exc:
        log.warning("[local-api] _locked_url patch failed: %s", exc)
    # Vision 链路替换：官方 _call_llm_vision_sync 用错误的端点/鉴权导致
    # 全部 401（实测 ergouzi /v1/messages + 图片 + claude-opus-5 返回 200）。
    # 自实现 Vision（Anthropic 格式），统一走 reviewer 配置。
    try:
        import base64 as _b64
        import urllib.request as _urlreq
        import urllib.error as _urlerr

        _VISION_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

        def _local_vision_sync(image_path: str, prompt: str, timeout: int = 120) -> str:
            # 同步读 SQLite（不能在 executor 线程里 run_until_complete）
            try:
                import sqlite3 as _sql
                _con = _sql.connect(str(_PRESET_DB_PATH), timeout=5)
                _rows = _con.execute("SELECT key, value FROM settings").fetchall()
                _con.close()
                values = dict(_rows)
            except Exception as _exc:
                raise RuntimeError(f"settings unavailable for vision: {_exc}") from _exc
            base = normalize_base_url(values.get("reviewer_base_url") or "https://ergouzi.life/")
            key = (values.get("reviewer_api_key") or "").strip()
            model = (values.get("reviewer_model_id") or "claude-opus-5").strip()
            if not key:
                raise RuntimeError("reviewer key missing for vision")
            ext = str(image_path).rsplit(".", 1)[-1].lower()
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
            with open(image_path, "rb") as f:
                b64 = _b64.b64encode(f.read()).decode()
            body = {
                "model": model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                    {"type": "text", "text": prompt or "请描述这张图片的内容。"},
                ]}],
            }
            req = _urlreq.Request(
                base.rstrip("/") + "/v1/messages", data=json.dumps(body).encode(),
                headers={**_VISION_UA, "Content-Type": "application/json",
                         "x-api-key": key, "Authorization": f"Bearer {key}",
                         "anthropic-version": "2023-06-01"},
            )
            with _urlreq.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode())
            return "".join(b.get("text", "") for b in d.get("content", []) if isinstance(b, dict))

        async def _patched_describe_image(image_path: str, context: str = ""):
            log.info("[vision-hook] describe_image (local) path=%s", image_path)
            loop = asyncio.get_event_loop()
            try:
                return await loop.run_in_executor(None, _local_vision_sync, image_path, context)
            except Exception as exc:
                log.warning("[vision-hook] local vision failed: %s", exc)
                raise

        def _patched_vision_sync(base_url, api_key, model_id, prompt, image_b64, mime_type="image/png", timeout=120):
            # 官方 sync 入口也替换：把 base64 还原成临时文件后走本地实现
            import tempfile as _tmp, os as _os
            suffix = ".png" if "png" in mime_type else ".jpg"
            fd, tmp_path = _tmp.mkstemp(suffix=suffix)
            try:
                with _os.fdopen(fd, "wb") as f:
                    f.write(_b64.b64decode(image_b64))
                return _local_vision_sync(tmp_path, prompt, timeout)
            finally:
                try:
                    _os.unlink(tmp_path)
                except Exception:
                    pass

        llm_client._call_llm_vision_sync = _patched_vision_sync
        llm_client.describe_image = _patched_describe_image
        log.info("[local-api] vision replaced with local ergouzi implementation")
    except Exception as exc:
        log.warning("[local-api] vision replacement failed: %s", exc)
    runner.get_all_settings = patched_get_all_settings
    runner._load_skill_prompt = patched_load_skill_prompt
    runner.asyncio.create_subprocess_exec = patched_spawn
    settings_router.get_all_settings = patched_get_all_settings
    settings_router.save_settings = patched_save_settings
    settings_router.call_llm = patched_call_llm
    settings_router.test_connection = patched_test_connection

    # NOTE: 不再强制把所有 Base URL 归一为 ergouzi（旧 persist_normalized_values
    # 段已移除）。显式配置的 DeepSeek 文本角色与 ergouzi 图片角色保持 SQLite 原值。

    # Artifact cleanup is deliberately not a live SQLite polling task. A
    # concurrent state writer can race the compiled workflow engine; output
    # reconciliation is performed after a step finishes, outside the runner.
    _PATCHED = True
    log.info("[local-api] endpoint, connection-test, and ImageGen patch installed; prompt/workspace injections disabled")
    return True
