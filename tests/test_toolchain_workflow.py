"""Typed discovery, exact targets, atomic grids and same-image review through public tools."""

from base64 import b64decode
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, validate
from PIL import Image

from aseprite_mcp.core import editing, state
from aseprite_mcp.core.commands import AsepriteCommand
from aseprite_mcp.tool_catalog import CORE_TOOLS, EXTENSION_TOOLS, TOOL_EXAMPLES
from aseprite_mcp.tools import animation, canvas, drawing, layers, quality, review, scene, sprite_map, text, tilemap
from support import FIXTURE_GLYPHS, call, connected_server, digest, failure, frame_image, payload, run


def observe_execution(monkeypatch, filename):
    observed = {"processes": 0, "saves": 0, "commits": 0}
    execute = AsepriteCommand.execute_lua_script
    replace = editing.os.replace

    async def counted(script, source=None):
        observed["processes"] += 1
        output = await execute(script, source)
        observed["saves"] += sum(line.startswith("EDIT_TARGETS:") for line in output.splitlines())
        return output

    def committed(source, target):
        if str(target) == filename:
            observed["commits"] += 1
        return replace(source, target)

    monkeypatch.setattr(AsepriteCommand, "execute_lua_script", staticmethod(counted))
    monkeypatch.setattr(editing.os, "replace", committed)
    return observed


def decode_grid(grid):
    image = Image.new("RGBA", (grid["width"], grid["height"]))
    for y, row in enumerate(grid["rows"]):
        for x, char in enumerate(row):
            if char != grid["transparent"]:
                value = grid["palette"][char].lstrip("#")
                if len(value) == 6:
                    value += "ff"
                image.putpixel((x, y), tuple(bytes.fromhex(value)))
    return image


def test_complete_discovery_and_contract_failures_without_aseprite(tmp_path, bitmap_font):
    with connected_server(env={"ASEPRITE_PATH": "missing-aseprite-contract-check"}) as (send, receive):
        send("tools/list", {}, 20)
        initial = receive(20)
        schemas = {tool["name"]: tool for tool in initial["tools"]}
        definitions, offset = {}, 0
        while offset is not None:
            result = call(send, receive, "search_tools", {"limit": 20, "offset": offset, "detail": "full"})
            validate(result["structuredContent"], schemas["search_tools"]["outputSchema"])
            page = result["structuredContent"]["data"]
            brief_result = call(send, receive, "search_tools", {"limit": 20, "offset": offset})
            validate(brief_result["structuredContent"], schemas["search_tools"]["outputSchema"])
            brief = brief_result["structuredContent"]["data"]
            assert brief["next_offset"] == page["next_offset"]
            assert brief["available_categories"] == page["available_categories"]
            assert brief["tools"] == [
                {"name": tool["name"], "category": tool["category"], "invocation": tool["invocation"],
                 "description": tool["description"].splitlines()[0], "required": tool["inputSchema"].get("required", [])}
                for tool in page["tools"]
            ]
            if offset == 0:
                full_bytes = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
                brief_bytes = len(json.dumps(brief_result, ensure_ascii=False).encode("utf-8"))
                assert brief_bytes * 4 <= full_bytes
            definitions.update((tool["name"], tool) for tool in page["tools"])
            offset = page["next_offset"]
        core_names = {name for names in CORE_TOOLS.values() for name in names}
        extension_names = {name for names in EXTENSION_TOOLS.values() for name in names}
        assert definitions.keys() == core_names | extension_names
        for name, definition in definitions.items():
            input_schema = definition["inputSchema"]
            Draft202012Validator.check_schema(input_schema)
            Draft202012Validator.check_schema(definition["outputSchema"])
            assert definition["invocation"] == ("direct" if name in core_names else "call_tool")
            assert input_schema["additionalProperties"] is False
            assert input_schema.get("examples", []) == definition["examples"] == TOOL_EXAMPLES.get(name, [])
            if name in core_names:
                assert schemas[name]["inputSchema"] == input_schema
            for example in definition["examples"]:
                validate(example, input_schema)
        assert definitions["set_slice_center"]["inputSchema"]["properties"]["x"]["description"]
        batch_map = definitions["draw_sprite_maps"]["inputSchema"]["$defs"]["BatchSpriteMapEdit"]
        assert batch_map["additionalProperties"] is False
        assert "palette" not in batch_map["required"]
        assert "palette" in definitions["draw_sprite_map"]["inputSchema"]["required"]
        assert "palette" in definitions["review_frame"]["outputSchema"]["$defs"]["SpriteMapEdit"]["required"]
        assert all(definitions[name]["examples"] for name in TOOL_EXAMPLES)
        exact = call(send, receive, "search_tools", {"query": "draw_text", "detail": "full", "limit": 1})
        assert exact["structuredContent"]["data"]["tools"] == [definitions["draw_text"]]
        for detail in ("brief", "full"):
            suggested = call(send, receive, "search_tools", {"query": "drawtexttt", "detail": detail})
            validate(suggested["structuredContent"], schemas["search_tools"]["outputSchema"])
            assert "suggested" in suggested["structuredContent"]["summary"]
            assert all(("inputSchema" in item) == (detail == "full") for item in suggested["structuredContent"]["data"]["tools"])
        assert call(send, receive, "search_tools", {"detail": "verbose"})["isError"]
        for query, expected in [
            ("draw_sprite_maps", "draw_sprite_maps"),
            ("get_scene_info", "get_sprite_info"),
            ("quality", "ensure_layers_present"),
            ("抖动", "draw_dither_detail"),
            ("质感", "draw_dither_detail"),
            ("色相", "adjust_hsl"),
        ]:
            result = call(send, receive, "search_tools", {"query": query})["structuredContent"]["data"]
            assert expected in [tool["name"] for tool in result["tools"]], result
        bad = [
            ("draw_sprite_map", {"layer_name": "ink", "frame_index": 1, "rows": ["AA", "A"], "palette": {"AA": "#fff"}}, "palette"),
            ("draw_pixels_at", {"layer_name": "ink", "frame_index": 1, "pixels": [{"x": 1, "color": "#fff"}]}, "y"),
            ("draw_pixels_at", {"layer_name": "ink", "frame_index": 1, "pixels": [{"x": 1, "y": 1, "color": "#fff", "oops": 2}]}, "oops"),
            ("get_sprite_info", {"oops": 1}, "Unknown argument"),
            ("call_tool", {"name": "measure_text", "arguments": {"text": "A", "font": bitmap_font, "oops": 1}}, "Unknown argument"),
            ("call_tool", {"name": "get_scene_info", "arguments": {}}, "get_sprite_info"),
            ("call_tool", {"name": "get_tile_at", "arguments": {"layer_name": "tiles", "col": 0, "row": 0}}, "frame_index"),
        ]
        for name, arguments, diagnostic in bad:
            result = call(send, receive, name, arguments)
            assert result["isError"] is True, result
            assert diagnostic in result["content"][0]["text"], result
            assert "executable" not in result["content"][0]["text"].lower(), result
        measured = call(send, receive, "call_tool", {"name": "measure_text", "arguments": {"text": "A", "font": bitmap_font}})
        validate(measured["structuredContent"], definitions["measure_text"]["outputSchema"])
        assert measured["structuredContent"] == json.loads(measured["content"][0]["text"])
        send("tools/list", {}, 21)
        assert receive(21) == initial


