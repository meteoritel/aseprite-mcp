"""End-to-end tests for concurrency, palette sync, review upgrades, PNG fast paths, and bilingual discovery."""

from base64 import b64decode
from pathlib import Path
import time

from PIL import Image
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from aseprite_mcp.core import editing, state
from aseprite_mcp.core.commands import AsepriteCommand
from aseprite_mcp.tools import analysis, animation, canvas, native_fx, palette, review, slices, sprite_map
from support import call, connected_server, digest, failure, frame_image, payload, run


def _observe_processes(monkeypatch):
    observed = {"lua": 0, "cmd": 0, "commits": 0}
    orig_lua = AsepriteCommand.execute_lua_script
    orig_cmd = AsepriteCommand.run_command
    orig_replace = editing.os.replace

    async def counted_lua(script, source=None):
        observed["lua"] += 1
        return await orig_lua(script, source)

    async def counted_cmd(args):
        observed["cmd"] += 1
        return await orig_cmd(args)

    def counted_replace(src, dst):
        observed["commits"] += 1
        return orig_replace(src, dst)

    monkeypatch.setattr(AsepriteCommand, "execute_lua_script", staticmethod(counted_lua))
    monkeypatch.setattr(AsepriteCommand, "run_command", staticmethod(counted_cmd))
    monkeypatch.setattr(editing.os, "replace", counted_replace)
    return observed


def test_different_files_run_concurrently_over_stdio(tmp_path):
    """Two calls targeting distinct files must overlap in real time instead of serializing."""
    first = tmp_path / "a.aseprite"
    second = tmp_path / "b.aseprite"
    marker_a = tmp_path / "a.started"
    marker_b = tmp_path / "b.started"
    with connected_server() as (send, receive):
        assert not call(send, receive, "create_canvas", {"width": 4, "height": 4, "filename": str(first)}, 1)["isError"]
        assert not call(send, receive, "create_canvas", {"width": 4, "height": 4, "filename": str(second)}, 2)["isError"]

        def barrier_script(own_marker: Path, peer_marker: Path, r: int, g: int, b: int) -> str:
            return f'''
            local spr = app.activeSprite
            local f = io.open("{own_marker.as_posix()}", "w"); f:write("1"); f:close()
            local deadline = os.clock() + 8.0
            local seen = false
            while os.clock() < deadline do
                local p = io.open("{peer_marker.as_posix()}", "r")
                if p then p:close(); seen = true; break end
            end
            if not seen then error("Peer process did not run concurrently") end
            local cel = spr.layers[1]:cel(spr.frames[1])
            if not cel then cel = spr:newCel(spr.layers[1], spr.frames[1], Image(spr.width, spr.height, spr.colorMode), Point(0, 0)) end
            cel.image:putPixel(0, 0, app.pixelColor.rgba({r}, {g}, {b}, 255))
            spr:saveAs(spr.filename)
            print("OVERLAPPED")
            '''

        send("tools/call", {"name": "run_lua_script", "arguments": {
            "filename": str(first), "script": barrier_script(marker_a, marker_b, 255, 0, 0),
        }}, 10)
        send("tools/call", {"name": "run_lua_script", "arguments": {
            "filename": str(second), "script": barrier_script(marker_b, marker_a, 0, 0, 255),
        }}, 11)
        res_a = receive(10)
        res_b = receive(11)
        assert not res_a["isError"], res_a
        assert not res_b["isError"], res_b
        assert "OVERLAPPED" in res_a["structuredContent"]["data"]["stdout"]
        assert "OVERLAPPED" in res_b["structuredContent"]["data"]["stdout"]

    assert frame_image(str(first), 1, tmp_path).getpixel((0, 0)) == (255, 0, 0, 255)
    assert frame_image(str(second), 1, tmp_path).getpixel((0, 0)) == (0, 0, 255, 255)


