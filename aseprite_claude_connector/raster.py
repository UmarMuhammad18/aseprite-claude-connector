"""Small RGBA raster helpers for the look tools (stdlib only, no Aseprite needed).

Aseprite hands over raw pixels; zooming, backdrops, layouts, diffs, and PNG
encoding all happen here. Pixels are bytes in R, G, B, A order, row by row.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

_CHECKER_CELL = 8
_CHECKER_LITE = (204, 204, 204)
_CHECKER_DARK = (170, 170, 170)


@dataclass(frozen=True)
class Raster:
    width: int
    height: int
    rgba: bytes


def fit_factor(width: int, height: int, scale: int | None, max_size: int) -> float:
    """The zoom to show an image at: integer when there's room, so pixels stay
    sharp, and a fraction only when it can't otherwise fit in ``max_size``."""
    if scale is not None:
        return scale
    k = max_size / max(width, height)
    return min(int(k), 32) if k >= 1 else k


def resized(src: Raster, factor: float) -> Raster:
    """Nearest-neighbor resize; a factor of 1 returns ``src`` unchanged."""
    if factor == 1:
        return src
    w = max(1, round(src.width * factor))
    h = max(1, round(src.height * factor))
    xmap = [min(src.width - 1, x * src.width // w) * 4 for x in range(w)]
    rows, last_y, last_row = [], None, b""
    for y in range(h):
        sy = min(src.height - 1, y * src.height // h)
        if sy != last_y:
            line = src.rgba[sy * src.width * 4 : (sy + 1) * src.width * 4]
            last_row = b"".join(line[i : i + 4] for i in xmap)
            last_y = sy
        rows.append(last_row)
    return Raster(w, h, b"".join(rows))


def over_background(src: Raster, background: str | tuple[int, int, int]) -> Raster:
    """Composite onto ``"checker"``, a solid (r, g, b), or nothing for
    ``"transparent"`` — most viewers show bare alpha as black, hiding the art."""
    if background == "transparent":
        return src
    out = bytearray(src.rgba)
    w = src.width
    for i in range(0, len(out), 4):
        a = out[i + 3]
        if a == 255:
            continue
        if background == "checker":
            x, y = (i // 4) % w, (i // 4) // w
            odd = (x // _CHECKER_CELL + y // _CHECKER_CELL) % 2
            bg = _CHECKER_DARK if odd else _CHECKER_LITE
        else:
            bg = background
        for c in range(3):
            out[i + c] = (out[i + c] * a + bg[c] * (255 - a)) // 255
        out[i + 3] = 255
    return Raster(src.width, src.height, bytes(out))


def tiled(panels: list[Raster], columns: int, gap: int = 4) -> Raster:
    """Lay same-sized panels out left to right, top to bottom, on a dark sheet."""
    pw, ph = panels[0].width, panels[0].height
    rows = -(-len(panels) // columns)
    w = columns * pw + (columns + 1) * gap
    h = rows * ph + (rows + 1) * gap
    out = bytearray(bytes((32, 32, 32, 255)) * (w * h))
    for n, panel in enumerate(panels):
        left = gap + (n % columns) * (pw + gap)
        top = gap + (n // columns) * (ph + gap)
        for y in range(ph):
            start = ((top + y) * w + left) * 4
            out[start : start + pw * 4] = panel.rgba[y * pw * 4 : (y + 1) * pw * 4]
    return Raster(w, h, bytes(out))


def diff(a: Raster, b: Raster) -> dict:
    """Changed-pixel count and bbox between two same-sized rasters."""
    changed, minx, miny, maxx, maxy = 0, a.width, a.height, -1, -1
    stride = a.width * 4
    for y in range(a.height):
        ra = a.rgba[y * stride : (y + 1) * stride]
        rb = b.rgba[y * stride : (y + 1) * stride]
        if ra == rb:
            continue
        for x in range(a.width):
            if ra[x * 4 : x * 4 + 4] != rb[x * 4 : x * 4 + 4]:
                changed += 1
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
    bbox = None
    if changed:
        bbox = {"x": minx, "y": miny, "width": maxx - minx + 1, "height": maxy - miny + 1}
    return {"changed_pixels": changed, "bbox": bbox}


def encode_png(src: Raster) -> bytes:
    """Encode as an 8-bit RGBA PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    stride = src.width * 4
    scanlines = b"".join(
        b"\x00" + src.rgba[y * stride : (y + 1) * stride] for y in range(src.height)
    )
    header = struct.pack(">IIBBBBB", src.width, src.height, 8, 6, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", header),
            chunk(b"IDAT", zlib.compress(scanlines, 6)),
            chunk(b"IEND", b""),
        )
    )
