"""Unit tests for encoding safety of the Aseprite command bridge.

Aseprite reads Lua files as UTF-8 and writes UTF-8 to stdout. On a
Chinese Windows system the ANSI code page is GBK, so any implicit
encoding would corrupt non-ASCII paths (e.g. Chinese filenames) and the
sprite would be saved to a mojibake location.
"""

import os
import sys

from aseprite_mcp.core.commands import AsepriteCommand, lua_escape


class TestLuaScriptFileEncoding:
    def test_script_file_is_utf8_with_chinese_path(self, monkeypatch, tmp_path):
        target = str(tmp_path / "精灵" / "角色.aseprite")
        os.makedirs(os.path.dirname(target))
        with open(target, "wb") as f:
            f.write(b"x")

        captured = {}

        def fake_run(args):
            script_path = args[args.index("--script") + 1]
            with open(script_path, "rb") as f:
                captured["script_bytes"] = f.read()
            return True, "OK"

        monkeypatch.setattr(
            AsepriteCommand, "run_command", staticmethod(fake_run)
        )
        success, _ = AsepriteCommand.execute_lua_script(
            f'spr:saveAs("{lua_escape(target)}")', target
        )
        assert success
        # The file must be valid UTF-8 and contain the original path.
        script = captured["script_bytes"].decode("utf-8")
        assert lua_escape(target) in script


class TestRunCommandDecoding:
    def test_stdout_decoded_as_utf8(self, monkeypatch):
        """run_command must decode Aseprite's UTF-8 output, not the ANSI page."""
        monkeypatch.setenv("ASEPRITE_PATH", sys.executable)
        success, output = AsepriteCommand.run_command(
            ["-X", "utf8", "-c", "print('中文路径/精灵')"]
        )
        assert success
        assert "中文路径/精灵" in output

    def test_stderr_decoded_as_utf8_on_failure(self, monkeypatch):
        monkeypatch.setenv("ASEPRITE_PATH", sys.executable)
        success, output = AsepriteCommand.run_command(
            ["-X", "utf8", "-c", "import sys; sys.stderr.write('错误：中文'); sys.exit(1)"]
        )
        assert not success
        assert "错误：中文" in output
