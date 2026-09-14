"""Session-level active sprite tracking.

Each stdio session works on one sprite file at a time. The first call that
names a file — create_canvas, or any tool given an explicit filename —
anchors it as the active file; later calls may then omit `filename`.
"""

_active_file: str | None = None

NO_ACTIVE_FILE_ERROR = (
    "No filename given and no active file set yet — "
    "pass filename explicitly or call create_canvas first"
)


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
