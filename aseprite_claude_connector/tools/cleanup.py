"""Colour cleanup: find stray pixels, and recolour a sprite into variants.

Both read pixels into Python rather than work in Lua, so ``recolor_variants`` writes
its files without raising Aseprite's script-security prompt in the live editor.
"""

from __future__ import annotations

import os

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ..raster import Raster, encode_png, fit_factor, over_background, remap, resized, strip, tiled
from ._common import ToolError, parse_color, rails, run
from .game_export import sprite_name
from .look import _LOOK, _LOOK_HELPERS, _take, frames_of, png_content

_MAX_LISTED = 40
_MAX_COMPARED_COLORS = 128
_MARK = {"isolated": (255, 60, 60), "orphan": (255, 210, 40), "rare": (255, 60, 255)}


def stray_report(src: Raster, rare: int = 2, near: int = 16) -> dict:
    """Pixels and colors that look like accidents. ``isolated`` pixels float with no
    opaque neighbor; ``orphan`` pixels touch art but share a color with none of it;
    ``rare`` colors appear ``rare`` times or fewer; ``near_duplicates`` are colors a
    hair away from a much commoner one, the usual sign of a wrong palette pick."""
    w, h = src.width, src.height
    rgba = src.rgba
    colors: dict[bytes, int] = {}
    solid = bytearray(w * h)
    for i in range(w * h):
        if rgba[i * 4 + 3]:
            solid[i] = 1
            key = rgba[i * 4 : i * 4 + 3]
            colors[key] = colors.get(key, 0) + 1
    isolated, orphans = [], []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if not solid[i]:
                continue
            me = rgba[i * 4 : i * 4 + 3]
            touches, same = False, False
            for ny in range(max(y - 1, 0), min(y + 2, h)):
                for nx in range(max(x - 1, 0), min(x + 2, w)):
                    n = ny * w + nx
                    if n != i and solid[n]:
                        touches = True
                        same = same or rgba[n * 4 : n * 4 + 3] == me
            if not touches:
                isolated.append((x, y))
            elif not same:
                orphans.append((x, y))
    scarce = {c for c, n in colors.items() if n <= rare}
    common = sorted(colors.items(), key=lambda kv: -kv[1])[:_MAX_COMPARED_COLORS]
    near_duplicates = []
    for color, n in common:
        for other, m in common:
            if m >= 4 * n and max(abs(a - b) for a, b in zip(color, other, strict=False)) <= near:
                near_duplicates.append(
                    {"color": "#" + color.hex(), "count": n, "close_to": "#" + other.hex()}
                )
                break
    rare_pixels = [
        (i % w, i // w) for i in range(w * h) if solid[i] and rgba[i * 4 : i * 4 + 3] in scarce
    ]
    return {
        "isolated": isolated,
        "orphans": orphans,
        "rare_colors": sorted("#" + c.hex() for c in scarce),
        "rare_pixels": rare_pixels,
        "near_duplicates": near_duplicates,
        "colors": len(colors),
    }


def marked(src: Raster, report: dict) -> Raster:
    """The art dimmed to gray, with each finding lit in its own color."""
    out = bytearray(src.rgba)
    for i in range(0, len(out), 4):
        if out[i + 3]:
            gray = (out[i] * 2 + out[i + 1] * 5 + out[i + 2]) // 16 + 24
            out[i : i + 4] = bytes((gray, gray, gray, 255))
    for key, points in (
        ("rare", report["rare_pixels"]),
        ("orphan", report["orphans"]),
        ("isolated", report["isolated"]),
    ):
        for x, y in points:
            out[(y * src.width + x) * 4 : (y * src.width + x) * 4 + 4] = bytes((*_MARK[key], 255))
    return Raster(src.width, src.height, bytes(out))


def _color_map(mapping: dict[str, str]) -> dict[tuple, tuple]:
    return {parse_color(a)[:3]: parse_color(b)[:3] for a, b in mapping.items()}


def register(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(title="Find stray pixels", readOnlyHint=True),
        structured_output=False,
    )
    def find_stray_pixels(
        frame: int | None = None,
        layer: str | None = None,
        rare: int = 2,
        near: int = 16,
        max_size: int = 512,
        file: str | None = None,
    ) -> list:
        """Find pixels and colors that look like accidents, and return a picture of
        them: the art in gray, with floating ``isolated`` pixels in red, ``orphan``
        pixels (touching art but matching none of it) in yellow, and pixels of colors
        used ``rare`` times or fewer in magenta. Also lists ``near_duplicates``: colors
        within ``near`` of a much commoner one. Dithering and highlights can be
        deliberate orphans, so treat this as a list to look over, not to erase. Defaults
        to the active frame, all visible layers. Read-only. Headless: pass ``file``."""
        if rare < 0 or not 0 <= near <= 255:
            raise ToolError("rare must be 0 or more, and near 0..255")
        body = (
            lua_locals(
                SCALE=1,
                MAX_SIZE=int(max_size),
                FRAME=frame,
                LAYER=layer,
                SELECTION=False,
                RX=None,
                RY=None,
                RW=None,
                RH=None,
            )
            + _LOOK_HELPERS
            + _LOOK
        )
        res = run(body, file=file)
        src = _take(res)
        report = stray_report(src, rare, near)
        k = fit_factor(src.width, src.height, None, max_size)
        picture = over_background(resized(marked(src, report), k), (24, 24, 24))
        meta = {
            "frame": res["frame"],
            "isolated": len(report["isolated"]),
            "orphans": len(report["orphans"]),
            "rare_colors": report["rare_colors"][:_MAX_LISTED],
            "near_duplicates": report["near_duplicates"][:_MAX_LISTED],
            "colors": report["colors"],
            "first_isolated": report["isolated"][:_MAX_LISTED],
            "first_orphans": report["orphans"][:_MAX_LISTED],
            "scale": k,
        }
        return png_content(picture, meta)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Recolor into variants", destructiveHint=False, openWorldHint=True
        ),
        structured_output=False,
    )
    def recolor_variants(
        variants: dict[str, dict[str, str]],
        output_dir: str,
        tag: str | None = None,
        name: str | None = None,
        file: str | None = None,
    ) -> list:
        """Recolor the sprite into team colors or seasons in one batch. ``variants`` maps
        each variant's name to a color swap, like ``{"red": {"#3050c0": "#c03030"},
        "green": {"#3050c0": "#30a040"}}``. Writes one strip ``<name>_<variant>.png`` per
        variant into ``output_dir``, frames left to right, and returns a picture comparing
        them. Colors must match exactly, and any that were never found are listed in
        ``unmatched``. Leaves the sprite untouched. ``tag`` limits it to one animation.
        Headless: pass ``file``."""
        if rails.capturing:
            raise ToolError("recolor_variants writes files, so it can't be batched")
        if rails.dry_run:
            raise ToolError("dry run: recolor_variants writes files, so it was not run.")
        if not variants:
            raise ToolError("variants needs at least one entry")
        maps = {}
        for variant, mapping in variants.items():
            if not mapping:
                raise ToolError(f"variant '{variant}' has no colors to swap")
            sprite_name("", variant)
            maps[variant] = _color_map(mapping)
        grabbed = frames_of(tag=tag, file=file)
        stem = sprite_name(grabbed["name"], name)
        frames = grabbed["frames"]
        os.makedirs(output_dir, exist_ok=True)
        present = {
            f.rgba[i : i + 3] for f in frames for i in range(0, len(f.rgba), 4) if f.rgba[i + 3]
        }
        written, panels, unmatched = {}, [], {}
        for variant, colors in maps.items():
            swapped = [remap(f, colors) for f in frames]
            path = os.path.join(output_dir, f"{stem}_{variant}.png")
            with open(path, "wb") as out:
                out.write(encode_png(strip(swapped)))
            written[variant] = path
            panels.append(swapped[0])
            missing = ["#" + bytes(c).hex() for c in colors if bytes(c) not in present]
            if missing:
                unmatched[variant] = missing
        k = fit_factor(len(panels) * frames[0].width, frames[0].height, None, 512)
        sheet = tiled([over_background(resized(p, k), "checker") for p in panels], len(panels))
        meta = {
            "files": written,
            "frames": len(frames),
            "unmatched": unmatched,
            "panels": list(maps),
        }
        return png_content(sheet, meta)
