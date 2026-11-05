"""Building and animating scenes.

- ``ambient_motion`` — loops a layer with wind, water shimmer, and a light glint,
  and adds a particle layer (motes, snow, rain, embers).
- ``split_into_layers`` — separates a layer into named parts from seed points, at
  the parts' real edges, so each can be edited or animated alone.
- ``extend_scene`` — grows the canvas and fills the new space by continuing the
  picture's own texture.
- ``clean_pixel_art`` — merges noise specks and firms up edges with the art's own
  colours, so a pixelated picture reads as drawn.

The layer's pixels are read like ``look`` reads them, the image work happens in
``scene.py``, and the results travel back inside the script, so nothing touches
the disk and every tool is one undo step.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ..raster import Raster
from ..scene import ambient_frames, cleaned, extended, part, particle_frames, split_regions
from ._common import ToolError, parse_color, run
from .look import _LOOK, _LOOK_HELPERS, _take, pixels_loader

_MAX_FRAMES = 64

_ACTIVE_LAYER = """
local s = app.activeSprite
if not s then error("no active sprite (headless: pass file=)") end
local l = app.activeLayer
if not l then error("no active layer; pass layer=") end
return J({ name = l.name, group = l.isGroup, frame = app.activeFrame and app.activeFrame.frameNumber or 1,
  rgb = s.colorMode == ColorMode.RGB })
"""

_FIND = """
local s = app.activeSprite
if s.colorMode ~= ColorMode.RGB then
  error("this tool works on RGB sprites; convert with set_color_mode first")
end
local layer = findLayer(s, LAYER)
if not layer then error("no layer named '" .. LAYER .. "'") end
if layer.isGroup or layer.isTilemap then error("'" .. LAYER .. "' isn't an image layer") end
local strip = load_image()
"""

_AMBIENT = """
while #s.frames < COUNT do s:newFrame(#s.frames) end
local particles = nil
if PARTICLES_NAME then
  particles = s:newLayer()
  particles.name = PARTICLES_NAME
end
for i = 1, COUNT do
  s:newCel(layer, i, Image(strip, Rectangle((i - 1) * W, 0, W, H)), Point(0, 0))
  if particles then
    s:newCel(particles, i, Image(strip, Rectangle((i - 1) * W, H, W, H)), Point(0, 0))
  end
  s.frames[i].duration = DURATION / 1000
end
local tagged = false
for _, t in ipairs(s.tags) do if t.name == TAG then tagged = true end end
if not tagged then
  local t = s:newTag(1, COUNT)
  t.name = TAG
end
return J({ layer = layer.name, frames = COUNT, duration_ms = DURATION, tag = TAG,
  particles = PARTICLES_NAME })
