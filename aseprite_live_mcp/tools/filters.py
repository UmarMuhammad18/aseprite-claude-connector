"""Image filters — cel-scoped, alpha-preserving, one undo step each.

All filters operate on the active layer+frame cel through ``editCel`` (same
contract as the draw tools): they composite the cel into a sprite-sized image,
transform the pixels, and write it back. Alpha is never invented — fully
transparent pixels stay transparent, and partial alpha passes through untouched
unless the filter is explicitly about alpha.

Kernels (blur/sharpen) clone the image first so reads come from the original.
Canvases are pixel-art sized; the Lua loops are fine up to the 1024x1024 guard.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

_GUARD = """
local __s = app.activeSprite
if not __s then error("no active sprite") end
if __s.width * __s.height > 1048576 then error("sprite too large for this filter (cap 1024x1024)") end
"""

_BRIGHTNESS_CONTRAST = (
    _GUARD
    + """
return editCel(function(img, s)
  local pc = app.pixelColor
  local br = BR * 255 / 100
  local cf = (259 * (CT * 255 / 100 + 255)) / (255 * (259 - CT * 255 / 100))
  local function adj(v)
    return math.max(0, math.min(255, math.floor(cf * (v - 128) + 128 + br + 0.5)))
  end
  for y = 0, img.height - 1 do
    for x = 0, img.width - 1 do
      local v = img:getPixel(x, y)
      local a = pc.rgbaA(v)
      if a > 0 then
        img:drawPixel(x, y, pc.rgba(adj(pc.rgbaR(v)), adj(pc.rgbaG(v)), adj(pc.rgbaB(v)), a))
      end
    end
  end
  return J({ brightness = BR, contrast = CT })
end)
"""
)

_INVERT = (
    _GUARD
    + """
return editCel(function(img, s)
  local pc = app.pixelColor
  for y = 0, img.height - 1 do
    for x = 0, img.width - 1 do
      local v = img:getPixel(x, y)
      local a = pc.rgbaA(v)
      if a > 0 then
        img:drawPixel(x, y, pc.rgba(255 - pc.rgbaR(v), 255 - pc.rgbaG(v), 255 - pc.rgbaB(v), a))
      end
    end
  end
  return J({ inverted = true })
end)
"""
)

_DESATURATE = (
    _GUARD
    + """
return editCel(function(img, s)
  local pc = app.pixelColor
  for y = 0, img.height - 1 do
    for x = 0, img.width - 1 do
      local v = img:getPixel(x, y)
      local a = pc.rgbaA(v)
      if a > 0 then
        local g = math.floor(0.299 * pc.rgbaR(v) + 0.587 * pc.rgbaG(v) + 0.114 * pc.rgbaB(v) + 0.5)
        img:drawPixel(x, y, pc.rgba(g, g, g, a))
      end
    end
  end
  return J({ desaturated = true })
end)
"""
)

# Box blur, alpha-weighted so transparent neighbors don't darken edges.
_BLUR = (
    _GUARD
    + """
return editCel(function(img, s)
  local pc = app.pixelColor
  local src = Image(img)
  local rad = RAD
  for y = 0, img.height - 1 do
    for x = 0, img.width - 1 do
      local sr, sg, sb, sa, wsum = 0, 0, 0, 0, 0
      for dy = -rad, rad do
        for dx = -rad, rad do
          local nx, ny = x + dx, y + dy
          if nx >= 0 and ny >= 0 and nx < src.width and ny < src.height then
            local v = src:getPixel(nx, ny)
            local a = pc.rgbaA(v)
            sr = sr + pc.rgbaR(v) * a
            sg = sg + pc.rgbaG(v) * a
            sb = sb + pc.rgbaB(v) * a
            sa = sa + a
            wsum = wsum + 1
          end
        end
      end
      if sa > 0 then
        img:drawPixel(x, y, pc.rgba(
          math.floor(sr / sa + 0.5), math.floor(sg / sa + 0.5), math.floor(sb / sa + 0.5),
          math.floor(sa / wsum + 0.5)))
      else
        img:drawPixel(x, y, 0)
      end
    end
  end
  return J({ blurred = true, radius = rad })
end)
"""
)

# Unsharp mask: out = src + STR * (src - boxblur1(src)), opaque-ish pixels only.
_SHARPEN = (
    _GUARD
    + """