def test_initialized_canvas_and_request_palette_over_stdio(tmp_path):
    first = tmp_path / "shared.aseprite"
    second = tmp_path / "local.aseprite"
    named_layers = ["base", '上色/亮"点']
    palette = {"A": "#f00", "B": "#0f0"}
    maps = [
        {"layer_name": ["base"], "frame_index": 1, "rows": ["AB"]},
        {"layer_name": [named_layers[1]], "frame_index": 1, "rows": [".A"], "palette": {"A": "#00f"}},
        {"layer_name": ["base"], "frame_index": 1, "rows": [".."], "palette": {}},
    ]
    with connected_server() as (send, receive):
        def invoke(tool, **arguments):
            result = call(send, receive, tool, arguments)
            assert result["isError"] is False, result
            return result["structuredContent"]["data"]

        for filename, arguments in [
            (first, {"maps": maps, "palette": palette}),
            (second, {"maps": [maps[0] | {"palette": palette}, *maps[1:]]}),
        ]:
            invoke("create_canvas", filename=str(filename), width=2, height=1, initial_layers=named_layers)
            invoke("draw_sprite_maps", **arguments)
            info = invoke("get_sprite_info")
            assert [layer["path"] for layer in info["layers"]] == [[name] for name in named_layers]

        before = digest(second)
        original_first = digest(first)
        for invalid_maps, fields, fragments in [
            (maps[:1], {}, ("maps[0].palette",)),
            ([maps[0] | {"palette": {}}], {"palette": palette}, ('layer_name=["base"]', "Unknown character 'A'", "row 0, column 0")),
            ([maps[0] | {"transparent": "B"}], {"palette": palette}, ("transparent character 'B'",)),
            ([maps[0], maps[0] | {"rows": ["AB", "ABA"]}], {"palette": palette},
             ("maps[1]", "rows[0] has 2", "rows[1] has 3", '"ABA"', "column 2 (grid right boundary")),
            ([maps[0], maps[1] | {"rows": ["A" * 16, "A" * 15]}], {"palette": palette},
             ("maps[1]", f"layer_name={json.dumps([named_layers[1]], ensure_ascii=False)}",
              "rows[0] has 16", "rows[1] has 15", "rows[1][0:15]", "column 15 (first missing cell")),
            ([maps[0] | {"rows": ["A" * 100, "A" * 99]}], {"palette": palette},
             ('rows[1][75:99] = "' + "A" * 24 + '"', "column 99 (first missing cell")),
        ]:
            bad = call(send, receive, "draw_sprite_maps", {"maps": invalid_maps, **fields})
            assert bad["isError"] is True, bad
            assert all(fragment in bad["content"][0]["text"] for fragment in fragments), bad
            assert digest(second) == before

        bad = call(send, receive, "draw_sprite_map", {**maps[0], "rows": ["AZ"], "palette": palette})
        assert bad["isError"] and all(fragment in bad["content"][0]["text"] for fragment in (
            'layer_name=["base"]', "Unknown character 'Z'", "row 0, column 1",
        ))
        assert digest(second) == before

        for initial_layers in ([], [""], ["same", "same"]):
            bad = call(send, receive, "create_canvas", {
                "filename": str(first), "width": 4, "height": 3, "overwrite": True, "initial_layers": initial_layers,
            })
            assert bad["isError"] is True, bad
            assert digest(first) == original_first
            active = invoke("review_frame", frame_index=1)
            assert Path(active["filename"]) == second

    original = frame_image(first.as_posix(), 1, tmp_path)
    assert original.tobytes() == frame_image(second.as_posix(), 1, tmp_path).tobytes()
    assert tuple(original.getpixel((x, 0)) for x in range(2)) == ((255, 0, 0, 255), (0, 0, 255, 255))


