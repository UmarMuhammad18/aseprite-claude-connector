"""Sprite lifecycle tools."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run
from .look import image_loader

_CREATE_LUA = """
local cm = ColorMode.RGB
if MODE == "GRAY" then cm = ColorMode.GRAY
elseif MODE == "INDEXED" then cm = ColorMode.INDEXED end
local s = Sprite(W, H, cm)
return J({ width = s.width, height = s.height, colorMode = string.lower(MODE) })
"""

_EXPAND = """
local s = app.activeSprite
if not s then error("no active sprite") end
local ow, oh = s.width, s.height
app.command.CanvasSize{ ui = false, left = L, top = T, right = R, bottom = B, trimOutside = false }
return J({ old = { width = ow, height = oh }, new = { width = s.width, height = s.height } })
"""

# Manual sheet import: load the sheet image, slice cells row-major, one frame per
# cell. Runs identically live and headless (ImportSpriteSheet converts the ACTIVE
# document in place, which headless would clobber the target file's layers).
_IMPORT_SHEET = """
local s = app.activeSprite
if not s then error("no active sprite") end
local sheet = load_image()
if not sheet then error("could not load sheet image: " .. PATH) end
if sheet.width % FW ~= 0 or sheet.height % FH ~= 0 then
  error("sheet " .. sheet.width .. "x" .. sheet.height .. " is not a multiple of the frame size")
end
local cols = sheet.width // FW
local rows = sheet.height // FH
local layer = s:newLayer()
layer.name = "imported"
local count = 0
for r = 0, rows - 1 do
  for c = 0, cols - 1 do
    count = count + 1
    if count > #s.frames then s:newEmptyFrame() end
    local cellImg = Image(FW, FH, s.colorMode)
    cellImg:drawImage(sheet, Point(-c * FW, -r * FH))
    s:newCel(layer, count, cellImg, Point(0, 0))
  end
end
return J({ frames = count, columns = cols, rows = rows, layer = layer.name })
"""


def register(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Create sprite", readOnlyHint=False, destructiveHint=False, idempotentHint=False
        )
    )
    def create_sprite(
        width: int, height: int, color_mode: str = "rgb", file: str | None = None
    ) -> dict:
        """Create a new sprite. Live: opens a new untitled sprite in the editor.
        Headless: writes a new .aseprite to ``file`` (required).
        ``color_mode`` is one of rgb | gray | indexed."""
        mode = {"rgb": "RGB", "gray": "GRAY", "grayscale": "GRAY", "indexed": "INDEXED"}.get(
            color_mode.strip().lower()
        )
        if not mode:
            raise ToolError(f"bad color_mode '{color_mode}' (rgb|gray|indexed)")
        if width < 1 or height < 1:
            raise ToolError("width and height must be >= 1")
        body = lua_locals(W=int(width), H=int(height), MODE=mode) + _CREATE_LUA
        # Creating a document isn't part of another sprite's undo history, so no
        # transaction; headless persists the new sprite to `file`.
        return run(body, mutates=False, file=file, save=bool(file))

    @mcp.tool(annotations=ToolAnnotations(title="Expand canvas"))
    def expand_canvas(
        left: int = 0, top: int = 0, right: int = 0, bottom: int = 0, file: str | None = None
    ) -> dict:
        """Grow (or shrink, with negatives) the canvas per side WITHOUT scaling
        content — existing pixels keep their positions relative to the old
        origin. One undo step. Headless: pass ``file``."""
        if left == 0 and top == 0 and right == 0 and bottom == 0:
            raise ToolError("nothing to do: all four sides are 0")
        body = lua_locals(L=int(left), T=int(top), R=int(right), B=int(bottom)) + _EXPAND
        return run(body, mutates=True, undo_label="Expand canvas", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Import sprite sheet"))
    def import_spritesheet(
        sheet_path: str, frame_width: int, frame_height: int, file: str | None = None
    ) -> dict:
        """Slice a sheet PNG into animation frames: cells are read row-major at
        the given frame size onto a new "imported" layer, adding frames as
        needed. The sheet's dimensions must be exact multiples of the frame
        size. One undo step. Headless: pass ``file`` (the target sprite)."""
        if frame_width < 1 or frame_height < 1:
            raise ToolError("frame size must be >= 1")
        body = (
            image_loader(str(sheet_path))
            + lua_locals(PATH=str(sheet_path), FW=int(frame_width), FH=int(frame_height))
            + _IMPORT_SHEET
        )
        return run(body, mutates=True, undo_label="Import sprite sheet", file=file)
