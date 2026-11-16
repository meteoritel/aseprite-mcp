"""Frame, cel, and tag tools added to animation.py."""

from conftest import failure
import json

from conftest import run

from aseprite_mcp.tools import animation, pixel_read


def test_add_frames(sprite):
    run(animation.add_frames(filename=sprite, count=3, duration_ms=100))
    info = json.loads(run(animation.get_sprite_info(filename=sprite)))
    assert info["frames"] == 4


def test_set_cel_opacity(sprite):
    run(animation.set_cel_opacity(filename=sprite, layer_name="body", frame_index=1, opacity=200))
    pixel = run(pixel_read.get_composite_pixel(filename=sprite, frame_index=1, x=8, y=8))
    assert "a=200" in pixel


def test_set_and_delete_tag(sprite):
    run(animation.add_frames(filename=sprite, count=3, duration_ms=100))
    run(animation.set_tag(filename=sprite, name="walk", from_frame=1, to_frame=3, direction="forward"))
    info = json.loads(run(animation.get_sprite_info(filename=sprite)))
    assert info["tags"] == [{"name": "walk", "from": 1, "to": 3, "direction": "forward"}]
    run(animation.delete_tag(filename=sprite, name="walk"))
    info = json.loads(run(animation.get_sprite_info(filename=sprite)))
    assert info["tags"] == []


def test_delete_tag_missing(sprite):
    result = failure(animation.delete_tag(filename=sprite, name="nope"))
    assert "Tag not found" in result


def test_delete_frame(sprite):
    run(animation.add_frames(filename=sprite, count=3, duration_ms=100))
    run(animation.delete_frame(filename=sprite, frame_index=4))
    info = json.loads(run(animation.get_sprite_info(filename=sprite)))
    assert info["frames"] == 3
