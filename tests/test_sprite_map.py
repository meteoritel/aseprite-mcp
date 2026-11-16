"""Compact character-grid authoring and readback (sprite_map.py)."""

from conftest import failure
import json

from conftest import BASE, run

from aseprite_mcp.tools import drawing, pixel_read, sprite_map


def _read(sprite, layer_name, x, y, width, height, **kwargs):
    raw = run(sprite_map.get_sprite_map(
        filename=sprite, layer_name=layer_name, frame_index=1,
        x=x, y=y, width=width, height=height, **kwargs,
    ))
    return json.loads(raw)


def _hex_at(sprite, layer_name, x, y):
    out = run(pixel_read.get_pixel_color(
        filename=sprite, x=x, y=y, layer_name=layer_name, frame_index=1))
    return out.split(" ")[0]


def test_draw_sprite_map_places_cells(sprite):
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_basic", frame_index=1,
        rows=["11.",
              ".22",
              "..3"],
        palette={"1": "#FF0000", "2": "#00FF00", "3": "#0000FF"},
    ))
    assert _hex_at(sprite, "map_basic", 0, 0) == "#ff0000"
    assert _hex_at(sprite, "map_basic", 1, 0) == "#ff0000"
    assert _hex_at(sprite, "map_basic", 1, 1) == "#00ff00"
    assert _hex_at(sprite, "map_basic", 2, 1) == "#00ff00"
    assert _hex_at(sprite, "map_basic", 2, 2) == "#0000ff"
    # '.' cells are skipped, so they stay transparent on a fresh layer.
    assert _hex_at(sprite, "map_basic", 0, 1) == "#000000"


def test_draw_sprite_map_anchors_at_xy(sprite):
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_anchor", frame_index=1,
        rows=["7"], palette={"7": "#123456"}, x=10, y=20,
    ))
    assert _hex_at(sprite, "map_anchor", 10, 20) == "#123456"
    assert _hex_at(sprite, "map_anchor", 0, 0) == "#000000"


def test_draw_sprite_map_skips_transparent_by_default(sprite):
    run(drawing.draw_rectangle_at(
        filename=sprite, layer_name="map_skip", frame_index=1,
        x=0, y=0, width=2, height=2, color="#FFFFFF", fill=True))
    # '.' means "leave it alone", so the white square survives underneath.
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_skip", frame_index=1,
        rows=[".1",
              ".."], palette={"1": "#FF0000"},
    ))
    assert _hex_at(sprite, "map_skip", 0, 0) == "#ffffff"
    assert _hex_at(sprite, "map_skip", 1, 0) == "#ff0000"


def test_draw_sprite_map_erase_transparent_clears(sprite):
    run(drawing.draw_rectangle_at(
        filename=sprite, layer_name="map_erase", frame_index=1,
        x=0, y=0, width=2, height=2, color="#FFFFFF", fill=True))
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_erase", frame_index=1,
        rows=[".1",
              ".."], palette={"1": "#FF0000"}, erase_transparent=True,
    ))
    assert _hex_at(sprite, "map_erase", 0, 0) == "#000000"
    assert _hex_at(sprite, "map_erase", 0, 1) == "#000000"
    assert _hex_at(sprite, "map_erase", 1, 0) == "#ff0000"


def test_draw_sprite_map_mirrors(sprite):
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_mirror", frame_index=1,
        rows=["1...",
              "...."], palette={"1": "#ABCDEF"},
        mirror_x=True, mirror_y=True,
    ))
    assert _hex_at(sprite, "map_mirror", 0, 0) == "#abcdef"
    assert _hex_at(sprite, "map_mirror", 3, 0) == "#abcdef"
    assert _hex_at(sprite, "map_mirror", 0, 1) == "#abcdef"
    assert _hex_at(sprite, "map_mirror", 3, 1) == "#abcdef"


def test_draw_sprite_map_rejects_ragged_rows(sprite):
    res = failure(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_bad", frame_index=1,
        rows=["11", "1"], palette={"1": "#FF0000"},
    ))
    assert res.startswith("Invalid sprite map"), res
    assert "rectangle" in res


def test_draw_sprite_map_rejects_unknown_character(sprite):
    res = failure(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_bad", frame_index=1,
        rows=["1x"], palette={"1": "#FF0000"},
    ))
    assert res.startswith("Invalid sprite map"), res
    assert "Unknown character" in res


def test_draw_sprite_map_rejects_bad_palette(sprite):
    res = failure(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_bad", frame_index=1,
        rows=["1"], palette={"1": "not-a-colour"},
    ))
    assert res.startswith("Invalid sprite map"), res


def test_draw_sprite_map_rejects_transparent_in_palette(sprite):
    res = failure(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_bad", frame_index=1,
        rows=["1"], palette={".": "#FF0000"},
    ))
    assert res.startswith("Invalid sprite map"), res
    assert "reserved" in res


def test_draw_sprite_map_all_transparent_is_a_noop(sprite):
    # Matches text.py's convention for a no-op: "OK: ..." so ok() reads it
    # as success rather than an unrecognised string.
    res = run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_bad", frame_index=1,
        rows=["..", ".."], palette={},
    ))
    assert res.startswith("OK: nothing to draw"), res


