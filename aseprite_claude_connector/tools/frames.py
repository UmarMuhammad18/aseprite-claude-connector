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

_ADD_MANY = """
local s = app.activeSprite
if not s then error("no active sprite") end
local added = {}
for i = 1, COUNT do
  local f = s:newEmptyFrame()
  added[#added + 1] = f.frameNumber
end
return J({ frames = #s.frames, added = added })
"""

_DURATION_RANGE = """
local s = app.activeSprite
if not s then error("no active sprite") end
if FROM < 1 or TO > #s.frames or FROM > TO then error("range out of bounds (1.." .. #s.frames .. ")") end
for n = FROM, TO do s.frames[n].duration = MS / 1000.0 end
return J({ from = FROM, to = TO, durationMs = MS })
"""

# Manual reverse: swap cel content + frame durations across the range for every
# image layer. app.command.ReverseFrames depends on timeline range state, which
# doesn't exist headless — the manual swap behaves identically in both backends.
_REVERSE = """
local s = app.activeSprite
if not s then error("no active sprite") end
if FROM < 1 or TO > #s.frames or FROM >= TO then error("need 1 <= from < to <= frames") end
local function allImageLayers(layers, out)
  for _, l in ipairs(layers) do
    if l.isGroup then allImageLayers(l.layers, out)
    elseif l.isImage then out[#out + 1] = l end
  end
  return out
end
local layers = allImageLayers(s.layers, {})
local lo, hi = FROM, TO
while lo < hi do
  for _, layer in ipairs(layers) do
    local a, b = layer:cel(lo), layer:cel(hi)
    local ai = a and { img = Image(a.image), pos = a.position, op = a.opacity } or nil
    local bi = b and { img = Image(b.image), pos = b.position, op = b.opacity } or nil
    if a then s:deleteCel(layer, lo) end
    if b then s:deleteCel(layer, hi) end
    if bi then
      local c = s:newCel(layer, lo, bi.img, bi.pos)
      c.opacity = bi.op
    end
    if ai then
      local c = s:newCel(layer, hi, ai.img, ai.pos)
      c.opacity = ai.op
    end
  end
  local d = s.frames[lo].duration
  s.frames[lo].duration = s.frames[hi].duration
  s.frames[hi].duration = d
  lo = lo + 1
  hi = hi - 1
end
return J({ reversed = { FROM, TO } })
"""

# Exact keys verified against Aseprite's data/pref.xml (section id="onionskin").
_ONION_PREF = """
local s = app.activeSprite
if not s then error("no active sprite") end
local o = app.preferences.document(s).onionskin
o.active = ACTIVE
o.prev_frames = PREV
o.next_frames = NXT
if LOOP_TAG ~= nil then o.loop_tag = LOOP_TAG end
return J({ active = o.active, prev_frames = o.prev_frames, next_frames = o.next_frames })
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

    @mcp.tool(annotations=ToolAnnotations(title="Add frames"))
    def add_frames(count: int, file: str | None = None) -> dict:
        """Append ``count`` empty frames in one undo step."""
        if not 1 <= count <= 256:
            raise ToolError("count must be 1..256")
        body = lua_locals(COUNT=int(count)) + _ADD_MANY
        return run(body, mutates=True, undo_label="Add frames", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set frame durations", idempotentHint=True))
    def set_frame_durations(
        from_frame: int, to_frame: int, ms: int, file: str | None = None
    ) -> dict:
        """Set every frame in [from_frame..to_frame] to ``ms`` milliseconds."""
        if ms < 1:
            raise ToolError("ms must be >= 1")
        body = lua_locals(FROM=int(from_frame), TO=int(to_frame), MS=int(ms)) + _DURATION_RANGE
        return run(body, mutates=True, undo_label="Frame durations", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Reverse frames"))
    def reverse_frames(
        from_frame: int | None = None, to_frame: int | None = None, file: str | None = None
    ) -> dict:
        """Reverse frame order (cels on every layer, plus durations) — the whole
        sprite by default, or the inclusive [from_frame..to_frame] range. One
        undo step."""
        for v in (from_frame, to_frame):
            if v is not None and v < 1:
                raise ToolError("frame numbers are 1-based")
        body_range = (
            "local FROM = " + (str(int(from_frame)) if from_frame is not None else "1") + "\n"
            "local TO = "
            + (str(int(to_frame)) if to_frame is not None else "#app.activeSprite.frames")
            + "\n"
        )
        guard = 'if not app.activeSprite then error("no active sprite") end\n'
        return run(
            guard + body_range + _REVERSE,
            mutates=True,
            undo_label="Reverse frames",
            file=file,
        )

    @mcp.tool(annotations=ToolAnnotations(title="Set onion skin", idempotentHint=True))
    def set_onion_skin(
        active: bool,
        prev_frames: int = 1,
        next_frames: int = 1,
        loop_tag: bool | None = None,
        file: str | None = None,
    ) -> dict:
        """Configure the editor's onion-skin view: on/off, ghost counts each
        direction, and whether ghosting stays inside the current tag. A view
        preference — visually meaningful in the live editor. (For a rendered
        onion-skin image any backend can produce, use ``render_onion_composite``.)"""
        if not (0 <= prev_frames <= 16 and 0 <= next_frames <= 16):
            raise ToolError("prev_frames/next_frames must be 0..16")
        body = (
            lua_locals(
                ACTIVE=bool(active), PREV=int(prev_frames), NXT=int(next_frames), LOOP_TAG=loop_tag
            )
            + _ONION_PREF
        )
        return run(body, mutates=False, file=file)
