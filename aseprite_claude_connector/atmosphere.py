"""Atmosphere: skies, water reflections, glows, and rim light (stdlib only, no
Aseprite needed).

- ``sky`` — a dithered sky for a time of day, with a sun, clouds lit from its side,
  and stars.
- ``reflection`` — the scene above a horizon mirrored into rippling water, one frame
  of a loop at a time.
- ``glow`` — a pool of light round a fire, lantern, or window.
- ``rim_light`` — the edge of a shape that faces a light, picked out in its colour.

Shading is ordered dither between a few colours, so it reads as pixel art. Works on
``Raster`` pixels from ``raster.py``.
"""

from __future__ import annotations

import math
import random

from .raster import Raster

_TAU = math.pi * 2
_BAYER = (0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5)

Colour = tuple[int, int, int]


def _threshold(x: int, y: int) -> float:
    return (_BAYER[(y & 3) * 4 + (x & 3)] + 0.5) / 16


def _rgb(text: str) -> Colour:
    return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))


def _ramp(colours: list[Colour], t: float, x: int, y: int) -> Colour:
    """The colour at ``t`` (0-1) along ``colours``, dithered between neighbours."""
    t = max(0.0, min(0.9999, t)) * (len(colours) - 1)
    i = int(t)
    if t - i > _threshold(x, y):
        i += 1
    return colours[i]


def _smooth(lo: float, hi: float, v: float) -> float:
    t = max(0.0, min(1.0, (v - lo) / (hi - lo)))
    return t * t * (3 - 2 * t)


class _Noise:
    """Value noise that is the same for the same seed."""

    def __init__(self, seed: int):
        rng = random.Random(seed)
        self.table = [rng.random() for _ in range(4096)]

    def at(self, x: int, y: int) -> float:
        return self.table[(x * 73856093 ^ y * 19349663 ^ x * y * 83492791) & 4095]

    def value(self, x: float, y: float) -> float:
        xi, yi = math.floor(x), math.floor(y)
        xf, yf = x - xi, y - yi
        xf, yf = xf * xf * (3 - 2 * xf), yf * yf * (3 - 2 * yf)
        top = self.at(xi, yi) + (self.at(xi + 1, yi) - self.at(xi, yi)) * xf
        low = self.at(xi, yi + 1) + (self.at(xi + 1, yi + 1) - self.at(xi, yi + 1)) * xf
        return top + (low - top) * yf

    def fbm(self, x: float, y: float, octaves: int = 4) -> float:
        total, amp, freq, norm = 0.0, 0.5, 1.0, 0.0
        for _ in range(octaves):
            total += amp * self.value(x * freq, y * freq)
            norm += amp
            amp *= 0.5
            freq *= 2.03
        return total / norm


# Sky colours from the top of the picture down to the horizon, the hotter colours
# reached only near the sun, cloud colours from shadow to lit, how many stars show, and
# how strongly the sky glows round the sun.
SKIES = {
    "dawn": {
        "sky": ["#16204c", "#2a3268", "#4a4682", "#7a5a92", "#b0709a", "#dc8c92", "#f4ae90"],
        "hot": ["#ffcc9a", "#ffe6b8", "#fff6dc"],
        "cloud": ["#3a3a70", "#5e4a84", "#96608e", "#d08490", "#f6b296", "#ffe2c0"],
        "stars": 0.25,
        "glow": 1.0,
    },
    "day": {
        "sky": ["#2460c4", "#3478d8", "#4a90e6", "#66a8f0", "#88c0f6", "#aed6fa", "#d2eafc"],
        "hot": ["#e8f4fe", "#f8fcff", "#ffffff"],
        "cloud": ["#8aa2c8", "#aabedc", "#c8d8ec", "#e2ecf8", "#f4f8fe", "#ffffff"],
        "stars": 0.0,
        "glow": 0.45,
    },
    "sunset": {
        "sky": [
            "#070b24", "#0e1539", "#1a2454", "#30336e", "#5a4084", "#9a4c86", "#da666c", "#f38650",
        ],
        "hot": ["#fda554", "#ffc368", "#ffe19a", "#fff0b8"],
        "cloud": ["#1a1c4a", "#3a2b70", "#7a3c82", "#cc586e", "#fc945a", "#ffdc96", "#fff6d8"],
        "stars": 0.6,
        "glow": 1.0,
    },
    "night": {
        "sky": ["#03051a", "#060a24", "#0a102e", "#0e163a", "#131d48", "#1a2656", "#232f64"],
        "hot": ["#3a4682", "#6a78aa", "#b8c2e0"],
        "cloud": ["#0c1230", "#161e44", "#242e5c", "#3a4678", "#5a6896", "#8894ba"],
        "stars": 1.0,
        "glow": 0.7,
    },
}  # fmt: skip


