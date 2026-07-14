"""Batch tools — process a whole folder of ``.aseprite`` files in one call.

Built for the studio reality (re-export / resize / palette-lock 100+ building
sprites at once). These are inherently disk-file operations, so they always run on
a **headless** backend regardless of the configured backend, and they are
**non-destructive**: every op renders to a separate output file (default `.png`)
and never writes back the source `.aseprite`. Each file is independent; a failure
on one is recorded and the rest continue (continue-on-error).
"""
from __future__ import annotations

import glob
import os

from mcp.types import ToolAnnotations

from ..backends.headless import HeadlessBackend
from ..config import load_config
from ..lua import build_lua, lua_locals
from ._common import ToolError, parse_color
from .palette import PRESETS

# Render frame 1 (optionally integer-upscaled, nearest-neighbor) and save it.
_EXPORT = """
local s = app.activeSprite
if not s then error("no active sprite") end
local img = Image(s.width, s.height, s.colorMode)
img:drawSprite(s, 1)
if SCALE > 1 then
  local big = Image(s.width * SCALE, s.height * SCALE, s.colorMode)
  for y = 0, big.height - 1 do
    for x = 0, big.width - 1 do
      big:drawPixel(x, y, img:getPixel(math.floor(x / SCALE), math.floor(y / SCALE)))
    end
  end
  big:saveAs(OUT)
  return J({ out = OUT, width = big.width, height = big.height })
end
img:saveAs(OUT)
return J({ out = OUT, width = s.width, height = s.height })
"""

# Nearest-neighbor resize of frame 1 (pixel-art friendly). Target is either an
# explicit TW x TH, or derived from SCALE (>0) against the sprite's own size.
_RESIZE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local tw, th = TW, TH
if SCALE > 0 then
  tw = math.max(1, math.floor(s.width * SCALE + 0.5))
  th = math.max(1, math.floor(s.height * SCALE + 0.5))
end
local img = Image(s.width, s.height, s.colorMode)
img:drawSprite(s, 1)
local out = Image(tw, th, s.colorMode)
for y = 0, th - 1 do
  for x = 0, tw - 1 do
    local sx = math.min(s.width - 1, math.floor(x * s.width / tw))
    local sy = math.min(s.height - 1, math.floor(y * s.height / th))
    out:drawPixel(x, y, img:getPixel(sx, sy))
  end
end
out:saveAs(OUT)
return J({ out = OUT, width = tw, height = th })
"""

# Snap frame 1 to COLORS (nearest), keep alpha, save. Source palette is not written.
_APPLY_PAL = """
local s = app.activeSprite
if not s then error("no active sprite") end
local img = Image(s.width, s.height, ColorMode.RGB)
img:drawSprite(s, 1)
local np = #COLORS
local pr, pg, pb = {}, {}, {}
for i = 1, np do pr[i] = COLORS[i][1]; pg[i] = COLORS[i][2]; pb[i] = COLORS[i][3] end
local pc = app.pixelColor
local n = 0
for y = 0, img.height - 1 do
  for x = 0, img.width - 1 do
    local v = img:getPixel(x, y)
    local a = pc.rgbaA(v)
    if a > 0 then
      local r, g, b = pc.rgbaR(v), pc.rgbaG(v), pc.rgbaB(v)
      local bi, bd = 1, 1e18
      for i = 1, np do
        local dr, dg, db = r - pr[i], g - pg[i], b - pb[i]
        local d = dr * dr + dg * dg + db * db
        if d < bd then bd = d; bi = i end
      end
      img:drawPixel(x, y, Color{ r = pr[bi], g = pg[bi], b = pb[bi], a = a }); n = n + 1
    end
  end
