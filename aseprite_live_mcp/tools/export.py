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

# Per-layer export: hide everything, then reveal one image layer (plus its
# ancestor groups — a layer inside a hidden group renders as nothing) and
# render. The pcall guarantees the original visibility flags come back even if
# a save fails mid-loop, so the document ends exactly as it started.
_LAYERS_LUA = """
local s = app.activeSprite
if not s then error("no active sprite") end
local all, targets = {}, {}
local function walk(layers, ancestors)
  for _, l in ipairs(layers) do
    all[#all + 1] = { layer = l, vis = l.isVisible }
    if l.isGroup then
      local chain = {}
      for i, a in ipairs(ancestors) do chain[i] = a end
      chain[#chain + 1] = l
      walk(l.layers, chain)
    elseif l.isImage then
      targets[#targets + 1] = { layer = l, ancestors = ancestors }
    end
  end
end
walk(s.layers, {})
if #targets == 0 then error("sprite has no image layers") end
local used, names, paths = {}, {}, {}
local ok, err = pcall(function()
  for _, t in ipairs(targets) do
    local base = t.layer.name:gsub("[^%w%-_]", "_")
    if base == "" then base = "layer" end
    local name = base
    local n = 2
    while used[name] do name = base .. "_" .. n; n = n + 1 end
    used[name] = true
    local out = app.fs.joinPath(OUT_DIR, name .. ".png")
    for _, e in ipairs(all) do e.layer.isVisible = false end
    for _, a in ipairs(t.ancestors) do a.isVisible = true end
    t.layer.isVisible = true
    s:saveCopyAs(out)
    names[#names + 1] = t.layer.name
    paths[#paths + 1] = out
  end
end)
for _, e in ipairs(all) do e.layer.isVisible = e.vis end
if not ok then error(err) end
return J({ layers = names, paths = paths, frames = #s.frames })
"""

# Tag export. Verified on 1.3.17.2 headless: SaveFileCopyAs honors the ``tag``
# param (a 2-frame tag out of a 3-frame sprite yields a 2-frame gif), and
# ExportSpriteSheet's ``tag`` param limits the sheet to that range. These two
# keep ``ui = false`` — unlike AutocropSprite/ChangePixelFormat they behave
# with it (see transform.py for that gotcha).
_TAGS_LUA = """
local s = app.activeSprite
if not s then error("no active sprite") end
if #s.tags == 0 then error("sprite has no tags — create_tag first, or use export_sprite for the whole animation") end
local used, out = {}, {}
for _, t in ipairs(s.tags) do
  local base = t.name:gsub("[^%w%-_]", "_")
  if base == "" then base = "tag" end
  local name = base
  local n = 2
  while used[name] do name = base .. "_" .. n; n = n + 1 end
  used[name] = true
  local path = app.fs.joinPath(OUT_DIR, name .. "." .. EXT)
  if EXT == "gif" then
    app.command.SaveFileCopyAs{ ui = false, filename = path, tag = t.name }
  else
    app.command.ExportSpriteSheet{ ui = false, type = SpriteSheetType.HORIZONTAL, textureFilename = path, tag = t.name }
  end
  out[#out + 1] = {
    tag = t.name, file = path,
    from = t.fromFrame.frameNumber, to = t.toFrame.frameNumber,
    frames = t.toFrame.frameNumber - t.fromFrame.frameNumber + 1,
  }
end
return J({ exported = out, count = #out })
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
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Export sprite", destructiveHint=False, openWorldHint=True
        )
    )
    def export_sprite(out_path: str, file: str | None = None) -> dict:
        """Export the active sprite to a file; format is chosen by ``out_path``
        extension (.png, .gif, ...). A multi-frame sprite saved to a single-image
        format is split into ``<name>1.ext``, ``<name>2.ext``, ...; a multi-frame
        sprite saved to ``.gif`` becomes one animated GIF (all frames, honoring
        per-frame durations). The returned ``files`` lists what was actually
        written. Does not modify the sprite. Headless: pass ``file``."""
        body = lua_locals(OUT=out_path) + _EXPORT_LUA
        res = run(body, mutates=False, file=file, save=False)
        frames = res.get("frames", 1) if isinstance(res, dict) else 1
        return {
            "requested": out_path,
            "frames": frames,
            "files": _resolve_written(out_path, frames),
        }

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Export spritesheet", destructiveHint=False, openWorldHint=True
        )
    )
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

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Export layers", destructiveHint=False, openWorldHint=True
        )
    )
    def export_layers(out_dir: str, file: str | None = None) -> dict:
        """Export every image layer (recursing into groups) as its own PNG in
        ``out_dir``, named ``<sanitized-layer-name>.png``. Hidden layers are
        exported too; every layer's original visibility is restored afterwards,
        so the document ends exactly as it started. A multi-frame sprite splits
        each layer into ``<name>1.png``, ``<name>2.png``, ...; the returned
        ``files`` lists what was actually written. Headless: pass ``file``."""
        os.makedirs(out_dir, exist_ok=True)
        body = lua_locals(OUT_DIR=out_dir) + _LAYERS_LUA
        res = run(body, mutates=False, file=file, save=False)
        if not isinstance(res, dict):
            raise ToolError("layer export returned no result")
        frames = res.get("frames", 1) or 1
        files: list[str] = []
        for p in res.get("paths") or []:
            files.extend(_resolve_written(p, frames))
        return {"layers": res.get("layers"), "frames": frames, "files": files}

    @mcp.tool(
        annotations=ToolAnnotations(title="Export tags", destructiveHint=False, openWorldHint=True)
    )
    def export_tags(out_dir: str, format: str = "gif", file: str | None = None) -> dict:
        """Export each animation tag's frame range as its own file in
        ``out_dir``: an animated ``<tag-name>.gif`` (format="gif", default) or a
        horizontal ``<tag-name>.png`` strip (format="png"). Errors if the sprite
        has no tags. Returns each tag's file, frame range, and frame count.
        Does not modify the sprite. Headless: pass ``file``."""
        fmt = format.strip().lower().lstrip(".")
        if fmt not in ("gif", "png"):
            raise ToolError(f"bad format '{format}' (gif|png)")
        os.makedirs(out_dir, exist_ok=True)
        body = lua_locals(OUT_DIR=out_dir, EXT=fmt) + _TAGS_LUA
        res = run(body, mutates=False, file=file, save=False)
        if not isinstance(res, dict):
            raise ToolError("tag export returned no result")
        exported = res.get("exported") or []
        for e in exported:
            if isinstance(e, dict) and "file" in e:
                e["exists"] = os.path.isfile(e["file"])
        return {"format": fmt, "count": res.get("count"), "exported": exported}
