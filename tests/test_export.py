"""Export and import tools (export.py)."""
import os
import struct

from conftest import BASE, ok, run

from aseprite_mcp.tools import animation, export


def png_size(path):
    with open(path, "rb") as f:
        data = f.read(24)
    return struct.unpack(">II", data[16:24])


def test_export_frame_scaled(sprite):
    out = f"{BASE}/frame1.png"
    ok(run(export.export_frame(filename=sprite, frame_index=1, output_filename=out, scale=8)))
    assert png_size(out) == (256, 256)


def test_export_spritesheet_with_data(sprite):
    ok(run(animation.add_frames(filename=sprite, count=3, duration_ms=100)))
    out = f"{BASE}/sheet.png"
    data = f"{BASE}/sheet.json"
    ok(run(export.export_spritesheet(filename=sprite, output_filename=out, sheet_type="horizontal", data_filename=data, scale=2, padding=1)))
    assert os.path.exists(out) and os.path.exists(data)


def test_export_spritesheet_tag_filter(sprite):
    ok(run(animation.set_tag(filename=sprite, name="clip", from_frame=1, to_frame=2, direction="forward")))
    out = f"{BASE}/sheet_tag.png"
    ok(run(export.export_spritesheet(filename=sprite, output_filename=out, sheet_type="horizontal", data_filename="", scale=1, padding=0, tag_name="clip")))
    w, h = png_size(out)
    assert (w, h) == (64, 32), "tag filter must export only the 2 tagged frames"


def test_export_layers(sprite):
    result = ok(run(export.export_layers(filename=sprite, output_directory=f"{BASE}/layers")))
    assert ".png" in result


def test_export_tag_gif(sprite):
    out = f"{BASE}/clip.gif"
    ok(run(export.export_tag(filename=sprite, tag_name="clip", output_filename=out, scale=4)))
    assert os.path.exists(out)


def test_import_image_as_layer(sprite):
    ok(run(export.import_image_as_layer(filename=sprite, image_path=f"{BASE}/frame1.png", layer_name="ref", frame_index=1, x=0, y=0)))
