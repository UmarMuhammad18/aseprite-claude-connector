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
