"""Tilemap tools (tilemap.py)."""

from conftest import failure
import json
import pytest

from conftest import run

from aseprite_mcp.tools import tilemap


@pytest.fixture
def terrain(sprite):
    run(tilemap.create_tilemap_layer(filename=sprite, layer_name="terrain", tile_width=8, tile_height=8))
    return sprite


@pytest.fixture
def painted_terrain(terrain):
    sprite = terrain
    run(tilemap.draw_on_tile(filename=sprite, layer_name="terrain", tile_index=1, pixels=[
        {"x": x, "y": y, "color": "#3E8948"} for x in range(8) for y in range(8)]))
    run(tilemap.draw_on_tile(filename=sprite, layer_name="terrain", tile_index=2, pixels=[
        {"x": x, "y": y, "color": "#743F39"} for x in range(8) for y in range(4)]))

    return sprite


def test_get_tilemap_info(painted_terrain):
    sprite = painted_terrain
    info = json.loads(run(tilemap.get_tilemap_info(filename=sprite, layer_name="terrain")))
    assert info == {
        "tile_width": 8, "tile_height": 8, "tile_count": 2,
        "map_cols": 4, "map_rows": 4,
    }


def test_set_and_get_tiles(painted_terrain):
    sprite = painted_terrain
    run(tilemap.set_tiles(filename=sprite, layer_name="terrain", frame_index=1, tiles=[
        {"col": 0, "row": 3, "tile_index": 1},
        {"col": 1, "row": 3, "tile_index": 1},
        {"col": 2, "row": 3, "tile_index": 2},
        {"col": 3, "row": 3, "tile_index": 1}]))
    tile = json.loads(run(tilemap.get_tile_at(filename=sprite, layer_name="terrain", frame_index=1, col=2, row=3)))
    assert tile["tile_index"] == 2


def test_set_tiles_rejects_out_of_range_index(painted_terrain):
    sprite = painted_terrain
    result = failure(tilemap.set_tiles(filename=sprite, layer_name="terrain", frame_index=1, tiles=[
        {"col": 0, "row": 0, "tile_index": 99}]))
    assert "out of range" in result
