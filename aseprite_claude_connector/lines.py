"""Cleaning up sketched line art (stdlib only, no Aseprite needed).

``clean_lines`` thins strokes to one pixel and removes the doubled corner pixels a
freehand line leaves, the way Aseprite's pixel-perfect brush would have drawn it.
Works on ``Raster`` pixels from ``raster.py``; kept pixels keep their colour.
"""

from __future__ import annotations

from .raster import Raster

# Neighbours clockwise from north: N, NE, E, SE, S, SW, W, NW.
_RING = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))


def _thin(on: list[bool], w: int, h: int) -> int:
    """Zhang-Suen thinning: peel stroke edges until every stroke is one pixel wide."""

    def ring(x, y):
        return [
            0 <= x + dx < w and 0 <= y + dy < h and on[(y + dy) * w + x + dx] for dx, dy in _RING
        ]

    removed = 0
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            gone = []
            for y in range(h):
                for x in range(w):
                    if not on[y * w + x]:
                        continue
                    p = ring(x, y)
                    count = sum(p)
                    turns = sum(1 for i in range(8) if not p[i] and p[(i + 1) % 8])
                    if not (2 <= count <= 6 and turns == 1):
                        continue
                    n, e, s, west = p[0], p[2], p[4], p[6]
                    if step == 0 and not (n and e and s) and not (e and s and west):
                        gone.append(y * w + x)
                    elif step == 1 and not (n and e and west) and not (n and s and west):
                        gone.append(y * w + x)
            for i in gone:
                on[i] = False
            removed += len(gone)
            changed = changed or bool(gone)
    return removed


def _corners(on: list[bool], w: int, h: int) -> int:
    """Drop the corner pixel of every L where a line turns: it has one neighbour across
    and one up or down, the inside of the L is empty, and every other neighbour still
    touches one of those two, so the line stays joined without the doubled pixel."""

    def lit(x, y):
        return 0 <= x < w and 0 <= y < h and on[y * w + x]

    removed = 0
    for y in range(h):
        for x in range(w):
            if not on[y * w + x]:
                continue
            across = [dx for dx in (-1, 1) if lit(x + dx, y)]
            upright = [dy for dy in (-1, 1) if lit(x, y + dy)]
            if len(across) != 1 or len(upright) != 1:
                continue
            ax, by = across[0], upright[0]
            if lit(x + ax, y + by):
                continue  # the L is filled in: a solid patch, not a line
            others = [
                (x + dx, y + dy)
                for dx, dy in _RING
                if (dx, dy) not in ((ax, 0), (0, by)) and lit(x + dx, y + dy)
            ]
            if all(
                max(abs(ox - (x + ax)), abs(oy - y)) <= 1
                or max(abs(ox - x), abs(oy - (y + by))) <= 1
                for ox, oy in others
            ):
                on[y * w + x] = False
                removed += 1
    return removed


def clean_lines(src: Raster, thin: bool = True, specks: bool = False) -> tuple[Raster, dict]:
    """``src`` with its strokes thinned to one pixel (``thin``) and doubled corners
    removed. ``specks`` also removes pixels with no neighbour at all."""
    w, h = src.width, src.height
    on = [src.rgba[n * 4 + 3] >= 128 for n in range(w * h)]
    thinned = _thin(on, w, h) if thin else 0
    cornered = _corners(on, w, h)
    lone = 0
    if specks:
        for y in range(h):
            for x in range(w):
                if on[y * w + x] and not any(
                    0 <= x + dx < w and 0 <= y + dy < h and on[(y + dy) * w + x + dx]
                    for dx, dy in _RING
                ):
                    on[y * w + x] = False
                    lone += 1
    out = bytearray(len(src.rgba))
    for n in range(w * h):
        if on[n]:
            out[n * 4 : n * 4 + 4] = src.rgba[n * 4 : n * 4 + 4]
    return Raster(w, h, bytes(out)), {
        "thinned_pixels": thinned,
        "corner_pixels": cornered,
        "lone_pixels": lone,
    }
