"""Stamp painting — scatter a pre-authored element along a path.

``paint_with_stamp`` wraps ``Brush{type=BrushType.IMAGE}`` + ``app.useTool``:
the stamp (an external image, or a region cut from the sprite itself) is
stamped once per point, all inside one transaction — so an agent can scatter
rivets, bushes, or rubble along an arbitrary path in a single undo step.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

_STAMP = """
local s = app.activeSprite
if not s then error("no active sprite") end
local stamp
if SRC_PATH ~= nil then
  stamp = Image{ fromFile = SRC_PATH }
  if not stamp then error("could not load stamp image: " .. SRC_PATH) end
else
  if SW < 1 or SH < 1 then error("source_rect needs positive width/height") end
  local frame = app.activeFrame or s.frames[1]
  local full = Image(s.width, s.height, ColorMode.RGB)
  full:drawSprite(s, frame)
  stamp = Image(SW, SH, ColorMode.RGB)
  stamp:drawImage(full, Point(-SX, -SY))
end
local layer = LAYER and findLayer(s, LAYER) or app.activeLayer
if not layer or not layer.isImage then error("target layer must be an image layer") end
local frame = app.activeFrame or s.frames[1]
local br = Brush{ type = BrushType.IMAGE, image = stamp }
for _, p in ipairs(PTS) do
  app.useTool{ tool = "pencil", brush = br, points = { Point(p[1], p[2]) },
    layer = layer, frame = frame }
end
return J({ stamped = #PTS, stamp_width = stamp.width, stamp_height = stamp.height })
"""


def _points_lua(points) -> str:
    try:
        return "{" + ",".join(f"{{{int(p[0])},{int(p[1])}}}" for p in points) + "}"
    except (TypeError, IndexError, ValueError):
        raise ToolError("points must be a list of [x, y] pairs") from None


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Paint with stamp"))
    def paint_with_stamp(
        points: list,
        source_path: str | None = None,
        source_rect: list | None = None,
        layer: str | None = None,
        file: str | None = None,
    ) -> dict:
        """Stamp an image at each [x, y] in ``points`` (points are stamp centers).
        The stamp comes from ``source_path`` (a PNG) or ``source_rect``
        ([x, y, width, height] cut from the composited sprite). One undo step
        for the whole scatter. Headless: pass ``file``."""
        if not points:
            raise ToolError("need at least one point")
        if (source_path is None) == (source_rect is None):
            raise ToolError("pass exactly one of source_path or source_rect")
        sx = sy = sw = sh = 0
        if source_rect is not None:
            try:
                sx, sy, sw, sh = (int(v) for v in source_rect)
            except (TypeError, ValueError):
                raise ToolError("source_rect must be [x, y, width, height]") from None
        body = (
            f"local PTS = {_points_lua(points)}\n"
            + lua_locals(SRC_PATH=source_path, SX=sx, SY=sy, SW=sw, SH=sh, LAYER=layer)
            + _STAMP
        )
        return run(body, mutates=True, undo_label="Stamp paint", file=file)
