"""Editor history tools (meaningful on the live editor)."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import run

_UNDO = """
local s = app.activeSprite
if not s then error("no active sprite") end
app.command.Undo()
return J({ undone = true })
"""

_REDO = """
local s = app.activeSprite
if not s then error("no active sprite") end
app.command.Redo()
return J({ redone = true })
"""

_SELECT_FRAME = """
local s = app.activeSprite
if not s then error("no active sprite") end
if N < 1 or N > #s.frames then error("frame out of range (1-" .. #s.frames .. ")") end
app.activeFrame = s.frames[N]
return J({ frame = N })
"""

_SELECT_LAYER = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, NAME)
if not l then error("no layer named '" .. NAME .. "'") end
app.activeLayer = l
return J({ layer = l.name })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Select frame", idempotentHint=True))
    def select_frame(number: int, file: str | None = None) -> dict:
        """Make a frame active, so the next edits land on it. Headless forgets this
        between calls, so use it as a step in ``edit_batch`` there."""
        return run(lua_locals(N=int(number)) + _SELECT_FRAME, file=file, batchable=True)

    @mcp.tool(annotations=ToolAnnotations(title="Select layer", idempotentHint=True))
    def select_layer(name: str, file: str | None = None) -> dict:
        """Make a layer active, so the next edits land on it. ``name`` may be a
        "Group/Layer" path. Headless forgets this between calls, so use it as a step
        in ``edit_batch`` there."""
        return run(lua_locals(NAME=name) + _SELECT_LAYER, file=file, batchable=True)

    @mcp.tool(annotations=ToolAnnotations(title="Undo"))
    def undo(file: str | None = None) -> dict:
        """Undo the last edit on the active sprite (live editor)."""
        return run(_UNDO, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Redo"))
    def redo(file: str | None = None) -> dict:
        """Redo the last undone edit (live editor)."""
        return run(_REDO, mutates=False, file=file)
