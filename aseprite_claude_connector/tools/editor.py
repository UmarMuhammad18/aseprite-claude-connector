"""Editor history tools (meaningful on the live editor)."""

from __future__ import annotations

from mcp.types import ToolAnnotations

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


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Undo"))
    def undo(file: str | None = None) -> dict:
        """Undo the last edit on the active sprite (live editor)."""
        return run(_UNDO, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Redo"))
    def redo(file: str | None = None) -> dict:
        """Redo the last undone edit (live editor)."""
        return run(_REDO, mutates=False, file=file)
