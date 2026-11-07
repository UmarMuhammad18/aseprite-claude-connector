"""Character animation on pixels (stdlib only, no Aseprite needed).

The pieces that make a character act rather than bob:

- ``Eye`` / ``drawn_eye`` — an eye redrawn from its socket: ring, white, a round
  pupil looking anywhere with a catchlight that follows it, lids (flat, arched, or
  slanted for a brow), a smiling lower lid, or shut.
- ``swung`` — a part cut out by an outline and turned about a joint, with shadow left
  where it joined the body so turning never opens a gap, and no light halo.
- ``bobbed`` — the body above a feet line moved, the feet planted (legs stretch).
- ``free_pixels`` — the floating symbols in a box ("!", "?", hearts): pixels not
  joined to the body.

Works on ``Raster`` pixels from ``raster.py``.
"""

from __future__ import annotations

import math
from collections import Counter

from . import rig
from .raster import Raster

RGBA = tuple[int, int, int, int]
CLEAR: RGBA = (0, 0, 0, 0)


class Grid:
    """A mutable RGBA picture, one tuple per pixel."""

    def __init__(self, w: int, h: int, px: list[RGBA] | None = None):
        self.w, self.h = w, h
        self.px = px if px is not None else [CLEAR] * (w * h)

    @classmethod
    def of(cls, r: Raster) -> Grid:
        d = r.rgba
        return cls(r.width, r.height, [tuple(d[i : i + 4]) for i in range(0, len(d), 4)])

    def raster(self) -> Raster:
        return Raster(self.w, self.h, b"".join(bytes(p) for p in self.px))

    def copy(self) -> Grid:
        return Grid(self.w, self.h, list(self.px))

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def get(self, x: int, y: int) -> RGBA:
        return self.px[y * self.w + x] if self.inside(x, y) else CLEAR

    def set(self, x: int, y: int, c: RGBA) -> None:
        if self.inside(x, y):
            self.px[y * self.w + x] = c

    def opaque(self, x: int, y: int) -> bool:
        return self.get(x, y)[3] > 0

    def cells(self):
        for y in range(self.h):
            for x in range(self.w):
                yield x, y


def lum(c: RGBA) -> float:
    return (c[0] + c[1] + c[2]) / 3


def over(dst: Grid, src: Grid, dx: int = 0, dy: int = 0) -> Grid:
    for x, y in src.cells():
        c = src.get(x, y)
        if c[3]:
            dst.set(x + dx, y + dy, c)
    return dst


def polygon_mask(points) -> set[tuple[int, int]]:
    """Cells whose centres are inside the polygon."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    out = set()
    for y in range(math.floor(min(ys)), math.ceil(max(ys)) + 1):
        for x in range(math.floor(min(xs)), math.ceil(max(xs)) + 1):
            cx, cy, inside = x + 0.5, y + 0.5, False
            j = len(points) - 1
            for i in range(len(points)):
                xi, yi = points[i]
                xj, yj = points[j]
                if (yi > cy) != (yj > cy) and cx < (xj - xi) * (cy - yi) / (yj - yi) + xi:
                    inside = not inside
                j = i
            if inside:
                out.add((x, y))
    return out


def box_cells(box) -> list[tuple[int, int]]:
    x0, y0, w, h = box
    return [(x, y) for y in range(y0, y0 + h) for x in range(x0, x0 + w)]


# --- symbols ----------------------------------------------------------------


def free_pixels(g: Grid, box) -> set[tuple[int, int]]:
    """Opaque pixels in ``box`` that aren't joined to anything outside it through
    solid colour: the floating symbols, but not the edge of a wing that crosses the
    box. Light pixels (a white outline round a symbol) don't join things up."""
    inbox = set(box_cells(box))

    def solid(c: RGBA) -> bool:
        return c[3] > 0 and lum(c) < 205

    reached, stack = set(), []
    for x, y in g.cells():
        if (x, y) not in inbox and g.opaque(x, y):
            reached.add((x, y))
            if solid(g.get(x, y)):
                stack.append((x, y))
    while stack:
        x, y = stack.pop()
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if n not in reached and g.opaque(*n):
                reached.add(n)
                if solid(g.get(*n)):
                    stack.append(n)
    return {p for p in inbox if g.opaque(*p) and p not in reached}


def taken(g: Grid, mask) -> Grid:
    """Move the ``mask`` pixels of ``g`` onto a picture of their own."""
    out = Grid(g.w, g.h)
    for x, y in mask:
        if g.opaque(x, y):
            out.set(x, y, g.get(x, y))
            g.set(x, y, CLEAR)
    return out


# --- body -------------------------------------------------------------------


