"""Layer management tools (layers.py)."""

from conftest import failure
from conftest import run

from aseprite_mcp.tools import canvas, drawing, layers


def test_rename_layer(sprite):
    run(canvas.add_layer(filename=sprite, layer_name="detail"))
    run(drawing.draw_ellipse_at(filename=sprite, layer_name="detail", frame_index=1, center_x=16, center_y=16, radius_x=6, radius_y=4, color="#306230", fill=True))
    run(layers.rename_layer(filename=sprite, layer_name="detail", new_name="shade"))


def test_duplicate_layer(sprite):
    result = run(layers.duplicate_layer(filename=sprite, layer_name="body"))
    assert "body copy" in result


def test_set_layer_blend_mode(sprite):
    run(layers.set_layer_blend_mode(filename=sprite, layer_name="body", mode="multiply"))


def test_set_layer_blend_mode_rejects_unknown(sprite):
    result = failure(layers.set_layer_blend_mode(filename=sprite, layer_name="body", mode="nonsense"))
    assert result.startswith("Unknown blend mode")


def test_reorder_layer(sprite):
    run(layers.reorder_layer(filename=sprite, layer_name="body", position=1))


def test_merge_layer_down(sprite):
    run(layers.merge_layer_down(filename=sprite, layer_name="body"))


def test_delete_layer(sprite):
    run(layers.delete_layer(filename=sprite, layer_name="body"))


def test_flatten_sprite(sprite):
    run(layers.flatten_sprite(filename=sprite))
