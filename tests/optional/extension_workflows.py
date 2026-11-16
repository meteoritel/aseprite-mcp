"""Explicit extension workflows; run this file directly when these outputs matter."""

from support import payload

import json

from PIL import Image

from aseprite_mcp.tools import animation, drawing, export, fx, native_fx, pixel_read, slices, tilemap
from support import digest, failure, frame_image, run


def test_tilemap_paint_place_read_render_and_recover(new_sprite, tmp_path):
    filename = new_sprite(32, 32)
    run(tilemap.create_tilemap_layer(filename=filename, layer_name="terrain", tile_width=8, tile_height=8))
    for index, height, colour in [(1, 8, "#3e8948"), (2, 4, "#743f39")]:
        run(tilemap.draw_on_tile(filename=filename, layer_name="terrain", tile_index=index,
                                 pixels=[{"x": x, "y": y, "color": colour} for y in range(height) for x in range(8)]))
    run(tilemap.set_tiles(filename=filename, layer_name="terrain", frame_index=1,
                          tiles=[{"col": 0, "row": 0, "tile_index": 1}, {"col": 1, "row": 0, "tile_index": 2}]))
    info = payload(run(tilemap.get_tilemap_info(filename=filename, layer_name="terrain")))
    assert info == {"tile_width": 8, "tile_height": 8, "tile_count": 2, "map_cols": 4, "map_rows": 4}
    assert payload(run(tilemap.get_tile_at(filename=filename, layer_name="terrain", frame_index=1, col=1, row=0)))["tile_index"] == 2
    original = digest(filename)
    assert "get_tile_at" in failure(pixel_read.get_pixels_rect(
        filename=filename, layer_name="terrain", frame_index=1, x=0, y=0, width=1, height=1,
    ))
    assert "coordinates" in failure(tilemap.draw_on_tile(
        filename=filename, layer_name="terrain", tile_index=1,
        pixels=[{"x": "0); error('injected') --", "y": 0, "color": "#ff0000"}],
    ))
    assert "out of range" in failure(tilemap.set_tiles(
        filename=filename, layer_name="terrain", frame_index=1,
        tiles=[{"col": 0, "row": 0, "tile_index": 99}],
    ))
    assert digest(filename) == original
    run(tilemap.set_tiles(filename=filename, layer_name="terrain", frame_index=1,
                          tiles=[{"col": 2, "row": 0, "tile_index": 1}]))
    expected = Image.new("RGBA", (32, 32))
    expected.paste((62, 137, 72, 255), (0, 0, 8, 8))
    expected.paste((116, 63, 57, 255), (8, 0, 16, 4))
    expected.paste((62, 137, 72, 255), (16, 0, 24, 8))
    assert frame_image(filename, 1, tmp_path).tobytes() == expected.tobytes()
    pixels = payload(run(pixel_read.get_composite_rect(filename=filename, x=0, y=0, width=32, height=32)))
    assert bytes(channel for p in pixels for channel in (p["r"], p["g"], p["b"], p["a"])) == expected.tobytes()


def test_slice_metadata_round_trip_and_duplicate_recovery(sprite):
    name = "weird|name,x"
    run(slices.create_slice(filename=sprite, name=name, x=1, y=2, width=16, height=16))
    run(slices.set_slice_center(filename=sprite, name=name, x=4, y=4, width=8, height=8))
    run(slices.set_slice_pivot(filename=sprite, name=name, x=8, y=6))
    expected = [{"name": name, "x": 1, "y": 2, "width": 16, "height": 16,
                 "center": {"x": 4, "y": 4, "width": 8, "height": 8}, "pivot": {"x": 8, "y": 6}}]
    assert payload(run(slices.list_slices(filename=sprite))) == expected
    original = digest(sprite)
    assert "already exists" in failure(slices.create_slice(filename=sprite, name=name, x=0, y=0, width=8, height=8))
    assert digest(sprite) == original
    run(slices.delete_slice(filename=sprite, name=name))
    assert payload(run(slices.list_slices(filename=sprite))) == []


def test_native_colour_processing_and_palette_readback(new_sprite, tmp_path):
    filename = new_sprite(8, 8)
    colours = ["#000000", "#ff0000", "#00ff00", "#0000ff", "#ffff00"]
    run(drawing.draw_pixels_at(filename=filename, layer_name="ink", frame_index=1,
                               pixels=[{"x": x, "y": 0, "color": colour} for x, colour in enumerate(colours)]))
    extracted = payload(run(native_fx.extract_palette(filename=filename, max_colors=8)))
    assert sorted(extracted["colors"]) == ["#000000", "#0000FF", "#00FF00", "#FF0000", "#FFFF00"]
    assert extracted["transparent_index"] == 0
    assert extracted["palette_size"] == extracted["count"] + 1
    assert extracted["palette_size"] <= extracted["max_colors"]
    run(native_fx.invert_colors(filename=filename, layer_name="ink", frame_index=1))
    run(fx.replace_color(filename=filename, layer_name="ink", frame_index=1,
                          from_color="#00ffff", to_color="#123456", tolerance=0))
    expected = Image.new("RGBA", (8, 8))
    for x, colour in enumerate([(255, 255, 255, 255), (18, 52, 86, 255),
                                (255, 0, 255, 255), (255, 255, 0, 255), (0, 0, 255, 255)]):
        expected.putpixel((x, 0), colour)
    assert frame_image(filename, 1, tmp_path).tobytes() == expected.tobytes()


def test_layer_and_tagged_sheet_delivery(sprite, tmp_path):
    directory = tmp_path / "layers"
    run(export.export_layers(filename=sprite, output_directory=str(directory)))
    with Image.open(directory / "body.png") as image:
        assert image.size == (32, 32)
        assert image.convert("RGBA").getpixel((8, 8)) == (208, 70, 72, 255)
    run(animation.add_frames(filename=sprite, count=2, duration_ms=150))
    for frame, colour in [(2, "#00ff00"), (3, "#0000ff")]:
        run(drawing.draw_pixels_at(filename=sprite, layer_name="body", frame_index=frame,
                                   pixels=[{"x": 0, "y": 0, "color": colour}]))
    run(animation.set_tag(filename=sprite, name="clip", from_frame=1, to_frame=2))
    output, data = tmp_path / "sheet.png", tmp_path / "sheet.json"
    run(export.export_spritesheet(filename=sprite, output_filename=str(output), data_filename=str(data),
                                   sheet_type="horizontal", scale=2, padding=1, tag_name="clip"))
    frames = json.loads(data.read_text(encoding="utf-8"))["frames"]
    assert [frame["duration"] for frame in frames] == [100, 150]
    with Image.open(output) as image:
        assert image.size == (129, 64)
        rgba = image.convert("RGBA")
        for frame, corner in zip(frames, [(0, 0, 0, 0), (0, 255, 0, 255)]):
            rect = frame["frame"]
            assert (rect["w"], rect["h"]) == (64, 64)
            assert rgba.getpixel((rect["x"], rect["y"])) == corner
            assert rgba.getpixel((rect["x"] + 16, rect["y"] + 16)) == (208, 70, 72, 255)
