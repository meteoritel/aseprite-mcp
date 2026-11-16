"""Lua escape hatch (script.py)."""
from conftest import failure, run

from aseprite_mcp.tools import script


def test_run_lua_script_returns_printed_output(sprite):
    out = run(script.run_lua_script(script='local spr = app.activeSprite print("size=" .. spr.width .. "x" .. spr.height)', filename=sprite))
    assert "size=32x32" in out


def test_run_lua_script_rejects_empty():
    assert failure(script.run_lua_script(script="  ")) == "Script cannot be empty"
