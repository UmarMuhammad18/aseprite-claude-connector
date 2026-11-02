"""Canvas vision — tools that return pictures to the model, not files on disk.

- ``look`` — one frame as an image: all layers or one, optionally a crop or the
  selection, scaled up with sharp pixels so small sprites are readable.
- ``look_animation`` — a tag or frame range laid out as a strip or grid.
- ``look_onion`` — the onion-skin composite as an image.
- ``previewable`` — adds a ``preview`` flag to a drawing tool: a before/after
  picture plus the changed-pixel count and bbox, so a mistake is visible at once.

Lua returns raw pixels as base64 over the normal result channel and ``raster.py``
builds the picture. Never write a temp file from Lua here: in the live editor that
raises Aseprite's script-security prompt, which blocks until someone answers it.
Everything here is read-only: no transactions, no undo steps, no saved files.
Pictures use up conversation space, so the default sizes are deliberately small.
"""

from __future__ import annotations

import base64
import binascii
import functools
import inspect
import json

from mcp.server.fastmcp import Image
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from ..backends import Backend
from ..lua import lua_locals
from ..raster import Raster, diff, encode_png, fit_factor, over_background, resized, tiled
from ._common import ToolError, parse_color, run
from .animate import _ONION_RENDER

_MAX_FRAMES = 64
_MAX_PREVIEW_PIXELS = 4_000_000
_MAX_GRAB_PIXELS = 16_000_000

_LOOK_HELPERS = """
local pc = app.pixelColor
local s = app.activeSprite
if not s then error("no active sprite (headless: pass file=)") end
local B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local B64_PAIRS = {}
for i = 0, 4095 do
  local hi, lo = (i >> 6) + 1, (i & 63) + 1
  B64_PAIRS[i] = B64:sub(hi, hi) .. B64:sub(lo, lo)
end
-- Base64 of an RGB image's bytes, safe to carry over the text result channel.
local function pack(img)
  local raw = img.bytes
  local parts, n = {}, 0
  for i = 1, #raw, 3 do
    local a, b, c = raw:byte(i, i + 2)
    local v = (a << 16) | ((b or 0) << 8) | (c or 0)
    n = n + 1
    parts[n] = B64_PAIRS[v >> 12] .. B64_PAIRS[v & 4095]
  end
  local out = table.concat(parts)
  local rem = #raw % 3
  if rem > 0 then out = out:sub(1, #out - (3 - rem)) .. string.rep("=", 3 - rem) end
  return out
end
-- Only canvases too big for the picture shrink here; zooming up happens in Python.
local function shrunk(img, k)
  if k >= 1 then return img end
  local out = Image(img)
  out:resize{ width = math.max(1, math.floor(img.width * k + 0.5)),
              height = math.max(1, math.floor(img.height * k + 0.5)), method = "nearest" }
  return out
end
local function toRGB(image)
  if image.colorMode == ColorMode.RGB then return image end
  local out = Image(image.width, image.height, ColorMode.RGB)
  local pal = s.palettes[1]
  local mask = s.transparentColor
  for it in image:pixels() do
    local v = it()
    if image.colorMode == ColorMode.GRAY then
      local g = pc.grayaV(v)
      out:drawPixel(it.x, it.y, pc.rgba(g, g, g, pc.grayaA(v)))
    elseif v ~= mask and v < #pal then
      local c = pal:getColor(v)
      out:drawPixel(it.x, it.y, pc.rgba(c.red, c.green, c.blue, c.alpha))
    end
  end
  return out
end
local function drawLayer(out, layer, frameNumber)
  if layer.isGroup then
    for _, child in ipairs(layer.layers) do
      if child.isVisible then drawLayer(out, child, frameNumber) end
    end
    return
  end
  if layer.isTilemap then error("look can't isolate a tilemap layer; omit layer") end
  local cel = layer:cel(frameNumber)
  if cel then
    local op = math.floor(cel.opacity * (layer.opacity or 255) / 255 + 0.5)
    out:drawImage(toRGB(cel.image), cel.position, op, layer.blendMode)
  end
end
-- One composited frame as a canvas-sized RGB image.
local function render(frameNumber, layerName)
  local img = Image(s.width, s.height, ColorMode.RGB)
  if not layerName then img:drawSprite(s, frameNumber); return img end
  local layer = findLayer(s, layerName)
  if not layer then error("no layer named '" .. layerName .. "'") end
  drawLayer(img, layer, frameNumber)
  return img
end
"""

