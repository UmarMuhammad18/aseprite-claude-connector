"""Atmosphere.

- ``paint_sky`` — a sky for a time of day, with a sun, clouds that can drift, and
  stars.
- ``paint_mountains`` — hazy ranges on the horizon, lit from the sun's side.
- ``reflect_in_water`` — the scene mirrored into rippling water below a horizon.
- ``add_glow`` — a pool of firelight or lantern light that can flicker.
- ``add_rim_light`` — the edge of a layer that faces a light, picked out.
- ``add_fire`` — a looping fire with embers.

Each one writes a new layer and leaves the art it works from alone. See
``atmosphere.py`` for the image work.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..atmosphere import (
    FLAMES,
    SKIES,
    bounds,
    cloud_frames,
    cropped,
    fire_frames,
    glow,
    mountains,
    reflection,
    rim_light,
    sky,
)
from ..lua import lua_locals
from ..raster import Raster
from ._common import ToolError, parse_color, run
from .look import _LOOK_HELPERS, _raster, pixels_loader
from .scene import _strip

_MAX_PIXELS = 3_000_000

_INFO = """
local s = app.activeSprite
if not s then error("no active sprite (headless: pass file=)") end
if s.colorMode ~= ColorMode.RGB then
  error("this tool works on RGB sprites; convert with set_color_mode first")
end
return J({ width = s.width, height = s.height, frames = #s.frames,
  frame = app.activeFrame and app.activeFrame.frameNumber or 1 })
"""

# Every frame of some layers (or of everything visible), down to row BOTTOM.
_GRAB = """
if s.colorMode ~= ColorMode.RGB then
  error("this tool works on RGB sprites; convert with set_color_mode first")
end
local wanted = nil
if NAMES then
  wanted = {}
  for name in NAMES:gmatch("[^\\n]+") do
    if not findLayer(s, name) then error("no layer named '" .. name .. "'") end
    wanted[name] = true
  end
end
local rows = math.min(BOTTOM or s.height - 1, s.height - 1) + 1
local first, last = ONLY or 1, ONLY or #s.frames
if s.width * rows * (last - first + 1) > MAX_PIXELS then
  error("too many pixels to read at once; use fewer frames or a smaller sprite")
