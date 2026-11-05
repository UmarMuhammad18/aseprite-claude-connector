"""Building and animating scenes at pixel resolution (stdlib only, no Aseprite needed).

- ``ambient_frames`` — a looping animation of one layer: wind, water shimmer, and a
  light glint. Pixels only ever move or brighten toward one colour, so the art keeps
  its palette.
- ``particle_frames`` — motes, snow, rain, or embers on transparency, looping.
- ``split_regions`` — which seed each pixel belongs to, growing every seed along
  paths of similar colour, so parts separate at their real edges.
- ``extended`` — a bigger canvas whose new margins continue the picture's texture.
- ``cleaned`` — specks merged into their surroundings and edges firmed up, using
  only colours already in the art.

Every motion completes whole cycles over the loop, so the last frame flows into the
first. Works on ``Raster`` pixels from ``raster.py``.
"""

from __future__ import annotations

import heapq
import math
import random

from .pixelate import _lab
from .raster import Raster

TAU = 2 * math.pi
Color = tuple[int, int, int]


def _lab_gap(a, b) -> float:
    p, q = _lab(a), _lab(b)
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2) ** 0.5


# --- ambient motion -----------------------------------------------------------


def ambient_frames(
    src: Raster,
    frames: int,
    *,
    wind: float = 0.0,
    wavelength: int = 48,
    shimmer: float = 0.0,
    glint: float = 0.0,
    glint_color: Color = (255, 236, 190),
) -> list[Raster]:
    """``frames`` looping frames of ``src``. ``wind`` is how many pixels a gust
    pushes things sideways as it rolls left to right, one crest per ``wavelength``
    pixels. ``shimmer`` wobbles each row like a reflection on water. ``glint`` (0-1)
    sweeps a band of light across the bright pixels once per loop."""
    w, h = src.width, src.height
    data = src.rgba
    light = [0.0] * (w * h)
    if glint:
        for n in range(w * h):
            i = n * 4
            if data[i + 3] >= 128:
                light[n] = _lab(tuple(data[i : i + 3]))[0]
    out = []
    for f in range(frames):
        t = f / frames
        buf = bytearray(len(data))
        sweep = t / 0.6  # the glint crosses in the first 60% of the loop, then rests
        reach = w + h * 0.7
        centre = -0.15 * reach + sweep * 1.3 * reach if sweep <= 1 else None
        for y in range(h):
            row = round(shimmer * math.sin(TAU * (t + y / 5))) if shimmer else 0
            gust_y = 0.35 * math.sin(TAU * (2 * t - y / max(8, h / 2)))
            for x in range(w):
                dx = row
                if wind:
                    dx += round(wind * (math.sin(TAU * (t - x / wavelength)) + gust_y))
                sx = min(w - 1, max(0, x - dx))
                si, di = (y * w + sx) * 4, (y * w + x) * 4
                if data[si + 3] < 128 <= data[di + 3]:
                    si = di  # never open a gap: a part's edge stays covered
                px = data[si : si + 4]
                if centre is not None and px[3] >= 128:
                    band = math.exp(-((((x + y * 0.7) - centre) / max(4, w / 24)) ** 2))
                    k = glint * band * max(0.0, (light[y * w + sx] - 0.35) / 0.4)
                    k = round(min(1.0, k) * 3) / 3  # three steps, so few new colours
                    if k:
                        px = bytes(
                            (
                                *(round(px[c] + (glint_color[c] - px[c]) * k) for c in range(3)),
                                px[3],
                            )
                        )
                buf[di : di + 4] = px
        out.append(Raster(w, h, bytes(buf)))
    return out


_PARTICLE_COLOURS = {
    "motes": [(255, 236, 180), (240, 200, 130), (255, 214, 150)],
    "snow": [(245, 248, 255), (214, 224, 240)],
    "rain": [(170, 196, 225), (130, 160, 200)],
    "embers": [(255, 196, 90), (255, 120, 40), (220, 60, 30)],
}