_LOOK = """
local fr = FRAME or (app.activeFrame and app.activeFrame.frameNumber) or 1
if fr < 1 or fr > #s.frames then error("frame " .. fr .. " out of range (1.." .. #s.frames .. ")") end
local rx, ry, rw, rh = 0, 0, s.width, s.height
if SELECTION then
  if s.selection.isEmpty then error("selection is empty") end
  local b = s.selection.bounds
  rx, ry, rw, rh = b.x, b.y, b.width, b.height
elseif RX then
  rx, ry, rw, rh = RX, RY, RW, RH
end
local x2 = math.min(rx + rw, s.width)
local y2 = math.min(ry + rh, s.height)
rx, ry = math.max(rx, 0), math.max(ry, 0)
rw, rh = x2 - rx, y2 - ry
if rw < 1 or rh < 1 then error("region is outside the canvas") end
local img = render(fr, LAYER)
if rw ~= s.width or rh ~= s.height then img = Image(img, Rectangle(rx, ry, rw, rh)) end
if not SCALE then img = shrunk(img, MAX_SIZE / math.max(rw, rh)) end
return J({ rgba = pack(img), width = img.width, height = img.height, frame = fr,
  frames = #s.frames, layer = LAYER or "all visible",
  region = { x = rx, y = ry, width = rw, height = rh } })
"""

_LOOK_ANIMATION = """
local first, last = FROM or 1, TO or #s.frames
if TAG then
  local hit = nil
  for _, t in ipairs(s.tags) do if t.name == TAG then hit = t; break end end
  if not hit then error("no tag named '" .. TAG .. "'") end
  first, last = hit.fromFrame.frameNumber, hit.toFrame.frameNumber
end
if first < 1 or last > #s.frames or first > last then
  error("frame range " .. first .. ".." .. last .. " invalid (1.." .. #s.frames .. ")")
end
local n = last - first + 1
if n > MAX_FRAMES then
  error(n .. " frames is over the " .. MAX_FRAMES .. " cap; pass a tag or a smaller range")
end
local cols = math.min(COLUMNS or (n <= 6 and n or math.ceil(math.sqrt(n))), n)
local rows = math.ceil(n / cols)
local k = SCALE and 1 or MAX_SIZE / math.max(cols * s.width, rows * s.height)
local packed, durations, w, h = {}, {}, 0, 0
for i = 1, n do
  local img = shrunk(render(first + i - 1, LAYER), k)
  w, h = img.width, img.height
  packed[i] = pack(img)
  durations[i] = math.floor(s.frames[first + i - 1].duration * 1000 + 0.5)
end
return J({ frames = packed, durations = durations, width = w, height = h,
  first_frame = first, last_frame = last, columns = cols, tag = TAG or "" })
"""

_GRAB = """
local first, last = FROM or 1, TO or #s.frames
if TAG then
  local hit = nil
  for _, t in ipairs(s.tags) do if t.name == TAG then hit = t; break end end
  if not hit then error("no tag named '" .. TAG .. "'") end
  first, last = hit.fromFrame.frameNumber, hit.toFrame.frameNumber
end
if s.width * s.height * (last - first + 1) > MAX_PIXELS then
  error("too many pixels to read at once; pass a tag, or use a smaller sprite")
end
local packed, durations = {}, {}
for n = first, last do
  packed[#packed + 1] = pack(render(n, nil))
  durations[#durations + 1] = math.floor(s.frames[n].duration * 1000 + 0.5)
end
local tags = {}
for i, t in ipairs(s.tags) do
  tags[i] = { name = t.name, from = t.fromFrame.frameNumber, to = t.toFrame.frameNumber }
end
local result = J({ frames = packed, durations = durations, width = s.width, height = s.height,
  name = s.filename, tags = tags })
if __previous then app.activeSprite = __previous end
return result
"""

