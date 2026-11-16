"""Native project edits preserve source content and explicit targets."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from PIL import Image

from conftest import run
from aseprite_mcp.tools import animation, canvas, drawing, sprite_map


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).digest()


def frame_image(filename, frame_index, directory):
    """Use Aseprite CLI independently of the production export implementation."""
    output = Path(directory) / "oracle.png"
    result = subprocess.run(
        [os.environ["ASEPRITE_PATH"], "--batch", filename,
         "--frame-range", f"{frame_index - 1},{frame_index - 1}",
         "--save-as", str(output)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    produced = list(Path(directory).glob("oracle*.png"))
    assert len(produced) == 1, produced
    with Image.open(produced[0]) as image:
        return image.convert("RGBA")


def paint(filename, layer="ink", frame=1):
    run(sprite_map.draw_sprite_map(
        filename=filename, layer_name=layer, frame_index=frame,
        rows=["A..", ".B."], palette={"A": "#ff0000", "B": "#00ff00"},
    ))


def test_same_frame_copy_preserves_project(new_sprite, tmp_path):
    filename = new_sprite()
    paint(filename)
    original = digest(filename)
    run(animation.copy_frame(filename=filename, source_frame=1, target_frame=1))
    assert digest(filename) == original
    image = frame_image(filename, 1, tmp_path)
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert image.getpixel((1, 1)) == (0, 255, 0, 255)
    assert image.getpixel((2, 0)) == (0, 0, 0, 0)


def test_frame_copy_descends_nested_groups(new_sprite, tmp_path):
    filename = new_sprite()
    run(canvas.add_group(filename=filename, group_name="outer"))
    run(canvas.add_group(filename=filename, group_name="inner", parent_group="outer"))
    run(canvas.add_layer(filename=filename, layer_name="ink", group="outer/inner"))
    run(canvas.add_frame(filename=filename))
    paint(filename, "outer/inner/ink")
    run(animation.copy_frame(filename=filename, source_frame=1, target_frame=2))
    image = frame_image(filename, 2, tmp_path)
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert image.getpixel((1, 1)) == (0, 255, 0, 255)


def test_explicit_draw_changes_only_selected_cel(new_sprite, tmp_path):
    filename = new_sprite()
    run(canvas.add_frame(filename=filename))
    run(drawing.draw_pixels_at(
        filename=filename, layer_name="ink", frame_index=2,
        pixels=[{"x": 2, "y": 3, "color": "#123456"}],
    ))
    image = frame_image(filename, 2, tmp_path)
    assert image.getpixel((2, 3)) == (18, 52, 86, 255)


def test_mirror_and_erase_share_one_pixel_semantics(new_sprite, tmp_path):
    filename = new_sprite()
    run(sprite_map.draw_sprite_map(
        filename=filename, layer_name="ink", frame_index=1,
        rows=["A..."], palette={"A": "#ff0000"},
        mirror_x=True, erase_transparent=True,
    ))
    image = frame_image(filename, 1, tmp_path)
    assert [image.getpixel((x, 0)) for x in range(4)] == [
        (255, 0, 0, 255), (0, 0, 0, 0), (0, 0, 0, 0), (255, 0, 0, 255),
    ]


@pytest.mark.parametrize("size", [16, 32])
def test_exact_grid_round_trip_preserves_alpha_and_outside_region(new_sprite, tmp_path, size):
    filename = new_sprite(size, size)
    run(sprite_map.draw_sprite_map(
        filename=filename, layer_name="ink", frame_index=1,
        rows=["ABCD"], palette={"A": "#ff000001", "B": "#ff00007f", "C": "#ff000080", "D": "#ff0000ff"},
        x=1, y=2,
    ))
    run(drawing.draw_pixels_at(filename=filename, layer_name="ink", frame_index=1,
                               pixels=[{"x": size - 1, "y": size - 1, "color": "#123456"}]))
    read = json.loads(run(sprite_map.get_sprite_map(
        filename=filename, layer_name="ink", frame_index=1,
        x=1, y=2, width=4, height=1, transparent="0",
    )))
    assert read["lossy"] is False
    assert "0" not in read["palette"]
    run(sprite_map.draw_sprite_map(
        filename=filename, layer_name="ink", frame_index=1, x=1, y=2,
        rows=read["rows"], palette=read["palette"], transparent=read["transparent"], erase_transparent=True,
    ))
    image = frame_image(filename, 1, tmp_path)
    assert [image.getpixel((x, 2)) for x in range(1, 5)] == [
        (255, 0, 0, 1), (255, 0, 0, 127), (255, 0, 0, 128), (255, 0, 0, 255),
    ]
    assert image.getpixel((size - 1, size - 1)) == (18, 52, 86, 255)

from aseprite_mcp.core.commands import AsepriteCommand
from aseprite_mcp.core import editing
from mcp.server.mcpserver.exceptions import ToolError
import asyncio


def test_copies_preserve_hidden_cel_metadata_and_target_timing(new_sprite):
    filename = new_sprite()
    run(AsepriteCommand.execute_lua_script_checked('''
        local spr = app.activeSprite
        local group = spr:newGroup(); group.name = "grp"; group.isVisible = false
        local layer = spr:newLayer(); layer.name = "ink"; layer.parent = group
        spr:newFrame(); spr:newFrame()
        local image = Image(2, 1, spr.colorMode)
        image:putPixel(0, 0, app.pixelColor.rgba(12, 34, 56, 255))
        local cel = spr:newCel(layer, spr.frames[2], image, Point(3, 4))
        cel.opacity = 127; cel.zIndex = 1
        spr.frames[1].duration = 0.05; spr.frames[2].duration = 0.1; spr.frames[3].duration = 0.15
        local tag = spr:newTag(spr.frames[1], spr.frames[3]); tag.name = "keep"
        spr:saveAs(spr.filename)
    ''', filename))
    run(animation.copy_frame(filename=filename, source_frame=2, target_frame=1))
    run(animation.propagate_frame_to_range(filename=filename, source_frame=2, start_frame=1, end_frame=3))
    run(animation.propagate_cels(filename=filename, layer_names=["grp/ink"], source_frame=2, start_frame=1, end_frame=3))
    run(animation.copy_cel(filename=filename, layer_name="grp/ink", source_frame=2, target_frame=3))
    output = run(AsepriteCommand.execute_lua_script_checked('''
        local spr = app.activeSprite
        local group = spr.layers[2]; local layer = group.layers[1]
        assert(not group.isVisible)
        assert(#spr.tags == 1 and spr.tags[1].name == "keep")
        for index, duration in ipairs({0.05, 0.1, 0.15}) do
            assert(math.abs(spr.frames[index].duration - duration) < 0.001)
            local cel = layer:cel(spr.frames[index])
            assert(cel.position == Point(3, 4) and cel.opacity == 127 and cel.zIndex == 1)
            local pixel = cel.image:getPixel(0, 0)
            assert(app.pixelColor.rgbaR(pixel) == 12 and app.pixelColor.rgbaG(pixel) == 34 and app.pixelColor.rgbaB(pixel) == 56)
        end
        print("VERIFIED")
    ''', filename))
    assert output.strip() == "VERIFIED"


def test_invalid_targets_and_failed_commit_preserve_project(new_sprite, monkeypatch):
    filename = new_sprite()
    paint(filename)
    original = digest(filename)
    for args in [{"layer_name": "missing", "frame_index": 1}, {"layer_name": "ink", "frame_index": 99}]:
        with pytest.raises(ToolError):
            run(drawing.draw_pixels_at(filename=filename, **args, create_if_missing=False,
                pixels=[{"x": 0, "y": 0, "color": "#ffffff"}]))
        assert digest(filename) == original
    replace = editing.os.replace

    def fail_commit(source, destination):
        if str(destination) == filename:
            raise OSError("project destination locked")
        return replace(source, destination)
    monkeypatch.setattr(editing.os, "replace", fail_commit)
    with pytest.raises(ToolError, match="destination locked"):
        run(drawing.draw_pixels_at(filename=filename, layer_name="ink", frame_index=1,
            pixels=[{"x": 0, "y": 0, "color": "#ffffff"}]))
    assert digest(filename) == original
    assert not list(Path(filename).parent.glob(".aseprite-edit-*"))


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


def test_large_pixel_read_fits_output_budget(new_sprite):
    from aseprite_mcp.tools import pixel_read
    filename = new_sprite(256, 256)
    run(drawing.draw_rectangle_at(filename=filename, layer_name="ink", frame_index=1,
        x=0, y=0, width=256, height=256, color="#123456", fill=True))
    pixels = json.loads(run(pixel_read.get_pixels_rect(filename=filename, layer_name="ink", frame_index=1,
        x=0, y=0, width=256, height=256)))
    assert len(pixels) == 256 * 256
    assert all((p["r"], p["g"], p["b"], p["a"]) == (18, 52, 86, 255) for p in pixels)


def test_create_native_requires_explicit_overwrite_and_anchors_after_success(new_sprite, tmp_path):
    from aseprite_mcp.core.state import get_active_file
    filename = new_sprite()
    paint(filename)
    original = digest(filename)
    with pytest.raises(ToolError, match="already exists"):
        run(canvas.create_canvas(8, 8, filename=filename))
    assert digest(filename) == original
    with pytest.raises(ToolError, match="editable project"):
        run(canvas.create_canvas(8, 8, filename=str(tmp_path / "wrong.png")))
    assert get_active_file() == filename
    run(canvas.create_canvas(8, 8, filename=filename, overwrite=True))
    assert json.loads(run(animation.get_sprite_info(filename=filename)))["width"] == 8
    target = tmp_path / "新目录" / "新工程"
    run(canvas.create_canvas(16, 16, filename=str(target)))
    assert target.with_suffix(".aseprite").exists()
    assert get_active_file() == str(target.with_suffix(".aseprite"))


def test_duplicate_frame_range_copies_groups_and_source_timing(new_sprite, tmp_path):
    filename = new_sprite()
    run(canvas.add_group(filename=filename, group_name="group"))
    run(canvas.add_layer(filename=filename, layer_name="ink", group="group"))
    paint(filename, "group/ink")
    run(canvas.set_frame_duration(filename=filename, frame_index=1, duration_ms=150))
    run(animation.duplicate_frame_range(filename=filename, start_frame=1, end_frame=1, times=2))
    info = json.loads(run(animation.get_sprite_info(filename=filename)))
    assert info["durations_ms"] == [150, 150, 150]
    image = frame_image(filename, 3, tmp_path)
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert image.getpixel((1, 1)) == (0, 255, 0, 255)


def test_mirrored_colour_conflict_preserves_project(new_sprite):
    filename = new_sprite()
    paint(filename)
    original = digest(filename)
    with pytest.raises(ToolError, match="[Cc]onflict"):
        run(sprite_map.draw_sprite_map(filename=filename, layer_name="ink", frame_index=1,
            rows=["AB"], palette={"A": "#ff0000", "B": "#00ff00"}, mirror_x=True, erase_transparent=True))
    assert digest(filename) == original


def test_position_creation_rejects_invalid_source_frame(new_sprite):
    filename = new_sprite()
    paint(filename)
    original = digest(filename)
    with pytest.raises(ToolError, match="Source frame index out of range"):
        run(animation.set_cel_position(filename=filename, layer_name="ink", frame_index=1,
            x=0, y=0, create_if_missing=True, source_frame_index=999))
    assert digest(filename) == original
