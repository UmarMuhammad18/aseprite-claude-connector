"""Tilemap tools — tilemap layers, tilesets, per-tile pixel edits, and tile placement.

Empirical notes (verified headless on Aseprite 1.3.17.2):

- ``app.command.NewLayer{ name=..., tilemap=true, gridBounds=Rectangle(0,0,tw,th) }``
  works in ``--batch`` and leaves the new tilemap layer active; the tileset grid
  honors ``gridBounds``.
- A fresh tileset has length 1: tile 0 is the reserved *empty* tile. ``Sprite:newTile``
  appends, so the first real tile is index 1. Scripting *can* assign an image to
  tile 0, but everything an empty cell shows is tile 0 — so these tools refuse to
  draw on it.
- Tilemap cel images are ``ColorMode.TILEMAP`` and sized in TILE units (a 3×2 image
  is 3 columns × 2 rows), while ``cel.position``/``cel.bounds`` are in canvas
  *pixels* (a 3×2 cel of 8×8 tiles at Point(0,0) has bounds 0,0,24,16). Anchoring
  cels at Point(0,0) keeps column/row equal to image x/y.
- Each tilemap "pixel" is a 32-bit tile reference (flip flags live in the high
  bits); ``app.pixelColor.tileI`` strips the flags when reading indices back.
- ``app.command.ExportTileset{ ui=false, ... }`` works headless and exports the
  strip *including* tile 0 as the first cell, so tile index ``i`` sits at
  ``x = i * tile_width`` in a horizontal strip.
"""

from __future__ import annotations

import os

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, parse_color, run

# Prepended to each body: tilemap layers only, top-level scan (matches findLayer).
_TM = """
local function findTilemapLayer(s, name)
  for _, l in ipairs(s.layers) do
    if l.name == name and l.isTilemap then return l end
  end
  return nil
end
"""

_CREATE = """
local s = app.activeSprite
if not s then error("no active sprite") end
app.command.NewLayer{ name = NAME, tilemap = true, gridBounds = Rectangle(0, 0, TW, TH) }
local l = app.activeLayer
if not l or not l.isTilemap then error("NewLayer did not create a tilemap layer") end
if l.name ~= NAME then l.name = NAME end
local ts = l.tileset
local g = ts.grid.tileSize
return J({ name = l.name, tile_width = g.width, tile_height = g.height,
  tileset_size = #ts, layers = #s.layers })
"""

_ADD_TILE = (
    _TM
    + """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findTilemapLayer(s, LAYER)
if not l then error("layer '" .. LAYER .. "' not found or not a tilemap layer") end
local ts = l.tileset
local t = s:newTile(ts)
return J({ layer = LAYER, tile_index = t.index, tileset_size = #ts })
"""
)

_DRAW_TILE = (
    _TM
    + """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findTilemapLayer(s, LAYER)
if not l then error("layer '" .. LAYER .. "' not found or not a tilemap layer") end
local ts = l.tileset
if INDEX >= #ts then
  error("tile index " .. INDEX .. " out of range (tileset has " .. #ts .. " tiles)")
end
local t = ts:tile(INDEX)
local img = Image(t.image)
local pc = app.pixelColor
local drawn = 0
for _, q in ipairs(PIX) do
  if q[1] >= 0 and q[2] >= 0 and q[1] < img.width and q[2] < img.height then
    img:drawPixel(q[1], q[2], pc.rgba(q[3], q[4], q[5], q[6]))
    drawn = drawn + 1
  end
end
t.image = img
return J({ layer = LAYER, tile_index = INDEX, drawn = drawn, skipped = #PIX - drawn,
  tile_width = img.width, tile_height = img.height })
"""
)

