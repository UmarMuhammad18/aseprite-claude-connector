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


# --- drifting clouds, mountains, fire -----------------------------------------------


def changed(a: Raster, b: Raster) -> int:
    return sum(a.rgba[i : i + 4] != b.rgba[i : i + 4] for i in range(0, len(a.rgba), 4))


def test_drifting_clouds_loop_without_a_jump():
    frames = atmosphere.cloud_frames(96, 60, 8, 8, clouds=0.7)
    assert (frames[0].width, frames[0].height) == (96, 61)
    steps = [changed(frames[i], frames[(i + 1) % 8]) for i in range(8)]
    assert min(steps) > 0
    assert steps[-1] <= max(steps[:-1]) * 1.5  # the seam is a step like the others


def test_clouds_leave_the_clear_sky_empty():
    frame = atmosphere.cloud_frames(96, 60, 4, 4, clouds=0.5)[0]
    alphas = {frame.rgba[i + 3] for i in range(0, len(frame.rgba), 4)}
    assert alphas == {0, 255}


def test_mountains_stand_on_the_horizon_and_leave_the_sky_clear():
    land = atmosphere.mountains(120, 80, 60, "sunset", size=0.5)
    assert all(px(land, x, 60)[3] == 255 for x in range(120))
    assert all(px(land, x, 61)[3] == 0 for x in range(120))
    assert all(px(land, x, 20)[3] == 0 for x in range(120))  # above the tallest peak


def test_ranges_dip_to_let_the_sun_through():
    def top(land, x):
        return next(y for y in range(land.height) if px(land, x, y)[3])

    flat = atmosphere.mountains(240, 80, 60, "sunset", trees=False)
    dipped = atmosphere.mountains(240, 80, 60, "sunset", sun=(120, 58), trees=False)
    assert top(dipped, 120) > top(flat, 120)
    assert top(dipped, 5) == top(flat, 5)


@pytest.mark.parametrize("time", list(atmosphere.LANDS))
def test_mountains_keep_to_their_palette(time):
    tones, caps = atmosphere.LANDS[time]
    allowed = {bytes(atmosphere._rgb(c)) for row in tones for c in row} | {
        bytes(atmosphere._rgb(c)) for c in caps
    }
    assert colours(atmosphere.mountains(96, 64, 50, time)) <= allowed


def test_a_fire_loops_and_stays_in_its_palette():
    frames, (cx, by) = atmosphere.fire_frames(20, 6, logs=False)
    again, _ = atmosphere.fire_frames(20, 6, logs=False)
    assert [f.rgba for f in frames] == [f.rgba for f in again]
    assert frames[0].rgba != frames[3].rgba
    allowed = {bytes(atmosphere._rgb(c)) for c in atmosphere.FLAMES["fire"]}
    assert colours(frames[0]) <= allowed
    assert px(frames[0], cx, by - 4)[3] == 255  # the heart of the fire, just above its base


def test_wind_carries_the_embers():
    def reach(wind):
        frames, (cx, _) = atmosphere.fire_frames(20, 6, wind=wind, logs=False)
        box = atmosphere.bounds(frames)
        return box[0] - cx, box[2] - cx

    assert reach(-20)[0] < reach(0)[0]
    assert reach(20)[1] > reach(0)[1]


def test_an_unknown_flame_palette_is_refused():
    with pytest.raises(ValueError, match="palette must be one of"):
        atmosphere.fire_frames(20, 4, palette="plaid")


def test_paint_sky_puts_drifting_clouds_on_their_own_layer(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, block(48, 30, (0, 0, 47, 29)), ran)
    asyncio.run(mcp.call_tool("paint_sky", {"horizon": 20, "drift": 3, "clouds": 0.7}))
    lua, kw = _edit(ran)
    assert 'CLOUDS = "Clouds"' in lua and "local sky_picture = load_image()" in lua
    assert "H = 21" in lua and kw["undo_label"] == "Paint sky: sunset"
    assert len([1 for _, k in ran if k.get("mutates")]) == 1  # one undo step for both layers


def test_paint_mountains_goes_above_the_sky_and_sends_only_its_rows(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, block(96, 64, (0, 0, 95, 63)), ran)
    asyncio.run(mcp.call_tool("paint_mountains", {"horizon": 50, "time": "night"}))
    lua, kw = _edit(ran)
    assert 'PLACE = "above"' in lua and 'NAMES = "Sky"' in lua and "LOW = true" in lua
    assert int(lua.split("\nlocal H = ")[1].split("\n")[0]) < 51
    assert kw["undo_label"] == "Paint mountains: night"


def test_add_fire_puts_its_base_where_asked(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, block(96, 64, (0, 0, 95, 63)), ran)
    res = asyncio.run(mcp.call_tool("add_fire", {"x": 40, "y": 50, "height": 20}))
    lua, kw = _edit(ran)
    top = int(lua.split("\nlocal TOP = ")[1].split("\n")[0])
    tall = int(lua.split("\nlocal H = ")[1].split("\n")[0])
    assert 50 <= top + tall - 1 <= 54  # the stones sit a pixel or two under the base
    assert "COLUMNS = 3" in lua and kw["undo_label"] == "Add fire"
    assert '"glow_hint"' in str(res)


def test_mist_is_thickest_along_its_middle_and_loops():
    bands = mist_frames = atmosphere.mist_frames(120, 30, 8, -8, density=0.8)

    def weight(band, y):
        return sum(band.rgba[(y * 120 + x) * 4 + 3] for x in range(120))

    assert weight(bands[0], 15) > weight(bands[0], 4) and weight(bands[0], 0) == 0
    steps = [changed(mist_frames[i], mist_frames[(i + 1) % 8]) for i in range(8)]
    assert min(steps) > 0 and steps[-1] <= max(steps[:-1]) * 1.5


def test_mist_warms_toward_the_sun():
    band = atmosphere.mist_frames(120, 30, density=1.0, sun_x=100)[0]
    assert bytes((255, 217, 160)) in {band.rgba[(15 * 120 + x) * 4 :][:3] for x in range(90, 110)}
    assert bytes((255, 217, 160)) not in {band.rgba[(15 * 120 + x) * 4 :][:3] for x in range(0, 30)}


def test_add_mist_sits_above_the_layer_it_is_given(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, block(96, 64, (0, 0, 95, 63)), ran)
    asyncio.run(
        mcp.call_tool("add_mist", {"y": 40, "thickness": 20, "drift": -3, "above": "Water"})
    )
    lua, kw = _edit(ran)
    assert 'NAMES = "Water"' in lua and "TOP = 30" in lua and "H = 20" in lua
    assert "COLUMNS = 3" in lua and kw["undo_label"] == "Add mist"
