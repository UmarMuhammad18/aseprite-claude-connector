"""Selection tools (most useful in the live editor; selection is per-session)."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, parse_color, run

_RECT = """
local s = app.activeSprite
if not s then error("no active sprite") end
s.selection:select(Rectangle(X, Y, W, H))
return J({ selected = {X, Y, W, H} })
"""

_ALL = """
local s = app.activeSprite
if not s then error("no active sprite") end
s.selection:selectAll()
return J({ selectedAll = true })
"""

_NONE = """
local s = app.activeSprite
if not s then error("no active sprite") end
s.selection:deselect()
return J({ deselected = true })
"""

_ELLIPSE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local sel = Selection()
local rx, ry = W / 2, H / 2
local cx, cy = X + rx, Y + ry
for row = 0, H - 1 do
  local py = row + 0.5
  local t = (py - ry) / ry
  local span = rx * math.sqrt(math.max(0, 1 - t * t))
  if span >= 0.5 then
    local x0 = math.floor(cx - span + 0.5)
    local x1 = math.ceil(cx + span - 0.5)
    sel:add(Rectangle(x0, Y + row, x1 - x0, 1))
  end
end
if MODE == "add" then s.selection:add(sel)
elseif MODE == "subtract" then s.selection:subtract(sel)
else
  s.selection:deselect()
  s.selection:add(sel)
end
local b = s.selection.bounds
return J({ mode = MODE, bounds = { x = b.x, y = b.y, width = b.width, height = b.height } })
"""

_BY_COLOR = """
local s = app.activeSprite
if not s then error("no active sprite") end
if s.width * s.height > 262144 then error("sprite too large for select_by_color (cap 512x512)") end
local frame = app.activeFrame or s.frames[1]
local img = Image(s.width, s.height, ColorMode.RGB)
img:drawSprite(s, frame)
local pc = app.pixelColor
local sel = Selection()
local count = 0
for y = 0, s.height - 1 do
  local runStart = nil
  for x = 0, s.width - 1 do
    local v = img:getPixel(x, y)
    local match = math.abs(pc.rgbaR(v) - R) <= TOL and math.abs(pc.rgbaG(v) - G) <= TOL
      and math.abs(pc.rgbaB(v) - B) <= TOL and math.abs(pc.rgbaA(v) - A) <= TOL
    if match then
      if not runStart then runStart = x end
      count = count + 1
    elseif runStart then
      sel:add(Rectangle(runStart, y, x - runStart, 1))
      runStart = nil
    end
  end
  if runStart then sel:add(Rectangle(runStart, y, s.width - runStart, 1)) end
end
if MODE == "add" then s.selection:add(sel)
elseif MODE == "subtract" then s.selection:subtract(sel)
else
  s.selection:deselect()
  if count > 0 then s.selection:add(sel) end
end
return J({ matched_pixels = count, mode = MODE })
"""

_INVERT = """
local s = app.activeSprite
if not s then error("no active sprite") end
local inv = Selection()
inv:add(Rectangle(0, 0, s.width, s.height))
inv:subtract(s.selection)
s.selection:deselect()
s.selection:add(inv)
local b = s.selection.bounds
return J({ inverted = true, bounds = { x = b.x, y = b.y, width = b.width, height = b.height } })
"""

_GET = """
local s = app.activeSprite
if not s then error("no active sprite") end
if s.selection.isEmpty then return J({ empty = true }) end
local b = s.selection.bounds
return J({ empty = false, bounds = { x = b.x, y = b.y, width = b.width, height = b.height } })
"""