_SET_TILES = (
    _TM
    + """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findTilemapLayer(s, LAYER)
if not l then error("layer '" .. LAYER .. "' not found or not a tilemap layer") end
if FRAME < 1 or FRAME > #s.frames then
  error("frame " .. FRAME .. " out of range (sprite has " .. #s.frames .. " frames)")
end
local ts = l.tileset
local g = ts.grid.tileSize
local tw, th = g.width, g.height
local w, h = 1, 1
for _, q in ipairs(TILES) do
  if q[3] >= #ts then
    error("tile index " .. q[3] .. " out of range (tileset has " .. #ts .. " tiles)")
  end
  if q[1] + 1 > w then w = q[1] + 1 end
  if q[2] + 1 > h then h = q[2] + 1 end
end
local cel = l:cel(FRAME)
local offc, offr = 0, 0
if cel then
  offc = math.floor(cel.position.x / tw)
  offr = math.floor(cel.position.y / th)
  local old = cel.image
  if offc + old.width > w then w = offc + old.width end
  if offr + old.height > h then h = offr + old.height end
end
local img = Image(w, h, ColorMode.TILEMAP)
if cel then
  local old = cel.image
  for y = 0, old.height - 1 do
    for x = 0, old.width - 1 do
      img:drawPixel(x + offc, y + offr, old:getPixel(x, y))
    end
  end
end
for _, q in ipairs(TILES) do
  img:drawPixel(q[1], q[2], q[3])
end
if cel then
  cel.image = img
  cel.position = Point(0, 0)
else
  s:newCel(l, s.frames[FRAME], img, Point(0, 0))
end
return J({ layer = LAYER, frame = FRAME, placed = #TILES, grid_width = w, grid_height = h })
"""
)

_INFO = (
    _TM
    + """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findTilemapLayer(s, LAYER)
if not l then error("layer '" .. LAYER .. "' not found or not a tilemap layer") end
if FRAME < 1 or FRAME > #s.frames then
  error("frame " .. FRAME .. " out of range (sprite has " .. #s.frames .. " frames)")
end
local ts = l.tileset
local g = ts.grid.tileSize
local out = { layer = LAYER, frame = FRAME, tile_width = g.width, tile_height = g.height,
  tileset_size = #ts, has_cel = false }
local cel = l:cel(FRAME)
if cel then
  local img = cel.image
  local pc = app.pixelColor
  out.has_cel = true
  out.cel_x = cel.position.x
  out.cel_y = cel.position.y
  out.grid_width = img.width
  out.grid_height = img.height
  out.truncated = (img.width > CAP or img.height > CAP)
  local gw = math.min(img.width, CAP)
  local gh = math.min(img.height, CAP)
  local rows = {}
  for y = 0, gh - 1 do
    local row = {}
    for x = 0, gw - 1 do row[x + 1] = pc.tileI(img:getPixel(x, y)) end
    rows[y + 1] = row
  end
  out.tiles = rows
end
return J(out)
"""
)

_EXPORT = (
    _TM
    + """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findTilemapLayer(s, LAYER)
if not l then error("layer '" .. LAYER .. "' not found or not a tilemap layer") end
local ts = l.tileset
local g = ts.grid.tileSize
app.activeLayer = l
local params = { ui = false, type = SpriteSheetType.HORIZONTAL, textureFilename = OUT }
if DATA ~= nil then
  params.dataFilename = DATA
  params.dataFormat = SpriteSheetDataFormat.JSON_ARRAY
end
app.command.ExportTileset(params)
return J({ exported = OUT, tiles = #ts, tile_width = g.width, tile_height = g.height })
"""
)


def _pixels_lua(pixels: list[dict]) -> str:
    """Render ``[{x, y, color}, ...]`` as a Lua literal of {x,y,r,g,b,a} tuples."""
    if not pixels:
        raise ToolError("pixels must be a non-empty list of {x, y, color} objects")
    parts = []
    for p in pixels:
        try:
            x, y, c = int(p["x"]), int(p["y"]), str(p["color"])
        except (KeyError, TypeError, ValueError):
            raise ToolError("pixels must be a list of {x, y, color} objects") from None
        r, g, b, a = parse_color(c)
        parts.append(f"{{{x},{y},{r},{g},{b},{a}}}")
    return "{" + ",".join(parts) + "}"


