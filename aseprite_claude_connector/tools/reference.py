"""Working from a reference picture.

- ``pixelate_reference`` — a reference turned into pixel art on a new layer: shrunk
  by area averaging, snapped to a small palette, and cleaned of stray pixels. A
  faithful base to refine, instead of drawing the picture from memory.
- ``compare_to_reference`` — the canvas beside the reference with a heatmap of
  where they differ, scores, and the worst areas, so corrections go where they
  matter.

The reference is read by a batch Aseprite and the image work happens in
``pixelate.py``, so the live editor never opens the file or raises its security
prompt.
"""

from __future__ import annotations

import os

from mcp.types import ToolAnnotations

from ..backends import get_backend
from ..lua import lua_locals
from ..pixelate import compared, cropped, heatmap, median_cut, pixelated, prepared, shrink
from ..raster import Raster, fit_factor, over_background, resized, tiled
from ._common import ToolError, new_pin, parse_color, refuse_in_dry_run, run
from .layers import _IMPORT
from .look import _LOOK, _LOOK_HELPERS, _take, pixels_loader, png_content, read_picture

_MAX_SIDE = 512


def _reference(path: str, crop: tuple | None) -> Raster:
    ref = read_picture(path)
    if crop is None:
        return ref
    try:
        return cropped(ref, *crop)
    except ValueError as e:
        raise ToolError(f"{e} ({ref.width}x{ref.height})") from None


def _crop(x, y, width, height) -> tuple | None:
    given = [v is not None for v in (x, y, width, height)]
    if not any(given):
        return None
    if not all(given):
        raise ToolError("pass all of crop_x, crop_y, crop_width, crop_height, or none")
    if width < 1 or height < 1:
        raise ToolError("the crop must be at least 1x1")
    return (int(x), int(y), int(width), int(height))


def _opaque_colours(pictures: list[Raster]) -> list[tuple[int, int, int]]:
    out = []
    for pic in pictures:
        d = pic.rgba
        out += [tuple(d[i : i + 3]) for i in range(0, len(d), 4) if d[i + 3] >= 128]
    return out


