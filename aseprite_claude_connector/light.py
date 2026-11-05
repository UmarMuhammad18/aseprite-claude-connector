"""Light: time-of-day versions of a scene, and normal maps for 2D lights (stdlib
only, no Aseprite needed).

- ``relight`` — dawn, noon, sunset, or night, by moving each colour's lightness,
  warmth, and saturation in OKLab. Every colour maps to one new colour, so the art
  keeps its colour count. Lanterns (``glows``) add warm pools that stay lit.
- ``normal_map`` — a normal map for Godot's and Unity's 2D lights: forms bulge from
  their outline and bright areas stand forward, so a passing light shades them.

Works on ``Raster`` pixels from ``raster.py``.
"""

from __future__ import annotations

import math

from .oklab import to_lab, to_rgb
from .raster import Raster

# lightness scale, lightness curve, saturation, (a, b) tint in highlights, in shadows
PRESETS = {
    "dawn": (0.92, 1.0, 0.9, (0.025, 0.03), (0.01, -0.03)),
    "noon": (1.06, 0.95, 1.08, (0.0, 0.01), (0.0, 0.0)),
    "sunset": (0.88, 1.05, 1.1, (0.05, 0.08), (0.03, -0.035)),
    "night": (0.55, 1.35, 0.45, (-0.015, -0.05), (0.0, -0.06)),
}
_GLOW = (0.025, 0.06)


def relight_colour(
    c: tuple[int, int, int], time: str, strength: float = 1.0
) -> tuple[int, int, int]:
    scale, curve, sat, hi, lo = PRESETS[time]
    L, a, b = to_lab(c)
    new_l = min(1.0, scale * L**curve)
    weight = min(1.0, max(0.0, (L - 0.2) / 0.6))
    ta = hi[0] * weight + lo[0] * (1 - weight)
    tb = hi[1] * weight + lo[1] * (1 - weight)
    lab = (new_l, a * sat + ta, b * sat + tb)
    lab = tuple(v0 + (v1 - v0) * strength for v0, v1 in zip((L, a, b), lab, strict=True))
    return to_rgb(lab)


def relight(
    src: Raster,
    time: str,
    strength: float = 1.0,
    glows: list[tuple[float, float, float]] | None = None,
) -> Raster:
    """``src`` as it would look at ``time``. ``glows`` are (x, y, radius) light
    sources whose pools keep their own colour, warmed, fading out in a few steps."""
    if time not in PRESETS:
        raise ValueError("time must be dawn, noon, sunset, or night")
    w, h = src.width, src.height
    cache: dict[tuple, tuple[int, int, int]] = {}
    out = bytearray(src.rgba)
    for n in range(w * h):
        i = n * 4
        if not out[i + 3]:
            continue
        c = tuple(src.rgba[i : i + 3])
        lit = cache.get(c)
        if lit is None:
            lit = cache[c] = relight_colour(c, time, strength)
        if glows:
            x, y = n % w + 0.5, n // w + 0.5
            k = max(
                (max(0.0, 1 - math.hypot(x - gx, y - gy) / r) for gx, gy, r in glows if r > 0),
                default=0.0,
            )
            k = round(k * k * 5) / 5  # falls off softly, in a few steps
            if k:
                L, a, b = to_lab(c)
                warm = to_rgb((min(1.0, L * 1.05), a + _GLOW[0], b + _GLOW[1]))
                lit = tuple(round(lit[j] + (warm[j] - lit[j]) * k) for j in range(3))
        out[i : i + 3] = bytes(lit)
    return Raster(w, h, bytes(out))


def _inner_distance(on: list[bool], w: int, h: int) -> list[float]:
    """How far each opaque pixel is from the nearest clear one (two-pass chamfer)."""
    far = float(w + h)
    d = [0.0 if not on[n] else far for n in range(w * h)]
    for y in range(h):
        for x in range(w):
            n = y * w + x
            if not d[n]:
                continue
            best = d[n]
            for dx, dy, cost in ((-1, 0, 1), (0, -1, 1), (-1, -1, 1.4), (1, -1, 1.4)):
                nx, ny = x + dx, y + dy
                best = min(best, (d[ny * w + nx] if 0 <= nx < w and 0 <= ny < h else 0) + cost)
            d[n] = best
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            n = y * w + x
            if not d[n]:
                continue
            best = d[n]
            for dx, dy, cost in ((1, 0, 1), (0, 1, 1), (1, 1, 1.4), (-1, 1, 1.4)):
                nx, ny = x + dx, y + dy
                best = min(best, (d[ny * w + nx] if 0 <= nx < w and 0 <= ny < h else 0) + cost)
            d[n] = best
    return d


def normal_map(src: Raster, strength: float = 1.0, bevel: int = 4, detail: float = 0.4) -> Raster:
    """A tangent-space normal map (green points up, as Godot and Unity expect) the
    size of ``src``, clear where ``src`` is. Forms round off over ``bevel`` pixels
    from their outline, and ``detail`` lets brightness raise the surface."""
    w, h = src.width, src.height
    on = [src.rgba[n * 4 + 3] >= 128 for n in range(w * h)]
    dist = _inner_distance(on, w, h)
    height = []
    for n in range(w * h):
        if not on[n]:
            height.append(0.0)
            continue
        k = min(1.0, dist[n] / max(1, bevel))
        dome = math.sin(k * math.pi / 2)
        bright = to_lab(tuple(src.rgba[n * 4 : n * 4 + 3]))[0]
        height.append(dome + detail * bright)

    def hgt(x, y):
        x, y = min(w - 1, max(0, x)), min(h - 1, max(0, y))
        return height[y * w + x]

    out = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            n = y * w + x
            if not on[n]:
                continue
            dx = (hgt(x + 1, y) - hgt(x - 1, y)) * strength
            dy = (hgt(x, y + 1) - hgt(x, y - 1)) * strength
            nx, ny, nz = -dx, dy, 1.0  # image rows run down; the map's green runs up
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            out[n * 4 : n * 4 + 4] = bytes(
                (
                    round((nx / length * 0.5 + 0.5) * 255),
                    round((ny / length * 0.5 + 0.5) * 255),
                    round((nz / length * 0.5 + 0.5) * 255),
                    src.rgba[n * 4 + 3],
                )
            )
    return Raster(w, h, bytes(out))