def test_dither_detail_is_directly_callable_over_stdio(new_sprite):
    filename = new_sprite(4, 4)
    run(drawing.draw_rectangle_at(
        filename=filename, layer_name="ink", frame_index=1,
        x=0, y=0, width=4, height=4, color="#123456", fill=True,
    ))

    with connected_server() as (send, receive):
        send("tools/list", {}, 30)
        schemas = {
            tool["name"]: tool["outputSchema"]
            for tool in receive(30)["tools"]
        }
        assert "draw_dither_detail" in schemas

        result = call(send, receive, "draw_dither_detail", {
            "filename": filename, "layer_name": "ink", "frame_index": 1,
            "x": 0, "y": 0, "width": 4, "height": 4,
            "color": "#00ff00", "density": 1,
        }, request_id=31)
        assert result["isError"] is False, result
        validate(result["structuredContent"], schemas["draw_dither_detail"])

        pixel = call(send, receive, "get_pixel_color", {
            "filename": filename, "layer_name": "ink", "frame_index": 1,
            "x": 2, "y": 2,
        }, request_id=32)
        assert pixel["structuredContent"]["data"]["hex"] == "#00ff00"


def test_create_layered_sprite_keeps_editable_underpaint_over_stdio(tmp_path):
    target = tmp_path / "new.aseprite"
    other = tmp_path / "other.ase"
    palette = {"A": "#a41", "B": "#fc8", "O": "#234"}
    rules = [
        {"name": "base", "mapping": {"A": "A", "B": "A"}},
        {"name": "shade", "mapping": {"B": "B"}},
        {"name": "outline", "mapping": {"O": "O"}},
        {"name": "notes", "mapping": {}},
    ]
    arguments = {"filename": str(target.with_suffix("")), "rows": ["AB.", ".O."], "palette": palette, "layers": rules}
    with connected_server() as (send, receive):
        def invoke(tool, **values):
            result = call(send, receive, tool, values)
            assert result["isError"] is False, result
            return result["structuredContent"]["data"]

        definition, = invoke("search_tools", query="分层绘制", detail="full", limit=1)["tools"]
        assert definition["name"] == "create_layered_sprite" and definition["invocation"] == "call_tool"
        created = call(send, receive, "call_tool", {"name": definition["name"], "arguments": arguments})
        assert created["isError"] is False, created
        validate(created["structuredContent"], definition["outputSchema"])
        receipt = created["structuredContent"]["data"]
        assert receipt["layer_paths"] == [[rule["name"]] for rule in rules]
        assert Path(receipt["filename"]) == target
        info = invoke("get_sprite_info")
        assert (info["width"], info["height"], info["frames"], info["color_mode"]) == (3, 2, 1, "rgb")
        assert [layer["path"] for layer in info["layers"]] == receipt["layer_paths"]

        base = invoke("get_sprite_map", layer_name=["base"], x=0, y=0, width=3, height=2, palette=palette)
        assert base["rows"] == ["AA.", "..."]
        expected = ((170, 68, 17, 255), (255, 204, 136, 255), (0, 0, 0, 0),
                    (0, 0, 0, 0), (34, 51, 68, 255), (0, 0, 0, 0))
        assert frame_image(str(target), 1, tmp_path).tobytes() == bytes(value for pixel in expected for value in pixel)

        invoke("set_layer_visibility", layer_name=["shade"], visible=False)
        assert frame_image(str(target), 1, tmp_path).getpixel((1, 0)) == expected[0]
        invoke("set_layer_visibility", layer_name=["shade"], visible=True)
        invoke("set_layer_visibility", layer_name=["base"], visible=False)
        image = frame_image(str(target), 1, tmp_path)
        assert (image.getpixel((0, 0)), image.getpixel((1, 0))) == (expected[2], expected[1])

        original = digest(target)
        for changes, message in [
            ({}, "already exists"),
            ({"filename": str(other), "layers": rules[:1]}, "Top layer mapping"),
            ({"filename": str(other), "layers": rules[:2]}, "No layer mapping for 'O'"),
            ({"filename": str(other), "layers": [{"name": "base", "mapping": {"A": "Z"}}]}, "'Z'"),
            ({"filename": str(other), "palette": palette | {"A": "#a418"}}, "must be opaque"),
            ({"filename": str(other), "layers": [rules[0], rules[0], *rules[1:]]}, "unique"),
        ]:
            failed = call(send, receive, "call_tool", {"name": definition["name"], "arguments": arguments | changes})
            assert failed["isError"] is True, failed
            assert message in failed["content"][0]["text"], failed
            assert not other.exists() and digest(target) == original
        assert Path(invoke("review_frame", frame_index=1)["filename"]) == target

        invoke("call_tool", name=definition["name"], arguments={
            "filename": str(other), "rows": [".."], "palette": {},
            "layers": [{"name": "sketch", "mapping": {}}],
        })
        assert frame_image(str(other), 1, tmp_path).getbbox() is None


