"""Tiles for game maps.

- ``make_seamless`` — makes a texture layer repeat with no visible edge.
- ``make_autotiles`` — builds the 47-tile edge-and-corner set for one terrain over
  another and writes what Godot or Unity needs to paint maps with it: a TileSet with
  terrain, or a sliced sheet and a Rule Tile.

Files are written from Python, so the live editor never raises its security prompt.
See ``tiles.py`` for the image work.
"""

from __future__ import annotations

import json
import os

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ..raster import encode_png, fit_factor, over_background, resized
from ..tiles import autotiles, godot_tileset, seamless, unity_rule_tile
from ._common import ToolError, refuse_in_dry_run, run
from .game_export import _recall, _remember, engine_at, locate
from .look import pixels_loader, png_content
from .scene import _FIND, _read, _target
from .unity_export import _assemble_meta, _guid_for, _sprite_entry, _sprite_id, _yaml_scalar

_COLUMNS = 8

_PUT = """
s:newCel(layer, FRAME, strip, Point(0, 0))
return J({ layer = layer.name, frame = FRAME, width = strip.width, height = strip.height })
"""

_NATIVE_META = """fileFormatVersion: 2
guid: __GUID__
NativeFormatImporter:
  externalObjects: {}
  mainObjectFileID: 11400000
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def _project_root(folder: str) -> str | None:
    root = os.path.abspath(folder)
    while not engine_at(root):
        if os.path.dirname(root) == root:
            return None
        root = os.path.dirname(root)
    return root


def _write(path: str, data: bytes | str) -> None:
    mode, kw = (
        ("wb", {}) if isinstance(data, bytes) else ("w", {"encoding": "utf-8", "newline": "\n"})
    )
    with open(path, mode, **kw) as f:
        f.write(data)


def _unity_files(folder: str, name: str, png: str, size: int, masks: list[int], rows: int) -> dict:
    meta_path = png + ".meta"
    guid = _guid_for(meta_path)
    sprites, idname, ids = [], [], []
    for n in range(len(masks)):
        tile = f"{name}_{n}"
        iid = 21300000 + n * 2
        x, y = (n % _COLUMNS) * size, (rows - 1 - n // _COLUMNS) * size  # Unity rows run up
        sprites.append(_sprite_entry(tile, x, y, size, size, _sprite_id(guid, n), iid, 0.5, 0.5, 0))
        idname.append(f"  - first:\n      213: {iid}\n    second: {_yaml_scalar(tile)}\n")
        ids.append(iid)
    _write(meta_path, _assemble_meta(guid, size, sprites, idname))
    rule = os.path.join(folder, f"{name}_rule.asset")
    _write(rule, unity_rule_tile(f"{name}_rule", guid, ids, masks))
    rule_meta = rule + ".meta"
    _write(rule_meta, _NATIVE_META.replace("__GUID__", _guid_for(rule_meta)))
    return {"meta": meta_path, "rule_tile": rule}


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Make a texture seamless"))
    def make_seamless(
        layer: str | None = None,
        band: int | None = None,
        patch: int = 6,
        frame: int | None = None,
        seed: int = 1,
        file: str | None = None,
    ) -> dict:
        """Make a texture repeat with no visible edge, for ground, walls, or water
        tiles. The layer (the active one by default) fills the canvas: it is shifted
        by half so its old edges meet in the middle, and that cross, ``band`` pixels
        wide (an eighth of the size by default), is rebuilt from ``patch``-sized
        pieces of the texture itself. Check it with ``look`` after
        ``expand_canvas`` or by exporting a few side by side. One undo step.
        Headless: pass ``file``."""
        if band is not None and band < 1:
            raise ToolError("band must be at least 1")
        layer, active = _target(layer, file)
        src, frame = _read(layer, frame or active, file)
        if min(src.width, src.height) < 8:
            raise ToolError("the canvas must be at least 8x8")
        out = seamless(src, band, patch, seed)
        body = pixels_loader(out) + lua_locals(LAYER=layer, FRAME=frame) + _FIND + _PUT
        return run(body, mutates=True, undo_label="Make seamless", file=file)

    @mcp.tool(
        annotations=ToolAnnotations(title="Make an autotile set", destructiveHint=False),
        structured_output=False,
    )
    def make_autotiles(
        fill_layer: str,
        size: int,
        name: str,
        base_layer: str | None = None,
        edge: int | None = None,
        outline: bool = True,
        game_dir: str | None = None,
        out_dir: str | None = None,
        frame: int = 1,
        file: str | None = None,
    ) -> list:
        """Build the 47-tile autotile set for one terrain (``fill_layer``, like
        grass) over another (``base_layer``, like dirt, or clear), so a map painter
        picks the right edge and corner for every neighbour. Both textures come from
        the top-left ``size`` square of their layer, so ``make_seamless`` them first.
        ``edge`` is how far the fill stops from an open side, and ``outline`` gives
        its border a darker shade of its own colours.
        Writes ``name``.png. With ``game_dir`` (or the remembered game folder, if
        ``out_dir`` isn't given), a Godot project also gets ``name``.tres, a TileSet
        whose terrain paints the set, and a Unity project gets the sheet sliced into
        tiles plus ``name``_rule.asset, a Rule Tile (needs the 2D Tilemap Extras
        package). ``out_dir`` writes the PNG and a JSON map of each tile's
        neighbours. Returns a picture of the set. Headless: pass ``file``."""
        refuse_in_dry_run("make_autotiles")
        if not 4 <= size <= 256:
            raise ToolError("size must be 4..256")
        if not name or any(c in name for c in '\\/:*?"<>|'):
            raise ToolError(f"'{name}' can't be used as a file name")
        if edge is not None and not 0 <= edge < size // 2:
            raise ToolError("edge must be 0 to half the tile size")
        fill, _ = _read(fill_layer, frame, file)
        if fill.width < size or fill.height < size:
            raise ToolError(f"the canvas is smaller than a {size}x{size} tile")
        base = _read(base_layer, frame, file)[0] if base_layer else None
        sheet, masks = autotiles(fill, size, base, edge, outline, _COLUMNS)
        if out_dir:
            if not os.path.isdir(out_dir):
                raise ToolError(f"no folder at {out_dir}")
            engine, folder = "folder", out_dir
        else:
            target = game_dir or _recall()
            if not target:
                raise ToolError("pass game_dir (your Godot or Unity project) or out_dir")
            engine, folder = locate(target)
            os.makedirs(folder, exist_ok=True)
            if game_dir:
                _remember(os.path.abspath(game_dir))
        png = os.path.join(folder, f"{name}.png")
        _write(png, encode_png(sheet))
        result = {"engine": engine, "png": png, "tiles": len(masks), "tile_size": size}
        rows = sheet.height // size
        if engine == "godot":
            root = _project_root(folder)
            res = "res://" + os.path.relpath(png, root).replace(os.sep, "/")
            tres = os.path.join(folder, f"{name}.tres")
            _write(tres, godot_tileset(res, size, masks, _COLUMNS, name))
            result["tileset"] = tres
            result["next_step"] = (
                "In Godot, give a TileMapLayer this TileSet, open the TileMap panel's "
                "Terrains tab, and paint with the terrain."
            )
        elif engine == "unity":
            result.update(_unity_files(folder, name, png, size, masks, rows))
            result["next_step"] = (
                "In Unity, drag the Rule Tile into a Tile Palette and paint. It needs the "
                "2D Tilemap Extras package."
            )
        else:
            mapped = os.path.join(folder, f"{name}.json")
            tiles_json = [
                {
                    "index": n,
                    "x": (n % _COLUMNS) * size,
                    "y": (n // _COLUMNS) * size,
                    "neighbours": m,
                }
                for n, m in enumerate(masks)
            ]
            _write(
                mapped,
                json.dumps(
                    {
                        "tile_size": size,
                        "bits": "N1 NE2 E4 SE8 S16 SW32 W64 NW128",
                        "tiles": tiles_json,
                    },
                    indent=1,
                ),
            )
            result["map"] = mapped
        k = fit_factor(sheet.width, sheet.height, None, 768)
        return png_content(over_background(resized(sheet, k), "checker"), {**result, "scale": k})
