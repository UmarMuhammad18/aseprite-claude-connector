"""Animation tag tools."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import run

_CREATE = """
local s = app.activeSprite
if not s then error("no active sprite") end
if FROM < 1 or TO > #s.frames or FROM > TO then error("frame range out of bounds") end
local t = s:newTag(FROM, TO)
t.name = NAME
return J({ name = t.name, from = t.fromFrame.frameNumber, to = t.toFrame.frameNumber })
"""

_DELETE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local target = nil
for _, t in ipairs(s.tags) do if t.name == NAME then target = t; break end end
if not target then error("no tag named '" .. NAME .. "'") end
s:deleteTag(target)
return J({ deleted = NAME })
"""

_LIST = """
local s = app.activeSprite
if not s then error("no active sprite") end
local out = {}
for i, t in ipairs(s.tags) do
  out[i] = { name = t.name, from = t.fromFrame.frameNumber, to = t.toFrame.frameNumber }
end
return J({ tags = out })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Create tag"))
    def create_tag(name: str, from_frame: int, to_frame: int, file: str | None = None) -> dict:
        """Create an animation tag named ``name`` spanning frames ``from_frame``..``to_frame`` (1-based)."""
        body = lua_locals(NAME=name, FROM=int(from_frame), TO=int(to_frame)) + _CREATE
        return run(body, mutates=True, undo_label="Create tag", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Delete tag", destructiveHint=True))
    def delete_tag(name: str, file: str | None = None) -> dict:
        """Delete the animation tag named ``name``."""
        body = lua_locals(NAME=name) + _DELETE
        return run(body, mutates=True, undo_label="Delete tag", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="List tags", readOnlyHint=True))
    def list_tags(file: str | None = None) -> dict:
        """List animation tags with their frame ranges."""
        return run(_LIST, file=file)
