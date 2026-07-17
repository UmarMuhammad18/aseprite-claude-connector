"""Shading tools.

- ``apply_shading`` — palette-constrained shading by light direction (adjust
  luminance, snap to nearest palette color). Parity with pixel-mcp's apply_shading.
- ``palette_ramp_walk`` — the index-adjacency differentiator: instead of snapping to
  the luminance-nearest palette color, it WALKS the arranged palette ±N indices
  toward lighter/darker (direction inferred from neighbor luminance). This respects
  hand-arranged shading ramps rather than picking by raw color distance — a narrow
  but real distinction from every luminance-nearest shader.

Both operate on RGB sprites and are one undo step. Light directions:
top_left, top, top_right, left, right, bottom_left, bottom, bottom_right.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

_DIRS = {
    "top_left": (-1, -1),
    "top": (0, -1),
    "top_right": (1, -1),
    "left": (-1, 0),
    "right": (1, 0),
    "bottom_left": (-1, 1),
    "bottom": (0, 1),
    "bottom_right": (1, 1),
}

# Inside-editCel helpers: palette tables, nearestIdx, pxrgb, litnessAt.
_PRELUDE = """
if s.colorMode ~= ColorMode.RGB then error("shading tools require an RGB sprite") end
local pal = s.palettes[1]
local np = #pal
if np < 2 then error("palette needs >= 2 colors") end
local pr, pg, pb, plum = {}, {}, {}, {}
for i = 0, np - 1 do
  local c = pal:getColor(i)
  pr[i] = c.red; pg[i] = c.green; pb[i] = c.blue
  plum[i] = 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue
end
local function nearestIdx(r, g, b)
  local best, bd = 0, 1e18
  for i = 0, np - 1 do
    local dr, dg, db = r - pr[i], g - pg[i], b - pb[i]
    local dd = dr * dr + dg * dg + db * db
    if dd < bd then bd = dd; best = i end
  end
  return best
end
local function pxrgb(v)
  return app.pixelColor.rgbaR(v), app.pixelColor.rgbaG(v), app.pixelColor.rgbaB(v), app.pixelColor.rgbaA(v)
end
local function litnessAt(xx, yy)
  local u = (W > 1) and (xx / (W - 1)) or 0.5
  local v = (H > 1) and (yy / (H - 1)) or 0.5
  return (u - 0.5) * LX + (v - 0.5) * LY
end
"""

_APPLY_LOOP = """
for yy = 0, H - 1 do
  for xx = 0, W - 1 do
    local px, py = X + xx, Y + yy
    if px >= 0 and py >= 0 and px < s.width and py < s.height then
      local r, g, b, a = pxrgb(img:getPixel(px, py))
      if a > 0 then
        local f = 1.0 + litnessAt(xx, yy) * INTENSITY
        local nr = math.max(0, math.min(255, math.floor(r * f + 0.5)))
        local ng = math.max(0, math.min(255, math.floor(g * f + 0.5)))
        local nb = math.max(0, math.min(255, math.floor(b * f + 0.5)))
        img:drawPixel(px, py, pal:getColor(nearestIdx(nr, ng, nb)))
      end
    end
  end
end
return J({ shaded = "palette-nearest", region = {X, Y, W, H} })
"""

_RAMP_LOOP = """
local function lighterDir(i)
  local up = (i < np - 1) and plum[i + 1] or -1
  local down = (i > 0) and plum[i - 1] or -1
  if up >= down then return 1 else return -1 end
end
local function walk(i, delta)
  if delta == 0 then return i end
  local step = (delta > 0) and lighterDir(i) or -lighterDir(i)
  local cur = i
  for _ = 1, math.abs(delta) do
    local nxt = cur + step
    if nxt < 0 or nxt > np - 1 then break end
    cur = nxt
  end
  return cur
end
for yy = 0, H - 1 do
  for xx = 0, W - 1 do
    local px, py = X + xx, Y + yy
    if px >= 0 and py >= 0 and px < s.width and py < s.height then
      local r, g, b, a = pxrgb(img:getPixel(px, py))
      if a > 0 then
        local delta = math.floor(litnessAt(xx, yy) * STEPS + 0.5)
        img:drawPixel(px, py, pal:getColor(walk(nearestIdx(r, g, b), delta)))
      end
    end
  end
end
return J({ shaded = "ramp-walk", region = {X, Y, W, H}, steps = STEPS })
"""


def _body(prelude_locals: str, loop: str) -> str:
    return prelude_locals + "return editCel(function(img, s)\n" + _PRELUDE + loop + "\nend)\n"


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Apply shading"))
    def apply_shading(
        x: int,
        y: int,
        width: int,
        height: int,
        light_direction: str,
        intensity: float = 0.5,
        file: str | None = None,
    ) -> dict:
        """Palette-constrained shading: brighten toward the light and darken away
        from it, snapping every pixel to the nearest palette color. ``intensity``
        ~0..1. RGB sprite only; one undo step. Headless: pass ``file``."""
        if light_direction not in _DIRS:
            raise ToolError(f"light_direction must be one of {', '.join(_DIRS)}")
        lx, ly = _DIRS[light_direction]
        loc = lua_locals(
            X=int(x),
            Y=int(y),
            W=int(width),
            H=int(height),
            LX=lx,
            LY=ly,
            INTENSITY=float(intensity),
        )
        return run(_body(loc, _APPLY_LOOP), mutates=True, undo_label="Apply shading", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Palette ramp-walk shading"))
    def palette_ramp_walk(
        x: int,
        y: int,
        width: int,
        height: int,
        light_direction: str,
        steps: int = 2,
        file: str | None = None,
    ) -> dict:
        """Shade by WALKING the arranged palette ±N indices toward lighter/darker
        (per light direction), instead of snapping to the luminance-nearest color —
        so hand-ordered shading ramps are respected. ``steps`` = max indices to walk
        at the fully-lit/shadowed edges. RGB sprite with an ordered ramp palette;
        one undo step. Headless: pass ``file``."""
        if light_direction not in _DIRS:
            raise ToolError(f"light_direction must be one of {', '.join(_DIRS)}")
        if steps < 1:
            raise ToolError("steps must be >= 1")
        lx, ly = _DIRS[light_direction]
        loc = lua_locals(
            X=int(x), Y=int(y), W=int(width), H=int(height), LX=lx, LY=ly, STEPS=int(steps)
        )
        return run(_body(loc, _RAMP_LOOP), mutates=True, undo_label="Ramp-walk shading", file=file)
