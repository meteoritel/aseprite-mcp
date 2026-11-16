"""Composite reads exclude hidden layers; tilemap and palette reads keep their domain semantics."""
import json
import os

import pytest
from PIL import Image

from conftest import BASE, failure, run

from aseprite_mcp.core.commands import lua_escape
from aseprite_mcp.tools import (
    analysis,
    animation,
    canvas,
    drawing,
    export,
    fx,
    layers,
    native_fx,
    pixel_read,
    script,
    selection,
    tilemap,
    transform,
)




def rgba(result):
    s = str(result)
    return (int(s.split("r=")[1].split(",")[0]),
            int(s.split("g=")[1].split(",")[0]),
            int(s.split("b=")[1].split(",")[0]),
            int(s.split("a=")[1].split(")")[0]))


@pytest.fixture
def layered(new_sprite):
    """32x32: hidden red 'bg' filling the canvas under a visible blue 'fg'
    covering only x < 16. The right half is transparent on every visible
    layer, so any red read there can only come from the hidden one."""
    path = new_sprite(32, 32)
    run(layers.rename_layer(filename=path, layer_name="Layer 1", new_name="bg"))
    run(drawing.draw_rectangle_at(filename=path, layer_name="bg", frame_index=1, x=0, y=0, width=32, height=32, color="#FF0000", fill=True))
    run(canvas.add_layer(filename=path, layer_name="fg"))
    run(drawing.draw_rectangle_at(filename=path, layer_name="fg", frame_index=1, x=0, y=0, width=16, height=32, color="#0000FF", fill=True))
    run(animation.set_layer_visibility(filename=path, layer_name="bg", visible=False))
    return path


def test_composite_pixel_ignores_hidden_layer(layered):
    # Visible half: the blue on 'fg'.
    assert rgba(run(pixel_read.get_composite_pixel(filename=layered, x=4, y=4))) == (0, 0, 255, 255)
    # Hidden-only half: nothing visible there, so fully transparent.
    assert rgba(run(pixel_read.get_composite_pixel(filename=layered, x=24, y=4))) == (0, 0, 0, 0)


def test_composite_rect_ignores_hidden_layer(layered):
    pixels = json.loads(run(pixel_read.get_composite_rect(filename=layered, x=0, y=0, width=32, height=1)))
    left = [p for p in pixels if p["x"] < 16]
    right = [p for p in pixels if p["x"] >= 16]
    assert all(p["a"] == 255 and p["hex"] == "#0000ff" for p in left), left[:2]
    assert all(p["a"] == 0 for p in right), right[:2]


def test_color_stats_ignores_hidden_layer(layered):
    stats = json.loads(run(analysis.get_color_stats(filename=layered, frame_index=1)))
    # Only the blue half is visible: 32x16 opaque pixels of exactly one colour.
    assert stats["unique_colors"] == 1, stats
    assert stats["opaque_pixels"] == 32 * 16, stats
    assert stats["top_colors"] == [{"color": "#0000FF", "count": 512}], stats


def test_composite_matches_exported_png(layered):
    """The composited read must equal what Aseprite's own renderer exports —
    this is the assertion that makes "what the player sees" mean something."""
    png = f"{BASE}/visibility_layered.png"
    run(export.export_frame(filename=layered, frame_index=1, output_filename=png, scale=1))
    assert os.path.exists(png), png
    image = Image.open(png).convert("RGBA")
    pixels = json.loads(run(pixel_read.get_composite_rect(filename=layered, x=0, y=0, width=32, height=32)))
    for p in pixels:
        assert (p["r"], p["g"], p["b"], p["a"]) == image.getpixel((p["x"], p["y"])), p


def test_compare_frames_ignores_hidden_layer(layered):
    run(animation.add_frames(filename=layered, count=1, duration_ms=100))
    run(drawing.draw_pixels_at(filename=layered, layer_name="bg", frame_index=2,
        pixels=[{"x": 24, "y": 4, "color": "#00ff00"}]))
    diff = json.loads(run(analysis.compare_frames(filename=layered, frame_a=1, frame_b=2)))
    assert diff["changed_pixels"] == 0
    run(drawing.draw_pixels_at(filename=layered, layer_name="fg", frame_index=2,
        pixels=[{"x": 4, "y": 4, "color": "#00ff00"}]))
    diff = json.loads(run(analysis.compare_frames(filename=layered, frame_a=1, frame_b=2)))
    assert diff["changed_pixels"] == 1
    assert diff["changed_bounds"] == {"x": 4, "y": 4, "width": 1, "height": 1}


def test_render_onion_skin_ignores_hidden_layer(layered):
    # The onion-skin render sits on a white background, so the hidden red
    # would read as (255,0,0) if it leaked through.
    png = f"{BASE}/visibility_onion.png"
    run(analysis.render_onion_skin(filename=layered, frame_index=1, output_filename=png, before=0, after=0, scale=1))
    image = Image.open(png).convert("RGBA")
    assert image.getpixel((24, 4)) == (255, 255, 255, 255), image.getpixel((24, 4))
    assert image.getpixel((4, 4)) == (0, 0, 255, 255), image.getpixel((4, 4))


