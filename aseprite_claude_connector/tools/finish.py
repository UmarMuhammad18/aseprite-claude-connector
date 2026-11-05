"""Finishing touches.

- ``export_animation`` — a GIF or animated PNG at a whole-number scale, written from
  Python, so the live editor never raises its security prompt.
- ``clean_lines`` — sketched strokes thinned to clean one-pixel lines.
"""

from __future__ import annotations

import os

from mcp.types import ToolAnnotations

from ..lines import clean_lines as cleaned_lines
from ..lua import lua_locals
from ..raster import encode_apng, encode_gif, over_background, resized
from ._common import ToolError, parse_color, refuse_in_dry_run, run
from .look import frames_of, pixels_loader
from .scene import _FIND, _read, _strip, _target

_WRITE_FRAMES = """
local done, i = {}, 0
for n in FRAMES:gmatch("%d+") do
  n = tonumber(n)
  s:newCel(layer, n, Image(strip, Rectangle(i * W, 0, W, H)), Point(0, 0))
  done[#done + 1] = n
  i = i + 1
end
return J({ layer = layer.name, frames = done })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Export an animation", destructiveHint=False))
    def export_animation(
        path: str,
        scale: int = 1,
        tag: str | None = None,
        background: str | None = None,
        file: str | None = None,
    ) -> dict:
        """Write the animation (or one ``tag``) as a looping ``.gif`` or animated
        ``.png`` at ``path``, scaled up ``scale`` times with sharp pixels (4 turns a
        384x128 banner into 1536x512). Each frame keeps its own duration. An animated
        PNG keeps transparency; a GIF is laid on ``background`` (#rrggbb, black by
        default), as are both when it's given. Written from Python, so the live
        editor shows no security prompt. Headless: pass ``file``."""
        refuse_in_dry_run("export_animation")
        kind = os.path.splitext(path)[1].lower()
        if kind not in (".gif", ".png"):
            raise ToolError("path must end in .gif or .png (an animated PNG)")
        if not 1 <= scale <= 16:
            raise ToolError("scale must be 1..16")
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            raise ToolError(f"no folder at {folder}")
        grabbed = frames_of(tag=tag, file=file)
        frames = [resized(f, scale) for f in grabbed["frames"]]
        if background is not None or kind == ".gif":
            bg = parse_color(background or "#000000")[:3]
            frames = [over_background(f, bg) for f in frames]
        durations = [int(ms) for ms in grabbed["durations"]]
        data = encode_gif(frames, durations) if kind == ".gif" else encode_apng(frames, durations)
        with open(path, "wb") as f:
            f.write(data)
        return {
            "path": path,
            "frames": len(frames),
            "width": frames[0].width,
            "height": frames[0].height,
            "duration_ms": sum(durations),
            "bytes": len(data),
        }

    @mcp.tool(annotations=ToolAnnotations(title="Clean up sketched lines"))
    def clean_lines(
        layer: str | None = None,
        thin: bool = True,
        specks: bool = False,
        all_frames: bool = False,
        frame: int | None = None,
        file: str | None = None,
    ) -> dict:
        """Turn rough sketched strokes into clean pixel-art lines: ``thin`` brings
        thick strokes down to one pixel, and the doubled corner pixels freehand lines
        leave are removed, as Aseprite's pixel-perfect brush would have drawn them.
        ``specks`` also clears pixels with no neighbour. Kept pixels keep their
        colour. Use it on a line-art layer over transparency (``layer``, the active
        one by default); one frame, or ``all_frames``. One undo step. Headless: pass
        ``file``."""
        layer, active = _target(layer, file)
        count = run("return #app.activeSprite.frames", file=file) if all_frames else None
        numbers = list(range(1, int(count) + 1)) if all_frames else [frame or active]
        results, totals = [], {"thinned_pixels": 0, "corner_pixels": 0, "lone_pixels": 0}
        for n in numbers:
            src, _ = _read(layer, n, file)
            out, info = cleaned_lines(src, thin, specks)
            results.append(out)
            for k in totals:
                totals[k] += info[k]
        body = (
            pixels_loader(_strip(results))
            + lua_locals(
                LAYER=layer,
                W=results[0].width,
                H=results[0].height,
                FRAMES=",".join(str(n) for n in numbers),
            )
            + _FIND
            + _WRITE_FRAMES
        )
        made = run(body, mutates=True, undo_label="Clean lines", file=file)
        return {**made, **totals}