_PICK = """
local __previous = nil
if PICK then
  __previous = app.activeSprite
  local found = false
  for _, sp in ipairs(app.sprites) do
    if sp.filename == PICK or sp.filename:match("[^\\\\/]+$") == PICK then
      app.activeSprite = sp
      found = true
      break
    end
  end
  if not found then error("no open sprite named '" .. PICK .. "'") end
end
"""

_LOOK_ONION_TAIL = """
return J({ rgba = pack(out), width = out.width, height = out.height, frame = FRAME,
  ghosts_prev = gp, ghosts_next = gn, note = "red = earlier frames, blue = later frames" })
"""

_SNAPSHOT = """
local fr = FRAME or (app.activeFrame and app.activeFrame.frameNumber) or 1
if s.width * s.height > MAX_PIXELS then error("sprite too large to preview; use look") end
local img = render(fr, nil)
return J({ rgba = pack(img), width = img.width, height = img.height, frame = fr })
"""


def _options(scale: int | None, max_size: int, background: str):
    """Validate the shared picture options; returns the parsed background."""
    if scale is not None and not 1 <= scale <= 32:
        raise ToolError("scale must be 1..32 (or omit it to fit max_size)")
    if not 16 <= max_size <= 2048:
        raise ToolError("max_size must be 16..2048")
    if background in ("checker", "transparent"):
        return background
    return parse_color(background)[:3]


def _raster(width: int, height: int, packed: str) -> Raster:
    try:
        rgba = base64.b64decode(packed, validate=True)
    except binascii.Error as e:
        raise ToolError(f"bad pixel data from Aseprite: {e}") from None
    if len(rgba) != width * height * 4:
        raise ToolError(f"bad pixel data from Aseprite: {len(rgba)} bytes for {width}x{height}")
    return Raster(width, height, rgba)


def _take(res: dict, key: str = "rgba") -> Raster:
    """Pop the pixels out of a Lua result, leaving just its metadata."""
    if not isinstance(res, dict) or key not in res:
        raise ToolError("no picture came back from Aseprite")
    return _raster(res.pop("width"), res.pop("height"), res.pop(key))


def png_content(img: Raster, meta: dict) -> list:
    meta = {**meta, "image_width": img.width, "image_height": img.height}
    return [Image(data=encode_png(img), format="png"), json.dumps(meta)]


def frames_of(
    tag: str | None = None,
    file: str | None = None,
    pick: str | None = None,
    backend: Backend | None = None,
) -> dict:
    """Read frames at full size, for tools that write their own files. ``pick`` reads
    another open sprite by name. Frame numbers in ``tags`` are the sprite's own."""
    opts = lua_locals(TAG=tag, FROM=None, TO=None, PICK=pick, MAX_PIXELS=_MAX_GRAB_PIXELS)
    res = run(opts + _PICK + _LOOK_HELPERS + _GRAB, file=file, backend=backend)
    if not isinstance(res, dict) or not res.get("frames"):
        raise ToolError("no pictures came back from Aseprite")
    w, h = res["width"], res["height"]
    return {
        "frames": [_raster(w, h, f) for f in res["frames"]],
        "durations": res["durations"],
        "tags": res["tags"],
        "name": res["name"],
        "size": {"width": w, "height": h},
    }


def animation_picture(result, first: int, last: int, *, max_size: int, file: str | None) -> list:
    """An edit's result beside a strip of the frames it made. The edit always wins: a
    failed picture is reported alongside it, never in place of it."""
    try:
        return _animation(
            lua_locals(
                SCALE=None,
                MAX_SIZE=int(max_size),
                TAG=None,
                FROM=first,
                TO=last,
                COLUMNS=None,
                LAYER=None,
                MAX_FRAMES=_MAX_FRAMES,
            ),
            None,
            max_size,
            "checker",
            file,
            result,
        )
    except ToolError as e:
        return [json.dumps({"result": result, "preview_error": str(e)})]


