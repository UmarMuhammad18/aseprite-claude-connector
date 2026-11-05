"""Building and animating scenes: no Aseprite needed."""

from __future__ import annotations

import asyncio
import base64

import pytest

from aseprite_claude_connector.raster import Raster
from aseprite_claude_connector.scene import (
    ambient_frames,
    cleaned,
    extended,
    part,
    particle_frames,
    split_regions,
)

DARK, LIGHT = (30, 30, 30), (220, 220, 220)


def solid(width, height, color, alpha=255):
    return Raster(width, height, bytes((*color, alpha)) * (width * height))


def stripes(width, height):
    """Vertical stripes, so any sideways motion shows."""
    rgba = bytearray()
    for _ in range(height):
        for x in range(width):
            rgba += bytes((DARK if x % 4 < 2 else LIGHT) + (255,))
    return Raster(width, height, bytes(rgba))


def halves(width, height):
    """Dark on the left, light on the right."""
    rgba = bytearray()
    for _ in range(height):
        for x in range(width):
            rgba += bytes((DARK if x < width // 2 else LIGHT) + (255,))
    return Raster(width, height, bytes(rgba))


def colours(r: Raster):
    return {r.rgba[i : i + 3] for i in range(0, len(r.rgba), 4) if r.rgba[i + 3]}


def test_wind_moves_pixels_without_new_colours():
    src = stripes(16, 8)
    frames = ambient_frames(src, 8, wind=1, wavelength=8)
    assert len(frames) == 8
    assert any(f.rgba != src.rgba for f in frames)
    assert all(colours(f) <= colours(src) for f in frames)


def test_wind_never_opens_a_gap_at_a_parts_edge():
    rgba = bytearray(stripes(16, 4).rgba)
    for y in range(4):
        for x in range(8, 16):
            rgba[(y * 16 + x) * 4 + 3] = 0  # the right half belongs to another layer
    src = Raster(16, 4, bytes(rgba))
    for f in ambient_frames(src, 8, wind=2, wavelength=8):
        for y in range(4):
            for x in range(8):
                assert f.rgba[(y * 16 + x) * 4 + 3] == 255


def test_a_glint_brightens_and_then_rests():
    src = solid(24, 8, (150, 150, 150))
    frames = ambient_frames(src, 10, glint=1)
    assert any(f.rgba != src.rgba for f in frames[:6])
    assert frames[-1].rgba == src.rgba  # it crosses in the first 60% of the loop


@pytest.mark.parametrize("kind", ["motes", "snow", "rain", "embers"])
def test_particles_loop(kind):
    frames = particle_frames(32, 24, 12, kind, 10)
    assert len(frames) == 12
    assert all(len(f.rgba) == 32 * 24 * 4 for f in frames)
    assert any(any(f.rgba[3::4]) for f in frames)


def test_an_unknown_particle_is_refused():
    with pytest.raises(ValueError):
        particle_frames(8, 8, 4, "confetti", 3)


def test_parts_stop_at_their_edge():
    src = halves(12, 6)
    labels = split_regions(src, [(1, 1, 0), (10, 4, 1)])
    assert labels[0] == 0 and labels[11] == 1
    left = part(src, labels, 0)
    assert colours(left) == {bytes(DARK)}


def test_a_seed_on_a_clear_pixel_is_refused():
    with pytest.raises(ValueError):
        split_regions(solid(4, 4, DARK, alpha=0), [(1, 1, 0)])


def test_extending_continues_the_texture_without_new_colours():
    src = stripes(12, 8)
    out = extended(src, 0, 10, 0, 4, patch=4)
    assert (out.width, out.height) == (22, 12)
    assert colours(out) <= colours(src)
    assert all(out.rgba[i + 3] == 255 for i in range(0, len(out.rgba), 4))
    # the original is untouched
    assert out.rgba[: 12 * 4] == src.rgba[: 12 * 4]


def test_cleaning_merges_a_close_speck_and_keeps_a_standout_one():
    rgba = bytearray(solid(5, 5, DARK).rgba)
    rgba[(1 * 5 + 1) * 4 : (1 * 5 + 1) * 4 + 3] = bytes((36, 36, 36))  # noise
    rgba[(3 * 5 + 3) * 4 : (3 * 5 + 3) * 4 + 3] = bytes((250, 240, 120))  # a flower
    out, info = cleaned(Raster(5, 5, bytes(rgba)), firm_edges=False)
    assert out.rgba[(1 * 5 + 1) * 4 : (1 * 5 + 1) * 4 + 3] == bytes(DARK)
    assert out.rgba[(3 * 5 + 3) * 4 : (3 * 5 + 3) * 4 + 3] == bytes((250, 240, 120))
    assert info["merged_pixels"] == 1


def test_firm_edges_darken_the_shadow_side_with_an_existing_colour():
    rgba = bytearray()
    shade = (60, 60, 60)
    for y in range(6):
        for x in range(8):
            c = shade if x == 3 and y == 0 else DARK if x < 4 else LIGHT
            rgba += bytes((*c, 255))
    out, info = cleaned(Raster(8, 6, bytes(rgba)), min_region=2)
    assert info["firmed_pixels"] > 0
    assert colours(out) <= colours(Raster(8, 6, bytes(rgba)))


def _server(monkeypatch, ran, canvas):
    from aseprite_claude_connector.server import build_server
    from aseprite_claude_connector.tools import scene

    def fake_run(lua, **kw):
        ran.append((lua, kw))
        if "app.activeLayer" in lua:
            return {"name": "Scene", "group": False, "frame": 1, "rgb": True}
        if "#app.activeSprite.frames" in lua:
            return 2
        if kw.get("mutates"):
            return {"layer": "Scene"}
        packed = base64.b64encode(canvas.rgba).decode()
        return {"rgba": packed, "width": canvas.width, "height": canvas.height, "frame": 1}

    monkeypatch.setattr(scene, "run", fake_run)
    return build_server()


def _edit(ran):
    return next((lua, kw) for lua, kw in ran if kw.get("mutates"))


def test_ambient_motion_is_one_undo_step_with_its_frames(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, ran, stripes(8, 4))
    asyncio.run(mcp.call_tool("ambient_motion", {"wind": 1, "frames": 4, "particles": "snow"}))
    lua, kw = _edit(ran)
    assert kw["undo_label"] == "Ambient motion"
    assert "IMAGE_W = 32" in lua and "IMAGE_H = 8" in lua  # 4 frames, plus a particle row
    assert 'PARTICLES_NAME = "Snow"' in lua


def test_ambient_motion_needs_something_to_do(monkeypatch):
    mcp = _server(monkeypatch, [], stripes(8, 4))
    with pytest.raises(Exception, match="nothing to animate"):
        asyncio.run(mcp.call_tool("ambient_motion", {}))


def test_split_makes_a_layer_per_name(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, ran, halves(8, 4))
    seeds = [{"name": "Left", "x": 0, "y": 0}, {"name": "Right", "x": 7, "y": 3}]
    asyncio.run(mcp.call_tool("split_into_layers", {"seeds": seeds}))
    lua, kw = _edit(ran)
    assert 'NAMES = "Left\\nRight"' in lua
    assert "IMAGE_W = 16" in lua


def test_extend_skips_the_cap_because_it_cannot_lose_pixels(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, ran, stripes(8, 4))
    asyncio.run(mcp.call_tool("extend_scene", {"right": 4}))
    lua, kw = _edit(ran)
    assert kw["capped"] is False
    assert "RIGHT = 4" in lua and "IMAGE_W = 12" in lua


def test_clean_every_frame_in_one_step(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, ran, stripes(8, 4))
    asyncio.run(mcp.call_tool("clean_pixel_art", {"all_frames": True}))
    lua, _ = _edit(ran)
    assert 'FRAMES = "1,2"' in lua


def test_new_layers_and_frames_are_exempt_from_the_cap():
    from aseprite_claude_connector.lua import build_lua

    lua = build_lua("return 1", mutates=True, max_pixels=10)
    assert "__isFresh" in lua
    assert "__oldLayers, __frames" in lua
