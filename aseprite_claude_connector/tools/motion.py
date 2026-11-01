"""Helpers that take the hand-work out of animating.

- ``inbetween`` — fill the gap between two drawn key poses and show the result.
- ``walk_cycle_template`` — a timed, tagged walk or run skeleton to draw over.
- ``apply_timing`` — ease, hold, or bounce applied to frame durations in one call.
- ``check_loop`` — compare the last frame with the first and flag a jump.

The poses and timing curves are plain Python, so they can be tested without Aseprite.
"""

from __future__ import annotations

import math
from statistics import median

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run
from .animate import _EASE
from .look import animation_picture

_MAX_INBETWEEN_PIXELS = 4_000_000
_MAX_COMPARED_STEPS = 12
EASINGS = ("linear", "ease_in", "ease_out", "smoothstep")
GAITS = {
    # share of the cycle a foot is on the ground, stride and bounce against leg length,
    # body lean, and the frame time that suits the gait
    "walk": {"stance": 0.6, "reach": 0.34, "lift": 0.24, "bob": 0.05, "lean": 0.05, "ms": 110},
    "run": {"stance": 0.38, "reach": 0.5, "lift": 0.42, "bob": 0.09, "lean": 0.16, "ms": 80},
}
PRESETS = ("ease_in", "ease_out", "ease_in_out", "hold", "bounce")

_INBETWEEN = (
    _EASE
    + """
local s = app.activeSprite
if not s then error("no active sprite") end
local layer = LAYER and findLayer(s, LAYER) or app.activeLayer
if not layer or not layer.isImage or layer.isTilemap then error("no target image layer") end
if TO ~= FROM + 1 then
  error("key poses must be on neighbouring frames: move them together, then in-between")
end
if FROM < 1 or TO > #s.frames then error("frames out of range (1.." .. #s.frames .. ")") end
if s.width * s.height * COUNT > MAX_PIXELS then error("sprite too large to in-between") end
local celA, celB = layer:cel(FROM), layer:cel(TO)
if not celA or not celB then error("both key frames need a cel on the layer") end
local pc = app.pixelColor
local mode = s.colorMode
local function solid(v)
  if mode == ColorMode.RGB then return pc.rgbaA(v) > 0 end
  if mode == ColorMode.GRAY then return pc.grayaA(v) > 0 end
  return v ~= s.transparentColor
end
local function canvas(cel)
  local img = Image(s.width, s.height, mode)
  if mode == ColorMode.INDEXED then img:clear(s.transparentColor) end
  if cel then img:drawImage(cel.image, cel.position) end
  return img
end
local imgA, imgB = canvas(celA), canvas(celB)
local boxA, boxB = imgA:shrinkBounds(), imgB:shrinkBounds()
if boxA.isEmpty or boxB.isEmpty then error("both key frames need art on the layer") end
local moveX = (boxB.x + boxB.width / 2) - (boxA.x + boxA.width / 2)
local moveY = (boxB.y + boxB.height / 2) - (boxA.y + boxA.height / 2)
local BAYER = { 0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5 }
local W, H = s.width, s.height
local empty = canvas(nil):getPixel(0, 0)
local function at(img, x, y)
  if x < 0 or y < 0 or x >= W or y >= H then return empty end
  return img:getPixel(x, y)
end
-- Both poses slide to where this frame sits between them, then trade pixels through an
-- ordered dither, which keeps every pixel a color the artist chose.
local function between(t, union)
  local out = canvas(nil)
  local ax, ay = math.floor(moveX * t + 0.5), math.floor(moveY * t + 0.5)
  local bx, by = ax - math.floor(moveX + 0.5), ay - math.floor(moveY + 0.5)
  for y = 0, H - 1 do
    for x = 0, W - 1 do
      local a, b = at(imgA, x - ax, y - ay), at(imgB, x - bx, y - by)
      local hasA, hasB = solid(a), solid(b)
      if hasA or hasB then
        local useB = (BAYER[(y % 4) * 4 + (x % 4) + 1] + 0.5) / 16 < t
        if union then
          out:drawPixel(x, y, (hasB and (useB or not hasA)) and b or a)
        elseif hasA and hasB then
          out:drawPixel(x, y, useB and b or a)
        elseif hasA and not useB then
          out:drawPixel(x, y, a)
        elseif hasB and useB then
          out:drawPixel(x, y, b)
        end
      end
    end
  end
  return out
end
local others = {}
local function walk(layers)
  for _, l in ipairs(layers) do
    if l.isGroup then walk(l.layers)
    elseif l ~= layer and not l.isTilemap and l:cel(FROM) then others[#others + 1] = l end
  end
end
walk(s.layers)
local duration = s.frames[FROM].duration
local middle = math.ceil(COUNT / 2)
local inserted = {}
for k = 1, COUNT do
  local at_frame = FROM + k
  s:newEmptyFrame(at_frame)
  s.frames[at_frame].duration = duration
  s:newCel(layer, at_frame, between(ease(k / (COUNT + 1)), SMEAR and k == middle), Point(0, 0))
  -- Everything else holds still rather than blinking out.
  for _, l in ipairs(others) do
    local held = l:cel(FROM)
    local cel = s:newCel(l, at_frame, held.image, held.position)
    cel.opacity = held.opacity
  end
  inserted[#inserted + 1] = at_frame
end
return J({ inserted = inserted, frames = #s.frames, layer = layer.name })
"""
)

