"""Publish standard Lua edits only after a complete native project save."""

import os
from pathlib import Path
import struct
import tempfile

from mcp.server.mcpserver.exceptions import ToolError

from .commands import AsepriteCommand, lua_escape

NATIVE_EXTENSIONS = {".ase", ".aseprite"}
ASEPRITE_MAGIC = 0xA5E0
UNCHANGED_MARKER = "PROJECT_UNCHANGED"


def native_project_path(filename: str) -> str:
    path = Path(filename)
    if not path.suffix:
        return str(path.with_suffix(".aseprite"))
    if path.suffix.lower() not in NATIVE_EXTENSIONS:
        raise ToolError("Use .aseprite or .ase for an editable project; use export tools for images")
    return str(path)


def validate_native_project(filename: str) -> None:
    with open(filename, "rb") as project:
        header = project.read(6)
    if len(header) != 6:
        raise ToolError("Aseprite did not save a complete native project")
    size, magic = struct.unpack("<IH", header)
    if magic != ASEPRITE_MAGIC or size != os.path.getsize(filename):
        raise ToolError("Aseprite saved an invalid native project")


async def execute_edit_script(script: str, filename: str | None = None, *, output_filename: str | None = None) -> str:
    """Run Lua using save_project(sprite), then replace its exact native target.

    filename opens an existing source. output_filename selects a separate
    destination or supplies the destination when creating a new project.
    """
    destination = native_project_path(output_filename or filename)
    try:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".aseprite-edit-", dir=Path(destination).parent) as staging:
            staged = str(Path(staging) / Path(destination).name)
            safe_path = lua_escape(staged.replace("\\", "/"))
            prelude = f'''local function save_project(sprite)
                sprite:saveAs("{safe_path}")
            end
            '''
            output = await AsepriteCommand.execute_lua_script_checked(prelude + script, filename)
            lines = output.splitlines()
            if UNCHANGED_MARKER in lines:
                return "\n".join(line for line in lines if line != UNCHANGED_MARKER)
            if not os.path.isfile(staged):
                raise ToolError("Aseprite exited successfully but saved no project")
            validate_native_project(staged)
            os.replace(staged, destination)
            return output
    except OSError as exc:
        raise ToolError(f"Could not save project '{destination}': {exc}") from exc
