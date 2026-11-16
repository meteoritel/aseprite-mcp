"""Export artifacts are decoded and verified independently with Pillow."""
import json
from pathlib import Path

from PIL import Image

from conftest import run
from aseprite_mcp.tools import animation, drawing, export, pixel_read


def test_export_frame_scaled(sprite, tmp_path):
    out = tmp_path / "frame1.png"
    run(export.export_frame(filename=sprite, frame_index=1, output_filename=str(out), scale=8))
    with Image.open(out) as image:
        assert image.size == (256, 256)
        assert image.convert("RGBA").getpixel((64, 64)) == (208, 70, 72, 255)
        assert image.convert("RGBA").getpixel((0, 0)) == (0, 0, 0, 0)


def test_export_spritesheet_with_data(sprite, tmp_path):
    run(animation.add_frames(filename=sprite, count=3, duration_ms=100))
    out, data = tmp_path / "sheet.png", tmp_path / "sheet.json"
    run(export.export_spritesheet(filename=sprite, output_filename=str(out), sheet_type="horizontal", data_filename=str(data), scale=2, padding=1))
    frames = json.loads(data.read_text())["frames"]
    assert [f["duration"] for f in frames] == [100] * 4
    with Image.open(out) as image:
        assert image.height == 64
        assert image.width == 4 * 64 + 3
        for frame in frames:
            rect = frame["frame"]
            assert (rect["w"], rect["h"]) == (64, 64)
            assert image.convert("RGBA").getpixel((rect["x"] + 16, rect["y"] + 16)) == (208, 70, 72, 255)


def test_export_spritesheet_tag_filter(sprite, tmp_path):
    run(animation.add_frames(filename=sprite, count=2, duration_ms=100))
    run(animation.set_tag(filename=sprite, name="clip", from_frame=2, to_frame=3, direction="forward"))
    out = tmp_path / "sheet_tag.png"
    run(export.export_spritesheet(filename=sprite, output_filename=str(out), tag_name="clip"))
    with Image.open(out) as image:
        assert image.size == (64, 32)


def test_export_layers(sprite, tmp_path):
    result = run(export.export_layers(filename=sprite, output_directory=str(tmp_path)))
    out = tmp_path / "body.png"
    assert str(out) in result
    with Image.open(out) as image:
        assert image.size == (32, 32)
        assert image.convert("RGBA").getpixel((8, 8)) == (208, 70, 72, 255)


def test_export_tag_gif(sprite, tmp_path):
    run(animation.add_frames(filename=sprite, count=1, duration_ms=150))
    run(drawing.draw_pixels_at(filename=sprite, layer_name="body", frame_index=2,
        pixels=[{"x": 0, "y": 0, "color": "#00ff00"}]))
    run(animation.set_tag(filename=sprite, name="clip", from_frame=1, to_frame=2))
    out = tmp_path / "clip.gif"
    run(export.export_tag(filename=sprite, tag_name="clip", output_filename=str(out), scale=4))
    with Image.open(out) as image:
        assert image.size == (128, 128)
        assert image.n_frames == 2
        assert image.info["duration"] == 100
        image.seek(1)
        assert image.info["duration"] == 150
        assert image.convert("RGBA").getpixel((0, 0)) == (0, 255, 0, 255)


def test_import_image_as_layer(sprite, tmp_path):
    source = tmp_path / "reference.png"
    Image.new("RGBA", (3, 2), (12, 34, 56, 127)).save(source)
    run(export.import_image_as_layer(filename=sprite, image_path=str(source), layer_name="ref", frame_index=1, x=2, y=3))
    pixels = json.loads(run(pixel_read.get_pixels_rect(filename=sprite, layer_name="ref", frame_index=1, x=2, y=3, width=3, height=2)))
    assert [(p["r"], p["g"], p["b"], p["a"]) for p in pixels] == [(12, 34, 56, 127)] * 6
