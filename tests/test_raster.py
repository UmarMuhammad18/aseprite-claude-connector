"""The look tools' pixel work: no Aseprite needed."""

from __future__ import annotations

import struct
import zlib

from aseprite_live_mcp.raster import (
    Raster,
    diff,
    encode_png,
    fit_factor,
    over_background,
    resized,
    tiled,
)

RED = bytes((255, 0, 0, 255))
CLEAR = bytes(4)


def _decode_png(data: bytes) -> tuple[int, int, bytes]:
    """Read back what encode_png wrote (unfiltered 8-bit RGBA)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, width, height, idat = 8, 0, 0, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])[0]
        assert crc == zlib.crc32(kind + body)
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
            assert body[8:10] == bytes((8, 6))
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 4 + 1
    return width, height, b"".join(raw[y * stride + 1 : (y + 1) * stride] for y in range(height))


def test_fit_uses_whole_zooms_up_and_fractions_only_to_shrink():
    assert fit_factor(32, 32, None, 512) == 16
    assert fit_factor(33, 10, None, 512) == 15
    assert fit_factor(4, 4, None, 512) == 32  # capped
    assert fit_factor(1024, 512, None, 512) == 0.5
    assert fit_factor(1024, 512, 3, 512) == 3  # an explicit scale wins


def test_integer_zoom_keeps_pixels_sharp():
    src = Raster(2, 1, RED + CLEAR)
    big = resized(src, 2)
    assert (big.width, big.height) == (4, 2)
    assert big.rgba == (RED * 2 + CLEAR * 2) * 2


def test_shrink_samples_without_blending():
    src = Raster(4, 1, RED + CLEAR + RED + CLEAR)
    small = resized(src, 0.5)
    assert (small.width, small.height) == (2, 1)
    assert {small.rgba[i : i + 4] for i in (0, 4)} <= {RED, CLEAR}


def test_resized_by_one_is_the_same_image():
    src = Raster(1, 1, RED)
    assert resized(src, 1) is src


def test_backgrounds():
    src = Raster(2, 1, RED + CLEAR)
    assert over_background(src, "transparent") is src
    assert over_background(src, (0, 0, 255)).rgba == RED + bytes((0, 0, 255, 255))
    checker = over_background(Raster(9, 1, CLEAR * 9), "checker").rgba
    assert checker[:4] != checker[32:36]  # the 8px cell boundary flips the shade
    half = over_background(Raster(1, 1, bytes((255, 0, 0, 128))), (0, 0, 0)).rgba
    assert half == bytes((128, 0, 0, 255))


def test_tiled_places_panels_in_reading_order():
    a, b, c = Raster(1, 1, RED), Raster(1, 1, CLEAR), Raster(1, 1, RED)
    sheet = tiled([a, b, c], columns=2, gap=1)
    assert (sheet.width, sheet.height) == (5, 5)

    def px(x, y):
        i = (y * sheet.width + x) * 4
        return sheet.rgba[i : i + 4]

    assert px(1, 1) == RED and px(3, 1) == CLEAR and px(1, 3) == RED
    assert px(0, 0) == bytes((32, 32, 32, 255))


def test_diff_counts_and_bounds_changes():
    before = Raster(3, 2, CLEAR * 6)
    assert diff(before, before) == {"changed_pixels": 0, "bbox": None}
    after = Raster(3, 2, CLEAR * 2 + RED + CLEAR + RED + CLEAR)
    assert diff(before, after) == {
        "changed_pixels": 2,
        "bbox": {"x": 1, "y": 0, "width": 2, "height": 2},
    }


def test_png_round_trip():
    src = Raster(2, 2, RED + CLEAR + CLEAR + RED)
    assert _decode_png(encode_png(src)) == (2, 2, src.rgba)
