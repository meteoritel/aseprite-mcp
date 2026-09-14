"""Pixel-art effect tools (fx.py)."""
from conftest import ok, run

from aseprite_mcp.tools import drawing, fx, pixel_read


def test_outline_cel(sprite):
    ok(run(fx.outline_cel(filename=sprite, layer_name="body", frame_index=1, color="#140C1C", include_diagonals=False)))


def test_replace_color_changes_pixels(sprite):
    ok(run(drawing.draw_rectangle_at(filename=sprite, layer_name="body", frame_index=1, x=10, y=10, width=4, height=4, color="#D04648", fill=True)))
    result = ok(run(fx.replace_color(filename=sprite, layer_name="body", frame_index=1, from_color="#D04648", to_color="#597DCE", tolerance=0)))
    assert "Replaced" in result
    px = ok(run(pixel_read.get_pixel_color(filename=sprite, x=11, y=11, layer_name="body", frame_index=1)))
    assert "#597dce" in px


def test_adjust_hsl(sprite):
    ok(run(fx.adjust_hsl(filename=sprite, layer_name="body", frame_index=1, hue_shift=30, saturation_shift=10, lightness_shift=-5)))


def test_apply_dither_gradient(sprite):
    ok(run(fx.apply_dither_gradient(filename=sprite, layer_name="body", frame_index=1, x=0, y=24, width=32, height=8, color_start="#30346D", color_end="#597DCE")))


def test_apply_dither_pattern(sprite):
    ok(run(fx.apply_dither_pattern(filename=sprite, layer_name="body", frame_index=1, x=0, y=0, width=8, height=8, color_a="#854C30", color_b="#D2AA99", density=0.5)))
