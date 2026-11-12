"""Atmosphere: skies, water reflections, glows, and rim light (stdlib only, no
Aseprite needed).

- ``sky`` — a dithered sky for a time of day, with a sun, clouds lit from its side,
  and stars. ``cloud_frames`` makes the clouds drift as a loop.
- ``mountains`` — hazy ranges on the horizon, lit from the sun's side.
- ``fire_frames`` — a looping fire with embers.
- ``mist_frames`` — a band of mist that drifts as a loop.
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


def _cloud_field(width: int, horizon: int, seed: int, extra: int = 0) -> tuple[list[float], int]:
    """How thick the cloud is at each pixel: a bank across the middle of the sky and
    wisps above it. ``extra`` columns are added on the right, for clouds to drift in
    from. Returns the field and its row count."""
    noise = _Noise(seed)
    fx, fy = 4.1 / width, 5.0 / horizon
    rows, across = horizon + 8, width + extra
    field = [0.0] * (across * rows)
    for y in range(rows):
        band = _smooth(horizon * 0.3, horizon * 0.56, y) * (
            1 - _smooth(horizon * 0.78, horizon * 0.96, y)
        )
        wisp = _smooth(horizon * 0.05, horizon * 0.16, y) * (
            1 - _smooth(horizon * 0.27, horizon * 0.42, y)
        )
        if band <= 0 and wisp <= 0:
            continue
        for x in range(across):
            warp = x + width * 0.037 * noise.fbm(x * fx * 1.4 + 7, y * fy, 2)
            cum = noise.fbm(warp * fx + 2.0, y * fy + 5.0, 5)
            cum += 0.16 * noise.fbm(x * fx * 4.1, y * fy * 3.3 + 3, 3) - 0.08
            cir = noise.fbm(warp * fx * 1.3 + 40 + y * 0.02, y * fy * 2.3 + 9, 4)
            field[y * across + x] = max(cum * band, cir * wisp * 0.9)
    return field, rows


def _shade_clouds(px, field, width, horizon, rows, look, sun, cut) -> None:
    """Paint the cloud in ``field`` into ``px``, each part shaded by how much cloud
    lies between it and the light."""
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
            px[i : i + 4] = bytes((*_ramp(ramp, lum, x, y), 255))


def _paint_clouds(px, width, horizon, look, sun, cover, seed) -> None:
    field, rows = _cloud_field(width, horizon, seed)
    _shade_clouds(px, field, width, horizon, rows, look, sun, 0.62 - cover * 0.28)


def cloud_frames(
    width: int,
    horizon: int,
    frames: int,
    drift: int,
    time: str = "sunset",
    sun: tuple[float, float] | None = None,
    clouds: float = 0.5,
    seed: int = 1,
) -> list[Raster]:
    """Clouds that travel ``drift`` pixels over ``frames`` frames and loop: as one bank
    moves on it fades into the next, so the last frame leads back into the first.
    Each picture is ``width`` by ``horizon + 1`` and clear where the sky shows."""
    look = SKIES[time]
    cut = 0.62 - max(0.0, min(1.0, clouds)) * 0.28
    span = abs(drift)
    across = width + span * 2
    field, rows = _cloud_field(width, horizon, seed, span * 2)
    out = []
    for f in range(frames):
        t = f / frames
        moved = round(drift * t)
        first = span - moved
        second = first + (span if drift > 0 else -span)
        level = math.hypot(1 - t, t)
        mixed = [0.0] * (width * rows)
        for y in range(rows):
            a = field[y * across + first : y * across + first + width]
            b = field[y * across + second : y * across + second + width]
            mixed[y * width : (y + 1) * width] = [
                ((1 - t) * p + t * q - cut) / level + cut for p, q in zip(a, b, strict=True)
            ]
        px = bytearray(width * (horizon + 1) * 4)
        _shade_clouds(px, mixed, width, horizon, rows, look, sun, cut)
        out.append(Raster(width, horizon + 1, bytes(px)))
    return out


# For each time of day: the far, middle, and near range as (shadow, mid, lit, haze, hot),
# then snow as (lit, shadow). Far ranges are paler, as air gets in the way.
LANDS = {
    "dawn": (
        [
            ("#5a5a96", "#7a6aa6", "#f0a898", "#c890a8", "#ffc8a0"),
            ("#3e4078", "#564c8a", "#c07a96", "#8a6a98", "#e89a90"),
            ("#22264e", "#2e2e60", "#6a4a7c", "#4a3c6a", "#9a5a78"),
        ],
        ("#fff0e0", "#a898c8"),
    ),
    "day": (
        [
            ("#6a8cc0", "#86a4d0", "#b8cce8", "#a8c4e8", "#d0e0f4"),
            ("#3e6a8a", "#4e8098", "#7aa8a8", "#7aa0c8", "#a0c0d8"),
            ("#1e4a3a", "#2a5e44", "#4a8a58", "#4a7a80", "#6a9a90"),
        ],
        ("#ffffff", "#b8c8e0"),
    ),
    "sunset": (
        [
            ("#3b3478", "#5a4288", "#e98a6e", "#b0608a", "#f39a62"),
            ("#27255e", "#3d2f72", "#a8507e", "#6e3c7c", "#d06a68"),
            ("#141640", "#1e1c50", "#4c2e6c", "#30224f", "#7a3a66"),
        ],
        ("#ffd9b0", "#8f80ba"),
    ),
    "night": (
        [
            ("#1a2452", "#243066", "#4a5a92", "#2a3668", "#5a6aa0"),
            ("#111a40", "#18224e", "#2e3c70", "#1c2854", "#3a4a80"),
            ("#080c24", "#0c1230", "#18224a", "#101838", "#202c58"),
        ],
        ("#c8d4f0", "#5a6896"),
    ),
}
# For each range: how tall it stands against the tallest, how fine its ridge is, and
# how far it dips to let the sun through.
_RANGES = ((1.0, 0.0075, 0.86, 95), (0.48, 0.013, 0.7, 70), (0.22, 0.024, 0.5, 50))


def mountains(
    width: int,
    height: int,
    horizon: int,
    time: str = "sunset",
    sun: tuple[float, float] | None = None,
    size: float = 0.5,
    ranges: int = 3,
    snow: bool = True,
    trees: bool = True,
    seed: int = 1,
) -> Raster:
    """Mountain ranges standing on ``horizon``, clear above their ridges. The tallest
    peak reaches ``size`` (0-1) of the way up from the horizon. Far ranges are paler
    and hazy at the foot, faces toward ``sun`` are lit, and the ranges dip where the
    sun sits so that it shows between them. ``snow`` caps the far range and ``trees``
    puts a treeline on the nearest."""
    if time not in LANDS:
        raise ValueError(f"time must be one of: {', '.join(LANDS)}")
    tones, caps = LANDS[time]
    noise = _Noise(seed + 101)
    px = bytearray(width * height * 4)
    wide = width / 480
    tallest = max(4.0, horizon * max(0.05, min(1.0, size)))
    chosen = {1: [0], 2: [0, 2], 3: [0, 1, 2]}[max(1, min(3, ranges))]

    def put(x: int, y: int, c: str) -> None:
        if 0 <= x < width and 0 <= y < height:
            px[(y * width + x) * 4 : (y * width + x) * 4 + 4] = bytes((*_rgb(c), 255))

    for n in chosen:
        scale, fine, dip, dip_wide = _RANGES[n]
        shade, mid, lit, haze, hot = tones[n]
        offset = seed * 7.3 + n * 13.9
        high, low = tallest * scale, tallest * scale * 0.2

        def ridge(
            x: float, fine=fine, dip=dip, dip_wide=dip_wide, offset=offset, high=high, low=low
        ):
            total, amp, freq, norm = 0.0, 0.5, 1.0, 0.0
            for i in range(5):
                q = 1 - abs(2 * noise.value(x * fine / wide * freq + offset, offset * 1.7 + i) - 1)
                total += amp * q * q
                norm += amp
                amp *= 0.5
                freq *= 2.1
            stand = 1.0
            if sun is not None:
                stand = 1 - dip * math.exp(-(((x - sun[0]) / (dip_wide * wide)) ** 2))
            return horizon - (low + (high - low) * total / norm) * stand

        for x in range(width):
            top_y = ridge(x)
            top = int(top_y)
            tall = horizon - top_y + 1
            slope = ridge(x + 3) - ridge(x - 3)
            toward = 1 if sun is None or x < sun[0] else -1
            near = 0.0 if sun is None else max(0.0, 1 - abs(x - sun[0]) / (170 * wide))
            for y in range(max(0, top), horizon + 1):
                down = y - top
                grain = noise.fbm(
                    (x - down * toward * 0.9) * 0.11 + offset, down * 0.035 + offset, 3
                )
                facing = slope * toward * 0.22 + (grain - 0.5) * 2.6
                c = lit if facing > 0.28 else (mid if facing > -0.1 else shade)
                capped = tall * 0.42 - down - (grain - 0.5) * 14 - max(0, 60 * wide - tall) * 0.5
                if snow and n == 0 and capped > 0:
                    c = caps[0] if facing > 0 else caps[1]
                if (down / tall) ** 1.4 * 0.85 + near * 0.25 > _threshold(x, y) + 0.2:
                    c = haze
                if near**1.5 * 0.95 > _threshold(x + 1, y + 2) + 0.3:
                    c = hot
                put(x, y, c)
            if trees and n == 2 and noise.at(x, 7) > 0.4:
                tree = 2 + int(noise.at(x, 11) * 5)
                for i in range(tree + 1):
                    for xx in range(x - i // 2, x + i // 2 + 1):
                        put(xx, top - tree + i, shade)
    return Raster(width, height, bytes(px))


FLAMES = {
    "fire": ["#fffbe0", "#ffe27a", "#ffb03a", "#ff7a22", "#d03c20", "#7a1c28"],
    "blue": ["#f0fbff", "#b0e8ff", "#5ab8f8", "#2a78e0", "#2440a8", "#161c5a"],
    "green": ["#f6ffe0", "#c8f87a", "#7ad83a", "#3aa82a", "#1c7030", "#0e3a28"],
}
_FLAME_STEPS = (0.78, 0.58, 0.40, 0.24, 0.10)


def fire_frames(
    tall: int,
    frames: int,
    wind: float = 0.0,
    logs: bool = True,
    palette: str = "fire",
    seed: int = 1,
) -> tuple[list[Raster], tuple[int, int]]:
    """A fire ``tall`` pixels high as a loop of ``frames`` pictures: flames that lick
    and sway, and embers that rise and lean with ``wind`` (pixels, negative for left).
    ``logs`` lays crossed logs and stones under it. Returns the pictures and where the
    middle of the fire's base is in them."""
    if palette not in FLAMES:
        raise ValueError(f"palette must be one of: {', '.join(FLAMES)}")
    tones = [_rgb(c) for c in FLAMES[palette]]
    noise = _Noise(seed + 37)
    k = tall / 30
    half = max(2, round(8.5 * k))
    w = int(half * 6 + abs(wind) * 2 + 8)
    h = int(tall * 3.4 + 8)
    cx, by = w // 2, h - 4
    rise = 3 * k
    bend = max(-0.45, min(0.45, wind / half * 0.12))  # flames bend a little; embers travel
    out = []
    for f in range(frames):
        t = f / frames
        level = math.hypot(1 - t, t)
        px = bytearray(w * h * 4)

        def put(x: float, y: float, c: Colour, alpha: int = 255, px=px) -> None:
            x, y = int(x), int(y)
            if 0 <= x < w and 0 <= y < h:
                px[(y * w + x) * 4 : (y * w + x) * 4 + 4] = bytes((*c, alpha))

        if logs:
            reach = max(3, round(8 * k))
            for j in range(-reach, reach + 1):
                lean = int(j * 0.25)
                put(cx + j, by - 1 + lean, (42, 20, 20))
                put(cx + j, by - 2 + lean, tones[3] if j % 3 == 0 else (74, 28, 20))
                put(cx + j, by - 1 - lean, (42, 20, 20))
                put(cx + j, by - 2 - lean, tones[2] if j % 4 == 1 else (58, 24, 20))
            for sx, sy in ((-12, 0), (-9, -2), (11, 0), (9, -2), (-5, 1), (5, 1), (0, 2)):
                for yy in range(3):
                    for xx in range(4):
                        if xx in (0, 3) and yy == 0:
                            continue
                        warm = (sx < 0 and xx >= 2) or (sx > 0 and xx <= 1)
                        stone = (138, 86, 72) if warm else (42, 42, 76)
                        put(cx + sx * k + xx - 2, by + sy + yy - 1, stone)
        for y in range(by - int(tall * 1.15), by - 1):
            up = (by - 2 - y) / tall
            for x in range(cx - half - 2, cx + half + 3):
                side = (x - cx) / half
                lick = x + math.sin(_TAU * t + up * 3) * 2.5 * k
                a = noise.fbm(lick * 0.21 / k, (y + f * rise) * 0.15 / k, 3)
                b = noise.fbm(lick * 0.21 / k, (y + (f - frames) * rise) * 0.15 / k, 3)
                n = (((1 - t) * a + t * b) - 0.5) / level + 0.5
                sway = math.sin(up * 4 - _TAU * t * 2) * 0.25 * up + bend * up * up
                v = 1.05 - (side - sway) ** 2 * (1 + up * 3.2) - max(0.0, up) ** 1.25
                v += (n - 0.5) * 1.2 * (0.35 + up)
                if v > 0.10:
                    put(x, y, tones[next((i for i, s in enumerate(_FLAME_STEPS) if v > s), 4)])
                elif v > 0.02 and _threshold(x, y) < 0.5:
                    put(x, y, tones[5])
        for i in range(14):
            u = (t + i / 14) % 1
            ex = cx + wind * u**1.2 + math.sin(u * 8 + i * 2.1) * 6 * k + (i % 4 - 1.5) * 3 * k
            ey = by - tall * 0.45 - u * tall * 2.3
            tone = tones[1] if u < 0.3 else (tones[3] if u < 0.65 else tones[4])
            put(ex, ey, tone, int(255 * (1 - u * 0.75)))
        out.append(Raster(w, h, bytes(px)))
    return out, (cx, by)


