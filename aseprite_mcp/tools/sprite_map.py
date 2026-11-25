"""Compact character-grid editing and readback."""

import json
from pathlib import Path
from typing import Annotated, List

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from ..core.commands import AsepriteCommand, lua_escape
from ..core.composite import COMPOSE_FRAME
from ..core.contracts import BatchSpriteMapEdit, Byte, Character, FrameIndex, LayerRef, NonnegativeInt, Palette, PositiveInt, Region, SpriteLayerRule, SpriteMapEdit, ToolOutput
from ..core.editing import edit_output, execute_edit_script, new_canvas_lua, new_project_path
from ..core.lua import EDIT_TARGET, NORMALIZE_CEL, lua_layer_ref
from ..core.region_read import EMIT_REGION_PIXELS, FIND_REGION_CEL, lua_region, read_region_pixels
from ..core.results import EditReceipt, SpriteMap
from ..core.sprite_grid import compile_layered_sprite, compile_sprite_map, encode_sprite_map, parse_sprite_map
from ..core.state import prepare_filename, set_active_file

async def draw_sprite_maps(
    *,
    filename: str = "",
    maps: Annotated[list[BatchSpriteMapEdit], Field(min_length=1)],
    palette: Palette | None = None,
) -> ToolOutput[EditReceipt]:
    """Draw ordered maps across layers/frames with one all-or-nothing project commit.

    Args:
        filename: Project, defaulting to the active file.
        maps: Ordered grid edits. All frames must exist. New top-level layers follow first occurrence order.
        palette: Shared character palette for this call. An explicit map palette replaces it for that map.
    """
    filename = prepare_filename(filename)
    if not maps:
        raise ToolError("maps must contain at least one map")
    compiled = []
    for index, item in enumerate(maps):
        if not isinstance(item, (BatchSpriteMapEdit, SpriteMapEdit)):
            try:
                item = BatchSpriteMapEdit.model_validate(item)
            except ValidationError as exc:
                raise ToolError(f"maps[{index}]: {exc}") from exc
        effective_palette = item.palette if item.palette is not None else palette
        if effective_palette is None:
            raise ToolError(f"maps[{index}].palette is required without a shared palette")
        try:
            _, _, pixels = compile_sprite_map(item.rows, effective_palette, item.transparent,
                                              item.mirror_x, item.mirror_y, item.erase_transparent)
        except ToolError as exc:
            layer_name = json.dumps(item.layer_name, ensure_ascii=False)
            raise ToolError(f"maps[{index}] (layer_name={layer_name}): {exc}") from exc
        compiled.append(dict(layer=item.layer_name, frame=item.frame_index, create=item.create_if_missing,
                             pixels=[[item.x+x, item.y+y, *rgba] for (x,y),rgba in sorted(pixels.items())]))
    script = _sprite_map_writer_lua(compiled) + '''
    local spr = app.activeSprite
    if apply_sprite_maps(spr, edits) then save_project(spr) else print("PROJECT_UNCHANGED") end
    '''
    execution = await execute_edit_script(script, filename)
    return edit_output("Sprite maps applied in order", filename, execution)


def _sprite_map_writer_lua(compiled: list[dict]) -> str:
    edits = lua_escape(json.dumps(compiled, ensure_ascii=False))
    return EDIT_TARGET + NORMALIZE_CEL + f'\nlocal edits = json.decode("{edits}")\n' + r'''
local function apply_sprite_maps(spr, edits)
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
    return changed
end
    '''


