"""UTF-8 survives Python, temporary Lua files and process diagnostics."""

import os
import sys

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import run
from aseprite_mcp.core.commands import AsepriteCommand, lua_escape


def test_script_file_is_utf8_and_removed_after_execution(monkeypatch, tmp_path):
    target = str(tmp_path / "精灵" / "角色.aseprite")
    captured = {}

    async def fake_run(args):
        script_path = args[args.index("--script") + 1]
        captured["path"] = script_path
        with open(script_path, "rb") as script:
            captured["bytes"] = script.read()
        return "OK"

    monkeypatch.setattr(AsepriteCommand, "run_command", staticmethod(fake_run))
    assert run(AsepriteCommand.execute_lua_script(
        f'spr:saveAs("{lua_escape(target)}")', target,
    )) == "OK"
    assert lua_escape(target) in captured["bytes"].decode("utf-8")
    assert not os.path.exists(captured["path"])


def test_stdout_decoded_as_utf8(monkeypatch):
    monkeypatch.setenv("ASEPRITE_PATH", sys.executable)
    output = run(AsepriteCommand.run_command(["-X", "utf8", "-c", "print('中文路径/精灵')"]))
    assert "中文路径/精灵" in output


def test_both_diagnostic_streams_survive_nonzero_exit(monkeypatch):
    monkeypatch.setenv("ASEPRITE_PATH", sys.executable)
    with pytest.raises(ToolError) as error:
        run(AsepriteCommand.run_command([
            "-X", "utf8", "-c",
            "import sys; print('脚本失败'); sys.stderr.write('错误：中文'); sys.exit(3)",
        ]))
    assert "脚本失败" in str(error.value)
    assert "错误：中文" in str(error.value)
    assert "code 3" in str(error.value)
