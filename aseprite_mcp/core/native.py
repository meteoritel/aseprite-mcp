"""Activate an explicit cel and optional selection for native batch filters."""
from .lua import lua_layer_ref, lua_layer_refs
from .contracts import LayerRef
from .lua import EDIT_TARGET
from .commands import lua_escape


def build_native_command_script(
    command_lua: str,
    layer_name: LayerRef,
    frame_index: int,
    region: tuple[int, int, int, int] | None = None,
) -> str:
    """Wrap an `app.command.X{ui=false,...}` snippet with target activation,
    an optional selection scope, a transaction, save, and the ERROR:/OK
    protocol used by the checked-execution path.

    Args:
        command_lua: the `app.command.X{ui=false, ...}` Lua line(s)
        layer_name: explicit layer to activate first
        frame_index: 1-based frame to activate
        region: optional (x, y, w, h) to scope the command via a selection
    """
    safe_layer = lua_escape(layer_name)
    if region is not None:
        x, y, w, h = region
        sel_set = f"spr.selection = Selection(Rectangle({x}, {y}, {w}, {h}))"
        sel_clear = "spr.selection:deselect()"
    else:
        sel_set = sel_clear = ""
    return f"""
    {EDIT_TARGET}
    local spr = app.activeSprite
    if not spr then print("ERROR:No active sprite") return end
    local idx = {frame_index}
    app.activeFrame = require_frame(spr, idx)
    local target = require_layer(spr, {lua_layer_ref(layer_name)} , false)
    require_cel(spr, target, idx, false)
    app.activeLayer = target
    {sel_set}
    app.transaction(function()
{command_lua}
    end)
    {sel_clear}
    save_project(spr)
    print("OK")
    """
