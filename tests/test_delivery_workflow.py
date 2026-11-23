"""Decode delivered images and metadata, preserving projects and previous outputs on failure."""

import json
from pathlib import Path

import pytest
from jsonschema import validate
from PIL import Image
from mcp.server.mcpserver.exceptions import ToolError

from aseprite_mcp.core.commands import AsepriteCommand
from aseprite_mcp.core import editing, state
from aseprite_mcp.tools import animation, canvas, drawing, export, slices, sprite_map
from support import call, connected_server, digest, frame_image, payload, run


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
    result = payload(run(export.export_minecraft_texture(
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
    result = payload(run(export.export_minecraft_texture(
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


def test_named_indexed_slices_export_in_requested_order_over_stdio(tmp_path):
    source = tmp_path / "indexed.aseprite"
    run(editing.execute_edit_script("""
        local spr = Sprite(4, 1, ColorMode.INDEXED)
        local palette = Palette(3)
        palette:setColor(0, Color{r=0, g=0, b=0, a=0})
        palette:setColor(1, Color{r=255, g=153, b=34})
        palette:setColor(2, Color{r=1, g=2, b=3})
        spr:setPalette(palette)
        local image = Image(4, 1, ColorMode.INDEXED)
        image:putPixel(0, 0, 1)
        image:putPixel(2, 0, 2)
        spr:newCel(spr.layers[1], 1, image, Point(0, 0))
        local hidden = spr:newLayer()
        local upper = image:clone()
        upper:putPixel(0, 0, 2)
        spr:newCel(hidden, 1, upper, Point(0, 0))
        hidden.isVisible = false
        spr:newSlice(Rectangle(0, 0, 2, 1)).name = "left"
        spr:newSlice(Rectangle(2, 0, 2, 1)).name = "right"
        spr:newSlice(Rectangle(3, 0, 2, 1)).name = "outside"
        save_project(spr)
    """, output_filename=str(source)))
    expected = frame_image(str(source), 1, tmp_path)
    assert expected.getpixel((0, 0)) == (255, 153, 34, 255)
    assert expected.getpixel((2, 0)) == (1, 2, 3, 255)
    original = digest(source)

    with connected_server(env={"ASERITE_MCP_WORKSPACE": str(tmp_path)}) as (send, receive):
        discovery = call(send, receive, "search_tools", {"query": "套装纹理", "limit": 1})
        definition, = discovery["structuredContent"]["data"]["tools"]
        assert definition["name"] == "export_slices_to_minecraft" and definition["invocation"] == "call_tool"
        by_export = call(send, receive, "search_tools", {"query": "切片导出", "limit": 1})
        assert by_export["structuredContent"]["data"]["tools"][0]["name"] == definition["name"]

        def export_slices(names, directory):
            return call(send, receive, "call_tool", {"name": definition["name"], "arguments": {
                "filename": source.name, "slice_names": names, "output_directory": directory,
            }})

        result = export_slices(["right", "left"], "textures")
        assert result["isError"] is False, result
        validate(result["structuredContent"], definition["outputSchema"])
        deliveries = result["structuredContent"]["data"]
        assert [entry["slice_name"] for entry in deliveries] == ["right", "left"]
        for entry, offset in zip(deliveries, (2, 0)):
            assert Path(entry["png"]) == tmp_path / "textures" / f"{entry['slice_name']}.png"
            with Image.open(entry["png"]) as image:
                assert image.size == (2, 1)
                assert image.convert("RGBA").tobytes() == expected.crop((offset, 0, offset + 2, 1)).tobytes()
            assert json.loads(Path(entry["mcmeta"]).read_text(encoding="utf-8")) == {}

        result = export_slices(["left"], "subset")
        assert result["isError"] is False, result
        assert sorted(path.name for path in (tmp_path / "subset").iterdir()) == ["left.png", "left.png.mcmeta"]

        for names, message in [
            (["left", "missing"], "Slice not found: missing"),
            (["left", "outside"], "Slice outside the canvas: outside"),
            (["right", "right"], "unique"),
            (["left", "../escape"], "Invalid slice name"),
            (["con"], "Invalid slice name"),
        ]:
            failed = export_slices(names, "rejected")
            assert failed["isError"] is True, failed
            assert message in failed["content"][0]["text"], failed
            assert not (tmp_path / "rejected").exists()
        assert digest(source) == original

        assert call(send, receive, "add_frame", {"filename": source.name})["isError"] is False
        failed = export_slices(["left"], "animated")
        assert failed["isError"] is True, failed
        assert "single-frame" in failed["content"][0]["text"], failed
        assert not (tmp_path / "animated").exists()


def test_slice_batch_preserves_outputs_on_collision_and_publish_failure(new_sprite, tmp_path, monkeypatch):
    source = new_sprite(2, 1)
    run(slices.create_slice(filename=source, name="fresh", x=0, y=0, width=1, height=1))
    run(slices.create_slice(filename=source, name="saved", x=1, y=0, width=1, height=1))
    original = digest(source)
    saved_png, saved_metadata = tmp_path / "saved.png", tmp_path / "saved.png.mcmeta"
    saved_png.write_bytes(b"previous image")
    saved_metadata.write_bytes(b"previous metadata")
    fresh_png = tmp_path / "fresh.png"

    def export_batch():
        return run(export.export_slices_to_minecraft(
            filename=source, output_directory=str(tmp_path), slice_names=["fresh", "saved"],
        ))

    resolve = Path.resolve
    with monkeypatch.context() as patch:
        def resolve_alias(path, *args, **kwargs):
            return resolve(saved_png if path == fresh_png else path, *args, **kwargs)

        patch.setattr(Path, "resolve", resolve_alias)
        with pytest.raises(ToolError, match="distinct paths"):
            export_batch()

    replace = export.os.replace

    def fail_last_replacement(source_path, destination):
        if Path(destination) == saved_metadata:
            raise OSError("metadata destination locked")
        return replace(source_path, destination)

    monkeypatch.setattr(export.os, "replace", fail_last_replacement)
    with pytest.raises(ToolError, match="Could not publish"):
        export_batch()
    assert saved_png.read_bytes() == b"previous image"
    assert saved_metadata.read_bytes() == b"previous metadata"
    assert not fresh_png.exists() and not (tmp_path / "fresh.png.mcmeta").exists()
    assert digest(source) == original


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
        assert str(path) in payload(result)["files"]
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