def sky(
    width: int,
    height: int,
    time: str = "sunset",
    horizon: int | None = None,
    sun: tuple[float, float] | None = None,
    clouds: float = 0.5,
    stars: float | None = None,
    seed: int = 1,
) -> Raster:
    """A sky filling the picture, shaded from the top down to ``horizon`` (the bottom
    edge by default). ``sun`` is where the sun or moon sits; the sky glows round it and
    the clouds are lit from its side. ``clouds`` is how much of the sky they cover
    (0-1) and ``stars`` how many show (0-1, the time's own amount by default)."""
    if time not in SKIES:
        raise ValueError(f"time must be one of: {', '.join(SKIES)}")
    look = SKIES[time]
    horizon = height - 1 if horizon is None else max(1, min(height - 1, horizon))
    ramp = [_rgb(c) for c in look["sky"] + look["hot"]]
    plain = (len(look["sky"]) - 1) / (len(ramp) - 1)
    reach = width * 0.62
    px = bytearray(width * height * 4)

    def glow_at(x: int, y: int) -> float:
        if sun is None:
            return 0.0
        d = math.hypot(x - sun[0], (y - sun[1]) * 1.25)
        return max(0.0, 1 - d / reach) ** 1.5

    for y in range(height):
        yy = min(y, horizon)
        base = (yy / horizon) ** 1.25 * plain
        for x in range(width):
            t = base + glow_at(x, yy) * (1 - plain) * 1.6 * look["glow"]
            i = (y * width + x) * 4
            px[i : i + 4] = bytes((*_ramp(ramp, t, x, y), 255))

    rng = random.Random(seed)
    amount = look["stars"] if stars is None else max(0.0, min(1.0, stars))
    if amount > 0:
        tones = [(116, 104, 176), (192, 184, 232), (255, 255, 255)]
        top = max(1, int(horizon * 0.62))
        for _ in range(int(width * top * 0.012 * amount)):
            x, y = rng.randrange(width), int(rng.random() ** 1.9 * top)
            if glow_at(x, y) > 0.35:
                continue
            tone = tones[min(2, int(rng.random() * 3 * (1 - y / top) + rng.random()))]
            i = (y * width + x) * 4
            px[i : i + 3] = bytes(tone)

    if clouds > 0:
        _paint_clouds(px, width, horizon, look, sun, max(0.0, min(1.0, clouds)), seed)

    if sun is not None:
        radius = max(2.0, width / 60)
        core, rim = ramp[-1], ramp[-2]
        for y in range(int(sun[1] - radius * 3), int(sun[1] + radius * 3) + 1):
            for x in range(int(sun[0] - radius * 3), int(sun[0] + radius * 3) + 1):
                if not (0 <= x < width and 0 <= y <= horizon):
                    continue
                d = math.hypot(x - sun[0], y - sun[1])
                i = (y * width + x) * 4
                if d <= radius:
                    px[i : i + 3] = bytes(core if d < radius - 1.5 else rim)
                elif d < radius * 3 and (1 - (d - radius) / (radius * 2)) ** 1.5 > _threshold(x, y):
                    px[i : i + 3] = bytes(rim)
    return Raster(width, height, bytes(px))


