"""The SDK stdio transport exits when its client disconnects.

The v1 transport could remain blocked after stdin EOF; the v2 transport must
close the server process when the client disappears.
"""

import os
import signal
import subprocess
import sys
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

CLIENT_CODE = """
import json, os, subprocess, sys, time
env = dict(os.environ)
env["PYTHONPATH"] = r"{repo}"
server = subprocess.Popen(
    [sys.executable, "-m", "aseprite_mcp"],
    cwd=r"{repo}", env=env,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True, encoding="utf-8", errors="replace",
)
request = {{
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {{"protocolVersion": "2024-11-05", "capabilities": {{}},
                "clientInfo": {{"name": "stdio-lifecycle-test", "version": "1"}}}},
}}
server.stdin.write(json.dumps(request) + "\\n")
server.stdin.flush()
reply = server.stdout.readline()
if not reply or '"result"' not in reply:
    print("HANDSHAKE_FAILED", flush=True)
    sys.exit(1)
print("READY " + str(server.pid), flush=True)
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


def _kill_tree(pid: int) -> None:
    if not _pid_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_stdio_server_exits_when_client_process_dies():
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT
    client = subprocess.Popen(
        [sys.executable, "-c", CLIENT_CODE],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    server_pid = None
    try:
        line = (client.stdout.readline() or "").strip()
        client.stdout.close()
        assert line.startswith("READY "), (
            f"server did not complete initialize handshake: {line!r}"
        )
        server_pid = int(line.split()[1])
        assert _pid_alive(server_pid), "server was not running before disconnect"

        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(client.pid), "/F"], capture_output=True)
        else:
            os.kill(client.pid, signal.SIGKILL)

        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and _pid_alive(server_pid):
            time.sleep(0.1)
        assert not _pid_alive(server_pid), "server remained alive after client disconnect"
    finally:
        _kill_tree(client.pid)
        if server_pid is not None:
            _kill_tree(server_pid)
