"""Frame tools."""
from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

_ADD = """
local s = app.activeSprite
if not s then error("no active sprite") end
local f = s:newEmptyFrame()
return J({ frames = #s.frames, added = f.frameNumber })
"""

_DUP = """
local s = app.activeSprite
if not s then error("no active sprite") end
if N < 1 or N > #s.frames then error("frame out of range") end
local f = s:newFrame(s.frames[N])
return J({ frames = #s.frames, added = f.frameNumber })
"""

_DELETE = """
local s = app.activeSprite
if not s then error("no active sprite") end
if #s.frames <= 1 then error("cannot delete the last frame") end
if N < 1 or N > #s.frames then error("frame out of range") end
s:deleteFrame(N)
return J({ frames = #s.frames })
"""

_DURATION = """
local s = app.activeSprite
if not s then error("no active sprite") end
if N < 1 or N > #s.frames then error("frame out of range") end
s.frames[N].duration = MS / 1000.0
return J({ frame = N, durationMs = MS })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Add frame"))
    def add_frame(file: str | None = None) -> dict:
        """Append a new empty frame."""
        return run(_ADD, mutates=True, undo_label="Add frame", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Duplicate frame"))
    def duplicate_frame(number: int, file: str | None = None) -> dict:
        """Duplicate frame ``number`` (1-based)."""
        body = lua_locals(N=int(number)) + _DUP
        return run(body, mutates=True, undo_label="Duplicate frame", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Delete frame", destructiveHint=True))
    def delete_frame(number: int, file: str | None = None) -> dict:
        """Delete frame ``number`` (1-based). Cannot delete the last frame."""
        body = lua_locals(N=int(number)) + _DELETE
        return run(body, mutates=True, undo_label="Delete frame", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set frame duration", idempotentHint=True))
    def set_frame_duration(number: int, ms: int, file: str | None = None) -> dict:
        """Set frame ``number``'s duration in milliseconds."""
        if ms < 1:
            raise ToolError("ms must be >= 1")
        body = lua_locals(N=int(number), MS=int(ms)) + _DURATION
        return run(body, mutates=True, undo_label="Frame duration", file=file)
