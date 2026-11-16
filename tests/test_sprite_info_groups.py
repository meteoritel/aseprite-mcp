"""get_sprite_info enumerates nested (grouped) layers with a parent field."""
import json

from conftest import run

from aseprite_mcp.tools import animation, canvas


def test_get_sprite_info_enumerates_group_children(sprite):
    run(canvas.add_group(filename=sprite, group_name="grp"))
    run(canvas.add_layer(filename=sprite, layer_name="child", group="grp"))
    layers = json.loads(run(animation.get_sprite_info(filename=sprite)))["layers"]
    names = [l["name"] for l in layers]
    assert "grp" in names and "child" in names  # nested layer enumerated
    child = next(l for l in layers if l["name"] == "child")
    assert child["parent"] == "grp"
    grp = next(l for l in layers if l["name"] == "grp")
    assert grp["is_group"] is True and grp["parent"] is None
