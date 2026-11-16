"""Drawing tools added in this round (drawing.py)."""

from conftest import failure
from conftest import run

from aseprite_mcp.tools import drawing, pixel_read


def test_draw_ellipse_at(sprite):
    run(drawing.draw_ellipse_at(filename=sprite, layer_name="body", frame_index=1, center_x=16, center_y=16, radius_x=6, radius_y=4, color="#306230", fill=True))
    px = run(pixel_read.get_pixel_color(filename=sprite, x=16, y=16, layer_name="body", frame_index=1))
    assert "#306230" in px


def test_draw_ellipse_rejects_bad_radius(sprite):
    result = failure(drawing.draw_ellipse_at(filename=sprite, layer_name="body", frame_index=1, center_x=16, center_y=16, radius_x=0, radius_y=4, color="#306230"))
    assert "must be > 0" in result