# Erase an explicit rect, or (live) whatever is currently selected. On indexed
# sprites "transparent" is the sprite's transparentColor index, not 0.
_ERASE = """
local s = app.activeSprite
if not s then error("no active sprite") end
return editCel(function(img, sp)
  local EMPTY = 0
  if sp.colorMode == ColorMode.INDEXED then EMPTY = sp.transparentColor end
  local cleared = 0
  if USE_RECT then
    for yy = math.max(0, Y), math.min(img.height - 1, Y + H - 1) do
      for xx = math.max(0, X), math.min(img.width - 1, X + W - 1) do
        img:drawPixel(xx, yy, EMPTY)
        cleared = cleared + 1
      end
    end
  else
    if sp.selection.isEmpty then error("no selection to erase (pass x/y/width/height, or select first)") end
    local b = sp.selection.bounds
    for yy = math.max(0, b.y), math.min(img.height - 1, b.y + b.height - 1) do
      for xx = math.max(0, b.x), math.min(img.width - 1, b.x + b.width - 1) do
        if sp.selection:contains(xx, yy) then
          img:drawPixel(xx, yy, EMPTY)
          cleared = cleared + 1
        end
      end
    end
  end
  return J({ cleared_pixels = cleared })
end)
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Select rectangle", idempotentHint=True))
    def select_rectangle(x: int, y: int, width: int, height: int, file: str | None = None) -> dict:
        """Set a rectangular selection. Most meaningful on the live editor."""
        body = lua_locals(X=int(x), Y=int(y), W=int(width), H=int(height)) + _RECT
        return run(body, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Select all", idempotentHint=True))
    def select_all(file: str | None = None) -> dict:
        """Select the whole canvas."""
        return run(_ALL, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Deselect", idempotentHint=True))
    def deselect(file: str | None = None) -> dict:
        """Clear the current selection."""
        return run(_NONE, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Select ellipse", idempotentHint=True))
    def select_ellipse(
        x: int, y: int, width: int, height: int, mode: str = "replace", file: str | None = None
    ) -> dict:
        """Select an ellipse inscribed in the given rectangle. ``mode`` is
        ``replace`` (default), ``add``, or ``subtract`` against the current
        selection."""
        if mode not in ("replace", "add", "subtract"):
            raise ToolError("mode must be replace, add, or subtract")
        body = lua_locals(X=int(x), Y=int(y), W=int(width), H=int(height), MODE=mode) + _ELLIPSE
        return run(body, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Select by color", idempotentHint=True))
    def select_by_color(
        color: str, tolerance: int = 0, mode: str = "replace", file: str | None = None
    ) -> dict:
        """Select every pixel matching ``color`` (composited, within
        ``tolerance`` 0-255 per channel) — a global magic wand. ``mode`` is
        ``replace``/``add``/``subtract``."""
        if mode not in ("replace", "add", "subtract"):
            raise ToolError("mode must be replace, add, or subtract")
        if not 0 <= tolerance <= 255:
            raise ToolError("tolerance must be 0..255")
        r, g, b, a = parse_color(color)
        body = lua_locals(R=r, G=g, B=b, A=a, TOL=int(tolerance), MODE=mode) + _BY_COLOR
        return run(body, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Invert selection", idempotentHint=False))
    def invert_selection(file: str | None = None) -> dict:
        """Invert the current selection against the canvas bounds."""
        return run(_INVERT, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Get selection", readOnlyHint=True))
    def get_selection(file: str | None = None) -> dict:
        """Report whether a selection exists and its bounding rectangle.
        (Selection is editor-session state — in headless mode it doesn't persist
        between calls, so this is mainly a live-editor tool.)"""
        return run(_GET, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Erase area", destructiveHint=True))
    def erase_area(
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
        file: str | None = None,
    ) -> dict:
        """Erase pixels to transparent. Pass an explicit rect (works everywhere,
        including headless), or pass nothing to erase the current selection —
        including non-rectangular ones (live editor). One undo step."""
        rect = [x, y, width, height]
        if any(v is not None for v in rect) and not all(v is not None for v in rect):
            raise ToolError("pass all of x/y/width/height, or none of them")
        use_rect = all(v is not None for v in rect)
        body = (
            lua_locals(
                USE_RECT=use_rect,
                X=int(x or 0),
                Y=int(y or 0),
                W=int(width or 0),
                H=int(height or 0),
            )
            + _ERASE
        )
        return run(body, mutates=True, undo_label="Erase area", file=file)
