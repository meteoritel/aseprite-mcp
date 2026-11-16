"""Visible readback, frame analysis and review images agree with saved pixels."""

from support import payload


from PIL import Image

from aseprite_mcp.tools import analysis, animation, canvas, drawing, pixel_read
from support import frame_image, run


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
