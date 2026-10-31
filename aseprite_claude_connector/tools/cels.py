"""Cel tools (the image on a given layer + frame).

``layer`` (name) and ``frame`` (1-based number) default to the active ones.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

# Prelude for resolving the target cel from optional LAYER / FRAME locals.
_RESOLVE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local layer = LAYER and findLayer(s, LAYER) or app.activeLayer
if not layer then error("no target layer") end
local fn = FRAME or (app.activeFrame and app.activeFrame.frameNumber) or 1
"""

_CLEAR = (
    _RESOLVE
    + """
local cel = layer:cel(fn)
if cel then cel.image = Image(cel.image.width, cel.image.height, s.colorMode) end
return J({ cleared = true, layer = layer.name, frame = fn })
"""
)

_POSITION = (
    _RESOLVE
    + """
local cel = layer:cel(fn)
if not cel then error("no cel at layer '" .. layer.name .. "' frame " .. fn) end
cel.position = Point(X, Y)
return J({ layer = layer.name, frame = fn, x = X, y = Y })
"""
)

_OPACITY = (
    _RESOLVE
    + """
local cel = layer:cel(fn)
if not cel then error("no cel at layer '" .. layer.name .. "' frame " .. fn) end
cel.opacity = OPACITY
return J({ layer = layer.name, frame = fn, opacity = OPACITY })
"""
)


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Clear cel", destructiveHint=True))
    def clear_cel(
        layer: str | None = None, frame: int | None = None, file: str | None = None
    ) -> dict:
        """Empty the cel at the given layer + frame (transparent)."""
        body = lua_locals(LAYER=layer, FRAME=None if frame is None else int(frame)) + _CLEAR
        return run(body, mutates=True, undo_label="Clear cel", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set cel position", idempotentHint=True))
    def set_cel_position(
        x: int, y: int, layer: str | None = None, frame: int | None = None, file: str | None = None
    ) -> dict:
        """Move the cel's top-left origin to (x, y)."""
        body = (
            lua_locals(LAYER=layer, FRAME=None if frame is None else int(frame), X=int(x), Y=int(y))
            + _POSITION
        )
        return run(body, mutates=True, undo_label="Cel position", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set cel opacity", idempotentHint=True))
    def set_cel_opacity(
        opacity: int, layer: str | None = None, frame: int | None = None, file: str | None = None
    ) -> dict:
        """Set the cel's opacity (0-255)."""
        if not 0 <= opacity <= 255:
            raise ToolError("opacity must be 0-255")
        body = (
            lua_locals(
                LAYER=layer, FRAME=None if frame is None else int(frame), OPACITY=int(opacity)
            )
            + _OPACITY
        )
        return run(body, mutates=True, undo_label="Cel opacity", file=file)
