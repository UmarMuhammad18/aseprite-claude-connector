"""Character tools: eyes, parts, bobbing, symbols, consistency, pinning, and setup for
the Claude desktop app. Pure functions, no Aseprite needed."""

from __future__ import annotations

import json
from collections import Counter

from aseprite_claude_connector import setup
from aseprite_claude_connector.character import (
    Grid,
    bobbed,
    drawn_eye,
    eye_style,
    free_pixels,
    merged_palette,
    polygon_mask,
    swung,
    taken,
)
from aseprite_claude_connector.pixelate import background_removed, edge_bits_cleared
from aseprite_claude_connector.raster import Raster
from aseprite_claude_connector.tools import _common

SKIN = (80, 76, 90, 255)
RING = (247, 193, 66, 255)
WHITE = (250, 248, 244, 255)
PUPIL = (24, 22, 28, 255)


def _head(size=40) -> Grid:
    """A grey head with one eye: yellow ring, white, a dark pupil."""
    g = Grid(size, size, [SKIN] * (size * size))
    for x, y in g.cells():
        d = ((x + 0.5 - 20) / 7) ** 2 + ((y + 0.5 - 20) / 7) ** 2
        if d <= 1:
            g.set(x, y, WHITE)
        elif d <= 1.4:
            g.set(x, y, RING)
    for x, y in g.cells():
        if (x - 21) ** 2 + (y - 20) ** 2 <= 6:
            g.set(x, y, PUPIL)
    return g


SOCKET = (20.0, 20.0, 6.5, 6.5)


def _count(g: Grid, colour) -> int:
    return sum(1 for p in g.px if p == colour)


def _centre_of(g: Grid, colour) -> tuple[float, float]:
    pts = [(x, y) for x, y in g.cells() if g.get(x, y) == colour]
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def test_eye_style_reads_the_eye_already_there():
    style = eye_style(_head(), SOCKET)
    assert style["ring"] == RING
    assert style["skin"] == SKIN
    assert style["white"] == WHITE
    assert style["pupil"] == PUPIL


def test_an_eye_looks_where_it_is_told():
    style = eye_style(_head(), SOCKET)
    left = drawn_eye(_head(), SOCKET, style, look=(-3, 0))
    right = drawn_eye(_head(), SOCKET, style, look=(3, 0))
    assert _centre_of(left, PUPIL)[0] < 19 < 21 < _centre_of(right, PUPIL)[0]


def test_lids_cover_the_eye_from_the_top_and_closing_leaves_a_line():
    style = eye_style(_head(), SOCKET)
    open_ = drawn_eye(_head(), SOCKET, style)
    half = drawn_eye(_head(), SOCKET, style, lid=0.5)
    shut = drawn_eye(_head(), SOCKET, style, closed=True)
    assert _count(half, WHITE) < _count(open_, WHITE)
    assert _count(shut, WHITE) == 0
    assert 0 < _count(shut, PUPIL) < 20  # the closed line, not a pupil
    whites = [y for x, y in half.cells() if half.get(x, y) == WHITE]
    assert min(whites) > 16  # the top of the eye is lid now


def test_a_brow_slants_the_lid():
    style = eye_style(_head(), SOCKET)
    angry = drawn_eye(_head(), SOCKET, style, lid=0.35, slant=0.5)

    def top_of_eye(g, x):
        ys = [y for y in range(40) if g.get(x, y) in (WHITE, PUPIL)]
        return min(ys) if ys else 99

    assert top_of_eye(angry, 17) < top_of_eye(angry, 23)  # the lid is lower on the right


def test_a_smile_lifts_a_lower_lid():
    style = eye_style(_head(), SOCKET)
    plain = drawn_eye(_head(), SOCKET, style)
    smiling = drawn_eye(_head(), SOCKET, style, smile=0.3)
    assert _count(smiling, WHITE) + _count(smiling, PUPIL) < _count(plain, WHITE) + _count(
        plain, PUPIL
    )


def test_eye_style_falls_back_when_the_eye_is_hidden():
    g = Grid(40, 40, [SKIN] * 1600)  # nothing there, like eyes behind sunglasses
    style = eye_style(g, SOCKET)
    assert style["white"][0] > 200 and style["pupil"][0] < 60


def test_free_pixels_takes_symbols_but_not_the_body_crossing_the_box():
    g = Grid(30, 30)
    for x in range(0, 15):  # a wing reaching into the box
        for y in range(10, 20):
            g.set(x, y, SKIN)
    for y in range(2, 7):  # a floating "!"
        g.set(24, y, RING)
    g.set(24, 8, RING)
    free = free_pixels(g, (10, 0, 20, 20))
    assert (24, 2) in free and (24, 8) in free
    assert not any(p[0] < 15 and 10 <= p[1] < 20 for p in free)


def test_bobbing_keeps_the_feet_planted_and_stretches_the_legs():
    g = Grid(10, 20)
    for y in range(20):
        g.set(5, y, (y * 10, 0, 0, 255))
    up = bobbed(g, feet=15, dy=-2)
    for y in range(15, 20):
        assert up.get(5, y) == g.get(5, y)  # feet unchanged
    assert up.get(5, 0) == g.get(5, 2)  # the body rose two pixels
    assert up.get(5, 14) == g.get(5, 14)  # the legs stretch rather than open a gap
    down = bobbed(g, feet=15, dy=1)
    assert down.get(5, 5) == g.get(5, 4)


