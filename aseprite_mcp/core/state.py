"""Session-level active sprite tracking and filename resolution.

Each stdio session works on one sprite file at a time. The first call that
names a file — create_canvas, or any tool given an explicit filename —
anchors it as the active file; later calls may then omit `filename`.

`prepare_filename()` is the single entry point every tool uses to turn the
user-supplied `filename` argument into a validated absolute path, so files
never silently land in the wrong directory.
"""

import os
import tempfile

from mcp.server.mcpserver.exceptions import ToolError

from .commands import reject_traversal

_active_file: str | None = None
_review_directory: tempfile.TemporaryDirectory | None = None

NO_ACTIVE_FILE_ERROR = (
    "No filename given and no active file set yet — "
    "call create_canvas first, or pass filename explicitly"
)

FILE_NOT_FOUND_HINT = (
    " not found — pass an absolute path, or a path relative to the "
    "workspace directory"
)

WORKSPACE_ENV_VAR = "ASEPRITE_MCP_WORKSPACE"
LEGACY_WORKSPACE_ENV_VAR = "ASERITE_MCP_WORKSPACE"


def set_active_file(filename: str) -> None:
    """Anchor `filename` as the file subsequent no-filename calls operate on."""
    global _active_file
    _active_file = filename


def get_active_file() -> str | None:
    """Return the currently anchored file, or None when none was set."""
    return _active_file


def resolve_filename(filename: str) -> str | None:
    """Explicit filename wins; otherwise fall back to the active file.

    Returns None when no filename was given and none is anchored yet.
    Callers should anchor the resolved file via set_active_file() only
    after validating that it exists.
    """
    return filename or _active_file


def get_configured_workspace_dir() -> str | None:
    """Return explicitly configured workspace directory, if any.

    Checks `ASEPRITE_MCP_WORKSPACE` first and falls back to the legacy
    `ASERITE_MCP_WORKSPACE` spelling for backwards compatibility.
    """
    workspace = os.getenv(WORKSPACE_ENV_VAR) or os.getenv(LEGACY_WORKSPACE_ENV_VAR)
    if workspace:
        return os.path.abspath(os.path.expanduser(workspace))
    return None


def get_workspace_dir() -> str:
    """Directory that relative paths resolve against.

    Explicitly configured workspace (`ASEPRITE_MCP_WORKSPACE` / legacy
    `ASERITE_MCP_WORKSPACE`) wins; otherwise the server's current working directory.
    """
    return get_configured_workspace_dir() or os.getcwd()


def resolve_path(path: str) -> str:
    """Expand `~` and make a relative path absolute against the workspace."""
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(get_workspace_dir(), expanded)
    return os.path.abspath(expanded)


def prepare_filename(
    filename: str,
    *,
    must_exist: bool = True,
    anchor: bool = True,
) -> str:
    """Validate a tool's `filename` argument and return an absolute path.

    Steps: fall back to the active file when omitted, resolve relative
    paths against the workspace, reject `..` traversal, optionally require
    the file to exist, then anchor it as the active file.

    Set `anchor=False` for output paths (exports, copies) so writing a file
    never re-points the session's active file at it.

    Returns the absolute path; raises ToolError with a corrective hint on failure.
    """
    resolved = resolve_filename(filename)
    if resolved is None:
        raise ToolError(NO_ACTIVE_FILE_ERROR)

    # Check traversal on the RAW input: resolving first would let
    # os.path.abspath silently collapse `..` and hide the attack.
    traversal_error = reject_traversal(resolved)
    if traversal_error:
        raise ToolError(traversal_error)

    absolute = resolve_path(resolved)

    if must_exist and not os.path.exists(absolute):
        raise ToolError(f"File {absolute}{FILE_NOT_FOUND_HINT}")

    if anchor:
        set_active_file(absolute)
    return absolute


def get_review_directory() -> str:
    """Temporary review images live until the owning stdio session exits."""
    global _review_directory
    if _review_directory is None:
        _review_directory = tempfile.TemporaryDirectory(prefix="aseprite-review-")
    return _review_directory.name


def cleanup_review_directory() -> None:
    global _review_directory
    if _review_directory is not None:
        _review_directory.cleanup()
        _review_directory = None
