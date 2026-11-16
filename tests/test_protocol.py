"""The legacy SDK crashed on Antigravity's server/discover probe.

Verify the current server answers discovery and then serves tools/list.
"""

import json
import os
import queue
import subprocess
import sys
import threading

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESPONSE_TIMEOUT_SECONDS = 10
PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"


def _read_response(server: subprocess.Popen[str]) -> dict:
    lines = queue.Queue()
    threading.Thread(
        target=lambda: lines.put(server.stdout.readline()), daemon=True
    ).start()
    line = lines.get(timeout=RESPONSE_TIMEOUT_SECONDS)
    assert line, "stdio server closed before replying"
    return json.loads(line)


def test_server_discover_then_tools_list_over_stdio():
    client_meta = {
        PROTOCOL_VERSION_META_KEY: "2026-07-28",
        CLIENT_INFO_META_KEY: {"name": "protocol-test", "version": "1"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT
    server = subprocess.Popen(
        [sys.executable, "-m", "aseprite_mcp"],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    try:
        server.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"_meta": client_meta},
        }) + "\n")
        server.stdin.flush()
        discover_response = _read_response(server)
        assert discover_response["id"] == 1

        server.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {"_meta": client_meta},
        }) + "\n")
        server.stdin.flush()
        tools_response = _read_response(server)
        assert tools_response["id"] == 2

        discover = discover_response["result"]
        assert "2026-07-28" in discover["supportedVersions"]
        assert discover["resultType"] == "complete"
        assert "tools" in discover["capabilities"]

        tool_names = {tool["name"] for tool in tools_response["result"]["tools"]}
        assert "create_canvas" in tool_names

        server.stdin.close()
        assert server.wait(timeout=RESPONSE_TIMEOUT_SECONDS) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()

# tools/call checks use the real stdio server and Aseprite adapter.
from contextlib import contextmanager
from pathlib import Path
import time

import pytest
from PIL import Image


@contextmanager
def connected_server():
    env = dict(os.environ, PYTHONPATH=REPO_ROOT)
    server = subprocess.Popen(
        [sys.executable, "-m", "aseprite_mcp"], cwd=REPO_ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8",
    )
    responses = queue.Queue()

    def read_lines():
        for line in server.stdout:
            responses.put(json.loads(line))
    threading.Thread(target=read_lines, daemon=True).start()

    def send(method, params, request_id=None):
        request = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            request["id"] = request_id
        server.stdin.write(json.dumps(request) + "\n")
        server.stdin.flush()

    def receive(request_id):
        deadline = time.monotonic() + RESPONSE_TIMEOUT_SECONDS
        while True:
            response = responses.get(timeout=max(0.01, deadline - time.monotonic()))
            if response.get("id") == request_id:
                return response["result"]
            assert time.monotonic() < deadline, f"No response for {request_id}"

    try:
        send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "editing-test", "version": "1"}}, 0)
        receive(0)
        send("notifications/initialized", {})
        yield send, receive
        server.stdin.close()
        assert server.wait(timeout=RESPONSE_TIMEOUT_SECONDS) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait(timeout=5)


def test_tools_call_reports_errors_and_exports_pixels(tmp_path):
    source = str(tmp_path / "project.aseprite")
    with connected_server() as (send, receive):
        send("tools/call", {"name": "create_canvas", "arguments": {"width": 0, "height": 16, "filename": source}}, 1)
        assert receive(1)["isError"] is True
        assert not Path(source).exists()
        send("tools/call", {"name": "create_canvas", "arguments": {"width": 16, "height": 16, "filename": source}}, 2)
        assert receive(2)["isError"] is False
        for request_id, layer, frame in [(3, "missing", 1), (4, "Layer 1", 999)]:
            send("tools/call", {"name": "draw_pixels_at", "arguments": {
                "layer_name": layer, "frame_index": frame, "create_if_missing": False,
                "pixels": [{"x": 0, "y": 0, "color": "#ff0000"}],
            }}, request_id)
            assert receive(request_id)["isError"] is True
        send("tools/call", {"name": "draw_pixels_at", "arguments": {
            "layer_name": "ink", "frame_index": 1,
            "pixels": [{"x": 2, "y": 3, "color": "#1234567f"}],
        }}, 5)
        assert receive(5)["isError"] is False
        send("tools/call", {"name": "export_minecraft_texture", "arguments": {
            "output_filename": str(tmp_path / "texture.png"),
        }}, 6)
        result = receive(6)
        assert result["isError"] is False
        artifacts = json.loads(result["content"][0]["text"])
        preview = Path(artifacts["preview_png"])
        assert preview.exists()
        with Image.open(artifacts["png"]) as image:
            assert image.size == (16, 16)
            assert image.convert("RGBA").getpixel((2, 3)) == (18, 52, 86, 127)
        send("tools/call", {"name": "export_frame", "arguments": {
            "frame_index": 999, "output_filename": str(tmp_path / "bad.png"),
        }}, 7)
        assert receive(7)["isError"] is True
    assert not preview.exists()


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
        assert receive(2)["isError"] is False
        assert receive(3)["isError"] is False
        send("tools/call", {"name": "get_pixels_rect", "arguments": {
            "layer_name": "Layer 1", "frame_index": 1, "x": 0, "y": 0, "width": 2, "height": 1,
        }}, 4)
        result = receive(4)
        assert result["isError"] is False
        pixels = json.loads(result["content"][0]["text"])
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