def bobbed(g: Grid, feet: int, dy: int = 0, dx: int = 0) -> Grid:
    """Rows above ``feet`` moved by (dx, dy) while the rows below stay planted. Moving
    up stretches the legs (the row above the feet repeats) rather than leaving a gap."""
    out = Grid(g.w, g.h)
    for y in range(g.h):
        if y < feet:
            sy, sx = min(y - dy, feet - 1), -dx
        else:
            sy, sx = y, 0
        for x in range(g.w):
            if g.inside(x + sx, sy):
                out.set(x, y, g.get(x + sx, sy))
    return out


def swung(
    g: Grid, outline, pivot, angle: float, dx: float = 0, dy: float = 0, band: int = 3, shadow=None
) -> Grid:
    """The part inside ``outline`` turned ``angle`` degrees clockwise about ``pivot``
    and moved by (dx, dy). Where the part met the rest of the picture, a ``band`` of
    ``shadow`` (the part's darkest colour by default) stays underneath, so turning it
    opens no gap; light halo pixels on the part's outer edge are dropped so they
    don't streak across the body."""
    out = g.copy()
    mask = polygon_mask(outline)
    part = taken(out, mask)
    for x, y in list(part.cells()):
        c = part.get(x, y)
        if c[3] and min(c[:3]) > 175:
            if any(not g.opaque(x + a, y + b) for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                part.set(x, y, CLEAR)
    colours = [part.get(*p) for p in part.cells() if part.opaque(*p)]
    if not colours:
        return out
    shade = shadow or min(colours, key=lum)
    rest = {p for p in out.cells() if out.opaque(*p)}
    for x, y in part.cells():
        if part.opaque(x, y) and any(
            (x + a, y + b) in rest for a in range(-band, band + 1) for b in range(-band, band + 1)
        ):
            out.set(x, y, shade)
    piece = rig.Part(part.raster())
    buf = bytearray(g.w * g.h * 4)
    piece.draw(buf, rig.local(angle, dx, dy, tuple(pivot)))
    return over(out, Grid.of(Raster(g.w, g.h, bytes(buf))))


# --- eyes -------------------------------------------------------------------


def _near(x, y, cx, cy, rx, ry) -> float:
    return ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2


def _ring(cx, cy, rx, ry, a, b) -> list[tuple[int, int]]:
    """Cells between the ellipses scaled out by ``a`` and ``b`` pixels."""
    span = box_cells((int(cx - rx) - 5, int(cy - ry) - 5, int(rx * 2) + 11, int(ry * 2) + 11))
    return [
        (x, y)
        for x, y in span
        if _near(x, y, cx, cy, rx + b, ry + b) <= 1 and _near(x, y, cx, cy, rx + a, ry + a) > 1
    ]


def _darker(c: RGBA, k: float) -> RGBA:
    return (round(c[0] * k), round(c[1] * k), round(c[2] * k), 255)


def eye_style(g: Grid, socket) -> dict:
    """The colours an eye in ``g`` already uses, read from around its socket: the
    ring just outside it, the skin beyond, the lightest (white) and darkest (pupil)
    colours inside. Falls back to clean defaults where the eye has none (an eye
    hidden behind sunglasses)."""
    cx, cy, rx, ry = socket
    inside = [
        g.get(x, y)
        for x, y in box_cells((int(cx - rx), int(cy - ry), int(rx * 2) + 2, int(ry * 2) + 2))
        if _near(x, y, cx, cy, rx, ry) <= 1 and g.opaque(x, y)
    ]
    rim = Counter(g.get(*p) for p in _ring(cx, cy, rx, ry, 0.2, 1.6) if g.opaque(*p))
    skin = Counter(g.get(*p) for p in _ring(cx, cy, rx, ry, 2.4, 3.8) if g.opaque(*p))
    white = max(inside, key=lum) if inside else (250, 248, 244, 255)
    pupil = min(inside, key=lum) if inside else (26, 23, 30, 255)
    if lum(white) - lum(pupil) < 80:  # no real eye in there (hidden, or flat colour)
        white, pupil = (250, 248, 244, 255), (26, 23, 30, 255)
    if lum(white) < 170:
        white = (250, 248, 244, 255)
    if lum(pupil) > 90:
        pupil = (26, 23, 30, 255)
    ring = rim.most_common(1)[0][0] if rim else (247, 193, 66, 255)
    return {
        "ring": ring,
        "ring_shadow": _darker(ring, 0.7),
        "skin": skin.most_common(1)[0][0] if skin else _darker(ring, 0.35),
        "white": white,
        "pupil": pupil,
    }


def drawn_eye(
    g: Grid,
    socket,
    style: dict,
    look=(0.0, 0.0),
    pupil=None,
    lid: float = 0.0,
    arc: float = 0.0,
    slant: float = 0.0,
    smile: float = 0.0,
    closed: bool = False,
    catch: int = 2,
) -> Grid:
    """Paint a whole eye over whatever was there. ``socket`` is (cx, cy, rx, ry), the
    area inside the ring. The pupil, ``pupil`` = (rx, ry) or about half the socket,
    looks ``look`` pixels from the centre. ``lid`` lowers the upper lid (0..1);
    ``arc`` curves its edge (higher in the middle: relaxed or happy) and ``slant``
    tilts it (pixels of drop per pixel across, + = lower on the right). ``smile``
    pushes a lower lid up in an arch. ``closed`` shuts it to a relaxed line."""
    cx, cy, rx, ry = socket
    skin, white, dark = style["skin"], style["white"], style["pupil"]
    span = box_cells((int(cx - rx) - 5, int(cy - ry) - 5, int(rx * 2) + 11, int(ry * 2) + 11))
    for x, y in span:  # clear the old eye, ring and all
        if g.opaque(x, y) and _near(x, y, cx, cy, rx + 2.7, ry + 2.3) <= 1:
            g.set(x, y, skin)
    inner = {(x, y) for x, y in span if _near(x, y, cx, cy, rx, ry) <= 1}
    for x, y in _ring(cx, cy, rx, ry, 0, 1.05):
        g.set(x, y, style["ring"] if y + 0.5 < cy + ry * 0.45 else style["ring_shadow"])
    if closed:
        for p in inner:
            g.set(*p, skin)
        for x in range(math.floor(cx - rx), math.ceil(cx + rx) + 1):
            k = (x + 0.5 - cx) / rx
            y = round(cy + 1.6 - 1.4 * k * k)  # lowest in the middle: relaxed, not sad
            for yy in (y, y - 1, y + 1):
                if (x, yy) in inner:
                    g.set(x, yy, dark)
                    break
        return g
    px, py = cx + look[0], cy + look[1]
    prx, pry = pupil or (max(1.2, rx * 0.5), max(1.5, ry * 0.62))
    for x, y in inner:
        on = ((x + 0.5 - px) / prx) ** 2 + ((y + 0.5 - py) / pry) ** 2 <= 1
        g.set(x, y, dark if on else white)
    hx, hy = int(px - prx * 0.45), int(py - pry * 0.25)
    for p in [(hx + a, hy + b) for a in range(catch) for b in range(catch)]:
        if p in inner:
            g.set(*p, white)
    if smile:
        for x, y in inner:
            k = ((x + 0.5 - cx) / rx) ** 2
            if y + 0.5 > cy + ry - ry * 2 * smile * (1 - 0.75 * k):
                g.set(x, y, skin)
    if lid:
        top, edge = cy - ry, {}
        for x, y in inner:
            k = ((x + 0.5 - cx) / rx) ** 2
            limit = top + ry * 2 * lid * (1 - arc + arc * k) + slant * (x + 0.5 - cx)
            if y + 0.5 < limit:
                g.set(x, y, skin)
            else:
                edge[x] = min(edge.get(x, 1 << 20), y)
        for x, y in edge.items():
            g.set(x, y, dark)
    return g


def colours_of(g: Grid) -> Counter:
    return Counter(p[:3] for p in g.px if p[3])


# --- consistency across sprites ------------------------------------------------


def merged_palette(counts: list[Counter], tolerance: float = 0.045) -> tuple[dict, list[dict]]:
    """One palette for several sprites. Colours closer than ``tolerance`` (OKLab, as
    ``pixelate`` measures it) form a group. A group is drift when its colours stand in
    for each other, some sprites using one and some another, the way separately
    pixelated poses come out; colours every sprite uses side by side are deliberate
    shading steps and stay apart. Returns the mapping that merges each drifting group
    into its most used colour, and every group with the sprites (by index) it's in
    and whether it drifts."""
    from .pixelate import _lab_distance

    total: Counter = Counter()
    for c in counts:
        total.update(c)
    reps: list[tuple[int, int, int]] = []
    members: dict[tuple, list[tuple]] = {}
    for colour, _ in total.most_common():
        home = next((r for r in reps if _lab_distance(colour, r) <= tolerance), None)
        if home is None:
            reps.append(colour)
            members[colour] = [colour]
        else:
            members[home].append(colour)
    mapping, groups = {}, []
    for r, ms in members.items():
        if len(ms) < 2:
            continue
        users = [i for i, c in enumerate(counts) if any(m in c for m in ms)]
        drifts = any(not all(m in counts[i] for m in ms) for i in users)
        if drifts:
            mapping.update({m: r for m in ms if m != r})
        groups.append(
            {"keep": r, "merge": [m for m in ms if m != r], "sprites": users, "drift": drifts}
        )
    return mapping, groups
