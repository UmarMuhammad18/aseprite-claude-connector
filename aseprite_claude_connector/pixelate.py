"""Turning a reference picture into pixel art, and measuring how close art is to it
(stdlib only, no Aseprite needed).

Works on ``Raster`` pixels from ``raster.py``: R, G, B, A bytes, row by row.
"""

from __future__ import annotations

import functools

from .raster import Raster

_BAYER = (0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5)

Color = tuple[int, int, int]


def cropped(src: Raster, x: int, y: int, width: int, height: int) -> Raster:
    """The part of ``src`` inside the rectangle, clipped to the picture."""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(src.width, x + width), min(src.height, y + height)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("the crop is outside the picture")
    stride = src.width * 4
    rows = [src.rgba[y * stride + x0 * 4 : y * stride + x1 * 4] for y in range(y0, y1)]
    return Raster(x1 - x0, y1 - y0, b"".join(rows))


def shrink(src: Raster, width: int, height: int) -> Raster:
    """Area-average down to ``width`` x ``height``: every source pixel counts toward
    the cell it falls in, weighted by alpha, so detail turns into the right colour
    instead of whichever pixel nearest-neighbour happens to land on."""
    if width < 1 or height < 1:
        raise ValueError("the size must be at least 1x1")
    sums = [[0, 0, 0, 0, 0] for _ in range(width * height)]
    xmap = [x * width // src.width for x in range(src.width)]
    data = src.rgba
    for y in range(src.height):
        row = (y * height // src.height) * width
        base = y * src.width * 4
        for x in range(src.width):
            i = base + x * 4
            a = data[i + 3]
            cell = sums[row + xmap[x]]
            cell[0] += data[i] * a
            cell[1] += data[i + 1] * a
            cell[2] += data[i + 2] * a
            cell[3] += a
            cell[4] += 1
    out = bytearray(width * height * 4)
    for n, (r, g, b, a, count) in enumerate(sums):
        if a:
            out[n * 4 : n * 4 + 4] = bytes((r // a, g // a, b // a, round(a / count)))
    return Raster(width, height, bytes(out))


def _opaque(src: Raster, cutoff: int = 128) -> list[Color]:
    data = src.rgba
    return [tuple(data[i : i + 3]) for i in range(0, len(data), 4) if data[i + 3] >= cutoff]


def median_cut(pixels: list[Color], count: int) -> list[Color]:
    """Split the colours into boxes along their widest axis, then nudge each box's
    colour to the mean of the pixels nearest it (a few k-means passes). A few slots
    go to accents: colours far from all the others that still cover a real area,
    like a scatter of pink flowers, which splitting by population would average
    away. Distances are perceptual (see ``_lab``)."""
    if not pixels:
        return []
    accents = count // 6 if count >= 6 else 0
    boxes = [pixels]
    while len(boxes) < count - accents:
        spans = []
        for box in boxes:
            if len(box) < 2:
                spans.append((-1.0, 0))
                continue
            labs = [_lab(p) for p in box]
            ranges = [max(v[c] for v in labs) - min(v[c] for v in labs) for c in range(3)]
            axis = max(range(3), key=ranges.__getitem__)
            spans.append((ranges[axis] * len(box) ** 0.5, axis))
        widest = max(range(len(boxes)), key=lambda i: spans[i][0])
        weight, axis = spans[widest]
        if weight <= 0:
            break
        box = sorted(boxes.pop(widest), key=lambda p: _lab(p)[axis])
        mid = len(box) // 2
        boxes += [box[:mid], box[mid:]]
    centres = [_mean(box) for box in boxes]
    centres += _accents(pixels, centres, accents)
    for _ in range(4):
        nearest = _Nearest(centres)
        groups: list[list[Color]] = [[] for _ in centres]
        for p in pixels:
            groups[nearest[p]].append(p)
        centres = [_mean(g) if g else c for g, c in zip(groups, centres, strict=True)]
    return sorted(set(centres), key=lambda c: _lab(c)[0])


def _accents(pixels: list[Color], centres: list[Color], count: int) -> list[Color]:
    """Up to ``count`` colours, each the one farthest from every colour chosen so far,
    among groups of similar pixels big enough to matter."""
    bins: dict[tuple[int, int, int], list[Color]] = {}
    for p in pixels:
        lab = _lab(p)
        bins.setdefault(
            (round(lab[0] / 0.06), round(lab[1] / 0.06), round(lab[2] / 0.06)), []
        ).append(p)
    floor = max(3, len(pixels) // 1000)
    groups = [(_mean(g), len(g)) for g in bins.values() if len(g) >= floor]
    chosen: list[Color] = []
    for _ in range(count):

        def gap(group):
            return min(_lab_distance(group[0], c) for c in centres + chosen)

        apart = [g for g in groups if gap(g) >= _ACCENT_GAP]
        if not apart:
            break
        chosen.append(max(apart, key=lambda g: gap(g) * g[1] ** 0.5)[0])
    return chosen


def _mean(colors: list[Color]) -> Color:
    n = len(colors)
    return tuple(round(sum(c[i] for c in colors) / n) for i in range(3))


# Hue counts double: two colours as bright as each other but different in hue
# (pink and tan) look further apart than the raw numbers say, and keeping them
# apart is what keeps a picture's accents.
_CHROMA_WEIGHT = 2.0
_ACCENT_GAP = 0.1


@functools.lru_cache(maxsize=1 << 16)
def _lab(c: Color) -> tuple[float, float, float]:
    """sRGB to OKLab, a space where equal distances look about equally different."""

    def linear(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = linear(c[0]), linear(c[1]), linear(c[2])
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        _CHROMA_WEIGHT * (1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_),
        _CHROMA_WEIGHT * (0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_),
    )


def _lab_distance(a: Color, b: Color) -> float:
    p, q = _lab(a), _lab(b)
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2) ** 0.5


def distance(a: Color, b: Color) -> float:
    """Colour difference that weights channels the way eyes do ("redmean")."""
    rm = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db) ** 0.5


class _Nearest(dict):
    """Colour to the index of the closest palette entry, worked out once per colour."""

    def __init__(self, palette: list[Color]):
        super().__init__()
        self.palette = palette

    def __missing__(self, c):
        best = min(range(len(self.palette)), key=lambda i: _lab_distance(c, self.palette[i]))
        self[c] = best
        return best


def quantized(src: Raster, palette: list[Color], dither: str = "none", strength: int = 24):
    """Snap every visible pixel to ``palette``. ``dither`` is ``none``, ``ordered``
    (a 4x4 Bayer pattern, the usual pixel-art look) or ``diffusion``
    (Floyd-Steinberg, closer to the picture but noisier). Mostly-clear pixels go
    fully clear and the rest fully opaque, as pixel art expects."""
    if dither not in ("none", "ordered", "diffusion"):
        raise ValueError("dither must be none, ordered, or diffusion")
    w, h = src.width, src.height
    nearest = _Nearest(palette)
    data = src.rgba
    out = bytearray(w * h * 4)
    err = [[0.0, 0.0, 0.0] for _ in range(w * h)] if dither == "diffusion" else None
    for y in range(h):
        for x in range(w):
            n = y * w + x
            i = n * 4
            if data[i + 3] < 128:
                continue
            c = [data[i], data[i + 1], data[i + 2]]
            if dither == "ordered":
                bump = (_BAYER[(y % 4) * 4 + x % 4] / 16 - 0.5) * strength
                c = [v + bump for v in c]
            elif err is not None:
                c = [v + e for v, e in zip(c, err[n], strict=True)]
            key = tuple(min(255, max(0, round(v))) for v in c)
            pick = palette[nearest[key]]
            out[i : i + 4] = bytes((*pick, 255))
            if err is not None:
                spill = [c[k] - pick[k] for k in range(3)]
                for dx, dy, share in ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)):
                    if 0 <= x + dx < w and y + dy < h:
                        e = err[n + dy * w + dx]
                        for k in range(3):
                            e[k] += spill[k] * share / 16
    return Raster(w, h, bytes(out))


def despeckled(src: Raster) -> Raster:
    """Replace lone pixels whose four neighbours all share one other colour. Shrinking
    a photo leaves these as noise; a pixel artist would never place them."""
    w, h = src.width, src.height
    data = src.rgba
    out = bytearray(data)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = (y * w + x) * 4
            around = [data[j : j + 4] for j in (i - 4, i + 4, i - w * 4, i + w * 4)]
            if around[0] != data[i : i + 4] and all(a == around[0] for a in around[1:]):
                out[i : i + 4] = around[0]
    return Raster(w, h, bytes(out))


def flattened(src: Raster, background: Color = (0, 0, 0)) -> list[Color]:
    """Each pixel's colour over ``background``, so clear areas compare as that colour."""
    data = src.rgba
    out = []
    for i in range(0, len(data), 4):
        a = data[i + 3]
        out.append(tuple((data[i + k] * a + background[k] * (255 - a)) // 255 for k in range(3)))
    return out


def compared(art: Raster, ref: Raster, cells: int = 4) -> dict:
    """How close ``art`` is to ``ref`` (same size): an overall score, a score with
    fine detail blurred away (does the composition and lighting match?), and the
    worst areas of a ``cells`` x ``cells`` grid with what differs there."""
    if (art.width, art.height) != (ref.width, ref.height):
        raise ValueError("the pictures must be the same size")
    w, h = art.width, art.height
    a, r = flattened(art), flattened(ref)
    errors = [distance(p, q) for p, q in zip(a, r, strict=True)]
    close = sum(1 for e in errors if e < 60) / len(errors)
    coarse_w, coarse_h = max(1, w // 4), max(1, h // 4)
    ca, cr = flattened(shrink(art, coarse_w, coarse_h)), flattened(shrink(ref, coarse_w, coarse_h))
    coarse = sum(distance(p, q) for p, q in zip(ca, cr, strict=True)) / len(ca)
    areas = []
    for gy in range(cells):
        for gx in range(cells):
            x0, x1 = gx * w // cells, (gx + 1) * w // cells
            y0, y1 = gy * h // cells, (gy + 1) * h // cells
            idx = [y * w + x for y in range(y0, y1) for x in range(x0, x1)]
            if not idx:
                continue
            mean_a, mean_r = _mean([a[i] for i in idx]), _mean([r[i] for i in idx])
            light = _lightness(mean_a) - _lightness(mean_r)
            areas.append(
                {
                    "x": x0,
                    "y": y0,
                    "width": x1 - x0,
                    "height": y1 - y0,
                    "error": round(sum(errors[i] for i in idx) / len(idx), 1),
                    "art_average": "#" + bytes(mean_a).hex(),
                    "reference_average": "#" + bytes(mean_r).hex(),
                    "art_is": "darker" if light < -12 else "lighter" if light > 12 else "similar",
                }
            )
    areas.sort(key=lambda c: -c["error"])
    return {
        "score": _score(sum(errors) / len(errors)),
        "shape_score": _score(coarse),
        "close_pixels": round(100 * close, 1),
        "worst_areas": areas[: max(3, cells)],
        "errors": errors,
    }


# A mean difference this big scores 0. A single flat colour over a photo scores
# around 45, and a faithful pixelation around 90, so the scale has room to show
# progress.
_SCORE_ZERO = 150.0


def _score(mean_error: float) -> float:
    return round(max(0.0, 100 * (1 - mean_error / _SCORE_ZERO)), 1)


def _lightness(c: Color) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def heatmap(art: Raster, errors: list[float]) -> Raster:
    """The art in grey with red where it differs from the reference."""
    out = bytearray(art.width * art.height * 4)
    for n, (c, e) in enumerate(zip(flattened(art), errors, strict=True)):
        grey = round(_lightness(c) * 0.5)
        heat = min(1.0, e / 100)
        out[n * 4 : n * 4 + 4] = bytes(
            (
                round(grey + (255 - grey) * heat),
                round(grey * (1 - heat)),
                round(grey * (1 - heat)),
                255,
            )
        )
    return Raster(art.width, art.height, bytes(out))