def particle_frames(
    width: int,
    height: int,
    frames: int,
    kind: str,
    count: int,
    colors: list[Color] | None = None,
    seed: int = 1,
) -> list[Raster]:
    """Looping particles on transparency. ``motes`` hover and twinkle, ``snow``
    drifts down, ``rain`` streaks down at a slant, and ``embers`` rise and flicker.
    Falling and rising particles cross the canvas a whole number of times per loop."""
    if kind not in _PARTICLE_COLOURS:
        raise ValueError("kind must be motes, snow, rain, or embers")
    colors = colors or _PARTICLE_COLOURS[kind]
    rng = random.Random(seed)
    span = height + 6
    specs = [
        {
            "x": rng.uniform(0, width),
            "y": rng.uniform(0, height),
            "phase": rng.uniform(0, TAU),
            "laps": rng.choice((1, 1, 2)) if kind != "rain" else rng.choice((3, 4)),
            "beat": rng.choice((1, 2)),
            "color": rng.choice(colors),
            "big": rng.random() < 0.3,
        }
        for _ in range(count)
    ]
    out = []
    for f in range(frames):
        t = f / frames
        buf = bytearray(width * height * 4)

        def put(x, y, c, a, buf=buf):
            x, y = int(round(x)) % width, int(round(y))
            if 0 <= y < height:
                i = (y * width + x) * 4
                if buf[i + 3] < a:
                    buf[i : i + 4] = bytes((*c, a))

        for p in specs:
            c = p["color"]
            if kind == "motes":
                x = p["x"] + 3 * math.sin(TAU * t + p["phase"])
                y = p["y"] + 2.5 * math.sin(TAU * 2 * t + p["phase"] * 1.7)
                glow = 0.5 + 0.5 * math.sin(TAU * p["beat"] * t + p["phase"])
                if glow < 0.2:
                    continue
                a = int(120 + 135 * glow)
                put(x, y, c, a)
                if p["big"] and glow > 0.55:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        put(x + dx, y + dy, c, a // 3)
            elif kind == "snow":
                y = (p["y"] + t * p["laps"] * span) % span - 3
                x = p["x"] + 2 * math.sin(TAU * t + p["phase"])
                put(x, y, c, 235)
                if p["big"]:
                    put(x + 1, y, c, 150)
                    put(x, y + 1, c, 150)
            elif kind == "rain":
                y = (p["y"] + t * p["laps"] * span) % span - 3
                x = p["x"] - (y * 0.25)
                for k in range(3):
                    put(x - k * 0.25, y - k, c, 200 - k * 50)
            else:  # embers
                y = (p["y"] - t * p["laps"] * span) % span - 3
                x = p["x"] + 2.5 * math.sin(TAU * 2 * t + p["phase"])
                flick = 0.5 + 0.5 * math.sin(TAU * p["beat"] * t + p["phase"])
                tone = colors[min(len(colors) - 1, int((1 - flick) * len(colors)))]
                put(x, y, tone, int(150 + 105 * flick))
        out.append(Raster(width, height, bytes(buf)))
    return out


# --- splitting into parts -------------------------------------------------------


def split_regions(src: Raster, seeds: list[tuple[int, int, int]]) -> list[int]:
    """The seed label each pixel belongs to (-1 for clear pixels). Each seed grows
    along the cheapest path, where stepping between different colours costs more,
    so a part stops at its outline even when colours repeat elsewhere."""
    w, h = src.width, src.height
    data = src.rgba
    opaque = [data[n * 4 + 3] >= 128 for n in range(w * h)]
    colour = [tuple(data[n * 4 : n * 4 + 3]) for n in range(w * h)]
    cost = [math.inf] * (w * h)
    label = [-1] * (w * h)
    heap = []
    for x, y, lab in seeds:
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError(f"seed ({x}, {y}) is outside the {w}x{h} canvas")
        n = y * w + x
        if not opaque[n]:
            raise ValueError(f"seed ({x}, {y}) is on a clear pixel")
        cost[n], label[n] = 0.0, lab
        heapq.heappush(heap, (0.0, n))
    while heap:
        c, n = heapq.heappop(heap)
        if c > cost[n]:
            continue
        x, y = n % w, n // w
        for m in (n - 1 if x else -1, n + 1 if x < w - 1 else -1, n - w, n + w):
            if m < 0 or m >= w * h or not opaque[m]:
                continue
            step = 0.002 + _lab_gap(colour[n], colour[m]) ** 2 * 4
            if c + step < cost[m]:
                cost[m], label[m] = c + step, label[n]
                heapq.heappush(heap, (c + step, m))
    first = seeds[0][2]
    for n in range(w * h):
        if opaque[n] and label[n] == -1:
            label[n] = first  # islands no seed can reach go with the first part
    # one smoothing pass: a pixel outvoted by three neighbours joins them
    smooth = label[:]
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            n = y * w + x
            if label[n] < 0:
                continue
            around = [label[n - 1], label[n + 1], label[n - w], label[n + w]]
            for lab in set(around):
                if lab >= 0 and lab != label[n] and around.count(lab) >= 3:
                    smooth[n] = lab
    return smooth


def part(src: Raster, labels: list[int], which: int) -> Raster:
    """Just the pixels labelled ``which``, on transparency."""
    out = bytearray(len(src.rgba))
    for n, lab in enumerate(labels):
        if lab == which:
            out[n * 4 : n * 4 + 4] = src.rgba[n * 4 : n * 4 + 4]
    return Raster(src.width, src.height, bytes(out))


# --- extending the canvas -------------------------------------------------------


def extended(
    src: Raster,
    left: int,
    right: int,
    top: int,
    bottom: int,
    sample: tuple[int, int, int, int] | None = None,
    patch: int = 6,
    seed: int = 1,
) -> Raster:
    """``src`` on a bigger canvas, with the new margins filled by patches copied from
    ``sample`` (x, y, width, height in ``src``; all of it by default). Patches go
    in nearest-first and each is the best match for the pixels already beside it,
    so texture runs on from the picture without new colours or a visible seam."""
    w, h = src.width + left + right, src.height + top + bottom
    sx0, sy0, sw, sh = sample or (0, 0, src.width, src.height)
    sx0, sy0 = max(0, sx0), max(0, sy0)
    sw, sh = min(sw, src.width - sx0), min(sh, src.height - sy0)
    patch = max(3, min(patch, sw, sh))
    if sw < 3 or sh < 3:
        raise ValueError("the sample area must be at least 3x3 inside the picture")
    out = bytearray(w * h * 4)
    filled = bytearray(w * h)
    for y in range(src.height):
        row = src.rgba[y * src.width * 4 : (y + 1) * src.width * 4]
        start = ((y + top) * w + left) * 4
        out[start : start + len(row)] = row
        filled[(y + top) * w + left : (y + top) * w + left + src.width] = b"\x01" * src.width
    rng = random.Random(seed)
    spots = [
        (sx0 + rng.randrange(sw - patch + 1), sy0 + rng.randrange(sh - patch + 1))
        for _ in range(1200)
    ]
    step = max(1, patch - max(2, patch // 3))
    inner = (left, top, left + src.width, top + src.height)

    def distance_out(px, py):
        cx, cy = px + patch / 2, py + patch / 2
        dx = max(inner[0] - cx, 0, cx - inner[2])
        dy = max(inner[1] - cy, 0, cy - inner[3])
        return dx + dy

    places = sorted(
        (
            (px, py)
            for py in range(-patch + 1, h, step)
            for px in range(-patch + 1, w, step)
            if any(
                not filled[y * w + x]
                for y in range(max(0, py), min(h, py + patch))
                for x in range(max(0, px), min(w, px + patch))
            )
        ),
        key=lambda p: distance_out(*p),
    )
    data = src.rgba
    for px, py in places:
        cells = [
            (x, y)
            for y in range(max(0, py), min(h, py + patch))
            for x in range(max(0, px), min(w, px + patch))
        ]
        known = [(x, y) for x, y in cells if filled[y * w + x]]
        if len(known) == len(cells):
            continue
        tried = rng.sample(spots, min(160, len(spots)))
        scored = []
        for ox, oy in tried:
            err = 0
            for x, y in known:
                a = (y * w + x) * 4
                b = ((oy + y - py) * src.width + ox + x - px) * 4
                err += sum((out[a + c] - data[b + c]) ** 2 for c in range(4))
            scored.append((err, ox, oy))
        scored.sort()
        best = scored[0][0]
        choice = rng.choice([s for s in scored if s[0] <= best * 1.1 + 1])
        _, ox, oy = choice
        for x, y in cells:
            if not filled[y * w + x]:
                a = (y * w + x) * 4
                b = ((oy + y - py) * src.width + ox + x - px) * 4
                out[a : a + 4] = data[b : b + 4]
                filled[y * w + x] = 1
    return Raster(w, h, bytes(out))


# --- cleaning up ------------------------------------------------------------------


def cleaned(
    src: Raster, min_region: int = 3, firm_edges: bool = True, tolerance: float = 0.12
) -> tuple[Raster, dict]:
    """Merge each patch of one colour smaller than ``min_region`` pixels into the
    colour that surrounds it most, if that colour is within ``tolerance`` of it: noise
    goes, but a speck that stands out (a flower, a glint) stays. Then
    (``firm_edges``) give the dark side of each strong edge the next darker colour of
    its own hue, the way a pixel artist defines a form. Only colours already in the
    art are used."""
    w, h = src.width, src.height
    px = [bytes(src.rgba[n * 4 : n * 4 + 4]) for n in range(w * h)]
    merged = 0
    for _ in range(1):
        seen = [False] * (w * h)
        for start in range(w * h):
            if seen[start]:
                continue
            region, stack, border = [], [start], {}
            seen[start] = True
            while stack:
                n = stack.pop()
                region.append(n)
                x, y = n % w, n // w
                for m, ok in (
                    (n - 1, x > 0),
                    (n + 1, x < w - 1),
                    (n - w, y > 0),
                    (n + w, y < h - 1),
                ):
                    if not ok:
                        continue
                    if px[m] == px[start]:
                        if not seen[m]:
                            seen[m] = True
                            stack.append(m)
                    else:
                        border[px[m]] = border.get(px[m], 0) + 1
            if len(region) < min_region and border:
                fill = max(border, key=lambda c: (border[c], -abs(c[3] - px[start][3])))
                same_kind = (fill[3] >= 128) == (px[start][3] >= 128)
                if same_kind and fill[3] >= 128 and _lab_gap(fill[:3], px[start][:3]) > tolerance:
                    continue
                for n in region:
                    px[n] = fill
                merged += len(region)
    firmed = 0
    if firm_edges:
        palette = sorted({p[:3] for p in px if p[3] >= 128}, key=lambda c: _lab(c)[0])
        labs = {c: _lab(c) for c in palette}
        darker: dict[Color, Color | None] = {}
        for c in palette:
            lc = labs[c]
            options = [d for d in palette if labs[d][0] < lc[0] - 0.03]
            best = min(
                options,
                key=lambda d: (
                    (labs[d][0] - (lc[0] - 0.09)) ** 2
                    + (labs[d][1] - lc[1]) ** 2
                    + (labs[d][2] - lc[2]) ** 2
                ),
                default=None,
            )
            if best is not None and _lab_gap(best, c) < 0.2:
                darker[c] = best
        base = px[:]
        for n in range(w * h):
            p = base[n]
            if p[3] < 128 or darker.get(p[:3]) is None:
                continue
            x, y = n % w, n // w
            lp = labs[p[:3]][0]
            edges = 0
            for m, ok in ((n - 1, x > 0), (n + 1, x < w - 1), (n - w, y > 0), (n + w, y < h - 1)):
                if ok and base[m][3] >= 128:
                    q = base[m][:3]
                    if labs[q][0] - lp > 0.16 and _lab_gap(p[:3], q) > 0.28:
                        edges += 1
            if edges:
                px[n] = bytes((*darker[p[:3]], p[3]))
                firmed += 1
    return Raster(w, h, b"".join(px)), {"merged_pixels": merged, "firmed_pixels": firmed}
