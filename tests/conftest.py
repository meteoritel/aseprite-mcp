"""Real Aseprite tests with independent projects under an owned temp directory."""
import asyncio
import os
import shutil
import sys
import tempfile
import uuid

import pytest
from mcp.server.mcpserver.exceptions import ToolError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aseprite_mcp.tools import canvas, drawing

BASE = os.path.join(tempfile.gettempdir(), "ase-pytest", uuid.uuid4().hex)


def run(coro):
    """Execute an async tool call from a sync test."""
    return asyncio.run(coro)


def failure(coro):
    """Exercise a real failed tool call and return its diagnostic for assertions."""
    with pytest.raises(ToolError) as error:
        run(coro)
    return str(error.value)


@pytest.fixture(scope="session", autouse=True)
def base_dir():
    os.makedirs(BASE, exist_ok=True)
    yield BASE
    from aseprite_mcp.core.state import cleanup_review_directory
    cleanup_review_directory()
    shutil.rmtree(BASE)


@pytest.fixture
def new_sprite(base_dir):
    """Create independent native projects under the owned test directory."""
    def create(width=16, height=16):
        path = os.path.join(base_dir, f"{uuid.uuid4().hex}.aseprite")
        run(canvas.create_canvas(width, height, filename=path))
        assert os.path.isfile(path)
        return path
    return create


@pytest.fixture
def sprite(request, base_dir):
    """An independent 32x32 project with a painted body layer."""
    name = request.module.__name__.removeprefix("tests.").removeprefix("test_")
    path = f"{BASE}/{name}-{uuid.uuid4().hex}.aseprite"
    run(canvas.create_canvas(width=32, height=32, filename=path))
    assert os.path.exists(path), f"sprite fixture did not create {path}"
    run(canvas.add_layer(filename=path, layer_name="body"))
    run(drawing.draw_rectangle_at(filename=path, layer_name="body", frame_index=1, x=8, y=8, width=16, height=16, color="#D04648", fill=True))
    return path


@pytest.fixture(autouse=True)
def reset_active_file():
    from aseprite_mcp.core import state
    state._active_file = None
    yield
    state._active_file = None