def test_ordered_batch_uses_one_process_and_commit_and_preserves_on_failure(new_sprite, tmp_path, monkeypatch):
    filename = new_sprite(8, 8)
    run(animation.add_frames(filename=filename, count=1))
    observed = observe_execution(monkeypatch, filename)
    maps = [
        {"layer_name": "base", "frame_index": 1, "rows": ["A..."], "palette": {"A": "#1234567f"}, "mirror_x": True},
        {"layer_name": "top", "frame_index": 2, "rows": ["BB"], "palette": {"B": "#00ff00"}},
        {"layer_name": ["base"], "frame_index": 1, "rows": [".C"], "palette": {"C": "#0000ff"}, "erase_transparent": True, "create_if_missing": False},
    ]
    receipt = payload(run(sprite_map.draw_sprite_maps(filename=filename, maps=maps)))
    assert observed == {"processes": 1, "saves": 1, "commits": 1}
    assert receipt["layer_paths"] == [["base"], ["top"]]
    image = frame_image(filename, 1, tmp_path)
    assert [image.getpixel((x, 0)) for x in range(4)] == [(0, 0, 0, 0), (0, 0, 255, 255), (0, 0, 0, 0), (18, 52, 86, 127)]
    info = payload(run(animation.get_sprite_info(filename=filename)))
    assert [entry["name"] for entry in info["layers"]][-2:] == ["base", "top"]
    before = digest(filename)
    execution_before = observed.copy()
    invalid_widths = maps[:1] + [maps[1] | {"rows": ["BB", "B"]}]
    diagnostic = failure(sprite_map.draw_sprite_maps(filename=filename, maps=invalid_widths))
    assert 'maps[1] (layer_name="top")' in diagnostic
    assert observed == execution_before
    assert digest(filename) == before
    for invalid, diagnostic in [
        (maps[:1] + [{"layer_name": "top", "frame_index": 99, "rows": ["A"], "palette": {"A": "#fff"}}], "maps[1]"),
        (maps[:1] + [{"layer_name": "missing/child", "frame_index": 1, "rows": ["A"], "palette": {"A": "#fff"}}], "maps[1]"),
        (maps[:1] + [{"layer_name": "top", "frame_index": 1, "rows": ["AB"], "palette": {"A": "#f00", "B": "#0f0"}, "mirror_x": True}], "maps[1]"),
        ([{"layer_name": "empty", "frame_index": 1, "rows": ["."], "palette": {}}, {"layer_name": "empty", "frame_index": 1, "rows": ["A"], "palette": {"A": "#fff"}, "create_if_missing": False}], "maps[1]"),
    ]:
        assert diagnostic in failure(sprite_map.draw_sprite_maps(filename=filename, maps=invalid))
        assert digest(filename) == before
    assert not list(tmp_path.glob(".aseprite-edit-*"))