@pytest.fixture
def grouped(new_sprite):
    """32x32 with a green 'inner' inside group 'grp'; the group is hidden
    first, then shown, so both branches of the group walk are exercised."""
    path = new_sprite(32, 32)
    run(canvas.add_group(filename=path, group_name="grp"))
    run(canvas.add_layer(filename=path, layer_name="inner", group="grp"))
    run(drawing.draw_rectangle_at(filename=path, layer_name="inner", frame_index=1, x=0, y=0, width=32, height=32, color="#00FF00", fill=True))
    return path


def test_hidden_group_is_not_composited(grouped):
    run(animation.set_layer_visibility(filename=grouped, layer_name="grp", visible=False))
    assert rgba(run(pixel_read.get_composite_pixel(filename=grouped, x=8, y=8))) == (0, 0, 0, 0)


def test_visible_group_is_composited(grouped):
    run(animation.set_layer_visibility(filename=grouped, layer_name="grp", visible=True))
    assert rgba(run(pixel_read.get_composite_pixel(filename=grouped, x=8, y=8))) == (0, 255, 0, 255)


@pytest.fixture
def tiled(new_sprite):
    """32x32 with an 8x8-tile tilemap layer holding one magenta tile."""
    path = new_sprite(32, 32)
    run(tilemap.create_tilemap_layer(filename=path, layer_name="tiles", tile_width=8, tile_height=8))
    run(tilemap.draw_on_tile(filename=path, layer_name="tiles", tile_index=1,
                                pixels=[{"x": px, "y": py, "color": "#FF00FF"} for py in range(8) for px in range(8)]))
    run(tilemap.set_tiles(filename=path, layer_name="tiles", frame_index=1, tiles=[{"col": 0, "row": 0, "tile_index": 1}]))
    return path


def test_pixel_read_refuses_tilemap_layer(tiled):
    # Before the guard this returned "#010000 (r=1, ..., a=0)" — the tile
    # index sitting in the red channel.
    message = failure(pixel_read.get_pixel_color(filename=tiled, x=1, y=1, layer_name="tiles", frame_index=1))
    assert "tilemap" in message, message
    assert "get_tile_at" in message, message
    assert "Existing layers:" in message and "tiles" in message, message


def test_pixels_rect_refuses_tilemap_layer(tiled):
    message = failure(pixel_read.get_pixels_rect(filename=tiled, x=0, y=0, width=3, height=3, layer_name="tiles", frame_index=1))
    assert "tilemap" in message and "get_tile_at" in message, message


def test_tilemap_tile_is_still_readable_as_a_tile(tiled):
    assert "tile_index" in run(tilemap.get_tile_at(filename=tiled, layer_name="tiles", frame_index=1, col=0, row=0))


def test_composite_still_renders_tilemap_layers(tiled):
    # The composite path is the documented workaround, so it must work here.
    assert rgba(run(pixel_read.get_composite_pixel(filename=tiled, x=1, y=1))) == (255, 0, 255, 255)


@pytest.fixture
def painted(new_sprite):
    """8x8 using five real colours, black among them — the case that made
    the transparent slot collide with a genuine colour."""
    colours = ["#000000", "#FF0000", "#00FF00", "#0000FF", "#FFFF00"]
    path = new_sprite(8, 8)
    run(drawing.draw_pixels_at(filename=path, layer_name="body", frame_index=1,
                                  pixels=[{"x": x, "y": y, "color": colours[(x * 3 + y) % 5]}
                                          for x in range(8) for y in range(8)]))
    return path


def test_extract_palette_drops_the_transparent_slot(painted):
    out = json.loads(run(native_fx.extract_palette(filename=painted, max_colors=8)))
    assert out["transparent_index"] == 0, out
    assert out["count"] == len(out["colors"]), out
    # #000000 is a real colour here, so it appears exactly once.
    assert out["colors"].count("#000000") == 1, out["colors"]
    assert out["count"] == 5, out
    assert sorted(out["colors"]) == ["#000000", "#0000FF", "#00FF00", "#FF0000", "#FFFF00"], out
    # The dropped slot is still a slot, so the palette is one larger than the
    # colour list — that is what makes the shortfall visible to the caller.
    assert out["max_colors"] == 8, out
    assert out["palette_size"] == out["count"] + 1, out


def test_extract_palette_budget_includes_the_transparent_slot(new_sprite):
    """Aseprite spends one slot of `max_colors` on the sprite's transparent
    colour, so asking for N yields at most N-1 usable colours — the stable
    "-1" a field test reported. Pinned here so a change in Aseprite's
    quantiser surfaces as a failure instead of silent drift in the rule
    that extract_palette's docstring documents."""
    path = new_sprite(32, 32)
    run(drawing.draw_pixels_at(
        filename=path, layer_name="body", frame_index=1,
        pixels=[{"x": x, "y": y, "color": f"#{x * 8:02X}{y * 8:02X}{(x * y) % 256:02X}"}
                for x in range(32) for y in range(32)]))
    out = json.loads(run(native_fx.extract_palette(filename=path, max_colors=8)))
    assert out["max_colors"] == 8, out
    assert out["transparent_index"] == 0, out
    assert out["palette_size"] <= out["max_colors"], out
    assert out["count"] == out["palette_size"] - 1, out
    assert out["count"] <= out["max_colors"] - 1, out


