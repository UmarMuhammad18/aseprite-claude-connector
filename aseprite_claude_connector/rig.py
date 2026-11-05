"""Cut-out animation: characters made of part layers, posed and in-betweened
(stdlib only, no Aseprite needed).

Each part turns about its pivot and moves, and a part with a parent follows it, so a
forearm stays on its upper arm. Rotation samples an 8x Scale2x copy of the part
(the RotSprite idea), which keeps pixel art crisp where plain rotation would jag it.
Works on ``Raster`` pixels from ``raster.py``.
"""

from __future__ import annotations

import math

from .raster import Raster

Affine = tuple[float, float, float, float, float, float]  # x' = a*x + b*y + c, y' = d*x + e*y + f

_IDENTITY: Affine = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def _then(first: Affine, second: Affine) -> Affine:
    """``first`` applied, then ``second``."""
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = second
    return (
        a2 * a1 + b2 * d1,
        a2 * b1 + b2 * e1,
        a2 * c1 + b2 * f1 + c2,
        d2 * a1 + e2 * d1,
        d2 * b1 + e2 * e1,
        d2 * c1 + e2 * f1 + f2,
    )


def _invert(m: Affine) -> Affine:
    a, b, c, d, e, f = m
    det = a * e - b * d
    return (e / det, -b / det, (b * f - e * c) / det, -d / det, a / det, (d * c - a * f) / det)


def local(angle: float, dx: float, dy: float, pivot: tuple[float, float]) -> Affine:
    """Turn ``angle`` degrees clockwise about ``pivot``, then move by (dx, dy)."""
    t = math.radians(angle)
    cos, sin = math.cos(t), math.sin(t)
    px, py = pivot
    return (cos, -sin, px - cos * px + sin * py + dx, sin, cos, py - sin * px - cos * py + dy)


def _scale2x(src: list[bytes], w: int, h: int) -> tuple[list[bytes], int, int]:
    """One Scale2x (EPX) pass: doubles the size, rounding off stair-steps without
    adding colours."""
    out = [b""] * (w * 2 * h * 2)

    def at(x, y):
        return src[min(h - 1, max(0, y)) * w + min(w - 1, max(0, x))]

    for y in range(h):
        for x in range(w):
            p, a, b, c, d = at(x, y), at(x, y - 1), at(x + 1, y), at(x - 1, y), at(x, y + 1)
            e0 = c if c == a and c != d and a != b else p
            e1 = a if a == b and a != c and b != d else p
            e2 = c if d == c and d != b and c != a else p
            e3 = b if b == d and b != a and d != c else p
            row = (y * 2) * w * 2
            out[row + x * 2], out[row + x * 2 + 1] = e0, e1
            out[row + w * 2 + x * 2], out[row + w * 2 + x * 2 + 1] = e2, e3
    return out, w * 2, h * 2


