"""Compact character-grid editing and readback."""

import json
from typing import Annotated, Dict, List

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from ..core.commands import AsepriteCommand, lua_escape
from ..core.composite import COMPOSE_FRAME
from ..core.contracts import Byte, Character, ContractModel, FrameIndex, LayerRef, NonnegativeInt, Palette, PositiveInt, ToolOutput
from ..core.editing import edit_output, execute_edit_script
from ..core.lua import EDIT_TARGET, FIND_LAYER, LAYER_NAMES, NORMALIZE_CEL, lua_layer_ref
from ..core.results import EditReceipt, SpriteMap
from ..core.sprite_grid import compile_sprite_map, encode_sprite_map, parse_sprite_map
from ..core.state import prepare_filename

_TILEMAP_REFUSAL = "is a tilemap layer: its cel stores tile indexes, not pixels"


class SpriteMapEdit(ContractModel):
    layer_name: LayerRef
    frame_index: FrameIndex
    rows: Annotated[list[str], Field(min_length=1, description="Equal-width pixel rows, top to bottom.")]
    palette: Annotated[Palette, Field(description="Single-character keys mapped to RGB/RGBA hex colours; transparent is reserved.")]
    x: int = Field(default=0, description="Sprite-global x of the grid origin; may be negative for clipping.")
    y: int = Field(default=0, description="Sprite-global y of the grid origin; may be negative for clipping.")
    transparent: Character = "."
    mirror_x: bool = False
    mirror_y: bool = False
    erase_transparent: bool = False
    create_if_missing: bool = True


async def draw_sprite_maps(*, filename: str = "", maps: Annotated[list[SpriteMapEdit], Field(min_length=1)]) -> ToolOutput[EditReceipt]:
    """Draw ordered maps across layers/frames with one all-or-nothing project commit.

    Args:
        filename: Project, defaulting to the active file.
        maps: Ordered grid edits. All frames must exist. New top-level layers follow first occurrence order.
    """
    filename = prepare_filename(filename)
    if not maps:
        raise ToolError("maps must contain at least one map")
    compiled = []
    for index, item in enumerate(maps):
        try:
            item = item if isinstance(item, SpriteMapEdit) else SpriteMapEdit.model_validate(item)
            _, _, pixels = compile_sprite_map(item.rows, item.palette, item.transparent,
                                              item.mirror_x, item.mirror_y, item.erase_transparent)
        except (ToolError, ValidationError) as exc:
            raise ToolError(f"maps[{index}]: {exc}") from exc
        compiled.append(dict(layer=item.layer_name, frame=item.frame_index, create=item.create_if_missing,
                             pixels=[[item.x+x, item.y+y, *rgba] for (x,y),rgba in sorted(pixels.items())]))
    script = EDIT_TARGET + NORMALIZE_CEL + '\nlocal edits = json.decode("' + lua_escape(json.dumps(compiled, ensure_ascii=False)) + '")\n' + r'''
    local spr = app.activeSprite
    if not spr then error("No active sprite") end
    if spr.colorMode ~= ColorMode.RGB then error("Sprite maps require RGB mode. Tip: use set_color_mode(mode='rgb') first.") end
    local planned_layers, planned_cels, bindings = {}, {}, {}
    for index, edit in ipairs(edits) do
        local ok, message = pcall(function()
            require_frame(spr, edit.frame)
            local target = find_layer(spr, edit.layer)
            local path = target and layer_path(target) or (type(edit.layer) ~= "string" and edit.layer or {edit.layer})
            local key = json.encode(path)
            local binding = target and {layer=target} or planned_layers[key] or {ref=edit.layer}
            if not target then
                local creatable = (type(edit.layer) ~= "string" and #edit.layer == 1)
                               or (type(edit.layer) == "string" and not string.find(edit.layer, "/", 1, true))
                if not planned_layers[key] and (not edit.create or not creatable) then
                    error("Layer " .. layer_ref_text(edit.layer) .. " not found; create groups and nested layers first")
                end
                if #edit.pixels > 0 then planned_layers[key] = binding end
            elseif target.isGroup or target.isTilemap then error("Sprite maps require a leaf image layer") end
            local cel_key = key .. ":" .. edit.frame
            if not edit.create and not planned_cels[cel_key] and (not target or not target:cel(spr.frames[edit.frame])) then
                error("No cel on requested layer/frame")
            end
            if #edit.pixels > 0 then planned_cels[cel_key] = true end
            bindings[index] = binding
        end)
        if not ok then error("maps[" .. (index-1) .. "] " .. layer_ref_text(edit.layer) .. ": " .. message) end
    end
    local changed = false
    _aseprite_edit_targets = {}
    app.transaction(function()
        for index, edit in ipairs(edits) do
            local ok, message = pcall(function()
                if #edit.pixels == 0 then return end
                local binding = bindings[index]
                local layer = binding.layer or require_layer(spr, binding.ref, true)
                binding.layer = layer
                remember_target(layer)
                require_cel(spr, layer, edit.frame, edit.create)
                local cel = normalize_cel(spr, layer, spr.frames[edit.frame], false)
                for _, pixel in ipairs(edit.pixels) do
                    if pixel[1] >= 0 and pixel[2] >= 0 and pixel[1] < spr.width and pixel[2] < spr.height then
                        cel.image:putPixel(pixel[1], pixel[2], app.pixelColor.rgba(pixel[3],pixel[4],pixel[5],pixel[6]))
                    end
                end
                changed = true
            end)
            if not ok then error("maps[" .. (index-1) .. "]: " .. message) end
        end
    end)
    if changed then save_project(spr) else print("PROJECT_UNCHANGED") end
    '''
    execution = await execute_edit_script(script, filename)
    return edit_output("Sprite maps applied in order", filename, execution)


