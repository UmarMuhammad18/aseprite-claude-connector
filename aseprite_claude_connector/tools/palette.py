"""Palette tools."""

from __future__ import annotations

import colorsys

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, parse_color, run

_GET = """
local s = app.activeSprite
if not s then error("no active sprite") end
local pal = s.palettes[1]
local out = {}
for i = 0, #pal - 1 do
  local c = pal:getColor(i)
  out[#out + 1] = string.format("#%02x%02x%02x%02x", c.red, c.green, c.blue, c.alpha)
end
return J({ size = #pal, colors = out })
"""

_SET_COLOR = """
local s = app.activeSprite
if not s then error("no active sprite") end
local pal = s.palettes[1]
if INDEX < 0 or INDEX >= #pal then error("index out of range (0.." .. (#pal - 1) .. ")") end
pal:setColor(INDEX, Color{ r = R, g = G, b = B, a = A })
return J({ index = INDEX })
"""

_ADD_COLOR = """
local s = app.activeSprite
if not s then error("no active sprite") end
local pal = s.palettes[1]
local n = #pal
pal:resize(n + 1)
pal:setColor(n, Color{ r = R, g = G, b = B, a = A })
return J({ index = n, size = #pal })
"""

# Uses a COLORS local (Lua array of {r,g,b,a}) prepended by Python.
_SET_PALETTE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local pal = Palette(#COLORS)
for i = 1, #COLORS do
  local c = COLORS[i]
  pal:setColor(i - 1, Color{ r = c[1], g = c[2], b = c[3], a = c[4] })
end
s:setPalette(pal)
return J({ size = #COLORS })
"""

# A few well-known palettes for apply_preset_palette (parity with headless servers).
PRESETS = {
    "gameboy": ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"],
    "pico8": [
        "#000000",
        "#1d2b53",
        "#7e2553",
        "#008751",
        "#ab5236",
        "#5f574f",
        "#c2c3c7",
        "#fff1e8",
        "#ff004d",
        "#ffa300",
        "#ffec27",
        "#00e436",
        "#29adff",
        "#83769c",
        "#ff77a8",
        "#ffccaa",
    ],
    "cga": [
        "#000000",
        "#0000aa",
        "#00aa00",
        "#00aaaa",
        "#aa0000",
        "#aa00aa",
        "#aa5500",
        "#aaaaaa",
        "#555555",
        "#5555ff",
        "#55ff55",
        "#55ffff",
        "#ff5555",
        "#ff55ff",
        "#ffff55",
        "#ffffff",
    ],
}


def _colors_lua(hex_colors: list[str]) -> str:
    parts = []
    for c in hex_colors:
        r, g, b, a = parse_color(c)
        parts.append(f"{{{r},{g},{b},{a}}}")
    return "local COLORS = {" + ",".join(parts) + "}\n"


# Append COLORS to the current palette (vs _SET_PALETTE which replaces it).
_APPEND_COLORS = """
local s = app.activeSprite
if not s then error("no active sprite") end
local pal = s.palettes[1]
local n = #pal
pal:resize(n + #COLORS)
for i = 1, #COLORS do
  local c = COLORS[i]
  pal:setColor(n + i - 1, Color{ r = c[1], g = c[2], b = c[3], a = c[4] })
end
return J({ added = #COLORS, start = n, size = #pal })
"""

# Median-cut palette extraction from an external image, done in Lua (no Pillow
# dependency for the shipped server). Samples opaque pixels (strided if huge),
# recursively splits the widest color bucket, averages each, sorts dark->light.
_EXTRACT = """
local img = Image{ fromFile = PATH }
if not img then error("could not load image: " .. PATH) end
local pc = app.pixelColor
local W, H = img.width, img.height
local total = W * H
local stride = 1
if total > 20000 then stride = math.ceil(math.sqrt(total / 20000)) end
local pts = {}
local yy = 0
while yy < H do
  local xx = 0
  while xx < W do
    local v = img:getPixel(xx, yy)
    if pc.rgbaA(v) > 0 then pts[#pts + 1] = { pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v) } end
    xx = xx + stride
  end
  yy = yy + stride
end
if #pts == 0 then error("image has no opaque pixels") end
local function chanRange(b, ch)
  local lo, hi = 255, 0
  for _, p in ipairs(b) do if p[ch] < lo then lo = p[ch] end; if p[ch] > hi then hi = p[ch] end end
  return hi - lo
end
local buckets = { pts }
while #buckets < MAXC do
  local bi, brange = nil, -1
  for i, b in ipairs(buckets) do
    if #b > 1 then
      for ch = 1, 3 do
        local rng = chanRange(b, ch)
        if rng > brange then brange = rng; bi = i end
      end
    end
  end
  if not bi or brange <= 0 then break end
  local b = buckets[bi]
  local bestch, bestrng = 1, -1
  for ch = 1, 3 do local rng = chanRange(b, ch); if rng > bestrng then bestrng = rng; bestch = ch end end
  table.sort(b, function(p, q) return p[bestch] < q[bestch] end)
  local mid = math.floor(#b / 2)
  local b1, b2 = {}, {}
  for i = 1, mid do b1[#b1 + 1] = b[i] end
  for i = mid + 1, #b do b2[#b2 + 1] = b[i] end
  buckets[bi] = b1
  buckets[#buckets + 1] = b2
end
local cols = {}
for _, b in ipairs(buckets) do
  local sr, sg, sb = 0, 0, 0
  for _, p in ipairs(b) do sr = sr + p[1]; sg = sg + p[2]; sb = sb + p[3] end
  local n = #b
  if n > 0 then cols[#cols + 1] = { math.floor(sr / n + 0.5), math.floor(sg / n + 0.5), math.floor(sb / n + 0.5) } end
end
table.sort(cols, function(a, b)
  return (0.299 * a[1] + 0.587 * a[2] + 0.114 * a[3]) < (0.299 * b[1] + 0.587 * b[2] + 0.114 * b[3])
end)
local hexes = {}
for i, c in ipairs(cols) do hexes[i] = string.format("#%02x%02x%02x", c[1], c[2], c[3]) end
local s = app.activeSprite
if REPLACE and s then
  local pal = Palette(#cols)
  for i = 1, #cols do pal:setColor(i - 1, Color{ r = cols[i][1], g = cols[i][2], b = cols[i][3], a = 255 }) end
  s:setPalette(pal)
end
return J({ colors = hexes, count = #hexes, source = PATH, replaced = REPLACE })
"""


_SORT = """
local s = app.activeSprite
if not s then error("no active sprite") end
local pal = s.palettes[1]
local entries = {}
for i = 0, #pal - 1 do
  local c = pal:getColor(i)
  local key
  if BY == "hue" then key = c.hsvHue
  elseif BY == "saturation" then key = c.hsvSaturation
  else key = 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue end
  entries[#entries + 1] = { c = Color(c), k = key }
end
table.sort(entries, function(a, b)
  if ASC then return a.k < b.k else return a.k > b.k end
end)
for i, e in ipairs(entries) do pal:setColor(i - 1, e.c) end
return J({ sorted = #entries, by = BY, ascending = ASC })
"""

_QUANTIZE_FROM_SPRITE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local before = #s.palettes[1]
app.command.ColorQuantization{ ui = false, withAlpha = false, maxColors = MAXC }
local pal = s.palettes[1]
local out = {}
for i = 0, #pal - 1 do
  local c = pal:getColor(i)
  out[#out + 1] = string.format("#%02x%02x%02x", c.red, c.green, c.blue)
end
return J({ before = before, size = #pal, colors = out })
"""

_LOAD_PALETTE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local pal = Palette{ fromFile = PATH }
if not pal then error("could not load palette: " .. PATH) end
s:setPalette(pal)
return J({ size = #pal, source = PATH })
"""

_SAVE_PALETTE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local pal = s.palettes[1]
pal:saveAs(PATH)
return J({ size = #pal, saved = PATH })
"""

_RESOURCE_PALETTE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local ok, pal = pcall(function() return Palette{ fromResource = RES } end)
if not ok or not pal then
  error("no bundled palette named '" .. RES .. "' (try DB16, DB32, ARQ4, EDG16, ...)")
end
s:setPalette(pal)
return J({ size = #pal, resource = RES })
"""


def _ramp(base_hex: str, count: int, hue_shift: bool) -> list[str]:
    """Build a dark->light shading ramp from a base color. Optional hue-shift pushes
    shadows toward blue and highlights toward yellow — the classic pixel-art move."""
    r, g, b, _ = parse_color(base_hex)
    h, _l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    out = []
    for i in range(count):
        t = i / (count - 1) if count > 1 else 0.5  # 0 = darkest, 1 = lightest
        nl = 0.15 + t * 0.7
        hh = (h + (0.5 - t) * 0.08) % 1.0 if hue_shift else h
        ns = min(1.0, s * (1.0 + (0.5 - abs(t - 0.5)) * 0.3))
        rr, gg, bb = colorsys.hls_to_rgb(hh, nl, ns)
        out.append(f"#{round(rr * 255):02x}{round(gg * 255):02x}{round(bb * 255):02x}")
    return out


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Get palette", readOnlyHint=True))
    def get_palette(file: str | None = None) -> dict:
        """Return the active sprite's palette as #rrggbbaa hex strings."""
        return run(_GET, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set palette color", idempotentHint=True))
    def set_palette_color(index: int, color: str, file: str | None = None) -> dict:
        """Set palette entry ``index`` to ``color`` (#rrggbb or #rrggbbaa)."""
        r, g, b, a = parse_color(color)
        body = lua_locals(INDEX=int(index), R=r, G=g, B=b, A=a) + _SET_COLOR
        return run(body, mutates=True, undo_label="Set palette color", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Add palette color"))
    def add_palette_color(color: str, file: str | None = None) -> dict:
        """Append ``color`` to the palette and return its new index."""
        r, g, b, a = parse_color(color)
        body = lua_locals(R=r, G=g, B=b, A=a) + _ADD_COLOR
        return run(body, mutates=True, undo_label="Add palette color", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set palette"))
    def set_palette(colors: list[str], file: str | None = None) -> dict:
        """Replace the whole palette with ``colors`` (list of #rrggbb/#rrggbbaa)."""
        if not colors:
            raise ToolError("colors must be a non-empty list")
        body = _colors_lua(colors) + _SET_PALETTE
        return run(body, mutates=True, undo_label="Set palette", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Apply preset palette"))
    def apply_preset_palette(name: str, file: str | None = None) -> dict:
        """Replace the palette with a built-in preset: gameboy | pico8 | cga."""
        key = name.strip().lower()
        if key not in PRESETS:
            raise ToolError(f"unknown preset '{name}' (have: {', '.join(sorted(PRESETS))})")
        body = _colors_lua(PRESETS[key]) + _SET_PALETTE
        return run(body, mutates=True, undo_label=f"Preset palette {key}", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Generate color ramp"))
    def generate_color_ramp(
        base_color: str, count: int = 5, hue_shift: bool = True, file: str | None = None
    ) -> dict:
        """Generate a dark->light shading ramp from ``base_color`` and APPEND it to the
        palette in order — ready for ``palette_ramp_walk``. ``count`` colors;
        ``hue_shift`` pushes shadows toward blue and highlights toward yellow. Returns
        the ramp as hex. One undo step. Headless: pass ``file``."""
        if count < 2:
            raise ToolError("count must be >= 2")
        hexes = _ramp(base_color, count, hue_shift)
        res = run(
            _colors_lua(hexes) + _APPEND_COLORS,
            mutates=True,
            undo_label="Generate color ramp",
            file=file,
        )
        if isinstance(res, dict):
            res["colors"] = hexes
        return res

    @mcp.tool(annotations=ToolAnnotations(title="Extract palette from image"))
    def extract_palette_from_image(
        image_path: str, max_colors: int = 16, replace: bool = True, file: str | None = None
    ) -> dict:
        """Extract a palette (median-cut) from an external image file and, by default,
        set it as the active sprite's palette — the concept-art → locked-palette step.
        Returns the colors as hex, sorted dark→light. Headless: pass ``file``."""
        if not 2 <= max_colors <= 256:
            raise ToolError("max_colors must be 2..256")
        body = lua_locals(PATH=image_path, MAXC=int(max_colors), REPLACE=bool(replace)) + _EXTRACT
        return run(body, mutates=bool(replace), undo_label="Extract palette", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Sort palette"))
    def sort_palette(
        by: str = "luminance", ascending: bool = True, file: str | None = None
    ) -> dict:
        """Reorder palette swatches by ``luminance`` (default), ``hue``, or
        ``saturation``. Intended for RGB sprites' swatch organization — on an
        INDEXED sprite this changes which color each pixel shows (indices aren't
        remapped). One undo step."""
        if by not in ("luminance", "hue", "saturation"):
            raise ToolError("by must be luminance, hue, or saturation")
        body = lua_locals(BY=by, ASC=bool(ascending)) + _SORT
        return run(body, mutates=True, undo_label="Sort palette", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Palette from sprite"))
    def palette_from_sprite(max_colors: int = 32, file: str | None = None) -> dict:
        """Derive the palette FROM the sprite's actual pixels (Aseprite's color
        quantization) — the inverse of ``quantize_to_palette``. Returns the new
        palette as hex. One undo step."""
        if not 2 <= max_colors <= 256:
            raise ToolError("max_colors must be 2..256")
        body = lua_locals(MAXC=int(max_colors)) + _QUANTIZE_FROM_SPRITE
        return run(body, mutates=True, undo_label="Palette from sprite", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Load palette file"))
    def load_palette(path: str, file: str | None = None) -> dict:
        """Replace the sprite's palette from a palette file (.gpl, .pal, .ase,
        .png strip — anything Aseprite reads). One undo step."""
        body = lua_locals(PATH=str(path)) + _LOAD_PALETTE
        return run(body, mutates=True, undo_label="Load palette", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Save palette file", openWorldHint=True))
    def save_palette(path: str, file: str | None = None) -> dict:
        """Write the sprite's palette to a file (.gpl, .pal, .png — by extension)."""
        body = lua_locals(PATH=str(path)) + _SAVE_PALETTE
        return run(body, mutates=False, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Apply bundled palette"))
    def apply_bundled_palette(name: str, file: str | None = None) -> dict:
        """Apply one of Aseprite's bundled extension palettes by resource ID —
        e.g. DB16, DB32, ARQ4, EDG16 (availability depends on the installed
        palette extensions). For gameboy/pico8/cga see ``apply_preset_palette``.
        One undo step."""
        body = lua_locals(RES=str(name)) + _RESOURCE_PALETTE
        return run(body, mutates=True, undo_label="Apply bundled palette", file=file)
