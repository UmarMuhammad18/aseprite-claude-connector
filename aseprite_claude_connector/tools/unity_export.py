"""Unity export — the flagship differentiator (the genuine white space).

No other Aseprite MCP regenerates Unity sprite metadata. ``export_unity_sprite``
exports a horizontal sprite sheet AND writes the Unity ``.meta`` beside it, with
the sheet pre-sliced into named Multiple-mode sprites (one per frame) — in a
single action. The sheet drops into a Unity project already sliced; no manual
Sprite Editor pass.

The .meta targets Unity 2021.3+/6 texture import. Rects, pivots, names and IDs are
generated deterministically here; Unity finalizes the asset on import. Exporting
again keeps the ``guid`` already in the ``.meta``, because prefabs and scenes point at
the sprite through it. Final in-Unity validation is a project-side step.
"""

from __future__ import annotations

import os
import re
import uuid

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from . import state
from ._common import ToolError, run
from ._schemas import UnityExport

# Unity SpriteAlignment code + canonical pivot (x, y from bottom-left, 0..1).
_ALIGN = {
    "center": (0, 0.5, 0.5),
    "top_left": (1, 0.0, 1.0),
    "top": (2, 0.5, 1.0),
    "top_right": (3, 1.0, 1.0),
    "left": (4, 0.0, 0.5),
    "right": (5, 1.0, 0.5),
    "bottom_left": (6, 0.0, 0.0),
    "bottom": (7, 0.5, 0.0),
    "bottom_right": (8, 1.0, 0.0),
    "custom": (9, 0.5, 0.5),
}

# Horizontal strip with no trim/padding => frame i occupies rect (i*w, 0, w, h),
# which makes the Unity rects exact and predictable.
_EXPORT_STRIP = """
local s = app.activeSprite
if not s then error("no active sprite") end
app.command.ExportSpriteSheet{
  ui = false,
  type = SpriteSheetType.HORIZONTAL,
  textureFilename = OUT,
  trim = false,
  borderPadding = 0,
  shapePadding = 0,
  innerPadding = 0,
}
return J({ frames = #s.frames, width = s.width, height = s.height })
"""

# Composite frame 1 to a single PNG and report every slice's rect + a Unity-space
# pivot (Aseprite pivots are top-left px within the slice; Unity wants 0..1 from
# the bottom-left, so y is flipped here).
_EXPORT_SLICES = """
local s = app.activeSprite
if not s then error("no active sprite") end
if #s.slices == 0 then error("sprite has no slices; create slices first (create_slice)") end
local img = Image(s.width, s.height, s.colorMode)
img:drawSprite(s, 1)
img:saveAs(OUT)
local out = {}
for i, sl in ipairs(s.slices) do
  local b = sl.bounds
  local px, py = 0.5, 0.5
  if sl.pivot then
    px = (b.width > 0) and (sl.pivot.x / b.width) or 0.5
    py = (b.height > 0) and (1 - sl.pivot.y / b.height) or 0.5
  end
  out[i] = { name = sl.name, x = b.x, y = b.y, width = b.width, height = b.height, px = px, py = py }
end
return J({ height = s.height, width = s.width, slices = out })
"""

# Token substitution (not str.format) so the literal YAML braces stay intact.
_META_TEMPLATE = """fileFormatVersion: 2
guid: __GUID__
TextureImporter:
  internalIDToNameTable:
__IDNAME__  externalObjects: {}
  serializedVersion: 12
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 1
    linearTexture: 0
    fadeOut: 0
    borderMipMap: 0
    mipMapsPreserveCoverage: 0
    alphaTestReferenceValue: 0.5
    mipMapFadeDistanceStart: 1
    mipMapFadeDistanceEnd: 3
  bumpmap:
    convertToNormalMap: 0
    externalNormalMap: 0
    heightScale: 0.25
    normalMapFilter: 0
  isReadable: 0
  streamingMipmaps: 0
  streamingMipmapsPriority: 0
  grayScaleToAlpha: 0
  generateCubemap: 6
  cubemapConvolution: 0
  seamlessCubemap: 0
  textureFormat: 1
  maxTextureSize: 2048
  textureSettings:
    serializedVersion: 2
    filterMode: 0
    aniso: 1
    mipBias: 0
    wrapU: 1
    wrapV: 1
    wrapW: 0
  nPOTScale: 0
  lightmap: 0
  compressionQuality: 50
  spriteMode: 2
  spriteExtrude: 1
  spriteMeshType: 1
  alignment: 0
  spritePivot: {x: 0.5, y: 0.5}
  spritePixelsToUnits: __PPU__
  spriteBorder: {x: 0, y: 0, z: 0, w: 0}
  spriteGenerateFallbackPhysicsShape: 1
  alphaUsage: 1
  alphaIsTransparency: 1
  spriteTessellationDetail: -1
  textureType: 8
  textureShape: 1
  singleChannelComponent: 0
  maxTextureSizeSet: 0
  compressionQualitySet: 0
  textureFormatSet: 0
  ignorePngGamma: 0
  applyGammaDecoding: 0
  platformSettings:
  - serializedVersion: 3
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 2048
    resizeAlgorithm: 0
    textureFormat: -1
    textureCompression: 1
    compressionQuality: 50
    crunchedCompression: 0
    allowsAlphaSplitting: 0
    overridden: 0
    androidETC2FallbackOverride: 0
    forceMaximumCompressionQuality_BC6H_BC7: 0
  spriteSheet:
    serializedVersion: 2
    sprites:
__SPRITES__    outline: []
    physicsShape: []
    bones: []
    spriteID:
    internalID: 0
    vertices: []
    indices:
    edges: []
    weights: []
    secondaryTextures: []
  spritePackingTag:
  pixelsPerUnit: __PPU__
  mipBias: 0
  userData:
  assetBundleName:
  assetBundleVariant:
"""


