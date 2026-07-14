"""Slice tools — named atlas regions with pivots and 9-patch centers.

Slices matter here beyond parity: a slice's pivot flows into the Unity ``.meta``
via ``export_unity_slices`` (see tools/unity_export.py), so exported Unity sprites
carry their correct pivot point — something no competitor's Aseprite→Unity path
does. ``findSlice`` lives in the Lua prelude.
"""
from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import run

_NEW = """
local s = app.activeSprite
if not s then error("no active sprite") end
local sl = s:newSlice(Rectangle(X, Y, W, H))
sl.name = NAME
return J({ name = sl.name, x = X, y = Y, width = W, height = H })
"""

_PIVOT = """
local s = app.activeSprite
if not s then error("no active sprite") end
local sl = findSlice(s, NAME)
if not sl then error("no slice named '" .. NAME .. "'") end
sl.pivot = Point(PX, PY)
return J({ name = NAME, pivot = { PX, PY } })
"""

_CENTER = """
local s = app.activeSprite
if not s then error("no active sprite") end
local sl = findSlice(s, NAME)
if not sl then error("no slice named '" .. NAME .. "'") end
sl.center = Rectangle(X, Y, W, H)
return J({ name = NAME, center = { X, Y, W, H } })
"""

_LIST = """
local s = app.activeSprite
if not s then error("no active sprite") end
local out = {}
for i, sl in ipairs(s.slices) do
  local b = sl.bounds
  local e = { name = sl.name, x = b.x, y = b.y, width = b.width, height = b.height }
  if sl.pivot then e.pivot = { sl.pivot.x, sl.pivot.y } end
  if sl.center then e.center = { sl.center.x, sl.center.y, sl.center.width, sl.center.height } end
  out[i] = e
end
return J({ slices = out, count = #out })
"""

_DELETE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local sl = findSlice(s, NAME)
if not sl then error("no slice named '" .. NAME .. "'") end
s:deleteSlice(sl)
return J({ deleted = NAME })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Create slice"))
    def create_slice(name: str, x: int, y: int, width: int, height: int, file: str | None = None) -> dict:
        """Create a named slice (atlas region) at the given rectangle. Slices become
        Unity sprites via export_unity_slices. One undo step. Headless: pass ``file``."""
        body = lua_locals(NAME=name, X=int(x), Y=int(y), W=int(width), H=int(height)) + _NEW
        return run(body, mutates=True, undo_label="Create slice", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set slice pivot", idempotentHint=True))
    def set_slice_pivot(name: str, pivot_x: int, pivot_y: int, file: str | None = None) -> dict:
        """Set a slice's pivot point, in pixels relative to the slice's top-left. This
        pivot is exported into the Unity ``.meta`` by export_unity_slices. One undo
        step. Headless: pass ``file``."""
        body = lua_locals(NAME=name, PX=int(pivot_x), PY=int(pivot_y)) + _PIVOT
        return run(body, mutates=True, undo_label="Set slice pivot", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set slice center (9-patch)", idempotentHint=True))
    def set_slice_center(name: str, x: int, y: int, width: int, height: int, file: str | None = None) -> dict:
        """Set a slice's 9-patch stretchable center rectangle (relative to the slice).
        One undo step. Headless: pass ``file``."""
        body = lua_locals(NAME=name, X=int(x), Y=int(y), W=int(width), H=int(height)) + _CENTER
        return run(body, mutates=True, undo_label="Set slice center", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="List slices", readOnlyHint=True))
    def list_slices(file: str | None = None) -> dict:
        """List every slice with its bounds, pivot, and 9-patch center. Read-only.
        Headless: pass ``file``."""
        return run(_LIST, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Delete slice", destructiveHint=True))
    def delete_slice(name: str, file: str | None = None) -> dict:
        """Delete the slice with the given name. One undo step. Headless: pass ``file``."""
        body = lua_locals(NAME=name) + _DELETE
        return run(body, mutates=True, undo_label="Delete slice", file=file)
