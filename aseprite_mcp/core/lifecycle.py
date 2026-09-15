"""Client-liveness watchdog: exit the server when its MCP client goes away.

Why this module exists
----------------------
A stdio MCP server is a child of the client and must die with it. Two things
break that in practice:

1. The client's direct child is usually a *launcher* chain, not the server.
   ``uv --directory ... run -m aseprite_mcp`` gives
   ``uv.exe -> python (venv launcher) -> python -m aseprite_mcp``, and the
   venv launcher does not watch *its* parent. Killing the client (or just
   ``uv.exe``) therefore leaves both python processes running with no
   client, forever.
2. The MCP SDK's stdio transport cannot always finish on its own: on stdin
   EOF ``stdin_reader`` ends, but ``stdout_writer`` stays blocked on a stream
   nobody closes, so the task group wrapping them never exits and
   ``anyio.run()`` never returns.

Measured on a real Windows session before this module existed: a server was
still alive 20 s after its stdin was closed, while a plain
``for line in sys.stdin`` control process on the same pipe exited in under a
second. One orphaned process *pair* (~60 MB) accumulated per crashed client
session, and nothing but ``taskkill /T`` could remove them.

How a dead client is detected
-----------------------------
The client's end of *stdin* is the authoritative signal, and no check ever
consumes input, so buffered requests are never stolen from the transport:

* Windows: ``PeekNamedPipe`` on stdin fails with ``ERROR_BROKEN_PIPE`` once
  every write handle is closed, and reports buffered bytes otherwise.
* POSIX: ``poll`` for ``POLLHUP``/``POLLERR`` on the stdin fd.

The parent process is a *fallback*, used only when stdin cannot answer (macOS
has no ``poll``, or stdin is not a pipe at all). It is the weaker of the two
signals: a client that launches the server through something short-lived
(``cmd /c start``, a detached spawner, a shell wrapper) leaves a dead parent
behind while the session stays perfectly usable, and a watchdog trusting that
parent would ``os._exit(0)`` into a healthy session ~4 s later. So "stdin is
open" outranks "parent is gone" rather than the two being OR-ed together. Where
the parent *is* the client (plain ``python -m aseprite_mcp``) the fallback is
still exact and immediate.

The check runs on a daemon thread every ``interval`` seconds, and must report
the same answer twice in a row before acting, so a one-off reading can never
kill a live session. Exiting goes through ``os._exit(0)`` deliberately: the
interpreter must not wait for the blocked transport task or any non-daemon
thread, which is exactly the state being escaped.

Set ``ASEPRITE_MCP_CLIENT_WATCHDOG=0`` to disable (e.g. when embedding the
server in a parent that is not an MCP client).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable

WATCHDOG_ENV_VAR = "ASEPRITE_MCP_CLIENT_WATCHDOG"
DEFAULT_INTERVAL_SECONDS = 2.0

# Exiting is irreversible, so the condition must hold on this many consecutive
# checks. A single reading still keeps an orphaned server around for at most
# one extra interval, which is a fair price for not killing a live session on a
# fluke.
_CONFIRMATIONS = 2

_ERROR_BROKEN_PIPE = 109
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x0
_WAIT_TIMEOUT = 0x102


def _env_enabled() -> bool:
    """Watchdog is on unless the env var explicitly turns it off."""
    raw = os.getenv(WATCHDOG_ENV_VAR)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _stdin_fd() -> int | None:
    """The stdin descriptor, or None when there is no usable stdin."""
    try:
        return sys.stdin.fileno()
    except (AttributeError, ValueError, OSError):
        return None


def _stdin_eof_windows(fd: int) -> bool | None:
    """True when the client's write end is closed, False while it is open.

    None when this stdin is not a pipe we can interrogate, so the caller knows
    the answer is unknown rather than "still connected".
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,      # hNamedPipe
        wintypes.LPVOID,      # lpBuffer
        wintypes.DWORD,       # nBufferSize
        wintypes.LPDWORD,     # lpBytesRead
        wintypes.LPDWORD,     # lpTotalBytesAvail
        wintypes.LPDWORD,     # lpBytesLeftThisMessage
    ]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL

    import msvcrt

    try:
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
    except (OSError, ValueError):
        return None

    available = wintypes.DWORD()
    ok = kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None)
    if ok:
        return False
    # Only a broken pipe means "no client is writing any more". Any other error
    # (stdin redirected from a file, say) means we cannot tell.
    if ctypes.get_last_error() == _ERROR_BROKEN_PIPE:
        return True
    return None


