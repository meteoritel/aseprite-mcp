"""list_slices must tolerate delimiter characters in a slice name."""
import json

from conftest import ok, run

from aseprite_mcp.tools import slices


def test_list_slices_handles_pipe_and_comma_in_name(sprite):
    ok(run(slices.create_slice(filename=sprite, name="weird|name,x", x=1, y=2, width=10, height=12)))
    ok(run(slices.create_slice(filename=sprite, name="ninepatch", x=0, y=0, width=16, height=16)))
    ok(run(slices.set_slice_center(filename=sprite, name="ninepatch", x=4, y=4, width=8, height=8)))
    by_name = {s["name"]: s for s in json.loads(ok(run(slices.list_slices(filename=sprite))))}
    assert "weird|name,x" in by_name
    assert by_name["weird|name,x"]["x"] == 1 and by_name["weird|name,x"]["width"] == 10
    assert by_name["ninepatch"]["center"] == {"x": 4, "y": 4, "width": 8, "height": 8}
