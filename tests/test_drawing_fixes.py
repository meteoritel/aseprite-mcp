"""B3 (cel-normalization, no silent clip) + B4 (per-pixel alpha) fixes."""

from conftest import failure
from conftest import run

from aseprite_mcp.tools import canvas, drawing, pixel_read


def _rgba(pixel_result: str) -> tuple[int, int, int, int]:
    s = str(pixel_result)
    return (int(s.split("r=")[1].split(",")[0]),
            int(s.split("g=")[1].split(",")[0]),
            int(s.split("b=")[1].split(",")[0]),
            int(s.split("a=")[1].split(")")[0]))


def test_polygon_offcanvas_vertices_no_clip(sprite):
    # Two vertices are outside the 32x32 canvas; pset() must bounds-guard
    # (no crash) and the in-canvas fill must still land at sprite-global (16,16).
    run(canvas.add_layer(filename=sprite, layer_name="poly"))
    pts = [{"x": 16, "y": -5}, {"x": -5, "y": 30}, {"x": 30, "y": 30}]
    run(drawing.draw_polygon(filename=sprite, layer_name="poly", frame_index=1, points=pts, color="#00FF00", fill=True, create_if_missing=True))
    r, g, b, _ = _rgba(run(pixel_read.get_pixel_color(filename=sprite, x=16, y=16, layer_name="poly", frame_index=1)))
    assert (r, g, b) == (0, 255, 0), (r, g, b)


def test_gradient_lands_at_sprite_global(sprite):
    run(canvas.add_layer(filename=sprite, layer_name="grad"))
    run(drawing.apply_gradient_rect(filename=sprite, layer_name="grad", frame_index=1, x=4, y=4, width=16, height=1, color_start="#000000", color_end="#FFFFFF", horizontal=True, create_if_missing=True))
    left = _rgba(run(pixel_read.get_pixel_color(filename=sprite, x=4, y=4, layer_name="grad", frame_index=1)))
    right = _rgba(run(pixel_read.get_pixel_color(filename=sprite, x=19, y=4, layer_name="grad", frame_index=1)))
    assert left[0] < right[0], (left, right)  # dark -> light, left to right


def test_draw_accepts_rgba_alpha(sprite):
    # "#RRGGBBAA" was rejected before B4 (len != 6) and left the layer empty.
    run(canvas.add_layer(filename=sprite, layer_name="alpha"))
    run(drawing.draw_pixels_at(filename=sprite, layer_name="alpha", frame_index=1, pixels=[{"x": 6, "y": 6, "color": "#FF000080"}], create_if_missing=True))
    r, g, b, a = _rgba(run(pixel_read.get_pixel_color(filename=sprite, x=6, y=6, layer_name="alpha", frame_index=1)))
    assert (r, g, b) == (255, 0, 0)
    assert a == 0x80  # semi-transparency preserved


def test_draw_accepts_short_hex(sprite):
    run(canvas.add_layer(filename=sprite, layer_name="short"))
    run(drawing.draw_pixels_at(filename=sprite, layer_name="short", frame_index=1, pixels=[{"x": 5, "y": 5, "color": "#0F0"}], create_if_missing=True))
    assert _rgba(run(pixel_read.get_pixel_color(filename=sprite, x=5, y=5, layer_name="short", frame_index=1))) == (0, 255, 0, 255)


def test_draw_rejects_bad_hex(sprite):
    run(canvas.add_layer(filename=sprite, layer_name="bad"))
    res = failure(drawing.draw_pixels_at(filename=sprite, layer_name="bad", frame_index=1, pixels=[{"x": 0, "y": 0, "color": "#GG0000"}], create_if_missing=True))
    assert res.startswith(("Invalid", "Failed"))
