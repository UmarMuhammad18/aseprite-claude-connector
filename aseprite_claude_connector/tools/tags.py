"""Animation tag tools."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, parse_color, run

# User-facing direction name -> Aseprite AniDir enum key (all four verified
# present on 1.3.17.2).
_DIRECTIONS = {
    "forward": "FORWARD",
    "reverse": "REVERSE",
    "pingpong": "PING_PONG",
    "ping_pong": "PING_PONG",
    "pingpong_reverse": "PING_PONG_REVERSE",
    "ping_pong_reverse": "PING_PONG_REVERSE",
}

# Shared find-by-name prefix: leaves ``target`` bound to the tag named NAME.
_FIND = """
local s = app.activeSprite
if not s then error("no active sprite") end
local target = nil
for _, t in ipairs(s.tags) do if t.name == NAME then target = t; break end end
if not target then error("no tag named '" .. NAME .. "'") end
"""

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

_RENAME = """
local s = app.activeSprite
if not s then error("no active sprite") end
local target = nil
for _, t in ipairs(s.tags) do if t.name == OLD then target = t; break end end
if not target then error("no tag named '" .. OLD .. "'") end
target.name = NEW
return J({ renamed = OLD, name = NEW })
"""

_COLOR = (
    _FIND
    + """
target.color = Color{ r = R, g = G, b = B, a = A }
return J({ name = NAME, color = HEX })
"""
)

# Assignment by plain 1-based frame numbers works in any order on 1.3.17.2 —
# verified including the from > old-to case.
_RANGE = (
    _FIND
    + """
if FROM < 1 or TO > #s.frames or FROM > TO then
  error("frame range " .. FROM .. ".." .. TO .. " out of bounds (sprite has " .. #s.frames .. " frames)")
end
target.fromFrame = FROM
target.toFrame = TO
return J({ name = NAME, from = target.fromFrame.frameNumber, to = target.toFrame.frameNumber })
"""
)

_DIRECTION = (
    _FIND
    + """
target.aniDir = AniDir[DIRKEY]
return J({ name = NAME, direction = DIRNAME })
"""
)


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

    @mcp.tool(annotations=ToolAnnotations(title="Rename tag", idempotentHint=True))
    def rename_tag(old_name: str, new_name: str, file: str | None = None) -> dict:
        """Rename the animation tag ``old_name`` to ``new_name``. One undo step.
        Headless: pass ``file``."""
        body = lua_locals(OLD=old_name, NEW=new_name) + _RENAME
        return run(body, mutates=True, undo_label="Rename tag", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set tag color", idempotentHint=True))
    def set_tag_color(name: str, color: str, file: str | None = None) -> dict:
        """Set the timeline label color of the tag ``name`` (#rrggbb or
        #rrggbbaa). One undo step. Headless: pass ``file``."""
        r, g, b, a = parse_color(color)
        body = lua_locals(NAME=name, R=r, G=g, B=b, A=a, HEX=color) + _COLOR
        return run(body, mutates=True, undo_label="Set tag color", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set tag range", idempotentHint=True))
    def set_tag_range(name: str, from_frame: int, to_frame: int, file: str | None = None) -> dict:
        """Move the tag ``name`` to span frames ``from_frame``..``to_frame``
        (1-based, inclusive; validated against the sprite's frame count). One
        undo step. Headless: pass ``file``."""
        if from_frame < 1 or to_frame < from_frame:
            raise ToolError("need 1 <= from_frame <= to_frame")
        body = lua_locals(NAME=name, FROM=int(from_frame), TO=int(to_frame)) + _RANGE
        return run(body, mutates=True, undo_label="Set tag range", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set tag direction", idempotentHint=True))
    def set_tag_direction(name: str, direction: str, file: str | None = None) -> dict:
        """Set the playback direction of the tag ``name``: forward | reverse |
        pingpong | pingpong_reverse. One undo step. Headless: pass ``file``."""
        d = direction.strip().lower().replace("-", "_")
        key = _DIRECTIONS.get(d)
        if not key:
            raise ToolError(
                f"bad direction '{direction}' (forward|reverse|pingpong|pingpong_reverse)"
            )
        body = lua_locals(NAME=name, DIRKEY=key, DIRNAME=d) + _DIRECTION
        return run(body, mutates=True, undo_label="Set tag direction", file=file)
