"""x/y validation for Dict[str, Any] pixel arguments (Lua-injection guard).

pixels args are typed Dict[str, Any], so x/y values bypass schema
validation and are interpolated into Lua scripts. Bad values must be
rejected with a friendly error BEFORE any script is built or run —
these tests therefore only need an existing file, not a real Aseprite.
"""
from conftest import BASE, run

from aseprite_mcp.tools import drawing, tilemap


def _placeholder(name: str) -> str:
    """A mere existing file; validation returns before Aseprite runs."""
    path = f"{BASE}/{name}"
    with open(path, "wb"):
        pass
    return path


_INJECTION_X = "0) os.execute('boom') --"


def test_draw_pixels_rejects_non_integer_xy(base_dir):
    sprite = _placeholder("xy_guard_draw.aseprite")
    res = run(drawing.draw_pixels(
        filename=sprite,
        pixels=[{"x": _INJECTION_X, "y": 0, "color": "#FF0000"}],
    ))
    assert res.startswith("Invalid pixel coordinates"), res


def test_draw_pixels_at_rejects_non_integer_xy(base_dir):
    sprite = _placeholder("xy_guard_draw_at.aseprite")
    res = run(drawing.draw_pixels_at(
        filename=sprite,
        layer_name="body",
        frame_index=1,
        pixels=[{"x": 1, "y": None, "color": "#FF0000"}],
        create_if_missing=True,
    ))
    assert res.startswith("Invalid pixel coordinates"), res


def test_draw_on_tile_rejects_non_integer_xy(base_dir):
    # Used to raise a raw ValueError (ToolError); now a friendly string
    # consistent with the other drawing tools.
    sprite = _placeholder("xy_guard_tile.aseprite")
    res = run(tilemap.draw_on_tile(
        filename=sprite,
        layer_name="tilemap",
        tile_index=1,
        pixels=[{"x": _INJECTION_X, "y": 0, "color": "#FF0000"}],
    ))
    assert res.startswith("Invalid pixel coordinates"), res


def test_draw_pixels_rejects_mixed_bad_values(base_dir):
    sprite = _placeholder("xy_guard_mixed.aseprite")
    res = run(drawing.draw_pixels(
        filename=sprite,
        pixels=[{"x": 3, "y": 4, "color": "#FF0000"},
                {"x": 3.5, "y": "abc", "color": "#FF0000"}],
    ))
    assert res.startswith("Invalid pixel coordinates"), res
