"""Decode delivered images and metadata, preserving projects and previous outputs on failure."""
import json
from pathlib import Path

import pytest
from PIL import Image
from mcp.server.mcpserver.exceptions import ToolError

from aseprite_mcp.core.commands import AsepriteCommand
from aseprite_mcp.core import state
from aseprite_mcp.tools import animation, canvas, drawing, export, sprite_map
from support import digest, run


def animated_project(new_sprite):
    filename = new_sprite()
    run(animation.add_frames(filename=filename, count=3, duration_ms=100))
    for frame, colour in enumerate(("#ff0000", "#00ff00", "#0000ff", "#ffff00"), 1):
        run(sprite_map.draw_sprite_map(filename=filename, layer_name="ink", frame_index=frame,
                                       rows=["A"], palette={"A": colour}))
    for frame, duration in ((2, 50), (3, 100), (4, 150)):
        run(canvas.set_frame_duration(filename=filename, frame_index=frame, duration_ms=duration))
    return filename


@pytest.mark.parametrize("direction,indices", [
    ("forward", [0, 1, 2]), ("reverse", [2, 1, 0]),
    ("pingpong", [0, 1, 2, 1]), ("pingpong_reverse", [2, 1, 0, 1]),
])
def test_animation_delivery_maps_tag_frames_and_ticks(new_sprite, tmp_path, direction, indices):
    filename = animated_project(new_sprite)
    run(animation.set_tag(filename=filename, name="clip", from_frame=2, to_frame=4, direction=direction))
    original = digest(filename)
    result = json.loads(run(export.export_minecraft_texture(
        filename=filename, output_filename=str(tmp_path / "texture.png"), tag_name="clip",
    )))
    metadata = json.loads(Path(result["mcmeta"]).read_text())
    assert metadata["animation"] == {
        "width": 16, "height": 16, "interpolate": False,
        "frames": [{"index": index, "time": [1, 2, 3][index]} for index in indices],
    }
    assert [frame["source_frame"] for frame in result["frames"]] == [2, 3, 4]
    colours = [(0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)]
    with Image.open(result["png"]) as image:
        rgba = image.convert("RGBA")
        assert image.size == (16, 48)
        for index, colour in enumerate(colours):
            assert rgba.getpixel((0, index * 16)) == colour
            assert rgba.getpixel((1, index * 16)) == (0, 0, 0, 0)
    with Image.open(result["preview_png"]) as image:
        assert image.size == (128, 384)
        for index, colour in enumerate(colours):
            assert all(image.getpixel((x, y + index * 128)) == colour for x in range(8) for y in range(8))
            assert image.getpixel((8, index * 128)) == (0, 0, 0, 0)
    assert digest(filename) == original


@pytest.mark.parametrize("size", [16, 32])
def test_static_delivery_and_review_lifetime(new_sprite, tmp_path, size):
    filename = new_sprite(size, size)
    run(sprite_map.draw_sprite_map(filename=filename, layer_name="ink", frame_index=1,
                                   rows=["A"], palette={"A": "#1234567f"}))
    original = digest(filename)
    result = json.loads(run(export.export_minecraft_texture(
        filename=filename, output_filename=str(tmp_path / "static.png"),
    )))
    assert json.loads(Path(result["mcmeta"]).read_text()) == {}
    with Image.open(result["png"]) as image:
        assert image.size == (size, size)
        assert image.convert("RGBA").getpixel((0, 0)) == (18, 52, 86, 127)
    with Image.open(result["preview_png"]) as image:
        assert image.size == (size * 8, size * 8)
        assert image.getpixel((7, 7)) == (18, 52, 86, 127)
    assert digest(filename) == original
    state.cleanup_review_directory()
    assert not Path(result["preview_png"]).exists()
    assert Path(result["png"]).exists()
    assert Path(result["mcmeta"]).exists()


