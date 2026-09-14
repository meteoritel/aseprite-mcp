"""Palette tools (palette.py)."""
import json

from conftest import ok, run

from aseprite_mcp.tools import palette


def test_list_palette_presets():
    presets = json.loads(run(palette.list_palette_presets()))
    assert "dawnbringer16" in presets
    assert len(presets["gameboy"]) == 4


def test_apply_palette_preset(sprite):
    result = ok(run(palette.apply_palette_preset(filename=sprite, preset="dawnbringer16")))
    assert "16 colors" in result


def test_apply_palette_preset_rejects_unknown(sprite):
    result = run(palette.apply_palette_preset(filename=sprite, preset="nonsense"))
    assert result.startswith("Unknown preset")


def test_quantize_to_palette(sprite):
    result = ok(run(palette.quantize_to_palette(filename=sprite)))
    assert "Quantized" in result


def test_generate_color_ramp():
    ramp = json.loads(run(palette.generate_color_ramp(base_color="#D04648", steps=5)))
    assert len(ramp) == 5
    assert all(c.startswith("#") and len(c) == 7 for c in ramp)


def test_color_mode_roundtrip(sprite):
    ok(run(palette.set_color_mode(filename=sprite, mode="indexed")))
    ok(run(palette.set_color_mode(filename=sprite, mode="rgb")))