def mist_frames(
    width: int,
    rows: int,
    frames: int = 1,
    drift: int = 0,
    colour: Colour = (154, 134, 192),
    density: float = 0.5,
    sun_x: float | None = None,
    warm: Colour = (255, 217, 160),
    seed: int = 1,
) -> list[Raster]:
    """A band of mist ``rows`` deep, thickest along its middle and thinning to nothing
    at its edges, in a few dithered strengths of ``colour``. Near ``sun_x`` it takes
    on ``warm``. Over ``frames`` it travels ``drift`` pixels and loops, each bank
    fading into the next."""
    noise = _Noise(seed + 211)
    span = abs(drift)
    across = width + span * 2
    cut = 0.36 - max(0.0, min(1.0, density)) * 0.2
    field = [0.0] * (across * rows)
    for y in range(rows):
        thick = math.exp(-(((y - rows / 2) / (rows * 0.24)) ** 2))
        for x in range(across):
            field[y * across + x] = noise.fbm(x * 5.3 / width + 50, y * 4.1 / rows + 20, 4) * thick
    between = tuple((a + b) // 2 for a, b in zip(colour, warm, strict=True))
    out = []
    for f in range(max(1, frames)):
        t = f / max(1, frames)
        moved = round(drift * t)
        first = span - moved
        second = first + (span if drift > 0 else -span)
        level = math.hypot(1 - t, t)
        px = bytearray(width * rows * 4)
        for y in range(rows):
            for x in range(width):
                v = (1 - t) * field[y * across + first + x] + t * field[y * across + second + x]
                a = ((v - 0.3) / level + 0.3 - cut) * 3.2
                if a <= 0:
                    continue
                step = int(min(1.0, a) * 4 + _threshold(x, y))
                if step <= 0:
                    continue
                near = 0.0 if sun_x is None else max(0.0, 1 - abs(x - sun_x) / (width * 0.4))
                tone = warm if near > 0.55 else (between if near > 0.25 else colour)
                i = (y * width + x) * 4
                px[i : i + 4] = bytes((*tone, min(255, step * 38)))
        out.append(Raster(width, rows, bytes(px)))
    return out


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