def _animation(opts: str, scale, max_size: int, bg, file: str | None, result=None) -> list:
    res = run(opts + _LOOK_HELPERS + _LOOK_ANIMATION, file=file)
    if not isinstance(res, dict) or not res.get("frames"):
        raise ToolError("no pictures came back from Aseprite")
    frames = [_raster(res["width"], res["height"], f) for f in res["frames"]]
    cols = res["columns"]
    rows = -(-len(frames) // cols)
    k = fit_factor(cols * frames[0].width, rows * frames[0].height, scale, max_size)
    sheet = tiled([over_background(resized(f, k), bg) for f in frames], cols)
    first = res["first_frame"]
    cells = [
        {
            "frame": first + i,
            "row": i // cols + 1,
            "column": i % cols + 1,
            "duration_ms": ms,
        }
        for i, ms in enumerate(res["durations"])
    ]
    meta = {
        "first_frame": first,
        "last_frame": res["last_frame"],
        "count": len(frames),
        "tag": res["tag"],
        "columns": cols,
        "rows": rows,
        "scale": k,
        "cells": cells,
    }
    if result is not None:
        meta["result"] = result
    return png_content(sheet, meta)


def _single(res: dict, scale: int | None, max_size: int, background) -> list:
    src = _take(res)
    k = fit_factor(src.width, src.height, scale, max_size)
    return png_content(over_background(resized(src, k), background), {**res, "scale": k})


def _snapshot(file: str | None, frame: int | None = None) -> dict:
    opts = lua_locals(FRAME=frame, MAX_PIXELS=_MAX_PREVIEW_PIXELS)
    return run(opts + _LOOK_HELPERS + _SNAPSHOT, file=file)


def _edit_result(result: dict, *, image: bytes | None = None, **extra) -> CallToolResult:
    """Keep a drawing tool's structured output while adding a picture to its content."""
    content = [TextContent(type="text", text=json.dumps({"result": result, **extra}))]
    if image is not None:
        content.insert(0, Image(data=image, format="png").to_image_content())
    return CallToolResult(content=content, structuredContent={"result": result})


def _with_before_after(fn, args, kwargs) -> CallToolResult:
    """Run a drawing tool between two renders. The edit always wins: a failed
    picture is reported alongside the result, never in place of it."""
    file = kwargs.get("file")
    try:
        first = _snapshot(file)
    except ToolError as e:
        return _edit_result(fn(*args, **kwargs), preview_error=str(e))
    result = fn(*args, **kwargs)
    try:
        frame = first["frame"]
        before, after = _take(first), _take(_snapshot(file, frame))
        if (before.width, before.height) != (after.width, after.height):
            raise ToolError("canvas size changed during the edit")
        k = fit_factor(2 * before.width, before.height, None, 512)
        panels = [over_background(resized(r, k), "checker") for r in (before, after)]
        data = encode_png(tiled(panels, 2))
    except ToolError as e:
        return _edit_result(result, preview_error=str(e))
    meta = {"left": "before", "right": "after", "frame": frame, "scale": k, **diff(before, after)}
    return _edit_result(result, image=data, preview=meta)


def previewable(fn):
    """Add a ``preview`` flag to a drawing tool. Off, the tool is unchanged; on, it
    returns a before/after picture plus changed-pixel count and bbox. The two
    renders are read-only, so the edit is still exactly one undo step."""

    @functools.wraps(fn)
    def wrapper(*args, preview: bool = False, **kwargs):
        if not preview:
            return fn(*args, **kwargs)
        return _with_before_after(fn, args, kwargs)

    sig = inspect.signature(fn)
    flag = inspect.Parameter(
        "preview", inspect.Parameter.KEYWORD_ONLY, default=False, annotation=bool
    )
    wrapper.__signature__ = sig.replace(parameters=[*sig.parameters.values(), flag])
    wrapper.__doc__ = (fn.__doc__ or "") + (
        "\n\n``preview`` true also returns a before/after picture of the canvas with the "
        "changed-pixel count and bbox."
    )
    return wrapper


def register(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(title="Look at the canvas", readOnlyHint=True),
        structured_output=False,
    )
    def look(
        frame: int | None = None,
        layer: str | None = None,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
        selection: bool = False,
        scale: int | None = None,
        max_size: int = 512,
        background: str = "checker",
        file: str | None = None,
    ) -> list:
        """See the canvas: returns a frame as an image, scaled up with sharp pixels.
        Defaults to the active frame with all visible layers. ``layer`` shows one
        layer or group alone (even if hidden). ``x``/``y``/``width``/``height`` crop
        to a region, and ``selection`` crops to the current selection. ``scale`` is
        an integer zoom (1-32); omit it to fit ``max_size``. ``background`` is
        ``checker``, ``transparent``, or a #rrggbb color. Prefer a crop when you only
        need part of the canvas: images use up conversation space. Headless: pass
        ``file``."""
        bg = _options(scale, max_size, background)
        region = (x, y, width, height)
        if any(v is not None for v in region) and any(v is None for v in region):
            raise ToolError("a crop needs all of x, y, width, and height")
        if selection and x is not None:
            raise ToolError("pass either a crop region or selection, not both")
        body = (
            lua_locals(
                SCALE=scale,
                MAX_SIZE=int(max_size),
                FRAME=frame,
                LAYER=layer,
                SELECTION=bool(selection),
                RX=x,
                RY=y,
                RW=width,
                RH=height,
            )
            + _LOOK_HELPERS
            + _LOOK
        )
        return _single(run(body, file=file), scale, max_size, bg)

    @mcp.tool(
        annotations=ToolAnnotations(title="Look at the animation", readOnlyHint=True),
        structured_output=False,
    )
    def look_animation(
        tag: str | None = None,
        from_frame: int | None = None,
        to_frame: int | None = None,
        columns: int | None = None,
        layer: str | None = None,
        scale: int | None = None,
        max_size: int = 768,
        background: str = "checker",
        file: str | None = None,
    ) -> list:
        """See an animation: returns a tag or frame range as one image, frames left
        to right and top to bottom. Defaults to every frame, capped at 64. A range of
        up to 6 frames is a strip and longer ones are a grid, unless ``columns`` is
        set. The result lists each cell's frame and duration. ``layer``, ``scale``,
        ``max_size``, and ``background`` work as in ``look``. Headless: pass
        ``file``."""
        bg = _options(scale, max_size, background)
        if tag is not None and (from_frame is not None or to_frame is not None):
            raise ToolError("pass either tag or a frame range, not both")
        if columns is not None and columns < 1:
            raise ToolError("columns must be >= 1")
        opts = lua_locals(
            SCALE=scale,
            MAX_SIZE=int(max_size),
            TAG=tag,
            FROM=from_frame,
            TO=to_frame,
            COLUMNS=columns,
            LAYER=layer,
            MAX_FRAMES=_MAX_FRAMES,
        )
        return _animation(opts, scale, max_size, bg, file)

    @mcp.tool(
        annotations=ToolAnnotations(title="Look at onion skin", readOnlyHint=True),
        structured_output=False,
    )
    def look_onion(
        frame: int | None = None,
        prev: int = 2,
        next: int = 2,
        opacity: float = 0.35,
        scale: int | None = None,
        max_size: int = 512,
        background: str = "checker",
        file: str | None = None,
    ) -> list:
        """See motion: returns ``frame`` as an image with earlier frames ghosted in
        red and later frames in blue, so the whole arc shows at once. Defaults to the
        active frame. The picture form of ``render_onion_composite``. Headless: pass
        ``file``."""
        bg = _options(scale, max_size, background)
        if not (0.05 <= float(opacity) <= 1.0):
            raise ToolError("opacity must be between 0.05 and 1.0")
        if prev < 0 or next < 0 or prev + next < 1:
            raise ToolError("need at least one ghost frame (prev + next >= 1)")
        body = (
            lua_locals(FRAME=frame, PREV=int(prev), NXT=int(next), OP=float(opacity))
            + _LOOK_HELPERS
            + "FRAME = FRAME or (app.activeFrame and app.activeFrame.frameNumber) or 1\n"
            + _ONION_RENDER
            + _LOOK_ONION_TAIL
        )
        return _single(run(body, file=file), scale, max_size, bg)
