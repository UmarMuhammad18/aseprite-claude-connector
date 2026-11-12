"""Atmosphere: skies, water, glows, and rim light. No Aseprite needed."""

from __future__ import annotations

import asyncio
import base64

import pytest

from aseprite_claude_connector import atmosphere
from aseprite_claude_connector.raster import Raster


def px(r: Raster, x: int, y: int) -> tuple[int, ...]:
    i = (y * r.width + x) * 4
    return tuple(r.rgba[i : i + 4])


def colours(r: Raster) -> set[bytes]:
    return {r.rgba[i : i + 3] for i in range(0, len(r.rgba), 4) if r.rgba[i + 3]}


def brightness(r: Raster, x: int, y: int) -> int:
    return sum(px(r, x, y)[:3])


def block(w, h, box, colour=(40, 60, 90)):
    buf = bytearray(w * h * 4)
    x0, y0, x1, y1 = box
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            buf[(y * w + x) * 4 : (y * w + x) * 4 + 4] = bytes((*colour, 255))
    return Raster(w, h, bytes(buf))


# --- sky ----------------------------------------------------------------------------


@pytest.mark.parametrize("time", list(atmosphere.SKIES))
def test_a_sky_fills_the_picture_from_a_small_palette(time):
    sky = atmosphere.sky(64, 40, time, clouds=0.5)
    assert all(sky.rgba[i + 3] == 255 for i in range(0, len(sky.rgba), 4))
    look = atmosphere.SKIES[time]
    allowed = len(look["sky"]) + len(look["hot"]) + len(look["cloud"]) + 3  # and the star tones
    assert len(colours(sky)) <= allowed


def test_the_sky_is_brightest_round_the_sun():
    sky = atmosphere.sky(96, 60, "sunset", horizon=50, sun=(70, 48), clouds=0, stars=0)
    assert brightness(sky, 70, 40) > brightness(sky, 5, 40) > brightness(sky, 5, 2)


def test_the_same_seed_paints_the_same_sky():
    a = atmosphere.sky(48, 32, "night", clouds=0.6, seed=4)
    assert a.rgba == atmosphere.sky(48, 32, "night", clouds=0.6, seed=4).rgba
    assert a.rgba != atmosphere.sky(48, 32, "night", clouds=0.6, seed=5).rgba


def test_an_unknown_time_is_refused():
    with pytest.raises(ValueError, match="time must be one of"):
        atmosphere.sky(8, 8, "teatime")


# --- water --------------------------------------------------------------------------


def _bands():
    """Red over blue, so a mirror shows blue first and then red."""
    w, h = 24, 12
    buf = bytearray()
    for y in range(h):
        buf += bytes((200, 30, 30, 255) if y < 6 else (30, 30, 200, 255)) * w
    return Raster(w, h, bytes(buf))


def test_still_water_mirrors_what_is_above_it():
    water = atmosphere.reflection(_bands(), 10, ripple=0, depth=0)
    assert px(water, 5, 0)[:3] == (30, 30, 200)  # nearest the horizon: the row just above
    assert px(water, 5, 9)[:3] == (200, 30, 30)  # further down: higher up the picture


def test_depth_sinks_the_reflection_into_the_tint():
    shallow = atmosphere.reflection(_bands(), 10, ripple=0, depth=0)
    deep = atmosphere.reflection(_bands(), 10, ripple=0, depth=1, tint=(0, 0, 0))
    assert brightness(deep, 5, 9) < brightness(shallow, 5, 9)


def test_ripples_loop_back_to_the_first_frame():
    frames = [atmosphere.reflection(_bands(), 10, n, 8) for n in range(9)]
    assert frames[0].rgba == frames[8].rgba
    assert frames[0].rgba != frames[3].rgba