def _stdin_eof_posix(fd: int) -> bool | None:
    import select

    poll = getattr(select, "poll", None)
    if poll is None:
        # macOS: no poll(), and every other EOF test would have to consume the
        # byte it looks at. Report "unknown" so the parent fallback takes over.
        return None
    poller = poll()
    # Registering only the hangup/error events keeps a readable-with-data
    # stdin from being reported, so buffered input never looks like EOF.
    poller.register(fd, select.POLLHUP | select.POLLERR)
    for _, revents in poller.poll(0):
        if revents & (select.POLLHUP | select.POLLERR):
            return True
    return False


def _stdin_eof() -> bool | None:
    """Tri-state: True = client gone, False = client connected, None = unknown."""
    fd = _stdin_fd()
    if fd is None:
        return None
    if os.name == "nt":
        return _stdin_eof_windows(fd)
    return _stdin_eof_posix(fd)


class _ParentWatch:
    """Reports when this process' parent has exited.

    Windows waits on a SYNCHRONIZE handle to the parent, which the kernel
    signals the moment the parent dies — even if it was force-killed. POSIX
    polls ``getppid()``, which changes once the parent is reaped.
    """

    def __init__(self) -> None:
        self._kernel32 = None
        self._handle = None
        self._ppid: int | None = None

        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel32.OpenProcess.restype = wintypes.HANDLE
                kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel32.WaitForSingleObject.restype = wintypes.DWORD

                handle = kernel32.OpenProcess(_SYNCHRONIZE, False, os.getppid())
                if handle:
                    self._kernel32 = kernel32
                    self._handle = handle
            except (OSError, ValueError):
                self._handle = None
        else:
            ppid = os.getppid()
            # ppid 1 means we were already reparented; nothing to compare to.
            self._ppid = ppid if ppid > 1 else None

    def parent_gone(self, timeout_ms: int = 0) -> bool:
        if self._handle is not None:
            return (
                self._kernel32.WaitForSingleObject(self._handle, timeout_ms)
                == _WAIT_OBJECT_0
            )
        if self._ppid is None:
            return False
        return os.getppid() != self._ppid


def client_gone() -> bool:
    """True when the MCP client that owns this server has disappeared.

    Precedence matters here. A readable stdin is *proof* the client is still
    connected, and it is deliberately allowed to veto the parent signal: a
    client that spawns us through a short-lived wrapper (``cmd /c start``, a
    detached spawner) leaves a dead parent while the session keeps working, and
    killing that session would be worse than leaving an orphan behind. Only
    when stdin cannot answer does the parent process get a say.

    Public so tests and other transports can reuse the same decision.
    """
    try:
        stdin_state = _stdin_eof()
    except Exception:  # noqa: BLE001 - a probe error must not kill the server
        stdin_state = None
    if stdin_state is not None:
        return stdin_state

    if _client_parent is None:
        return False
    try:
        return _client_parent.parent_gone()
    except Exception:  # noqa: BLE001
        return False


_client_parent: _ParentWatch | None = None


def _watch_loop(
    interval: float,
    probe: Callable[[], bool],
    on_client_gone: Callable[[], None],
) -> None:
    strikes = 0
    while True:
        time.sleep(interval)
        try:
            if probe():
                strikes += 1
                if strikes >= _CONFIRMATIONS:
                    on_client_gone()
                    return
            else:
                strikes = 0
        except Exception:  # noqa: BLE001
            # A watchdog that dies on the first hiccup is worse than none.
            strikes = 0
            continue


def install_client_watchdog(
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    probe: Callable[[], bool] | None = None,
    on_client_gone: Callable[[], None] | None = None,
) -> threading.Thread | None:
    """Start the watchdog thread.

    Returns the thread, or None when disabled via the environment. `probe`
    and `on_client_gone` are injectable for tests.
    """
    if probe is None and not _env_enabled():
        return None

    global _client_parent
    if _client_parent is None and probe is None:
        _client_parent = _ParentWatch()

    if probe is None:
        probe = client_gone
    if on_client_gone is None:
        on_client_gone = lambda: os._exit(0)  # noqa: E731 - intentional hard exit

    thread = threading.Thread(
        target=_watch_loop,
        args=(interval, probe, on_client_gone),
        name="mcp-client-watchdog",
        daemon=True,
    )
    thread.start()
    return thread