async def draw_sprite_map(*, filename: str='', layer_name: LayerRef, frame_index: FrameIndex, rows: List[str], palette: Palette, x: int=0, y: int=0, transparent: Character='.', mirror_x: bool=False, mirror_y: bool=False, erase_transparent: bool=False, create_if_missing: bool=True) -> ToolOutput[EditReceipt]:
    """Draw a whole region from a compact character-grid map.

    `rows` is a list of equal-length strings, one per pixel row, top to
    bottom; `palette` maps each character to a colour. This is the compact
    alternative to draw_pixels_at's {x, y, color} lists:

        draw_sprite_map(
            layer_name="hero", frame_index=1,
            rows=["..1111..",
                  ".122221.",
                  "12233221"],
            palette={"1": "#3b2a1e", "2": "#8b5a2b", "3": "#f2c48d"},
        )

    Characters equal to `transparent` ("." by default) are skipped, so
    whatever is already on the layer shows through. Pass
    erase_transparent=true to clear them instead — that is what makes a
    map round-trip exactly after pixels are deleted in an edit.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer to draw on
        frame_index: Frame index starting at 1
        rows: Grid rows, top to bottom; every row must be the same length
        palette: Character -> hex colour (#RGB, #RGBA, #RRGGBB or #RRGGBBAA)
        x: Sprite-global x of the grid's top-left cell (default 0)
        y: Sprite-global y of the grid's top-left cell (default 0)
        transparent: Character meaning "no pixel here" (default ".")
        mirror_x: Also draw every cell at its left-right reflection, so a symmetric sprite only has to be authored once. The mirror is in place: the grid keeps its width, so author the full width with the far half left as `transparent`
        mirror_y: Also draw every cell at its top-bottom reflection (in place)
        erase_transparent: Clear transparent cells instead of leaving them
        create_if_missing: Create the layer (top-level names only) and cel if they don't exist
    """
    try:
        edit = SpriteMapEdit(
            layer_name=layer_name, frame_index=frame_index, rows=rows, palette=palette,
            x=x, y=y, transparent=transparent, mirror_x=mirror_x, mirror_y=mirror_y,
            erase_transparent=erase_transparent, create_if_missing=create_if_missing,
        )
    except ValidationError as exc:
        raise ToolError(f"Invalid sprite map: {exc}") from exc
    result = await draw_sprite_maps(filename=filename, maps=[edit])
    result.data.frame = frame_index
    return result


