"""Real sessions serialize edits, recover from cancellation and release processes."""
import asyncio
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

import pytest

from aseprite_mcp.core import editing
from aseprite_mcp.core.commands import AsepriteCommand
from support import REPO_ROOT, call, connected_server, digest, paint, run


SLOW_EXTENSION_SERVER = """
import os
from pathlib import Path
from aseprite_mcp import create_server
from aseprite_mcp.tools import text
original = text.execute_edit_script
async def delayed_edit(script, filename):
    marker = Path(os.environ['PROXY_TEST_MARKER'])
    if not marker.exists():
        prefix = 'local f = io.open("' + marker.as_posix() + '", "w"); f:write("started"); f:close(); '
        if os.environ['PROXY_TEST_MODE'] == 'serial':
            prefix += 'local started = os.clock(); while os.clock() - started < 0.3 do end; '
        else:
            prefix += 'while true do end; '
        script = prefix + script
    return await original(script, filename)
text.execute_edit_script = delayed_edit
create_server().run(transport='stdio')
"""


@pytest.mark.parametrize("mode", ["serial", "cancel", "disconnect"])
def test_proxy_edit_shares_serialization_cancellation_and_cleanup(tmp_path, bitmap_font, mode):
    source, marker = tmp_path / "proxy.aseprite", tmp_path / "proxy-started"
    arguments = {"text": "B", "font": bitmap_font, "x": 0, "y": 0,
                 "layer_name": "ink", "frame_index": 1, "color": "#ff0000"}
    with connected_server(code=SLOW_EXTENSION_SERVER, env={
        "PROXY_TEST_MARKER": str(marker), "PROXY_TEST_MODE": mode,
    }) as (send, receive):
        assert not call(send, receive, "create_canvas", {"width": 16, "height": 16, "filename": str(source)})["isError"]
        before = source.read_bytes()
        send("tools/call", {"name": "call_tool", "arguments": {"name": "draw_text", "arguments": arguments}}, 2)
        deadline = time.monotonic() + 5
        while not marker.exists():
            assert time.monotonic() < deadline, "Extension Lua did not start"
            time.sleep(0.01)
        if mode == "disconnect":
            pass  # Closing the real transport must cancel the active proxy edit.
        else:
            send("tools/call", {"name": "draw_pixels_at", "arguments": {
                "layer_name": "ink", "frame_index": 1,
                "pixels": [{"x": 0, "y": 0, "color": "#00ff00"}],
            }}, 3)
            if mode == "cancel":
                send("notifications/cancelled", {"requestId": 2, "reason": "cancel proxy"})
            else:
                assert receive(2)["isError"] is False
            assert receive(3)["isError"] is False
            pixels = call(send, receive, "get_pixels_rect", {
                "layer_name": "ink", "frame_index": 1, "x": 0, "y": 0, "width": 2, "height": 1,
            })["structuredContent"]["data"]
            assert pixels[0] == {"x": 0, "y": 0, "r": 0, "g": 255, "b": 0, "a": 255, "hex": "#00ff00"}
            assert pixels[1]["a"] == (255 if mode == "serial" else 0)
            assert not call(send, receive, "call_tool", {"name": "draw_text", "arguments": arguments})["isError"]
    if mode == "disconnect":
        assert source.read_bytes() == before
    assert not list(tmp_path.glob(".aseprite-edit-*"))


def test_cancel_running_call_then_edit_again(tmp_path):
    marker = tmp_path / "started"
    with connected_server() as (send, receive):
        send("tools/call", {"name": "run_lua_script", "arguments": {
            "script": f'local f = io.open("{marker.as_posix()}", "w"); f:write("started"); f:close(); while true do end',
        }}, 1)
        deadline = time.monotonic() + 5
        while not marker.exists():
            assert time.monotonic() < deadline, "Lua did not start"
            time.sleep(0.01)
        queued_marker = tmp_path / "queued-started"
        send("tools/call", {"name": "run_lua_script", "arguments": {
            "script": f'local f = io.open("{queued_marker.as_posix()}", "w"); f:write("started"); f:close()',
        }}, 2)
        send("notifications/cancelled", {"requestId": 2, "reason": "cancel queued call"})
        send("notifications/cancelled", {"requestId": 1, "reason": "test cancellation"})
        source = tmp_path / "after-cancel.aseprite"
        send("tools/call", {"name": "create_canvas", "arguments": {
            "width": 16, "height": 16, "filename": str(source),
        }}, 3)
        assert receive(3)["isError"] is False
        assert source.exists()

        assert not queued_marker.exists()


