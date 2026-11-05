"""Working from a reference picture: no Aseprite needed."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from aseprite_claude_connector.pixelate import (
    compared,
    cropped,
    despeckled,
    median_cut,
    quantized,
    shrink,
)
from aseprite_claude_connector.raster import Raster

GREY = (128, 128, 128)
PINK = (230, 120, 150)


def solid(width, height, color, alpha=255):
    return Raster(width, height, bytes((*color, alpha)) * (width * height))


def pixel(r: Raster, x, y):
    i = (y * r.width + x) * 4
    return tuple(r.rgba[i : i + 4])


def test_shrinking_averages_each_area():
    src = Raster(2, 1, bytes((0, 0, 0, 255, 200, 100, 50, 255)))
    assert pixel(shrink(src, 1, 1), 0, 0) == (100, 50, 25, 255)


def test_shrinking_ignores_the_colour_of_clear_pixels():
    src = Raster(2, 1, bytes((255, 0, 0, 0, 0, 0, 255, 255)))
    assert pixel(shrink(src, 1, 1), 0, 0) == (0, 0, 255, 128)


def test_a_crop_is_clipped_to_the_picture():
    src = solid(4, 4, GREY)
    assert cropped(src, 2, 2, 10, 10).width == 2
    with pytest.raises(ValueError):
        cropped(src, 5, 5, 2, 2)


def test_a_small_accent_keeps_its_own_colour():
    """A few pink flowers in a big grey field still get a palette entry."""
    field = [(g, g, g) for g in range(40, 200) for _ in range(20)]
    palette = median_cut(field + [PINK] * 80, 12)
    assert len(palette) <= 12
    assert min(sum(abs(a - b) for a, b in zip(c, PINK, strict=True)) for c in palette) < 30


def test_snapping_uses_only_the_palette():
    src = Raster(2, 1, bytes((10, 10, 10, 255, 240, 240, 240, 255)))
    art = quantized(src, [(0, 0, 0), (255, 255, 255)])
    assert pixel(art, 0, 0) == (0, 0, 0, 255)
    assert pixel(art, 1, 0) == (255, 255, 255, 255)


def test_ordered_dither_mixes_the_two_nearest_colours():
    art = quantized(solid(8, 8, GREY), [(0, 0, 0), (255, 255, 255)], "ordered", strength=255)
    seen = {pixel(art, x, y) for x in range(8) for y in range(8)}
    assert seen == {(0, 0, 0, 255), (255, 255, 255, 255)}


def test_mostly_clear_pixels_go_fully_clear():
    art = quantized(solid(1, 1, GREY, alpha=60), [GREY])
    assert pixel(art, 0, 0)[3] == 0


def test_an_unknown_dither_is_refused():
    with pytest.raises(ValueError):
        quantized(solid(1, 1, GREY), [GREY], "noise")


def test_despeckle_removes_lone_pixels_only():
    rgba = bytearray(solid(3, 3, GREY).rgba)
    rgba[16:20] = bytes((*PINK, 255))
    assert pixel(despeckled(Raster(3, 3, bytes(rgba))), 1, 1) == (*GREY, 255)
    edge = bytearray(solid(3, 3, GREY).rgba)
    for i in (12, 16, 20):
        edge[i : i + 4] = bytes((*PINK, 255))
    assert pixel(despeckled(Raster(3, 3, bytes(edge))), 1, 1) == (*PINK, 255)


def test_a_perfect_match_scores_100():
    r = compared(solid(8, 8, GREY), solid(8, 8, GREY))
    assert (r["score"], r["shape_score"], r["close_pixels"]) == (100.0, 100.0, 100.0)


def test_the_worst_area_is_the_one_that_differs():
    ref = solid(8, 8, GREY)
    rgba = bytearray(ref.rgba)
    for y in range(4, 8):
        for x in range(4, 8):
            i = (y * 8 + x) * 4
            rgba[i : i + 3] = bytes((20, 20, 20))
    r = compared(Raster(8, 8, bytes(rgba)), ref, cells=2)
    worst = r["worst_areas"][0]
    assert (worst["x"], worst["y"], worst["art_is"]) == (4, 4, "darker")
    assert r["score"] < 100


def _server(monkeypatch, ran):
    from aseprite_claude_connector.server import build_server
    from aseprite_claude_connector.tools import reference

    monkeypatch.setattr(reference, "read_picture", lambda path: solid(20, 10, PINK))

    def fake_run(lua, **kw):
        ran.append((lua, kw))
        if kw.get("mutates"):
            return {"layer": "Reference pixels", "width": 4, "height": 2, "x": 0, "y": 0}
        art = base64.b64encode(solid(4, 2, PINK).rgba).decode()
        return {"rgba": art, "width": 4, "height": 2, "frame": 1, "layer": "all visible"}

    monkeypatch.setattr(reference, "run", fake_run)
    return build_server()


def test_pixelate_sends_pixels_and_keeps_the_aspect(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, ran)
    res = asyncio.run(mcp.call_tool("pixelate_reference", {"image_path": "ref.png", "width": 4}))
    lua, kw = ran[0]
    assert kw["mutates"] and kw["undo_label"] == "Pixelate reference"
    assert "fromFile" not in lua
    assert "IMAGE_W = 4" in lua and "IMAGE_H = 2" in lua
    out = res[1] if isinstance(res, tuple) else json.loads(res[0].text)
    assert out["source"] == {"width": 20, "height": 10}


def test_compare_returns_a_picture_and_scores(monkeypatch):
    ran = []
    mcp = _server(monkeypatch, ran)
    res = asyncio.run(mcp.call_tool("compare_to_reference", {"image_path": "ref.png"}))
    parts = res[0] if isinstance(res, tuple) else res
    assert any(getattr(p, "type", "") == "image" for p in parts)
    meta = json.loads(next(p.text for p in parts if getattr(p, "type", "") == "text"))
    assert meta["score"] == 100.0
    assert meta["panels"] == ["reference", "canvas", "difference"]