# A plain YAML scalar we can emit unquoted; anything else (colons, leading -/#,
# trailing space, quotes) gets a double-quoted, escaped scalar so the .meta stays
# valid YAML for user-supplied slice names.
_YAML_SAFE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ .-]*$")


def _yaml_scalar(s: str) -> str:
    s = str(s)
    if s and _YAML_SAFE.match(s) and not s.endswith(" "):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _guid_for(meta_path: str) -> str:
    """The guid already in ``meta_path``, or a new one for a first export."""
    try:
        with open(meta_path, encoding="utf-8") as f:
            found = re.search(r"^guid: ([0-9a-f]{32})\s*$", f.read(), re.MULTILINE)
    except OSError:
        found = None
    return found.group(1) if found else uuid.uuid4().hex


def _sprite_id(guid: str, index: int) -> str:
    return f"{guid[:24]}{index:08x}"


def _sprite_entry(
    name: str,
    x: int,
    y: int,
    w: int,
    h: int,
    sid: str,
    iid: int,
    px: float,
    py: float,
    alignment: int = 9,
) -> str:
    return (
        "    - serializedVersion: 2\n"
        f"      name: {_yaml_scalar(name)}\n"
        "      rect:\n"
        "        serializedVersion: 2\n"
        f"        x: {x}\n"
        f"        y: {y}\n"
        f"        width: {w}\n"
        f"        height: {h}\n"
        f"      alignment: {alignment}\n"
        f"      pivot: {{x: {px}, y: {py}}}\n"
        "      border: {x: 0, y: 0, z: 0, w: 0}\n"
        "      outline: []\n"
        "      physicsShape: []\n"
        "      tessellationDetail: 0\n"
        "      bones: []\n"
        f"      spriteID: {sid}\n"
        f"      internalID: {iid}\n"
        "      vertices: []\n"
        "      indices: \n"
        "      edges: []\n"
        "      weights: []\n"
    )


def _assemble_meta(guid: str, ppu: int, sprites: list[str], idname: list[str]) -> str:
    return (
        _META_TEMPLATE.replace("__GUID__", guid)
        .replace("__PPU__", str(ppu))
        .replace("__SPRITES__", "".join(sprites))
        .replace("__IDNAME__", "".join(idname))
    )


def _gen_meta(
    guid: str,
    ppu: int,
    frames: int,
    w: int,
    h: int,
    stem: str,
    px: float,
    py: float,
    alignment: int = 9,
):
    sprites, idname, rects = [], [], []
    for i in range(frames):
        name = f"{stem}_{i}"
        sid = _sprite_id(guid, i)
        iid = 21300000 + i * 2
        x = i * w
        sprites.append(_sprite_entry(name, x, 0, w, h, sid, iid, px, py, alignment))
        idname.append(f"  - first:\n      213: {iid}\n    second: {_yaml_scalar(name)}\n")
        rects.append({"name": name, "x": x, "y": 0, "width": w, "height": h})
    return _assemble_meta(guid, ppu, sprites, idname), rects


def _gen_meta_slices(guid: str, ppu: int, slices: list, tex_h: int):
    """One Unity sprite per Aseprite slice, y-flipped into Unity texture space,
    each carrying its slice's pivot (alignment = Custom)."""
    sprites, idname, rects = [], [], []
    for i, sl in enumerate(slices):
        name = str(sl["name"])
        sid = _sprite_id(guid, i)
        iid = 21300000 + i * 2
        x, w, h = int(sl["x"]), int(sl["width"]), int(sl["height"])
        uy = tex_h - (int(sl["y"]) + h)  # Aseprite top-left -> Unity bottom-left
        px, py = float(sl["px"]), float(sl["py"])
        sprites.append(_sprite_entry(name, x, uy, w, h, sid, iid, px, py, 9))
        idname.append(f"  - first:\n      213: {iid}\n    second: {_yaml_scalar(name)}\n")
        rects.append({"name": name, "x": x, "y": uy, "width": w, "height": h, "pivot": [px, py]})
    return _assemble_meta(guid, ppu, sprites, idname), rects


