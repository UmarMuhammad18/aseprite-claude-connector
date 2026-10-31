"""Read-only inspection tools."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..backends import get_backend
from ..lua import lua_locals
from ._common import ToolError, run
from ._schemas import SpriteInfo

_SPRITE_INFO_LUA = """
local s = app.activeSprite
if not s then return J({error = "no active sprite"}) end
local mode = "indexed"
if s.colorMode == ColorMode.RGB then mode = "rgb"
elseif s.colorMode == ColorMode.GRAY then mode = "gray" end
local tags = {}
for i, t in ipairs(s.tags) do tags[i] = t.name end
local layers = {}
for i, l in ipairs(s.layers) do layers[i] = l.name end
return J({
  width = s.width, height = s.height, colorMode = mode,
  frames = #s.frames, layers = layers, tags = tags,
  filename = s.filename,
})
"""

# Everything an agent would otherwise piece together from several calls. Layers list
# top first, like the timeline.
_DESCRIBE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local function enumName(enum, value)
  for k, v in pairs(enum) do if v == value then return k end end
  return tostring(value)
end
local mode = "indexed"
if s.colorMode == ColorMode.RGB then mode = "rgb"
elseif s.colorMode == ColorMode.GRAY then mode = "gray" end

local layers = {}
local function walk(list, depth)
  for i = #list, 1, -1 do
    local l = list[i]
    local kind = "image"
    if l.isGroup then kind = "group"
    elseif l.isTilemap then kind = "tilemap"
    elseif l.isReference then kind = "reference"
    elseif l.isBackground then kind = "background" end
    local entry = { name = l.name, depth = depth, kind = kind, visible = l.isVisible }
    if not l.isEditable then entry.locked = true end
    if l.isGroup then
      layers[#layers + 1] = entry
      walk(l.layers, depth + 1)
    else
      entry.opacity = l.opacity
      -- NORMAL shares its value with SRC_OVER, so a plain lookup picks either.
      entry.blend = l.blendMode == BlendMode.NORMAL and "normal"
        or enumName(BlendMode, l.blendMode):lower()
      entry.cels = #l.cels
      layers[#layers + 1] = entry
    end
  end
end
walk(s.layers, 0)

local durations, total = {}, 0
for i, f in ipairs(s.frames) do
  local ms = math.floor(f.duration * 1000 + 0.5)
  total = total + ms
  if i <= MAX_ITEMS then durations[i] = ms end
end

local tags = {}
for i, t in ipairs(s.tags) do
  tags[i] = {
    name = t.name, from = t.fromFrame.frameNumber, to = t.toFrame.frameNumber,
    direction = enumName(AniDir, t.aniDir):lower(), repeats = t.repeats,
  }
end

local slices = {}
for i, sl in ipairs(s.slices) do
  local b = sl.bounds
  slices[i] = { name = sl.name, x = b.x, y = b.y, width = b.width, height = b.height }
end

local pal = s.palettes[1]
local colors = {}
for i = 0, math.min(#pal, MAX_ITEMS) - 1 do
  local c = pal:getColor(i)
  colors[i + 1] = string.format("#%02x%02x%02x%02x", c.red, c.green, c.blue, c.alpha)
end

local selection = { empty = s.selection.isEmpty }
if not s.selection.isEmpty then
  local b = s.selection.bounds
  selection = { empty = false, x = b.x, y = b.y, width = b.width, height = b.height }
end

local active = {}
if app.activeLayer then active.layer = app.activeLayer.name end
if app.activeFrame then active.frame = app.activeFrame.frameNumber end
if app.activeTag then active.tag = app.activeTag.name end

return J({
  filename = s.filename, modified = s.isModified,
  width = s.width, height = s.height, colorMode = mode,
  layers = layers, tags = tags, slices = slices, selection = selection, active = active,
  frames = { count = #s.frames, total_ms = total, durations_ms = durations },
  palette = { count = #pal, colors = colors },
})
"""

_GET_PIXEL = """
local s = app.activeSprite
if not s then error("no active sprite") end
local frame = app.activeFrame or s.frames[1]
if X < 0 or Y < 0 or X >= s.width or Y >= s.height then error("point out of bounds") end
local img = Image(s.width, s.height, ColorMode.RGB)
img:drawSprite(s, frame)
local v = img:getPixel(X, Y)
return J({ x = X, y = Y, color = string.format("#%02x%02x%02x%02x",
  app.pixelColor.rgbaR(v), app.pixelColor.rgbaG(v), app.pixelColor.rgbaB(v), app.pixelColor.rgbaA(v)) })
"""

