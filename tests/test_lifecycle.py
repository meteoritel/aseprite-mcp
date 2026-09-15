"""Client-liveness watchdog (core/lifecycle.py).

Unlike the other test modules these need no Aseprite: they cover the decision
logic plus the end-to-end case that used to leak — a server whose client
process is force-killed has to exit on its own.
"""
import os
import select
import signal
import subprocess
import sys
import threading
import time

import pytest

from aseprite_mcp.core import lifecycle

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# A stand-in MCP client: spawns the real server, completes an actual
# initialize handshake (so the test can prove the server is up and serving,
# not merely a lingering process), reports the server pid, then just sits
# there. Killing *this* process is what used to leave the server running
# forever.
CLIENT_CODE = """
import json, os, subprocess, sys, time
env = dict(os.environ)
env["PYTHONPATH"] = r"{repo}"
p = subprocess.Popen(
    [sys.executable, "-m", "aseprite_mcp"],
    cwd=r"{repo}", env=env,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True, encoding="utf-8", errors="replace",
)
request = {{
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {{"protocolVersion": "2024-11-05", "capabilities": {{}},
                "clientInfo": {{"name": "lifecycle-test", "version": "1"}}}},
}}
p.stdin.write(json.dumps(request) + "\\n")
p.stdin.flush()
reply = p.stdout.readline()
if not reply or '"result"' not in reply:
    print("HANDSHAKE_FAILED", flush=True)
    sys.exit(1)
print("READY " + str(p.pid), flush=True)
time.sleep(600)
""".format(repo=REPO_ROOT)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        return str(pid) in (result.stdout or "")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_client(pid: int) -> None:
    """Kill just the client process — what a crash looks like.

    Deliberately NOT `taskkill /T`: killing the tree would take the server with
    it and the test could no longer tell whether the watchdog did anything.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _kill_tree(pid: int) -> None:
    """Cleanup only: remove a process and anything it spawned."""
    if not _pid_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _platform_stdin_probe():
    """The raw fd-level EOF probe for this platform."""
    if os.name == "nt":
        return lifecycle._stdin_eof_windows
    return lifecycle._stdin_eof_posix


# macOS has no select.poll(), so no non-consuming EOF probe exists to test and
# the watchdog there is left with the parent signal alone.
requires_stdin_probe = pytest.mark.skipif(
    os.name != "nt" and not hasattr(select, "poll"),
    reason="no non-consuming stdin EOF probe on this platform (macOS lacks poll)",
)


class _DeadParent:
    """Stands in for a parent process that has exited."""

    def parent_gone(self, timeout_ms: int = 0) -> bool:
        return True


class _LiveParent:
    def parent_gone(self, timeout_ms: int = 0) -> bool:
        return False


@pytest.fixture(autouse=True)
def watchdog_env(monkeypatch):
    """Keep a developer's own ASEPRITE_MCP_CLIENT_WATCHDOG out of these tests."""
    monkeypatch.delenv(lifecycle.WATCHDOG_ENV_VAR, raising=False)


def test_install_returns_thread_and_fires_when_client_gone():
    gone = threading.Event()
    thread = lifecycle.install_client_watchdog(
        interval=0.01, probe=lambda: True, on_client_gone=gone.set
    )
    assert thread is not None
    assert gone.wait(5.0), "watchdog never reported the client as gone"
    assert not thread.is_alive(), "watchdog should stop after firing once"


def test_watchdog_keeps_waiting_while_client_is_alive():
    fired = threading.Event()
    lifecycle.install_client_watchdog(
        interval=0.01, probe=lambda: False, on_client_gone=fired.set
    )
    time.sleep(0.2)
    assert not fired.is_set()


def test_flickering_probe_never_fires():
    """One-off readings must not kill a live session: two in a row are needed."""
    sequence = [True, False, True, False, True, False]
    calls: list[int] = []
    fired = threading.Event()

    def probe() -> bool:
        calls.append(1)
        return sequence[min(len(calls) - 1, len(sequence) - 1)]

    lifecycle.install_client_watchdog(
        interval=0.01, probe=probe, on_client_gone=fired.set
    )
    time.sleep(0.3)
    assert not fired.is_set(), f"fired after {len(calls)} alternating readings"


def test_probe_error_does_not_kill_the_watchdog():
    """A hiccup in the probe must not silently disarm it."""
    calls = []

    def flaky() -> bool:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("transient")
        return True

    gone = threading.Event()
    lifecycle.install_client_watchdog(
        interval=0.01, probe=flaky, on_client_gone=gone.set
    )
    assert gone.wait(5.0), "watchdog gave up after the probe raised"


def test_env_var_disables_the_watchdog(monkeypatch):
    monkeypatch.setenv(lifecycle.WATCHDOG_ENV_VAR, "0")
    assert lifecycle.install_client_watchdog() is None