def test_exact_paths_quality_repairs_and_cross_project_copy(new_sprite):
    filename = new_sprite()
    group = '组/带斜杠:"'
    assert payload(run(canvas.add_group(filename=filename, group_name=group)))["layer_paths"] == [[group]]
    for parent in ([group], None):
        receipt = payload(run(canvas.add_layer(filename=filename, layer_name="ink", group=parent or "")))
        assert receipt["layer_paths"] == ([[group, "ink"]] if parent else [["ink"]])
    run(canvas.add_layer(filename=filename, layer_name="literal/ink"))
    maps = [{"layer_name": ref, "frame_index": 1, "rows": ["A"], "palette": {"A": color}}
            for ref, color in [([group, "ink"], "#f00"), (["ink"], "#0f0"), (["literal/ink"], "#00f")]]
    run(sprite_map.draw_sprite_maps(filename=filename, maps=maps))
    for item in maps:
        result = payload(run(sprite_map.get_sprite_map(filename=filename, layer_name=item["layer_name"], frame_index=1,
                                                      x=0, y=0, width=1, height=1, palette=item["palette"])))
        assert result["layer"] == item["layer_name"] and result["rows"] == ["A"]
    run(canvas.add_layer(filename=filename, layer_name="empty", group=[group]))
    before = digest(filename)
    assert "not found" in failure(quality.ensure_layers_present(filename=filename, layer_names=[[group, "empty"], [group, "absent"]]))
    assert digest(filename) == before
    validation = payload(run(quality.validate_scene(filename=filename, required_layers=[[group, "empty"], [group, "absent"]])))
    assert validation["missing_layers"] == [[group, "absent"]]
    assert validation["missing_cels"] == [{"layer": [group, "empty"], "frame": 1}]
    for malformed in (["ink:2-1"], ["ink:1"], ["ink:"]):
        assert "Invalid" in failure(quality.audit_animation(filename=filename, layer_frame_ranges=malformed))
    run(quality.ensure_layers_present(filename=filename, layer_names=[[group, "empty"]]))
    run(animation.add_frames(filename=filename, count=1))
    audit = payload(run(quality.audit_animation(filename=filename, report_cels=True, layer_frame_ranges=[{"layer": [group, "ink"], "ranges": [[1, 1]]}])))
    assert {tuple(entry["layer"]) for entry in audit["cels"][0]["cels"]} >= {(group, "ink"), ("ink",), ("literal/ink",)}
    assert audit["out_of_range"] == [{"layer": [group, "ink"], "frame": 2}]
    truncated = payload(run(quality.audit_animation(filename=filename, layer_frame_ranges=["ink:1-1"],
        overlap_pairs=[{"a": [group, "ink"], "b": ["ink"]}], max_overlaps=0, max_out_of_range=0)))
    assert truncated["summary"]["out_of_range_total"] == 1
    assert truncated["summary"]["out_of_range_truncated"] is True
    assert truncated["summary"]["overlaps_total"] == 2 and truncated["summary"]["overlaps_truncated"] is True
    options = dict(filename=filename, layer_names=[[group, "ink"]], layer_frame_ranges=[{"layer": [group, "ink"], "ranges": [[1, 1]]}], layer_order=[[group, "empty"], [group, "ink"]], out_of_range_action="delete_cels")
    before = digest(filename)
    report = payload(run(quality.animation_sanitize(**options, report_only=True)))
    assert report["out_of_range"] == 1 and digest(filename) == before
    assert payload(run(quality.animation_sanitize(**options)))["deleted"] == 1
    info = payload(run(animation.get_sprite_info(filename=filename)))
    assert [entry["name"] for entry in info["layers"] if entry["parent"] == group] == ["empty", "ink"]
    assert payload(run(quality.validate_scene(filename=filename, required_layers=[[group, "ink"]])))["missing_cels"] == [{"layer": [group, "ink"], "frame": 2}]
    target = new_sprite()
    run(canvas.add_group(filename=target, group_name=group))
    copied = payload(run(scene.copy_layers_between_sprites(source_filename=filename, target_filename=target, layer_names=[[group, "ink"]])))
    assert copied["layer_paths"] == [[group, "ink"]]
    result = payload(run(sprite_map.get_sprite_map(filename=target, layer_name=[group, "ink"], x=0, y=0, width=1, height=1)))
    assert list(result["palette"].values()) == ["#ff0000"]
    renamed = payload(run(layers.rename_layer(filename=target, layer_name=[group, "ink"], new_name="final")))
    assert renamed["layer_paths"] == [[group, "final"]]
    duplicate = payload(run(layers.duplicate_layer(filename=target, layer_name=[group, "final"])))
    assert duplicate["layer_paths"] == [[group, "final copy"]]
    run(canvas.add_layer(filename=target, layer_name="final", group=[group]))
    assert "Ambiguous" in failure(sprite_map.get_sprite_map(filename=target, layer_name=[group, "final"], x=0, y=0, width=1, height=1))


def test_batch_keeps_preflight_targets_when_a_new_name_shadows_a_nested_layer(new_sprite):
    filename = new_sprite()
    run(canvas.add_group(filename=filename, group_name="art"))
    run(canvas.add_layer(filename=filename, layer_name="ink", group=["art"]))
    result = payload(run(sprite_map.draw_sprite_maps(filename=filename, maps=[
        {"layer_name": ["ink"], "frame_index": 1, "rows": ["A"], "palette": {"A": "#f00"}},
        {"layer_name": "ink", "frame_index": 1, "rows": ["A"], "palette": {"A": "#0f0"}},
    ])))
    assert result["layer_paths"] == [["ink"], ["art", "ink"]]
    for ref, expected in [(["ink"], "#ff0000"), (["art", "ink"], "#00ff00")]:
        grid = payload(run(sprite_map.get_sprite_map(filename=filename, layer_name=ref, x=0, y=0, width=1, height=1)))
        assert list(grid["palette"].values()) == [expected]


@pytest.mark.skipif(os.name != "nt", reason="Windows path spellings")
def test_review_snapshot_accepts_windows_path_variants(new_sprite, tmp_path):
    project = Path(new_sprite())
    other = new_sprite()
    run(sprite_map.draw_sprite_map(filename=str(project), layer_name="ink", frame_index=1,
                                   rows=["A"], palette={"A": "#f00"}))
    with connected_server(env={"ASERITE_MCP_WORKSPACE": str(tmp_path)}) as (send, receive):
        target = {"frame_index": 1, "layer_name": ["ink"]}
        first = call(send, receive, "review_frame", target | {"filename": str(project)})
        snapshot = first["structuredContent"]["data"]
        before = {key: snapshot[key] for key in ("filename", "frame", "region", "map", "cel")}
        assert "\\" in before["filename"]
        variant = project.as_posix()
        variant = variant[0].swapcase() + variant[1:]
        unchanged = {"changed_pixels": 0, "changed_bounds": None}
        for path in (variant, project.name, ""):
            result = call(send, receive, "review_frame", target | {"filename": path, "before": before})
            assert result["structuredContent"]["data"]["changes"] == {"composite": unchanged, "cel": unchanged}
        mismatch = call(send, receive, "review_frame", target | {"filename": other, "before": before})
        assert mismatch["isError"] and "same absolute filename" in mismatch["content"][0]["text"]


