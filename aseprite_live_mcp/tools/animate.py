"""Animation helpers.

- ``tween_frames`` — insert in-between frames that interpolate a cel's position from
  a start frame to an end frame (a cel-transform tween). Parity with diivi/Pro.
- ``smear_frame`` — the stretch: append a motion-smear frame that blends two frames
  (overlap averaged, single-frame areas ghosted). True pixel-content smear frames
  were found in no other tool — this is a first attempt at that, not a claim of a
  solved feature.
- ``frame_diff`` — pixel-exact diff of two composited frames (count, ratio, change
  bbox): the "did this frame actually move / did my edit leak into other frames"
  check an agent can't do by eye.
- ``render_onion_composite`` — write a PNG of one frame with its neighbors ghosted
  (prev tinted red, next tinted blue, Aseprite's own convention) so an agent can
  *see* motion arcs without flipping frames.
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


_DIFF = """
local s = app.activeSprite
if not s then error("no active sprite") end
if FA < 1 or FA > #s.frames or FB < 1 or FB > #s.frames then
  error("frame out of range (sprite has " .. #s.frames .. " frames)")
end
local ia = Image(s.width, s.height, ColorMode.RGB); ia:drawSprite(s, FA)
local ib = Image(s.width, s.height, ColorMode.RGB); ib:drawSprite(s, FB)
local changed, minx, miny, maxx, maxy = 0, s.width, s.height, -1, -1
for y = 0, s.height - 1 do
  for x = 0, s.width - 1 do
    if ia:getPixel(x, y) ~= ib:getPixel(x, y) then
      changed = changed + 1
      if x < minx then minx = x end
      if x > maxx then maxx = x end
      if y < miny then miny = y end
      if y > maxy then maxy = y end
    end
  end
end
local total = s.width * s.height
local bbox = nil
if changed > 0 then bbox = { x = minx, y = miny, width = maxx - minx + 1, height = maxy - miny + 1 } end
return J({ frame_a = FA, frame_b = FB, changed_pixels = changed, total_pixels = total,
  changed_ratio = changed / total, bbox = bbox, identical = (changed == 0) })
"""

_ONION = """
local s = app.activeSprite
if not s then error("no active sprite") end
if s.width * s.height > 262144 then error("sprite too large for onion composite (cap 512x512)") end
if FRAME < 1 or FRAME > #s.frames then error("frame out of range") end
local pc = app.pixelColor
local out = Image(s.width, s.height, ColorMode.RGB)
-- src-over blend of a ghost frame, alpha scaled by OP, tinted toward (tr,tg,tb).
local function ghost(fr, tr, tg, tb)
  local gi = Image(s.width, s.height, ColorMode.RGB); gi:drawSprite(s, fr)
  for y = 0, s.height - 1 do
    for x = 0, s.width - 1 do
      local v = gi:getPixel(x, y)
      local a = pc.rgbaA(v)
      if a > 0 then
        local sa = (a / 255) * OP
        local r = math.floor(pc.rgbaR(v) * 0.6 + tr * 0.4)
        local g = math.floor(pc.rgbaG(v) * 0.6 + tg * 0.4)
        local b = math.floor(pc.rgbaB(v) * 0.6 + tb * 0.4)
        local d = out:getPixel(x, y)
        local da = pc.rgbaA(d) / 255
        local oa = sa + da * (1 - sa)
        if oa > 0 then
          out:drawPixel(x, y, pc.rgba(
            math.floor((r * sa + pc.rgbaR(d) * da * (1 - sa)) / oa + 0.5),
            math.floor((g * sa + pc.rgbaG(d) * da * (1 - sa)) / oa + 0.5),
            math.floor((b * sa + pc.rgbaB(d) * da * (1 - sa)) / oa + 0.5),
            math.floor(oa * 255 + 0.5)))
        end
      end
    end
  end
end
local gp, gn = 0, 0
for k = PREV, 1, -1 do
  local fr = FRAME - k
  if fr >= 1 then ghost(fr, 255, 60, 60); gp = gp + 1 end
end
for k = 1, NXT do
  local fr = FRAME + k
  if fr <= #s.frames then ghost(fr, 60, 120, 255); gn = gn + 1 end
end
-- the current frame, full opacity, over the ghosts
local ci = Image(s.width, s.height, ColorMode.RGB); ci:drawSprite(s, FRAME)
for y = 0, s.height - 1 do
  for x = 0, s.width - 1 do
    local v = ci:getPixel(x, y)
    if pc.rgbaA(v) > 0 then out:drawPixel(x, y, v) end
  end
end
out:saveAs(OUT)
return J({ png = OUT, frame = FRAME, ghosts_prev = gp, ghosts_next = gn })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Tween frames"))
    def tween_frames(
        from_frame: int,
        to_frame: int,
        count: int = 1,
        layer: str | None = None,
        file: str | None = None,
    ) -> dict:
        """Insert ``count`` in-between frames between ``from_frame`` and ``to_frame``
        that interpolate the cel's position (a motion tween of the start cel's
        image). Headless: pass ``file``."""
        if count < 1:
            raise ToolError("count must be >= 1")
        body = (
            lua_locals(FROM=int(from_frame), TO=int(to_frame), COUNT=int(count), LAYER=layer)
            + _TWEEN
        )
        return run(body, mutates=True, undo_label="Tween frames", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Smear frame"))
    def smear_frame(
        from_frame: int, to_frame: int, layer: str | None = None, file: str | None = None
    ) -> dict:
        """Append a motion-smear frame blending ``from_frame`` and ``to_frame``:
        overlapping pixels averaged, single-frame areas ghosted at half alpha — a
        pixel-content smear. RGB sprite only. Headless: pass ``file``."""
        body = lua_locals(FROM=int(from_frame), TO=int(to_frame), LAYER=layer) + _SMEAR
        return run(body, mutates=True, undo_label="Smear frame", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Frame diff", readOnlyHint=True))
    def frame_diff(frame_a: int, frame_b: int, file: str | None = None) -> dict:
        """Pixel-exact diff of two composited frames: changed-pixel count and ratio,
        the bounding box of the change, and whether they're identical. Use it to
        verify an animation actually moves — or that an edit didn't leak into
        frames it shouldn't touch. Headless: pass ``file``."""
        body = lua_locals(FA=int(frame_a), FB=int(frame_b)) + _DIFF
        return run(body, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Render onion-skin composite", readOnlyHint=True))
    def render_onion_composite(
        frame: int,
        output_path: str,
        prev: int = 1,
        next: int = 1,
        opacity: float = 0.35,
        file: str | None = None,
    ) -> dict:
        """Write a PNG of ``frame`` with up to ``prev`` earlier frames ghosted in
        red and ``next`` later frames ghosted in blue (Aseprite's onion-skin
        convention) at the given ghost ``opacity`` — so you can *see* the motion
        arc in one image. Does not modify the sprite. Headless: pass ``file``."""
        if not (0.05 <= float(opacity) <= 1.0):
            raise ToolError("opacity must be between 0.05 and 1.0")
        if prev < 0 or next < 0 or prev + next < 1:
            raise ToolError("need at least one ghost frame (prev + next >= 1)")
        body = (
            lua_locals(
                FRAME=int(frame),
                PREV=int(prev),
                NXT=int(next),
                OP=float(opacity),
                OUT=str(output_path),
            )
            + _ONION
        )
        return run(body, file=file)
