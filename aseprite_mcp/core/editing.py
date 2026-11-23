"""Publish standard Lua edits only after a complete native project save."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
import struct
import tempfile

from mcp.server.mcpserver.exceptions import ToolError

from .commands import AsepriteCommand, lua_escape
from .contracts import ToolOutput
from .results import EditReceipt
from .state import prepare_filename

NATIVE_EXTENSIONS = {".ase", ".aseprite"}
ASEPRITE_MAGIC = 0xA5E0
UNCHANGED_MARKER = "PROJECT_UNCHANGED"


@dataclass
class EditExecution:
    stdout: str
    layer_paths: list[list[str]]


def edit_output(summary: str, filename: str, execution: EditExecution | None = None, frame: int | None = None) -> ToolOutput[EditReceipt]:
    return ToolOutput(summary=summary, data=EditReceipt(
        filename=filename, layer_paths=execution.layer_paths if execution else [], frame=frame,
    ))


def _edit_execution(output: str) -> EditExecution:
    paths, lines = [], []
    for line in output.splitlines():
        if line.startswith("EDIT_TARGETS:"):
            paths.extend(json.loads(line.removeprefix("EDIT_TARGETS:")))
        elif line != UNCHANGED_MARKER:
            lines.append(line)
    return EditExecution("\n".join(lines), paths)


def native_project_path(filename: str) -> str:
    path = Path(filename)
    if not path.suffix:
        return str(path.with_suffix(".aseprite"))
    if path.suffix.lower() not in NATIVE_EXTENSIONS:
        raise ToolError("Use .aseprite or .ase for an editable project; use export tools for images")
    return str(path)


def new_project_path(filename: str) -> str:
    if not os.path.isabs(filename):
        raise ToolError(f"Specify an ABSOLUTE project filename, e.g. 'D:/art/sprites/coin.aseprite'. Got: {filename!r}")
    return native_project_path(prepare_filename(filename, must_exist=False, anchor=False))


def new_canvas_lua(width: int, height: int, layer_names: list[str] | None = None) -> str:
    script = f"local spr = Sprite({width}, {height})\n"
    if layer_names is None:
        return script
    if not layer_names or any(not name.strip() for name in layer_names):
        raise ToolError("Provide at least one non-blank layer name")
    if len(set(layer_names)) != len(layer_names):
        raise ToolError("Layer names must be unique")
    names = lua_escape(json.dumps(layer_names, ensure_ascii=False))
    return script + f'''
    local initial_layers = json.decode("{names}")
    spr.layers[1].name = initial_layers[1]
    for index = 2, #initial_layers do
        spr:newLayer().name = initial_layers[index]
    end
    '''


def validate_native_project(filename: str) -> None:
    with open(filename, "rb") as project:
        header = project.read(6)
    if len(header) != 6:
        raise ToolError("Aseprite did not save a complete native project")
    size, magic = struct.unpack("<IH", header)
    if magic != ASEPRITE_MAGIC or size != os.path.getsize(filename):
        raise ToolError("Aseprite saved an invalid native project")


async def execute_edit_script(script: str, filename: str | None = None, *, output_filename: str | None = None) -> EditExecution:
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
            prelude = f'''_aseprite_edit_targets = {{}}
            local function save_project(sprite)
                sprite:saveAs("{safe_path}")
                print("EDIT_TARGETS:" .. json.encode(_aseprite_edit_targets))
            end
            '''
            output = await AsepriteCommand.execute_lua_script_checked(prelude + script, filename)
            lines = output.splitlines()
            if UNCHANGED_MARKER in lines:
                return _edit_execution(output)
            if not os.path.isfile(staged):
                raise ToolError("Aseprite exited successfully but saved no project")
            validate_native_project(staged)
            os.replace(staged, destination)
            return _edit_execution(output)
    except OSError as exc:
        raise ToolError(f"Could not save project '{destination}': {exc}") from exc