_WALK = """
local s = app.activeSprite
if not s then error("no active sprite") end
if WIDE > s.width or TALL > s.height then
  error("this cycle needs a canvas of at least " .. WIDE .. "x" .. TALL)
end
local blank = #s.frames == 1
for _, c in ipairs(s.cels) do if not c.image:isEmpty() then blank = false end end
local first = blank and 1 or #s.frames + 1
-- A frame added after a tag's end joins that tag, so put the existing tags back.
local ends = {}
for i, t in ipairs(s.tags) do ends[i] = t.toFrame.frameNumber end
while #s.frames < first + COUNT - 1 do s:newEmptyFrame() end
for i, t in ipairs(s.tags) do t.toFrame = s.frames[ends[i]] end
local last = first + COUNT - 1
local PART = {
  near = Color{ r = 90, g = 190, b = 255 }, far = Color{ r = 40, g = 90, b = 150 },
  body = Color{ r = 240, g = 240, b = 240 },
}
local function line(img, x0, y0, x1, y1, c)
  local dx, dy = math.abs(x1 - x0), -math.abs(y1 - y0)
  local sx, sy = x0 < x1 and 1 or -1, y0 < y1 and 1 or -1
  local e = dx + dy
  while true do
    img:drawPixel(x0, y0, c)
    if x0 == x1 and y0 == y1 then return end
    local e2 = 2 * e
    if e2 >= dy then e = e + dy; x0 = x0 + sx end
    if e2 <= dx then e = e + dx; y0 = y0 + sy end
  end
end
local images = {}
for n = 1, COUNT do images[n] = Image(s.width, s.height, s.colorMode) end
local X, Y = math.floor(s.width / 2), s.height - 2
for f, a, b, c, d, part in SEGMENTS:gmatch("(%d+),(-?%d+),(-?%d+),(-?%d+),(-?%d+),(%a+);") do
  line(images[tonumber(f)], X + tonumber(a), Y + tonumber(b), X + tonumber(c), Y + tonumber(d), PART[part])
end
local guide = s:newLayer()
guide.name = GUIDE
guide.opacity = 140
for n = 1, COUNT do
  s:newCel(guide, first + n - 1, images[n], Point(0, 0))
  s.frames[first + n - 1].duration = MS / 1000
end
guide.isEditable = false
local art = s:newLayer()
art.name = ART
local tag = s:newTag(first, last)
tag.name = TAG
app.activeLayer = art
app.activeFrame = s.frames[first]
return J({ first_frame = first, last_frame = last, guide_layer = GUIDE, art_layer = ART, tag = TAG })
"""

_TIMING = """
local s = app.activeSprite
if not s then error("no active sprite") end
local n = FROM
for ms in DURATIONS:gmatch("%d+") do
  s.frames[n].duration = tonumber(ms) / 1000
  n = n + 1
end
return J({ from_frame = FROM, to_frame = n - 1 })
"""

_RANGE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local first, last = FROM or 1, TO or #s.frames
local direction = "forward"
if TAG then
  local hit = nil
  for _, t in ipairs(s.tags) do if t.name == TAG then hit = t; break end end
  if not hit then error("no tag named '" .. TAG .. "'") end
  first, last = hit.fromFrame.frameNumber, hit.toFrame.frameNumber
  if hit.aniDir == AniDir.PING_PONG or hit.aniDir == AniDir.PING_PONG_REVERSE then
    direction = "pingpong"
  end
