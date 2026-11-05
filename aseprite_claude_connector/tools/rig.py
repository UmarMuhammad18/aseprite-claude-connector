"""Character animation from parts.

``animate_parts`` poses a character cut into part layers (head, torso, arms, legs;
``split_into_layers`` makes them) at a few key frames and fills in the frames
between. Parts turn about their pivots with pixel-art-safe rotation, and a part
with a parent follows it. See ``rig.py`` for the image work.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ..rig import Part, pose_at, render, world
from ._common import ToolError, run
from .look import pixels_loader
from .scene import _read, _strip

_MAX_FRAMES = 64

_ANIMATE = """
local s = app.activeSprite
if s.colorMode ~= ColorMode.RGB then
  error("animate_parts works on RGB sprites; convert with set_color_mode first")
end
local strip = load_image()
local layers = {}
for name in NAMES:gmatch("[^\\n]+") do
  local l = findLayer(s, name)
  if not l or l.isGroup or l.isTilemap then error("no image layer named '" .. name .. "'") end
  layers[#layers + 1] = l
end
while #s.frames < COUNT do s:newFrame(#s.frames) end
for row, l in ipairs(layers) do
  for i = 1, COUNT do
    s:newCel(l, i, Image(strip, Rectangle((i - 1) * W, (row - 1) * H, W, H)), Point(0, 0))
  end
end
for i = 1, COUNT do s.frames[i].duration = DURATION / 1000 end
local tagged = false
for _, t in ipairs(s.tags) do if t.name == TAG then tagged = true end end
if not tagged then
  local t = s:newTag(1, COUNT)
  t.name = TAG
end
local names = {}
for _, l in ipairs(layers) do names[#names + 1] = l.name end
return J({ parts = names, frames = COUNT, duration_ms = DURATION, tag = TAG })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Animate a character by its parts"))
    def animate_parts(
        poses: list[dict],
        frames: int,
        pivots: dict[str, list[float]] | None = None,
        parents: dict[str, str] | None = None,
        loop: bool = True,
        easing: str = "smooth",
        duration_ms: int = 100,
        from_frame: int = 1,
        tag: str = "move",
        file: str | None = None,
    ) -> dict:
        """Animate a character made of part layers like a cut-out puppet. ``poses``
        are key poses: ``{"frame": 1, "part": "Arm", "angle": -20, "x": 0, "y": 1}``,
        with ``angle`` in degrees clockwise and ``x``/``y`` a move in pixels; any
        left out are 0. Frames between keys are filled in (``easing`` is ``smooth``
        or ``linear``), and with ``loop`` the last pose eases back to the first.
        ``pivots`` maps a part to the [x, y] it turns about (a shoulder, a hip; its
        middle by default). ``parents`` maps a part to the one it hangs from, so
        ``{"Forearm": "Arm"}`` keeps the forearm on the arm. Each part is drawn from
        its ``from_frame`` pixels, turned with RotSprite-style rotation so edges stay
        crisp. Frames are added as needed and tagged ``tag``. Check the result with
        ``look_animation`` and ``check_loop``. One undo step. Headless: pass
        ``file``."""
        if not 2 <= frames <= _MAX_FRAMES:
            raise ToolError(f"frames must be 2..{_MAX_FRAMES}")
        if easing not in ("smooth", "linear"):
            raise ToolError("easing must be smooth or linear")
        if not 10 <= duration_ms <= 5000:
            raise ToolError("duration_ms must be 10..5000")
        pivots, parents = pivots or {}, parents or {}
        keys: dict[str, list[dict]] = {}
        for p in poses:
            try:
                name, at = str(p["part"]), int(p["frame"])
                key = {
                    "frame": at,
                    "angle": float(p.get("angle", 0)),
                    "x": float(p.get("x", 0)),
                    "y": float(p.get("y", 0)),
                }
            except (KeyError, TypeError, ValueError):
                raise ToolError(
                    'each pose needs "part" and "frame"; angle, x, y are numbers'
                ) from None
            if not 1 <= at <= frames:
                raise ToolError(f"pose frame {at} is outside 1..{frames}")
            keys.setdefault(name, []).append(key)
        if not keys:
            raise ToolError("pass at least one pose")
        names = list(dict.fromkeys([*keys, *parents, *parents.values(), *pivots]))
        sources = {}
        for name in names:
            src, _ = _read(name, from_frame, file)
            sources[name] = Part(src)
        centres = {
            n: tuple(pivots[n]) if n in pivots else sources[n].centre()
            for n in names
            if not sources[n].empty or n in pivots
        }
        for n in names:
            centres.setdefault(n, (0.0, 0.0))
        for k in keys.values():
            k.sort(key=lambda key: key["frame"])
        rendered = []
        for name in names:
            for f in range(1, frames + 1):
                now = {n: pose_at(keys.get(n, []), f, frames, loop, easing) for n in names}
                rendered.append(render(sources[name], world(name, now, centres, parents)))
        width, height = rendered[0].width, rendered[0].height
        body = (
            pixels_loader(_strip(rendered, rows=len(names)))
            + lua_locals(
                NAMES="\n".join(names),
                COUNT=frames,
                W=width,
                H=height,
                DURATION=int(duration_ms),
                TAG=tag,
            )
            + _ANIMATE
        )
        return run(body, mutates=True, undo_label="Animate parts", file=file)
