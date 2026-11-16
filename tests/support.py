"""Run real tools and inspect their projects, artifacts and stdio responses."""

import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

import pytest
from PIL import Image
from mcp.server.mcpserver.exceptions import ToolError

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
RESPONSE_TIMEOUT_SECONDS = 10
FIXTURE_GLYPHS = {
    "A": [".##.", "#..#", "####", "#..#", "#..#", "...."],
    "B": ["###.", "#..#", "###.", "#..#", "###.", "...."],
    "O": [".##.", "#..#", "#..#", "#..#", ".##.", "...."],
}


def run(coro):
    return asyncio.run(coro)


def failure(coro):
    with pytest.raises(ToolError) as error:
        run(coro)
    return str(error.value)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).digest()


def frame_image(filename, frame_index, directory):
    """Read the saved project using Aseprite CLI, independently of tool export."""
    with tempfile.TemporaryDirectory(dir=directory) as staging:
        output = Path(staging) / "frame.png"
        result = subprocess.run(
            [os.getenv("ASEPRITE_PATH", "aseprite"), "--batch", filename,
             "--frame-range", f"{frame_index - 1},{frame_index - 1}",
             "--save-as", str(output)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        produced = list(Path(staging).glob("frame*.png"))
        assert len(produced) == 1, produced
        with Image.open(produced[0]) as image:
            return image.convert("RGBA")


@contextmanager
def connected_server(*, env=None, code=None):
    environment = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONDONTWRITEBYTECODE="1") | (env or {})
    command = [sys.executable, "-B", "-m", "aseprite_mcp"] if code is None else [sys.executable, "-B", "-c", code]
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as diagnostics:
        server = subprocess.Popen(
            command, cwd=REPO_ROOT, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=diagnostics,
            text=True, encoding="utf-8",
        )
        responses = queue.Queue()
        pending = {}

        def read_lines():
            try:
                for line in server.stdout:
                    responses.put(json.loads(line))
            except (ValueError, OSError) as error:
                responses.put(error)
            finally:
                responses.put(None)

        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()

        def send(method, params, request_id=None):
            request = {"jsonrpc": "2.0", "method": method, "params": params}
            if request_id is not None:
                request["id"] = request_id
            server.stdin.write(json.dumps(request) + "\n")
            server.stdin.flush()

        def receive(request_id):
            deadline = time.monotonic() + RESPONSE_TIMEOUT_SECONDS
            while request_id not in pending:
                try:
                    response = responses.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    diagnostics.seek(0)
                    pytest.fail(f"No response for {request_id}: {diagnostics.read()}")
                if isinstance(response, Exception):
                    raise response
                if response is None:
                    diagnostics.seek(0)
                    pytest.fail(f"Server closed before response {request_id}: {diagnostics.read()}")
                if "id" in response:
                    pending[response["id"]] = response
            response = pending.pop(request_id)
            assert "error" not in response, response
            return response["result"]

        try:
            send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "workflow-test", "version": "1"}}, 0)
            initialized = receive(0)
            assert initialized["instructions"] == (Path(REPO_ROOT) / "SKILL.md").read_text(encoding="utf-8").strip()
            send("notifications/initialized", {})
            yield send, receive
            server.stdin.close()
            assert server.wait(timeout=RESPONSE_TIMEOUT_SECONDS) == 0
        finally:
            if server.poll() is None:
                server.kill()
                server.wait(timeout=5)
            if not server.stdin.closed:
                server.stdin.close()
            reader.join(timeout=5)
            server.stdout.close()


def call(send, receive, name, arguments, request_id=1):
    send("tools/call", {"name": name, "arguments": arguments}, request_id)
    return receive(request_id)


def paint(filename, layer="ink", frame=1):
    from aseprite_mcp.tools import sprite_map

    run(sprite_map.draw_sprite_map(
        filename=filename, layer_name=layer, frame_index=frame,
        rows=["A..", ".B."], palette={"A": "#ff0000", "B": "#00ff00"},
    ))


def payload(output):
    """Consume the same successful result data used by protocol clients."""
    return output.model_dump(mode="json")["data"]