def export_sheet(
    png_path: str,
    pixels_per_unit: int = 100,
    alignment: str = "custom",
    pivot_x: float = 0.5,
    pivot_y: float = 0.5,
    file: str | None = None,
) -> dict:
    """Write the sheet and its pre-sliced ``.meta``."""
    align = _ALIGN.get(alignment.strip().lower())
    if not align:
        raise ToolError(f"unknown alignment '{alignment}' (have: {', '.join(sorted(_ALIGN))})")
    code, apx, apy = align
    px, py = (pivot_x, pivot_y) if code == 9 else (apx, apy)
    info = run(lua_locals(OUT=png_path) + _EXPORT_STRIP, mutates=False, file=file, save=False)
    if not isinstance(info, dict):
        raise ToolError("sprite sheet export failed")
    frames, w, h = int(info["frames"]), int(info["width"]), int(info["height"])
    stem = os.path.splitext(os.path.basename(png_path))[0]
    meta_path = png_path + ".meta"
    guid = _guid_for(meta_path)
    meta, rects = _gen_meta(guid, pixels_per_unit, frames, w, h, stem, px, py, code)
    with open(meta_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(meta)
    result = {
        "mode": "frames",
        "png": png_path,
        "png_exists": os.path.isfile(png_path),
        "meta": meta_path,
        "guid": guid,
        "frames": frames,
        "frame_size": {"width": w, "height": h},
        "sheet_size": {"width": w * frames, "height": h},
        "pixels_per_unit": pixels_per_unit,
        "alignment": alignment.strip().lower(),
        "sprites": rects,
    }
    state.set_last("export", result)
    return result


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Export Unity sprite", destructiveHint=False))
    def export_unity_sprite(
        png_path: str,
        pixels_per_unit: int = 100,
        alignment: str = "custom",
        pivot_x: float = 0.5,
        pivot_y: float = 0.5,
        file: str | None = None,
    ) -> UnityExport:
        """Export a horizontal sprite sheet AND write the Unity ``.meta`` beside it,
        pre-sliced into named Multiple-mode sprites (one per frame) — one action, no
        manual Sprite Editor pass. ``alignment`` is one of center, top_left, top,
        top_right, left, right, bottom_left, bottom, bottom_right, custom; ``custom``
        uses ``pivot_x``/``pivot_y`` (0..1, 0,0 = bottom left). Targets Unity 2021.3+/6.
        Headless: pass ``file``."""
        if not png_path.lower().endswith(".png"):
            raise ToolError("png_path must end in .png")
        return export_sheet(png_path, pixels_per_unit, alignment, pivot_x, pivot_y, file)

    @mcp.tool(annotations=ToolAnnotations(title="Export Unity slices", destructiveHint=False))
    def export_unity_slices(
        png_path: str, pixels_per_unit: int = 100, file: str | None = None
    ) -> UnityExport:
        """Export the sprite as a single PNG AND write a Unity ``.meta`` with one
        Multiple-mode sprite **per named slice**, each carrying that slice's pivot —
        so an atlas laid out with slices imports into Unity already sliced *and*
        pivoted. No competitor's Aseprite→Unity path exports pivots. Requires slices
        (see create_slice / set_slice_pivot). Headless: pass ``file``."""
        if not png_path.lower().endswith(".png"):
            raise ToolError("png_path must end in .png")
        info = run(lua_locals(OUT=png_path) + _EXPORT_SLICES, mutates=False, file=file, save=False)
        if not isinstance(info, dict):
            raise ToolError("slice export failed")
        tex_w, tex_h = int(info["width"]), int(info["height"])
        slices = info.get("slices") or []
        if not slices:
            raise ToolError("sprite has no slices to export")
        meta_path = png_path + ".meta"
        guid = _guid_for(meta_path)
        meta, rects = _gen_meta_slices(guid, pixels_per_unit, slices, tex_h)
        with open(meta_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(meta)
        result = {
            "mode": "slices",
            "png": png_path,
            "png_exists": os.path.isfile(png_path),
            "meta": meta_path,
            "guid": guid,
            "texture_size": {"width": tex_w, "height": tex_h},
            "pixels_per_unit": pixels_per_unit,
            "sprites": rects,
        }
        state.set_last("export", result)
        return result
