"""The process adapter remains responsive and reaps its owned processes."""

import asyncio
import os
import subprocess
import sys

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from conftest import run
from aseprite_mcp.core import commands


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


def test_timeout_reaps_the_process(python_process, monkeypatch, tmp_path):
    monkeypatch.setattr(commands, "PROCESS_TIMEOUT_SECONDS", 0.4)
    pid_file = tmp_path / "pid"
    code = f"import os,time; from pathlib import Path; Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(30)"
    with pytest.raises(ToolError, match="timed out"):
        run(commands.AsepriteCommand.run_command(["-c", code]))
    assert_process_gone(int(pid_file.read_text()))


def test_output_budget_ends_the_process(python_process, monkeypatch):
    monkeypatch.setattr(commands, "MAX_OUTPUT_BYTES", 1024)
    with pytest.raises(ToolError, match="output exceeded"):
        run(commands.AsepriteCommand.run_command(["-c", "import time; print('x'*2048, flush=True); time.sleep(30)"]))


def test_startup_failure_is_a_tool_error(monkeypatch, tmp_path):
    monkeypatch.setenv("ASEPRITE_PATH", str(tmp_path / "missing-aseprite"))
    with pytest.raises(ToolError, match="Could not start"):
        run(commands.AsepriteCommand.run_command(["--version"]))


def test_process_wait_does_not_block_event_loop(python_process):
    async def scenario():
        execution = asyncio.create_task(commands.AsepriteCommand.run_command([
            "-c", "import time; time.sleep(0.2); print('done')",
        ]))
        await asyncio.sleep(0.02)
        assert not execution.done()
        assert (await execution).strip() == "done"
    run(scenario())


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