async def get_sprite_map(
    *,
    filename: str = "",
    layer_name: LayerRef = "",
    frame_index: FrameIndex = 1,
    x: int,
    y: int,
    width: PositiveInt,
    height: PositiveInt,
    palette: Palette | None = None,
    max_colors: NonnegativeInt = 0,
    alpha_threshold: Byte = 1,
    transparent: Character = ".",
    composite: bool = False,
) -> ToolOutput[SpriteMap]:
    """Read a rectangular region back as a compact character-grid map.

    Returns JSON whose `rows`, `palette` and `transparent` are shaped
    exactly like draw_sprite_map's arguments, so a read/edit/write loop
    needs no reformatting:

        {"layer": "hero", "frame": 1, "x": 0, "y": 0,
         "width": 16, "height": 16, "transparent": ".",
         "columns": "0123456789abcdef",
         "palette": {"0": "#3b2a1e", "1": "#8b5a2b"},
         "rows": ["....0011........", ...]}

    `columns` labels each column's x offset, so a character's position can
    be read off without counting. Against get_pixels_rect's per-pixel JSON
    a 16x16 region goes from ~256 objects to 16 short strings — and unlike
    judging an exported PNG by eye, the hex values are exact.

    Auto-assigned characters follow ascending colour order. Pass `palette`
    (e.g. a previous result's) to pin the assignment: characters then stay
    stable across edits, so two maps can be diffed character by character.

    Args:
        filename: Aseprite file to read (optional; defaults to the session's active file)
        layer_name: Explicit layer name; may be empty only for composite reads
        frame_index: Frame index starting at 1
        x: Left edge of the region (sprite-global)
        y: Top edge of the region (sprite-global)
        width: Region width
        height: Region height
        palette: Optional character -> hex colour map to reuse for the output
        max_colors: Quantise to at most this many colours (0 = no limit)
        alpha_threshold: Alpha below this becomes `transparent` (default 1)
        transparent: Character emitted for empty cells (default ".")
        composite: Read the visible flattened composite instead of a single layer
    """
    filename = prepare_filename(filename)
    if width <= 0 or height <= 0:
        raise ToolError("Width and height must be > 0")
    if max_colors < 0:
        raise ToolError("max_colors must be >= 0")
    if not 0 <= alpha_threshold <= 255:
        raise ToolError("alpha_threshold must be between 0 and 255")
    if not composite and not layer_name:
        raise ToolError("Invalid layer_name: specify an explicit layer, or composite=true")
    if not isinstance(transparent, str) or len(transparent) != 1:
        raise ToolError(f"Invalid transparent: must be a single character, got {transparent!r}")

    _, error = parse_sprite_map([transparent], palette or {}, transparent)
    if error:
        raise ToolError(error)

    safe_layer = lua_escape(layer_name)

    if composite:
        # Visible layers only — see COMPOSE_FRAME for why flattening a
        # clone beats Sprite:flatten() directly.
        reader = f"""
        {COMPOSE_FRAME}
        local img = compose_frame(spr, idx, nil)
        local ox, oy = 0, 0
        """
    else:
        reader = f"""
        if spr.colorMode ~= ColorMode.RGB then print("ERROR:Sprite maps require RGB mode. Tip: use set_color_mode(mode='rgb') first.") return end
        local cel = nil
        {FIND_LAYER}
        {LAYER_NAMES}
        local target = find_layer(spr, {lua_layer_ref(layer_name)})
        if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end
        if target.isTilemap then print("ERROR:Layer '{safe_layer}' {_TILEMAP_REFUSAL}. Tip: use get_composite_rect for the rendered colour.") return end
        print("LAYER_PATH:" .. json.encode(layer_path(target)))
        cel = target:cel(spr.frames[idx])
        if not cel then print("ERROR:No cel on layer '{safe_layer}' at frame {frame_index} (sprite has " .. #spr.frames .. " frame(s), 1-based). Tip: call add_frame first, or draw on this layer/frame.") return end
        local img = cel.image
        local ox = cel.position.x
        local oy = cel.position.y
        """

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index {frame_index} out of range (sprite has " .. #spr.frames .. " frame(s), 1-based). Tip: call add_frame first.") return end
    {reader}

    local iw, ih = img.width, img.height
    for py = {y}, {y + height - 1} do
        for px = {x}, {x + width - 1} do
            local cx = px - ox
            local cy = py - oy
            local r, g, b, a = 0, 0, 0, 0
            if cx >= 0 and cy >= 0 and cx < iw and cy < ih then
                local pv = img:getPixel(cx, cy)
                r = app.pixelColor.rgbaR(pv)
                g = app.pixelColor.rgbaG(pv)
                b = app.pixelColor.rgbaB(pv)
                a = app.pixelColor.rgbaA(pv)
            end
            print(string.format("PIXEL:%d,%d,%d,%d,%d,%d", px, py, r, g, b, a))
        end
    end
    """

    output = await AsepriteCommand.execute_lua_script(script, filename)

    resolved_path = None
    cells: Dict[tuple[int, int], tuple[int, int, int, int]] = {}
    for line in output.splitlines():
        if line.startswith("LAYER_PATH:"):
            resolved_path = json.loads(line.removeprefix("LAYER_PATH:"))
        if line.startswith("ERROR:"):
            raise ToolError(f"Failed to read sprite map: {line[6:]}")
        if line.startswith("PIXEL:"):
            px, py, r, g, b, a = (int(value) for value in line[6:].split(","))
            cells[(px - x, py - y)] = (r, g, b, a)

    if len(cells) != width * height:
        raise ToolError("Failed to read sprite map: incomplete pixel data returned")

    result = encode_sprite_map(cells, frame_index=frame_index, x=x, y=y, width=width, height=height,
                               palette=palette, max_colors=max_colors, alpha_threshold=alpha_threshold,
                               transparent=transparent, source="composite" if composite else "cel",
                               layer=None if composite else resolved_path)
    return ToolOutput(summary="Read exact sprite map", data=result)
