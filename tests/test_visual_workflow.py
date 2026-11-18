"""Visible readback, frame analysis and review images agree with saved pixels."""

from PIL import Image

from aseprite_mcp.tools import analysis, animation, canvas, drawing, fx, pixel_read, sprite_map
from support import digest, failure, frame_image, payload, run


def test_dither_detail_preserves_transparency_alpha_and_unselected_pixels(new_sprite):
    filename = new_sprite(12, 12)
    run(sprite_map.draw_sprite_map(
        filename=filename, layer_name="ink", frame_index=1, x=5, y=5,
        rows=["A..A", "ABAA", "AAAA", "A..A"],
        palette={"A": "#123456", "B": "#00FF0080"},
    ))
    run(drawing.draw_pixels_at(
        filename=filename, layer_name="ink", frame_index=1,
        pixels=[{"x": 4, "y": 5, "color": "#ABCDEF"}],
    ))

    receipt = payload(run(fx.draw_dither_detail(
        filename=filename, layer_name="ink", frame_index=1,
        x=5, y=5, width=4, height=4, color="#FF0000", density=0.5,
    )))
    assert receipt["layer_paths"] == [["ink"]]
    pixels = payload(run(pixel_read.get_pixels_rect(
        filename=filename, layer_name="ink", frame_index=1,
        x=5, y=5, width=4, height=4,
    )))
    actual = [
        (pixel["r"], pixel["g"], pixel["b"], pixel["a"])
        for pixel in pixels
    ]
    expected = [
        (255, 0, 0, 255), (0, 0, 0, 0), (0, 0, 0, 0), (18, 52, 86, 255),
        (18, 52, 86, 255), (255, 0, 0, 128), (18, 52, 86, 255), (255, 0, 0, 255),
        (255, 0, 0, 255), (18, 52, 86, 255), (255, 0, 0, 255), (18, 52, 86, 255),
        (18, 52, 86, 255), (0, 0, 0, 0), (0, 0, 0, 0), (255, 0, 0, 255),
    ]
    assert actual == expected
    outside = payload(run(pixel_read.get_pixel_color(
        filename=filename, layer_name="ink", frame_index=1, x=4, y=5,
    )))
    assert (outside["r"], outside["g"], outside["b"], outside["a"]) == (171, 205, 239, 255)

    run(fx.draw_dither_detail(
        filename=filename, layer_name="ink", frame_index=1,
        x=5, y=5, width=4, height=4, color="#0000FF", density=0,
    ))
    unchanged = payload(run(pixel_read.get_pixel_color(
        filename=filename, layer_name="ink", frame_index=1, x=5, y=5,
    )))
    assert (unchanged["r"], unchanged["g"], unchanged["b"], unchanged["a"]) == (255, 0, 0, 255)

    run(drawing.draw_pixels_at(
        filename=filename, layer_name="ink", frame_index=1,
        pixels=[{"x": 11, "y": 11, "color": "#123456"}],
    ))
    run(fx.draw_dither_detail(
        filename=filename, layer_name="ink", frame_index=1,
        x=11, y=11, width=2, height=2, color="#00FF00", density=1,
    ))
    edge = payload(run(pixel_read.get_pixel_color(
        filename=filename, layer_name="ink", frame_index=1, x=11, y=11,
    )))
    assert (edge["r"], edge["g"], edge["b"], edge["a"]) == (0, 255, 0, 255)

    assert "density" in failure(fx.draw_dither_detail(
        filename=filename, layer_name="ink", frame_index=1,
        x=5, y=5, width=4, height=4, color="#FF0000", density=1.1,
    ))
    assert "3 or 6 RGB hex digits" in failure(fx.draw_dither_detail(
        filename=filename, layer_name="ink", frame_index=1,
        x=5, y=5, width=4, height=4, color="#FF000080",
    ))

    run(canvas.add_layer(filename=filename, layer_name="empty"))
    before = digest(filename)
    assert "No cel" in failure(fx.draw_dither_detail(
        filename=filename, layer_name="empty", frame_index=1,
        x=0, y=0, width=1, height=1, color="#FF0000",
    ))
    assert digest(filename) == before


def test_dither_detail_uses_canvas_coordinates_for_offset_cels(new_sprite):
    filename = new_sprite(8, 8)
    run(drawing.draw_pixels_at(
        filename=filename, layer_name="ink", frame_index=1,
        pixels=[{"x": 1, "y": 1, "color": "#123456"}],
    ))
    run(animation.set_cel_position(
        filename=filename, layer_name="ink", frame_index=1, x=3, y=2,
    ))

    run(fx.draw_dither_detail(
        filename=filename, layer_name="ink", frame_index=1,
        x=4, y=3, width=1, height=1, color="#00FF00", density=1,
    ))
    moved = payload(run(pixel_read.get_pixel_color(
        filename=filename, layer_name="ink", frame_index=1, x=4, y=3,
    )))
    original = payload(run(pixel_read.get_pixel_color(
        filename=filename, layer_name="ink", frame_index=1, x=1, y=1,
    )))
    assert (moved["r"], moved["g"], moved["b"], moved["a"]) == (0, 255, 0, 255)
    assert original["a"] == 0


