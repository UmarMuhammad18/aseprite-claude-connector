"""Tiles that repeat: seamless textures and autotile sets for game maps (stdlib only,
no Aseprite needed).

- ``seamless`` — a texture made to repeat with no visible edge: it is shifted by
  half so the old edges meet in the middle, then that cross is rebuilt from patches
  of the texture itself.
- ``autotiles`` — the 47 tiles a map needs for one terrain over another: every
  combination of edges and corners, from one fill texture and an optional base.
- ``godot_tileset`` / ``unity_rule_tile`` — the files that make each engine paint
  with them.

Works on ``Raster`` pixels from ``raster.py``.
"""

from __future__ import annotations

import math
import random

from .oklab import to_lab
from .raster import Raster

# --- seamless -------------------------------------------------------------------


def seamless(src: Raster, band: int | None = None, patch: int = 6, seed: int = 1) -> Raster:
    """``src`` shifted by half and with the cross where its edges now meet rebuilt,
    so it tiles with no seam. ``band`` is how wide a strip is rebuilt (an eighth of
    the size by default)."""
    w, h = src.width, src.height
    band = band or max(2, min(w, h) // 8)
    data = src.rgba
    shifted = bytearray(len(data))
    for y in range(h):
        for x in range(w):
            sx, sy = (x + w // 2) % w, (y + h // 2) % h
            shifted[(y * w + x) * 4 : (y * w + x) * 4 + 4] = data[
                (sy * w + sx) * 4 : (sy * w + sx) * 4 + 4
            ]
    filled = bytearray(w * h)
    cx, cy = w // 2, h // 2
    for y in range(h):
        for x in range(w):
            if abs(x - cx) > band // 2 and abs(y - cy) > band // 2:
                filled[y * w + x] = 1
    patch = max(3, min(patch, w // 2, h // 2))
    rng = random.Random(seed)
    spots = [(rng.randrange(w), rng.randrange(h)) for _ in range(600)]
    step = max(1, patch - max(1, patch // 3))
    holes = [
        (px, py)
        for py in range(cy - band - patch, cy + band + 1, step)
        for px in range(-patch + 1, w, step)
    ] + [
        (px, py)
        for px in range(cx - band - patch, cx + band + 1, step)
        for py in range(-patch + 1, h, step)
    ]
    holes.sort(key=lambda p: -min(abs(p[0] + patch / 2 - cx), abs(p[1] + patch / 2 - cy)))
    out = shifted

    def at(buf, x, y):
        i = ((y % h) * w + (x % w)) * 4
        return buf[i : i + 4]

    for px, py in holes:
        cells = [(x % w, y % h) for y in range(py, py + patch) for x in range(px, px + patch)]
        if all(filled[y * w + x] for x, y in cells):
            continue
        known = [(x, y) for x, y in cells if filled[y * w + x]]
        best, pick = None, None
        for ox, oy in rng.sample(spots, 120):
            err = 0
            for x, y in known:
                a = at(out, x, y)
                b = at(out, ox + (x - px) % w, oy + (y - py) % h)
                err += sum((a[c] - b[c]) ** 2 for c in range(4))
            if best is None or err < best:
                best, pick = err, (ox, oy)
        ox, oy = pick
        for x, y in cells:
            if not filled[y * w + x]:
                src_px = at(out, ox + (x - px) % w, oy + (y - py) % h)
                out[(y * w + x) * 4 : (y * w + x) * 4 + 4] = src_px
                filled[y * w + x] = 1
    return Raster(w, h, bytes(out))


# --- autotiles ------------------------------------------------------------------

N, NE, E, SE, S, SW, W, NW = 1, 2, 4, 8, 16, 32, 64, 128


def blob_masks() -> list[int]:
    """The 47 neighbour patterns of a blob autotile set. A corner only matters when
    both sides beside it are there, which folds 256 patterns down to 47."""
    seen = []
    for m in range(256):
        r = m & (N | E | S | W)
        for corner, a, b in ((NE, N, E), (SE, S, E), (SW, S, W), (NW, N, W)):
            if m & corner and m & a and m & b:
                r |= corner
        if r not in seen:
            seen.append(r)
    seen.sort(key=lambda r: (-bin(r & (N | E | S | W)).count("1"), -bin(r).count("1"), r))
    return seen


def _wave(t: float, size: int, depth: float) -> float:
    """A gentle wobble along an edge that repeats every tile, so edges meet up."""
    return depth * (
        0.5 * math.sin(2 * math.pi * t / size) + 0.3 * math.sin(4 * math.pi * t / size + 1)
    )


def _inside(mask: int, x: float, y: float, size: int, edge: float) -> bool:
    """Whether a point of a tile with neighbours ``mask`` is fill, not base."""
    near = []
    if not mask & N:
        near.append(y - _wave(x, size, edge / 3))
    if not mask & S:
        near.append(size - y - _wave(x + size / 2, size, edge / 3))
    if not mask & W:
        near.append(x - _wave(y + size / 3, size, edge / 3))
    if not mask & E:
        near.append(size - x - _wave(y + 2 * size / 3, size, edge / 3))
    if any(d < edge for d in near):
        return False
    # an outer corner, where two missing sides meet, is rounded off
    for sides, cx, cy in ((N | W, 0, 0), (N | E, size, 0), (S | W, 0, size), (S | E, size, size)):
        if not mask & sides:
            r = edge * 2
            dx, dy = abs(x - cx), abs(y - cy)
            if dx < r and dy < r and math.hypot(r - dx, r - dy) > r - edge:
                return False
    # an inner corner, where both sides are there but the diagonal isn't, is notched
    for corner, sides, cx, cy in (
        (NE, N | E, size, 0),
        (SE, S | E, size, size),
        (SW, S | W, 0, size),
        (NW, N | W, 0, 0),
    ):
        if mask & sides == sides and not mask & corner and math.hypot(x - cx, y - cy) < edge:
            return False
    return True


def _darker(c: tuple[int, int, int], palette: list[tuple[int, int, int]]):
    lc = to_lab(c)
    options = [p for p in palette if to_lab(p)[0] < lc[0] - 0.04]
    if not options:
        return tuple(max(0, round(v * 0.7)) for v in c)
    return min(
        options,
        key=lambda p: (
            (to_lab(p)[0] - (lc[0] - 0.12)) ** 2
            + 4 * ((to_lab(p)[1] - lc[1]) ** 2 + (to_lab(p)[2] - lc[2]) ** 2)
        ),
    )


def autotiles(
    fill: Raster,
    size: int,
    base: Raster | None = None,
    edge: int | None = None,
    outline: bool = True,
    columns: int = 8,
) -> tuple[Raster, list[int]]:
    """The 47-tile blob set for ``fill`` over ``base`` (clear without one), laid out
    ``columns`` wide. Both textures are read from their top-left ``size`` square, so
    make them seamless first. ``edge`` is how far in from a missing neighbour the
    fill stops. ``outline`` gives the fill's border its own darker shade. Returns
    the sheet and each tile's neighbour mask, in order."""
    edge = edge if edge is not None else max(2, size // 5)
    masks = blob_masks()
    rows = -(-len(masks) // columns)
    sw, sh = columns * size, rows * size

    def texel(src: Raster | None, x: int, y: int) -> bytes:
        if src is None:
            return bytes(4)
        i = ((y % min(size, src.height)) * src.width + (x % min(size, src.width))) * 4
        return bytes(src.rgba[i : i + 4])

    palette = sorted(
        {tuple(fill.rgba[i : i + 3]) for i in range(0, len(fill.rgba), 4) if fill.rgba[i + 3]}
    )
    shade = {c: _darker(c, palette) for c in palette}
    out = bytearray(sw * sh * 4)
    for n, mask in enumerate(masks):
        ox, oy = (n % columns) * size, (n // columns) * size
        inside = [
            [_inside(mask, x + 0.5, y + 0.5, size, edge) for x in range(size)] for y in range(size)
        ]
        for y in range(size):
            for x in range(size):
                if inside[y][x]:
                    px = texel(fill, x, y)
                    border = any(
                        0 <= x + dx < size and 0 <= y + dy < size and not inside[y + dy][x + dx]
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    )
                    if outline and border and px[3]:
                        px = bytes((*shade[tuple(px[:3])], px[3]))
                else:
                    px = texel(base, x, y)
                i = ((oy + y) * sw + ox + x) * 4
                out[i : i + 4] = px
    return Raster(sw, sh, bytes(out)), masks


# --- engine files ---------------------------------------------------------------

_GODOT_BITS = (
    (N, "top_side"),
    (NE, "top_right_corner"),
    (E, "right_side"),
    (SE, "bottom_right_corner"),
    (S, "bottom_side"),
    (SW, "bottom_left_corner"),
    (W, "left_side"),
    (NW, "top_left_corner"),
)


def godot_tileset(texture_res: str, size: int, masks: list[int], columns: int, terrain: str) -> str:
    """A Godot 4 TileSet with one terrain in "match corners and sides" mode, so
    painting with the terrain picks the right tile for every neighbour."""
    lines = [
        '[gd_resource type="TileSet" load_steps=3 format=3]',
        "",
        f'[ext_resource type="Texture2D" path="{texture_res}" id="1_tiles"]',
        "",
        '[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_tiles"]',
        'texture = ExtResource("1_tiles")',
        f"texture_region_size = Vector2i({size}, {size})",
    ]
    for n, mask in enumerate(masks):
        at = f"{n % columns}:{n // columns}/0"
        lines += [f"{at} = 0", f"{at}/terrain_set = 0", f"{at}/terrain = 0"]
        lines += [
            f"{at}/terrains_peering_bit/{name} = 0" for bit, name in _GODOT_BITS if mask & bit
        ]
    lines += [
        "",
        "[resource]",
        f"tile_size = Vector2i({size}, {size})",
        "terrain_set_0/mode = 0",
        f'terrain_set_0/terrain_0/name = "{terrain}"',
        "terrain_set_0/terrain_0/color = Color(0.35, 0.6, 0.3, 1)",
        'sources/0 = SubResource("TileSetAtlasSource_tiles")',
        "",
    ]
    return "\n".join(lines)


# Unity's neighbour order for a Rule Tile, and what each needs: 1 is "this tile",
# 2 is "not this tile". Positions are Unity's, with y up.
_UNITY_NEIGHBOURS = (
    (NW, -1, 1),
    (N, 0, 1),
    (NE, 1, 1),
    (W, -1, 0),
    (E, 1, 0),
    (SW, -1, -1),
    (S, 0, -1),
    (SE, 1, -1),
)
RULE_TILE_SCRIPT = "9d1514134bc4fbd41bb739b1b9a49231"


def _rules_for(mask: int) -> list[tuple[int, int, int]]:
    rules = []
    for bit, x, y in _UNITY_NEIGHBOURS:
        if bit in (N, E, S, W):
            rules.append((x, y, 1 if mask & bit else 2))
            continue
        sides = {NE: N | E, SE: S | E, SW: S | W, NW: N | W}[bit]
        if mask & sides == sides:  # a corner only counts when both sides are there
            rules.append((x, y, 1 if mask & bit else 2))
    return rules


def unity_rule_tile(name: str, texture_guid: str, sprite_ids: list[int], masks: list[int]) -> str:
    """A Unity Rule Tile (2D Tilemap Extras) choosing among the sliced tiles."""

    def ref(iid: int) -> str:
        return f"{{fileID: {iid}, guid: {texture_guid}, type: 3}}"

    out = [
        "%YAML 1.1",
        "%TAG !u! tag:unity3d.com,2011:",
        "--- !u!114 &11400000",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        "  m_GameObject: {fileID: 0}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {RULE_TILE_SCRIPT}, type: 3}}",
        f"  m_Name: {name}",
        "  m_EditorClassIdentifier: ",
        f"  m_DefaultSprite: {ref(sprite_ids[0])}",
        "  m_DefaultGameObject: {fileID: 0}",
        "  m_DefaultColliderType: 1",
        "  m_TilingRules:",
    ]
    for n, (mask, iid) in enumerate(zip(masks, sprite_ids, strict=True)):
        rules = _rules_for(mask)
        hexes = "".join(v.to_bytes(4, "little").hex() for _, _, v in rules)
        out += [
            f"  - m_Id: {n}",
            "    m_Sprites:",
            f"    - {ref(iid)}",
            "    m_GameObject: {fileID: 0}",
            "    m_MinAnimationSpeed: 1",
            "    m_MaxAnimationSpeed: 1",
            "    m_PerlinScale: 0.5",
            "    m_Output: 0",
            "    m_ColliderType: 1",
            "    m_RandomTransform: 0",
            f"    m_Neighbors: {hexes}",
            "    m_NeighborPositions:",
        ]
        out += [f"    - {{x: {x}, y: {y}, z: 0}}" for x, y, _ in rules]
        out += ["    m_RuleTransform: 0"]
    return "\n".join(out) + "\n"
