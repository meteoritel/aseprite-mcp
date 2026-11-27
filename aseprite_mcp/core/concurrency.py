"""Per-file async read/write scheduling for concurrent MCP tool calls."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Any

from .commands import reject_traversal
from .image_read import is_raster_image
from .state import get_active_file, resolve_path

LOCKLESS_TOOLS = frozenset({
    "search_tools",
    "list_palette_presets",
    "generate_color_ramp",
    "list_convolution_matrices",
    "list_text_fonts",
    "measure_text",
})

READ_ONLY_TOOLS = frozenset({
    "get_sprite_info",
    "get_palette",
    "get_pixel_color",
    "get_pixels_rect",
    "get_composite_pixel",
    "get_composite_rect",
    "get_sprite_map",
    "review_frame",
    "review_contact_sheet",
    "compare_frames",
    "get_color_stats",
    "list_slices",
    "get_tile_at",
    "get_tilemap_info",
    "validate_scene",
    "audit_animation",
})

EXPORT_TOOLS = frozenset({
    "export_sprite",
    "copy_sprite",
    "export_frame",
    "export_spritesheet",
    "export_layers",
    "export_tag",
    "export_minecraft_texture",
    "export_slices_to_minecraft",
    "render_onion_skin",
})

PREVIEW_TOOLS = frozenset({
    "start_preview_server",
    "stop_preview_server",
})

CREATE_NATIVE_TOOLS = frozenset({
    "create_canvas",
    "create_layered_sprite",
})

_GLOBAL_KEY = "__global__"
_PREVIEW_KEY = "__preview__"
_INVALID_KEY = "__invalid__"


class _AsyncRWLock:
    """FIFO readers-writer lock with cancellation-safe waiter cleanup."""

    def __init__(self) -> None:
        self._readers = 0
        self._writer = False
        self._waiters: deque[tuple[bool, asyncio.Future[None]]] = deque()

    def _can_grant(self, is_write: bool) -> bool:
        if is_write:
            return not self._writer and self._readers == 0
        return not self._writer

    async def acquire(self, is_write: bool) -> None:
        if not self._waiters and self._can_grant(is_write):
            if is_write:
                self._writer = True
            else:
                self._readers += 1
            return

        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        entry = (is_write, future)
        self._waiters.append(entry)
        try:
            await future
        except BaseException:
            if future.done() and not future.cancelled():
                self.release(is_write)
            else:
                try:
                    self._waiters.remove(entry)
                except ValueError:
                    pass
                self._wake_waiters()
            raise

    def release(self, is_write: bool) -> None:
        if is_write:
            self._writer = False
        else:
            self._readers -= 1
        self._wake_waiters()

    def _wake_waiters(self) -> None:
        while self._waiters:
            is_write, future = self._waiters[0]
            if future.cancelled():
                self._waiters.popleft()
                continue
            if is_write:
                if not self._writer and self._readers == 0:
                    self._waiters.popleft()
                    self._writer = True
                    future.set_result(None)
                break
            if self._writer:
                break
            self._waiters.popleft()
            self._readers += 1
            future.set_result(None)


def unwrap_tool_call(context: Any) -> tuple[str, dict[str, Any]]:
    """Extract the effective tool name and arguments from a tools/call context."""
    params = getattr(context, "params", None)
    if isinstance(params, Mapping):
        name = params.get("name")
        arguments = params.get("arguments")
    else:
        request = getattr(context, "request", None)
        req_params = getattr(request, "params", None)
        name = getattr(req_params, "name", None)
        arguments = getattr(req_params, "arguments", None)

    tool_name = name if isinstance(name, str) else ""
    tool_args = dict(arguments) if isinstance(arguments, Mapping) else {}

    if tool_name == "call_tool":
        inner_name = tool_args.get("name")
        inner_args = tool_args.get("arguments")
        if isinstance(inner_name, str) and isinstance(inner_args, Mapping):
            return inner_name, dict(inner_args)
    return tool_name, tool_args


def _canonical_key(raw_path: Any, *, allow_active: bool = True, native_default: bool = False) -> str:
    if isinstance(raw_path, str) and raw_path:
        if reject_traversal(raw_path):
            return _INVALID_KEY
        resolved = resolve_path(raw_path)
        if native_default and not Path(resolved).suffix:
            resolved = str(Path(resolved).with_suffix(".aseprite"))
        return os.path.normcase(resolved)
    if allow_active:
        active = get_active_file()
        return os.path.normcase(active) if active else _GLOBAL_KEY
    return ""


def _merge_locks(entries: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    merged: dict[str, bool] = {}
    for key, is_write in entries:
        if not key or key == _INVALID_KEY:
            continue
        merged[key] = merged.get(key, False) or is_write
    return sorted(merged.items(), key=lambda item: item[0])


def plan_resource_locks(tool_name: str, args: Mapping[str, Any]) -> list[tuple[str, bool]]:
    """Return sorted (resource_key, is_write) pairs required for a tool call."""
    if not tool_name or tool_name in LOCKLESS_TOOLS:
        return []
    if tool_name in PREVIEW_TOOLS:
        return [(_PREVIEW_KEY, True)]

    locks: list[tuple[str, bool]] = []

    if tool_name == "review_contact_sheet":
        filenames = args.get("filenames")
        if isinstance(filenames, list) and filenames:
            for item in filenames:
                locks.append((_canonical_key(item, allow_active=False), False))
        else:
            locks.append((_canonical_key(args.get("filename", "")), False))
        if save_to := args.get("save_preview_to"):
            locks.append((_canonical_key(save_to, allow_active=False), True))
        return _merge_locks(locks)

    if tool_name == "copy_layers_between_sprites":
        locks.append((_canonical_key(args.get("source_filename", "")), False))
        locks.append((_canonical_key(args.get("target_filename", ""), allow_active=False), True))
        return _merge_locks(locks)

    if tool_name in EXPORT_TOOLS:
        locks.append((_canonical_key(args.get("filename", "")), False))
        for field in ("output_filename", "output_directory", "data_filename"):
            if target := args.get(field):
                locks.append((
                    _canonical_key(
                        target,
                        allow_active=False,
                        native_default=(tool_name == "copy_sprite" and field == "output_filename"),
                    ),
                    True,
                ))
        return _merge_locks(locks)

    if tool_name in READ_ONLY_TOOLS:
        locks.append((_canonical_key(args.get("filename", "")), False))
        if save_to := args.get("save_preview_to"):
            locks.append((_canonical_key(save_to, allow_active=False), True))
        return _merge_locks(locks)

    if tool_name == "extract_palette":
        key = _canonical_key(args.get("filename", ""))
        is_write = not (key not in (_GLOBAL_KEY, _INVALID_KEY) and is_raster_image(key))
        locks.append((key, is_write))
        return _merge_locks(locks)

    is_create = tool_name in CREATE_NATIVE_TOOLS
    locks.append((
        _canonical_key(args.get("filename", ""), allow_active=not is_create, native_default=is_create),
        True,
    ))
    if tool_name == "import_image_as_layer" and (image_path := args.get("image_path")):
        locks.append((_canonical_key(image_path, allow_active=False), False))
    return _merge_locks(locks)


class ResourceLockManager:
    """Manage per-resource RW locks with automatic cleanup of idle entries."""

    def __init__(self) -> None:
        self._locks: dict[str, _AsyncRWLock] = {}
        self._refs: dict[str, int] = {}

    def _borrow(self, key: str) -> _AsyncRWLock:
        lock = self._locks.get(key)
        if lock is None:
            lock = _AsyncRWLock()
            self._locks[key] = lock
        self._refs[key] = self._refs.get(key, 0) + 1
        return lock

    def _return(self, key: str) -> None:
        remaining = self._refs[key] - 1
        if remaining <= 0:
            self._refs.pop(key, None)
            self._locks.pop(key, None)
        else:
            self._refs[key] = remaining

    @asynccontextmanager
    async def acquire(self, tool_name: str, args: Mapping[str, Any]):
        plan = plan_resource_locks(tool_name, args)
        acquired: list[tuple[str, _AsyncRWLock, bool]] = []
        try:
            for key, is_write in plan:
                lock = self._borrow(key)
                try:
                    await lock.acquire(is_write)
                except BaseException:
                    self._return(key)
                    raise
                acquired.append((key, lock, is_write))
            yield
        finally:
            for key, lock, is_write in reversed(acquired):
                lock.release(is_write)
                self._return(key)
