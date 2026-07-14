"""Selection tools (most useful in the live editor; selection is per-session)."""
from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import run

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
