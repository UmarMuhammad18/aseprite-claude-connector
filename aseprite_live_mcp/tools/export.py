"""Export tools (read-only with respect to the sprite)."""

from __future__ import annotations

import os

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

# Single-image formats: a multi-frame sprite saved to one of these is split by
# Aseprite into <name>1.ext, <name>2.ext, ...
_SINGLE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".qoi", ".webp"}

_EXPORT_LUA = """
local s = app.activeSprite
if not s then error("no active sprite") end
s:saveCopyAs(OUT)
return J({ exported = OUT, frames = #s.frames })
"""

_SHEET_LUA = """
local s = app.activeSprite
if not s then error("no active sprite") end
local st = SpriteSheetType.ROWS
if SHEET == "horizontal" then st = SpriteSheetType.HORIZONTAL
elseif SHEET == "vertical" then st = SpriteSheetType.VERTICAL
elseif SHEET == "columns" then st = SpriteSheetType.COLUMNS
elseif SHEET == "packed" then st = SpriteSheetType.PACKED end
local params = { ui = false, type = st, textureFilename = OUT }
if DATA ~= nil then
  params.dataFilename = DATA
  params.dataFormat = SpriteSheetDataFormat.JSON_ARRAY
end
app.command.ExportSpriteSheet(params)
return J({ sheet = OUT, data = DATA, frames = #s.frames })
"""


def _resolve_written(out_path: str, frames: int) -> list[str]:
    """Return the file(s) Aseprite actually wrote for a saveCopyAs call."""
    if os.path.isfile(out_path):
        return [out_path]
    root, ext = os.path.splitext(out_path)
    if frames > 1 and ext.lower() in _SINGLE_IMAGE_EXTS:
        return [
            f"{root}{i}{ext}" for i in range(1, frames + 1) if os.path.isfile(f"{root}{i}{ext}")
        ]
    return []


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Export sprite", readOnlyHint=True))
    def export_sprite(out_path: str, file: str | None = None) -> dict:
        """Export the active sprite to a file; format is chosen by ``out_path``
        extension (.png, .gif, ...). A multi-frame sprite saved to a single-image
        format is split into ``<name>1.ext``, ``<name>2.ext``, ...; the returned
        ``files`` lists what was actually written. Does not modify the sprite.
        Headless: pass ``file``."""
        body = lua_locals(OUT=out_path) + _EXPORT_LUA
        res = run(body, mutates=False, file=file, save=False)
        frames = res.get("frames", 1) if isinstance(res, dict) else 1
        return {
            "requested": out_path,
            "frames": frames,
            "files": _resolve_written(out_path, frames),
        }

    @mcp.tool(annotations=ToolAnnotations(title="Export spritesheet", readOnlyHint=True))
    def export_spritesheet(
        out_path: str,
        data_path: str | None = None,
        sheet_type: str = "rows",
        file: str | None = None,
    ) -> dict:
        """Pack all frames into a single sprite-sheet image (optionally writing a
        JSON atlas to ``data_path``). ``sheet_type`` is rows | columns | horizontal
        | vertical | packed. Does not modify the sprite. Headless: pass ``file``."""
        st = sheet_type.strip().lower()
        if st not in ("rows", "columns", "horizontal", "vertical", "packed"):
            raise ToolError(f"bad sheet_type '{sheet_type}'")
        body = lua_locals(OUT=out_path, DATA=data_path, SHEET=st) + _SHEET_LUA
        res = run(body, mutates=False, file=file, save=False)
        out = {"sheet": out_path, "sheet_exists": os.path.isfile(out_path)}
        if data_path is not None:
            out["data"] = data_path
            out["data_exists"] = os.path.isfile(data_path)
        if isinstance(res, dict):
            out["frames"] = res.get("frames")
        return out
