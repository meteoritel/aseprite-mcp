"""Shared fixtures for the end-to-end tool tests.

These tests run each MCP tool against a real Aseprite (ASEPRITE_PATH),
so they are smoke/integration tests, not unit tests. Tests within a
file form a sequence on a module-scoped sprite; files are independent.

Scratch files live under a fixed temp path (not pytest's tmp_path) so
they resolve identically inside the Docker-wrapped Aseprite, which only
mounts /tmp and /var/folders. On Windows, "/tmp/..." stopped counting
as an absolute path in Python 3.13 (no drive letter), which
create_canvas rejects — so use the platform temp dir there instead.
"""
import asyncio
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aseprite_mcp.tools  # noqa: F401  (registers all tools)
from aseprite_mcp.tools import canvas, drawing

if sys.platform == "win32":
    BASE = os.path.join(tempfile.gettempdir(), "ase-pytest")
else:
    BASE = "/tmp/ase-pytest"


def run(coro):
    """Execute an async tool call from a sync test."""
    return asyncio.run(coro)


def ok(result):
    """Assert a tool call did not return an error message."""
    assert not str(result).startswith(
        ("Failed", "ERROR", "Invalid", "Script failed")
    ), result
    return result


@pytest.fixture(scope="session", autouse=True)
def base_dir():
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE, exist_ok=True)
    return BASE


@pytest.fixture(scope="module")
def sprite(request, base_dir):
    """A fresh 32x32 sprite per test module with a painted 'body' layer."""
    name = request.module.__name__.removeprefix("tests.").removeprefix("test_")
    path = f"{BASE}/{name}.aseprite"
    ok(run(canvas.create_canvas(width=32, height=32, filename=path)))
    # ok() only matches a few error prefixes; a message like "create_canvas
    # requires an ABSOLUTE filename..." would slip through it silently.
    # Asserting existence catches any such silent failure.
    assert os.path.exists(path), f"sprite fixture did not create {path}"
    ok(run(canvas.add_layer(filename=path, layer_name="body")))
    ok(run(drawing.draw_rectangle_at(filename=path, layer_name="body", frame_index=1, x=8, y=8, width=16, height=16, color="#D04648", fill=True)))
    return path