def test_review_matches_independent_render_and_cleans_failed_artifacts(new_sprite, tmp_path, monkeypatch):
    filename = new_sprite(8, 8)
    run(canvas.add_group(filename=filename, group_name="visible"))
    run(canvas.add_layer(filename=filename, layer_name="ink", group=["visible"]))
    run(sprite_map.draw_sprite_map(filename=filename, layer_name=["visible", "ink"], frame_index=1, rows=["AB"], palette={"A": "#1234567f", "B": "#ff0000"}))
    run(animation.set_cel_position(filename=filename, layer_name=["visible", "ink"], frame_index=1, x=1, y=2))
    run(animation.set_layer_opacity(filename=filename, layer_name=["visible"], opacity=128))
    run(canvas.add_group(filename=filename, group_name="hidden"))
    run(canvas.add_layer(filename=filename, layer_name="ink", group=["hidden"]))
    run(drawing.draw_pixels_at(filename=filename, layer_name=["hidden", "ink"], frame_index=1, pixels=[{"x": 0, "y": 0, "color": "#fff"}]))
    run(animation.set_layer_visibility(filename=filename, layer_name=["hidden"], visible=False))
    run(tilemap.create_tilemap_layer(filename=filename, layer_name="tiles", tile_width=2, tile_height=2))
    run(tilemap.draw_on_tile(filename=filename, layer_name=["tiles"], tile_index=1, pixels=[{"x": 0, "y": 0, "color": "#00ff007f"}]))
    run(tilemap.set_tiles(filename=filename, layer_name=["tiles"], frame_index=1, tiles=[{"col": 3, "row": 3, "tile_index": 1}]))
    expected = frame_image(filename, 1, tmp_path)
    before = digest(filename)
    observed = observe_execution(monkeypatch, filename)
    result = payload(run(review.review_frame(filename=filename, frame_index=1)))
    assert observed == {"processes": 1, "saves": 0, "commits": 0}
    assert digest(filename) == before
    assert "image layers" in failure(quality.ensure_layers_present(filename=filename, layer_names=[["tiles"]]))
    assert digest(filename) == before
    assert result["map"]["source"] == "composite" and result["map"]["layer"] is None
    assert decode_grid(result["map"]).tobytes() == expected.tobytes()
    preview = Path(result["preview_png"])
    with Image.open(preview) as image:
        assert image.convert("RGBA").tobytes() == expected.resize((64, 64), Image.Resampling.NEAREST).tobytes()
    region = payload(run(review.review_frame(filename=filename, frame_index=1, region={"x": -1, "y": -1, "width": 4, "height": 5}, palette=result["map"]["palette"])))
    assert decode_grid(region["map"]).tobytes() == expected.crop((-1, -1, 3, 4)).tobytes()
    directory = preview.parent
    retained = set(directory.iterdir())
    assert "range" in failure(review.review_frame(filename=filename, frame_index=99))
    assert set(directory.iterdir()) == retained
    state.cleanup_review_directory()
    assert not preview.exists()