end
if first < 1 or last > #s.frames or first > last then
  error("frame range " .. first .. ".." .. last .. " invalid (1.." .. #s.frames .. ")")
end
"""

_LOOP = (
    _RANGE
    + """
local function frame(n)
  local img = Image(s.width, s.height, ColorMode.RGB)
  img:drawSprite(s, n)
  return img
end
local function compare(a, b)
  local ia, ib = frame(a), frame(b)
  if ia:isEqual(ib) then return 0, nil end
  local changed, x0, y0, x1, y1 = 0, s.width, s.height, -1, -1
  for y = 0, s.height - 1 do
    for x = 0, s.width - 1 do
      if ia:getPixel(x, y) ~= ib:getPixel(x, y) then
        changed = changed + 1
        x0, y0 = math.min(x0, x), math.min(y0, y)
        x1, y1 = math.max(x1, x), math.max(y1, y)
      end
    end
  end
  return changed, { x = x0, y = y0, width = x1 - x0 + 1, height = y1 - y0 + 1 }
end
local n = last - first + 1
if n < 2 then error("a loop needs at least 2 frames") end
local seam, box = compare(last, first)
local steps = {}
local stride = math.max(1, (n - 1) / MAX_STEPS)
local at = 0
while at < n - 1 and #steps < MAX_STEPS do
  local a = first + math.floor(at)
  steps[#steps + 1] = compare(a, a + 1)
  at = at + stride
end
return J({ first_frame = first, last_frame = last, frames = n, seam_pixels = seam,
  seam_bbox = box, step_pixels = steps, direction = direction,
  total_pixels = s.width * s.height })
"""
)


def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def _knee(hip, foot, length, facing):
    """Two-bone reach: the knee on the side the figure faces. A foot just past full
    stretch straightens the leg rather than leaving the ground."""
    dx, dy = foot[0] - hip[0], foot[1] - hip[1]
    dist = math.hypot(dx, dy) or 1.0
    half = max(length, dist / 2)
    rise = math.sqrt(max(0.0, half * half - dist * dist / 4))
    mx, my = (hip[0] + foot[0]) / 2, (hip[1] + foot[1]) / 2
    nx, ny = -dy / dist, dx / dist
    if nx * facing < 0:
        nx, ny = -nx, -ny
    return mx + nx * rise, my + ny * rise


def foot_path(phase: float, gait: dict, reach: float, lift: float) -> tuple[float, float]:
    """Where a foot sits at ``phase`` (0..1), relative to the point under the hip and
    in the direction the figure faces. On the ground it travels backward, which is what
    carries the body forward; off the ground it swings forward."""
    phase %= 1.0
    stance = gait["stance"]
    if phase < stance:
        return reach * (1 - 2 * phase / stance), 0.0
    u = (phase - stance) / (1 - stance)
    return reach * (2 * _smooth(u) - 1), lift * math.sin(math.pi * u)


def walk_segments(height: int, count: int, gait_name: str, facing: int) -> list[list[tuple]]:
    """Each frame's skeleton as ``(x0, y0, x1, y1, part)`` lines, measured from the
    ground under the body, with y growing downward as it does on the canvas."""
    gait = GAITS[gait_name]
    leg = height * 0.5
    bone = leg * 0.53
    reach, lift = leg * gait["reach"], leg * gait["lift"]
    torso = height * 0.3
    arm = height * 0.14
    radius = max(1, round(height / 12))
    toe = max(1, round(height / 14))
    frames = []
    for n in range(count):
        p = n / count
        # A step every half cycle, lowest just after the foot takes the weight.
        bob = gait["bob"] * leg * math.cos(4 * math.pi * (p - gait["stance"] / 8))
        hip = (0.0, -leg + bob)
        neck = (facing * gait["lean"] * torso, hip[1] - torso)
        lines = []
        for side, offset in (("far", 0.5), ("near", 0.0)):
            fx, fy = foot_path(p + offset, gait, reach, lift)
            foot = (facing * fx, -fy)
            knee = _knee(hip, foot, bone, facing)
            lines += [(*hip, *knee, side), (*knee, *foot, side)]
            lines.append((*foot, foot[0] + facing * toe, foot[1], side))
            # Arms swing against the leg on their own side.
            swing = 0.55 * math.cos(2 * math.pi * (p + offset)) * -facing
            elbow = (neck[0] + arm * math.sin(swing), neck[1] + arm * math.cos(swing))
            bend = swing + facing * 0.5
            hand = (elbow[0] + arm * math.sin(bend), elbow[1] + arm * math.cos(bend))
            lines += [(*neck, *elbow, side), (*elbow, *hand, side)]
        lines.append((*hip, *neck, "body"))
        cx, cy = neck[0], neck[1] - radius - 1
        steps = max(8, radius * 6)
        for k in range(steps):
            a0, a1 = 2 * math.pi * k / steps, 2 * math.pi * (k + 1) / steps
            lines.append(
                (
                    cx + radius * math.cos(a0),
                    cy + radius * math.sin(a0),
                    cx + radius * math.cos(a1),
                    cy + radius * math.sin(a1),
                    "body",
                )
            )
        frames.append([(*(round(v) for v in s[:4]), s[4]) for s in lines])
    return frames


def timing_durations(preset: str, count: int, base_ms: int, strength: float) -> list[int]:
    """Frame times in ms for a preset. ``base_ms`` is the quickest frame and ``strength``
    how many times longer the slowest one lasts."""
    if count == 1:
        return [base_ms]
    extra = strength - 1
    out = []
    for i in range(count):
        u = i / (count - 1)
        if preset == "ease_in":  # gathers speed, so the first frames linger
            weight = 1 + extra * (1 - u) ** 2
        elif preset == "ease_out":
            weight = 1 + extra * u**2
        elif preset == "ease_in_out":
            weight = 1 + extra * (2 * u - 1) ** 2
        elif preset == "hold":
            weight = strength if i == count - 1 else 1
        else:  # bounce: hangs at the top of the arc and snaps through the impact
            weight = 1 + extra * (1 - abs(2 * u - 1))
        out.append(max(1, round(base_ms * weight)))
    return out


def loop_verdict(seam: int, steps: list[int], direction: str) -> dict:
    """Judge the jump from last frame to first against the steps inside the loop."""
    typical = median(steps) if steps else 0
    if direction == "pingpong":
        verdict, note = "pingpong", "ping-pong plays back the way it came, so it has no seam"
    elif seam == 0 and typical == 0:
        verdict, note = "static", "no frame differs from the next, so nothing moves"
    elif seam == 0:
        verdict, note = "duplicate", "the last frame equals the first, so the loop stutters there"
    elif seam > typical * 1.5 + 4:
        verdict = "jump"
        note = f"the seam changes {seam} pixels, against about {round(typical)} per frame"
    else:
        verdict, note = "smooth", "the seam is in line with the frames inside the loop"
    return {"verdict": verdict, "note": note, "typical_step_pixels": round(typical)}


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="In-between key poses"), structured_output=False)
    def inbetween(
        from_frame: int,
        count: int = 1,
        layer: str | None = None,
        easing: str = "smoothstep",
        smear: bool = False,
        max_size: int = 512,
        file: str | None = None,
    ) -> list:
        """Fill in ``count`` frames between the key pose on ``from_frame`` and the one on
        the next frame, then return a picture of the result. Unlike ``tween_frames`` it
        handles a pose that changes shape: both poses slide toward each other and trade
        pixels through an ordered dither, so no new colors appear. ``smear`` makes the
        middle frame hold both poses at once, for fast moves. Other layers hold still.
        It's a first pass to draw over, not finished art. ``easing``: linear, ease_in,
        ease_out, or smoothstep. One undo step. Headless: pass ``file``."""
        if not 1 <= count <= 16:
            raise ToolError("count must be 1..16")
        if easing not in EASINGS:
            raise ToolError(f"easing must be one of {', '.join(EASINGS)}")
        body = (
            lua_locals(
                FROM=int(from_frame),
                TO=int(from_frame) + 1,
                COUNT=int(count),
                LAYER=layer,
                EASING=easing,
                SMEAR=bool(smear),
                MAX_PIXELS=_MAX_INBETWEEN_PIXELS,
            )
            + _INBETWEEN
        )
        res = run(body, mutates=True, undo_label="In-between", file=file, capped=False)
        return animation_picture(
            res, from_frame, from_frame + count + 1, max_size=max_size, file=file
        )

    @mcp.tool(annotations=ToolAnnotations(title="Walk cycle template"))
    def walk_cycle_template(
        body_height: int,
        frames: int = 8,
        gait: str = "walk",
        facing: str = "right",
        tag: str | None = None,
        file: str | None = None,
    ) -> dict:
        """Lay down a timed, tagged walk or run skeleton to draw over. It adds ``frames``
        frames (an even number, 4-16), or uses the sprite if it's a blank single frame,
        with a locked faded guide layer and an empty art layer above it, which it leaves
        active. The near limbs are light blue and the far limbs dark blue. Feet travel
        backward on the ground and swing forward through the air, so the cycle walks
        forward; the figure stays in place, ready for scrolling scenery or game movement.
        Check it with ``look_animation``, then hide or delete the guide. One undo step.
        Headless: pass ``file``."""
        if gait not in GAITS:
            raise ToolError("gait must be walk or run")
        if facing not in ("right", "left"):
            raise ToolError("facing must be right or left")
        if frames % 2 or not 4 <= frames <= 16:
            raise ToolError("frames must be an even number from 4 to 16")
        if not 12 <= body_height <= 256:
            raise ToolError("body_height must be 12..256")
        cycle = walk_segments(body_height, frames, gait, 1 if facing == "right" else -1)
        reach = max(abs(v) for f in cycle for s in f for v in (s[0], s[2]))
        tall = 2 - min(v for f in cycle for s in f for v in (s[1], s[3]))
        encoded = "".join(
            f"{n},{s[0]},{s[1]},{s[2]},{s[3]},{s[4]};"
            for n, lines in enumerate(cycle, 1)
            for s in lines
        )
        body = (
            lua_locals(
                COUNT=int(frames),
                SEGMENTS=encoded,
                WIDE=2 * reach + 3,
                TALL=int(tall),
                MS=GAITS[gait]["ms"],
                GUIDE=f"{gait.title()} guide",
                ART=f"{gait.title()} art",
                TAG=tag or gait,
            )
            + _WALK
        )
        res = run(body, mutates=True, undo_label="Walk cycle template", file=file, capped=False)
        if isinstance(res, dict):
            res["frame_ms"] = GAITS[gait]["ms"]
        return res

    @mcp.tool(annotations=ToolAnnotations(title="Apply timing preset"))
    def apply_timing(
        preset: str,
        tag: str | None = None,
        from_frame: int | None = None,
        to_frame: int | None = None,
        base_ms: int = 80,
        strength: float = 3.0,
        file: str | None = None,
    ) -> dict:
        """Set frame durations from a preset, over a tag or a frame range (every frame by
        default). ``ease_in`` starts slow and speeds up, ``ease_out`` slows to a stop,
        ``ease_in_out`` does both, ``hold`` keeps the last frame on screen, and ``bounce``
        hangs at the middle and snaps through both ends. ``base_ms`` is the quickest frame
        and ``strength`` how many times longer the slowest lasts. One undo step. Headless:
        pass ``file``."""
        if preset not in PRESETS:
            raise ToolError(f"preset must be one of {', '.join(PRESETS)}")
        if not 1 <= base_ms <= 65535:
            raise ToolError("base_ms must be 1..65535")
        if not 1 <= strength <= 32:
            raise ToolError("strength must be 1..32")
        if tag is not None and (from_frame is not None or to_frame is not None):
            raise ToolError("pass either tag or a frame range, not both")
        span = run(
            lua_locals(FROM=from_frame, TO=to_frame, TAG=tag)
            + _RANGE
            + "return J({ count = last - first + 1, first = first })",
            file=file,
            save=False,
        )
        durations = timing_durations(preset, span["count"], base_ms, strength)
        body = lua_locals(FROM=span["first"], DURATIONS=",".join(map(str, durations))) + _TIMING
        res = run(body, mutates=True, undo_label="Apply timing", file=file, capped=False)
        if isinstance(res, dict):
            res["durations_ms"] = durations
        return res

    @mcp.tool(annotations=ToolAnnotations(title="Check animation loop", readOnlyHint=True))
    def check_loop(
        tag: str | None = None,
        from_frame: int | None = None,
        to_frame: int | None = None,
        file: str | None = None,
    ) -> dict:
        """Check whether an animation loops cleanly: compares its last frame with its
        first against the steps inside the loop. ``verdict`` is ``smooth``, ``jump``,
        ``duplicate`` (the last frame repeats the first, which stutters), ``static``, or
        ``pingpong``, and ``seam_bbox`` says where a jump is, ready to crop with ``look``.
        Compares up to 12 steps from long animations. Read-only. Headless: pass
        ``file``."""
        if tag is not None and (from_frame is not None or to_frame is not None):
            raise ToolError("pass either tag or a frame range, not both")
        body = (
            lua_locals(FROM=from_frame, TO=to_frame, TAG=tag, MAX_STEPS=_MAX_COMPARED_STEPS) + _LOOP
        )
        res = run(body, file=file)
        if not isinstance(res, dict):
            raise ToolError("loop check failed")
        return {**res, **loop_verdict(res["seam_pixels"], res["step_pixels"], res["direction"])}
