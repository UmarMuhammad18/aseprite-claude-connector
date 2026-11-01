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


def blit(dest: bytearray, dest_width: int, src: Raster, left: int, top: int) -> None:
    """Copy ``src`` into a raw RGBA buffer, replacing what's there."""
    for y in range(src.height):
        start = ((top + y) * dest_width + left) * 4
        dest[start : start + src.width * 4] = src.rgba[y * src.width * 4 : (y + 1) * src.width * 4]


def strip(frames: list[Raster]) -> Raster:
    """Same-sized frames in a row, touching, on transparency: a sprite strip."""
    w, h = frames[0].width, frames[0].height
    out = bytearray(len(frames) * w * h * 4)
    for n, frame in enumerate(frames):
        blit(out, len(frames) * w, frame, n * w, 0)
    return Raster(len(frames) * w, h, bytes(out))


def remap(src: Raster, colors: dict[tuple[int, int, int], tuple[int, int, int]]) -> Raster:
    """Swap exact RGB colors, keeping each pixel's alpha."""
    table = {bytes(k): bytes(v) for k, v in colors.items()}
    out = bytearray(src.rgba)
    for i in range(0, len(out), 4):
        if out[i + 3]:
            hit = table.get(bytes(out[i : i + 3]))
            if hit:
                out[i : i + 3] = hit
    return Raster(src.width, src.height, bytes(out))


class _NearestInCube(dict):
    """Color bytes to an index in the 6x7x6 cube, worked out once per color."""

    def __missing__(self, c):
        index = (round(c[0] / 51) * 7 + round(c[1] * 6 / 255)) * 6 + round(c[2] / 51)
        self[c] = index
        return index


def _gif_palette(frames: list[Raster]) -> tuple[list[tuple[int, int, int]], dict]:
    """A palette for these frames: the exact colors if they fit, or else a 6x7x6 color
    cube. Returns the palette and a lookup from color bytes to index."""
    seen: dict[bytes, int] = {}
    for frame in frames:
        for i in range(0, len(frame.rgba), 4):
            seen.setdefault(frame.rgba[i : i + 3], len(seen))
        if len(seen) > 256:
            cube = [
                (r * 51, g * 255 // 6, b * 51) for r in range(6) for g in range(7) for b in range(6)
            ]
            return cube, _NearestInCube()
    return [tuple(c) for c in seen], seen


def _lzw(indices: bytes, min_code: int) -> bytes:
    """GIF's variable-width LZW, with its codes packed low bit first."""
    clear, stop = 1 << min_code, (1 << min_code) + 1
    table = {bytes((i,)): i for i in range(clear)}
    next_code, width = stop + 1, min_code + 1
    out, bits, count = bytearray(), 0, 0

    def emit(code: int) -> None:
        nonlocal bits, count
        bits |= code << count
        count += width
        while count >= 8:
            out.append(bits & 255)
            bits >>= 8
            count -= 8

    emit(clear)
    run = b""
    for i in range(len(indices)):
        grown = run + indices[i : i + 1]
        if grown in table:
            run = grown
            continue
        emit(table[run])
        if next_code == 4096:
            emit(clear)
            table = {bytes((c,)): c for c in range(clear)}
            next_code, width = stop + 1, min_code + 1
        else:
            table[grown] = next_code
            if next_code == 1 << width:
                width += 1
            next_code += 1
        run = indices[i : i + 1]
    if run:
        emit(table[run])
    emit(stop)
    if count:
        out.append(bits & 255)
    return bytes(out)


def encode_gif(frames: list[Raster], delay_ms: int) -> bytes:
    """Encode same-sized frames as a looping GIF. Flatten them with ``over_background``
    first: alpha is ignored here."""
    palette, lookup = _gif_palette(frames)
    size = max(2, (len(palette) - 1).bit_length())
    table = b"".join(bytes(c) for c in palette).ljust((1 << size) * 3, b"\0")
    w, h = frames[0].width, frames[0].height
    parts = [
        b"GIF89a",
        struct.pack("<HHBBB", w, h, 0xF0 | (size - 1), 0, 0),
        table,
        b"!\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00",
    ]
    delay = max(2, round(delay_ms / 10))
    for frame in frames:
        rgba = frame.rgba
        indices = bytes(lookup[rgba[i : i + 3]] for i in range(0, len(rgba), 4))
        parts.append(b"!\xf9\x04\x00" + struct.pack("<H", delay) + b"\x00\x00")
        parts.append(b"," + struct.pack("<HHHHB", 0, 0, w, h, 0) + bytes((size,)))
        data = _lzw(indices, size)
        for i in range(0, len(data), 255):
            block = data[i : i + 255]
            parts.append(bytes((len(block),)) + block)
        parts.append(b"\x00")
    parts.append(b";")
    return b"".join(parts)


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
