"""Unit tests for core.state path resolution — no Aseprite needed."""

import asyncio
import os

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from aseprite_mcp.core.state import (
    FILE_NOT_FOUND_HINT,
    NO_ACTIVE_FILE_ERROR,
    get_active_file,
    get_workspace_dir,
    prepare_filename,
    resolve_path,
    set_active_file,
)


def _run(coro):
    """Execute an async tool call from a sync test."""
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_session(monkeypatch):
    """Fresh session state and no workspace env var for every test."""
    monkeypatch.delenv("ASERITE_MCP_WORKSPACE", raising=False)
    import aseprite_mcp.core.state as state

    state._active_file = None
    yield
    state._active_file = None


class TestGetWorkspaceDir:
    def test_defaults_to_cwd(self):
        assert os.path.isabs(get_workspace_dir())

    def test_env_var_wins_and_is_absolute(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASERITE_MCP_WORKSPACE", str(tmp_path / "proj"))
        assert get_workspace_dir() == os.path.abspath(str(tmp_path / "proj"))


class TestResolvePath:
    def test_absolute_passthrough(self, tmp_path):
        assert resolve_path(str(tmp_path / "a.aseprite")) == os.path.abspath(
            str(tmp_path / "a.aseprite")
        )

    def test_relative_resolves_to_workspace(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASERITE_MCP_WORKSPACE", str(tmp_path))
        assert resolve_path("sprites/a.aseprite") == os.path.join(
            str(tmp_path), "sprites", "a.aseprite"
        )

    def test_tilde_expansion(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ASERITE_MCP_WORKSPACE", str(tmp_path))
        home = os.path.expanduser("~")
        assert resolve_path("~/x.aseprite").startswith(home)


class TestPrepareFilename:
    def test_no_filename_no_active_file(self):
        with pytest.raises(ToolError, match="no active file"):
            prepare_filename("")

    def test_missing_file_returns_hint(self, tmp_path):
        with pytest.raises(ToolError) as error:
            prepare_filename(str(tmp_path / "nope.aseprite"))
        assert FILE_NOT_FOUND_HINT in str(error.value)

    def test_existing_file_anchors(self, tmp_path):
        target = tmp_path / "real.aseprite"
        target.write_bytes(b"x")
        path = prepare_filename(str(target))
        assert path == str(target)
        assert get_active_file() == str(target)

    def test_active_file_fallback(self, tmp_path):
        target = tmp_path / "real.aseprite"
        target.write_bytes(b"x")
        prepare_filename(str(target))
        # Omit filename: falls back to the anchored absolute path.
        path = prepare_filename("")
        assert path == str(target)

    def test_traversal_rejected(self, tmp_path):
        with pytest.raises(ToolError, match="traversal"):
            prepare_filename(str(tmp_path / ".." / "evil.aseprite"))

    def test_output_path_must_exist_false_no_anchor(self, tmp_path):
        out = tmp_path / "new.png"
        path = prepare_filename(str(out), must_exist=False, anchor=False)
        assert path == str(out)
        assert get_active_file() is None

    def test_anchor_false_keeps_previous_active_file(self, tmp_path):
        target = tmp_path / "real.aseprite"
        target.write_bytes(b"x")
        prepare_filename(str(target))
        prepare_filename(str(tmp_path / "out.png"), must_exist=False, anchor=False)
        assert get_active_file() == str(target)


class TestCreateCanvasAnchoring:
    """create_canvas must only anchor the active file after a real success."""

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.delenv("ASERITE_MCP_WORKSPACE", raising=False)
        import aseprite_mcp.core.state as state

        state._active_file = None
        yield
        state._active_file = None

    def test_relative_filename_rejected(self):
        from aseprite_mcp.tools import canvas as canvas_mod

        with pytest.raises(ToolError, match="ABSOLUTE"):
            _run(canvas_mod.create_canvas(8, 8, filename="sprites/c.aseprite"))
        assert get_active_file() is None

    def test_failure_does_not_anchor(self, monkeypatch, tmp_path):
        from aseprite_mcp.tools import canvas as canvas_mod

        async def fail(*args, **kwargs):
            raise ToolError("boom")
        monkeypatch.setattr(canvas_mod, "execute_edit_script", fail)
        with pytest.raises(ToolError, match="boom"):
            _run(canvas_mod.create_canvas(8, 8, filename=str(tmp_path / "c.aseprite")))
        assert get_active_file() is None

    def test_success_anchors(self, monkeypatch, tmp_path):
        from aseprite_mcp.tools import canvas as canvas_mod

        target = tmp_path / "c.aseprite"
        result = _run(canvas_mod.create_canvas(8, 8, filename=str(target)))
        assert "anchored" in result
        assert get_active_file() == os.path.abspath(str(target))


class TestRunLuaScriptFallback:
    """run_lua_script with no filename should open the active file."""

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.delenv("ASERITE_MCP_WORKSPACE", raising=False)
        import aseprite_mcp.core.state as state

        state._active_file = None
        yield
        state._active_file = None

    def test_uses_active_file_when_omitted(self, monkeypatch, tmp_path):
        from aseprite_mcp.tools import script as script_mod

        target = tmp_path / "real.aseprite"
        target.write_bytes(b"x")
        prepare_filename(str(target))

        seen = {}

        async def fake_execute(script, filename=None):
            seen["filename"] = filename
            return "OK"

        monkeypatch.setattr(script_mod.AsepriteCommand, "execute_lua_script", fake_execute)
        result = _run(script_mod.run_lua_script("print(1)"))
        assert "OK" in result
        assert seen["filename"] == str(target)

    def test_no_file_runs_without_sprite(self, monkeypatch):
        from aseprite_mcp.tools import script as script_mod

        seen = {}

        async def fake_execute(script, filename=None):
            seen["filename"] = filename
            return "OK"

        monkeypatch.setattr(script_mod.AsepriteCommand, "execute_lua_script", fake_execute)
        result = _run(script_mod.run_lua_script("print(1)"))
        assert "OK" in result
        assert seen["filename"] is None