@requires_stdin_probe
def test_stdin_probe_is_non_consuming():
    """Reading nothing must stay possible for the transport after a probe."""
    read_fd, write_fd = os.pipe()
    try:
        probe = _platform_stdin_probe()
        assert probe(read_fd) is False
        os.write(write_fd, b"x")
        # Data waiting is not EOF, and the probe must leave it in the pipe.
        assert probe(read_fd) is False
        assert os.read(read_fd, 1) == b"x"
        assert probe(read_fd) is False
        os.close(write_fd)
        write_fd = -1
        assert probe(read_fd) is True, "closed writer must read as EOF"
    finally:
        if write_fd != -1:
            os.close(write_fd)
        os.close(read_fd)


@requires_stdin_probe
def test_open_stdin_beats_a_dead_parent(monkeypatch):
    """A short-lived launch wrapper must not get a working session killed.

    `cmd /c start`-style launchers, detached spawners and shell wrappers all
    exit while the client keeps holding our stdin. The pipe is proof the session
    is alive, so it has to outrank the dead-parent signal — otherwise the
    watchdog exits a perfectly healthy session a couple of ticks in.
    """
    read_fd, write_fd = os.pipe()
    try:
        monkeypatch.setattr(lifecycle, "_client_parent", _DeadParent())
        monkeypatch.setattr(lifecycle, "_stdin_fd", lambda: read_fd)
        assert lifecycle.client_gone() is False
        # Buffered input is not EOF either.
        os.write(write_fd, b"x")
        assert lifecycle.client_gone() is False
    finally:
        os.close(write_fd)
        os.close(read_fd)


@requires_stdin_probe
def test_closed_stdin_alone_is_enough(monkeypatch):
    """The authoritative signal does not need the parent to agree."""
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    try:
        monkeypatch.setattr(lifecycle, "_client_parent", _LiveParent())
        monkeypatch.setattr(lifecycle, "_stdin_fd", lambda: read_fd)
        assert lifecycle.client_gone() is True
    finally:
        os.close(read_fd)


def test_dead_parent_decides_when_stdin_cannot_tell(monkeypatch):
    """macOS (no poll), or a stdin that is not a pipe, leaves the parent signal.

    This is the case the fallback exists for, and the reason it was not simply
    dropped when stdin became authoritative.
    """
    monkeypatch.setattr(lifecycle, "_client_parent", _DeadParent())
    monkeypatch.setattr(lifecycle, "_stdin_fd", lambda: None)
    assert lifecycle.client_gone() is True


def test_probe_error_falls_back_to_the_parent(monkeypatch):
    """A throwing stdin probe must not read as 'still connected'."""

    def raises() -> bool | None:
        raise OSError("pipe busy")

    monkeypatch.setattr(lifecycle, "_client_parent", _DeadParent())
    monkeypatch.setattr(lifecycle, "_stdin_eof", raises)
    assert lifecycle.client_gone() is True


def _orphan_scenario(*, watchdog: bool, observe_seconds: float) -> tuple[bool, int, int]:
    """Run client -> server, crash the client, watch the server.

    Returns (server_survived, client_pid, server_pid). The stand-in client owns
    the server's stdin pipe, exactly like a real MCP client; killing only that
    client is the failure this watchdog is for. `server_pid` is the server's
    launcher, which exits with the server it supervises, so its survival is a
    faithful proxy for the server's.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT
    env[lifecycle.WATCHDOG_ENV_VAR] = "1" if watchdog else "0"

    client = subprocess.Popen(
        [sys.executable, "-c", CLIENT_CODE], env=env,
        stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    server_pid = None
    try:
        line = (client.stdout.readline() or "").strip()
        client.stdout.close()
        assert line.startswith("READY "), (
            f"server never completed the initialize handshake: {line!r}"
        )
        server_pid = int(line.split()[1])
        assert _pid_alive(server_pid), "server was not running to begin with"

        started = time.time()
        _kill_client(client.pid)
        assert not _pid_alive(client.pid), "client survived its own kill"
        while time.time() - started < observe_seconds and _pid_alive(server_pid):
            time.sleep(0.25)
        return _pid_alive(server_pid), client.pid, server_pid
    finally:
        # Never leave an orphan behind, whichever arm of the A/B this is.
        _kill_tree(client.pid)
        if server_pid is not None:
            _kill_tree(server_pid)


@requires_stdin_probe
def test_watchdog_is_what_ends_the_orphan_case():
    """A/B on the real thing: same kill, watchdog off vs on.

    The control arm is what makes this meaningful. If the server died on its
    own with the watchdog disabled, the exit could not be attributed to the
    watchdog and the test would prove nothing, so that arm must observe a
    *surviving* server.

    Before the watchdog existed, the pair left behind was ~60 MB per crashed
    client session and nothing but `taskkill /T /F` could remove it.
    """
    survived_without, _, _ = _orphan_scenario(watchdog=False, observe_seconds=6)
    assert survived_without, (
        "control arm failed: the server exited even with "
        f"{lifecycle.WATCHDOG_ENV_VAR}=0, so this test cannot attribute the "
        "exit to the watchdog. Something else now ends the server (the MCP "
        "SDK may have fixed stdin EOF handling) — re-check whether the "
        "watchdog is still needed."
    )

    survived_with, _, _ = _orphan_scenario(watchdog=True, observe_seconds=15)
    assert not survived_with, (
        "server outlived its force-killed client: the watchdog did not fire "
        "(see core/lifecycle.py)"
    )