_NEW_POSE = """
local s = Sprite(W, H)
local l = s.layers[1]
l.name = LAYER
s:newCel(l, 1, load_image(), Point(0, 0))
local t = s:newTag(1, 1)
t.name = NAME
if PIN then s.properties.claude_target = PIN end
app.refresh()
return J({ name = NAME, width = W, height = H })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Split a character sheet", openWorldHint=True))
    def split_sheet(
        image_path: str,
        columns: int,
        rows: int,
        width: int,
        height: int | None = None,
        colors: int = 16,
        palette: list[str] | None = None,
        names: list[str] | None = None,
        remove_background: bool = True,
        clear_edges: bool = True,
        dither: str = "none",
        layer_name: str = "Art",
        out_dir: str | None = None,
    ) -> dict:
        """Cut a character sheet (poses in a ``columns`` x ``rows`` grid) into one
        pixel-art sprite per pose, all at the same scale and on ONE shared palette of
        ``colors`` colours (or ``palette``), so the poses stay consistent with each
        other. Each cell is shrunk to ``width`` x ``height`` (the cell's aspect by
        default), its background cleared and the bits of neighbouring poses dropped.
        Each sprite gets a tag named from ``names`` (row by row; "pose_1"... by
        default), so ``pin_sprite(tag=...)`` can pick it. Live: opens the sprites in
        the editor. Headless: writes ``<out_dir>/<name>.aseprite``."""
        if columns < 1 or rows < 1 or columns * rows > 64:
            raise ToolError("columns x rows must be 1..64 cells")
        if not 1 <= width <= _MAX_SIDE:
            raise ToolError(f"width must be 1..{_MAX_SIDE}")
        if names is not None and len(names) != columns * rows:
            raise ToolError(f"give {columns * rows} names, one per cell, or none")
        live = get_backend().name == "live"
        if not live and not out_dir:
            raise ToolError("headless: pass out_dir for the sprite files")
        if out_dir and not os.path.isdir(out_dir):
            raise ToolError(f"no folder at {out_dir}")
        refuse_in_dry_run("split_sheet")
        sheet = read_picture(image_path)
        cw, ch = sheet.width // columns, sheet.height // rows
        if height is None:
            height = max(1, min(_MAX_SIDE, round(width * ch / cw)))
        cells = [
            cropped(sheet, c * cw, r * ch, cw, ch) for r in range(rows) for c in range(columns)
        ]
        small = [prepared(cell, width, height, remove_background) for cell in cells]
        if palette:
            chosen = [parse_color(c)[:3] for c in palette]
        else:
            chosen = median_cut(_opaque_colours(small), colors)
        if not chosen:
            raise ToolError("the sheet is fully transparent")
        made = []
        for n, cell in enumerate(cells):
            name = names[n] if names else f"pose_{n + 1}"
            art = pixelated(
                cell, width, height, chosen, dither, True, remove_background, clear_edges
            )
            body = (
                pixels_loader(art)
                + lua_locals(
                    W=width, H=height, LAYER=layer_name, NAME=name, PIN=new_pin() if live else None
                )
                + _NEW_POSE
            )
            path = os.path.join(out_dir, name + ".aseprite") if out_dir and not live else None
            run(body, file=path, save=bool(path), follow_pin=False)
            made.append({"name": name, **({"file": path} if path else {})})
        return {
            "sprites": made,
            "width": width,
            "height": height,
            "palette": ["#" + bytes(c).hex() for c in chosen],
        }

    @mcp.tool(annotations=ToolAnnotations(title="Pixelate a reference picture"))
    def pixelate_reference(
        image_path: str,
        width: int,
        height: int | None = None,
        colors: int = 16,
        palette: list[str] | None = None,
        dither: str = "none",
        despeckle: bool = True,
        crop_x: int | None = None,
        crop_y: int | None = None,
        crop_width: int | None = None,
        crop_height: int | None = None,
        layer_name: str = "Reference pixels",
        x: int = 0,
        y: int = 0,
        remove_background: bool = False,
        clear_edges: bool = False,
        file: str | None = None,
    ) -> dict:
        """Turn a reference picture into pixel art on a new layer: the faithful way to
        recreate a photo or painting. The picture (or the ``crop_*`` part of it, in
        its own pixels) is shrunk to ``width`` x ``height`` by averaging, so each
        pixel is the true colour of that area. ``height`` defaults to the picture's
        aspect. It is then snapped to ``colors`` colours chosen from the picture, or
        to ``palette`` (#rrggbb list) to match an existing one. ``dither`` is
        ``none``, ``ordered``, or ``diffusion``. ``despeckle`` removes lone noise
        pixels. ``remove_background`` clears a white sheet or flat backdrop (and the
        light fringe it leaves), before the palette is chosen so no colours are spent
        on it. ``clear_edges`` drops bits of neighbouring art a crop catches at its
        edges, keeping the subject and anything floating clear of the edges. To cut
        every pose out of a character sheet at once, use ``split_sheet``. Refine the
        result by hand, and check it with ``compare_to_reference``. One undo step.
        Headless: pass ``file``."""
        if not 1 <= width <= _MAX_SIDE or (height is not None and not 1 <= height <= _MAX_SIDE):
            raise ToolError(f"width and height must be 1..{_MAX_SIDE}")
        if palette is None and not 2 <= colors <= 256:
            raise ToolError("colors must be 2..256")
        ref = _reference(image_path, _crop(crop_x, crop_y, crop_width, crop_height))
        if height is None:
            height = max(1, min(_MAX_SIDE, round(width * ref.height / ref.width)))
        small = prepared(ref, width, height, remove_background)
        if palette:
            chosen = [parse_color(c)[:3] for c in palette]
        else:
            chosen = median_cut(_opaque_colours([small]), colors)
        if not chosen:
            raise ToolError("the picture is fully transparent there")
        try:
            art = pixelated(
                ref, width, height, chosen, dither, despeckle, remove_background, clear_edges
            )
        except ValueError as e:
            raise ToolError(str(e)) from None
        used = sorted({art.rgba[i : i + 3] for i in range(0, len(art.rgba), 4) if art.rgba[i + 3]})
        body = (
            pixels_loader(art)
            + lua_locals(PATH=image_path, NAME=layer_name, PX=int(x), PY=int(y))
            + _IMPORT
        )
        made = run(body, mutates=True, undo_label="Pixelate reference", file=file)
        return {
            **made,
            "source": {"width": ref.width, "height": ref.height},
            "colors": ["#" + c.hex() for c in used],
        }

    @mcp.tool(
        annotations=ToolAnnotations(title="Compare with a reference", readOnlyHint=True),
        structured_output=False,
    )
    def compare_to_reference(
        image_path: str,
        layer: str | None = None,
        frame: int | None = None,
        crop_x: int | None = None,
        crop_y: int | None = None,
        crop_width: int | None = None,
        crop_height: int | None = None,
        grid: int = 4,
        max_size: int = 768,
        file: str | None = None,
    ) -> list:
        """See how close the canvas is to a reference picture. Returns the reference
        shrunk to the canvas size, the canvas, and a heatmap (red = most different)
        side by side, plus scores out of 100: ``score`` per pixel, ``shape_score``
        with fine detail blurred away (composition, values, and colour masses), and
        ``close_pixels`` (% that nearly match). ``worst_areas`` are the cells of a
        ``grid`` x ``grid`` split that differ most, with both average colours and
        whether the art is darker or lighter: fix those first. ``crop_*`` picks the
        part of the reference the canvas shows. ``layer`` compares one layer; clear
        pixels count as black. Headless: pass ``file``."""
        if not 1 <= grid <= 16:
            raise ToolError("grid must be 1..16")
        ref = _reference(image_path, _crop(crop_x, crop_y, crop_width, crop_height))
        opts = lua_locals(
            FRAME=frame,
            LAYER=layer,
            SELECTION=False,
            RX=None,
            RY=None,
            RW=None,
            RH=None,
            SCALE=1,
            MAX_SIZE=_MAX_SIDE * 4,
        )
        res = run(opts + _LOOK_HELPERS + _LOOK, file=file)
        art = _take(res)
        target = shrink(ref, art.width, art.height)
        result = compared(art, target, grid)
        errors = result.pop("errors")
        k = fit_factor(3 * art.width, art.height, None, max_size)
        panels = [
            over_background(resized(p, k), (0, 0, 0)) for p in (target, art, heatmap(art, errors))
        ]
        stretch = (ref.width / ref.height) / (art.width / art.height)
        meta = {
            "panels": ["reference", "canvas", "difference"],
            "frame": res["frame"],
            "layer": res["layer"],
            "scale": k,
            **result,
        }
        if abs(stretch - 1) > 0.05:
            meta["note"] = (
                f"the reference is {ref.width}x{ref.height} and the canvas "
                f"{art.width}x{art.height}, so it was stretched to fit; crop it to match"
            )
        return png_content(tiled(panels, 3), meta)
