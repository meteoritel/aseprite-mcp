"""Visual feedback tools (analysis.py)."""
import json
import os

from conftest import BASE, run

from aseprite_mcp.tools import analysis, animation, drawing


def test_render_onion_skin(sprite):
    run(animation.add_frames(filename=sprite, count=2, duration_ms=100))
    out = f"{BASE}/onion.png"
    run(analysis.render_onion_skin(filename=sprite, frame_index=2, output_filename=out, before=1, after=1, scale=4, ghost_opacity=100))
    assert os.path.exists(out)


def test_compare_identical_frames(sprite):
    run(animation.add_frames(filename=sprite, count=2, duration_ms=100))
    # add_frames duplicates content, so frames 1 and 2 are identical;
    # this used to crash on math.huge in the bbox formatting
    diff = json.loads(run(analysis.compare_frames(filename=sprite, frame_a=1, frame_b=2)))
    assert diff["total_pixels"] == 1024
    assert diff["changed_pixels"] == 0
    assert "changed_bounds" not in diff


def test_compare_differing_frames(sprite):
    run(animation.add_frames(filename=sprite, count=2, duration_ms=100))
    run(drawing.draw_rectangle_at(filename=sprite, layer_name="body", frame_index=3, x=0, y=0, width=4, height=4, color="#FFFFFF", fill=True))
    diff = json.loads(run(analysis.compare_frames(filename=sprite, frame_a=1, frame_b=3)))
    assert diff["changed_pixels"] == 16
    assert diff["changed_bounds"] == {"x": 0, "y": 0, "width": 4, "height": 4}


def test_get_color_stats(sprite):
    stats = json.loads(run(analysis.get_color_stats(filename=sprite, frame_index=1)))
    assert stats["unique_colors"] >= 1
    assert stats["top_colors"][0]["count"] > 0