def test_layer_review_previews_match_raw_cels_and_keep_request_order(new_sprite, tmp_path, monkeypatch):
    filename = new_sprite()
    run(canvas.add_group(filename=filename, group_name="art"))
    run(canvas.add_layer(filename=filename, layer_name="ink", group=["art"]))
    run(canvas.add_layer(filename=filename, layer_name="empty"))
    run(sprite_map.draw_sprite_maps(filename=filename, palette={"A": "#f00", "B": "#1234567f"}, maps=[
        {"layer_name": "base", "frame_index": 1, "rows": ["A"]},
        {"layer_name": ["art", "ink"], "frame_index": 1, "rows": ["B"], "x": 1, "y": 1},
    ]))
    run(animation.set_layer_visibility(filename=filename, layer_name=["art"], visible=False))
    before = digest(filename)
    observed = observe_execution(monkeypatch, filename)
    request = {"filename": filename, "frame_index": 1, "layer_names": [["art", "ink"], "base", "empty"],
               "region": {"x": -1, "y": 0, "width": 4, "height": 3}}
    result = run(review.review_frame(**request, preview_mode="both"))
    data = payload(result)
    assert observed == {"processes": 1, "saves": 0, "commits": 0}
    assert data["cel"] is None
    expected_layers = [["art", "ink"], ["base"], ["empty"]]
    assert [cel["layer_name"] for cel in data["cels"]] == expected_layers
    assert [cel["status"] for cel in data["cels"]] == ["exact", "exact", "missing_cel"]
    assert data["preview_png"] == data["previews"][0]["png"]
    assert [preview["kind"] for preview in data["previews"]] == ["composite", "layer", "layer", "layer"]
    assert [preview["layer_name"] for preview in data["previews"]] == [None, *expected_layers]
    expected = frame_image(filename, 1, tmp_path).crop((-1, 0, 3, 3))
    hidden = Image.new("RGBA", (4, 3))
    hidden.putpixel((2, 1), (18, 52, 86, 127))
    for preview, block, image in zip(data["previews"], result.content[1:],
                                      [expected, hidden, expected, Image.new("RGBA", (4, 3))], strict=True):
        assert b64decode(block.data) == Path(preview["png"]).read_bytes()
        with Image.open(preview["png"]) as png:
            assert png.size == (32, 24)
            assert png.tobytes() == image.resize((32, 24), Image.Resampling.NEAREST).tobytes()

    selected = payload(run(review.review_frame(**request, preview_mode="layer")))
    assert [preview["layer_name"] for preview in selected["previews"]] == expected_layers
    assert selected["preview_png"] == selected["previews"][0]["png"]
    default = payload(run(review.review_frame(**request)))
    assert [preview["kind"] for preview in default["previews"]] == ["composite"]
    for overrides, message in [
        ({"layer_name": "base"}, "either layer_name or layer_names"),
        ({"layer_names": ["base", ["base"]]}, "Duplicate review layer"),
        ({"layer_names": None, "preview_mode": "both"}, "require layer_name"),
        ({"region": {"width": 257, "height": 257}}, "pixel budget"),
        ({"layer_names": [["art"]]}, "is a group"),
    ]:
        assert message in failure(review.review_frame(**(request | overrides)))
    assert digest(filename) == before

    directory = Path(data["preview_png"]).parent
    retained = set(directory.iterdir())
    save = Image.Image.save

    def fail_second_preview(image, path, *args, **kwargs):
        if Path(path).name.endswith("-1-8x.png"):
            Path(path).write_bytes(b"incomplete")
            raise OSError("preview write failed")
        return save(image, path, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", fail_second_preview)
    with pytest.raises(OSError, match="preview write failed"):
        run(review.review_frame(**request, preview_mode="both"))
    assert set(directory.iterdir()) == retained


def test_review_delivers_preview_when_exact_grid_exceeds_capacity(new_sprite, tmp_path):
    filename = new_sprite(8, 8)
    run(canvas.add_layer(filename=filename, layer_name="ink"))
    request = dict(filename=filename, frame_index=1, layer_name=["ink"])
    first = payload(run(review.review_frame(**request)))
    assert first["cel"]["status"] == "missing_cel"
    snapshot = {key: first[key] for key in ("filename", "frame", "region", "map", "cel")}
    run(drawing.draw_pixels_at(filename=filename, layer_name="ink", frame_index=1,
                               pixels=[{"x": i % 8, "y": i // 8, "color": f"#{i:02x}1234"} for i in range(64)]))
    before = digest(filename)
    result = payload(run(review.review_frame(**request, before=snapshot, preview_mode="both")))
    assert result["map"] is None and result["map_unavailable"] == "palette_capacity"
    assert result["region"] == {"x": 0, "y": 0, "width": 8, "height": 8}
    assert result["cel"] == {"layer_name": ["ink"], "status": "palette_capacity", "edit": None}
    delta = {"changed_pixels": 64, "changed_bounds": result["region"]}
    assert result["changes"] == {"composite": delta, "cel": delta}
    preview = Path(result["preview_png"])
    isolated = Path(result["previews"][1]["png"])
    assert set(preview.parent.iterdir()) == {Path(first["preview_png"]), preview, isolated}
    expected = frame_image(filename, 1, tmp_path).resize((64, 64), Image.Resampling.NEAREST)
    with Image.open(preview) as image:
        assert image.convert("RGBA").tobytes() == expected.tobytes()
    with Image.open(isolated) as image:
        assert image.tobytes() == expected.tobytes()
    assert digest(filename) == before


def test_review_compares_hidden_cel_by_rgba_in_one_batch(new_sprite, monkeypatch):
    filename = new_sprite(32, 32)
    run(canvas.add_group(filename=filename, group_name="art"))
    run(canvas.add_layer(filename=filename, layer_name="ink", group=["art"]))
    run(canvas.add_layer(filename=filename, layer_name="ink"))
    run(canvas.add_layer(filename=filename, layer_name="empty"))
    run(sprite_map.draw_sprite_map(filename=filename, layer_name=["art", "ink"], frame_index=1,
                                   rows=["AB"], palette={"A": "#1234567f", "B": "#ff0000"}))
    run(animation.set_cel_position(filename=filename, layer_name=["art", "ink"], frame_index=1, x=7, y=8))
    run(animation.set_layer_visibility(filename=filename, layer_name=["art"], visible=False))
    region = {"x": 6, "y": 8, "width": 4, "height": 1}
    request = dict(filename=filename, frame_index=1, layer_name=["art", "ink"], region=region)
    before = payload(run(review.review_frame(**request, palette={"A": "#1234567f", "B": "#ff0000"})))
    original = before["cel"]["edit"]
    assert original["rows"] == [".AB."]
    assert original["layer_name"] == ["art", "ink"]
    assert original["erase_transparent"] is True and original["create_if_missing"] is False
    snapshot = {key: before[key] for key in ("filename", "frame", "region", "map", "cel")}
    unchanged = {"changed_pixels": 0, "changed_bounds": None}
    new_palette = {"K": "#1234567f", "L": "#ff0000"}
    assert payload(run(review.review_frame(**request, before=snapshot, palette=new_palette)))["changes"] == {
        "composite": unchanged, "cel": unchanged,
    }
    run(sprite_map.draw_sprite_map(filename=filename, **(original | {"rows": ["...."]})))
    saved = digest(filename)
    observed = observe_execution(monkeypatch, filename)
    result = payload(run(review.review_frame(**request, before=snapshot)))
    assert result["changes"] == {
        "composite": unchanged,
        "cel": {"changed_pixels": 2, "changed_bounds": {"x": 7, "y": 8, "width": 2, "height": 1}},
    }
    assert result["cel"]["edit"]["rows"] == ["...."]
    assert observed == {"processes": 1, "saves": 0, "commits": 0}
    assert digest(filename) == saved
    assert "same absolute filename" in failure(review.review_frame(**request, before=snapshot | {"filename": "other"}))
    assert "same region" in failure(review.review_frame(**request, before=snapshot | {"region": region | {"x": 0}}))
    assert "same layer path" in failure(review.review_frame(**(request | {"layer_name": ["ink"]}), before=snapshot))
    assert "exact composite" in failure(review.review_frame(**request, before=snapshot | {"map": before["map"] | {"lossy": True}}))
    empty = payload(run(review.review_frame(**(request | {"layer_name": ["empty"]}))))
    assert empty["cel"] == {"layer_name": ["empty"], "status": "missing_cel", "edit": None}
    assert "is a group" in failure(review.review_frame(**(request | {"layer_name": ["art"]})))


def test_snapshot_id_matches_inline_grid_and_compares_over_capacity(new_sprite):
    filename = new_sprite(8, 8)
    with connected_server() as (send, receive):
        def invoke(tool, **arguments):
            response = call(send, receive, tool, {"filename": filename, **arguments})
            assert not response["isError"], response
            return response["structuredContent"]["data"]

        target = {"frame_index": 1, "layer_name": ["ink"]}
        invoke("draw_sprite_map", **target, rows=["A"], palette={"A": "#f00"})
        first = invoke("review_frame", **target)
        baseline = {key: first[key] for key in ("filename", "frame", "region", "map", "cel")}
        assert first["snapshot_id"]
        invoke("draw_sprite_map", **target, rows=["A"], palette={"A": "#0f0"})
        delta = {"changed_pixels": 1, "changed_bounds": {"x": 0, "y": 0, "width": 1, "height": 1}}
        assert invoke("review_frame", **target, before=baseline)["changes"] == {"composite": delta, "cel": delta}
        assert invoke("review_frame", **target, before_id=first["snapshot_id"])["changes"] == {"composite": delta, "cel": delta}
        incompatible = call(send, receive, "review_frame", {
            **target, "before": baseline, "before_id": first["snapshot_id"],
        })
        assert incompatible["isError"] and "either before or before_id" in incompatible["content"][0]["text"]

        invoke("draw_pixels_at", **target,
               pixels=[{"x": i % 8, "y": i // 8, "color": f"#{i:02x}1234"} for i in range(64)])
        over_capacity = invoke("review_frame", **target)
        assert over_capacity["map"] is None and over_capacity["cel"]["status"] == "palette_capacity"
        invoke("draw_sprite_map", **target, rows=["A"], palette={"A": "#fff"})
        assert invoke("review_frame", **target, before_id=over_capacity["snapshot_id"])["changes"] == {"composite": delta, "cel": delta}
        invoke("set_layer_visibility", layer_name=["ink"], visible=False)
        hidden = invoke("review_frame", **target)
        invoke("draw_sprite_map", **target, rows=["A"], palette={"A": "#f00"})
        assert invoke("review_frame", **target, before_id=hidden["snapshot_id"])["changes"] == {
            "composite": {"changed_pixels": 0, "changed_bounds": None}, "cel": delta,
        }


@pytest.mark.parametrize("max_records,max_bytes", [(2, 40), (32, 20)])
def test_snapshot_budget_keeps_only_recent_baselines_over_stdio(new_sprite, max_records, max_bytes):
    filename = new_sprite()
    code = f"""
from aseprite_mcp import create_server
from aseprite_mcp.core import review_snapshots
review_snapshots.MAX_REVIEW_SNAPSHOTS = {max_records}
review_snapshots.MAX_REVIEW_SNAPSHOT_BYTES = {max_bytes}
create_server().run(transport='stdio')
"""
    with connected_server(code=code) as (send, receive):
        request = {"filename": filename, "frame_index": 1, "region": {"width": 2, "height": 1}}

        def review_data(**overrides):
            result = call(send, receive, "review_frame", request | overrides)
            assert not result["isError"], result
            return result["structuredContent"]["data"]

        ids = [review_data()["snapshot_id"] for _ in range(3)]
        assert None not in ids and len(set(ids)) == 3
        assert review_data(region={"width": max_bytes // 4 + 1, "height": 1})["snapshot_id"] is None
        expired = call(send, receive, "review_frame", request | {"before_id": ids[0]})
        assert expired["isError"] and "Review the same target again" in expired["content"][0]["text"]
        assert review_data(before_id=ids[1])["changes"]["composite"]["changed_pixels"] == 0
        assert review_data(before_id=ids[2])["changes"]["composite"]["changed_pixels"] == 0


def test_text_stamp_preserves_holes_alpha_and_clips_at_canvas(new_sprite, bitmap_font):
    filename = new_sprite(8, 8)
    run(drawing.draw_rectangle_at(filename=filename, layer_name="label", frame_index=1, x=0, y=0, width=8, height=8, color="#0000ff", fill=True))
    result = payload(run(text.draw_text(filename=filename, text="O", x=-1, y=1, font=bitmap_font, layer_name=["label"], frame_index=1, color="#ff000080")))
    assert result["layer_paths"] == [["label"]]
    assert result["stamp_bounds"] == {"x": -1, "y": 1, "width": 4, "height": 5}
    image = decode_grid(payload(run(sprite_map.get_sprite_map(filename=filename, layer_name=["label"], x=0, y=0, width=8, height=8))))
    for y in range(8):
        for x in range(8):
            covered = 1 <= y < 6 and x < 3 and FIXTURE_GLYPHS["O"][y-1][x+1] == "#"
            assert image.getpixel((x, y)) == ((128, 0, 127, 255) if covered else (0, 0, 255, 255))
