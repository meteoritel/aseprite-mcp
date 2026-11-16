"""Stable discovery, extension dispatch and editing through real MCP stdio."""

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
from test_text import bitmap_font, FIXTURE_GLYPHS


@contextmanager
def connected_server(*, env=None, code=None):
    env = dict(os.environ, PYTHONPATH=REPO_ROOT) | (env or {})
    command = [sys.executable, "-m", "aseprite_mcp"] if code is None else [sys.executable, "-c", code]
    server = subprocess.Popen(
        command, cwd=REPO_ROOT, env=env,
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
                assert "error" not in response, response
                return response["result"]
            assert time.monotonic() < deadline, f"No response for {request_id}"

    try:
        send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "editing-test", "version": "1"}}, 0)
        initialized = receive(0)
        assert initialized["instructions"] == (Path(REPO_ROOT) / "SKILL.md").read_text(encoding="utf-8").strip()
        send("notifications/initialized", {})
        yield send, receive
        server.stdin.close()
        assert server.wait(timeout=RESPONSE_TIMEOUT_SECONDS) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait(timeout=5)


def call(send, receive, name, arguments, request_id=1):
    send("tools/call", {"name": name, "arguments": arguments}, request_id)
    return receive(request_id)


def test_extension_discovery_is_stable_and_needs_no_aseprite():
    from mcp.server.mcpserver.tools import Tool
    from aseprite_mcp.tools.text import draw_text

    with connected_server(env={"ASEPRITE_PATH": "missing-aseprite-for-discovery-test"}) as (send, receive):
        send("tools/list", {}, 1)
        initial = receive(1)
        names = {tool["name"] for tool in initial["tools"]}
        assert {"draw_sprite_map", "get_sprite_map", "export_minecraft_texture", "search_tools", "call_tool"} <= names
        assert not names.intersection({"draw_text", "list_text_fonts", "set_onion_skin", "animation_workflow_guide"})

        # A known extension can be executed before any search.
        fonts = call(send, receive, "call_tool", {"name": "list_text_fonts", "arguments": {}})
        assert fonts["isError"] is False
        assert isinstance(fonts["content"][0]["text"], str)
        assert fonts["structuredContent"]["result"] == fonts["content"][0]["text"]
        assert call(send, receive, "list_text_fonts", {})["isError"] is True

        result = call(send, receive, "search_tools", {"query": "DRAW_TEXT", "category": "text"})
        data = json.loads(result["content"][0]["text"])
        assert data == result["structuredContent"]
        definition = data["tools"][0]
        assert definition["name"] == "draw_text"
        actual = Tool.from_function(draw_text)
        assert definition["inputSchema"] == actual.parameters
        assert definition["outputSchema"] == actual.output_schema
        assert set(definition["inputSchema"]["required"]) == {"text", "x", "y", "font", "layer_name", "frame_index"}
        assert json.loads(call(send, receive, "search_tools", {"query": "zz-no-matching-tool"})["content"][0]["text"])["tools"] == []
        # All words must match, including parameter names.
        words = json.loads(call(send, receive, "search_tools", {"query": "draw_text frame_index"})["content"][0]["text"])
        assert [tool["name"] for tool in words["tools"]] == ["draw_text"]

        for category in data["available_categories"]:
            page_names, offset = [], 0
            while offset is not None:
                page = json.loads(call(send, receive, "search_tools", {
                    "category": category, "limit": 1, "offset": offset,
                })["content"][0]["text"])
                assert all(tool["category"] == category for tool in page["tools"])
                page_names.extend(tool["name"] for tool in page["tools"])
                offset = page["next_offset"]
            assert len(page_names) == len(set(page_names))
            whole = json.loads(call(send, receive, "search_tools", {"category": category, "limit": 20})["content"][0]["text"])
            assert page_names == [tool["name"] for tool in whole["tools"]]
        assert json.loads(call(send, receive, "search_tools", {"offset": 999})["content"][0]["text"])["next_offset"] is None
        for arguments in ({"limit": 0}, {"limit": 21}, {"offset": -1}, {"category": "unknown"}):
            assert call(send, receive, "search_tools", arguments)["isError"] is True
        send("tools/list", {}, 2)
        assert receive(2) == initial
    with connected_server() as (send, receive):
        send("tools/list", {}, 1)
        assert receive(1) == initial


def test_proxy_rejects_invalid_targets_arguments_and_business_failures():
    with connected_server() as (send, receive):
        for name in ("create_canvas", "search_tools", "call_tool", "set_onion_skin", "animation_workflow_guide", "unknown"):
            result = call(send, receive, "call_tool", {"name": name, "arguments": {}})
            assert result["isError"] is True
            assert name in result["content"][0]["text"]
        for arguments in ({}, {"text": "A", "font": "unused", "size": []}, {"text": "A", "font": "missing-font-for-test"}):
            result = call(send, receive, "call_tool", {"name": "measure_text", "arguments": arguments})
            assert result["isError"] is True
            assert "measure_text" in result["content"][0]["text"]


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
            pixels = json.loads(call(send, receive, "get_pixels_rect", {
                "layer_name": "ink", "frame_index": 1, "x": 0, "y": 0, "width": 2, "height": 1,
            })["content"][0]["text"])
            assert pixels[0] == {"x": 0, "y": 0, "r": 0, "g": 255, "b": 0, "a": 255, "hex": "#00ff00"}
            assert pixels[1]["a"] == (255 if mode == "serial" else 0)
            assert not call(send, receive, "call_tool", {"name": "draw_text", "arguments": arguments})["isError"]
    if mode == "disconnect":
        assert source.read_bytes() == before
    assert not list(tmp_path.glob(".aseprite-edit-*"))