def test_existing_dither_pattern_keeps_its_rectangle_fill_semantics(new_sprite):
    filename = new_sprite(4, 4)
    run(fx.apply_dither_pattern(
        filename=filename, layer_name="ink", frame_index=1,
        x=0, y=0, width=4, height=4,
        color_a="#123456", color_b="#ABCDEF", density=0.5,
    ))
    pixels = payload(run(pixel_read.get_pixels_rect(
        filename=filename, layer_name="ink", frame_index=1,
        x=0, y=0, width=4, height=4,
    )))
    actual = [pixel["hex"] for pixel in pixels]
    expected = [
        "#abcdef", "#123456", "#abcdef", "#123456",
        "#123456", "#abcdef", "#123456", "#abcdef",
        "#abcdef", "#123456", "#abcdef", "#123456",
        "#123456", "#abcdef", "#123456", "#abcdef",
    ]
    assert actual == expected

    run(fx.apply_dither_gradient(
        filename=filename, layer_name="ink", frame_index=1,
        x=0, y=0, width=4, height=4,
        color_start="#000000", color_end="#FFFFFF",
    ))
    gradient = payload(run(pixel_read.get_pixels_rect(
        filename=filename, layer_name="ink", frame_index=1,
        x=0, y=0, width=4, height=4,
    )))
    assert [pixel["hex"] for pixel in gradient[:4]] == ["#000000"] * 4
    assert [pixel["hex"] for pixel in gradient[-4:]] == ["#ffffff"] * 4


def test_visible_readback_analysis_and_review_images(new_sprite, tmp_path):
    filename = new_sprite(32, 32)
    run(drawing.draw_rectangle_at(filename=filename, layer_name="bg", frame_index=1,
                                  x=0, y=0, width=32, height=32, color="#ff0000", fill=True))
    run(drawing.draw_rectangle_at(filename=filename, layer_name="fg", frame_index=1,
                                  x=0, y=0, width=16, height=32, color="#0000ff", fill=True))
    run(canvas.add_group(filename=filename, group_name="details"))
    run(canvas.add_layer(filename=filename, layer_name="highlight", group="details"))
    run(drawing.draw_rectangle_at(filename=filename, layer_name="details/highlight", frame_index=1,
                                  x=4, y=4, width=4, height=4, color="#00ff00", fill=True))
    run(animation.set_layer_visibility(filename=filename, layer_name="bg", visible=False))

    for visible in (True, False):
        run(animation.set_layer_visibility(filename=filename, layer_name="details", visible=visible))
        expected = Image.new("RGBA", (32, 32))
        expected.paste((0, 0, 255, 255), (0, 0, 16, 32))
        if visible:
            expected.paste((0, 255, 0, 255), (4, 4, 8, 8))
        assert frame_image(filename, 1, tmp_path).tobytes() == expected.tobytes()
        pixels = payload(run(pixel_read.get_composite_rect(
            filename=filename, frame_index=1, x=0, y=0, width=32, height=32,
        )))
        assert bytes(channel for p in pixels for channel in (p["r"], p["g"], p["b"], p["a"])) == expected.tobytes()

    hidden = payload(run(pixel_read.get_pixels_rect(
        filename=filename, layer_name="bg", frame_index=1, x=24, y=4, width=1, height=1,
    )))[0]
    assert (hidden["r"], hidden["g"], hidden["b"], hidden["a"]) == (255, 0, 0, 255)
    stats = payload(run(analysis.get_color_stats(filename=filename, frame_index=1)))
    assert stats["unique_colors"] == 1
    assert stats["opaque_pixels"] == 512
    assert stats["top_colors"] == [{"color": "#0000FF", "count": 512}]

    run(animation.add_frames(filename=filename, count=1, duration_ms=100))
    run(drawing.draw_pixels_at(filename=filename, layer_name="bg", frame_index=2,
                               pixels=[{"x": 24, "y": 4, "color": "#00ff00"}]))
    identical = payload(run(analysis.compare_frames(filename=filename, frame_a=1, frame_b=2)))
    assert identical["changed_pixels"] == 0
    assert "changed_bounds" not in identical
    run(drawing.draw_pixels_at(filename=filename, layer_name="fg", frame_index=2,
                               pixels=[{"x": 4, "y": 4, "color": "#00ff00"}]))
    changed = payload(run(analysis.compare_frames(filename=filename, frame_a=1, frame_b=2)))
    assert changed["changed_pixels"] == 1
    assert changed["changed_bounds"] == {"x": 4, "y": 4, "width": 1, "height": 1}

    review = tmp_path / "onion.png"
    run(analysis.render_onion_skin(filename=filename, frame_index=2, output_filename=str(review),
                                   before=0, after=0, scale=1))
    expected = Image.new("RGBA", (32, 32), (255, 255, 255, 255))
    expected.paste((0, 0, 255, 255), (0, 0, 16, 32))
    expected.putpixel((4, 4), (0, 255, 0, 255))
    with Image.open(review) as image:
        assert image.size == expected.size
        assert image.convert("RGBA").tobytes() == expected.tobytes()