def test_palette_merge_in_create_and_draw_uses_single_process(tmp_path, monkeypatch):
    project = tmp_path / "potion.aseprite"
    observed = _observe_processes(monkeypatch)
    colors = ["#1E1428", "#6DC2CA", "#DEEED6"]
    run(canvas.create_canvas(
        16, 16, filename=str(project), initial_layers=["back", "liquid", "front"], palette=colors,
    ))
    assert observed["lua"] == 1 and observed["commits"] == 1
    assert payload(run(palette.get_palette(filename=str(project)))) == colors

    observed["lua"] = 0
    observed["commits"] = 0
    run(sprite_map.draw_sprite_maps(
        filename=str(project),
        palette={"A": "#112233", "B": "#44556680"},
        sync_palette=True,
        maps=[
            {"layer_name": "back", "frame_index": 1, "rows": ["AB"]},
            {"layer_name": "front", "frame_index": 1, "rows": [".C"], "palette": {"C": "#778899"}},
        ],
    ))
    assert observed["lua"] == 1 and observed["commits"] == 1
    assert payload(run(palette.get_palette(filename=str(project)))) == ["#112233", "#445566", "#778899"]

    layered = tmp_path / "layered.aseprite"
    observed["lua"] = 0
    run(sprite_map.create_layered_sprite(
        filename=str(layered),
        rows=["AB"],
        palette={"A": "#AA1122", "B": "#33BB44"},
        layers=[
            {"name": "base", "mapping": {"A": "A", "B": "A"}},
            {"name": "top", "mapping": {"B": "B"}},
        ],
        sync_palette=True,
    ))
    assert observed["lua"] == 1
    assert payload(run(palette.get_palette(filename=str(layered)))) == ["#AA1122", "#33BB44"]


def test_workspace_env_precedence_and_relative_project_creation(tmp_path, monkeypatch):
    preferred = tmp_path / "preferred"
    legacy = tmp_path / "legacy"
    preferred.mkdir()
    legacy.mkdir()

    # Without configured workspace, relative create_canvas is still rejected.
    monkeypatch.delenv("ASEPRITE_MCP_WORKSPACE", raising=False)
    monkeypatch.delenv("ASERITE_MCP_WORKSPACE", raising=False)
    assert "ABSOLUTE" in failure(canvas.create_canvas(8, 8, filename="rel/item.aseprite"))

    # Legacy spelling continues to work.
    monkeypatch.setenv("ASERITE_MCP_WORKSPACE", str(legacy))
    receipt_legacy = payload(run(canvas.create_canvas(8, 8, filename="sub/legacy_item.aseprite")))
    assert Path(receipt_legacy["filename"]) == legacy / "sub" / "legacy_item.aseprite"
    assert (legacy / "sub" / "legacy_item.aseprite").is_file()

    # Correct spelling takes precedence over legacy spelling.
    monkeypatch.setenv("ASEPRITE_MCP_WORKSPACE", str(preferred))
    receipt_pref = payload(run(canvas.create_canvas(8, 8, filename="sub/new_item")))
    assert Path(receipt_pref["filename"]) == preferred / "sub" / "new_item.aseprite"
    assert (preferred / "sub" / "new_item.aseprite").is_file()

    # Traversal is still blocked.
    assert "traversal" in failure(canvas.create_canvas(8, 8, filename="../escape.aseprite"))


def test_review_backgrounds_grid_stable_palette_and_persistent_preview(tmp_path):
    project = tmp_path / "catfooted.aseprite"
    saved_preview = tmp_path / "reports" / "catfooted_preview.png"
    with connected_server() as (send, receive):
        def invoke(name, **arguments):
            res = call(send, receive, name, arguments)
            assert not res["isError"], res
            return res["structuredContent"]["data"], res["content"][1:]

        invoke("create_canvas", width=4, height=4, filename=str(project), initial_layers=["aura", "body"])
        invoke("draw_sprite_maps", filename=str(project), maps=[
            {"layer_name": "aura", "frame_index": 1, "rows": ["A...", "....", "....", "...."], "palette": {"A": "#3D1A7080"}},
            {"layer_name": "body", "frame_index": 1, "rows": [".B..", "....", "....", "...."], "palette": {"B": "#FF0000"}},
        ])

        # Multi-background preview strip + grid + persistent save.
        multi, blocks = invoke(
            "review_frame",
            filename=str(project),
            frame_index=1,
            backgrounds=["#303034", "mc_slot", "checker"],
            show_grid=True,
            save_preview_to=str(saved_preview),
        )
        assert len(blocks) == 1
        assert Path(multi["saved_preview_png"]) == saved_preview
        assert saved_preview.read_bytes() == b64decode(blocks[0]["data"])
        with Image.open(saved_preview) as strip:
            assert strip.width > 3 * 32  # 3 panels + margins + rulers
            assert strip.height > 32

        # Single solid background verifies exact alpha compositing over #303034.
        hud_only, _ = invoke(
            "review_frame",
            filename=str(project),
            frame_index=1,
            backgrounds=["#303034"],
            grid_mode="none",
        )
        assert hud_only["map"] is None and hud_only["map_unavailable"] == "omitted"
        with Image.open(hud_only["preview_png"]) as img:
            assert img.size == (32, 32)
            # Pixel (0,0) is #3D1A70 with alpha 0x80 (~50.2%) over #303034 -> ~(54, 37, 82, 255)
            r, g, b, a = img.getpixel((0, 0))
            assert a == 255 and 52 <= r <= 57 and 35 <= g <= 39 and 80 <= b <= 84
            # Pixel (1,0) is opaque red #FF0000
            assert img.getpixel((8, 0)) == (255, 0, 0, 255)
            # Pixel (2,0) is fully transparent -> pure #303034
            assert img.getpixel((16, 0)) == (0x30, 0x30, 0x34, 255)

        # Stable character palette across edits when passing before_id without manual palette.
        base_review, _ = invoke("review_frame", filename=str(project), frame_index=1)
        base_palette = base_review["map"]["palette"]
        red_key = next(k for k, v in base_palette.items() if v.lower() == "#ff0000")
        # Add a brand new color (#000001 sorts before existing colors!) and verify red keeps its key.
        invoke("draw_sprite_map", filename=str(project), layer_name="body", frame_index=1,
               rows=["..C."], palette={"C": "#000001"})
        next_review, _ = invoke("review_frame", filename=str(project), frame_index=1, before_id=base_review["snapshot_id"])
        assert next_review["map"]["palette"][red_key].lower() == "#ff0000"
        assert "#000001" in [v.lower() for v in next_review["map"]["palette"].values()]
        assert next_review["changes"]["composite"]["changed_pixels"] == 1
        session_preview = Path(multi["preview_png"])

    # Persistent preview survives session shutdown while session preview is cleaned up.
    assert saved_preview.is_file()
    assert not session_preview.exists()