def test_a_swung_part_moves_without_opening_a_gap_at_the_joint():
    g = Grid(40, 40)
    for x in range(10, 30):  # body
        for y in range(10, 30):
            g.set(x, y, SKIN)
    for x in range(30, 38):  # a wing to the right
        for y in range(12, 18):
            g.set(x, y, (40, 37, 46, 255))
    outline = [(30, 11), (39, 11), (39, 19), (30, 19)]
    turned = swung(g, outline, (30, 15), -20)
    assert turned.get(29, 15) == g.get(29, 15)  # the body is untouched
    # where the wing met the body there's no hole
    for y in range(12, 18):
        assert turned.opaque(30, y)
    # and the wing went up: something above its old top now
    assert any(turned.opaque(x, 10) for x in range(33, 39))


def test_polygon_mask_and_taken():
    mask = polygon_mask([(0, 0), (4, 0), (4, 4), (0, 4)])
    assert len(mask) == 16
    g = Grid(6, 6, [SKIN] * 36)
    part = taken(g, mask)
    assert not g.opaque(1, 1) and part.opaque(1, 1) and g.opaque(5, 5)


def test_background_removal_clears_a_white_sheet_but_keeps_light_parts_inside():
    w = h = 20
    px = []
    for y in range(h):
        for x in range(w):
            inside = 5 <= x < 15 and 5 <= y < 15
            chest = 8 <= x < 12 and 8 <= y < 12
            if chest:
                px.append((235, 232, 234, 255))
            elif inside:
                px.append((40, 37, 46, 255))
            else:
                px.append((255, 255, 255, 255))
    src = Raster(w, h, b"".join(bytes(p) for p in px))
    out = background_removed(src).rgba
    assert out[3] == 0  # corner cleared
    assert out[(10 * w + 10) * 4 + 3] == 255  # the light chest, enclosed, stays
    assert out[(5 * w + 5) * 4 + 3] == 255  # the subject stays


def test_edge_bits_go_but_floating_symbols_stay():
    w = h = 20
    data = bytearray(w * h * 4)

    def put(x, y):
        data[(y * w + x) * 4 : (y * w + x) * 4 + 4] = bytes((50, 50, 50, 255))

    for x in range(6, 14):
        for y in range(6, 20):
            put(x, y)  # the subject, touching the bottom edge
    for y in range(8, 12):
        put(0, y)  # a bit of the neighbouring pose
    put(17, 2)  # a floating symbol
    out = edge_bits_cleared(Raster(w, h, bytes(data))).rgba
    assert out[(9 * w + 0) * 4 + 3] == 0
    assert out[(2 * w + 17) * 4 + 3] == 255
    assert out[(10 * w + 10) * 4 + 3] == 255


def test_merged_palette_joins_drifted_blacks_but_not_distinct_colours():
    a = Counter({(42, 39, 48): 500, (247, 193, 66): 80})
    b = Counter({(35, 32, 40): 300, (250, 196, 64): 60, (226, 221, 222): 40})
    mapping, groups = merged_palette([a, b])
    assert mapping[(35, 32, 40)] == (42, 39, 48)  # the more used black wins
    assert mapping[(250, 196, 64)] == (247, 193, 66)
    assert (226, 221, 222) not in mapping
    assert any(g["sprites"] == [0, 1] and g["drift"] for g in groups)


def test_shading_steps_used_together_are_not_drift():
    steps = Counter({(48, 44, 54): 300, (57, 54, 64): 200})
    mapping, groups = merged_palette([steps, Counter(steps)])
    assert mapping == {}
    assert groups and not groups[0]["drift"]


def test_pinned_runs_switch_to_the_pinned_sprite_first(monkeypatch):
    sent = []

    class FakeLive:
        name = "live"

        def exec(self, lua, file=None, save=False):
            sent.append(lua)
            from aseprite_claude_connector.backends.base import ExecResult

            return ExecResult(ok=True, result="1")

    monkeypatch.setattr(_common.target, "pin", "abc123")
    _common.run("return 1", backend=FakeLive())
    assert "claude_target == __PIN" in sent[-1] and '"abc123"' in sent[-1]
    _common.run("return 1", backend=FakeLive(), follow_pin=False)
    assert "claude_target" not in sent[-1]
    monkeypatch.setattr(_common.target, "pin", None)
    _common.run("return 1", backend=FakeLive())
    assert "claude_target" not in sent[-1]


def test_setup_registers_with_the_desktop_app_and_keeps_other_servers(tmp_path):
    path = tmp_path / "Claude" / "claude_desktop_config.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    msg = setup.register_desktop("aseprite", path)
    config = json.loads(path.read_text())
    assert "Registered" in msg
    assert config["theme"] == "dark" and "other" in config["mcpServers"]
    entry = config["mcpServers"]["aseprite"]
    assert entry["args"] == ["-m", "aseprite_claude_connector"]
    assert entry["env"]["ASEPRITE_MCP_BACKEND"] == "live"
    assert "already" in setup.register_desktop("aseprite", path)


def test_setup_desktop_makes_the_config_when_there_is_none_and_leaves_bad_json(tmp_path):
    fresh = tmp_path / "new" / "claude_desktop_config.json"
    setup.register_desktop("aseprite", fresh)
    assert "aseprite" in json.loads(fresh.read_text())["mcpServers"]
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert "left alone" in setup.register_desktop("aseprite", bad)
    assert bad.read_text() == "{not json"