class Part:
    """A part's pixels, trimmed to what it covers, with an 8x copy for turning."""

    def __init__(self, src: Raster):
        w, h = src.width, src.height
        xs = [n % w for n in range(w * h) if src.rgba[n * 4 + 3]]
        ys = [n // w for n in range(w * h) if src.rgba[n * 4 + 3]]
        self.canvas = (w, h)
        self.empty = not xs
        if self.empty:
            return
        self.x0, self.y0 = min(xs), min(ys)
        self.w, self.h = max(xs) - self.x0 + 1, max(ys) - self.y0 + 1
        cells = []
        for y in range(self.y0, self.y0 + self.h):
            for x in range(self.x0, self.x0 + self.w):
                i = (y * w + x) * 4
                cells.append(bytes(src.rgba[i : i + 4]))
        self.cells = cells
        big, bw, bh = cells, self.w, self.h
        for _ in range(3):
            big, bw, bh = _scale2x(big, bw, bh)
        self.big, self.bw = big, bw

    def centre(self) -> tuple[float, float]:
        return (self.x0 + self.w / 2, self.y0 + self.h / 2)

    def draw(self, into: bytearray, m: Affine) -> None:
        """Paint the part through transform ``m`` (part pixels to canvas)."""
        if self.empty:
            return
        cw, ch = self.canvas
        a, b, c, d, e, f = m
        turned = abs(b) > 1e-6 or abs(d) > 1e-6 or a < 0
        if not turned:  # a plain move: copy the pixels exactly
            ox, oy = round(c), round(f)
            for y in range(self.h):
                ty = self.y0 + y + oy
                if not 0 <= ty < ch:
                    continue
                for x in range(self.w):
                    tx = self.x0 + x + ox
                    px = self.cells[y * self.w + x]
                    if px[3] and 0 <= tx < cw:
                        into[(ty * cw + tx) * 4 : (ty * cw + tx) * 4 + 4] = px
            return
        inv = _invert(m)
        corners = [
            (a * x + b * y + c, d * x + e * y + f)
            for x in (self.x0, self.x0 + self.w)
            for y in (self.y0, self.y0 + self.h)
        ]
        tx0 = max(0, math.floor(min(p[0] for p in corners)))
        tx1 = min(cw, math.ceil(max(p[0] for p in corners)))
        ty0 = max(0, math.floor(min(p[1] for p in corners)))
        ty1 = min(ch, math.ceil(max(p[1] for p in corners)))
        ia, ib, ic, id_, ie, if_ = inv
        for ty in range(ty0, ty1):
            for tx in range(tx0, tx1):
                cx, cy = tx + 0.5, ty + 0.5
                sx = (ia * cx + ib * cy + ic - self.x0) * 8
                sy = (id_ * cx + ie * cy + if_ - self.y0) * 8
                if not (0 <= sx < self.bw and 0 <= sy < self.h * 8):
                    continue
                px = self.big[int(sy) * self.bw + int(sx)]
                if px[3]:
                    into[(ty * cw + tx) * 4 : (ty * cw + tx) * 4 + 4] = px


def _ease(k: float, easing: str) -> float:
    return k if easing == "linear" else k * k * (3 - 2 * k)


def pose_at(keys: list[dict], frame: int, frames: int, loop: bool, easing: str) -> tuple:
    """(angle, x, y) at ``frame`` from keyframes sorted by frame. Before the first key
    and after the last, a loop eases back round to the first; otherwise it holds."""
    if not keys:
        return (0.0, 0.0, 0.0)
    values = [(k["frame"], (k.get("angle", 0.0), k.get("x", 0.0), k.get("y", 0.0))) for k in keys]
    if loop:
        first_frame, first = values[0]
        values = (
            [(values[-1][0] - frames, values[-1][1])] + values + [(first_frame + frames, first)]
        )
    if frame <= values[0][0]:
        return values[0][1]
    for (f0, v0), (f1, v1) in zip(values, values[1:], strict=False):
        if f0 <= frame <= f1:
            k = 0.0 if f1 == f0 else _ease((frame - f0) / (f1 - f0), easing)
            return tuple(v0[i] + (v1[i] - v0[i]) * k for i in range(3))
    return values[-1][1]


def world(part: str, frame_poses: dict, pivots: dict, parents: dict) -> Affine:
    """The transform that takes ``part``'s pixels to the canvas: its own pose, then
    each parent's in turn."""
    m = _IDENTITY
    seen = set()
    node = part
    while node is not None and node not in seen:
        seen.add(node)
        angle, dx, dy = frame_poses.get(node, (0.0, 0.0, 0.0))
        m = _then(m, local(angle, dx, dy, pivots[node]))
        node = parents.get(node)
    return m


def render(part: Part, m: Affine) -> Raster:
    w, h = part.canvas
    buf = bytearray(w * h * 4)
    part.draw(buf, m)
    return Raster(w, h, bytes(buf))
