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