def test_review_contact_sheet_multi_file_with_png_frames_and_slices(tmp_path, monkeypatch):
    first = tmp_path / "normal_potion.aseprite"
    second = tmp_path / "splash_potion.aseprite"
    ref_png = tmp_path / "vanilla_potion.png"
    saved = tmp_path / "set_sheet.png"

    run(canvas.create_canvas(4, 4, filename=str(first), initial_layers=["ink"]))
    run(sprite_map.draw_sprite_map(filename=str(first), layer_name="ink", frame_index=1, rows=["AA"], palette={"A": "#ff0000"}))
    run(animation.add_frames(filename=str(first), count=1))
    run(sprite_map.draw_sprite_map(filename=str(first), layer_name="ink", frame_index=2, rows=[".B"], palette={"B": "#00ff00"}))
    run(slices.create_slice(filename=str(first), name="left", x=0, y=0, width=2, height=4))
    run(slices.create_slice(filename=str(first), name="right", x=2, y=0, width=2, height=4))

    run(canvas.create_canvas(4, 4, filename=str(second), initial_layers=["ink"]))
    run(sprite_map.draw_sprite_map(filename=str(second), layer_name="ink", frame_index=1, rows=["CC"], palette={"C": "#0000ff"}))

    ref = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    ref.putpixel((0, 0), (255, 255, 0, 255))
    ref.save(ref_png)

    # Anchor `first` as active file and verify contact sheet never changes it.
    state.set_active_file(str(first))
    observed = _observe_processes(monkeypatch)

    result = run(review.review_contact_sheet(
        filenames=[str(first), str(second), str(ref_png)],
        backgrounds=["mc_hud", "mc_slot"],
        scale=4,
        save_preview_to=str(saved),
    ))
    data = payload(result)
    assert observed["lua"] == 1  # Both native .aseprite files rendered in ONE Aseprite process!
    assert state.get_active_file() == str(first)
    assert [entry["label"] for entry in data["entries"]] == ["normal_potion", "splash_potion", "vanilla_potion"]
    assert data["backgrounds"] == ["mc_hud", "mc_slot"]
    assert Path(data["saved_preview_png"]) == saved and saved.is_file()
    assert len(result.content) == 2 and result.content[1].type == "image"

    # Multi-frame mode.
    observed["lua"] = 0
    frames_sheet = payload(run(review.review_contact_sheet(
        filename=str(first), frame_indices=[1, 2], backgrounds=["checker"], scale=4,
    )))
    assert observed["lua"] == 1
    assert [entry["frame"] for entry in frames_sheet["entries"]] == [1, 2]

    # Multi-slice mode.
    observed["lua"] = 0
    slices_sheet = payload(run(review.review_contact_sheet(
        filename=str(first), slice_names=["left", "right"], scale=4,
    )))
    assert observed["lua"] == 1
    assert [(e["slice_name"], e["width"], e["height"]) for e in slices_sheet["entries"]] == [
        ("left", 2, 4), ("right", 2, 4),
    ]
    state.cleanup_review_directory()


