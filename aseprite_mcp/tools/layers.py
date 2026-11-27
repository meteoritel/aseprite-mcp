from mcp.server.mcpserver.exceptions import ToolError

from ..core.commands import lua_escape
from ..core.contracts import LayerRef, PositiveInt, ToolOutput
from ..core.editing import edit_output, execute_edit_script
from ..core.lua import FIND_LAYER, LAYER_NAMES, lua_layer_ref
from ..core.results import EditReceipt
from ..core.state import prepare_filename

_BLEND_MODES = {
    "normal": "BlendMode.NORMAL",
    "darken": "BlendMode.DARKEN",
    "multiply": "BlendMode.MULTIPLY",
    "color_burn": "BlendMode.COLOR_BURN",
    "lighten": "BlendMode.LIGHTEN",
    "screen": "BlendMode.SCREEN",
    "color_dodge": "BlendMode.COLOR_DODGE",
    "addition": "BlendMode.ADDITION",
    "overlay": "BlendMode.OVERLAY",
    "soft_light": "BlendMode.SOFT_LIGHT",
    "hard_light": "BlendMode.HARD_LIGHT",
    "difference": "BlendMode.DIFFERENCE",
    "exclusion": "BlendMode.EXCLUSION",
    "subtract": "BlendMode.SUBTRACT",
    "divide": "BlendMode.DIVIDE",
    "hue": "BlendMode.HSL_HUE",
    "saturation": "BlendMode.HSL_SATURATION",
    "color": "BlendMode.HSL_COLOR",
    "luminosity": "BlendMode.HSL_LUMINOSITY",
}


