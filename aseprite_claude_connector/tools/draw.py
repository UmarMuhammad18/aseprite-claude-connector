"""Drawing tools (mutating — each is one undo step on the live editor).

All tools composite the active cel, draw into a sprite-sized image via ``editCel``
(defined in the Lua prelude), and write it back.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, parse_color, run
from .look import previewable

_RECT = """
return editCel(function(img, s)
  local col = Color{ r = R, g = G, b = B, a = A }
  local function putpx(px, py)
    if px >= 0 and py >= 0 and px < s.width and py < s.height then img:drawPixel(px, py, col) end
  end
  if FILL then
    for yy = 0, H - 1 do for xx = 0, W - 1 do putpx(X + xx, Y + yy) end end
  else
    for xx = 0, W - 1 do putpx(X + xx, Y); putpx(X + xx, Y + H - 1) end
    for yy = 0, H - 1 do putpx(X, Y + yy); putpx(X + W - 1, Y + yy) end
  end
  return J({ drawn = "rectangle", x = X, y = Y, w = W, h = H })
end)
"""

_LINE = """
return editCel(function(img, s)
  local col = Color{ r = R, g = G, b = B, a = A }
  local x0, y0, x1, y1 = X0, Y0, X1, Y1
  local dx = math.abs(x1 - x0)
  local dy = -math.abs(y1 - y0)
  local sx = x0 < x1 and 1 or -1
  local sy = y0 < y1 and 1 or -1
  local err = dx + dy
  while true do
    if x0 >= 0 and y0 >= 0 and x0 < s.width and y0 < s.height then img:drawPixel(x0, y0, col) end
    if x0 == x1 and y0 == y1 then break end
    local e2 = 2 * err
    if e2 >= dy then err = err + dy; x0 = x0 + sx end
    if e2 <= dx then err = err + dx; y0 = y0 + sy end
  end
  return J({ drawn = "line", from = {X0, Y0}, to = {X1, Y1} })
end)
"""

_CIRCLE = """
return editCel(function(img, s)
  local col = Color{ r = R, g = G, b = B, a = A }
  local cx, cy, rad = CX, CY, RAD
  local function px(x, y)
    if x >= 0 and y >= 0 and x < s.width and y < s.height then img:drawPixel(x, y, col) end
  end
  if FILL then
    for y = -rad, rad do
      for x = -rad, rad do
        if x * x + y * y <= rad * rad then px(cx + x, cy + y) end
      end
    end
  else
    local x, y, err = rad, 0, 1 - rad
    while x >= y do
      px(cx + x, cy + y); px(cx + y, cy + x); px(cx - y, cy + x); px(cx - x, cy + y)
      px(cx - x, cy - y); px(cx - y, cy - x); px(cx + y, cy - x); px(cx + x, cy - y)
      y = y + 1
      if err < 0 then err = err + 2 * y + 1 else x = x - 1; err = err + 2 * (y - x) + 1 end
    end
  end
  return J({ drawn = "circle", cx = CX, cy = CY, r = RAD })
end)
"""

_FILL = """
return editCel(function(img, s)
  local sx, sy = X, Y
  if sx < 0 or sy < 0 or sx >= s.width or sy >= s.height then error("fill point outside canvas") end
  local col = Color{ r = R, g = G, b = B, a = A }
  local target = img:getPixel(sx, sy)
  local repl = nil
  if s.colorMode == ColorMode.RGB then repl = app.pixelColor.rgba(R, G, B, A) end
  if repl ~= nil and target == repl then return J({ filled = false, reason = "target equals fill color" }) end
  local W, H = s.width, s.height
  local stack = { {sx, sy} }
  local count = 0
  while #stack > 0 do
    local p = table.remove(stack)
    local x, y = p[1], p[2]
    if x >= 0 and y >= 0 and x < W and y < H and img:getPixel(x, y) == target then
      img:drawPixel(x, y, col)
      count = count + 1
      stack[#stack + 1] = {x + 1, y}
      stack[#stack + 1] = {x - 1, y}
      stack[#stack + 1] = {x, y + 1}
      stack[#stack + 1] = {x, y - 1}
    end
  end
  return J({ filled = true, pixels = count })
end)
"""

_ELLIPSE = """
return editCel(function(img, s)
  local col = Color{ r = R, g = G, b = B, a = A }
  local cx, cy, rx, ry = CX, CY, RX, RY
  local function inside(x, y)
    if rx == 0 or ry == 0 then return false end
    local dx = (x - cx) / rx
    local dy = (y - cy) / ry
    return dx * dx + dy * dy <= 1.0
  end
  local function put(x, y) if x >= 0 and y >= 0 and x < s.width and y < s.height then img:drawPixel(x, y, col) end end
  for y = cy - ry, cy + ry do
    for x = cx - rx, cx + rx do
      if inside(x, y) then
        if FILL then put(x, y)
        elseif not (inside(x - 1, y) and inside(x + 1, y) and inside(x, y - 1) and inside(x, y + 1)) then put(x, y) end
      end
    end
  end
  return J({ drawn = "ellipse", cx = CX, cy = CY, rx = RX, ry = RY })
end)
"""

# Bayer 4x4 threshold matrix, shared by the gradient (dithered) and dither tools.
_BAYER = "local bayer = {0,8,2,10, 12,4,14,6, 3,11,1,9, 15,7,13,5}\n"

_GRADIENT = (
    _BAYER
    + """
return editCel(function(img, s)
  local function put(x, y, c) if x >= 0 and y >= 0 and x < s.width and y < s.height then img:drawPixel(x, y, c) end end
  local c1 = Color{ r = R1, g = G1, b = B1, a = A1 }
  local c2 = Color{ r = R2, g = G2, b = B2, a = A2 }
  local ramp = {}
  for i = 0, BANDS do
    local k = i / BANDS
    ramp[i] = Color{
      r = math.floor(R1 + (R2 - R1) * k + 0.5),
      g = math.floor(G1 + (G2 - G1) * k + 0.5),
      b = math.floor(B1 + (B2 - B1) * k + 0.5),
      a = math.floor(A1 + (A2 - A1) * k + 0.5) }
  end
  for yy = 0, H - 1 do
    for xx = 0, W - 1 do
      local t
      if DIR == 0 then t = (W > 1) and xx / (W - 1) or 0
      elseif DIR == 1 then t = (H > 1) and yy / (H - 1) or 0
      else t = ((W + H) > 2) and (xx + yy) / (W + H - 2) or 0 end
      local px, py = X + xx, Y + yy
      if DITHER then
        local thr = (bayer[(yy % 4) * 4 + (xx % 4) + 1] + 0.5) / 16.0
        local pos = t * BANDS
        local i = math.min(math.floor(pos), BANDS - 1)
        local frac = pos - i
        -- With several bands, each stays solid and only the seams between them dither.
        if BANDS > 1 then frac = math.max(0, math.min(1, (frac - 0.3) / 0.4)) end
        put(px, py, (frac > thr) and ramp[i + 1] or ramp[i])
      else
        put(px, py, Color{
          r = math.floor(R1 + (R2 - R1) * t + 0.5),
          g = math.floor(G1 + (G2 - G1) * t + 0.5),
          b = math.floor(B1 + (B2 - B1) * t + 0.5),
          a = math.floor(A1 + (A2 - A1) * t + 0.5) })
      end
    end
  end
  return J({ drawn = "gradient", dither = DITHER, region = { X, Y, W, H } })
end)
"""
)

_DITHER = (
    _BAYER
    + """
return editCel(function(img, s)
  local function put(x, y, c) if x >= 0 and y >= 0 and x < s.width and y < s.height then img:drawPixel(x, y, c) end end
  local c1 = Color{ r = R1, g = G1, b = B1, a = A1 }
  local c2 = Color{ r = R2, g = G2, b = B2, a = A2 }
  for yy = 0, H - 1 do
    for xx = 0, W - 1 do
      local thr = (bayer[(yy % 4) * 4 + (xx % 4) + 1] + 0.5) / 16.0
      put(X + xx, Y + yy, (DENSITY > thr) and c2 or c1)
    end
  end
  return J({ dithered = true, density = DENSITY, region = { X, Y, W, H } })
end)
"""
)

# PIXELS is a Lua array of {x, y, r, g, b, a}, prepended by Python. The pixel
# value is converted per color mode explicitly (raw RGBA ints would be written
# as bogus palette indices on indexed sprites; Color{} doesn't reliably resolve
# an index in batch mode).
_PIXELS = """
return editCel(function(img, s)
  local pc = app.pixelColor
  local pal = s.palettes[1]
  local function pixval(r, g, b, a)
    if img.colorMode == ColorMode.RGB then return pc.rgba(r, g, b, a) end
    if img.colorMode == ColorMode.GRAY then
      return pc.graya(math.floor(0.299 * r + 0.587 * g + 0.114 * b + 0.5), a)
    end
    if a == 0 then return s.transparentColor end
    local best, bestd = 0, math.huge
    for i = 0, #pal - 1 do
      local c = pal:getColor(i)
      local d = (c.red - r) ^ 2 + (c.green - g) ^ 2 + (c.blue - b) ^ 2
      if d < bestd then best, bestd = i, d end
    end
    return best
  end
  local drawn, skipped = 0, 0
  for _, p in ipairs(PIXELS) do
    if p[1] >= 0 and p[2] >= 0 and p[1] < s.width and p[2] < s.height then
      img:drawPixel(p[1], p[2], pixval(p[3], p[4], p[5], p[6]))
      drawn = drawn + 1
    else
      skipped = skipped + 1
    end
  end
  return J({ drawn = drawn, skipped = skipped })
end)
"""

_POLYLINE = """
return editCel(function(img, s)
  local col = Color{ r = R, g = G, b = B, a = A }
  local function putpx(px, py)
    if px >= 0 and py >= 0 and px < s.width and py < s.height then img:drawPixel(px, py, col) end
  end
  local function seg(x0, y0, x1, y1)
    local dx = math.abs(x1 - x0)
    local dy = -math.abs(y1 - y0)
    local sx = x0 < x1 and 1 or -1
    local sy = y0 < y1 and 1 or -1
    local e = dx + dy
    while true do
      putpx(x0, y0)
      if x0 == x1 and y0 == y1 then break end
      local e2 = 2 * e
      if e2 >= dy then e = e + dy; x0 = x0 + sx end
      if e2 <= dx then e = e + dx; y0 = y0 + sy end
    end
  end
  local n = #PTS
  for i = 1, n - 1 do seg(PTS[i][1], PTS[i][2], PTS[i + 1][1], PTS[i + 1][2]) end
  if CLOSE and n > 2 then seg(PTS[n][1], PTS[n][2], PTS[1][1], PTS[1][2]) end
  return J({ segments = n - 1 + ((CLOSE and n > 2) and 1 or 0) })
end)
"""

_OUTLINE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local layer = LAYER and findLayer(s, LAYER) or activeImageLayer(s)
if not layer or not layer.isImage then error("no target image layer") end
local mode = s.colorMode
if SELECTIVE and mode ~= ColorMode.RGB then error("selective outlines need an RGB sprite") end
local col = Color{ r = R, g = G, b = B, a = A }
local pc = app.pixelColor
local function solid(v)
  if mode == ColorMode.RGB then return pc.rgbaA(v) > 0 end
  if mode == ColorMode.GRAY then return pc.grayaA(v) > 0 end
  return v ~= s.transparentColor
end
local dirs = DIAG and {{1,0},{-1,0},{0,1},{0,-1},{1,1},{1,-1},{-1,1},{-1,-1}} or {{1,0},{-1,0},{0,1},{0,-1}}
-- Each cel grows by a pixel all round, so art at its edge still gets its outline.
local function outline(cel)
  local src = cel.image
  local W, H = src.width + 2, src.height + 2
  local img = Image(W, H, mode)
  if mode == ColorMode.INDEXED then img:clear(s.transparentColor) end
  img:drawImage(src, Point(1, 1))
  local base = img:clone()
  local function at(x, y)
    if x < 0 or y < 0 or x >= W or y >= H then return nil end
    local v = base:getPixel(x, y)
    if solid(v) then return v end
    return nil
  end
  local added = 0
  for y = 0, H - 1 do
    for x = 0, W - 1 do
      if not at(x, y) then
        for _, d in ipairs(dirs) do
          local v = at(x + d[1], y + d[2])
          if v then
            if SELECTIVE then
              img:drawPixel(x, y, pc.rgba(pc.rgbaR(v) * 45 // 100, pc.rgbaG(v) * 40 // 100,
                math.min(255, pc.rgbaB(v) * 55 // 100 + 12), 255))
            else
              img:drawPixel(x, y, col)
            end
            added = added + 1
            break
          end
        end
      end
    end
  end
  cel.image = img
  cel.position = Point(cel.position.x - 1, cel.position.y - 1)
  return added
end
local total, frames = 0, 0
if ALL then
  for _, cel in ipairs(layer.cels) do total = total + outline(cel); frames = frames + 1 end
else
  local frame = app.activeFrame or s.frames[1]
  local cel = layer:cel(frame.frameNumber)
  if cel then total = outline(cel); frames = 1 end
end
return J({ outlined = frames > 0, pixels = total, frames = frames, layer = layer.name })
"""


def _pixels_lua(pixels) -> str:
    parts = []
    try:
        for p in pixels:
            r, g, b, a = parse_color(p["color"])
            parts.append(f"{{{int(p['x'])},{int(p['y'])},{r},{g},{b},{a}}}")
    except (TypeError, KeyError, ValueError):
        raise ToolError('pixels must be a list of {"x", "y", "color"} objects') from None
    return "local PIXELS = {" + ",".join(parts) + "}\n"


def _points_lua(points) -> str:
    try:
        return "{" + ",".join(f"{{{int(p[0])},{int(p[1])}}}" for p in points) + "}"
    except (TypeError, KeyError, IndexError, ValueError):
        raise ToolError("points must be a list of [x, y] pairs") from None


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Draw pixels"))
    @previewable
    def draw_pixels(pixels: list, file: str | None = None) -> dict:
        """Set individual pixels: ``pixels`` is a list of
        ``{"x": int, "y": int, "color": "#rrggbb[aa]"}``. The precision tool for
        detail work — one undo step for the whole batch. Capped at 4096 pixels
        per call. Headless: pass ``file``."""
        if not pixels:
            raise ToolError("pixels list is empty")
        if len(pixels) > 4096:
            raise ToolError("too many pixels in one call (cap 4096); split the batch")
        body = _pixels_lua(pixels) + _PIXELS
        return run(body, mutates=True, undo_label="Draw pixels", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Draw polyline"))
    @previewable
    def draw_polyline(
        points: list, color: str, close: bool = False, file: str | None = None
    ) -> dict:
        """Stroke connected line segments through ``points`` (ordered [x, y]
        pairs); ``close=True`` joins the last point back to the first. One undo
        step. Headless: pass ``file``."""
        if not points or len(points) < 2:
            raise ToolError("need at least 2 points")
        r, g, b, a = parse_color(color)
        body = (
            f"local PTS = {_points_lua(points)}\n"
            + lua_locals(R=r, G=g, B=b, A=a, CLOSE=bool(close))
            + _POLYLINE
        )
        return run(body, mutates=True, undo_label="Draw polyline", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Draw rectangle"))
    @previewable
    def draw_rectangle(
        x: int,
        y: int,
        width: int,
        height: int,
        color: str,
        fill: bool = True,
        file: str | None = None,
    ) -> dict:
        """Draw a rectangle on the active layer + frame. ``color`` is #rrggbb or
        #rrggbbaa. ``fill`` false draws only the outline. One undo step (live).
        Headless: pass ``file``."""
        r, g, b, a = parse_color(color)
        body = (
            lua_locals(
                X=int(x), Y=int(y), W=int(width), H=int(height), R=r, G=g, B=b, A=a, FILL=fill
            )
            + _RECT
        )
        return run(body, mutates=True, undo_label="Draw rectangle", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Draw line"))
    @previewable
    def draw_line(x1: int, y1: int, x2: int, y2: int, color: str, file: str | None = None) -> dict:
        """Draw a 1px line from (x1,y1) to (x2,y2). One undo step. Headless: pass ``file``."""
        r, g, b, a = parse_color(color)
        body = (
            lua_locals(X0=int(x1), Y0=int(y1), X1=int(x2), Y1=int(y2), R=r, G=g, B=b, A=a) + _LINE
        )
        return run(body, mutates=True, undo_label="Draw line", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Draw circle"))
    @previewable
    def draw_circle(
        center_x: int,
        center_y: int,
        radius: int,
        color: str,
        fill: bool = False,
        file: str | None = None,
    ) -> dict:
        """Draw a circle centered at (center_x, center_y). ``fill`` true fills the
        disk. One undo step. Headless: pass ``file``."""
        r, g, b, a = parse_color(color)
        body = (
            lua_locals(
                CX=int(center_x), CY=int(center_y), RAD=int(radius), R=r, G=g, B=b, A=a, FILL=fill
            )
            + _CIRCLE
        )
        return run(body, mutates=True, undo_label="Draw circle", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Flood fill"))
    @previewable
    def fill_area(x: int, y: int, color: str, file: str | None = None) -> dict:
        """Flood-fill the contiguous same-color region at (x, y). Most reliable on
        RGB sprites. One undo step. Headless: pass ``file``."""
        r, g, b, a = parse_color(color)
        body = lua_locals(X=int(x), Y=int(y), R=r, G=g, B=b, A=a) + _FILL
        return run(body, mutates=True, undo_label="Fill", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Draw ellipse"))
    @previewable
    def draw_ellipse(
        center_x: int,
        center_y: int,
        radius_x: int,
        radius_y: int,
        color: str,
        fill: bool = False,
        file: str | None = None,
    ) -> dict:
        """Draw an ellipse centered at (center_x, center_y) with independent x/y radii.
        ``fill`` true fills it. One undo step. Headless: pass ``file``."""
        r, g, b, a = parse_color(color)
        body = (
            lua_locals(
                CX=int(center_x),
                CY=int(center_y),
                RX=int(radius_x),
                RY=int(radius_y),
                R=r,
                G=g,
                B=b,
                A=a,
                FILL=fill,
            )
            + _ELLIPSE
        )
        return run(body, mutates=True, undo_label="Draw ellipse", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Draw gradient"))
    @previewable
    def draw_gradient(
        x: int,
        y: int,
        width: int,
        height: int,
        color1: str,
        color2: str,
        direction: str = "vertical",
        dither: bool = False,
        bands: int = 1,
        file: str | None = None,
    ) -> dict:
        """Fill a rectangle with a linear gradient from ``color1`` to ``color2``.
        ``direction`` is horizontal | vertical | diagonal. ``dither`` true uses an
        ordered Bayer dither between the two colors instead of blending RGB — the
        palette-friendly way. With ``dither``, ``bands`` above 1 steps through that
        many solid colors and dithers only the seams, which reads far cleaner than one
        dither across a tall area. One undo step. Headless: pass ``file``."""
        if not 1 <= bands <= 32:
            raise ToolError("bands must be 1-32")
        d = {"horizontal": 0, "vertical": 1, "diagonal": 2}.get(direction.strip().lower())
        if d is None:
            raise ToolError("direction must be horizontal | vertical | diagonal")
        r1, g1, b1, a1 = parse_color(color1)
        r2, g2, b2, a2 = parse_color(color2)
        body = (
            lua_locals(
                X=int(x),
                Y=int(y),
                W=int(width),
                H=int(height),
                DIR=d,
                DITHER=dither,
                BANDS=int(bands),
                R1=r1,
                G1=g1,
                B1=b1,
                A1=a1,
                R2=r2,
                G2=g2,
                B2=b2,
                A2=a2,
            )
            + _GRADIENT
        )
        return run(body, mutates=True, undo_label="Draw gradient", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Apply dither"))
    @previewable
    def apply_dither(
        x: int,
        y: int,
        width: int,
        height: int,
        color1: str,
        color2: str,
        density: float = 0.5,
        file: str | None = None,
    ) -> dict:
        """Fill a rectangle with a uniform ordered (Bayer 4x4) dither mixing ``color1``
        and ``color2``. ``density`` 0..1 is the fraction of ``color2`` — 0.5 is an even
        checker-style mix. One undo step. Headless: pass ``file``."""
        if not 0.0 <= density <= 1.0:
            raise ToolError("density must be 0.0..1.0")
        r1, g1, b1, a1 = parse_color(color1)
        r2, g2, b2, a2 = parse_color(color2)
        body = (
            lua_locals(
                X=int(x),
                Y=int(y),
                W=int(width),
                H=int(height),
                DENSITY=float(density),
                R1=r1,
                G1=g1,
                B1=b1,
                A1=a1,
                R2=r2,
                G2=g2,
                B2=b2,
                A2=a2,
            )
            + _DITHER
        )
        return run(body, mutates=True, undo_label="Apply dither", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Add outline"))
    @previewable
    def add_outline(
        color: str = "#000000",
        diagonal: bool = False,
        selective: bool = False,
        layer: str | None = None,
        all_frames: bool = False,
        file: str | None = None,
    ) -> dict:
        """Add a 1px outline around the opaque pixels of a layer, in ``color`` — readability
        against busy backgrounds. ``selective`` true ignores ``color`` and darkens each
        neighbouring pixel's own color instead, for a softer outline that follows the art
        (RGB sprites). ``diagonal`` true also outlines diagonally (8-connected). ``layer``
        picks the layer, and ``all_frames`` outlines every cel on it rather than the
        active one. One undo step. Headless: pass ``file``."""
        r, g, b, a = parse_color(color)
        body = (
            lua_locals(
                R=r,
                G=g,
                B=b,
                A=a,
                DIAG=diagonal,
                SELECTIVE=selective,
                LAYER=layer,
                ALL=all_frames,
            )
            + _OUTLINE
        )
        return run(body, mutates=True, undo_label="Add outline", file=file)