def test_a_sun_path_runs_down_the_water_under_the_sun():
    water = atmosphere.reflection(_bands(), 10, ripple=0, depth=0, sun_x=12)
    lit = bytes((255, 240, 184))
    xs = {
        (i // 4) % water.width for i in range(0, len(water.rgba), 4) if water.rgba[i : i + 3] == lit
    }
    assert xs and all(abs(x - 12) < 10 for x in xs)


# --- glow ---------------------------------------------------------------------------


def test_a_glow_fades_out_from_its_centre():
    pool = atmosphere.glow(60, 60, (30, 30), 20, (255, 140, 60), strength=1.0)
    assert px(pool, 30, 30)[3] > px(pool, 40, 30)[3] > 0
    assert px(pool, 55, 30)[3] == 0
    assert colours(pool) == {bytes((255, 140, 60))}


def test_open_air_takes_less_light_than_the_ground():
    ground = block(60, 60, (0, 30, 59, 59))
    pool = atmosphere.glow(60, 60, (30, 30), 20, (255, 140, 60), 1.0, lit=ground, air=0.2)
    assert px(pool, 30, 33)[3] > px(pool, 30, 27)[3] > 0


def test_a_flickering_glow_loops():
    a = atmosphere.glow(40, 40, (20, 20), 12, (255, 140, 60), flicker=1, phase=0.0)
    b = atmosphere.glow(40, 40, (20, 20), 12, (255, 140, 60), flicker=1, phase=0.25)
    c = atmosphere.glow(40, 40, (20, 20), 12, (255, 140, 60), flicker=1, phase=1.0)
    assert a.rgba == c.rgba and a.rgba != b.rgba


# --- rim light ----------------------------------------------------------------------


def test_only_the_edge_facing_the_light_is_lit():
    rim = atmosphere.rim_light(block(20, 20, (6, 6, 13, 13)), (100, 10), (255, 176, 112))
    lit = {(i // 4 % 20, i // 4 // 20) for i in range(0, len(rim.rgba), 4) if rim.rgba[i + 3]}
    assert lit and {x for x, _ in lit} == {13}  # the right-hand column, toward the light


def test_a_wider_rim_mixes_into_the_art():
    shape = block(20, 20, (6, 6, 13, 13))
    one = atmosphere.rim_light(shape, (100, 10), (255, 176, 112))
    two = atmosphere.rim_light(shape, (100, 10), (255, 176, 112), width=2)
    assert len(colours(two)) == 2 and len(colours(one)) == 1


def test_a_fire_only_lights_what_is_near_it():
    shape = block(60, 20, (0, 8, 59, 12))
    rim = atmosphere.rim_light(shape, (2, 0), (255, 140, 60), radius=15)
    xs = {i // 4 % 60 for i in range(0, len(rim.rgba), 4) if rim.rgba[i + 3]}
    assert xs and max(xs) < 20


def test_bounds_and_crop_keep_just_the_pixels():
    shape = block(20, 20, (6, 7, 13, 12))
    box = atmosphere.bounds([shape])
    assert box == (6, 7, 13, 12)
    assert (atmosphere.cropped(shape, box).width, atmosphere.cropped(shape, box).height) == (8, 6)
    assert atmosphere.bounds([Raster(4, 4, bytes(64))]) is None


# --- the tools ----------------------------------------------------------------------


def _server(monkeypatch, canvas, ran, frames=3):
    from aseprite_claude_connector.server import build_server
    from aseprite_claude_connector.tools import atmosphere as tools

    def fake_run(lua, **kw):
        ran.append((lua, kw))
        if kw.get("mutates"):
            return {"layer": "New", "frames": frames}
        if "packed[#packed + 1] = pack(img)" in lua:
            only = "ONLY = nil" not in lua
            rows = canvas.height
            if "BOTTOM = nil" not in lua:
                rows = int(lua.split("BOTTOM = ")[1].split("\n")[0]) + 1
            packed = base64.b64encode(canvas.rgba[: canvas.width * rows * 4]).decode()
            return {
                "frames": [packed] * (1 if only else frames),
                "width": canvas.width,
                "height": rows,
            }
        return {"width": canvas.width, "height": canvas.height, "frames": frames, "frame": 1}

    monkeypatch.setattr(tools, "run", fake_run)
    return build_server()


def _edit(ran):
    return next((lua, kw) for lua, kw in ran if kw.get("mutates"))


def test_paint_sky_goes_to_the_bottom_on_every_frame(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, block(32, 20, (0, 0, 31, 19)), ran)
    asyncio.run(mcp.call_tool("paint_sky", {"time": "night", "clouds": 0}))
    lua, kw = _edit(ran)
    assert 'PLACE = "bottom"' in lua and 'FRAMES = "1,2,3"' in lua and "COLUMNS = 1" in lua
    assert kw["undo_label"] == "Paint sky: night" and kw["capped"] is False


def test_reflect_in_water_writes_only_the_rows_below_the_horizon(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, block(32, 20, (0, 0, 31, 19)), ran)
    asyncio.run(mcp.call_tool("reflect_in_water", {"horizon": 11, "layers": ["Sky"]}))
    lua, kw = _edit(ran)
    assert "TOP = 12" in lua and "H = 8" in lua and "COLUMNS = 3" in lua
    assert 'PLACE = "above"' in lua and 'NAMES = "Sky"' in lua
    assert kw["undo_label"] == "Reflect in water"


def test_add_glow_sends_only_its_own_area_and_adds_light(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, block(64, 64, (0, 0, 63, 63)), ran)
    asyncio.run(mcp.call_tool("add_glow", {"x": 32, "y": 32, "radius": 10}))
    lua, _ = _edit(ran)
    assert "ADD = true" in lua and "COLUMNS = 1" in lua
    assert int(lua.split("\nlocal W = ")[1].split("\n")[0]) < 30


def test_a_flickering_glow_gets_a_picture_for_each_frame(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, block(64, 64, (0, 0, 63, 63)), ran)
    asyncio.run(mcp.call_tool("add_glow", {"x": 32, "y": 32, "radius": 10, "flicker": 1}))
    assert "COLUMNS = 3" in _edit(ran)[0]


def test_add_rim_light_names_its_layer_after_the_source(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, block(32, 20, (8, 6, 15, 13)), ran)
    asyncio.run(mcp.call_tool("add_rim_light", {"layer": "Knight", "light": [200, 10]}))
    lua, kw = _edit(ran)
    assert 'NAME = "Knight (rim)"' in lua and 'NAMES = "Knight"' in lua
    assert kw["undo_label"] == "Add rim light"


def test_a_layer_with_no_edge_toward_the_light_is_refused(monkeypatch):
    from mcp.server.fastmcp.exceptions import ToolError

    mcp = _server(monkeypatch, Raster(16, 16, bytes(16 * 16 * 4)), [])
    with pytest.raises(ToolError, match="no edge"):
        asyncio.run(mcp.call_tool("add_rim_light", {"layer": "Empty", "light": [200, 10]}))
