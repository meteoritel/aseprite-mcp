"""Create or duplicate layers inside explicit groups; reject invalid parents."""
import json

import pytest

from conftest import BASE, failure, run
from aseprite_mcp.tools import animation, canvas, drawing, layers


def _top_level(path):
    """Map of top-level layer name -> is_group.

    get_sprite_info now enumerates nested layers too (each with a "parent"),
    so filter to parent==None for the top level.
    """
    info = json.loads(run(animation.get_sprite_info(filename=path)))
    return {layer["name"]: layer["is_group"]
            for layer in info["layers"] if layer.get("parent") is None}


@pytest.fixture
def fresh(base_dir, request):
    path = f"{BASE}/cig_{request.node.name}.aseprite"
    run(canvas.create_canvas(width=16, height=16, filename=path))
    return path


def test_add_group_top_level(fresh):
    run(canvas.add_group(filename=fresh, group_name="GRP"))
    assert _top_level(fresh).get("GRP") is True


def test_add_layer_into_group(fresh):
    run(canvas.add_group(filename=fresh, group_name="GRP"))
    run(canvas.add_layer(filename=fresh, layer_name="child", group="GRP"))
    assert "child" not in _top_level(fresh), "child must be inside GRP, not top level"
    # reachable by path and (recursively) by bare name
    run(drawing.draw_rectangle_at(filename=fresh, layer_name="GRP/child", frame_index=1, x=0, y=0, width=4, height=4, color="#ffffff", fill=True))
    run(layers.rename_layer(filename=fresh, layer_name="child", new_name="child_renamed"))


def test_add_group_nested_then_layer_two_deep(fresh):
    run(canvas.add_group(filename=fresh, group_name="GRP"))
    run(canvas.add_group(filename=fresh, group_name="SUB", parent_group="GRP"))
    assert "SUB" not in _top_level(fresh), "SUB must be inside GRP"
    run(canvas.add_layer(filename=fresh, layer_name="deep", group="GRP/SUB"))
    run(drawing.draw_rectangle_at(filename=fresh, layer_name="GRP/SUB/deep", frame_index=1, x=0, y=0, width=2, height=2, color="#ffffff", fill=True))


def test_duplicate_into_group(fresh):
    run(canvas.add_layer(filename=fresh, layer_name="body"))
    run(drawing.draw_rectangle_at(filename=fresh, layer_name="body", frame_index=1, x=0, y=0, width=8, height=8, color="#D04648", fill=True))
    run(canvas.add_group(filename=fresh, group_name="GRP"))
    run(layers.duplicate_layer(filename=fresh, layer_name="body", new_name="body_copy", group="GRP"))
    assert "body_copy" not in _top_level(fresh), "copy must be inside GRP"
    run(drawing.draw_rectangle_at(filename=fresh, layer_name="GRP/body_copy", frame_index=1, x=0, y=0, width=2, height=2, color="#ffffff", fill=True))


def test_add_layer_unknown_group_fails(fresh):
    result = failure(canvas.add_layer(filename=fresh, layer_name="child", group="NOPE"))


def test_add_layer_target_not_a_group_fails(fresh):
    run(canvas.add_layer(filename=fresh, layer_name="plain"))  # a normal layer, not a group
    result = failure(canvas.add_layer(filename=fresh, layer_name="child", group="plain"))