def test_get_sprite_map_round_trips_through_draw(sprite):
    """Draw -> read -> draw must reproduce the original pixels exactly."""
    rows = ["..11..",
            ".1221.",
            "122221",
            ".3223."]
    palette = {"1": "#3B2A1E", "2": "#8B5A2B", "3": "#F2C48D"}
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_src", frame_index=1,
        rows=rows, palette=palette, x=0, y=0,
    ))

    read = _read(sprite, "map_src", 0, 0, 6, 4)
    assert read["width"] == 6 and read["height"] == 4
    assert read["transparent"] == "."
    assert read["columns"] == "012345"
    # Every drawn colour is represented, and '.' is never a palette key.
    assert sorted(read["palette"].values()) == ["#3b2a1e", "#8b5a2b", "#f2c48d"]
    assert read["transparent"] not in read["palette"]

    # Rows are character-encoded; resolve them back to colours to compare
    # against the source grid (auto-assigned characters may differ).
    resolved = [
        [read["palette"].get(char, "transparent") for char in row]
        for row in read["rows"]
    ]
    expected = [
        [palette.get(char, "transparent") for char in row] for row in rows
    ]
    assert resolved == [[hexv.lower() for hexv in row] for row in expected]

    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_dst", frame_index=1,
        x=0, y=0, rows=read["rows"], palette=read["palette"],
        transparent=read["transparent"], erase_transparent=True,
    ))

    src = run(pixel_read.get_pixels_rect(
        filename=sprite, x=0, y=0, width=6, height=4,
        layer_name="map_src", frame_index=1))
    dst = run(pixel_read.get_pixels_rect(
        filename=sprite, x=0, y=0, width=6, height=4,
        layer_name="map_dst", frame_index=1))
    assert src == dst


def test_get_sprite_map_palette_keeps_characters_stable(sprite):
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_stable", frame_index=1,
        rows=["121", "212"], palette={"1": "#101010", "2": "#202020"},
    ))
    first = _read(sprite, "map_stable", 0, 0, 3, 2)
    second = _read(sprite, "map_stable", 0, 0, 3, 2, palette=first["palette"])
    assert second["rows"] == first["rows"]
    assert second["palette"] == first["palette"]


def test_get_sprite_map_quantises(sprite):
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_quant", frame_index=1,
        rows=["1234"], palette={
            "1": "#FF0000", "2": "#FE0000", "3": "#FD0000", "4": "#FC0000",
        },
    ))
    read = _read(sprite, "map_quant", 0, 0, 4, 1, max_colors=2)
    assert len(read["palette"]) == 2
    # Every row character must be a known palette key.
    assert set("".join(read["rows"])) <= set(read["palette"])


def test_get_sprite_map_reads_composite(sprite):
    # The shared fixture paints a #D04648 square on 'body' at 8,8..23,23.
    read = _read(sprite, "", 8, 8, 2, 2, composite=True)
    assert sorted(read["palette"].values()) == ["#d04648"]


def test_get_sprite_map_alpha_threshold(sprite):
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_alpha", frame_index=1,
        rows=["1"], palette={"1": "#FF00007F"},
    ))
    read = _read(sprite, "map_alpha", 0, 0, 1, 1)
    assert read["rows"] == ["0"]
    assert read["palette"] == {"0": "#ff00007f"}
    assert read["lossy"] is False
    observed = _read(sprite, "map_alpha", 0, 0, 1, 1, alpha_threshold=128)
    assert observed["rows"] == ["."]
    assert observed["lossy"] is True


def test_get_sprite_map_rejects_zero_size(sprite):
    res = failure(sprite_map.get_sprite_map(
        filename=sprite, layer_name="body", x=0, y=0, width=0, height=1))
    assert res.startswith("Width and height"), res


def test_get_sprite_map_rejects_bad_palette_without_aseprite(base_dir):
    """The palette is an output mapping, so it must be rejected before the
    Aseprite launch — a bare existing file is enough to prove no launch."""
    path = f"{BASE}/map_palette_guard.aseprite"
    with open(path, "wb"):
        pass
    res = failure(sprite_map.get_sprite_map(
        filename=path, layer_name="body", x=0, y=0, width=1, height=1,
        palette={"a": "not-a-colour"},
    ))
    assert res.startswith("Invalid colour"), res


def test_get_sprite_map_reports_colour_overflow(sprite):
    # 64 distinct colours exceed the 62-character alphabet: the tool must say
    # so (and point at max_colors) instead of silently dropping cells.
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!@"
    assert len(chars) == 64
    run(sprite_map.draw_sprite_map(
        filename=sprite, layer_name="map_overflow", frame_index=1,
        rows=["".join(chars[r * 8:(r + 1) * 8]) for r in range(8)],
        palette={c: f"#{i:02x}0000" for i, c in enumerate(chars)},
    ))

    res = failure(sprite_map.get_sprite_map(
        filename=sprite, layer_name="map_overflow", x=0, y=0, width=8, height=8))
    assert res.startswith("Invalid colour count"), res
    assert "max_colors" in res

    # ...and quantising is the documented way out.
    read = _read(sprite, "map_overflow", 0, 0, 8, 8, max_colors=32)
    assert len(read["palette"]) <= 32
    assert all(char in read["palette"] for row in read["rows"] for char in row)
