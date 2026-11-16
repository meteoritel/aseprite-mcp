"""Slice tools (slices.py)."""

from conftest import failure
import json

from conftest import run

from aseprite_mcp.tools import slices


def test_create_slice(sprite):
    run(slices.create_slice(filename=sprite, name="button", x=4, y=4, width=16, height=12))


def test_create_slice_rejects_duplicate(sprite):
    run(slices.create_slice(filename=sprite, name="button", x=4, y=4, width=16, height=12))
    result = failure(slices.create_slice(filename=sprite, name="button", x=0, y=0, width=8, height=8))
    assert "already exists" in result


def test_set_slice_center(sprite):
    run(slices.create_slice(filename=sprite, name="button", x=4, y=4, width=16, height=12))
    run(slices.set_slice_center(filename=sprite, name="button", x=4, y=4, width=8, height=4))


def test_set_slice_pivot(sprite):
    run(slices.create_slice(filename=sprite, name="button", x=4, y=4, width=16, height=12))
    run(slices.set_slice_pivot(filename=sprite, name="button", x=8, y=6))


def test_list_slices(sprite):
    run(slices.create_slice(filename=sprite, name="button", x=4, y=4, width=16, height=12))
    run(slices.set_slice_center(filename=sprite, name="button", x=4, y=4, width=8, height=4))
    run(slices.set_slice_pivot(filename=sprite, name="button", x=8, y=6))
    listed = json.loads(run(slices.list_slices(filename=sprite)))
    assert listed[0]["name"] == "button"
    assert listed[0]["center"]["width"] == 8
    assert listed[0]["pivot"] == {"x": 8, "y": 6}


def test_delete_slice(sprite):
    run(slices.create_slice(filename=sprite, name="button", x=4, y=4, width=16, height=12))
    run(slices.delete_slice(filename=sprite, name="button"))
    assert json.loads(run(slices.list_slices(filename=sprite))) == []