def test_external_png_read_fast_path_zero_subprocesses_and_preserves_active_file(tmp_path, monkeypatch):
    project = tmp_path / "work.aseprite"
    run(canvas.create_canvas(4, 4, filename=str(project)))
    assert state.get_active_file() == str(project)

    ref_png = tmp_path / "reference.png"
    img = Image.new("RGBA", (4, 2), (0, 0, 0, 0))
    img.putpixel((0, 0), (255, 0, 0, 255))
    img.putpixel((1, 0), (255, 0, 0, 255))
    img.putpixel((2, 0), (0, 255, 0, 128))
    img.save(ref_png)
    before_bytes = digest(ref_png)

    observed = _observe_processes(monkeypatch)

    stats = payload(run(analysis.get_color_stats(filename=str(ref_png))))
    assert stats["unique_colors"] == 2 and stats["opaque_pixels"] == 3
    assert stats["top_colors"][0] == {"color": "#FF0000", "count": 2}

    grid = payload(run(sprite_map.get_sprite_map(filename=str(ref_png))))
    assert grid["source"] == "composite" and grid["width"] == 4 and grid["height"] == 2
    assert len(grid["palette"]) == 2

    reviewed = payload(run(review.review_frame(filename=str(ref_png), frame_index=1, backgrounds=["mc_hud"])))
    assert reviewed["region"] == {"x": 0, "y": 0, "width": 4, "height": 2}

    extracted = payload(run(native_fx.extract_palette(filename=str(ref_png), max_colors=8)))
    assert extracted["count"] == 2 and set(extracted["colors"]) == {"#FF0000", "#00FF00"}
    assert extracted["transparent_index"] == 0

    assert observed["lua"] == 0 and observed["cmd"] == 0  # Zero Aseprite subprocesses!
    assert digest(ref_png) == before_bytes
    assert state.get_active_file() == str(project)
    state.cleanup_review_directory()


def test_batch_grid_diagnostics_aggregate_errors_and_majority_width(new_sprite):
    filename = new_sprite(8, 8)
    # rows[0] has typo (3 chars) while rows[1..3] have 4 chars -> majority width is 4, blames rows[0]!
    err = failure(sprite_map.draw_sprite_maps(
        filename=filename,
        palette={"A": "#ff0000", "B": "#00ff00"},
        maps=[
            {"layer_name": "base", "frame_index": 1, "rows": ["AAA", "AAAA", "AAAA", "AAAA"]},
            {"layer_name": "top", "frame_index": 1, "rows": ["AZB", "ABQ"]},
        ],
    ))
    assert "2 error(s)" in err
    assert 'maps[0] (layer_name="base")' in err
    assert "3 of 4 rows have 4 character(s) but rows[0] has 3" in err
    assert 'maps[1] (layer_name="top")' in err
    assert "Unknown character 'Z' at row 0, column 1" in err
    assert "Unknown character 'Q' at row 1, column 2" in err
    assert "Available palette keys: ['A', 'B']" in err


def test_bilingual_intent_discovery_and_guidance_bootstrapping():
    with connected_server(env={"ASEPRITE_PATH": "missing-aseprite-discovery"}) as (send, receive):
        send("tools/list", {}, 1)
        tools = {tool["name"]: tool for tool in receive(1)["tools"]}
        assert "review_contact_sheet" in tools
        assert "outline_native" in tools["search_tools"]["description"]
        assert "copy_layers_between_sprites" in tools["search_tools"]["description"]
        assert "search_tools" in tools["run_lua_script"]["description"]

        for query, expected_any in [
            ("描边", {"outline_native", "outline_cel"}),
            ("轮廓加边", {"outline_native"}),
            ("亮度", {"adjust_brightness_contrast"}),
            ("变暗", {"adjust_brightness_contrast"}),
            ("跨文件 复制图层", {"copy_layers_between_sprites"}),
            ("copy layer between files", {"copy_layers_between_sprites"}),
            ("copy layer across sprites", {"copy_layers_between_sprites"}),
            ("拼图", {"review_contact_sheet"}),
            ("contact sheet", {"review_contact_sheet"}),
            ("side by side compare", {"review_contact_sheet"}),
            ("参考图", {"review_contact_sheet", "get_color_stats", "get_sprite_map", "extract_palette"}),
            ("切片", {"create_slice", "export_slices_to_minecraft"}),
            ("模糊", {"apply_convolution"}),
            ("色阶", {"generate_color_ramp"}),
            ("文字", {"draw_text"}),
            ("补间", {"tween_cel_positions"}),
        ]:
            reply = call(send, receive, "search_tools", {"query": query, "limit": 5})
            assert not reply["isError"], (query, reply)
            found = {item["name"] for item in reply["structuredContent"]["data"]["tools"]}
            assert found & expected_any, f"query={query!r} expected one of {expected_any}, got {found}"