async def create_layered_sprite(
    *,
    filename: str,
    rows: Annotated[list[str], Field(min_length=1)],
    palette: Palette,
    layers: Annotated[list[SpriteLayerRule], Field(min_length=1)],
    transparent: Character = ".",
) -> ToolOutput[EditReceipt]:
    """Create one RGB frame with editable layers expanded from a composite grid.

    Args:
        filename: Absolute path to a new .aseprite or .ase project. An omitted extension becomes .aseprite.
        rows: Equal-width composite rows, top to bottom. The rows set the canvas size.
        palette: Character-to-hex palette for composite and layer colors. Mapped colors must be opaque.
        layers: Rules listed bottom to top, each with a unique name and character mapping. A symbol may paint on several layers; its topmost mapped color must match the composite.
        transparent: Grid character to leave clear on all layers.
    """
    filename = new_project_path(filename)
    target = Path(filename)
    if target.exists() or target.is_symlink():
        raise ToolError(f"Project already exists: {filename}; choose a new project filename")
    rules = [layer if isinstance(layer, SpriteLayerRule) else SpriteLayerRule.model_validate(layer) for layer in layers]
    width, height, pixels_by_layer = compile_layered_sprite(rows, palette, rules, transparent)
    creation = new_canvas_lua(width, height, [rule.name for rule in rules])
    compiled = [
        dict(layer=[rule.name], frame=1, create=True, pixels=pixels)
        for rule, pixels in zip(rules, pixels_by_layer)
    ]
    script = _sprite_map_writer_lua(compiled) + creation + '''
    apply_sprite_maps(spr, edits)
    _aseprite_edit_targets = {}
    for _, layer in ipairs(spr.layers) do remember_target(layer) end
    save_project(spr)
    '''
    execution = await execute_edit_script(script, output_filename=filename)
    set_active_file(filename)
    return edit_output("Layered sprite created", filename, execution, frame=1)


async def draw_sprite_map(*, filename: str='', layer_name: LayerRef, frame_index: FrameIndex, rows: List[str], palette: Palette, x: int=0, y: int=0, transparent: Character='.', mirror_x: bool=False, mirror_y: bool=False, erase_transparent: bool=False, create_if_missing: bool=True) -> ToolOutput[EditReceipt]:
    """Draw a whole region from a compact character-grid map.

    Use an RGB project. For a reviewed cel, pass a copy of cel.edit from
    review_frame and the project filename. The edit grid erases transparent
    cells inside its rectangle and leaves pixels outside it intact.

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

    RGB cel reads preserve RGBA with the default settings. The result is
    lossy when a color limit or alpha threshold changes pixels. Use a smaller
    region if exact colors exceed the available character slots.

    Reuse rows, palette, transparent and the origin for draw_sprite_map.
    Set erase_transparent=true to round-trip removed pixels. To compare
    successive grids, pass the previous palette to keep character assignments.

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

    region = Region(x=x, y=y, width=width, height=height)
    if composite:
        prelude = COMPOSE_FRAME
        reader = f"""
        emit_region_pixels(compose_frame(spr, idx, nil), Point(0, 0), {lua_region(region)})
        """
    else:
        prelude = FIND_REGION_CEL
        reader = f"""
        local path, cel = find_region_cel(spr, {lua_layer_ref(layer_name)}, spr.frames[idx])
        if not cel then
            error("No cel on layer " .. json.encode(path) .. " at frame " .. idx
                .. ". Tip: draw on this layer/frame.")
        end
        print("LAYER_PATH:" .. json.encode(path))
        emit_region_pixels(cel.image, cel.position, {lua_region(region)})
        """

    script = prelude + EMIT_REGION_PIXELS + f"""
    local spr = app.activeSprite
    if not spr then error("No active sprite") end
    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then
        error("Frame index " .. idx .. " out of range (sprite has " .. #spr.frames .. " frames, 1-based). Tip: call add_frame first.")
    end
    {reader}
    """

    output = await AsepriteCommand.execute_lua_script_checked(script, filename)
    resolved_path = None
    if not composite:
        resolved_path = next(json.loads(line.removeprefix("LAYER_PATH:"))
                             for line in output.splitlines() if line.startswith("LAYER_PATH:"))
    cells = read_region_pixels(output, region)
    result = encode_sprite_map(cells, frame_index=frame_index, x=x, y=y, width=width, height=height,
                               palette=palette, max_colors=max_colors, alpha_threshold=alpha_threshold,
                               transparent=transparent, source="composite" if composite else "cel",
                               layer=None if composite else resolved_path)
    return ToolOutput(summary="Read exact sprite map", data=result)
