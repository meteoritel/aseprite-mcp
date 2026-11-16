from mcp.server.mcpserver.exceptions import ToolError

from ..core.commands import AsepriteCommand
from ..core.contracts import ToolOutput
from ..core.results import ScriptOutput
from ..core.state import get_active_file, prepare_filename


async def run_lua_script(script: str, filename: str = "") -> ToolOutput[ScriptOutput]:
    """Execute arbitrary Aseprite Lua code in batch mode (escape hatch).

    Use this when no dedicated tool covers what you need. The full API
    is documented at https://www.aseprite.org/api/. Anything the curated
    tools do can also be done here — they are Lua underneath.

    Essentials for batch-mode scripts:
    - When filename is given, it is opened first and available as
      app.activeSprite.
    - Changes are NOT saved automatically; call spr:saveAs(spr.filename)
      at the end if you modified the sprite.
    - print() is the only way to return data; a clean exit does not mean
      your logic succeeded, so print what you need to verify.
    - Coordinates on cel images are cel-local: offset sprite-global
      coordinates by cel.position before getPixel/putPixel.

    WARNING: this executes unrestricted code (including io/os access)
    on the host running Aseprite. Only pass scripts you trust.

    Args:
        script: Lua source code to execute
        filename: Aseprite file to open before running (optional; defaults to
            the session's active file, or no file when nothing is anchored)
    """
    if not script.strip():
        raise ToolError("Script cannot be empty")
    if filename:
        filename = prepare_filename(filename)
    else:
        # No filename given: fall back to the active file so the script
        # sees it as app.activeSprite. Still allow None (script without
        # any sprite) when nothing is anchored.
        filename = get_active_file()

    output = await AsepriteCommand.execute_lua_script(script, filename or None)
    return ToolOutput(summary='Run lua script completed', data=ScriptOutput(stdout=output))