def test_concurrent_calls_preserve_both_edits(tmp_path):
    source, marker = tmp_path / "concurrent.aseprite", tmp_path / "loaded"
    with connected_server() as (send, receive):
        send("tools/call", {"name": "create_canvas", "arguments": {
            "width": 16, "height": 16, "filename": str(source),
        }}, 1)
        assert receive(1)["isError"] is False
        script = f'''
        local spr = app.activeSprite
        local f = io.open("{marker.as_posix()}", "w"); f:write("loaded"); f:close()
        local started = os.clock(); while os.clock() - started < 0.3 do end
        spr.layers[1]:cel(spr.frames[1]).image:putPixel(0, 0, app.pixelColor.rgba(255, 0, 0, 255))
        spr:saveAs(spr.filename)
        '''
        send("tools/call", {"name": "run_lua_script", "arguments": {"script": script}}, 2)
        deadline = time.monotonic() + 5
        while not marker.exists():
            assert time.monotonic() < deadline, "Lua did not open the project"
            time.sleep(0.01)
        send("tools/call", {"name": "draw_pixels_at", "arguments": {
            "layer_name": "Layer 1", "frame_index": 1,
            "pixels": [{"x": 1, "y": 0, "color": "#00ff00"}],
        }}, 3)
        assert receive(3)["isError"] is False
        assert receive(2)["isError"] is False
        send("tools/call", {"name": "get_pixels_rect", "arguments": {
            "layer_name": "Layer 1", "frame_index": 1, "x": 0, "y": 0, "width": 2, "height": 1,
        }}, 4)
        result = receive(4)
        assert result["isError"] is False
        pixels = result["structuredContent"]["data"]
        assert [(p["r"], p["g"], p["b"], p["a"]) for p in pixels] == [(255, 0, 0, 255), (0, 255, 0, 255)]


def test_disconnect_cleans_running_call(tmp_path):
    marker = tmp_path / "running"
    with connected_server() as (send, receive):
        send("tools/call", {"name": "run_lua_script", "arguments": {
            "script": f'local f = io.open("{marker.as_posix()}", "w"); f:write("running"); f:close(); while true do end',
        }}, 1)
        deadline = time.monotonic() + 5
        while not marker.exists():
            assert time.monotonic() < deadline, "Lua did not start"
            time.sleep(0.01)


CLIENT_CODE = """
import json, os, subprocess, sys, time, queue, threading
env = dict(os.environ)
env["PYTHONPATH"] = r"{repo}"
server = subprocess.Popen(
    [sys.executable, "-B", "-m", "aseprite_mcp"],
    cwd=r"{repo}", env=env,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True, encoding="utf-8", errors="replace",
)
request = {{
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {{"protocolVersion": "2024-11-05", "capabilities": {{}},
                "clientInfo": {{"name": "stdio-lifecycle-test", "version": "1"}}}},
}}
server.stdin.write(json.dumps(request) + "\\n")
server.stdin.flush()
lines = queue.Queue()
threading.Thread(target=lambda: lines.put(server.stdout.readline()), daemon=True).start()
try:
    reply = lines.get(timeout=10)
except queue.Empty:
    server.kill(); server.wait(timeout=5)
    raise SystemExit("HANDSHAKE_TIMEOUT")
if not reply or '"result"' not in reply:
    print("HANDSHAKE_FAILED", flush=True)
    sys.exit(1)
print("READY " + str(server.pid), flush=True)
time.sleep(600)
""".format(repo=REPO_ROOT)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        return str(pid) in (result.stdout or "")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_tree(pid: int) -> None:
    if not _pid_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_stdio_server_exits_when_client_process_dies():
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT
    client = subprocess.Popen(
        [sys.executable, "-B", "-c", CLIENT_CODE],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    server_pid = None
    try:
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(client.stdout.readline()), daemon=True).start()
        line = (lines.get(timeout=15) or "").strip()
        client.stdout.close()
        assert line.startswith("READY "), (
            f"server did not complete initialize handshake: {line!r}"
        )
        server_pid = int(line.split()[1])
        assert _pid_alive(server_pid), "server was not running before disconnect"

        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(client.pid), "/F"], capture_output=True)
        else:
            os.kill(client.pid, signal.SIGKILL)

        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and _pid_alive(server_pid):
            time.sleep(0.1)
        assert not _pid_alive(server_pid), "server remained alive after client disconnect"
    finally:
        _kill_tree(client.pid)
        if server_pid is not None:
            _kill_tree(server_pid)


def test_cancel_before_commit_cleans_staging_and_script(new_sprite, tmp_path, monkeypatch):
    filename = new_sprite()
    paint(filename)
    original = digest(filename)
    marker = tmp_path / "saved"
    script_paths = []
    execute = AsepriteCommand.run_command

    async def track_script(args):
        script_paths.append(Path(args[args.index("--script") + 1]))
        return await execute(args)
    monkeypatch.setattr(AsepriteCommand, "run_command", track_script)

    async def scenario():
        task = asyncio.create_task(editing.execute_edit_script(f'''
            local spr = app.activeSprite
            spr.layers[2]:cel(spr.frames[1]).image:clear()
            save_project(spr)
            local f = io.open("{marker.as_posix()}", "w"); f:write("saved"); f:close()
            while true do end
        ''', filename))
        async with asyncio.timeout(5):
            while not marker.exists():
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    run(scenario())
    assert digest(filename) == original
    assert script_paths and all(not path.exists() for path in script_paths)
    assert not list(Path(filename).parent.glob(".aseprite-edit-*"))