def test_unrepresentable_timing_preserves_existing_outputs(new_sprite, tmp_path):
    filename = new_sprite()
    run(canvas.add_frame(filename=filename))
    run(canvas.set_frame_duration(filename=filename, frame_index=2, duration_ms=127))
    target = tmp_path / "texture.png"
    sidecar = tmp_path / "texture.png.mcmeta"
    target.write_bytes(b"old image")
    sidecar.write_bytes(b"old metadata")
    with pytest.raises(ToolError, match="Frame 2 duration 127"):
        run(export.export_minecraft_texture(filename=filename, output_filename=str(target)))
    assert target.read_bytes() == b"old image"
    assert sidecar.read_bytes() == b"old metadata"


def test_export_without_new_artifact_does_not_move_reference(new_sprite, tmp_path, monkeypatch):
    filename = new_sprite()
    target = tmp_path / "texture.png"
    reference = tmp_path / "texture_reference.png"
    target.write_bytes(b"old image")
    reference.write_bytes(b"reference")
    original = AsepriteCommand.run_command

    async def no_artifact(args):
        if "--save-as" in args:
            return ""
        return await original(args)

    monkeypatch.setattr(AsepriteCommand, "run_command", staticmethod(no_artifact))
    with pytest.raises(ToolError, match="no output file"):
        run(export.export_frame(filename=filename, frame_index=1, output_filename=str(target)))
    assert target.read_bytes() == b"old image"
    assert reference.read_bytes() == b"reference"


def test_publish_failure_restores_existing_pair(new_sprite, tmp_path, monkeypatch):
    filename = new_sprite()
    target, sidecar = tmp_path / "texture.png", tmp_path / "texture.png.mcmeta"
    target.write_bytes(b"old image")
    sidecar.write_bytes(b"old metadata")
    original = export.os.replace

    def fail_metadata(source, destination):
        if Path(destination) == sidecar:
            raise OSError("metadata destination locked")
        return original(source, destination)

    monkeypatch.setattr(export.os, "replace", fail_metadata)
    with pytest.raises(ToolError, match="Could not publish"):
        run(export.export_minecraft_texture(filename=filename, output_filename=str(target)))
    assert target.read_bytes() == b"old image"
    assert sidecar.read_bytes() == b"old metadata"


@pytest.mark.parametrize("corruption", ["png", "json", "layout"])
def test_corrupt_delivery_is_rejected_before_publication(new_sprite, tmp_path, monkeypatch, corruption):
    filename = new_sprite()
    target, sidecar = tmp_path / "texture.png", tmp_path / "texture.png.mcmeta"
    target.write_bytes(b"old image")
    sidecar.write_bytes(b"old metadata")
    original = AsepriteCommand.run_command

    async def corrupt_output(args):
        output = await original(args)
        if "--sheet" in args:
            sheet = Path(args[args.index("--sheet") + 1])
            data = Path(args[args.index("--data") + 1])
            if corruption == "png":
                sheet.write_bytes(b"not a PNG")
            elif corruption == "json":
                data.write_text("{broken", encoding="utf-8")
            else:
                data.write_text(json.dumps({"frames": [{}]}), encoding="utf-8")
        return output
    monkeypatch.setattr(AsepriteCommand, "run_command", corrupt_output)
    with pytest.raises(ToolError):
        run(export.export_minecraft_texture(filename=filename, output_filename=str(target)))
    assert target.read_bytes() == b"old image"
    assert sidecar.read_bytes() == b"old metadata"
    assert not list(tmp_path.glob(".aseprite-*-*"))


def test_numbered_png_export_publishes_only_this_sequence(new_sprite, tmp_path):
    filename = animated_project(new_sprite)
    reference = tmp_path / "texture_reference.png"
    reference.write_bytes(b"reference")
    result = run(export.export_sprite(filename=filename, output_filename=str(tmp_path / "texture.png")))
    outputs = sorted(path for path in tmp_path.glob("texture*.png") if path != reference)
    assert len(outputs) == 4
    for path, colour in zip(outputs, [(255,0,0,255), (0,255,0,255), (0,0,255,255), (255,255,0,255)]):
        assert str(path) in result
        with Image.open(path) as image:
            assert image.convert("RGBA").getpixel((0, 0)) == colour
    assert reference.read_bytes() == b"reference"


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
