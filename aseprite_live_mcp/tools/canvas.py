"""Sprite lifecycle tools."""
from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

_CREATE_LUA = """
local cm = ColorMode.RGB
if MODE == "GRAY" then cm = ColorMode.GRAY
elseif MODE == "INDEXED" then cm = ColorMode.INDEXED end
local s = Sprite(W, H, cm)
return J({ width = s.width, height = s.height, colorMode = string.lower(MODE) })
"""


def register(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Create sprite", readOnlyHint=False, destructiveHint=False, idempotentHint=False
        )
    )
    def create_sprite(
        width: int, height: int, color_mode: str = "rgb", file: str | None = None
    ) -> dict:
        """Create a new sprite. Live: opens a new untitled sprite in the editor.
        Headless: writes a new .aseprite to ``file`` (required).
        ``color_mode`` is one of rgb | gray | indexed."""
        mode = {"rgb": "RGB", "gray": "GRAY", "grayscale": "GRAY", "indexed": "INDEXED"}.get(
            color_mode.strip().lower()
        )
        if not mode:
            raise ToolError(f"bad color_mode '{color_mode}' (rgb|gray|indexed)")
        if width < 1 or height < 1:
            raise ToolError("width and height must be >= 1")
        body = lua_locals(W=int(width), H=int(height), MODE=mode) + _CREATE_LUA
        # Creating a document isn't part of another sprite's undo history, so no
        # transaction; headless persists the new sprite to `file`.
        return run(body, mutates=False, file=file, save=bool(file))