end
local packed = {}
for n = first, last do
  local img = Image(s.width, s.height, ColorMode.RGB)
  if wanted then
    for _, l in ipairs(s.layers) do
      if wanted[l.name] then drawLayer(img, l, n) end
    end
  else
    img:drawSprite(s, n)
  end
  if rows < s.height then img = Image(img, Rectangle(0, 0, s.width, rows)) end
  packed[#packed + 1] = pack(img)
end
return J({ frames = packed, width = s.width, height = rows, canvas_height = s.height,
  count = #s.frames })
"""

# A new layer holding the strip: one column per frame, or one picture on every frame.
_NEW_LAYER = """
local s = app.activeSprite
local strip = load_image()
local anchor = nil
if PLACE == "above" then
  for name in NAMES:gmatch("[^\\n]+") do
    local l = findLayer(s, name)
    if l and (not anchor or l.stackIndex > anchor.stackIndex) then anchor = l end
  end
end
local l = s:newLayer()
l.name = NAME
if PLACE == "bottom" then
  l.stackIndex = 1
elseif anchor then
  l.parent = anchor.parent
  l.stackIndex = anchor.stackIndex + 1
elseif LOW then
  l.stackIndex = 1
end
if ADD then l.blendMode = BlendMode.ADDITION end
local col = 0
for n in FRAMES:gmatch("%d+") do
  s:newCel(l, tonumber(n), Image(strip, Rectangle((COLUMNS == 1 and 0 or col) * W, 0, W, H)),
    Point(LEFT, TOP))
  col = col + 1
end
return J({ layer = l.name, frames = col })
"""

# A still sky at the bottom of the stack with its drifting clouds on a layer above it.
# ``sky_picture`` is loaded before the strip of cloud frames replaces ``load_image``.
_SKY_AND_CLOUDS = """
local s = app.activeSprite
local strip = load_image()
local sky = s:newLayer()
sky.name = NAME
sky.stackIndex = 1
local clouds = s:newLayer()
clouds.name = CLOUDS
clouds.stackIndex = 2
for n = 1, #s.frames do
  s:newCel(sky, n, sky_picture, Point(0, 0))
  s:newCel(clouds, n, Image(strip, Rectangle((n - 1) * W, 0, W, H)), Point(0, 0))
end
return J({ layer = sky.name, clouds = clouds.name, frames = #s.frames })
"""


def _info(file: str | None) -> dict:
    return run(_INFO, file=file)


def _grab(
    names: list[str] | None, bottom: int | None, only: int | None, file: str | None
) -> list[Raster]:
    opts = lua_locals(
        NAMES="\n".join(names) if names else None,
        BOTTOM=bottom,
        ONLY=only,
        MAX_PIXELS=16_000_000,
    )
    res = run(opts + _LOOK_HELPERS + _GRAB, file=file)
    if not isinstance(res, dict) or not res.get("frames"):
        raise ToolError("no pictures came back from Aseprite")
    return [_raster(res["width"], res["height"], f) for f in res["frames"]]


def _write(
    pictures: list[Raster],
    frames: list[int],
    name: str,
    label: str,
    file: str | None,
    *,
    place: str = "top",
    names: list[str] | None = None,
    left: int = 0,
    top: int = 0,
    add: bool = False,
    low: bool = False,
) -> dict:
    """Put ``pictures`` on a new layer: one for each of ``frames``, or a single one
    shown on all of them. ``low`` puts it at the bottom when there is no layer in
    ``names`` to go above."""
    w, h = pictures[0].width, pictures[0].height
    if w * h * len(pictures) > _MAX_PIXELS:
        raise ToolError(
            f"that is {w * h * len(pictures):,} pixels to send, over the {_MAX_PIXELS:,} limit; "
            "use fewer frames or a smaller area"
        )
    body = pixels_loader(_strip(pictures)) + lua_locals(
        NAME=name,
        PLACE=place,
        NAMES="\n".join(names or []),
        FRAMES=",".join(str(f) for f in frames),
        COLUMNS=len(pictures),
        W=w,
        H=h,
        LEFT=left,
        TOP=top,
        ADD=add,
        LOW=low,
    )
    # Only a new layer is written, so no existing pixels can be lost.
    return run(body + _NEW_LAYER, mutates=True, undo_label=label, file=file, capped=False)


def _point(value: list[float] | None, what: str) -> tuple[float, float] | None:
    if value is None:
        return None
    if len(value) != 2:
        raise ToolError(f"{what} is [x, y]")
    return float(value[0]), float(value[1])


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Paint a sky"))
    def paint_sky(
        time: str = "sunset",
        horizon: int | None = None,
        sun: list[float] | None = None,
        clouds: float = 0.5,
        stars: float | None = None,
        drift: int = 0,
        layer: str = "Sky",
        seed: int = 1,
        file: str | None = None,
    ) -> dict:
        """Paint a sky behind the art: ``dawn``, ``day``, ``sunset``, or ``night``,
        shaded in dithered bands from the top down to row ``horizon`` (the bottom edge
        by default). ``sun`` is ``[x, y]`` for the sun or moon: the sky glows round it
        and the clouds are lit from its side. ``clouds`` is how much they cover (0-1, 0
        for none) and ``stars`` how many show (0-1; each time has its own default).
        ``seed`` changes the cloud shapes. ``drift`` is how many pixels the clouds
        travel over the sprite's frames (negative for leftward; try 1 per frame): they
        then go on their own "Clouds" layer and loop seamlessly. The sky goes on a new
        layer named ``layer`` at the bottom of the stack, on every frame. Follow with
        ``paint_mountains`` and ``reflect_in_water`` for a lake. One undo step.
        Headless: pass ``file``."""
        if time not in SKIES:
            raise ToolError(f"time must be one of: {', '.join(SKIES)}")
        if not 0 <= clouds <= 1 or (stars is not None and not 0 <= stars <= 1):
            raise ToolError("clouds and stars must be 0..1")
        info = _info(file)
        if horizon is not None and not 1 <= horizon < info["height"]:
            raise ToolError(f"horizon must be 1..{info['height'] - 1}")
        w, h, count = info["width"], info["height"], info["frames"]
        where = _point(sun, "sun")
        line = horizon or h - 1
        if not drift or count < 2 or clouds <= 0:
            picture = sky(w, h, time, horizon, where, clouds, stars, seed)
            frames = list(range(1, count + 1))
            made = _write([picture], frames, layer, f"Paint sky: {time}", file, place="bottom")
            return {**made, "time": time, "horizon": line}
        if abs(drift) > w:
            raise ToolError(f"drift must be within {w} pixels either way")
        if w * (line + 1) * count > _MAX_PIXELS:
            raise ToolError("too many pixels for drifting clouds; use fewer frames or drift=0")
        still = sky(w, h, time, horizon, where, 0, stars, seed)
        moving = cloud_frames(w, line, count, drift, time, where, clouds, seed)
        body = (
            pixels_loader(still)
            + "local sky_picture = load_image()\n"
            + pixels_loader(_strip(moving))
            + lua_locals(NAME=layer, CLOUDS="Clouds", W=w, H=line + 1)
            + _SKY_AND_CLOUDS
        )
        made = run(body, mutates=True, undo_label=f"Paint sky: {time}", file=file, capped=False)
        return {**made, "time": time, "horizon": line, "drift": drift}

    @mcp.tool(annotations=ToolAnnotations(title="Paint mountains"))
    def paint_mountains(
        horizon: int,
        time: str = "sunset",
        sun: list[float] | None = None,
        size: float = 0.5,
        ranges: int = 3,
        snow: bool = True,
        trees: bool = True,
        above: str = "Sky",
        layer: str = "Mountains",
        seed: int = 1,
        file: str | None = None,
    ) -> dict:
        """Paint mountain ranges standing on row ``horizon``: up to three ``ranges``,
        the far one palest and hazy at its foot, the near one dark. ``time`` is
        ``dawn``, ``day``, ``sunset``, or ``night``, matching ``paint_sky``. The
        tallest peak reaches ``size`` (0-1) of the way up from the horizon. With
        ``sun`` at ``[x, y]``, faces toward it are lit and the ranges dip there so it
        shows between them; without it the light comes from the right. ``snow`` caps
        the far range and ``trees`` puts a treeline on the nearest. ``seed`` changes
        the shapes. They go on a new layer named ``layer`` just above the layer named
        ``above`` (the sky), or at the bottom if there is none. Follow with
        ``reflect_in_water``. One undo step. Headless: pass ``file``."""
        if time not in SKIES:
            raise ToolError(f"time must be one of: {', '.join(SKIES)}")
        if not 0 < size <= 1 or ranges not in (1, 2, 3):
            raise ToolError("size must be above 0 and at most 1, and ranges 1, 2, or 3")
        info = _info(file)
        if not 4 <= horizon < info["height"]:
            raise ToolError(f"horizon must be 4..{info['height'] - 1}")
        picture = mountains(
            info["width"], info["height"], horizon, time, _point(sun, "sun"), size, ranges,
            snow, trees, seed,
        )  # fmt: skip
        box = bounds([picture])
        box = (0, box[1], info["width"] - 1, box[3])
        made = _write(
            [cropped(picture, box)],
            list(range(1, info["frames"] + 1)),
            layer,
            f"Paint mountains: {time}",
            file,
            place="above",
            names=[above],
            top=box[1],
            low=True,
        )
        return {**made, "time": time, "horizon": horizon, "peak_row": box[1]}

    @mcp.tool(annotations=ToolAnnotations(title="Add a fire"))
    def add_fire(
        x: int,
        y: int,
        height: int = 30,
        wind: float = 0.0,
        logs: bool = True,
        palette: str = "fire",
        layer: str = "Fire",
        seed: int = 1,
        file: str | None = None,
    ) -> dict:
        """Light a fire with the middle of its base at ``x``, ``y``: flames ``height``
        pixels tall that lick and sway, and embers that rise above them and lean with
        ``wind`` (pixels; negative blows left). It loops seamlessly over the sprite's
        frames, so give it 8 or more; with one frame it is a still. ``logs`` lays
        crossed logs and a ring of stones, for a campfire; leave them off for a torch
        or a brazier. ``palette`` is ``fire``, ``blue``, or ``green``. It goes on a new
        layer named ``layer`` on top. Follow with ``add_glow`` at the same place to
        light what is round it. One undo step. Headless: pass ``file``."""
        if not 6 <= height <= 200:
            raise ToolError("height must be 6..200")
        if palette not in FLAMES:
            raise ToolError(f"palette must be one of: {', '.join(FLAMES)}")
        info = _info(file)
        count = info["frames"]
        pictures, (cx, by) = fire_frames(height, count, wind, logs, palette, seed)
        box = bounds(pictures)
        made = _write(
            [cropped(p, box) for p in pictures],
            list(range(1, count + 1)),
            layer,
            "Add fire",
            file,
            left=x - cx + box[0],
            top=y - by + box[1],
        )
        hint = {"x": x, "y": y - height // 4, "radius": height * 3}
        return {**made, "palette": palette, "glow_hint": hint}

    @mcp.tool(annotations=ToolAnnotations(title="Reflect the scene in water"))
    def reflect_in_water(
        horizon: int,
        layers: list[str] | None = None,
        ripple: float = 1.0,
        depth: float = 0.5,
        tint: str = "#0c1030",
        sun_x: float | None = None,
        layer: str = "Water",
        file: str | None = None,
    ) -> dict:
        """Fill everything below row ``horizon`` with water that mirrors what is above
        it. The reflection ripples more the nearer it comes (``ripple``, 0 for a still
        mirror) and sinks into ``tint`` with ``depth`` (0-1). With more than one frame
        the ripples move as a seamless loop over all of them, and anything animated
        above is reflected frame by frame. ``sun_x`` lays a broken path of light down
        the water under the sun. ``layers`` are the top-level layers to reflect (the
        sky, hills, a castle); the water goes just above them, so a foreground kept
        on higher layers stays in front and out of the reflection. By default
        everything visible is reflected and the water goes on top. It is a new layer
        named ``layer``. One undo step. Headless: pass ``file``."""
        if not 0 <= depth <= 1 or not 0 <= ripple <= 4:
            raise ToolError("depth must be 0..1 and ripple 0..4")
        info = _info(file)
        rows = info["height"] - horizon - 1
        if horizon < 1 or rows < 1:
            raise ToolError(f"horizon must be 1..{info['height'] - 2}")
        above = _grab(layers, horizon, None, file)
        colour = parse_color(tint)[:3]
        count = len(above)
        water = [
            reflection(a, rows, n, count, ripple, colour, depth, sun_x) for n, a in enumerate(above)
        ]
        made = _write(
            water,
            list(range(1, count + 1)),
            layer,
            "Reflect in water",
            file,
            place="above" if layers else "top",
            names=layers,
            top=horizon + 1,
        )
        return {**made, "horizon": horizon, "rows": rows}

    @mcp.tool(annotations=ToolAnnotations(title="Add a glow of light"))
    def add_glow(
        x: float,
        y: float,
        radius: float,
        color: str = "#ff8c3c",
        strength: float = 0.6,
        flicker: float = 0.0,
        on_layers: list[str] | None = None,
        air: float = 0.15,
        layer: str = "Glow",
        file: str | None = None,
    ) -> dict:
        """Light the scene from a fire, lantern, or window at ``x``, ``y``: a pool of
        ``color`` that fades out by ``radius`` in dithered steps, on a new layer that
        adds its light to what is under it. ``strength`` is 0-1. ``flicker`` (0-1)
        makes the pool breathe as a seamless loop over every frame. ``on_layers`` are
        the top-level layers the light lands on (the ground, a figure); open air round
        them takes only ``air`` of it, so the sky behind a campfire stays dark. By
        default it lights everything. The layer is named ``layer`` and goes on top. One
        undo step. Headless: pass ``file``."""
        if radius < 2 or radius > 4096:
            raise ToolError("radius must be 2..4096")
        if not 0 < strength <= 1 or not 0 <= flicker <= 1 or not 0 <= air <= 1:
            raise ToolError("strength must be above 0 and at most 1; flicker and air 0..1")
        info = _info(file)
        w, h = info["width"], info["height"]
        colour = parse_color(color)[:3]
        moving = flicker > 0 and info["frames"] > 1
        numbers = list(range(1, info["frames"] + 1))
        if on_layers:
            masks = _grab(on_layers, None, None if moving else info["frame"], file)
        else:
            masks = [None] * (len(numbers) if moving else 1)
        pools = [
            glow(w, h, (x, y), radius, colour, strength, m, air, n / len(masks), flicker)
            for n, m in enumerate(masks)
        ]
        box = bounds(pools)
        if box is None:
            raise ToolError("the glow is off the canvas")
        pools = [cropped(p, box) for p in pools]
        made = _write(pools, numbers, layer, "Add glow", file, left=box[0], top=box[1], add=True)
        return {**made, "blend": "addition", "bounds": list(box)}

    @mcp.tool(annotations=ToolAnnotations(title="Add rim light"))
    def add_rim_light(
        layer: str,
        light: list[float],
        color: str = "#ffb070",
        width: int = 1,
        radius: float | None = None,
        all_frames: bool = True,
        file: str | None = None,
    ) -> dict:
        """Pick out the edge of ``layer`` that faces a light: a sunset behind a figure,
        a fire beside a tree. ``light`` is where the light is, ``[x, y]``, and may be
        off the canvas for a far-off sun. Edge pixels facing it turn ``color``;
        ``width`` 2 adds a dithered second row mixed with the art's own colour. With
        ``radius`` the light fades out that far from its source, for a fire. The rim
        goes on a new layer named like "Knight (rim)" just above ``layer``, so the art
        is untouched and the light can be hidden or recoloured. Runs on every frame,
        or the active one with ``all_frames`` false. One undo step. Headless: pass
        ``file``."""
        if width not in (1, 2):
            raise ToolError("width must be 1 or 2")
        if radius is not None and radius <= 0:
            raise ToolError("radius must be above 0")
        info = _info(file)
        source = _point(light, "light")
        colour = parse_color(color)[:3]
        only = None if all_frames else info["frame"]
        shapes = _grab([layer], None, only, file)
        rims = [rim_light(s, source, colour, width, radius) for s in shapes]
        box = bounds(rims)
        if box is None:
            raise ToolError(f"no edge of '{layer}' faces that light")
        rims = [cropped(r, box) for r in rims]
        numbers = list(range(1, info["frames"] + 1)) if all_frames else [info["frame"]]
        made = _write(
            rims,
            numbers,
            f"{layer} (rim)",
            "Add rim light",
            file,
            place="above",
            names=[layer],
            left=box[0],
            top=box[1],
        )
        return {**made, "source": layer, "bounds": list(box)}