end
img:saveAs(OUT)
return J({ out = OUT, colors = np, mapped = n })
"""


def _headless() -> HeadlessBackend:
    cfg = load_config()
    return HeadlessBackend(cfg.aseprite_path, cfg.exec_timeout)


def _list(folder: str, recursive: bool) -> list[str]:
    if not os.path.isdir(folder):
        raise ToolError(f"not a folder: {folder}")
    pat = os.path.join(folder, "**", "*.aseprite") if recursive else os.path.join(folder, "*.aseprite")
    files = sorted(glob.glob(pat, recursive=recursive))
    if not files:
        raise ToolError(f"no .aseprite files found in {folder}")
    return files


def _colors_lua(hex_colors: list[str]) -> str:
    parts = []
    for c in hex_colors:
        r, g, b, a = parse_color(c)
        parts.append(f"{{{r},{g},{b},{a}}}")
    return "local COLORS = {" + ",".join(parts) + "}\n"


def _run_each(files, out_dir, fmt, body_for):
    """Run ``body_for(file, out_path)`` -> (body, out_path) per file, continue on error."""
    backend = _headless()
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        out = os.path.join(out_dir, f"{stem}.{fmt}")
        body = body_for(f, out)
        try:
            res = backend.exec(build_lua(body, mutates=False), file=f, save=False)
            if not res.ok:
                results.append({"file": f, "ok": False, "error": res.error})
            else:
                results.append({"file": f, "ok": True, "out": out, "exists": os.path.isfile(out)})
        except Exception as e:  # pragma: no cover - defensive
            results.append({"file": f, "ok": False, "error": str(e)})
    ok = sum(1 for r in results if r["ok"])
    return {
        "out_dir": out_dir, "processed": len(files),
        "succeeded": ok, "failed": len(files) - ok, "results": results,
    }


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Batch export folder"))
    def batch_export(
        folder: str, out_dir: str | None = None, format: str = "png",
        scale: int = 1, recursive: bool = False, file: str | None = None,
    ) -> dict:
        """Export every ``.aseprite`` in ``folder`` (first frame) to an image, optionally
        integer-upscaled by ``scale``. Non-destructive: writes ``<name>.<format>`` to
        ``out_dir`` (default = ``folder``); never modifies the source. Continues past
        per-file errors. Headless. (``file`` is ignored — this operates on a folder.)"""
        if scale < 1:
            raise ToolError("scale must be >= 1")
        files = _list(folder, recursive)
        out = out_dir or folder
        return _run_each(files, out, format, lambda f, o: lua_locals(OUT=o, SCALE=int(scale)) + _EXPORT)

    @mcp.tool(annotations=ToolAnnotations(title="Batch resize folder"))
    def batch_resize(
        folder: str, out_dir: str | None = None, scale: float | None = None,
        width: int | None = None, height: int | None = None, format: str = "png",
        recursive: bool = False, file: str | None = None,
    ) -> dict:
        """Resize every ``.aseprite`` in ``folder`` (first frame, nearest-neighbor) and
        write images to ``out_dir``. Give either ``scale`` (multiplier) or explicit
        ``width``/``height``. Non-destructive; continues past per-file errors. Headless."""
        if scale is None and not (width and height):
            raise ToolError("give scale, or both width and height")
        files = _list(folder, recursive)
        out = out_dir or folder
        sc = float(scale) if scale is not None else 0.0
        tw, th = (int(width), int(height)) if scale is None else (0, 0)
        return _run_each(files, out, format, lambda f, o: lua_locals(OUT=o, SCALE=sc, TW=tw, TH=th) + _RESIZE)

    @mcp.tool(annotations=ToolAnnotations(title="Batch apply palette"))
    def batch_apply_palette(
        folder: str, out_dir: str | None = None, preset: str | None = None,
        palette: list[str] | None = None, format: str = "png",
        recursive: bool = False, file: str | None = None,
    ) -> dict:
        """Palette-lock every ``.aseprite`` in ``folder``: snap each sprite (first frame,
        alpha preserved) to a palette and export images to ``out_dir``. Give a ``preset``
        (gameboy/pico8/cga) or an explicit ``palette`` list of #rrggbb. Non-destructive;
        continues past per-file errors. Headless."""
        if palette:
            colors = palette
        elif preset:
            key = preset.strip().lower()
            if key not in PRESETS:
                raise ToolError(f"unknown preset '{preset}' (have: {', '.join(sorted(PRESETS))})")
            colors = PRESETS[key]
        else:
            raise ToolError("give a preset or a palette list")
        colors_lua = _colors_lua(colors)
        files = _list(folder, recursive)
        out = out_dir or folder
        return _run_each(files, out, format, lambda f, o: colors_lua + lua_locals(OUT=o) + _APPLY_PAL)
