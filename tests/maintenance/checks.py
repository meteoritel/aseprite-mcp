"""Explicit maintenance checks for startup instructions."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

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
