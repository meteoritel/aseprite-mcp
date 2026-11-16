"""Explicit maintenance checks for generated references and startup instructions."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from aseprite_mcp.tool_catalog import CORE_TOOLS, DISCOVERY_TOOLS, EXTENSION_TOOLS


def test_reference_generation_without_git_and_stale_interface_detection(tmp_path):
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "aseprite_mcp", tmp_path / "aseprite_mcp", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "scripts").mkdir()
    shutil.copy2(root / "scripts/gen_tool_reference.py", tmp_path / "scripts/gen_tool_reference.py")
    command = [sys.executable, "-S", str(tmp_path / "scripts/gen_tool_reference.py")]
    subprocess.run(command, check=True, capture_output=True)
    generated = tmp_path / "docs/reference/tools.md"
    assert generated.read_bytes() == (root / "docs/reference/tools.md").read_bytes()
    subprocess.run(command + ["--check"], check=True, capture_output=True)

    catalog = tmp_path / "aseprite_mcp/tool_catalog.py"
    core, extensions = dict(CORE_TOOLS), dict(EXTENSION_TOOLS)
    core["text"] = ("measure_text",)
    extensions["text"] = tuple(name for name in extensions["text"] if name != "measure_text")
    catalog.write_text(f"CORE_TOOLS = {core!r}\nEXTENSION_TOOLS = {extensions!r}\nDISCOVERY_TOOLS = {DISCOVERY_TOOLS!r}\n", encoding="utf-8")
    assert subprocess.run(command + ["--check"], capture_output=True).returncode == 1
    subprocess.run(command, check=True, capture_output=True)
    text = tmp_path / "aseprite_mcp/tools/text.py"
    text.write_text(text.read_text(encoding="utf-8").replace("size: int = 1,", "size: int = 2,"), encoding="utf-8")
    assert subprocess.run(command + ["--check"], capture_output=True).returncode == 1


@pytest.mark.parametrize("resource", ["missing", "blank", "unreadable", "invalid-utf8"])
def test_startup_requires_readable_nonempty_instructions(tmp_path, resource):
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "aseprite_mcp", tmp_path / "aseprite_mcp", ignore=shutil.ignore_patterns("__pycache__"))
    skill = tmp_path / "SKILL.md"
    if resource == "blank":
        skill.write_text(" \n\t", encoding="utf-8")
    elif resource == "unreadable":
        skill.mkdir()
    elif resource == "invalid-utf8":
        skill.write_bytes(b"\xff")
    result = subprocess.run([sys.executable, "-B", "-m", "aseprite_mcp"], cwd=tmp_path,
                            input="", capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode != 0
    assert not result.stdout
    assert str(skill) in result.stderr
    assert "Restore a readable, nonempty UTF-8 SKILL.md" in result.stderr
