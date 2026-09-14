"""Layer management tools (layers.py)."""
from conftest import ok, run

from aseprite_mcp.tools import canvas, drawing, layers


def test_rename_layer(sprite):
    ok(run(canvas.add_layer(filename=sprite, layer_name="detail")))
    ok(run(drawing.draw_ellipse_at(filename=sprite, layer_name="detail", frame_index=1, center_x=16, center_y=16, radius_x=6, radius_y=4, color="#306230", fill=True)))
    ok(run(layers.rename_layer(filename=sprite, layer_name="detail", new_name="shade")))


def test_duplicate_layer(sprite):
    result = ok(run(layers.duplicate_layer(filename=sprite, layer_name="shade")))
    assert "shade copy" in result


def test_set_layer_blend_mode(sprite):
    ok(run(layers.set_layer_blend_mode(filename=sprite, layer_name="shade copy", mode="multiply")))


def test_set_layer_blend_mode_rejects_unknown(sprite):
    result = run(layers.set_layer_blend_mode(filename=sprite, layer_name="shade copy", mode="nonsense"))
    assert result.startswith("Unknown blend mode")


def test_reorder_layer(sprite):
    ok(run(layers.reorder_layer(filename=sprite, layer_name="shade copy", position=1)))


def test_merge_layer_down(sprite):
    ok(run(layers.merge_layer_down(filename=sprite, layer_name="body")))


def test_delete_layer(sprite):
    ok(run(layers.delete_layer(filename=sprite, layer_name="shade")))


def test_flatten_sprite(sprite):
    ok(run(layers.flatten_sprite(filename=sprite)))
