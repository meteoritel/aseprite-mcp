import os

from ..core.commands import AsepriteCommand, lua_escape
from ..core.state import prepare_filename, set_active_file
from ..core.lua import FIND_LAYER, LAYER_NAMES
from .. import mcp

@mcp.tool()
async def create_canvas(width: int, height: int, *, filename: str) -> str:
    """Create a new Aseprite canvas with specified dimensions.

    Args:
        width: Width of the canvas in pixels
        height: Height of the canvas in pixels
        filename: REQUIRED. Absolute path for the output file, e.g.
            "D:/art/sprites/coin.aseprite". Relative paths are rejected, so
            the canvas can never silently land in the server's own folder.
    """
    if width <= 0 or height <= 0:
        return "Width and height must be > 0"
    # Hard requirement: an absolute path. A relative path would resolve
    # against the server's workspace (its own folder), silently dropping
    # the canvas somewhere the caller never intended.
    if not os.path.isabs(filename):
        return (
            "create_canvas requires an ABSOLUTE filename, e.g. "
            f"'D:/art/sprites/coin.aseprite'. Got: '{filename}'"
        )
    # anchor=False: only anchor after the canvas actually exists on disk,
    # so a failed create does not point the active file at a missing file.
    filename, err = prepare_filename(filename, must_exist=False, anchor=False)
    if err:
        return err

    safe_path = lua_escape(filename.replace("\\", "/"))
    script = f"""
    local spr = Sprite({width}, {height})
    spr:saveAs("{safe_path}")
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script)

    if success:
        set_active_file(filename)
        return f"Canvas created and anchored as active file: {filename}. Subsequent tool calls may omit filename."
    else:
        return f"Failed to create canvas: {output}"

@mcp.tool()
async def add_layer(filename: str = "", *, layer_name: str, group: str = "") -> str:
    """Add a new layer to the Aseprite file.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Name of the new layer
        group: Optional group to place the new layer inside, by name or
            "group/subgroup" path (default: top level)
    """
    filename, err = prepare_filename(filename)
    if err:
        return err

    safe_layer_name = lua_escape(layer_name)
    safe_group = lua_escape(group)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local parent = nil
    if "{safe_group}" ~= "" then
        parent = find_layer(spr, "{safe_group}")
        if not parent then print("ERROR:Group '{safe_group}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_group first, or check get_sprite_info for the exact group names.") return end
        if not parent.isGroup then print("ERROR:Target is not a group") return end
    end

    app.transaction(function()
        local lyr = spr:newLayer()
        lyr.name = "{safe_layer_name}"
        if parent then lyr.parent = parent end
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)

    if success:
        location = f" inside group '{group}'" if group else ""
        return f"Layer '{layer_name}' added{location} to {filename}"
    else:
        return f"Failed to add layer: {output}"

@mcp.tool()
async def add_group(filename: str = "", *, group_name: str, parent_group: str = "") -> str:
    """Add a new, empty group layer.

    Combine with add_layer(group=...) / duplicate_layer(group=...) to build a
    grouped layer structure.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        group_name: Name of the new group
        parent_group: Optional existing group to nest the new group inside, by
            name or "group/subgroup" path (default: top level)
    """
    filename, err = prepare_filename(filename)
    if err:
        return err

    safe_group = lua_escape(group_name)
    safe_parent = lua_escape(parent_group)
    script = f"""
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local parent = nil
    if "{safe_parent}" ~= "" then
        parent = find_layer(spr, "{safe_parent}")
        if not parent then print("ERROR:Group '{safe_parent}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_group first, or check get_sprite_info for the exact group names.") return end
        if not parent.isGroup then print("ERROR:Target is not a group") return end
    end

    app.transaction(function()
        local grp = spr:newGroup()
        grp.name = "{safe_group}"
        if parent then grp.parent = parent end
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)

    if success:
        location = f" inside '{parent_group}'" if parent_group else ""
        return f"Group '{group_name}' created{location} in {filename}"
    return f"Failed to create group: {output}"

@mcp.tool()
async def add_frame(filename: str = "") -> str:
    """Add a new frame to the Aseprite file.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
    """
    filename, err = prepare_filename(filename)
    if err:
        return err
    
    script = """
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    app.transaction(function()
        spr:newFrame()
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)

    if success:
        return f"New frame added successfully to {filename}"
    else:
        return f"Failed to add frame: {output}"

@mcp.tool()
async def set_frame(filename: str = "", *, frame_index: int) -> str:
    """Set the active frame by index (1-based).

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        frame_index: Frame index starting at 1
    """
    filename, err = prepare_filename(filename)
    if err:
        return err

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then
        print("ERROR:Frame index out of range") return
    end

    app.transaction(function()
        app.activeFrame = spr.frames[idx]
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)

    if success:
        return f"Active frame set to {frame_index} in {filename}"
    else:
        return f"Failed to set frame: {output}"

@mcp.tool()
async def set_frame_duration(filename: str = "", *, frame_index: int, duration_ms: int) -> str:
    """Set the duration of a frame in milliseconds.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        frame_index: Frame index starting at 1
        duration_ms: Duration in milliseconds
    """
    filename, err = prepare_filename(filename)
    if err:
        return err
    if duration_ms <= 0:
        return "Duration must be > 0"

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

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)

    if success:
        return f"Frame {frame_index} duration set to {duration_ms}ms in {filename}"
    else:
        return f"Failed to set frame duration: {output}"

@mcp.tool()
async def set_layer(filename: str = "", *, layer_name: str, create_if_missing: bool = False) -> str:
    """Set the active layer by name.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer name to activate
        create_if_missing: Create layer if it does not exist
    """
    filename, err = prepare_filename(filename)
    if err:
        return err

    create_flag = "true" if create_if_missing else "false"
    safe_layer_name = lua_escape(layer_name)

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, "{safe_layer_name}")

    app.transaction(function()
        if not target then
            if {create_flag} then
                target = spr:newLayer()
                target.name = "{safe_layer_name}"
            else
                return
            end
        end
        app.activeLayer = target
    end)

    spr:saveAs(spr.filename)
    print("OK")
    """

    success, output = AsepriteCommand.execute_lua_script_checked(script, filename)

    if success:
        return f"Active layer set to '{layer_name}' in {filename}"
    else:
        return f"Failed to set layer: {output}"
