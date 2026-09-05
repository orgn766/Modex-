#!/usr/bin/env python3
# -*- coding: utf-8
"""Small regression test for the figure gate process contract.

Run from any cwd with the system Python. It uses temporary fixture workspaces
and never touches a user's project.
"""
from __future__ import annotations

import json
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import uuid
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUALITY = HERE / "figure_quality_gate.py"
NUMBER = HERE / "figure_number_consistency_gate.py"
RENDER = HERE / "figure_render_qa.py"


class _PlainWorkspace:
    """Avoid Windows TemporaryDirectory ACL rewriting in packaged runtimes."""

    def __enter__(self):
        self.path = HERE.parent / f"_figure_gate_test_{uuid.uuid4().hex}"
        self.path.mkdir()
        return str(self.path)

    def __exit__(self, *_):
        shutil.rmtree(self.path)


def run(script: Path, workspace: Path, stage: str | None = "post") -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(script), "--workspace", str(workspace)]
    if stage is not None:
        command.extend(["--stage", stage])
    return subprocess.run(
        command,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def main() -> int:
    lifecycle_path = HERE.parent / "backend" / "services" / "figure_lifecycle_patch.py"
    lifecycle_spec = importlib.util.spec_from_file_location("modex_figure_lifecycle_test", lifecycle_path)
    lifecycle = importlib.util.module_from_spec(lifecycle_spec)
    lifecycle_spec.loader.exec_module(lifecycle)
    assert lifecycle._vision_enabled(HERE, {"data_fig_vision": True})
    assert lifecycle._vision_review_reason({"returncode": 1, "error": "missing"}, {}) == "missing"

    with _PlainWorkspace() as raw:
        ws = Path(raw)
        (ws / "figures").mkdir()
        # BLOCK: forbidden colormap.
        (ws / "figures" / "gen_fig_bad.py").write_text("import matplotlib.pyplot as plt\nplt.plot([1,2], cmap='jet')\n", encoding="utf-8")
        bad = run(QUALITY, ws)
        assert bad.returncode == 1, (bad.returncode, bad.stdout, bad.stderr)
        assert "FIGURE_QUALITY_BLOCK=true" in bad.stdout

        # REVIEW: no output and no contract, but no integrity block.
        (ws / "figures" / "gen_fig_bad.py").unlink()
        review = run(QUALITY, ws, stage="pre")
        assert review.returncode == 2, (review.returncode, review.stdout, review.stderr)
        assert "FIGURE_QUALITY_REVIEW=true" in review.stdout

        # PASS: minimal declared source, contract, manifest, and paired outputs.
        (ws / "figures" / "gen_fig_ok.py").write_text(
            "# FIGURE_CONTRACT source_json\nimport json\nimport matplotlib.pyplot as plt\ndata=json.load(open('data.json'))\nplt.plot(data['x'], data['y'])\nplt.savefig('fig_ok.pdf')\nplt.savefig('fig_ok.png')\n",
            encoding="utf-8",
        )
        (ws / "figures" / "data.json").write_text('{"x":[1,2],"y":[1,2]}', encoding="utf-8")
        (ws / "FIGURE_CONTRACT.json").write_text('{}', encoding="utf-8")
        (ws / "VISUALIZATION_DATA_MANIFEST.json").write_text('{}', encoding="utf-8")
        (ws / "figures" / "fig_ok.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        # Valid 1x1 PNG; this test exercises verdict wiring, not image decoding.
        (ws / "figures" / "fig_ok.png").write_bytes(bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
            "0000000c49444154789c6360a0c00000020001e221bc330000000049454e44ae426082"
        ))
        passed = run(QUALITY, ws)
        assert passed.returncode == 0, (passed.returncode, passed.stdout, passed.stderr)
        assert "FIGURE_QUALITY_PASS=true" in passed.stdout

        # Number gate: absent result source is an explicit REVIEW, not PASS.
        number_review = run(NUMBER, ws, stage=None)
        assert number_review.returncode == 2, (number_review.returncode, number_review.stdout, number_review.stderr)
        assert "FIGURE_NUMBER_REVIEW" in number_review.stdout

        (ws / "RESULTS.json").write_text("{bad json", encoding="utf-8")
        number_block = run(NUMBER, ws, stage=None)
        assert number_block.returncode == 1, (number_block.returncode, number_block.stdout, number_block.stderr)
        assert "FIGURE_NUMBER_BLOCK" in number_block.stdout

        # Hunan competition: verify the planned final 7.5--9 pt range.
        import fitz
        strict = ws / "strict"
        (strict / "figures").mkdir(parents=True)
        (strict / "CLAUDE.md").write_text("- competition: hunan_graduate\n", encoding="utf-8")
        utils = HERE.parent / "skills" / "shared-scripts" / "plot_utils.py"
        spec = importlib.util.spec_from_file_location("modex_plot_utils_hunan_test", utils)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        previous_cwd = Path.cwd()
        try:
            os.chdir(strict)
            module.setup_style("auto")
            import matplotlib
            assert matplotlib.rcParams["font.size"] == 9
        finally:
            os.chdir(previous_cwd)
        pdf = strict / "figures" / "fig_font.pdf"
        doc = fitz.open()
        page = doc.new_page(width=6 * 72, height=3.6 * 72)
        page.insert_text((24, 24), "final font", fontsize=9)
        doc.save(pdf)
        doc.close()
        render_output = strict / "_tmp" / "render.json"
        subprocess.run(
            [sys.executable, str(RENDER), "--workspace", str(strict), "--output", str(render_output)],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert json.loads(render_output.read_text(encoding="utf-8"))["verdict"] == "PASS"
        doc = fitz.open()
        page = doc.new_page(width=6 * 72, height=3.6 * 72)
        page.insert_text((24, 24), "too large", fontsize=12)
        doc.save(pdf)
        doc.close()
        subprocess.run(
            [sys.executable, str(RENDER), "--workspace", str(strict), "--output", str(render_output)],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert json.loads(render_output.read_text(encoding="utf-8"))["verdict"] == "BLOCK"
        doc = fitz.open()
        page = doc.new_page(width=6 * 72, height=3.6 * 72)
        page.insert_text((24, 24), "final font", fontsize=9)
        doc.save(pdf)
        doc.close()
        (strict / "PROBLEM_ANALYSIS.md").write_text(
            "<!-- BEGIN FIGURE_MANIFEST -->\nDATA=1\nDRAWIO=0\nTIKZ=1\nGPTIMG=0\nALL=2\n\n"
            "DATA:\n- fig_font\n\nDRAWIO:\n\nTIKZ:\n- tikz_missing\n\nGPTIMG:\n<!-- END FIGURE_MANIFEST -->\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(RENDER), "--workspace", str(strict), "--output", str(render_output)],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        report = json.loads(render_output.read_text(encoding="utf-8"))
        assert report["verdict"] == "REVIEW"
        assert {item["figure_id"] for item in report["figures"]} == {"fig_font", "tikz_missing"}

    if platform.system() == "Windows":
        utils = HERE.parent / "skills" / "shared-scripts" / "plot_utils.py"
        spec = importlib.util.spec_from_file_location("modex_plot_utils_test", utils)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.setup_style("auto")
        import matplotlib
        import matplotlib.pyplot as plt
        assert "DejaVu Sans" in matplotlib.rcParams["font.family"]
        fig, ax = plt.subplots(figsize=(2, 1))
        ax.set_title("中文 CO₂ −")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fig.canvas.draw()
        plt.close(fig)
        assert not [warning for warning in caught if "Glyph" in str(warning.message)]
    print("FIGURE_GATE_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