return editCel(function(img, s)
  local pc = app.pixelColor
  local src = Image(img)
  local function clamp(v) return math.max(0, math.min(255, math.floor(v + 0.5))) end
  for y = 0, img.height - 1 do
    for x = 0, img.width - 1 do
      local v = src:getPixel(x, y)
      local a = pc.rgbaA(v)
      if a > 0 then
        local sr, sg, sb, n = 0, 0, 0, 0
        for dy = -1, 1 do
          for dx = -1, 1 do
            local nx, ny = x + dx, y + dy
            if nx >= 0 and ny >= 0 and nx < src.width and ny < src.height then
              local nv = src:getPixel(nx, ny)
              if pc.rgbaA(nv) > 0 then
                sr = sr + pc.rgbaR(nv); sg = sg + pc.rgbaG(nv); sb = sb + pc.rgbaB(nv); n = n + 1
              end
            end
          end
        end
        if n > 0 then
          img:drawPixel(x, y, pc.rgba(
            clamp(pc.rgbaR(v) + STR * (pc.rgbaR(v) - sr / n)),
            clamp(pc.rgbaG(v) + STR * (pc.rgbaG(v) - sg / n)),
            clamp(pc.rgbaB(v) + STR * (pc.rgbaB(v) - sb / n)), a))
        end
      end
    end
  end
  return J({ sharpened = true, strength = STR })
end)
"""
)


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Brightness / contrast"))
    def adjust_brightness_contrast(
        brightness: int = 0, contrast: int = 0, file: str | None = None
    ) -> dict:
        """Adjust the active cel's brightness and contrast, each -100..100
        (0 = unchanged). Alpha is preserved. One undo step. Headless: pass ``file``."""
        if not (-100 <= brightness <= 100 and -100 <= contrast <= 100):
            raise ToolError("brightness and contrast must be in -100..100")
        if brightness == 0 and contrast == 0:
            raise ToolError("nothing to do: brightness and contrast are both 0")
        body = lua_locals(BR=int(brightness), CT=int(contrast)) + _BRIGHTNESS_CONTRAST
        return run(body, mutates=True, undo_label="Brightness/contrast", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Invert colors", idempotentHint=False))
    def invert_colors(file: str | None = None) -> dict:
        """Invert the active cel's RGB (alpha untouched). One undo step."""
        return run(_INVERT, mutates=True, undo_label="Invert colors", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Desaturate"))
    def desaturate(file: str | None = None) -> dict:
        """Convert the active cel to grayscale (Rec. 601 luma), keeping alpha.
        One undo step. Headless: pass ``file``."""
        return run(_DESATURATE, mutates=True, undo_label="Desaturate", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Box blur"))
    def box_blur(radius: int = 1, file: str | None = None) -> dict:
        """Blur the active cel with an alpha-weighted box kernel. ``radius`` 1-4
        (1 = 3x3). Transparent neighbors don't darken edges. One undo step."""
        if not 1 <= radius <= 4:
            raise ToolError("radius must be 1..4")
        body = lua_locals(RAD=int(radius)) + _BLUR
        return run(body, mutates=True, undo_label="Box blur", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Sharpen"))
    def sharpen(strength: float = 0.5, file: str | None = None) -> dict:
        """Sharpen the active cel (unsharp mask over a 3x3 neighborhood).
        ``strength`` 0.1-2.0. Only opaque pixels are considered, so sprite edges
        don't halo against transparency. One undo step."""
        if not 0.1 <= float(strength) <= 2.0:
            raise ToolError("strength must be 0.1..2.0")
        body = lua_locals(STR=float(strength)) + _SHARPEN
        return run(body, mutates=True, undo_label="Sharpen", file=file)
