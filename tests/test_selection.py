"""Region operation tools (selection.py)."""
from conftest import ok, run

from aseprite_mcp.tools import selection


def test_copy_region(sprite):
    ok(run(selection.copy_region(filename=sprite, layer_name="body", frame_index=1, x=8, y=8, width=8, height=8, dest_x=20, dest_y=20)))


def test_move_region(sprite):
    ok(run(selection.move_region(filename=sprite, layer_name="body", frame_index=1, x=20, y=20, width=8, height=8, dest_x=0, dest_y=0)))


def test_erase_region(sprite):
    ok(run(selection.erase_region(filename=sprite, layer_name="body", frame_index=1, x=0, y=0, width=4, height=4)))


def test_erase_color(sprite):
    result = ok(run(selection.erase_color(filename=sprite, layer_name="body", frame_index=1, color="#D04648", tolerance=0)))
    assert "Erased" in result
