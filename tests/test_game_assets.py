"""Game assets: lines, part animation, tiles, light, and animation export. No Aseprite
needed."""

from __future__ import annotations

import asyncio
import base64
import struct
import zlib

import pytest

from aseprite_claude_connector import light, lines, rig, tiles
from aseprite_claude_connector.oklab import to_lab, to_rgb
from aseprite_claude_connector.raster import Raster, encode_apng, encode_gif

INK, RED = (20, 20, 30), (200, 60, 50)


def blank(w, h):
    return bytearray(w * h * 4)


def put(buf, w, x, y, c):
    buf[(y * w + x) * 4 : (y * w + x) * 4 + 4] = bytes((*c, 255))


def opaque(r: Raster):
    return {(n % r.width, n // r.width) for n in range(r.width * r.height) if r.rgba[n * 4 + 3]}


def test_oklab_round_trips():
    for c in [(0, 0, 0), (255, 255, 255), (12, 200, 99), (240, 20, 140)]:
        assert to_rgb(to_lab(c)) == c


# --- lines ------------------------------------------------------------------------


def test_a_thick_stroke_thins_to_one_pixel():
    w, h = 20, 8
    buf = blank(w, h)
    for x in range(2, 18):
        for y in (3, 4):
            put(buf, w, x, y, INK)
    out, info = lines.clean_lines(Raster(w, h, bytes(buf)))
    assert info["thinned_pixels"] > 0
    for x in range(4, 16):
        assert sum((x, y) in opaque(out) for y in range(h)) == 1


def test_a_doubled_corner_is_removed():
    w, h = 6, 6
    buf = blank(w, h)
    for x, y in ((1, 1), (2, 1), (2, 2), (3, 2)):  # an L step: (2, 1) is the doubled corner
        put(buf, w, x, y, INK)
    out, info = lines.clean_lines(Raster(w, h, bytes(buf)), thin=False)
    assert info["corner_pixels"] == 1
    assert len(opaque(out)) == 3


def test_kept_line_pixels_keep_their_colour():
    w, h = 10, 3
    buf = blank(w, h)
    for x in range(1, 9):
        put(buf, w, x, 1, RED)
    out, _ = lines.clean_lines(Raster(w, h, bytes(buf)))
    assert out.rgba == bytes(buf)


# --- part animation ---------------------------------------------------------------


def _bar():
    w, h = 30, 30
    buf = blank(w, h)
    for y in range(14, 16):
        for x in range(10, 22):
            put(buf, w, x, y, RED)
    return Raster(w, h, bytes(buf))


def test_no_pose_leaves_a_part_exactly_as_drawn():
    part = rig.Part(_bar())
    assert rig.render(part, rig.world("bar", {}, {"bar": (10, 15)}, {})).rgba == _bar().rgba


def test_a_quarter_turn_stands_the_bar_up_without_new_colours():
    part = rig.Part(_bar())
    out = rig.render(part, rig.world("bar", {"bar": (90, 0, 0)}, {"bar": (16, 15)}, {}))
    xs = {x for x, _ in opaque(out)}
    ys = {y for _, y in opaque(out)}
    assert max(ys) - min(ys) > max(xs) - min(xs)
    assert {out.rgba[i : i + 3] for i in range(0, len(out.rgba), 4) if out.rgba[i + 3]} == {
        bytes(RED)
    }


def test_a_child_follows_its_parent():
    pivots = {"arm": (10.0, 15.0), "hand": (21.0, 15.0)}
    moved = rig.world("hand", {"arm": (0, 5, 0)}, pivots, {"hand": "arm"})
    assert moved[2] == pytest.approx(5)  # the hand moved with the arm


def test_poses_ease_between_keys_and_loop_back():
    keys = [{"frame": 1, "angle": 0}, {"frame": 5, "angle": 40}]
    assert rig.pose_at(keys, 3, 8, True, "linear")[0] == pytest.approx(20)
    assert rig.pose_at(keys, 7, 8, True, "linear")[0] == pytest.approx(20)
    assert rig.pose_at(keys, 7, 8, False, "linear")[0] == pytest.approx(40)


# --- tiles ------------------------------------------------------------------------


def test_there_are_47_blob_tiles():
    masks = tiles.blob_masks()
    assert len(masks) == 47
    assert masks[0] == 255  # the full tile comes first


def _speckle(size):
    buf = blank(size, size)
    for y in range(size):
        for x in range(size):
            put(buf, size, x, y, (40 + (x * 7 + y * 13) % 60, 120, 50))
    return Raster(size, size, bytes(buf))


def test_seamless_keeps_the_size_and_colours():
    src = _speckle(16)
    out = tiles.seamless(src)
    assert (out.width, out.height) == (16, 16)
    colours = {src.rgba[i : i + 3] for i in range(0, len(src.rgba), 4)}
    assert {out.rgba[i : i + 3] for i in range(0, len(out.rgba), 4)} <= colours


def test_autotiles_lay_out_every_tile():
    sheet, masks = tiles.autotiles(_speckle(8), 8)
    assert (sheet.width, sheet.height) == (64, 48)
    full = {(x, y) for y in range(8) for x in range(8)}
    assert (
        opaque(Raster(8, 8, b"".join(sheet.rgba[y * 256 : y * 256 + 32] for y in range(8)))) == full
    )
    lone = masks.index(0)
    ox, oy = (lone % 8) * 8, (lone // 8) * 8
    corner = sheet.rgba[(oy * 64 + ox) * 4 + 3]
    assert corner == 0  # an isolated tile's corner is base, clear here


def test_the_godot_tileset_names_its_peering_bits():
    text = tiles.godot_tileset("res://t.png", 16, [255, 0], 8, "Grass")
    assert "terrain_set_0/mode = 0" in text
    assert "0:0/0/terrains_peering_bit/top_left_corner = 0" in text
    assert "1:0/0/terrains_peering_bit" not in text


def test_the_rule_tile_skips_corners_without_both_sides():
    rules = tiles._rules_for(tiles.N)
    assert (0, 1, 1) in rules  # north is this tile
    assert all((x, y) != (1, 1) for x, y, _ in rules)  # no NE rule without east


# --- light ------------------------------------------------------------------------


def test_night_is_darker_and_bluer():
    c = (180, 160, 120)
    night = to_lab(light.relight_colour(c, "night"))
    day = to_lab(c)
    assert night[0] < day[0] and night[2] < day[2]


def test_relighting_keeps_the_colour_count():
    src = _speckle(8)
    out = light.relight(src, "sunset")
    before = {src.rgba[i : i + 3] for i in range(0, len(src.rgba), 4)}
    after = {out.rgba[i : i + 3] for i in range(0, len(out.rgba), 4)}
    assert len(after) <= len(before)


def test_a_glow_stays_brighter_than_the_dark_around_it():
    src = Raster(9, 1, bytes((120, 120, 120, 255)) * 9)
    out = light.relight(src, "night", glows=[(0.5, 0.5, 4)])
    assert to_lab(tuple(out.rgba[0:3]))[0] > to_lab(tuple(out.rgba[32:35]))[0]


def test_a_normal_map_points_outward_with_green_up():
    w = h = 21
    buf = blank(w, h)
    for y in range(h):
        for x in range(w):
            if (x - 10) ** 2 + (y - 10) ** 2 <= 81:
                put(buf, w, x, y, (150, 150, 150))
    nm = light.normal_map(Raster(w, h, bytes(buf)), bevel=6, detail=0)

    def px(x, y):
        return nm.rgba[(y * w + x) * 4 : (y * w + x) * 4 + 4]

    assert px(2, 10)[0] < 128  # left edge faces left
    assert px(18, 10)[0] > 128  # right edge faces right
    assert px(10, 2)[1] > 128  # top edge faces up
    assert px(10, 18)[1] < 128  # bottom edge faces down
    assert px(0, 0)[3] == 0


# --- animation export -------------------------------------------------------------


def _frames():
    return [Raster(2, 1, bytes((r, 0, 0, 255, 0, 0, 0, 0))) for r in (255, 100)]


def test_an_apng_has_one_frame_control_per_frame():
    data = encode_apng(_frames(), [100, 250])
    assert data.startswith(b"\x89PNG")
    assert data.count(b"fcTL") == 2 and b"acTL" in data
    pos = data.index(b"fcTL") + 4
    assert struct.unpack(">HH", data[pos + 20 : pos + 24]) == (100, 1000)


def test_a_gif_takes_a_delay_per_frame():
    data = encode_gif(_frames(), [100, 250])
    assert b"!\xf9\x04\x00\x0a\x00" in data and b"!\xf9\x04\x00\x19\x00" in data


def _server(monkeypatch, canvas, ran):
    from aseprite_claude_connector.server import build_server
    from aseprite_claude_connector.tools import finish, scene
    from aseprite_claude_connector.tools import light as light_tools
    from aseprite_claude_connector.tools import rig as rig_tools
    from aseprite_claude_connector.tools import tiles as tile_tools

    def fake_run(lua, **kw):
        ran.append((lua, kw))
        if "app.activeLayer" in lua:
            return {"name": "Art", "group": False, "frame": 1, "rgb": True}
        if "names[#names + 1] = l.name" in lua and "walk(s.layers)" in lua:
            return {"layers": ["Art"], "frames": 1, "frame": 1}
        if kw.get("mutates"):
            return {"layer": "Art"}
        packed = base64.b64encode(canvas.rgba).decode()
        return {"rgba": packed, "width": canvas.width, "height": canvas.height, "frame": 1}

    for module in (scene, finish, light_tools, rig_tools, tile_tools):
        monkeypatch.setattr(module, "run", fake_run, raising=False)
    monkeypatch.setattr(
        finish,
        "frames_of",
        lambda **kw: {"frames": _frames(), "durations": [100, 250]},
    )
    return build_server()


def test_export_animation_writes_an_apng(monkeypatch, tmp_path):
    mcp = _server(monkeypatch, _bar(), [])
    out = tmp_path / "a.png"
    asyncio.run(mcp.call_tool("export_animation", {"path": str(out), "scale": 2}))
    data = out.read_bytes()
    assert data.count(b"fcTL") == 2
    ihdr = data.index(b"IHDR") + 4
    assert struct.unpack(">II", data[ihdr : ihdr + 8]) == (4, 2)


def test_export_animation_refuses_other_formats(monkeypatch, tmp_path):
    mcp = _server(monkeypatch, _bar(), [])
    with pytest.raises(Exception, match=".gif or .png"):
        asyncio.run(mcp.call_tool("export_animation", {"path": str(tmp_path / "a.webp")}))


def test_animate_parts_is_one_step_for_every_part(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, _bar(), ran)
    poses = [{"frame": 1, "part": "Arm", "angle": 0}, {"frame": 3, "part": "Arm", "angle": 30}]
    asyncio.run(mcp.call_tool("animate_parts", {"poses": poses, "frames": 4}))
    lua, kw = next((lua, kw) for lua, kw in ran if kw.get("mutates"))
    assert kw["undo_label"] == "Animate parts"
    assert "IMAGE_W = 120" in lua  # four 30-pixel frames


def test_relight_writes_copies_and_hides_the_originals(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, _bar(), ran)
    asyncio.run(mcp.call_tool("relight_scene", {"time": "night"}))
    lua, kw = next((lua, kw) for lua, kw in ran if kw.get("mutates"))
    assert 'SUFFIX = " (night)"' in lua and "HIDE = true" in lua


def test_autotiles_write_a_godot_tileset(monkeypatch, tmp_path):
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    mcp = _server(monkeypatch, _speckle(16), [])
    asyncio.run(
        mcp.call_tool(
            "make_autotiles",
            {"fill_layer": "Art", "size": 8, "name": "grass", "game_dir": str(project)},
        )
    )
    tres = (project / "sprites" / "grass.tres").read_text(encoding="utf-8")
    assert 'path="res://sprites/grass.png"' in tres
    png = (project / "sprites" / "grass.png").read_bytes()
    assert png.startswith(b"\x89PNG") and zlib.decompress(png[png.index(b"IDAT") + 4 : -16])
