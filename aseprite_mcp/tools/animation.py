from ..core.inspection import read_sprite_info
from mcp.server.mcpserver.exceptions import ToolError
from ..core.lua import CEL_COPIES
from ..core.editing import execute_edit_script
import json
from ..core.commands import lua_escape
from ..core.state import prepare_filename
from ..core.lua import FIND_LAYER, LAYER_NAMES
from .. import mcp

@mcp.tool()
async def add_frames(filename: str = "", *, count: int, duration_ms: int | None = None) -> str:
    """Add multiple frames to a sprite and optionally set their duration.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        count: Number of frames to add
        duration_ms: Optional duration for each new frame in milliseconds
    """
    filename = prepare_filename(filename)

    if count < 1:
        raise ToolError("Count must be >= 1")

    duration_line = ""
    if duration_ms is not None and duration_ms > 0:
        duration_line = f"spr.frames[#spr.frames].duration = {duration_ms} / 1000.0"

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    app.transaction(function()
        for i = 1, {count} do
            spr:newFrame()
            {duration_line}
        end
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Added {count} frames to {filename}"

@mcp.tool()
async def set_frame_duration_all(filename: str = "", *, duration_ms: int) -> str:
    """Set the duration of all frames in milliseconds.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        duration_ms: Duration in milliseconds
    """
    filename = prepare_filename(filename)
    if duration_ms <= 0:
        raise ToolError("Duration must be > 0")

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    app.transaction(function()
        for i = 1, #spr.frames do
            spr.frames[i].duration = {duration_ms} / 1000.0
        end
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Set duration of all frames to {duration_ms}ms in {filename}"

@mcp.tool()
async def set_layer_visibility(filename: str = "", *, layer_name: str, visible: bool = True) -> str:
    """Set layer visibility by name.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer name to target
        visible: Whether the layer should be visible
    """
    filename = prepare_filename(filename)

    safe_layer_name = lua_escape(layer_name)
    visible_flag = "true" if visible else "false"
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, "{safe_layer_name}")
    if not target then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    app.transaction(function()
        target.isVisible = {visible_flag}
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Layer '{layer_name}' visibility set to {visible} in {filename}"

@mcp.tool()
async def set_layer_opacity(filename: str = "", *, layer_name: str, opacity: int) -> str:
    """Set layer opacity by name (0-255).

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer name to target
        opacity: Opacity value 0-255
    """
    filename = prepare_filename(filename)
    if opacity < 0 or opacity > 255:
        raise ToolError("Opacity must be between 0 and 255")

    safe_layer_name = lua_escape(layer_name)
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, "{safe_layer_name}")
    if not target then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    app.transaction(function()
        target.opacity = {opacity}
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Layer '{layer_name}' opacity set to {opacity} in {filename}"

@mcp.tool()
async def get_sprite_info(filename: str = "") -> str:
    """Read canvas, layer tree, frame durations and tag metadata as JSON."""
    filename = prepare_filename(filename)
    return json.dumps(await read_sprite_info(filename), ensure_ascii=False)


@mcp.tool()
async def duplicate_frame_range(filename: str = "", *, start_frame: int, end_frame: int, times: int = 1) -> str:
    """Duplicate a frame range and append copies to the end.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        start_frame: Starting frame index (1-based)
        end_frame: Ending frame index (1-based, inclusive)
        times: Number of times to append the range (default: 1)
    """
    filename = prepare_filename(filename)
    if times < 1:
        raise ToolError("Times must be >= 1")

    script = f"""
    {CEL_COPIES}
    local spr = app.activeSprite
    local first, last = {start_frame}, {end_frame}
    if first < 1 or last > #spr.frames or first > last then print("ERROR:Frame range out of bounds") return end
    local snapshots = {{}}
    for fi = first, last do
        snapshots[#snapshots + 1] = {{cels=snapshot_frame(spr, spr.frames[fi]), duration=spr.frames[fi].duration}}
    end
    app.transaction(function()
        for repetition = 1, {times} do
            for _, snapshot in ipairs(snapshots) do
                local frame = spr:newFrame()
                frame.duration = snapshot.duration
                write_frame(spr, frame, snapshot.cels, true)
            end
        end
    end)
    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Duplicated frames {start_frame}-{end_frame} (x{times}) in {filename}"

@mcp.tool()
async def set_cel_position(filename: str='', *, layer_name: str, frame_index: int, x: int, y: int, create_if_missing: bool=False, source_frame_index: int | None=None) -> str:
    """Set a cel's position in a specific layer and frame.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer name to target
        frame_index: Frame index starting at 1
        x: X position in pixels
        y: Y position in pixels
        create_if_missing: Create the cel if it does not exist
        source_frame_index: Optional frame to copy the cel image from
    """
    filename = prepare_filename(filename)

    safe_layer_name = lua_escape(layer_name)
    source_idx = "nil" if source_frame_index is None else str(source_frame_index)
    create_flag = "true" if create_if_missing else "false"

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local source_index = {source_idx}
    if source_index ~= nil and (source_index < 1 or source_index > #spr.frames) then
        print("ERROR:Source frame index out of range") return
    end
    {FIND_LAYER}
    {LAYER_NAMES}
    local target_layer = find_layer(spr, "{safe_layer_name}")
    if not target_layer then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then
        print("ERROR:Frame index out of range") return
    end

    app.transaction(function()
        local frame = spr.frames[idx]
        local cel = target_layer:cel(frame)
        if not cel and {create_flag} then
            local source_frame = {source_idx}
            if source_frame == nil then
                source_frame = idx
            end
            local source_cel = target_layer:cel(spr.frames[source_frame])
            if source_cel then
                local img = source_cel.image:clone()
                cel = spr:newCel(target_layer, frame, img, source_cel.position)
            else
                local img = Image(spr.width, spr.height, spr.colorMode)
                cel = spr:newCel(target_layer, frame, img, Point(0, 0))
            end
        end
        if not cel then print("ERROR:No cel on the selected layer/frame") return end
        cel.position = Point({x}, {y})
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Cel position set to ({x}, {y}) on '{layer_name}' frame {frame_index} in {filename}"

@mcp.tool()
async def tween_cel_positions(filename: str = "", *, layer_name: str, start_frame: int, end_frame: int, start_x: int, start_y: int, end_x: int, end_y: int, create_missing_cels: bool = False, source_frame_index: int | None = None) -> str:
    """Tween cel positions linearly across a frame range.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer name to target
        start_frame: Starting frame index (1-based)
        end_frame: Ending frame index (1-based, inclusive)
        start_x: Starting X position in pixels
        start_y: Starting Y position in pixels
        end_x: Ending X position in pixels
        end_y: Ending Y position in pixels
        create_missing_cels: Create missing cels during tween
        source_frame_index: Optional frame to copy the cel image from
    """
    filename = prepare_filename(filename)

    safe_layer_name = lua_escape(layer_name)
    create_flag = "true" if create_missing_cels else "false"
    source_idx = "nil" if source_frame_index is None else str(source_frame_index)

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local source_index = {source_idx}
    if source_index ~= nil and (source_index < 1 or source_index > #spr.frames) then
        print("ERROR:Source frame index out of range") return
    end
    {FIND_LAYER}
    {LAYER_NAMES}
    local target_layer = find_layer(spr, "{safe_layer_name}")
    if not target_layer then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    local start_idx = {start_frame}
    local end_idx = {end_frame}
    if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
        print("ERROR:Frame range out of bounds") return
    end

    local span = end_idx - start_idx
    app.transaction(function()
        for fi = start_idx, end_idx do
            local t = 0
            if span > 0 then
                t = (fi - start_idx) / span
            end
            local x = math.floor({start_x} + ({end_x} - {start_x}) * t + 0.5)
            local y = math.floor({start_y} + ({end_y} - {start_y}) * t + 0.5)
            local frame = spr.frames[fi]
            local cel = target_layer:cel(frame)
            if not cel and {create_flag} then
                local source_frame = {source_idx}
                if source_frame == nil then
                    source_frame = start_idx
                end
                local source_cel = target_layer:cel(spr.frames[source_frame])
                if source_cel then
                    local img = source_cel.image:clone()
                    cel = spr:newCel(target_layer, frame, img, source_cel.position)
                else
                    local img = Image(spr.width, spr.height, spr.colorMode)
                    cel = spr:newCel(target_layer, frame, img, Point(0, 0))
                end
            end
            if cel then
                cel.position = Point(x, y)
            end
        end
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Tweened cel positions on '{layer_name}' frames {start_frame}-{end_frame} in {filename}"

@mcp.tool()
async def offset_cel_positions(filename: str = "", *, layer_name: str, start_frame: int, end_frame: int, dx: int, dy: int) -> str:
    """Offset cel positions by a delta across a frame range.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer name to target
        start_frame: Starting frame index (1-based)
        end_frame: Ending frame index (1-based, inclusive)
        dx: X delta in pixels
        dy: Y delta in pixels
    """
    filename = prepare_filename(filename)

    safe_layer_name = lua_escape(layer_name)
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target_layer = find_layer(spr, "{safe_layer_name}")
    if not target_layer then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    local start_idx = {start_frame}
    local end_idx = {end_frame}
    if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
        print("ERROR:Frame range out of bounds") return
    end

    app.transaction(function()
        for fi = start_idx, end_idx do
            local frame = spr.frames[fi]
            local cel = target_layer:cel(frame)
            if cel then
                local pos = cel.position
                cel.position = Point(pos.x + {dx}, pos.y + {dy})
            end
        end
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Offset cel positions by ({dx}, {dy}) on '{layer_name}' frames {start_frame}-{end_frame} in {filename}"

@mcp.tool()
async def create_cel(filename: str='', *, layer_name: str, frame_index: int, x: int=0, y: int=0) -> str:
    """Create an empty cel on a layer/frame.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer name to target
        frame_index: Frame index starting at 1
        x: X position in pixels
        y: Y position in pixels
    """
    filename = prepare_filename(filename)

    safe_layer_name = lua_escape(layer_name)
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, "{safe_layer_name}")
    if not target then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    app.transaction(function()
        local frame = spr.frames[idx]
        local cel = target:cel(frame)
        if cel then return end
        local img = Image(spr.width, spr.height, spr.colorMode)
        spr:newCel(target, frame, img, Point({x}, {y}))
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Cel created on '{layer_name}' frame {frame_index} in {filename}"

@mcp.tool()
async def clear_cel(filename: str='', *, layer_name: str, frame_index: int) -> str:
    """Delete a cel on a layer/frame."""
    filename = prepare_filename(filename)

    safe_layer_name = lua_escape(layer_name)
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, "{safe_layer_name}")
    if not target then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    app.transaction(function()
        local frame = spr.frames[idx]
        local cel = target:cel(frame)
        if cel then
            spr:deleteCel(cel)
        end
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Cel cleared on '{layer_name}' frame {frame_index} in {filename}"

@mcp.tool()
async def copy_cel(filename: str = "", *, layer_name: str, source_frame: int, target_frame: int, replace: bool = True, create_target_frame: bool = True) -> str:
    """Copy a cel snapshot, optionally extending the timeline for its target.

    Args:
        filename: Source project (defaults to the active file)
        layer_name: Explicit layer name or group path
        source_frame: Source frame, 1-based; must contain a cel
        target_frame: Target frame, 1-based
        replace: Replace an existing target cel (default True)
        create_target_frame: Extend the timeline when required (default True)
    """
    filename = prepare_filename(filename)
    name = lua_escape(layer_name)
    script = f"""
    {CEL_COPIES}
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    local src, dst = {source_frame}, {target_frame}
    if src < 1 or src > #spr.frames then print("ERROR:Source frame out of range") return end
    if dst < 1 or (dst > #spr.frames and not {str(create_target_frame).lower()}) then print("ERROR:Target frame out of range. Tip: call add_frame first or enable create_target_frame.") return end
    local layer = find_layer(spr, "{name}")
    if not layer then print("ERROR:Layer '{name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end
    if layer.isGroup then print("ERROR:Select a leaf layer for cel copying") return end
    local snapshot = snapshot_cel(layer:cel(spr.frames[src]))
    if not snapshot then print("ERROR:No source cel on layer '{name}' at frame {source_frame}") return end
    if src == dst then print("PROJECT_UNCHANGED") return end
    local added = math.max(0, dst - #spr.frames)
    app.transaction(function()
        while #spr.frames < dst do spr:newFrame() end
        write_cel(spr, layer, spr.frames[dst], snapshot, {str(replace).lower()})
    end)
    save_project(spr)
    print("OK|frames_added=" .. added)
    """
    output = await execute_edit_script(script, filename)
    added = next((int(line.split("=", 1)[1]) for line in output.splitlines() if line.startswith("OK|frames_added=")), 0)
    note = f" ({added} frame(s) auto-created)" if added else ""
    return f"Cel copied on '{layer_name}' from frame {source_frame} to frame {target_frame}{note} in {filename}"

@mcp.tool()
async def copy_frame(filename: str = "", *, source_frame: int, target_frame: int | None = None, overwrite: bool = True) -> str:
    """Copy all grouped and hidden cels; append when target_frame is omitted.

    Existing target durations and tags are preserved. An appended frame uses
    the source duration. overwrite=false fills only missing target cels.
    """
    filename = prepare_filename(filename)
    destination = "nil" if target_frame is None else str(target_frame)
    script = f"""
    {CEL_COPIES}
    local spr = app.activeSprite
    local src = {source_frame}
    local dst = {destination}
    if src < 1 or src > #spr.frames then print("ERROR:Source frame out of range") return end
    if dst ~= nil and (dst < 1 or dst > #spr.frames) then print("ERROR:Target frame out of range") return end
    if src == dst then print("PROJECT_UNCHANGED") return end
    local snapshot = snapshot_frame(spr, spr.frames[src])
    app.transaction(function()
        local frame
        if dst == nil then
            frame = spr:newFrame()
            frame.duration = spr.frames[src].duration
        else
            frame = spr.frames[dst]
        end
        write_frame(spr, frame, snapshot, {str(overwrite).lower()} or dst == nil)
    end)
    save_project(spr)
    print("OK")
    """
    await execute_edit_script(script, filename)
    return f"Frame {source_frame} copied to {target_frame or 'new frame'} in {filename}"

@mcp.tool()
async def propagate_frame_to_range(filename: str = "", *, source_frame: int, start_frame: int, end_frame: int, overwrite: bool = True) -> str:
    """Copy source cels throughout an inclusive frame range, preserving durations."""
    filename = prepare_filename(filename)
    script = f"""
    {CEL_COPIES}
    local spr = app.activeSprite
    local src, first, last = {source_frame}, {start_frame}, {end_frame}
    if src < 1 or src > #spr.frames then print("ERROR:Source frame out of range") return end
    if first < 1 or last > #spr.frames or first > last then print("ERROR:Frame range out of bounds") return end
    if first == src and last == src then print("PROJECT_UNCHANGED") return end
    local snapshot = snapshot_frame(spr, spr.frames[src])
    app.transaction(function()
        for fi = first, last do
            if fi ~= src then write_frame(spr, spr.frames[fi], snapshot, {str(overwrite).lower()}) end
        end
    end)
    save_project(spr)
    print("OK")
    """
    await execute_edit_script(script, filename)
    return f"Propagated frame {source_frame} to frames {start_frame}-{end_frame} in {filename}"

@mcp.tool()
async def set_tag(filename: str = "", *, name: str, from_frame: int, to_frame: int, direction: str = "forward") -> str:
    """Create or update an animation tag on the sprite.

    direction: forward | reverse | pingpong | pingpong_reverse
    """
    filename = prepare_filename(filename)

    ani_dirs = {
        "forward": "AniDir.FORWARD",
        "reverse": "AniDir.REVERSE",
        "pingpong": "AniDir.PING_PONG",
        "pingpong_reverse": "AniDir.PING_PONG_REVERSE",
    }
    if direction not in ani_dirs:
        raise ToolError(f"Unsupported direction '{direction}' (forward, reverse, pingpong, pingpong_reverse)")

    safe_name = lua_escape(name)
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local start_idx = {from_frame}
    local end_idx = {to_frame}
    if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
        print("ERROR:Frame range out of bounds") return
    end

    local tag = nil
    for _, t in ipairs(spr.tags) do
        if t.name == "{safe_name}" then tag = t break end
    end
    if not tag then
        tag = spr:newTag(start_idx, end_idx)
    else
        tag.fromFrame = spr.frames[start_idx]
        tag.toFrame = spr.frames[end_idx]
    end
    tag.name = "{safe_name}"
    tag.aniDir = {ani_dirs[direction]}

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Tag '{name}' set to frames {from_frame}-{to_frame} (direction={direction}) in {filename}"

@mcp.tool()
async def set_onion_skin(
    filename: str = "",
    enabled: bool = True,
    before: int = 2,
    after: int = 2,
    opacity: int = 128
) -> str:
    """Configure onion skin settings for Aseprite."""
    filename = prepare_filename(filename)
    if before < 0 or after < 0:
        raise ToolError("Before/after must be >= 0")
    if opacity < 0 or opacity > 255:
        raise ToolError("Opacity must be between 0 and 255")

    return (
        "Onion skin settings are UI-only in batch mode; no changes applied "
        f"(enabled={enabled}, before={before}, after={after}, opacity={opacity})"
    )

@mcp.tool()
async def propagate_cels(filename: str = "", *, layer_names: list[str], source_frame: int, start_frame: int, end_frame: int, replace: bool = True) -> str:
    """Copy cels from a source frame to a range of frames for specific layers.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_names: List of layer names to copy
        source_frame: Frame index to copy from (1-based)
        start_frame: Start frame index (1-based)
        end_frame: End frame index (1-based, inclusive)
        replace: Whether to overwrite existing cels (default: True)
    """
    filename = prepare_filename(filename)
    if not layer_names:
        raise ToolError("Layer names list cannot be empty")

    layers_lua = "{" + ",".join(f'"{lua_escape(name)}"' for name in layer_names) + "}"
    script = f"""
    {CEL_COPIES}
    {FIND_LAYER}
    {LAYER_NAMES}
    local spr = app.activeSprite
    local src, first, last = {source_frame}, {start_frame}, {end_frame}
    if src < 1 or src > #spr.frames then print("ERROR:Source frame out of range") return end
    if first < 1 or last > #spr.frames or first > last then print("ERROR:Frame range out of bounds") return end
    local snapshot = {{}}
    for _, name in ipairs({layers_lua}) do
        local layer = find_layer(spr, name)
        if not layer then error("Layer '" .. name .. "' not found. Existing layers: [" .. layer_names(spr) .. "]") end
        if layer.isGroup then error("Select a leaf layer for cel propagation") end
        snapshot[#snapshot + 1] = {{layer=layer, cel=snapshot_cel(layer:cel(spr.frames[src]))}}
    end
    if first == src and last == src then print("PROJECT_UNCHANGED") return end
    app.transaction(function()
        for fi = first, last do
            if fi ~= src then
                for _, entry in ipairs(snapshot) do
                    if entry.cel then write_cel(spr, entry.layer, spr.frames[fi], entry.cel, {str(replace).lower()}) end
                end
            end
        end
    end)
    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return (
        f"Propagated cels from frame {source_frame} to frames {start_frame}-{end_frame} "
        f"for layers {', '.join(layer_names)} in {filename}"
    )

@mcp.tool()
async def tween_cel_positions_eased(filename: str = "", *, layer_name: str, start_frame: int, end_frame: int, start_x: int, start_y: int, end_x: int, end_y: int, easing: str = "smoothstep", create_missing_cels: bool = False, source_frame_index: int | None = None) -> str:
    """Tween cel positions with easing across a frame range."""
    filename = prepare_filename(filename)

    easing = (easing or "smoothstep").lower().strip()
    if easing not in {"linear", "ease_in", "ease_out", "ease_in_out", "smoothstep"}:
        raise ToolError("Unsupported easing (linear, ease_in, ease_out, ease_in_out, smoothstep)")

    safe_layer_name = lua_escape(layer_name)
    create_flag = "true" if create_missing_cels else "false"
    source_idx = "nil" if source_frame_index is None else str(source_frame_index)

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target_layer = find_layer(spr, "{safe_layer_name}")
    if not target_layer then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    local start_idx = {start_frame}
    local end_idx = {end_frame}
    if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
        print("ERROR:Frame range out of bounds") return
    end

    local function ease(t)
        local mode = "{easing}"
        if mode == "linear" then return t end
        if mode == "ease_in" then return t * t end
        if mode == "ease_out" then return 1 - (1 - t) * (1 - t) end
        if mode == "ease_in_out" then
            if t < 0.5 then return 2 * t * t end
            local u = -2 * t + 2
            return 1 - (u * u) / 2
        end
        return t * t * (3 - 2 * t)
    end

    local span = end_idx - start_idx
    app.transaction(function()
        for fi = start_idx, end_idx do
            local t = 0
            if span > 0 then
                t = (fi - start_idx) / span
            end
            local e = ease(t)
            local x = math.floor({start_x} + ({end_x} - {start_x}) * e + 0.5)
            local y = math.floor({start_y} + ({end_y} - {start_y}) * e + 0.5)
            local frame = spr.frames[fi]
            local cel = target_layer:cel(frame)
            if not cel and {create_flag} then
                local source_frame = {source_idx}
                if source_frame == nil then
                    source_frame = start_idx
                end
                local source_cel = target_layer:cel(spr.frames[source_frame])
                if source_cel then
                    local img = source_cel.image:clone()
                    cel = spr:newCel(target_layer, frame, img, source_cel.position)
                else
                    local img = Image(spr.width, spr.height, spr.colorMode)
                    cel = spr:newCel(target_layer, frame, img, Point(0, 0))
                end
            end
            if cel then
                cel.position = Point(x, y)
            end
        end
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return (
        f"Tweened cel positions ({easing}) on '{layer_name}' frames {start_frame}-{end_frame} "
        f"in {filename}"
    )

@mcp.tool()
async def oscillate_cel_positions(filename: str = "", *, layer_name: str, start_frame: int, end_frame: int, amplitude_x: int = 0, amplitude_y: int = 0, cycles: float = 1.0, phase_deg: float = 0.0, create_missing_cels: bool = False, source_frame_index: int | None = None) -> str:
    """Oscillate cel positions across a frame range using a sine wave."""
    filename = prepare_filename(filename)

    safe_layer_name = lua_escape(layer_name)
    create_flag = "true" if create_missing_cels else "false"
    source_idx = "nil" if source_frame_index is None else str(source_frame_index)

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target_layer = find_layer(spr, "{safe_layer_name}")
    if not target_layer then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    local start_idx = {start_frame}
    local end_idx = {end_frame}
    if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
        print("ERROR:Frame range out of bounds") return
    end

    local amplitude_x = {amplitude_x}
    local amplitude_y = {amplitude_y}
    local cycles = {cycles}
    local phase = ({phase_deg}) * math.pi / 180
    local span = end_idx - start_idx

    app.transaction(function()
        for fi = start_idx, end_idx do
            local t = 0
            if span > 0 then
                t = (fi - start_idx) / span
            end
            local angle = 2 * math.pi * cycles * t + phase
            local dx = math.floor(amplitude_x * math.sin(angle) + 0.5)
            local dy = math.floor(amplitude_y * math.cos(angle) + 0.5)

            local frame = spr.frames[fi]
            local cel = target_layer:cel(frame)
            if not cel and {create_flag} then
                local source_frame = {source_idx}
                if source_frame == nil then
                    source_frame = start_idx
                end
                local source_cel = target_layer:cel(spr.frames[source_frame])
                if source_cel then
                    local img = source_cel.image:clone()
                    cel = spr:newCel(target_layer, frame, img, source_cel.position)
                else
                    local img = Image(spr.width, spr.height, spr.colorMode)
                    cel = spr:newCel(target_layer, frame, img, Point(0, 0))
                end
            end
            if cel then
                local pos = cel.position
                cel.position = Point(pos.x + dx, pos.y + dy)
            end
        end
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return (
        f"Oscillated cel positions on '{layer_name}' frames {start_frame}-{end_frame} "
        f"in {filename}"
    )

@mcp.tool()
async def tween_cel_opacity_eased(filename: str = "", *, layer_name: str, start_frame: int, end_frame: int, start_opacity: int, end_opacity: int, easing: str = "smoothstep", create_missing_cels: bool = False, source_frame_index: int | None = None) -> str:
    """Tween cel opacity with easing across a frame range."""
    filename = prepare_filename(filename)
    if start_opacity < 0 or start_opacity > 255 or end_opacity < 0 or end_opacity > 255:
        raise ToolError("Opacity must be between 0 and 255")

    easing = (easing or "smoothstep").lower().strip()
    if easing not in {"linear", "ease_in", "ease_out", "ease_in_out", "smoothstep"}:
        raise ToolError("Unsupported easing (linear, ease_in, ease_out, ease_in_out, smoothstep)")

    safe_layer_name = lua_escape(layer_name)
    create_flag = "true" if create_missing_cels else "false"
    source_idx = "nil" if source_frame_index is None else str(source_frame_index)

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target_layer = find_layer(spr, "{safe_layer_name}")
    if not target_layer then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    local start_idx = {start_frame}
    local end_idx = {end_frame}
    if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
        print("ERROR:Frame range out of bounds") return
    end

    local function ease(t)
        local mode = "{easing}"
        if mode == "linear" then return t end
        if mode == "ease_in" then return t * t end
        if mode == "ease_out" then return 1 - (1 - t) * (1 - t) end
        if mode == "ease_in_out" then
            if t < 0.5 then return 2 * t * t end
            local u = -2 * t + 2
            return 1 - (u * u) / 2
        end
        return t * t * (3 - 2 * t)
    end

    local span = end_idx - start_idx
    app.transaction(function()
        for fi = start_idx, end_idx do
            local t = 0
            if span > 0 then
                t = (fi - start_idx) / span
            end
            local e = ease(t)
            local op = math.floor({start_opacity} + ({end_opacity} - {start_opacity}) * e + 0.5)
            if op < 0 then op = 0 end
            if op > 255 then op = 255 end
            local frame = spr.frames[fi]
            local cel = target_layer:cel(frame)
            if not cel and {create_flag} then
                local source_frame = {source_idx}
                if source_frame == nil then
                    source_frame = start_idx
                end
                local source_cel = target_layer:cel(spr.frames[source_frame])
                if source_cel then
                    local img = source_cel.image:clone()
                    cel = spr:newCel(target_layer, frame, img, source_cel.position)
                else
                    local img = Image(spr.width, spr.height, spr.colorMode)
                    cel = spr:newCel(target_layer, frame, img, Point(0, 0))
                end
            end
            if cel then
                cel.opacity = op
            end
        end
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return (
        f"Tweened cel opacity ({easing}) on '{layer_name}' frames {start_frame}-{end_frame} "
        f"in {filename}"
    )

@mcp.tool()
async def tween_cel_scale_eased(filename: str = "", *, layer_name: str, start_frame: int, end_frame: int, start_scale: float, end_scale: float, easing: str = "smoothstep", anchor: str = "center", replace: bool = True, create_missing_cels: bool = True, source_frame_index: int | None = None) -> str:
    """Tween cel scale with easing across a frame range."""
    filename = prepare_filename(filename)
    if start_scale <= 0 or end_scale <= 0:
        raise ToolError("Scale must be > 0")

    easing = (easing or "smoothstep").lower().strip()
    if easing not in {"linear", "ease_in", "ease_out", "ease_in_out", "smoothstep"}:
        raise ToolError("Unsupported easing (linear, ease_in, ease_out, ease_in_out, smoothstep)")

    anchor = (anchor or "center").lower().strip()
    if anchor not in {"center", "topleft"}:
        raise ToolError("Unsupported anchor (center, topleft)")

    safe_layer_name = lua_escape(layer_name)
    create_flag = "true" if create_missing_cels else "false"
    replace_flag = "true" if replace else "false"
    source_idx = "nil" if source_frame_index is None else str(source_frame_index)

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target_layer = find_layer(spr, "{safe_layer_name}")
    if not target_layer then print("ERROR:Layer '{safe_layer_name}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    local start_idx = {start_frame}
    local end_idx = {end_frame}
    if start_idx < 1 or end_idx > #spr.frames or start_idx > end_idx then
        print("ERROR:Frame range out of bounds") return
    end

    local source_frame = {source_idx}
    if source_frame == nil then
        source_frame = start_idx
    end
    if source_frame < 1 or source_frame > #spr.frames then
        print("ERROR:Source frame out of range") return
    end

    local source_cel = target_layer:cel(spr.frames[source_frame])
    if not source_cel then
        print("ERROR:Source cel not found") return
    end

    local base_img = source_cel.image:clone()
    local base_w = base_img.width
    local base_h = base_img.height
    local base_pos = source_cel.position

    local function ease(t)
        local mode = "{easing}"
        if mode == "linear" then return t end
        if mode == "ease_in" then return t * t end
        if mode == "ease_out" then return 1 - (1 - t) * (1 - t) end
        if mode == "ease_in_out" then
            if t < 0.5 then return 2 * t * t end
            local u = -2 * t + 2
            return 1 - (u * u) / 2
        end
        return t * t * (3 - 2 * t)
    end

    local span = end_idx - start_idx
    app.transaction(function()
        for fi = start_idx, end_idx do
            local t = 0
            if span > 0 then
                t = (fi - start_idx) / span
            end
            local e = ease(t)
            local scale = {start_scale} + ({end_scale} - {start_scale}) * e
            local new_w = math.max(1, math.floor(base_w * scale + 0.5))
            local new_h = math.max(1, math.floor(base_h * scale + 0.5))

            local dst_frame = spr.frames[fi]
            local dst_cel = target_layer:cel(dst_frame)
            if dst_cel and {replace_flag} then
                spr:deleteCel(dst_cel)
                dst_cel = nil
            end
            if not dst_cel and {create_flag} then
                local img = base_img:clone()
                img:resize(new_w, new_h)
                local pos_x = base_pos.x
                local pos_y = base_pos.y
                if "{anchor}" == "center" then
                    local cx = base_pos.x + base_w / 2
                    local cy = base_pos.y + base_h / 2
                    pos_x = math.floor(cx - new_w / 2 + 0.5)
                    pos_y = math.floor(cy - new_h / 2 + 0.5)
                end
                dst_cel = spr:newCel(target_layer, dst_frame, img, Point(pos_x, pos_y))
            end
        end
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return (
        f"Tweened cel scale ({easing}) on '{layer_name}' frames {start_frame}-{end_frame} "
        f"in {filename}"
    )


@mcp.tool()
async def delete_frame(filename: str = "", *, frame_index: int) -> str:
    """Delete a frame by index.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        frame_index: Frame index starting at 1
    """
    filename = prepare_filename(filename)

    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end
    if #spr.frames <= 1 then print("ERROR:Cannot delete the only frame") return end

    app.transaction(function()
        spr:deleteFrame(spr.frames[idx])
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Frame {frame_index} deleted from {filename}"


@mcp.tool()
async def delete_tag(filename: str = "", *, name: str) -> str:
    """Delete an animation tag by name.

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        name: Tag name to delete
    """
    filename = prepare_filename(filename)

    safe_name = lua_escape(name)
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local target = nil
    for _, tag in ipairs(spr.tags) do
        if tag.name == "{safe_name}" then target = tag break end
    end
    if not target then print("ERROR:Tag not found") return end

    app.transaction(function()
        spr:deleteTag(target)
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Tag '{name}' deleted from {filename}"


@mcp.tool()
async def set_cel_opacity(filename: str='', *, layer_name: str, frame_index: int, opacity: int) -> str:
    """Set the opacity of a single cel (0-255).

    Args:
        filename: Aseprite file to modify (optional; defaults to the session's active file)
        layer_name: Layer containing the cel
        frame_index: Frame index starting at 1
        opacity: Opacity 0 (transparent) to 255 (opaque)
    """
    filename = prepare_filename(filename)
    if not (0 <= opacity <= 255):
        raise ToolError("Opacity must be between 0 and 255")

    safe_layer = lua_escape(layer_name)
    script = f"""
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end

    local idx = {frame_index}
    if idx < 1 or idx > #spr.frames then print("ERROR:Frame index out of range") return end

    {FIND_LAYER}
    {LAYER_NAMES}
    local target = find_layer(spr, "{safe_layer}")
    if not target then print("ERROR:Layer '{safe_layer}' not found. Existing layers: [" .. layer_names(spr) .. "]. Tip: call add_layer first.") return end

    local cel = target:cel(spr.frames[idx])
    if not cel then print("ERROR:No cel at that layer/frame") return end

    app.transaction(function()
        cel.opacity = {opacity}
    end)

    save_project(spr)
    print("OK")
    """

    await execute_edit_script(script, filename)
    return f"Cel opacity set to {opacity} on '{layer_name}' frame {frame_index} in {filename}"
