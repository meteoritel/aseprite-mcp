"""The legacy SDK crashed on Antigravity's server/discover probe.

Verify the current server answers discovery and then serves tools/list.
"""

import json
import os
import queue
import subprocess
import sys
import threading

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESPONSE_TIMEOUT_SECONDS = 10
PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"


def _read_response(server: subprocess.Popen[str]) -> dict:
    lines = queue.Queue()
    threading.Thread(
        target=lambda: lines.put(server.stdout.readline()), daemon=True
    ).start()
    line = lines.get(timeout=RESPONSE_TIMEOUT_SECONDS)
    assert line, "stdio server closed before replying"
    return json.loads(line)


def test_server_discover_then_tools_list_over_stdio():
    client_meta = {
        PROTOCOL_VERSION_META_KEY: "2026-07-28",
        CLIENT_INFO_META_KEY: {"name": "protocol-test", "version": "1"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT
    server = subprocess.Popen(
        [sys.executable, "-m", "aseprite_mcp"],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    try:
        server.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"_meta": client_meta},
        }) + "\n")
        server.stdin.flush()
        discover_response = _read_response(server)
        assert discover_response["id"] == 1

        server.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {"_meta": client_meta},
        }) + "\n")
        server.stdin.flush()
        tools_response = _read_response(server)
        assert tools_response["id"] == 2

        discover = discover_response["result"]
        assert "2026-07-28" in discover["supportedVersions"]
        assert discover["resultType"] == "complete"
        assert "tools" in discover["capabilities"]

        tool_names = {tool["name"] for tool in tools_response["result"]["tools"]}
        assert "create_canvas" in tool_names

        server.stdin.close()
        assert server.wait(timeout=RESPONSE_TIMEOUT_SECONDS) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