def _tiles_lua(tiles: list[dict]) -> str:
    """Render ``[{column, row, index}, ...]`` as a Lua literal of {c,r,i} tuples."""
    if not tiles:
        raise ToolError("tiles must be a non-empty list of {column, row, index} objects")
    parts = []
    for t in tiles:
        try:
            c, r, i = int(t["column"]), int(t["row"]), int(t["index"])
        except (KeyError, TypeError, ValueError):
            raise ToolError("tiles must be a list of {column, row, index} objects") from None
        if c < 0 or r < 0:
            raise ToolError("tile column/row must be >= 0")
        if i < 0:
            raise ToolError("tile index must be >= 0 (0 = the empty tile)")
        parts.append(f"{{{c},{r},{i}}}")
    return "{" + ",".join(parts) + "}"


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Create tilemap layer"))
    def create_tilemap_layer(
        name: str, tile_width: int, tile_height: int, file: str | None = None
    ) -> dict:
        """Create a tilemap layer with its own tileset on a tile_width x tile_height
        grid. The new tileset starts with only tile 0, the reserved empty tile — use
        add_tile to append editable tiles. One undo step. Headless: pass ``file``."""
        if tile_width < 1 or tile_height < 1:
            raise ToolError("tile_width and tile_height must be >= 1")
        body = lua_locals(NAME=name, TW=int(tile_width), TH=int(tile_height)) + _CREATE
        return run(body, mutates=True, undo_label="Create tilemap layer", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Add tile"))
    def add_tile(layer: str, file: str | None = None) -> dict:
        """Append an empty tile to a tilemap layer's tileset; returns the new tile's
        index and the tileset size. The first added tile is index 1 (tile 0 is the
        reserved empty tile). One undo step. Headless: pass ``file``."""
        body = lua_locals(LAYER=layer) + _ADD_TILE
        return run(body, mutates=True, undo_label="Add tile", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Draw on tile"))
    def draw_on_tile(
        layer: str, tile_index: int, pixels: list[dict], file: str | None = None
    ) -> dict:
        """Set pixels on one tile of a tilemap layer's tileset. ``pixels`` is a list
        of {x, y, color} objects (color #rrggbb or #rrggbbaa; x/y relative to the
        tile's top-left). Pixels outside the tile are skipped and counted. Every
        placed instance of the tile updates. One undo step. Headless: pass ``file``."""
        if tile_index < 1:
            raise ToolError("tile 0 is the reserved empty tile; draw on index >= 1")
        body = (
            f"local PIX = {_pixels_lua(pixels)}\n"
            + lua_locals(LAYER=layer, INDEX=int(tile_index))
            + _DRAW_TILE
        )
        return run(body, mutates=True, undo_label="Draw on tile", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set tiles"))
    def set_tiles(layer: str, frame: int, tiles: list[dict], file: str | None = None) -> dict:
        """Place tile references on a tilemap layer's cel. ``tiles`` is a list of
        {column, row, index} objects (0-based grid cells; index 0 erases to the empty
        tile). The cel is created or grown as needed, anchored at the sprite origin.
        ``frame`` is 1-based. One undo step. Headless: pass ``file``."""
        body = (
            f"local TILES = {_tiles_lua(tiles)}\n"
            + lua_locals(LAYER=layer, FRAME=int(frame))
            + _SET_TILES
        )
        return run(body, mutates=True, undo_label="Set tiles", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Get tilemap info", readOnlyHint=True))
    def get_tilemap_info(layer: str, frame: int = 1, file: str | None = None) -> dict:
        """Read a tilemap layer: tile size, tileset length, and the cel's grid size,
        pixel position, and tile-index grid (``tiles`` as rows of columns, flip flags
        stripped; capped at 64x64 with ``truncated`` set). Read-only. Headless: pass
        ``file``."""
        body = lua_locals(LAYER=layer, FRAME=int(frame), CAP=64) + _INFO
        return run(body, file=file)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Export tileset", destructiveHint=False, openWorldHint=True
        )
    )
    def export_tileset(
        layer: str, output_path: str, data_path: str | None = None, file: str | None = None
    ) -> dict:
        """Export a tilemap layer's tileset as a horizontal PNG strip (plus an
        Aseprite JSON atlas if ``data_path`` is given). The strip includes tile 0
        (the empty tile) first, so tile index i sits at x = i * tile_width. Writes
        files but does not modify the sprite (it does make the layer active).
        Headless: pass ``file``."""
        body = lua_locals(LAYER=layer, OUT=output_path, DATA=data_path) + _EXPORT
        res = run(body, mutates=False, file=file, save=False)
        out = {"exported": output_path, "exists": os.path.isfile(output_path)}
        if data_path is not None:
            out["data"] = data_path
            out["data_exists"] = os.path.isfile(data_path)
        if isinstance(res, dict):
            out["tiles"] = res.get("tiles")
            out["tile_width"] = res.get("tile_width")
            out["tile_height"] = res.get("tile_height")
        return out
