"""Real subprocess execution preserves diagnostics and reaps timed out or cancelled work."""
import asyncio
import os
import subprocess
import sys

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from aseprite_mcp.core import commands
from aseprite_mcp.core.commands import AsepriteCommand
from support import run


def assert_process_gone(pid):
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert str(pid).encode("ascii") not in result.stdout
    else:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.fixture
def python_process(monkeypatch):
    monkeypatch.setenv("ASEPRITE_PATH", sys.executable)


def test_output_budget_ends_the_process(python_process, monkeypatch):
    monkeypatch.setattr(commands, "MAX_OUTPUT_BYTES", 1024)
    with pytest.raises(ToolError, match="output exceeded"):
        run(commands.AsepriteCommand.run_command(["-c", "import time; print('x'*2048, flush=True); time.sleep(30)"]))


def test_startup_failure_is_a_tool_error(monkeypatch, tmp_path):
    monkeypatch.setenv("ASEPRITE_PATH", str(tmp_path / "missing-aseprite"))
    with pytest.raises(ToolError, match="Could not start"):
        run(commands.AsepriteCommand.run_command(["--version"]))


def test_cancel_reaps_process_and_allows_next_execution(python_process, tmp_path):
    pid_file = tmp_path / "pid"

    async def scenario():
        execution = asyncio.create_task(commands.AsepriteCommand.run_command([
            "-c", f"import os,time; from pathlib import Path; Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(30)",
        ]))
        async with asyncio.timeout(5):
            while not pid_file.exists():
                await asyncio.sleep(0.01)
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution
        assert_process_gone(int(pid_file.read_text()))
        assert (await commands.AsepriteCommand.run_command(["-c", "print('next')"])).strip() == "next"
    run(scenario())


def test_timeout_reaps_wrapper_and_child(python_process, monkeypatch, tmp_path):
    monkeypatch.setattr(commands, "PROCESS_TIMEOUT_SECONDS", 1.5)
    child_pid = tmp_path / "child"
    parent_pid = tmp_path / "parent"
    code = (
        "import os,subprocess,sys,time; from pathlib import Path; "
        f"Path({str(parent_pid)!r}).write_text(str(os.getpid())); "
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"Path({str(child_pid)!r}).write_text(str(child.pid)); time.sleep(30)"
    )
    with pytest.raises(ToolError, match="timed out"):
        run(commands.AsepriteCommand.run_command(["-c", code]))
    assert_process_gone(int(parent_pid.read_text()))
    assert_process_gone(int(child_pid.read_text()))


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