def _paint_clouds(px, width, horizon, look, sun, cover, seed) -> None:
    """A bank of cloud across the middle of the sky, shaded by what lies between each
    part and the light."""
    noise = _Noise(seed)
    fx, fy = 4.1 / width, 5.0 / horizon
    cut = 0.62 - cover * 0.28
    rows = horizon + 8
    field = [0.0] * (width * rows)
    for y in range(rows):
        band = _smooth(horizon * 0.3, horizon * 0.56, y) * (
            1 - _smooth(horizon * 0.78, horizon * 0.96, y)
        )
        wisp = _smooth(horizon * 0.05, horizon * 0.16, y) * (
            1 - _smooth(horizon * 0.27, horizon * 0.42, y)
        )
        if band <= 0 and wisp <= 0:
            continue
        for x in range(width):
            warp = x + width * 0.037 * noise.fbm(x * fx * 1.4 + 7, y * fy, 2)
            cum = noise.fbm(warp * fx + 2.0, y * fy + 5.0, 5)
            cum += 0.16 * noise.fbm(x * fx * 4.1, y * fy * 3.3 + 3, 3) - 0.08
            cir = noise.fbm(warp * fx * 1.3 + 40 + y * 0.02, y * fy * 2.3 + 9, 4)
            field[y * width + x] = max(cum * band, cir * wisp * 0.9)
    ramp = [_rgb(c) for c in look["cloud"]]
    steps = [max(1, round(k * width / 480)) for k in (5, 11, 18)]
    reach = width * 0.75
    for y in range(horizon + 1):
        for x in range(width):
            d = field[y * width + x]
            if d <= cut - 0.01:
                continue
            if (d - cut + 0.01) / 0.06 <= _threshold(x + 1, y + 2) * 0.9:
                continue
            if sun is None:
                vx, vy, near = 0.0, -1.0, 0.45
            else:
                vx, vy = sun[0] - x, sun[1] + horizon * 0.06 - y
                far = math.hypot(vx, vy) + 0.001
                vx, vy, near = vx / far, vy / far, max(0.0, 1 - far / reach)
            shade = 0.0
            for k in steps:
                qx = max(0, min(width - 1, int(x + vx * k + 0.5)))
                qy = max(0, min(rows - 1, int(y + vy * k + 0.5)))
                shade += max(0.0, field[qy * width + qx] - cut)
            edge = max(0.0, 1 - shade * 9)
            lum = 0.16 + edge * (0.22 + 0.62 * near**1.2) + (y / horizon - 0.45) * 0.18
            lum += near**2.5 * 0.15
            i = (y * width + x) * 4
            px[i : i + 3] = bytes(_ramp(ramp, lum, x, y))


def _speck(x: int, y: int, z: int) -> float:
    return ((x * 73856093 ^ y * 19349663 ^ z * 83492791) & 1023) / 1024