async def delete_layer(filename: str = "", *, layer_name: LayerRef) -> ToolOutput[EditReceipt]:
    """Delete a layer by name.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: Name of the layer to delete
    """
    filename = prepare_filename(filename)

    safe_layer = lua_escape(layer_name)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local target = find_layer(spr, {lua_layer_ref(layer_name)})
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end
    if #spr.layers <= 1 then print("ERROR:Cannot delete the only layer") return end

    app.transaction(function()
        spr:deleteLayer(target)
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Layer '{layer_name}' deleted from {filename}", filename, execution, None)


async def rename_layer(filename: str = "", *, layer_name: LayerRef, new_name: str) -> ToolOutput[EditReceipt]:
    """Rename a layer.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: Current layer name
        new_name: New layer name
    """
    filename = prepare_filename(filename)
    if not new_name:
        raise ToolError("New name cannot be empty")

    safe_layer = lua_escape(layer_name)
    safe_new = lua_escape(new_name)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local target = find_layer(spr, {lua_layer_ref(layer_name)})
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end

    app.transaction(function()
        target.name = "{safe_new}"
        _aseprite_edit_targets = {{}}
        remember_target(target)
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Layer '{layer_name}' renamed to '{new_name}' in {filename}", filename, execution, None)


async def duplicate_layer(filename: str = "", *, layer_name: LayerRef, new_name: str = "", group: LayerRef = "") -> ToolOutput[EditReceipt]:
    """Duplicate a layer with all its cels across every frame.

    The copy inherits the source's opacity and blend mode. By default it is
    placed directly above the source layer; pass `group` to place it inside a
    group instead. To copy layers across different `.aseprite` projects, use
    `call_tool("copy_layers_between_sprites", ...)` (inspect schema via `search_tools`).

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: Layer to duplicate, by name or "group/subgroup/layer" path
        new_name: Name for the copy (default: "<layer_name> copy")
        group: Optional group to place the copy inside, by name or
            "group/subgroup" path (default: directly above the source)
    """
    filename = prepare_filename(filename)

    final_name = new_name or f"{layer_name[-1] if isinstance(layer_name, list) else layer_name} copy"
    safe_layer = lua_escape(layer_name)
    safe_new = lua_escape(final_name)
    safe_group = lua_escape(group)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local src = find_layer(spr, {lua_layer_ref(layer_name)})
    if not src then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end

    local parent = nil
    if "{safe_group}" ~= "" then
        parent = find_layer(spr, {lua_layer_ref(group)})
        if not parent then print("ERROR:Group '{safe_group}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_group first, or check get_sprite_info for the exact group names.") return end
        if not parent.isGroup then print("ERROR:Target is not a group") return end
    end

    app.transaction(function()
        local copy = spr:newLayer()
        copy.name = "{safe_new}"
        copy.opacity = src.opacity
        copy.blendMode = src.blendMode
        if parent then
            copy.parent = parent
        else
            copy.parent = src.parent
            copy.stackIndex = src.stackIndex + 1
        end
        for _, frame in ipairs(spr.frames) do
            local cel = src:cel(frame)
            if cel then
                local c = spr:newCel(copy, frame, cel.image:clone(), cel.position)
                c.opacity = cel.opacity
            end
        end
        _aseprite_edit_targets = {{}}
        remember_target(copy)
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    location = f" inside group '{group}'" if group else ""
    return edit_output(f"Layer '{layer_name}' duplicated as '{final_name}'{location} in {filename}", filename, execution, None)


async def reorder_layer(filename: str = "", *, layer_name: LayerRef, position: PositiveInt) -> ToolOutput[EditReceipt]:
    """Move a layer to a new position in the layer stack.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: Layer to move
        position: Target stack position, 1-based where 1 is the bottom layer
    """
    filename = prepare_filename(filename)
    if position < 1:
        raise ToolError("Position must be >= 1")

    safe_layer = lua_escape(layer_name)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local target = find_layer(spr, {lua_layer_ref(layer_name)})
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end
    if {position} > #spr.layers then print("ERROR:Position out of range") return end

    app.transaction(function()
        target.stackIndex = {position}
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Layer '{layer_name}' moved to position {position} in {filename}", filename, execution, None)


async def set_layer_blend_mode(filename: str = "", *, layer_name: LayerRef, mode: str) -> ToolOutput[EditReceipt]:
    """Set a layer's blend mode.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: Layer to modify
        mode: One of: normal, darken, multiply, color_burn, lighten, screen,
            color_dodge, addition, overlay, soft_light, hard_light,
            difference, exclusion, subtract, divide, hue, saturation,
            color, luminosity
    """
    filename = prepare_filename(filename)

    blend = _BLEND_MODES.get(mode.lower())
    if blend is None:
        raise ToolError(f"Unknown blend mode '{mode}'. Valid modes: {', '.join(sorted(_BLEND_MODES))}")

    safe_layer = lua_escape(layer_name)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local target = find_layer(spr, {lua_layer_ref(layer_name)})
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end

    app.transaction(function()
        target.blendMode = {blend}
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Layer '{layer_name}' blend mode set to {mode} in {filename}", filename, execution, None)


async def merge_layer_down(filename: str = "", *, layer_name: LayerRef) -> ToolOutput[EditReceipt]:
    """Merge a layer into the layer directly below it.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
        layer_name: Layer to merge down (must not be the bottom layer)
    """
    filename = prepare_filename(filename)

    safe_layer = lua_escape(layer_name)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local target = find_layer(spr, {lua_layer_ref(layer_name)})
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first or check get_sprite_info.") return end
    if target.stackIndex <= 1 then print("ERROR:Layer is the bottom layer; nothing to merge into") return end

    app.activeLayer = target
    app.command.MergeDownLayer()

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Layer '{layer_name}' merged down in {filename}", filename, execution, None)


async def flatten_sprite(filename: str = "") -> ToolOutput[EditReceipt]:
    """Flatten all layers into a single layer.

    Args:
        filename: Aseprite file to modify (optional; defaults to the
            session's active file)
    """
    filename = prepare_filename(filename)

    script = """
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    app.transaction(function()
        spr:flatten()
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)
    return edit_output(f"Sprite flattened in {filename}", filename, execution, None)
