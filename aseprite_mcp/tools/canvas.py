import os
from typing import Annotated

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..core.commands import lua_escape
from ..core.contracts import FrameIndex, HexColor, LayerRef, PositiveInt, ToolOutput
from ..core.editing import edit_output, execute_edit_script, new_canvas_lua, new_project_path, parse_palette_colors, set_palette_lua
from ..core.lua import FIND_LAYER, LAYER_NAMES, lua_layer_ref
from ..core.results import EditReceipt
from ..core.state import prepare_filename, set_active_file

async def create_canvas(
    width: PositiveInt,
    height: PositiveInt,
    *,
    filename: str,
    overwrite: bool = False,
    initial_layers: Annotated[list[str], Field(min_length=1)] | None = None,
    palette: Annotated[list[HexColor], Field(min_length=1)] | None = None,
) -> ToolOutput[EditReceipt]:
    """Create a new Aseprite canvas with specified dimensions.

    Pass `initial_layers` and `palette` to build a multi-layer project with its
    stored palette in one Aseprite invocation (skipping separate add_layer and
    set_palette calls). To split a single composite ASCII grid into editable
    layers in one step, use `call_tool("create_layered_sprite", ...)`.

    Args:
        width: Width of the canvas in pixels
        height: Height of the canvas in pixels
        filename: Project path ending in .aseprite or .ase (absolute, or relative when ASEPRITE_MCP_WORKSPACE is configured).
            An omitted extension becomes .aseprite. The saved project becomes the active file.
        overwrite: Replace an existing native project (default False)
        initial_layers: Unique top-level layer names, listed bottom to top. Omit to use Aseprite's default layer.
        palette: Optional ordered list of hex colors (#RGB, #RGBA, #RRGGBB or #RRGGBBAA) stored as the project palette.
    """
    if width <= 0 or height <= 0:
        raise ToolError("Width and height must be > 0")
    filename = new_project_path(filename)
    if os.path.exists(filename) and not overwrite:
        raise ToolError(f"Project already exists: {filename}; pass overwrite=true to replace it")
    palette_lua = ""
    if palette is not None:
        if not palette:
            raise ToolError("palette must contain at least one color")
        palette_lua = set_palette_lua(parse_palette_colors(palette))
    script = new_canvas_lua(width, height, initial_layers) + palette_lua + "\nsave_project(spr)\n"

    execution = await execute_edit_script(script, output_filename=filename)

    set_active_file(filename)
    return edit_output(
        f"Canvas created: {filename} (anchored as active file for single-file calls; pass explicit filename for parallel multi-file workflows).",
        filename,
        execution,
        None,
    )

async def add_layer(filename: str = "", *, layer_name: str, group: LayerRef = "") -> ToolOutput[EditReceipt]:
    """Add a new layer to the Aseprite file.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Name of the new layer
        group: Optional group to place the new layer inside, by name or
            "group/subgroup" path (default: top level)
    """
    filename = prepare_filename(filename)

    safe_layer_name = lua_escape(layer_name)
    safe_group = lua_escape(group)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local parent = nil
    if "{safe_group}" ~= "" then
        parent = find_layer(spr, {lua_layer_ref(group)})
        if not parent then print("ERROR:Group '{safe_group}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_group first, or check get_sprite_info for the exact group names.") return end
        if not parent.isGroup then print("ERROR:Target is not a group") return end
    end

    app.transaction(function()
        local lyr = spr:newLayer()
        lyr.name = "{safe_layer_name}"
        if parent then lyr.parent = parent end
        _aseprite_edit_targets = {{}}
        remember_target(lyr)
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)

    location = f" inside group '{group}'" if group else ""
    return edit_output(f"Layer '{layer_name}' added{location} to {filename}", filename, execution, None)

async def add_group(filename: str = "", *, group_name: str, parent_group: LayerRef = "") -> ToolOutput[EditReceipt]:
    """Add a new, empty group layer.

    Combine with add_layer(group=...) / duplicate_layer(group=...) to build a
    grouped layer structure.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        group_name: Name of the new group
        parent_group: Optional existing group to nest the new group inside, by
            name or "group/subgroup" path (default: top level)
    """
    filename = prepare_filename(filename)

    safe_group = lua_escape(group_name)
    safe_parent = lua_escape(parent_group)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local parent = nil
    if "{safe_parent}" ~= "" then
        parent = find_layer(spr, {lua_layer_ref(parent_group)})
        if not parent then print("ERROR:Group '{safe_parent}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_group first, or check get_sprite_info for the exact group names.") return end
        if not parent.isGroup then print("ERROR:Target is not a group") return end
    end

    app.transaction(function()
        local grp = spr:newGroup()
        grp.name = "{safe_group}"
        if parent then grp.parent = parent end
        _aseprite_edit_targets = {{}}
        remember_target(grp)
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)

    location = f" inside '{parent_group}'" if parent_group else ""
    return edit_output(f"Group '{group_name}' created{location} in {filename}", filename, execution, None)

async def add_frame(filename: str = "") -> ToolOutput[EditReceipt]:
    """Add a new frame to the Aseprite file.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
    """
    filename = prepare_filename(filename)
    
    script = """
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    app.transaction(function()
        spr:newFrame()
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)

    return edit_output(f"New frame added successfully to {filename}", filename, execution, None)


async def set_frame_duration(filename: str = "", *, frame_index: FrameIndex, duration_ms: PositiveInt) -> ToolOutput[EditReceipt]:
    """Set the duration of a frame in milliseconds.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        frame_index: Frame index starting at 1
        duration_ms: Duration in milliseconds
    """
    filename = prepare_filename(filename)
    if duration_ms <= 0:
        raise ToolError("Duration must be > 0")

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then
        print("ERROR:Frame index out of range") return
    end

    app.transaction(function()
        spr.frames[idx].duration = {duration_ms} / 1000.0
    end)

    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, filename)

    return edit_output(f"Frame {frame_index} duration set to {duration_ms}ms in {filename}", filename, execution, frame_index)