def reflection(
    above: Raster,
    rows: int,
    frame: int = 0,
    frames: int = 1,
    ripple: float = 1.0,
    tint: Colour = (12, 16, 48),
    depth: float = 0.5,
    sun_x: float | None = None,
) -> Raster:
    """``rows`` of water under ``above``, whose bottom row is the horizon: the picture
    mirrored, rippling more the nearer it comes, and sinking into ``tint`` with
    ``depth`` (0-1). ``frame`` of ``frames`` is where this is in a loop. ``sun_x``
    lays a broken path of light down the water under the sun."""
    width, horizon = above.width, above.height - 1
    src = above.rgba
    stride = width * 4
    t = frame / max(1, frames)
    path = [bytes((255, 240, 184)), bytes((255, 188, 102)), bytes((240, 126, 92))]
    out = bytearray(stride * rows)
    for row in range(rows):
        d = row + 1
        phase = 38 * math.log(d + 6)
        sway = math.sin(phase - _TAU * t) * (0.5 + d * 0.05) * ripple
        sway += math.sin(phase * 2.3 + _TAU * t) * d * 0.022 * ripple
        crest = math.sin(phase * 1.7 - _TAU * t)
        sy = horizon - int(d * 0.95 + crest * (d * 0.035 + 0.3) * ripple + 0.5)
        sy = max(0, min(horizon, sy))
        line = src[sy * stride : (sy + 1) * stride]
        shift = int(round(sway))
        if shift > 0:
            line = line[shift * 4 :] + line[-4:] * shift
        elif shift < 0:
            line = line[:4] * -shift + line[: shift * 4]
        k = min(0.9, depth * (0.4 + (d / rows) ** 0.8))
        lift = 28 if crest > 0.8 else 0
        made = bytearray(stride)
        for ch in range(3):
            table = bytes(min(255, int(v * (1 - k) + tint[ch] * k)) for v in range(256))
            plane = line[ch::4].translate(table)
            if lift:
                bright = bytes(min(255, v + lift - ch * 4) for v in range(256))
                plane = bytearray(plane)
                run = 3 + d // 10
                for x0 in range(0, width, run):
                    if _speck(x0 // run, row, 0) > 0.55:
                        plane[x0 : x0 + run] = plane[x0 : x0 + run].translate(bright)
            made[ch::4] = plane
        made[3::4] = line[3::4]
        if sun_x is not None and crest > -0.2:
            half = (5 + d * 0.36) * 2.2
            for x in range(max(0, int(sun_x - half - 3)), min(width, int(sun_x + half + 4))):
                p = 1 - abs(x - sun_x + sway * 2) / half
                if p > 0 and _speck(x // 2, row, frame // 2) < p * 0.8:
                    made[x * 4 : x * 4 + 4] = (
                        path[0 if p > 0.6 else (1 if p > 0.3 else 2)] + b"\xff"
                    )
        out[row * stride : (row + 1) * stride] = made
    return Raster(width, rows, bytes(out))


def glow(
    width: int,
    height: int,
    centre: tuple[float, float],
    radius: float,
    colour: Colour,
    strength: float = 0.6,
    lit: Raster | None = None,
    air: float = 0.15,
    phase: float = 0.0,
    flicker: float = 0.0,
) -> Raster:
    """A pool of ``colour`` light round ``centre``, fading out by ``radius`` in dithered
    steps, for a layer set to add. Where ``lit`` has pixels the light lands at full
    ``strength``; open air takes only ``air`` of it. ``flicker`` (0-1) makes the pool
    breathe as ``phase`` runs 0 to 1 through a loop."""
    reach = radius * (
        1 + flicker * (0.07 * math.sin(_TAU * phase * 3) + 0.04 * math.sin(_TAU * phase * 5 + 1))
    )
    px = bytearray(width * height * 4)
    cx, cy = centre
    levels = 12
    for y in range(max(0, int(cy - reach)), min(height, int(cy + reach) + 1)):
        for x in range(max(0, int(cx - reach)), min(width, int(cx + reach) + 1)):
            d = math.hypot(x - cx, (y - cy) * 1.1)
            if d >= reach:
                continue
            level = int((1 - d / reach) ** 2 * levels + _threshold(x, y))
            if level <= 0:
                continue
            share = 1.0 if lit is None or lit.rgba[(y * width + x) * 4 + 3] else air
            alpha = int(min(255, 255 * strength * share * level / levels))
            if alpha > 0:
                i = (y * width + x) * 4
                px[i : i + 4] = bytes((*colour, alpha))
    return Raster(width, height, bytes(px))


def rim_light(
    shape: Raster,
    light: tuple[float, float],
    colour: Colour,
    width: int = 1,
    radius: float | None = None,
) -> Raster:
    """The pixels of ``shape`` on the edge that faces ``light``, in ``colour``, on an
    otherwise empty picture. ``width`` 2 adds a dithered second row, mixed with the
    shape's own colour. With ``radius`` the light fades out that far from its
    source."""
    w, h, src = shape.width, shape.height, shape.rgba
    px = bytearray(w * h * 4)

    def solid(x: int, y: int) -> bool:
        return 0 <= x < w and 0 <= y < h and src[(y * w + x) * 4 + 3] > 0

    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            if not src[i + 3]:
                continue
            dx, dy = light[0] - x, light[1] - y
            far = math.hypot(dx, dy)
            if far < 0.5:
                continue
            if radius is not None and (
                far >= radius or (1 - far / radius) * 1.6 < _threshold(x, y)
            ):
                continue
            sx, sy = round(dx / far), round(dy / far)
            if not solid(x + sx, y + sy):
                px[i : i + 4] = bytes((*colour, 255))
            elif width > 1 and not solid(x + sx * 2, y + sy * 2) and _threshold(x, y) < 0.5:
                px[i : i + 4] = bytes((colour[c] + src[i + c]) // 2 for c in range(3)) + b"\xff"
    return Raster(w, h, bytes(px))


def bounds(pictures: list[Raster]) -> tuple[int, int, int, int] | None:
    """The box (left, top, right, bottom) holding every pixel in ``pictures``."""
    left = top = None
    right = bottom = -1
    for p in pictures:
        stride = p.width * 4
        for y in range(p.height):
            alpha = p.rgba[y * stride + 3 : (y + 1) * stride : 4]
            if not any(alpha):
                continue
            first = next(x for x, a in enumerate(alpha) if a)
            last = p.width - 1 - next(x for x, a in enumerate(reversed(alpha)) if a)
            left = first if left is None else min(left, first)
            top = y if top is None else min(top, y)
            right, bottom = max(right, last), max(bottom, y)
    if left is None:
        return None
    return left, top, right, bottom


def cropped(p: Raster, box: tuple[int, int, int, int]) -> Raster:
    left, top, right, bottom = box
    stride = p.width * 4
    rows = [
        p.rgba[y * stride + left * 4 : y * stride + (right + 1) * 4] for y in range(top, bottom + 1)
    ]
    return Raster(right - left + 1, bottom - top + 1, b"".join(rows))