"""

_SPLIT = """
local made = {}
local i = 0
for name in NAMES:gmatch("[^\\n]+") do
  local l = s:newLayer()
  l.name = name
  l.parent = layer.parent
  l.stackIndex = layer.stackIndex + 1
  s:newCel(l, FRAME, Image(strip, Rectangle(i * W, 0, W, H)), Point(0, 0))
  made[#made + 1] = name
  i = i + 1
end
if HIDE then layer.isVisible = false end
return J({ source = layer.name, layers = made, frame = FRAME, source_hidden = HIDE })
"""

_EXTEND = """
app.command.CanvasSize{ ui = false, left = LEFT, top = TOP, right = RIGHT, bottom = BOTTOM,
  trimOutside = false }
-- The other frames keep their own pixels and share the new margins, so an animated
-- layer keeps moving where it did and the extension holds still around it.
local others = {}
for _, cel in ipairs(layer.cels) do
  if cel.frameNumber ~= FRAME then
    local img = Image(strip)
    img:drawImage(cel.image, cel.position)
    others[#others + 1] = { frame = cel.frameNumber, image = img }
  end
end
s:newCel(layer, FRAME, strip, Point(0, 0))
for _, o in ipairs(others) do s:newCel(layer, o.frame, o.image, Point(0, 0)) end
return J({ layer = layer.name, frame = FRAME, frames = 1 + #others, width = s.width,
  height = s.height })
"""

_CLEAN = """
local done, i = {}, 0
for n in FRAMES:gmatch("%d+") do
  n = tonumber(n)
  s:newCel(layer, n, Image(strip, Rectangle(i * W, 0, W, H)), Point(0, 0))
  done[#done + 1] = n
  i = i + 1
end
return J({ layer = layer.name, frames = done })
"""


def _target(layer: str | None, file: str | None) -> tuple[str, int]:
    """The layer to work on (the active one by default) and the active frame."""
    info = run(_ACTIVE_LAYER, file=file)
    if layer is None:
        if info["group"]:
            raise ToolError(f"the active layer '{info['name']}' is a group; pass layer=")
        layer = info["name"]
    if not info["rgb"]:
        raise ToolError("this tool works on RGB sprites; convert with set_color_mode first")
    return layer, info["frame"]


def _read(layer: str, frame: int | None, file: str | None) -> tuple[Raster, int]:
    """One layer of one frame, canvas-sized, as pixels."""
    opts = lua_locals(
        FRAME=frame,
        LAYER=layer,
        SELECTION=False,
        RX=None,
        RY=None,
        RW=None,
        RH=None,
        SCALE=1,
        MAX_SIZE=1 << 20,
    )
    res = run(opts + _LOOK_HELPERS + _LOOK, file=file)
    return _take(res), res["frame"]


def _strip(rasters: list[Raster], rows: int = 1) -> Raster:
    """Same-sized rasters side by side; ``rows`` > 1 stacks equal runs of them."""
    w, h = rasters[0].width, rasters[0].height
    per_row = len(rasters) // rows
    out = bytearray(per_row * w * rows * h * 4)
    stride = per_row * w * 4
    for n, r in enumerate(rasters):
        left, top = (n % per_row) * w, (n // per_row) * h
        for y in range(h):
            start = (top + y) * stride + left * 4
            out[start : start + w * 4] = r.rgba[y * w * 4 : (y + 1) * w * 4]
    return Raster(per_row * w, rows * h, bytes(out))


def _colour(c: str) -> tuple[int, int, int]:
    return parse_color(c)[:3]


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Animate a scene with ambient motion"))
    def ambient_motion(
        layer: str | None = None,
        frames: int = 16,
        duration_ms: int = 90,
        wind: float = 0.0,
        wavelength: int = 48,
        shimmer: float = 0.0,
        glint: float = 0.0,
        glint_color: str = "#ffecbe",
        particles: str | None = None,
        particle_count: int = 24,
        particle_colors: list[str] | None = None,
        from_frame: int = 1,
        tag: str = "loop",
        seed: int = 1,
        file: str | None = None,
    ) -> dict:
        """Bring a still scene to life as a seamless loop. ``layer`` (the active layer
        by default) is animated from ``from_frame`` over
        ``frames`` frames of ``duration_ms``: ``wind`` (pixels, try 1) sends gusts
        rolling left to right, one per ``wavelength`` pixels; ``shimmer`` (pixels)
        wobbles rows like water; ``glint`` (0-1) sweeps light across the bright pixels
        once a loop. ``particles`` adds a layer of ``motes``, ``snow``, ``rain``, or
        ``embers``. Animate each part on its own layer (see ``split_into_layers``) so
        armour can glint while grass blows. Frames are added as needed, copying the
        others, and tagged ``tag``. Check with ``check_loop``. One undo step.
        Headless: pass ``file``."""
        if not 2 <= frames <= _MAX_FRAMES:
            raise ToolError(f"frames must be 2..{_MAX_FRAMES}")
        if not 10 <= duration_ms <= 5000:
            raise ToolError("duration_ms must be 10..5000")
        if not 0 <= glint <= 1:
            raise ToolError("glint must be 0..1")
        if wavelength < 2:
            raise ToolError("wavelength must be at least 2")
        if not (wind or shimmer or glint or particles):
            raise ToolError("nothing to animate: set wind, shimmer, glint, or particles")
        layer, _ = _target(layer, file)
        src, frame = _read(layer, from_frame, file)
        looped = ambient_frames(
            src,
            frames,
            wind=wind,
            wavelength=wavelength,
            shimmer=shimmer,
            glint=glint,
            glint_color=_colour(glint_color),
        )
        name = None
        if particles:
            try:
                specks = particle_frames(
                    src.width,
                    src.height,
                    frames,
                    particles,
                    max(1, min(500, particle_count)),
                    [_colour(c) for c in particle_colors] if particle_colors else None,
                    seed,
                )
            except ValueError as e:
                raise ToolError(str(e)) from None
            looped += specks
            name = particles.capitalize()
        body = (
            pixels_loader(_strip(looped, rows=2 if particles else 1))
            + lua_locals(
                LAYER=layer,
                COUNT=frames,
                W=src.width,
                H=src.height,
                DURATION=int(duration_ms),
                TAG=tag,
                PARTICLES_NAME=name,
            )
            + _FIND
            + _AMBIENT
        )
        made = run(body, mutates=True, undo_label="Ambient motion", file=file)
        return {**made, "source_frame": frame}

    @mcp.tool(annotations=ToolAnnotations(title="Split a layer into parts"))
    def split_into_layers(
        seeds: list[dict],
        layer: str | None = None,
        frame: int | None = None,
        hide_source: bool = True,
        file: str | None = None,
    ) -> dict:
        """Separate a picture into parts on their own layers, like armour and meadow,
        so each can be edited or animated alone. ``seeds`` are points on each part:
        ``[{"name": "armour", "x": 90, "y": 40}, {"name": "meadow", "x": 5, "y": 5}]``.
        The first part named ends up on top. Each part grows from its seeds and stops where colours change sharply, so
        put a seed on every distinct area of a part (a part may have many seeds).
        If a part leaks into another, add seeds where it leaked and run it again.
        ``layer`` defaults to the active one, which is hidden afterwards unless
        ``hide_source`` is false. Check the result with ``look`` and ``layer=``.
        One undo step. Headless: pass ``file``."""
        if not seeds:
            raise ToolError("pass at least one seed")
        names: list[str] = []
        points = []
        for s in seeds:
            try:
                name, x, y = str(s["name"]).strip(), int(s["x"]), int(s["y"])
            except (KeyError, TypeError, ValueError):
                raise ToolError('each seed needs "name", "x", and "y"') from None
            if not name or "\n" in name:
                raise ToolError("seed names must be one line and not empty")
            if name not in names:
                names.append(name)
            points.append((x, y, names.index(name)))
        if len(names) > 16:
            raise ToolError("at most 16 parts")
        layer, active = _target(layer, file)
        src, frame = _read(layer, frame or active, file)
        try:
            labels = split_regions(src, points)
        except ValueError as e:
            raise ToolError(str(e)) from None
        parts = [part(src, labels, i) for i in range(len(names))]
        body = (
            pixels_loader(_strip(parts))
            + lua_locals(
                LAYER=layer,
                W=src.width,
                H=src.height,
                FRAME=frame,
                NAMES="\n".join(names),
                HIDE=hide_source,
            )
            + _FIND
            + _SPLIT
        )
        made = run(body, mutates=True, undo_label="Split into layers", file=file)
        sizes = {n: labels.count(i) for i, n in enumerate(names)}
        return {**made, "pixels": sizes}

    @mcp.tool(annotations=ToolAnnotations(title="Extend the scene"))
    def extend_scene(
        left: int = 0,
        right: int = 0,
        top: int = 0,
        bottom: int = 0,
        layer: str | None = None,
        sample_x: int | None = None,
        sample_y: int | None = None,
        sample_width: int | None = None,
        sample_height: int | None = None,
        patch: int = 6,
        frame: int | None = None,
        seed: int = 1,
        file: str | None = None,
    ) -> dict:
        """Grow the canvas by ``left``/``right``/``top``/``bottom`` pixels and fill the
        new space on ``layer`` (the active one) by continuing its own texture, like
        turning a portrait scene into a wide banner. Patches of ``patch`` pixels are
        copied from the ``sample_*`` area (all of the layer by default) and matched
        to what is already beside them, so no new colours appear. Pick a sample of
        pure background, like open meadow, so the subject isn't copied, and big
        enough not to repeat. The margins come from ``frame`` and are shared by the
        layer's other frames. Other layers just get a bigger canvas. One undo step. Headless: pass ``file``."""
        if min(left, right, top, bottom) < 0:
            raise ToolError("the margins must be 0 or more; use crop_sprite to shrink")
        if not any((left, right, top, bottom)):
            raise ToolError("pass at least one margin")
        if not 3 <= patch <= 64:
            raise ToolError("patch must be 3..64")
        given = [v is not None for v in (sample_x, sample_y, sample_width, sample_height)]
        if any(given) and not all(given):
            raise ToolError("pass all of sample_x, sample_y, sample_width, sample_height, or none")
        layer, active = _target(layer, file)
        src, frame = _read(layer, frame or active, file)
        sample = (sample_x, sample_y, sample_width, sample_height) if all(given) else None
        if (src.width + left + right) * (src.height + top + bottom) > 4_000_000:
            raise ToolError("the extended canvas would be over 4 million pixels")
        try:
            grown = extended(src, left, right, top, bottom, sample, patch, seed)
        except ValueError as e:
            raise ToolError(str(e)) from None
        body = (
            pixels_loader(grown)
            + lua_locals(
                LAYER=layer,
                LEFT=int(left),
                RIGHT=int(right),
                TOP=int(top),
                BOTTOM=int(bottom),
                FRAME=frame,
            )
            + _FIND
            + _EXTEND
        )
        # Growing the canvas and filling new space can't lose a pixel.
        return run(body, mutates=True, undo_label="Extend scene", file=file, capped=False)

    @mcp.tool(annotations=ToolAnnotations(title="Clean up pixel art"))
    def clean_pixel_art(
        layer: str | None = None,
        min_region: int = 3,
        tolerance: float = 0.12,
        firm_edges: bool = True,
        all_frames: bool = False,
        frame: int | None = None,
        file: str | None = None,
    ) -> dict:
        """Make pixelated or noisy art read as drawn: every patch of one colour
        smaller than ``min_region`` pixels merges into the colour around it, if that
        colour is close (``tolerance``, 0-1; standout specks like flowers stay), and
        ``firm_edges`` darkens the shadow side of strong edges with the art's own
        darker shade. No new colours. ``layer`` defaults to the active one; one
        frame, or ``all_frames``. One undo step. Headless: pass ``file``."""
        if not 2 <= min_region <= 64:
            raise ToolError("min_region must be 2..64")
        if not 0 <= tolerance <= 1:
            raise ToolError("tolerance must be 0..1")
        layer, active = _target(layer, file)
        count = run("return #app.activeSprite.frames", file=file) if all_frames else None
        numbers = list(range(1, int(count) + 1)) if all_frames else [frame or active]
        if len(numbers) > _MAX_FRAMES:
            raise ToolError(f"at most {_MAX_FRAMES} frames at once")
        results, merged, firmed = [], 0, 0
        for n in numbers:
            src, _ = _read(layer, n, file)
            out, info = cleaned(src, min_region, firm_edges, tolerance)
            results.append(out)
            merged += info["merged_pixels"]
            firmed += info["firmed_pixels"]
        body = (
            pixels_loader(_strip(results))
            + lua_locals(
                LAYER=layer,
                W=results[0].width,
                H=results[0].height,
                FRAMES=",".join(str(n) for n in numbers),
            )
            + _FIND
            + _CLEAN
        )
        made = run(body, mutates=True, undo_label="Clean pixel art", file=file)
        return {**made, "merged_pixels": merged, "firmed_pixels": firmed}
