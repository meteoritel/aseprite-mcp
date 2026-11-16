import os

from mcp.server.mcpserver.exceptions import ToolError

from ..core.commands import lua_escape
from ..core.contracts import FrameIndex, LayerRef, PositiveInt, ToolOutput
from ..core.editing import edit_output, execute_edit_script, native_project_path
from ..core.lua import FIND_LAYER, LAYER_NAMES, lua_layer_ref
from ..core.results import EditReceipt
from ..core.state import prepare_filename, set_active_file

async def create_canvas(width: PositiveInt, height: PositiveInt, *, filename: str, overwrite: bool = False) -> ToolOutput[EditReceipt]:
    """Create a new Aseprite canvas with specified dimensions.

    Args:
        width: Width of the canvas in pixels
        height: Height of the canvas in pixels
        filename: REQUIRED. Absolute path for the output file, e.g.
            "D:/art/sprites/coin.aseprite". Relative paths are rejected, so
            the canvas can never silently land in the server's own folder.
        overwrite: Replace an existing native project (default False)
    """
    if width <= 0 or height <= 0:
        raise ToolError("Width and height must be > 0")
    # Hard requirement: an absolute path. A relative path would resolve
    # against the server's workspace (its own folder), silently dropping
    # the canvas somewhere the caller never intended.
    if not os.path.isabs(filename):
        raise ToolError(
            "create_canvas requires an ABSOLUTE filename, e.g. "
            f"'D:/art/sprites/coin.aseprite'. Got: '{filename}'"
        )
    # anchor=False: only anchor after the canvas actually exists on disk,
    # so a failed create does not point the active file at a missing file.
    filename = prepare_filename(filename, must_exist=False, anchor=False)
    filename = native_project_path(filename)
    if os.path.exists(filename) and not overwrite:
        raise ToolError(f"Project already exists: {filename}; pass overwrite=true to replace it")
    script = f"""
    local spr = Sprite({width}, {height})
    save_project(spr)
    print("OK")
    """

    execution = await execute_edit_script(script, output_filename=filename)

    set_active_file(filename)
    return edit_output(f"Canvas created and anchored as active file: {filename}. Subsequent tool calls may omit filename.", filename, execution, None)

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
