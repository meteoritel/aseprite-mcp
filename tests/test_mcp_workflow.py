"""Discover tools, author a project and deliver its pixels through real MCP."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

from PIL import Image
from jsonschema import validate

from support import FIXTURE_GLYPHS, REPO_ROOT, RESPONSE_TIMEOUT_SECONDS, call, connected_server

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


def test_core_je_delivery_and_extension_edit_in_one_session(tmp_path, bitmap_font):
    source, output = tmp_path / "贴图.aseprite", tmp_path / "贴图.png"
    palette = {"A": "#1234567f", "B": "#00ff00", "C": "#0000ff"}
    with connected_server() as (send, receive):
        output_schemas = {}
        def invoke(tool_name, **arguments):
            result = call(send, receive, tool_name, arguments)
            assert result["isError"] is False, result
            schema_name = arguments["name"] if tool_name == "call_tool" else tool_name
            validate(result["structuredContent"], output_schemas[schema_name])
            data = result["structuredContent"]["data"]
            if tool_name == "search_tools":
                output_schemas.update((tool["name"], tool["outputSchema"]) for tool in data["tools"])
            return data

        send("tools/list", {}, 10)
        initial_tools = receive(10)
        output_schemas.update((tool["name"], tool["outputSchema"]) for tool in initial_tools["tools"])
        invoke("create_canvas", width=16, height=16, filename=str(source))
        invoke("add_group", group_name="art")
        invoke("add_layer", layer_name="ink", group="art")
        invoke("draw_sprite_maps", maps=[
            {"layer_name": ["art", "ink"], "frame_index": 1, "rows": ["AB.", "..A"], "palette": palette},
            {"layer_name": "hidden", "frame_index": 1, "x": 15, "y": 15, "rows": ["M"], "palette": {"M": "#ff00ff"}},
        ])
        read_arguments = {"layer_name": "art/ink", "frame_index": 1, "x": 0, "y": 0, "width": 3, "height": 2, "palette": palette}
        first = invoke("get_sprite_map", **read_arguments)
        assert first["rows"] == ["AB.", "..A"]
        assert first["lossy"] is False
        assert first["palette"]["A"].lower() == "#1234567f"
        invoke("search_tools", query="validate_scene")
        validation = invoke("call_tool", name="validate_scene", arguments={"required_layers": [["art", "ink"]]})
        assert validation["missing_layers"] == [] and validation["missing_cels"] == []
        invoke("set_layer_visibility", layer_name="hidden", visible=False)
        assert invoke("copy_frame", source_frame=1)["frame"] == 2
        invoke("draw_sprite_map", layer_name="art/ink", frame_index=2, x=1, y=0,
               rows=[".C"], palette=palette, erase_transparent=True)
        assert invoke("get_sprite_map", **read_arguments)["rows"] == ["AB.", "..A"]
        assert invoke("get_sprite_map", **(read_arguments | {"frame_index": 2}))["rows"] == ["A.C", "..A"]
        reviewed = invoke("review_frame", frame_index=2)
        assert reviewed["map"]["source"] == "composite"
        assert reviewed["preview_lifetime"] == "session"
        frame_preview = Path(reviewed["preview_png"])
        with Image.open(frame_preview) as image:
            assert image.size == (128, 128)
            assert image.convert("RGBA").getpixel((16, 0)) == (0, 0, 255, 255)
        hidden = invoke("get_pixels_rect", layer_name="hidden", frame_index=2, x=15, y=15, width=1, height=1)
        assert (hidden[0]["r"], hidden[0]["b"], hidden[0]["a"]) == (255, 255, 255)

        definition = invoke("search_tools", query="draw_text", category="text")["tools"][0]
        assert definition["name"] == "draw_text"
        invoke("call_tool", name="draw_text", arguments={
            "text": "A", "font": bitmap_font, "x": 8, "y": 1,
            "layer_name": "label", "frame_index": 2, "color": "#ffcc00",
        })
        text_pixels = invoke("get_pixels_rect", layer_name="label", frame_index=2, x=8, y=1, width=4, height=6)
        assert [(p["r"], p["g"], p["b"], p["a"]) for p in text_pixels] == [
            (255, 204, 0, 255) if cell == "#" else (0, 0, 0, 0)
            for row in FIXTURE_GLYPHS["A"] for cell in row
        ]
        invoke("set_frame_duration", frame_index=1, duration_ms=100)
        invoke("set_frame_duration", frame_index=2, duration_ms=150)
        invoke("set_tag", name="loop", from_frame=1, to_frame=2, direction="reverse")
        before_export = source.read_bytes()
        artifacts = invoke("export_minecraft_texture", output_filename=str(output), tag_name="loop")
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
    assert not frame_preview.exists()
    assert source.exists() and output.exists() and Path(artifacts["mcmeta"]).exists()


def test_discover_and_execute_extensions_without_aseprite(bitmap_font):
    with connected_server(env={"ASEPRITE_PATH": "missing-aseprite-for-discovery-test"}) as (send, receive):
        send("tools/list", {}, 1)
        initial = receive(1)
        names = {tool["name"] for tool in initial["tools"]}
        assert {"draw_sprite_map", "get_sprite_map", "export_minecraft_texture", "search_tools", "call_tool"} <= names
        assert not names.intersection({"draw_text", "measure_text", "list_text_fonts"})

        measured = call(send, receive, "call_tool", {
            "name": "measure_text", "arguments": {"text": "A", "font": bitmap_font},
        })
        assert measured["isError"] is False
        assert measured["structuredContent"]["data"]["width"] == 4
        assert measured["structuredContent"]["data"]["height"] == 5
        assert measured["structuredContent"] == json.loads(measured["content"][0]["text"])
        assert call(send, receive, "measure_text", {"text": "A", "font": bitmap_font})["isError"] is True

        result = call(send, receive, "search_tools", {"query": "DRAW_TEXT frame_index", "category": "text"})
        definition = result["structuredContent"]["data"]["tools"][0]
        assert definition["name"] == "draw_text"
        schema = definition["inputSchema"]
        assert set(schema["required"]) == {"text", "x", "y", "font", "layer_name", "frame_index"}
        assert schema["properties"]["text"]["type"] == "string"
        assert schema["properties"]["frame_index"]["type"] == "integer"

        page_names, offset = [], 0
        while offset is not None:
            result = call(send, receive, "search_tools", {"category": "text", "limit": 1, "offset": offset})
            page = result["structuredContent"]["data"]
            assert page == json.loads(result["content"][0]["text"])["data"]
            page_names.extend(tool["name"] for tool in page["tools"])
            offset = page["next_offset"]
        assert page_names == ["list_text_fonts", "measure_text", "draw_text"]
        assert call(send, receive, "search_tools", {"limit": 0})["isError"] is True
        send("tools/list", {}, 2)
        assert receive(2) == initial


def test_failed_calls_preserve_project_and_allow_editing_again(tmp_path):
    source = tmp_path / "精灵" / "角色.aseprite"
    output = tmp_path / "审阅.png"
    layer_name = '画师\'s "ink"'
    with connected_server(env={"ASERITE_MCP_WORKSPACE": str(tmp_path)}) as (send, receive):
        assert call(send, receive, "get_sprite_info", {})["isError"] is True
        without_sprite = call(send, receive, "run_lua_script", {"script": 'print("无工程")'})
        assert without_sprite["isError"] is False
        assert without_sprite["structuredContent"]["data"]["stdout"].strip() == "无工程"
        assert call(send, receive, "create_canvas", {"width": 0, "height": 16, "filename": str(source)})["isError"] is True
        assert not source.exists()
        assert not call(send, receive, "create_canvas", {"width": 16, "height": 16, "filename": str(source)})["isError"]
        original = source.read_bytes()

        for name, arguments, diagnostic in [
            ("draw_pixels_at", {"layer_name": "missing", "frame_index": 1, "create_if_missing": False,
                                "pixels": [{"x": 0, "y": 0, "color": "#ff0000"}]}, "Existing layers:"),
            ("draw_pixels_at", {"layer_name": "Layer 1", "frame_index": 999,
                                "pixels": [{"x": 0, "y": 0, "color": "#ff0000"}]}, "1-based"),
            ("draw_pixels_at", {"layer_name": "Layer 1", "frame_index": 1,
                                "pixels": [{"x": "0); error('injected') --", "y": 0, "color": "#ff0000"}]}, "pixels.0.x"),
            ("draw_pixels_at", {"layer_name": "missing/child", "frame_index": 1,
                                "pixels": [{"x": 0, "y": 0, "color": "#ff0000"}]}, "not found"),
            ("get_sprite_info", {"filename": "../角色.aseprite"}, "traversal"),
            ("create_canvas", {"width": 8, "height": 8, "filename": str(source)}, "already exists"),
            ("call_tool", {"name": "create_canvas", "arguments": {}}, "create_canvas"),
            ("call_tool", {"name": "measure_text", "arguments": {}}, "measure_text"),
            ("call_tool", {"name": "measure_text", "arguments": {"text": "A", "font": "missing-font-for-test"}}, "measure_text"),
            ("run_lua_script", {"script": "local x = nil; print(x.y)"}, "attempt to index a nil value"),
        ]:
            result = call(send, receive, name, arguments)
            assert result["isError"] is True, (name, result)
            assert diagnostic in result["content"][0]["text"], result
            assert source.read_bytes() == original

        drawn = call(send, receive, "draw_pixels_at", {
            "filename": "精灵/角色.aseprite", "layer_name": layer_name, "frame_index": 1,
            "pixels": [{"x": 2, "y": 3, "color": "#1234567f"}],
        })
        assert drawn["isError"] is False, drawn
        printed = call(send, receive, "run_lua_script", {
            "script": 'local spr = app.activeSprite; print("中文:" .. spr.width .. "x" .. spr.height)',
        })
        assert printed["isError"] is False
        assert printed["structuredContent"]["data"]["stdout"].strip() == "中文:16x16"
        assert not call(send, receive, "export_frame", {
            "frame_index": 1, "output_filename": str(output), "scale": 2,
        })["isError"]
        with Image.open(output) as image:
            assert image.size == (32, 32)
            assert image.convert("RGBA").getpixel((4, 6)) == (18, 52, 86, 127)
        assert call(send, receive, "export_frame", {
            "frame_index": 999, "output_filename": str(tmp_path / "bad.png"),
        })["isError"] is True
        assert not (tmp_path / "bad.png").exists()
        assert not call(send, receive, "draw_pixels_at", {
            "layer_name": layer_name, "frame_index": 1,
            "pixels": [{"x": 0, "y": 0, "color": "#ff0000"}],
        })["isError"]
    assert source.exists()
    assert not list(source.parent.glob(".aseprite-edit-*"))