_GET_PIXELS = """
local s = app.activeSprite
if not s then error("no active sprite") end
local frame = app.activeFrame or s.frames[1]
if X < 0 or Y < 0 or W < 1 or H < 1 or X + W > s.width or Y + H > s.height then error("region out of bounds") end
if W * H > 4096 then error("region too large (" .. (W * H) .. " px > 4096 cap); use a smaller region or export") end
local img = Image(s.width, s.height, ColorMode.RGB)
img:drawSprite(s, frame)
local rows = {}
for yy = 0, H - 1 do
  local row = {}
  for xx = 0, W - 1 do
    local v = img:getPixel(X + xx, Y + yy)
    row[xx + 1] = string.format("#%02x%02x%02x%02x",
      app.pixelColor.rgbaR(v), app.pixelColor.rgbaG(v), app.pixelColor.rgbaB(v), app.pixelColor.rgbaA(v))
  end
  rows[yy + 1] = row
end
return J({ x = X, y = Y, width = W, height = H, pixels = rows })
"""


_GET_META = """
local s = app.activeSprite
if not s then error("no active sprite") end
local out = {}
local n = 0
for k, v in pairs(s.properties) do
  local t = type(v)
  if t == "string" or t == "number" or t == "boolean" then out[k] = v else out[k] = tostring(v) end
  n = n + 1
end
if n == 0 then return J({ empty = true }) end
return J({ properties = out })
"""


def register(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(title="Backend status", readOnlyHint=True, openWorldHint=True)
    )
    def status() -> dict:
        """Report backend health plus this server's version and whether a newer
        release exists. Live: whether Aseprite is connected + its version.
        Headless: the resolved Aseprite executable path and whether it exists."""
        from ..update_check import get_update_info

        health = get_backend().health()
        if isinstance(health, dict):
            health = {**health, "server": get_update_info()}
        return health

    @mcp.tool(annotations=ToolAnnotations(title="Sprite info", readOnlyHint=True))
    def get_sprite_info(file: str | None = None) -> SpriteInfo:
        """Get the active sprite's size, color mode, and layer/frame/tag lists.
        Headless: pass ``file`` (the .aseprite to inspect)."""
        res = run(_SPRITE_INFO_LUA, file=file)
        if not isinstance(res, dict):
            raise ToolError("could not read sprite info")
        if "error" in res:
            raise ToolError(str(res["error"]))
        return res

    @mcp.tool(annotations=ToolAnnotations(title="Describe sprite", readOnlyHint=True))
    def describe_sprite(file: str | None = None) -> dict:
        """Summarize the active sprite in one call: size, color mode, the layer tree
        with visibility and blend modes, frame timing, tags, slices, palette, the
        selection, and what's active. Frame durations and palette colors stop at 64
        entries; ``count`` always gives the full number."""
        return run(lua_locals(MAX_ITEMS=64) + _DESCRIBE, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Get pixel", readOnlyHint=True))
    def get_pixel(x: int, y: int, file: str | None = None) -> dict:
        """Read one composited pixel (all layers) at (x, y) as #rrggbbaa."""
        body = lua_locals(X=int(x), Y=int(y)) + _GET_PIXEL
        return run(body, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set sprite metadata"))
    def set_sprite_metadata(entries: dict, file: str | None = None) -> dict:
        """Attach typed key/value metadata to the sprite (Aseprite's Properties
        system — stored in the .aseprite file itself). Values may be strings,
        numbers, or booleans. Useful for provenance ("generated_by", spec IDs)
        and pipeline state. One undo step."""
        if not entries or not isinstance(entries, dict):
            raise ToolError("entries must be a non-empty object of key -> value")
        from ..lua import lua_str

        sets = []
        for k, v in entries.items():
            if not isinstance(k, str) or not k:
                raise ToolError("metadata keys must be non-empty strings")
            if isinstance(v, bool):
                lit = "true" if v else "false"
            elif isinstance(v, (int, float)):
                lit = repr(v)
            elif isinstance(v, str):
                lit = lua_str(v)
            else:
                raise ToolError(f"unsupported value type for '{k}' (string/number/bool only)")
            sets.append(f"s.properties[{lua_str(k)}] = {lit}")
        body = (
            'local s = app.activeSprite\nif not s then error("no active sprite") end\n'
            + "\n".join(sets)
            + f"\nreturn J({{ set = {len(sets)} }})"
        )
        return run(body, mutates=True, undo_label="Set metadata", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Get sprite metadata", readOnlyHint=True))
    def get_sprite_metadata(file: str | None = None) -> dict:
        """Read the sprite's typed key/value metadata (Properties)."""
        return run(_GET_META, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Get pixels", readOnlyHint=True))
    def get_pixels(x: int, y: int, width: int, height: int, file: str | None = None) -> dict:
        """Read a composited pixel region as a grid of #rrggbbaa strings — the AI
        feedback loop for 'what does the canvas look like now'. Capped at 4096 px;
        use a smaller region or export for larger areas."""
        body = lua_locals(X=int(x), Y=int(y), W=int(width), H=int(height)) + _GET_PIXELS
        return run(body, file=file)
