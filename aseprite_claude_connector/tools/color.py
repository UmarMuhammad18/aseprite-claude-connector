"""Color-operation tools: replace/remap, quantize-to-palette, HSL adjust, and a
color histogram. Daily pixel-art parity ops the headless leaders all ship.

All mutating tools composite the active cel via ``editCel`` and are one undo step.
``get_color_stats`` is read-only and feeds the art-QA loop (palette-drift checks).
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import parse_color, run

_REPLACE = """
return editCel(function(img, s)
  local fr, fg, fb = FR, FG, FB
  local tol = TOL
  local pc = app.pixelColor
  local changed = 0
  for y = 0, s.height - 1 do
    for x = 0, s.width - 1 do
      local v = img:getPixel(x, y)
      local a = pc.rgbaA(v)
      if a > 0 then
        local dr, dg, db = pc.rgbaR(v) - fr, pc.rgbaG(v) - fg, pc.rgbaB(v) - fb
        if dr * dr + dg * dg + db * db <= tol * tol then
          -- keep the source pixel's alpha unless to_color specified one (#rrggbbaa)
          local na = HAS_ALPHA and TA or a
          img:drawPixel(x, y, Color{ r = TR, g = TG, b = TB, a = na }); changed = changed + 1
        end
      end
    end
  end
  return J({ replaced = changed })
end)
"""

_QUANTIZE = """
return editCel(function(img, s)
  local pal = s.palettes[1]
  local np = #pal
  if np < 1 then error("palette is empty") end
  local pr, pg, pb = {}, {}, {}
  for i = 0, np - 1 do local c = pal:getColor(i); pr[i] = c.red; pg[i] = c.green; pb[i] = c.blue end
  local pc = app.pixelColor
  local function nearest(r, g, b)
    local bi, bd = 0, 1e18
    for i = 0, np - 1 do
      local dr, dg, db = r - pr[i], g - pg[i], b - pb[i]
      local d = dr * dr + dg * dg + db * db
      if d < bd then bd = d; bi = i end
    end
    return bi
  end
  local n = 0
  for y = 0, s.height - 1 do
    for x = 0, s.width - 1 do
      local v = img:getPixel(x, y)
      local a = pc.rgbaA(v)
      if a > 0 then
        local c = pal:getColor(nearest(pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v)))
        img:drawPixel(x, y, Color{ r = c.red, g = c.green, b = c.blue, a = a })
        n = n + 1
      end
    end
  end
  return J({ quantized = n, palette = np })
end)
"""

_HSL = """
return editCel(function(img, s)
  local pc = app.pixelColor
  local n = 0
  for y = 0, s.height - 1 do
    for x = 0, s.width - 1 do
      local v = img:getPixel(x, y)
      local a = pc.rgbaA(v)
      if a > 0 then
        local c = Color{ r = pc.rgbaR(v), g = pc.rgbaG(v), b = pc.rgbaB(v), a = a }
        c.hslHue = (c.hslHue + DH) % 360
        c.hslSaturation = math.max(0, math.min(1, c.hslSaturation * SMUL))
        c.hslLightness = math.max(0, math.min(1, c.hslLightness + DL))
        img:drawPixel(x, y, Color{ r = c.red, g = c.green, b = c.blue, a = a })
        n = n + 1
      end
    end
  end
  return J({ adjusted = n })
end)
"""

_STATS = """
local s = app.activeSprite
if not s then error("no active sprite") end
local frame = app.activeFrame or s.frames[1]
local img = Image(s.width, s.height, ColorMode.RGB)
img:drawSprite(s, frame)
local pc = app.pixelColor
local counts = {}
local distinct, opaque = 0, 0
for y = 0, s.height - 1 do
  for x = 0, s.width - 1 do
    local v = img:getPixel(x, y)
    if pc.rgbaA(v) > 0 then
      opaque = opaque + 1
      local key = string.format("#%02x%02x%02x", pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v))
      if not counts[key] then counts[key] = 0; distinct = distinct + 1 end
      counts[key] = counts[key] + 1
    end
  end
end
local arr = {}
for k, v in pairs(counts) do arr[#arr + 1] = { k, v } end
table.sort(arr, function(a, b) return a[2] > b[2] end)
local top = {}
for i = 1, math.min(TOPN, #arr) do top[i] = { color = arr[i][1], count = arr[i][2] } end
return J({ distinctColors = distinct, opaquePixels = opaque, top = top })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Replace color"))
    def replace_color(
        from_color: str, to_color: str, tolerance: int = 0, file: str | None = None
    ) -> dict:
        """Replace every pixel matching ``from_color`` (within ``tolerance``, a 0-255
        RGB distance) with ``to_color`` across the active cel, preserving each pixel's
        alpha unless ``to_color`` carries its own. One undo step. Headless: pass ``file``."""
        fr, fg, fb, _ = parse_color(from_color)
        tr, tg, tb, ta = parse_color(to_color)
        has_alpha = len(to_color.strip().lstrip("#")) == 8
        body = (
            lua_locals(
                FR=fr,
                FG=fg,
                FB=fb,
                TR=tr,
                TG=tg,
                TB=tb,
                TA=ta,
                HAS_ALPHA=has_alpha,
                TOL=int(tolerance),
            )
            + _REPLACE
        )
        return run(body, mutates=True, undo_label="Replace color", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Quantize to palette"))
    def quantize_to_palette(file: str | None = None) -> dict:
        """Snap every opaque pixel of the active cel to its nearest color in the
        sprite's palette (alpha preserved) — enforce palette discipline after intake
        or shading. RGB sprite; one undo step. Headless: pass ``file``."""
        return run(_QUANTIZE, mutates=True, undo_label="Quantize to palette", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Adjust HSL"))
    def adjust_hsl(
        hue_shift: float = 0.0,
        saturation: float = 1.0,
        lightness: float = 0.0,
        file: str | None = None,
    ) -> dict:
        """Shift the active cel's colors in HSL: ``hue_shift`` degrees (-360..360),
        ``saturation`` a multiplier (1.0 = unchanged), ``lightness`` a delta (-1..1).
        Useful for tint variants. One undo step. Headless: pass ``file``."""
        body = lua_locals(DH=float(hue_shift), SMUL=float(saturation), DL=float(lightness)) + _HSL
        return run(body, mutates=True, undo_label="Adjust HSL", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Color stats", readOnlyHint=True))
    def get_color_stats(top: int = 8, file: str | None = None) -> dict:
        """Return a color histogram of the composited sprite: distinct opaque color
        count, total opaque pixels, and the ``top`` most-used colors with counts —
        a palette-drift check for the art-QA loop. Read-only. Headless: pass ``file``."""
        body = lua_locals(TOPN=int(top)) + _STATS
        return run(body, file=file)
