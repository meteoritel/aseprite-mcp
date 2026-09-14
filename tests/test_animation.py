"""Frame, cel, and tag tools added to animation.py."""
import json

from conftest import ok, run

from aseprite_mcp.tools import animation


def test_add_frames(sprite):
    ok(run(animation.add_frames(filename=sprite, count=3, duration_ms=100)))
    info = json.loads(run(animation.get_sprite_info(filename=sprite)))
    assert info["frames"] == 4


def test_set_cel_opacity(sprite):
    ok(run(animation.set_cel_opacity(filename=sprite, layer_name="body", frame_index=1, opacity=200)))


def test_set_and_delete_tag(sprite):
    ok(run(animation.set_tag(filename=sprite, name="walk", from_frame=1, to_frame=3, direction="forward")))
    ok(run(animation.delete_tag(filename=sprite, name="walk")))
    info = json.loads(run(animation.get_sprite_info(filename=sprite)))
    assert info["tags"] == []


def test_delete_tag_missing(sprite):
    result = run(animation.delete_tag(filename=sprite, name="nope"))
    assert "Tag not found" in result


def test_delete_frame(sprite):
    ok(run(animation.delete_frame(filename=sprite, frame_index=4)))
    info = json.loads(run(animation.get_sprite_info(filename=sprite)))
    assert info["frames"] == 3