def test_run_lua_script_surfaces_lua_errors(sprite):
    # Aseprite reports Lua errors on stdout and exits non-zero; before the
    # fix only stderr was read, so the message came back empty.
    message = failure(script.run_lua_script(script="local x = nil\nprint(x.y)", filename=sprite))
    assert "attempt to index a nil value" in message, message
    message = failure(script.run_lua_script(script="this is not lua", filename=sprite))
    assert "syntax error" in message, message


@pytest.mark.parametrize("call, expected", [
    (lambda s: animation.set_cel_opacity(filename=s, layer_name="ZZZ", frame_index=1, opacity=128), "Layer"),
    (lambda s: fx.outline_cel(filename=s, layer_name="ZZZ", frame_index=1), "Layer"),
    (lambda s: fx.replace_color(filename=s, layer_name="ZZZ", frame_index=1, from_color="#000000", to_color="#FFFFFF"), "Layer"),
    (lambda s: fx.adjust_hsl(filename=s, layer_name="ZZZ", frame_index=1, hue_shift=5), "Layer"),
    (lambda s: layers.delete_layer(filename=s, layer_name="ZZZ"), "Layer"),
    (lambda s: layers.rename_layer(filename=s, layer_name="ZZZ", new_name="q"), "Layer"),
    (lambda s: layers.duplicate_layer(filename=s, layer_name="ZZZ"), "Layer"),
    (lambda s: layers.reorder_layer(filename=s, layer_name="ZZZ", position=1), "Layer"),
    (lambda s: layers.set_layer_blend_mode(filename=s, layer_name="ZZZ", mode="multiply"), "Layer"),
    (lambda s: layers.merge_layer_down(filename=s, layer_name="ZZZ"), "Layer"),
    (lambda s: canvas.add_layer(filename=s, layer_name="a", group="ZZZ_GROUP"), "Group"),
    (lambda s: canvas.add_group(filename=s, group_name="g", parent_group="ZZZ_GROUP"), "Group"),
    (lambda s: pixel_read.get_pixel_color(filename=s, x=0, y=0, layer_name="ZZZ", frame_index=1), "Layer"),
    (lambda s: pixel_read.get_pixels_rect(filename=s, x=0, y=0, width=2, height=2, layer_name="ZZZ", frame_index=1), "Layer"),
    (lambda s: tilemap.get_tilemap_info(filename=s, layer_name="ZZZ"), "Layer"),
    (lambda s: transform.flip_layer(filename=s, layer_name="ZZZ", frame_index=1), "Layer"),
    (lambda s: selection.copy_region(filename=s, layer_name="ZZZ", frame_index=1, x=0, y=0,
                                     width=2, height=2, dest_x=0, dest_y=0), "Source layer"),
])
def test_missing_layer_errors_carry_context(sprite, call, expected):
    """Every migrated site must name the thing that is missing *and* list
    what does exist, so the caller can fix it without a second round trip."""
    message = failure(call(sprite))
    assert f"{expected} 'ZZZ" in message, message
    assert "Existing layers:" in message, message
    assert "body" in message, message


def test_tilemap_reads_carry_context(sprite):
    message = failure(tilemap.get_tilemap_info(filename=sprite, layer_name="ZZZ"))
    assert "Existing layers:" in message and "body" in message, message


def test_dither_tools_auto_create_layers(sprite):
    # apply_dither_* documented create_if_missing but only ever created the
    # cel, so a fresh layer name died with a bare "Layer not found".
    run(fx.apply_dither_pattern(filename=sprite, layer_name="dither_new", frame_index=1,
                                   x=0, y=0, width=8, height=8, color_a="#000000", color_b="#FFFFFF"))
    info = json.loads(run(animation.get_sprite_info(filename=sprite)))
    assert "dither_new" in [layer["name"] for layer in info["layers"]], info


def test_dither_can_still_refuse_to_create(sprite):
    message = failure(fx.apply_dither_gradient(filename=sprite, layer_name="ZZZ_GHOST", frame_index=1,
                                                  x=0, y=0, width=8, height=8, color_start="#000000",
                                                  color_end="#FFFFFF", create_if_missing=False))
    assert "Existing layers:" in message, message


def test_lua_escape_quotes_both_styles():
    # Error text embeds layer names in single quotes, so an apostrophe must
    # not be able to break out of the literal.
    assert lua_escape("it's") == "it\\'s"
    assert lua_escape('a"b') == 'a\\"b'
    assert lua_escape("a\\b") == "a\\\\b"
