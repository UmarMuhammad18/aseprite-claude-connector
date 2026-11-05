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

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ..pixelate import compared, cropped, despeckled, heatmap, median_cut, quantized, shrink
from ..raster import Raster, fit_factor, over_background, resized, tiled
from ._common import ToolError, parse_color, run
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


def register(mcp):
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
        file: str | None = None,
    ) -> dict:
        """Turn a reference picture into pixel art on a new layer: the faithful way to
        recreate a photo or painting. The picture (or the ``crop_*`` part of it, in
        its own pixels) is shrunk to ``width`` x ``height`` by averaging, so each
        pixel is the true colour of that area. ``height`` defaults to the picture's
        aspect. It is then snapped to ``colors`` colours chosen from the picture, or
        to ``palette`` (#rrggbb list) to match an existing one. ``dither`` is
        ``none``, ``ordered``, or ``diffusion``. ``despeckle`` removes lone noise
        pixels. Refine the result by hand, and check it with
        ``compare_to_reference``. One undo step. Headless: pass ``file``."""
        if not 1 <= width <= _MAX_SIDE or (height is not None and not 1 <= height <= _MAX_SIDE):
            raise ToolError(f"width and height must be 1..{_MAX_SIDE}")
        if palette is None and not 2 <= colors <= 256:
            raise ToolError("colors must be 2..256")
        ref = _reference(image_path, _crop(crop_x, crop_y, crop_width, crop_height))
        if height is None:
            height = max(1, min(_MAX_SIDE, round(width * ref.height / ref.width)))
        small = shrink(ref, width, height)
        if palette:
            chosen = [parse_color(c)[:3] for c in palette]
        else:
            data = small.rgba
            seen = [tuple(data[i : i + 3]) for i in range(0, len(data), 4) if data[i + 3] >= 128]
            chosen = median_cut(seen, colors)
        if not chosen:
            raise ToolError("the picture is fully transparent there")
        try:
            art = quantized(small, chosen, dither)
        except ValueError as e:
            raise ToolError(str(e)) from None
        if despeckle:
            art = despeckled(art)
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