def test_core_je_delivery_and_extension_edit_in_one_session(tmp_path, bitmap_font):
    source, output = tmp_path / "texture.aseprite", tmp_path / "texture.png"
    palette = {"A": "#1234567f", "B": "#00ff00", "C": "#0000ff"}
    with connected_server() as (send, receive):
        def invoke(tool_name, **arguments):
            result = call(send, receive, tool_name, arguments)
            assert result["isError"] is False, result
            return result["content"][0]["text"]

        send("tools/list", {}, 10)
        initial_tools = receive(10)
        invoke("create_canvas", width=16, height=16, filename=str(source))
        invoke("add_group", group_name="art")
        invoke("add_layer", layer_name="ink", group="art")
        invoke("draw_sprite_map", layer_name="art/ink", frame_index=1,
               rows=["AB.", "..A"], palette=palette)
        read_arguments = {"layer_name": "art/ink", "frame_index": 1, "x": 0, "y": 0, "width": 3, "height": 2, "palette": palette}
        first = json.loads(invoke("get_sprite_map", **read_arguments))
        assert first["rows"] == ["AB.", "..A"]
        assert first["lossy"] is False
        assert first["palette"]["A"].lower() == "#1234567f"
        invoke("draw_pixels_at", layer_name="hidden", frame_index=1,
               pixels=[{"x": 15, "y": 15, "color": "#ff00ff"}])
        invoke("set_layer_visibility", layer_name="hidden", visible=False)
        invoke("copy_frame", source_frame=1)
        invoke("draw_sprite_map", layer_name="art/ink", frame_index=2, x=1, y=0,
               rows=[".C"], palette=palette, erase_transparent=True)
        assert json.loads(invoke("get_sprite_map", **read_arguments))["rows"] == ["AB.", "..A"]
        assert json.loads(invoke("get_sprite_map", **(read_arguments | {"frame_index": 2})))["rows"] == ["A.C", "..A"]
        hidden = json.loads(invoke("get_pixels_rect", layer_name="hidden", frame_index=2, x=15, y=15, width=1, height=1))
        assert (hidden[0]["r"], hidden[0]["b"], hidden[0]["a"]) == (255, 255, 255)

        definition = json.loads(invoke("search_tools", query="draw_text", category="text"))["tools"][0]
        assert definition["name"] == "draw_text"
        invoke("call_tool", name="draw_text", arguments={
            "text": "A", "font": bitmap_font, "x": 8, "y": 1,
            "layer_name": "label", "frame_index": 2, "color": "#ffcc00",
        })
        text_pixels = json.loads(invoke("get_pixels_rect", layer_name="label", frame_index=2, x=8, y=1, width=4, height=6))
        assert [(p["r"], p["g"], p["b"], p["a"]) for p in text_pixels] == [
            (255, 204, 0, 255) if cell == "#" else (0, 0, 0, 0)
            for row in FIXTURE_GLYPHS["A"] for cell in row
        ]
        invoke("set_frame_duration", frame_index=1, duration_ms=100)
        invoke("set_frame_duration", frame_index=2, duration_ms=150)
        invoke("set_tag", name="loop", from_frame=1, to_frame=2, direction="reverse")
        before_export = source.read_bytes()
        artifacts = json.loads(invoke("export_minecraft_texture", output_filename=str(output), tag_name="loop"))
        assert source.read_bytes() == before_export
        assert [frame["source_frame"] for frame in artifacts["frames"]] == [1, 2]
        metadata = json.loads(Path(artifacts["mcmeta"]).read_text())
        assert metadata == {"animation": {"width": 16, "height": 16, "interpolate": False,
                                           "frames": [{"index": 1, "time": 3}, {"index": 0, "time": 2}]}}
        expected = Image.new("RGBA", (16, 32))
        for offset in (0, 16):
            expected.putpixel((0, offset), (18, 52, 86, 127))
            expected.putpixel((2, offset + 1), (18, 52, 86, 127))
        expected.putpixel((1, 0), (0, 255, 0, 255))
        expected.putpixel((2, 16), (0, 0, 255, 255))
        for y, row in enumerate(FIXTURE_GLYPHS["A"]):
            for x, cell in enumerate(row):
                if cell == "#":
                    expected.putpixel((8 + x, 17 + y), (255, 204, 0, 255))
        with Image.open(output) as png:
            assert png.size == (16, 32)
            assert png.convert("RGBA").tobytes() == expected.tobytes()
        preview = Path(artifacts["preview_png"])
        with Image.open(preview) as png:
            assert png.size == (128, 256)
            assert png.convert("RGBA").tobytes() == expected.resize((128, 256), Image.Resampling.NEAREST).tobytes()
        send("tools/list", {}, 11)
        assert receive(11) == initial_tools
    assert not preview.exists()
    assert source.exists() and output.exists() and Path(artifacts["mcmeta"]).exists()


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
