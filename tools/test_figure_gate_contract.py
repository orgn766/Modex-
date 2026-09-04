#!/usr/bin/env python3
# -*- coding: utf-8
"""Small regression test for the figure gate process contract.

Run from any cwd with the system Python. It uses temporary fixture workspaces
and never touches a user's project.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUALITY = HERE / "figure_quality_gate.py"
NUMBER = HERE / "figure_number_consistency_gate.py"


def run(script: Path, workspace: Path, stage: str | None = "post") -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(script), "--workspace", str(workspace)]
    if stage is not None:
        command.extend(["--stage", stage])
    return subprocess.run(
        command,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="modex-figure-gate-") as raw:
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
    print("FIGURE_GATE_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
