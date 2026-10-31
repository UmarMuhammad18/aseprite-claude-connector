"""Whole-sprite transform tools."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

_FLIP = """
local s = app.activeSprite
if not s then error("no active sprite") end
app.command.Flip{ ui = false, target = "sprite", orientation = ORIENT }
return J({ flipped = ORIENT })
"""

_RESIZE = """
local s = app.activeSprite
if not s then error("no active sprite") end
s:resize(W, H)
return J({ width = s.width, height = s.height })
"""

_CROP = """
local s = app.activeSprite
if not s then error("no active sprite") end
s:crop(X, Y, W, H)
return J({ width = s.width, height = s.height })
"""

_ROTATE = """
local s = app.activeSprite
if not s then error("no active sprite") end
app.command.Rotate{ ui = false, target = "sprite", angle = ANGLE }
return J({ rotated = ANGLE, width = s.width, height = s.height })
"""

# GOTCHA (verified on 1.3.17.2): AutocropSprite and ChangePixelFormat silently
# no-op in batch mode when the params table contains a ``ui`` key — even
# ``ui = false``. Call them WITHOUT a ui entry; with a valid ``format``/no
# params they never raise UI anyway. (Flip/Rotate/ExportSpriteSheet tolerate
# ``ui = false`` fine; it's specific to these job-based commands.)
_AUTOCROP = """
local s = app.activeSprite
if not s then error("no active sprite") end
local ow, oh = s.width, s.height
app.command.AutocropSprite()
if s.width == ow and s.height == oh then
  -- The command can still no-op (headless quirk above); fall back to a manual
  -- union-of-cel-content crop so the result is backend-independent.
  local minx, miny, maxx, maxy = nil, nil, nil, nil
  local function scan(layers)
    for _, l in ipairs(layers) do
      if l.isGroup then scan(l.layers)
      elseif l.isImage then
        for f = 1, #s.frames do
          local c = l:cel(f)
          if c then
            local sb = c.image:shrinkBounds()
            if sb.width > 0 and sb.height > 0 then
              local x1, y1 = c.position.x + sb.x, c.position.y + sb.y
              local x2, y2 = x1 + sb.width, y1 + sb.height
              if not minx or x1 < minx then minx = x1 end
              if not miny or y1 < miny then miny = y1 end
              if not maxx or x2 > maxx then maxx = x2 end
              if not maxy or y2 > maxy then maxy = y2 end
            end
          end
        end
      end
    end
  end
  scan(s.layers)
  if not minx then error("sprite has no visible content to trim") end
  if minx < 0 then minx = 0 end
  if miny < 0 then miny = 0 end
  if maxx > ow then maxx = ow end
  if maxy > oh then maxy = oh end
  if minx > 0 or miny > 0 or maxx < ow or maxy < oh then
    s:crop(minx, miny, maxx - minx, maxy - miny)
  end
end
return J({ old_width = ow, old_height = oh, width = s.width, height = s.height })
"""

_COLOR_MODE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local function modename(cm)
  if cm == ColorMode.RGB then return "rgb"
  elseif cm == ColorMode.GRAY then return "gray"
  elseif cm == ColorMode.INDEXED then return "indexed" end
  return tostring(cm)
end
local old = modename(s.colorMode)
-- A new sprite's palette has one entry, and converting to it would blank the art.
if MODE == "indexed" and #s.palettes[1] <= 1 then
  app.command.ColorQuantization{ ui = false, withAlpha = false, maxColors = 256 }
end
if DITHER ~= nil then
  app.command.ChangePixelFormat{ format = MODE, dithering = DITHER }
else
  app.command.ChangePixelFormat{ format = MODE }
end
local new = modename(s.colorMode)
if new ~= MODE then
  error("color mode change to '" .. MODE .. "' did not take (sprite is still " .. new .. ")")
end
return J({ old_mode = old, mode = new })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Flip sprite"))
    def flip_sprite(direction: str, file: str | None = None) -> dict:
        """Flip the whole sprite horizontally or vertically."""
        d = direction.strip().lower()
        if d not in ("horizontal", "vertical"):
            raise ToolError("direction must be horizontal | vertical")
        body = lua_locals(ORIENT=d) + _FLIP
        return run(body, mutates=True, undo_label="Flip", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Resize sprite"))
    def resize_sprite(width: int, height: int, file: str | None = None) -> dict:
        """Scale the whole sprite to new pixel dimensions."""
        if width < 1 or height < 1:
            raise ToolError("width/height must be >= 1")
        body = lua_locals(W=int(width), H=int(height)) + _RESIZE
        return run(body, mutates=True, undo_label="Resize", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Crop sprite", destructiveHint=True))
    def crop_sprite(x: int, y: int, width: int, height: int, file: str | None = None) -> dict:
        """Crop the sprite to the given rectangle."""
        if width < 1 or height < 1:
            raise ToolError("width/height must be >= 1")
        body = lua_locals(X=int(x), Y=int(y), W=int(width), H=int(height)) + _CROP
        return run(body, mutates=True, undo_label="Crop", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Rotate sprite"))
    def rotate_sprite(degrees: int, file: str | None = None) -> dict:
        """Rotate the whole sprite by 90, 180, or 270 degrees clockwise (lossless).
        One undo step. Headless: pass ``file``."""
        if degrees not in (90, 180, 270):
            raise ToolError("degrees must be 90, 180, or 270")
        body = lua_locals(ANGLE=int(degrees)) + _ROTATE
        return run(body, mutates=True, undo_label="Rotate", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Autocrop sprite (trim)"))
    def autocrop_sprite(file: str | None = None) -> dict:
        """Trim transparent borders: shrink the canvas to the union of visible
        content across all layers and frames (Sprite > Trim). Errors if the
        sprite is fully transparent. Returns the old and new size. One undo
        step. Headless: pass ``file``."""
        return run(_AUTOCROP, mutates=True, undo_label="Autocrop", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set color mode"))
    def set_color_mode(mode: str, dithering: str | None = None, file: str | None = None) -> dict:
        """Convert the sprite between rgb | gray | indexed color modes.
        ``dithering`` applies only when converting to indexed: ordered | old |
        error-diffusion (default none). Returns the old and new mode. One undo
        step. Headless: pass ``file``."""
        m = {"rgb": "rgb", "gray": "gray", "grayscale": "gray", "indexed": "indexed"}.get(
            mode.strip().lower()
        )
        if not m:
            raise ToolError(f"bad mode '{mode}' (rgb|gray|indexed)")
        d = None
        if dithering is not None:
            d = dithering.strip().lower()
            if d not in ("ordered", "old", "error-diffusion"):
                raise ToolError(f"bad dithering '{dithering}' (ordered|old|error-diffusion)")
            if m != "indexed":
                raise ToolError("dithering only applies when converting to indexed")
        body = lua_locals(MODE=m, DITHER=d) + _COLOR_MODE
        return run(body, mutates=True, undo_label="Color mode", file=file)
