"""Saved native projects preserve pixel semantics, targets and unaffected content."""
import json
from pathlib import Path

import pytest
from PIL import Image
from mcp.server.mcpserver.exceptions import ToolError

from aseprite_mcp.core import editing
from aseprite_mcp.core.commands import AsepriteCommand
from aseprite_mcp.tools import animation, canvas, drawing, export, layers, pixel_read, selection, sprite_map
from support import digest, frame_image, paint, run


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


def test_explicit_draw_changes_only_selected_cel(new_sprite, tmp_path):
    filename = new_sprite()
    paint(filename, "guard")
    run(canvas.add_layer(filename=filename, layer_name="ink"))
    run(canvas.add_frame(filename=filename))
    original_first_frame = frame_image(filename, 1, tmp_path).tobytes()
    run(drawing.draw_pixels_at(
        filename=filename, layer_name="ink", frame_index=2,
        pixels=[{"x": 2, "y": 3, "color": "#123456"}],
    ))
    image = frame_image(filename, 2, tmp_path)
    assert image.getpixel((2, 3)) == (18, 52, 86, 255)
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert frame_image(filename, 1, tmp_path).tobytes() == original_first_frame
    guard = json.loads(run(pixel_read.get_pixels_rect(
        filename=filename, layer_name="guard", frame_index=2,
        x=0, y=0, width=3, height=4,
    )))
    assert [(p["r"], p["g"], p["b"], p["a"]) for p in guard] == [
        (255, 0, 0, 255) if (x, y) == (0, 0) else
        (0, 255, 0, 255) if (x, y) == (1, 1) else (0, 0, 0, 0)
        for y in range(4) for x in range(3)
    ]


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
    original = digest(filename)
    with pytest.raises(ToolError, match="[Cc]onflict"):
        run(sprite_map.draw_sprite_map(
            filename=filename, layer_name="ink", frame_index=1,
            rows=["AB"], palette={"A": "#ff0000", "B": "#00ff00"},
            mirror_x=True, erase_transparent=True,
        ))
    assert digest(filename) == original
    run(sprite_map.draw_sprite_map(
        filename=filename, layer_name="ink", frame_index=1,
        rows=[".B.."], palette={"B": "#00ff00"},
    ))
    image = frame_image(filename, 1, tmp_path)
    assert [image.getpixel((x, 0)) for x in range(4)] == [
        (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 0, 0), (255, 0, 0, 255),
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
    read["palette"] = {char: colour.replace("ff0000", "00ff00") for char, colour in read["palette"].items()}
    run(sprite_map.draw_sprite_map(
        filename=filename, layer_name="ink", frame_index=1, x=1, y=2,
        rows=read["rows"], palette=read["palette"], transparent=read["transparent"], erase_transparent=True,
    ))
    image = frame_image(filename, 1, tmp_path)
    assert [image.getpixel((x, 2)) for x in range(1, 5)] == [
        (0, 255, 0, 1), (0, 255, 0, 127), (0, 255, 0, 128), (0, 255, 0, 255),
    ]
    assert image.getpixel((size - 1, size - 1)) == (18, 52, 86, 255)


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


def test_copy_move_and_erase_regions(sprite, tmp_path):
    run(selection.copy_region(filename=sprite, layer_name="body", frame_index=1,
        x=8, y=8, width=4, height=4, dest_x=0, dest_y=0))
    image = frame_image(sprite, 1, tmp_path)
    red = (208, 70, 72, 255)
    clear = (0, 0, 0, 0)
    assert image.getpixel((0, 0)) == red
    assert image.getpixel((8, 8)) == red
    assert image.getpixel((4, 0)) == clear
    run(selection.move_region(filename=sprite, layer_name="body", frame_index=1,
        x=0, y=0, width=4, height=4, dest_x=24, dest_y=24))
    image = frame_image(sprite, 1, tmp_path)
    assert image.getpixel((0, 0)) == clear
    assert image.getpixel((24, 24)) == red
    assert image.getpixel((8, 8)) == red
    run(selection.erase_region(filename=sprite, layer_name="body", frame_index=1,
        x=24, y=24, width=4, height=4))
    image = frame_image(sprite, 1, tmp_path)
    assert image.getpixel((24, 24)) == clear
    assert image.getpixel((8, 8)) == red
    run(selection.erase_color(filename=sprite, layer_name="body", frame_index=1,
        color="#D04648", tolerance=0))
    assert frame_image(sprite, 1, tmp_path).getbbox() is None
    reference = tmp_path / "reference.png"
    Image.new("RGBA", (3, 2), (12, 34, 56, 127)).save(reference)
    run(export.import_image_as_layer(
        filename=sprite, image_path=str(reference), layer_name="ref", frame_index=1, x=2, y=3,
    ))
    expected = Image.new("RGBA", (32, 32))
    expected.paste((12, 34, 56, 127), (2, 3, 5, 5))
    assert frame_image(sprite, 1, tmp_path).tobytes() == expected.tobytes()


def test_grouped_copies_preserve_hidden_cel_metadata_and_timing(new_sprite):
    filename = new_sprite()
    run(canvas.add_group(filename=filename, group_name="outer"))
    run(canvas.add_group(filename=filename, group_name="inner", parent_group="outer"))
    run(canvas.add_layer(filename=filename, layer_name="ink", group="outer/inner"))
    run(AsepriteCommand.execute_lua_script_checked('''
        local spr = app.activeSprite
        local group = spr.layers[2]; group.isVisible = false
        local layer = group.layers[1].layers[1]
        for index = 2, 7 do spr:newFrame() end
        local image = Image(2, 1, spr.colorMode)
        image:putPixel(0, 0, app.pixelColor.rgba(12, 34, 56, 255))
        local cel = spr:newCel(layer, spr.frames[2], image, Point(3, 4))
        cel.opacity = 127; cel.zIndex = 1
        for index, frame in ipairs(spr.frames) do frame.duration = index * 0.05 end
        local tag = spr:newTag(spr.frames[1], spr.frames[7]); tag.name = "keep"
        spr:saveAs(spr.filename)
    ''', filename))
    # Disjoint destinations keep later copies from concealing an earlier failed edit.
    run(animation.copy_frame(filename=filename, source_frame=2, target_frame=1))
    run(animation.copy_cel(filename=filename, layer_name="outer/inner/ink", source_frame=2, target_frame=3))
    run(animation.propagate_frame_to_range(filename=filename, source_frame=2, start_frame=4, end_frame=5))
    run(animation.propagate_cels(filename=filename, layer_names=["outer/inner/ink"], source_frame=2, start_frame=6, end_frame=7))
    run(animation.duplicate_frame_range(filename=filename, start_frame=2, end_frame=2, times=2))
    output = run(AsepriteCommand.execute_lua_script_checked('''
        local spr = app.activeSprite
        local group = spr.layers[2]; local layer = group.layers[1].layers[1]
        assert(not group.isVisible)
        assert(#spr.tags == 1 and spr.tags[1].name == "keep")
        assert(#spr.frames == 9)
        for index, frame in ipairs(spr.frames) do
            local duration = index <= 7 and index * 0.05 or 0.1
            assert(math.abs(frame.duration - duration) < 0.001)
            local cel = layer:cel(frame)
            assert(cel.position == Point(3, 4) and cel.opacity == 127 and cel.zIndex == 1)
            local pixel = cel.image:getPixel(0, 0)
            assert(app.pixelColor.rgbaR(pixel) == 12 and app.pixelColor.rgbaG(pixel) == 34 and app.pixelColor.rgbaB(pixel) == 56)
        end
        print("VERIFIED")
    ''', filename))
    assert output.strip() == "VERIFIED"


def test_layer_paths_resolve_ambiguous_names_and_preserve_hierarchy(new_sprite):
    filename = new_sprite()
    run(canvas.add_group(filename=filename, group_name="abc/x"))
    run(canvas.add_layer(filename=filename, layer_name="y", group="abc/x"))
    run(canvas.add_group(filename=filename, group_name="abc"))
    run(canvas.add_group(filename=filename, group_name="x", parent_group="abc"))
    # Build the genuine hierarchy directly because the existing slash-named group takes precedence.
    run(AsepriteCommand.execute_lua_script_checked('''
        local spr = app.activeSprite
        local group = spr.layers[3].layers[1]
        local z = spr:newLayer(); z.name = "z"; z.parent = group
        local duplicate = spr:newLayer(); duplicate.name = "dupe"; duplicate.parent = group
        local top = spr:newLayer(); top.name = "dupe"
        spr:saveAs(spr.filename)
    ''', filename))
    run(layers.rename_layer(filename=filename, layer_name="abc/x/y", new_name="renamed"))
    for name, colour in [("abc/x/renamed", "#ff0000"), ("abc/x/z", "#00ff00"),
                         ("dupe", "#0000ff"), ("abc/x/dupe", "#ffff00")]:
        run(drawing.draw_pixels_at(filename=filename, layer_name=name, frame_index=1,
                                   pixels=[{"x": 0, "y": 0, "color": colour}]))
    run(AsepriteCommand.execute_lua_script_checked('''
        local spr = app.activeSprite
        local slash = spr.layers[2]
        local genuine = spr.layers[3].layers[1]
        assert(slash.name == "abc/x" and slash.layers[1].name == "renamed")
        local function check(layer, red, green, blue)
            local pixel = layer:cel(spr.frames[1]).image:getPixel(0, 0)
            assert(app.pixelColor.rgbaR(pixel) == red and app.pixelColor.rgbaG(pixel) == green and app.pixelColor.rgbaB(pixel) == blue)
        end
        check(slash.layers[1], 255, 0, 0)
        check(genuine.layers[1], 0, 255, 0)
        check(genuine.layers[2], 255, 255, 0)
        check(spr.layers[4], 0, 0, 255)
    ''', filename))
    info = json.loads(run(animation.get_sprite_info(filename=filename)))
    renamed = next(layer for layer in info["layers"] if layer["name"] == "renamed")
    assert renamed["parent"] == "abc/x"


def test_failed_commit_preserves_source_and_allows_next_edit(new_sprite, tmp_path, monkeypatch):
    filename = new_sprite()
    paint(filename)
    original = digest(filename)
    replace = editing.os.replace

    def fail_commit(source, destination):
        if str(destination) == filename:
            raise OSError("project destination locked")
        return replace(source, destination)

    with monkeypatch.context() as fault:
        fault.setattr(editing.os, "replace", fail_commit)
        with pytest.raises(ToolError, match="destination locked"):
            run(drawing.draw_pixels_at(filename=filename, layer_name="ink", frame_index=1,
                                       pixels=[{"x": 0, "y": 0, "color": "#ffffff"}]))
    assert digest(filename) == original
    assert not list(Path(filename).parent.glob(".aseprite-edit-*"))
    run(drawing.draw_pixels_at(filename=filename, layer_name="ink", frame_index=1,
                               pixels=[{"x": 0, "y": 0, "color": "#ffffff"}]))
    assert frame_image(filename, 1, tmp_path).getpixel((0, 0)) == (255, 255, 255, 255)
