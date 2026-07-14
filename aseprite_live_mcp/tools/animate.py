"""Animation helpers.

- ``tween_frames`` — insert in-between frames that interpolate a cel's position from
  a start frame to an end frame (a cel-transform tween). Parity with diivi/Pro.
- ``smear_frame`` — the stretch: append a motion-smear frame that blends two frames
  (overlap averaged, single-frame areas ghosted). True pixel-content smear frames
  were found in no other tool — this is a first attempt at that, not a claim of a
  solved feature.
"""
from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

_TWEEN = """
local s = app.activeSprite
if not s then error("no active sprite") end
local layer = LAYER and findLayer(s, LAYER) or app.activeLayer
if not layer then error("no target layer") end
if FROM < 1 or TO > #s.frames or FROM >= TO then error("need 1 <= from < to <= frames") end
local celA = layer:cel(FROM)
local celB = layer:cel(TO)
if not celA or not celB then error("both from and to frames need a cel on the layer") end
local imgA = celA.image
local ax, ay = celA.position.x, celA.position.y
local bx, by = celB.position.x, celB.position.y
local inserted = {}
for k = 1, COUNT do
  local t = k / (COUNT + 1)
  local at = FROM + k
  s:newEmptyFrame(at)
  local nx = math.floor(ax + (bx - ax) * t + 0.5)
  local ny = math.floor(ay + (by - ay) * t + 0.5)
  s:newCel(layer, at, Image(imgA), Point(nx, ny))
  inserted[#inserted + 1] = at
end
return J({ inserted = inserted, frames = #s.frames })
"""

_SMEAR = """
local s = app.activeSprite
if not s then error("no active sprite") end
if s.colorMode ~= ColorMode.RGB then error("smear_frame requires an RGB sprite") end
local layer = LAYER and findLayer(s, LAYER) or app.activeLayer
if not layer then error("no target layer") end
if FROM < 1 or TO > #s.frames then error("frames out of range") end
local celA = layer:cel(FROM)
local celB = layer:cel(TO)
if not celA or not celB then error("both frames need a cel on the layer") end
local iA = Image(s.width, s.height, ColorMode.RGB); iA:drawImage(celA.image, celA.position)
local iB = Image(s.width, s.height, ColorMode.RGB); iB:drawImage(celB.image, celB.position)
local out = Image(s.width, s.height, ColorMode.RGB)
local pc = app.pixelColor
for y = 0, s.height - 1 do
  for x = 0, s.width - 1 do
    local va, vb = iA:getPixel(x, y), iB:getPixel(x, y)
    local aa, ab = pc.rgbaA(va), pc.rgbaA(vb)
    if aa > 0 and ab > 0 then
      out:drawPixel(x, y, pc.rgba(
        math.floor((pc.rgbaR(va) + pc.rgbaR(vb)) / 2),
        math.floor((pc.rgbaG(va) + pc.rgbaG(vb)) / 2),
        math.floor((pc.rgbaB(va) + pc.rgbaB(vb)) / 2), 255))
    elseif aa > 0 then
      out:drawPixel(x, y, pc.rgba(pc.rgbaR(va), pc.rgbaG(va), pc.rgbaB(va), 128))
    elseif ab > 0 then
      out:drawPixel(x, y, pc.rgba(pc.rgbaR(vb), pc.rgbaG(vb), pc.rgbaB(vb), 128))
    end
  end
end
local fr = s:newEmptyFrame()
s:newCel(layer, fr.frameNumber, out, Point(0, 0))
return J({ smearFrame = fr.frameNumber, frames = #s.frames })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Tween frames"))
    def tween_frames(
        from_frame: int, to_frame: int, count: int = 1, layer: str | None = None, file: str | None = None
    ) -> dict:
        """Insert ``count`` in-between frames between ``from_frame`` and ``to_frame``
        that interpolate the cel's position (a motion tween of the start cel's
        image). Headless: pass ``file``."""
        if count < 1:
            raise ToolError("count must be >= 1")
        body = lua_locals(FROM=int(from_frame), TO=int(to_frame), COUNT=int(count), LAYER=layer) + _TWEEN
        return run(body, mutates=True, undo_label="Tween frames", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Smear frame"))
    def smear_frame(from_frame: int, to_frame: int, layer: str | None = None, file: str | None = None) -> dict:
        """Append a motion-smear frame blending ``from_frame`` and ``to_frame``:
        overlapping pixels averaged, single-frame areas ghosted at half alpha — a
        pixel-content smear. RGB sprite only. Headless: pass ``file``."""
        body = lua_locals(FROM=int(from_frame), TO=int(to_frame), LAYER=layer) + _SMEAR
        return run(body, mutates=True, undo_label="Smear frame", file=file)
