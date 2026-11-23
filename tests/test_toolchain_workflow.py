"""Typed discovery, exact targets, atomic grids and same-image review through public tools."""

import json
from pathlib import Path

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
            result = call(send, receive, "search_tools", {"limit": 20, "offset": offset})
            validate(result["structuredContent"], schemas["search_tools"]["outputSchema"])
            page = result["structuredContent"]["data"]
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
            ([maps[0] | {"palette": {}}], {"palette": palette}, ("row 0, column 0",)),
            ([maps[0] | {"transparent": "B"}], {"palette": palette}, ("transparent character 'B'",)),
            ([maps[0], maps[0] | {"rows": ["AB", "ABA"]}], {"palette": palette},
             ("maps[1]", "rows[0] has 2", "rows[1] has 3", '"ABA"', "column 2 (grid right boundary")),
            ([maps[0] | {"rows": ["ABA", "AB"]}], {"palette": palette},
             ("rows[0] has 3", "rows[1] has 2", '"AB"', "column 2 (first missing cell")),
        ]:
            bad = call(send, receive, "draw_sprite_maps", {"maps": invalid_maps, **fields})
            assert bad["isError"] is True, bad
            assert all(fragment in bad["content"][0]["text"] for fragment in fragments), bad
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

        definition, = invoke("search_tools", query="分层绘制", limit=1)["tools"]
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
    result = payload(run(review.review_frame(**request, before=snapshot)))
    assert result["map"] is None and result["map_unavailable"] == "palette_capacity"
    assert result["region"] == {"x": 0, "y": 0, "width": 8, "height": 8}
    assert result["cel"] == {"layer_name": ["ink"], "status": "palette_capacity", "edit": None}
    delta = {"changed_pixels": 64, "changed_bounds": result["region"]}
    assert result["changes"] == {"composite": delta, "cel": delta}
    preview = Path(result["preview_png"])
    assert set(preview.parent.iterdir()) == {Path(first["preview_png"]), preview}
    expected = frame_image(filename, 1, tmp_path).resize((64, 64), Image.Resampling.NEAREST)
    with Image.open(preview) as image:
        assert image.convert("RGBA").tobytes() == expected.tobytes()
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
