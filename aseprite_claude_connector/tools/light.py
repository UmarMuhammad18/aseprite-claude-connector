"""Light.

- ``relight_scene`` — dawn, noon, sunset, or night versions of a scene, on new
  layers beside the originals, with warm pools around lanterns.
- ``make_normal_map`` — a normal map for Godot's and Unity's 2D lights, as a layer
  and optionally a PNG beside the exported sprite.

See ``light.py`` for the image work.
"""

from __future__ import annotations

import os

from mcp.types import ToolAnnotations

from ..light import PRESETS, normal_map, relight
from ..lua import lua_locals
from ..raster import encode_png
from ._common import ToolError, refuse_in_dry_run, run
from .look import pixels_loader
from .scene import _read, _strip

_LAYERS = """
local s = app.activeSprite
if not s then error("no active sprite (headless: pass file=)") end
if s.colorMode ~= ColorMode.RGB then
  error("this tool works on RGB sprites; convert with set_color_mode first")
end
local names = {}
local function walk(layers)
  for _, l in ipairs(layers) do
    if l.isGroup then
      if l.isVisible then walk(l.layers) end
    elseif l.isVisible and not l.isTilemap then
      names[#names + 1] = l.name
    end
  end
end
walk(s.layers)
return J({ layers = names, frames = #s.frames,
  frame = app.activeFrame and app.activeFrame.frameNumber or 1 })
"""

# Each source layer gets a copy above it; the strip holds one row per layer, one
# column per frame.
_COPIES = """
local s = app.activeSprite
local strip = load_image()
local made, row = {}, 0
for name in NAMES:gmatch("[^\\n]+") do
  local src = findLayer(s, name)
  if not src then error("no layer named '" .. name .. "'") end
  local l = s:newLayer()
  l.name = name .. SUFFIX
  l.parent = src.parent
  l.stackIndex = src.stackIndex + 1
  local col = 0
  for n in FRAMES:gmatch("%d+") do
    s:newCel(l, tonumber(n), Image(strip, Rectangle(col * W, row * H, W, H)), Point(0, 0))
    col = col + 1
  end
  if HIDE then src.isVisible = false end
  if HIDE_NEW then l.isVisible = false end
  made[#made + 1] = l.name
  row = row + 1
end
return J({ layers = made })
"""


def _scene(
    layers: list[str] | None, all_frames: bool, file: str | None
) -> tuple[list[str], list[int]]:
    info = run(_LAYERS, file=file)
    names = layers or info["layers"]
    if not names:
        raise ToolError("no visible image layers to work on")
    frames = list(range(1, info["frames"] + 1)) if all_frames else [info["frame"]]
    return names, frames


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Relight a scene"))
    def relight_scene(
        time: str,
        layers: list[str] | None = None,
        strength: float = 1.0,
        glows: list[list[float]] | None = None,
        all_frames: bool = True,
        file: str | None = None,
    ) -> dict:
        """Show a scene at another time of day: ``dawn``, ``noon``, ``sunset``, or
        ``night``. Each colour's lightness, warmth, and saturation shift the way that
        light would, and each maps to one new colour, so the colour count stays the
        same. ``glows`` are lanterns or windows, ``[[x, y, radius], ...]``, whose
        pools stay warm and lit. ``strength`` (0-1) blends toward the original.
        Works on ``layers`` (every visible image layer by default), writing a copy
        named like "Ground (night)" above each and hiding the original, so switching
        back is a visibility toggle. One undo step. Headless: pass ``file``."""
        if time not in PRESETS:
            raise ToolError(f"time must be one of: {', '.join(PRESETS)}")
        if not 0 <= strength <= 1:
            raise ToolError("strength must be 0..1")
        points = []
        for g in glows or []:
            if len(g) != 3 or g[2] <= 0:
                raise ToolError("each glow is [x, y, radius] with a positive radius")
            points.append((float(g[0]), float(g[1]), float(g[2])))
        names, frames = _scene(layers, all_frames, file)
        rendered = []
        for name in names:
            for f in frames:
                src, _ = _read(name, f, file)
                rendered.append(relight(src, time, strength, points))
        body = pixels_loader(_strip(rendered, rows=len(names))) + lua_locals(
            NAMES="\n".join(names),
            FRAMES=",".join(str(f) for f in frames),
            W=rendered[0].width,
            H=rendered[0].height,
            SUFFIX=f" ({time})",
            HIDE=True,
            HIDE_NEW=False,
        )
        made = run(body + _COPIES, mutates=True, undo_label=f"Relight: {time}", file=file)
        return {**made, "time": time, "frames": frames, "hidden": names}

    @mcp.tool(annotations=ToolAnnotations(title="Make a normal map"))
    def make_normal_map(
        layer: str | None = None,
        strength: float = 1.0,
        bevel: int = 4,
        detail: float = 0.4,
        all_frames: bool = True,
        save_path: str | None = None,
        file: str | None = None,
    ) -> dict:
        """Make a normal map so the art reacts to 2D lights in Godot and Unity: a torch
        moving past shades it. Forms round off over ``bevel`` pixels from their
        outline, ``detail`` (0-1) lets bright areas stand forward, and ``strength``
        steepens it all. It goes on a hidden "Normal map" layer, and ``save_path``
        also writes it as a PNG strip matching an exported sprite sheet (frames side
        by side). In Godot, set it as the normal map of a CanvasTexture whose diffuse
        is the sprite; in Unity, add it to the sprite's Secondary Textures as
        ``_NormalMap``. Made from ``layer``, or everything visible by default.
        One undo step. Headless: pass ``file``."""
        if save_path is not None:
            refuse_in_dry_run("make_normal_map with save_path")
            if not save_path.lower().endswith(".png"):
                raise ToolError("save_path must end in .png")
            if not os.path.isdir(os.path.dirname(os.path.abspath(save_path))):
                raise ToolError(f"no folder at {os.path.dirname(os.path.abspath(save_path))}")
        if not 1 <= bevel <= 64:
            raise ToolError("bevel must be 1..64")
        if not 0 <= detail <= 1 or not 0 < strength <= 8:
            raise ToolError("detail must be 0..1 and strength 0..8")
        _, frames = _scene(None, all_frames, file)
        maps = [normal_map(_read(layer, f, file)[0], strength, bevel, detail) for f in frames]
        sheet = _strip(maps)
        body = pixels_loader(sheet) + lua_locals(
            NAMES="Normal map",
            FRAMES=",".join(str(f) for f in frames),
            W=maps[0].width,
            H=maps[0].height,
            SUFFIX="",
            HIDE=False,
            HIDE_NEW=True,
        )
        made = run(body + _NORMAL_LAYER, mutates=True, undo_label="Normal map", file=file)
        result = {**made, "frames": frames}
        if save_path:
            with open(save_path, "wb") as f:
                f.write(encode_png(sheet))
            result["png"] = save_path
        return result


# A new hidden layer named "Normal map" on top, one cel per frame.
_NORMAL_LAYER = """
local s = app.activeSprite
local strip = load_image()
local l = s:newLayer()
l.name = NAMES
local col = 0
for n in FRAMES:gmatch("%d+") do
  s:newCel(l, tonumber(n), Image(strip, Rectangle(col * W, 0, W, H)), Point(0, 0))
  col = col + 1
end
l.isVisible = not HIDE_NEW
return J({ layer = l.name })
"""
