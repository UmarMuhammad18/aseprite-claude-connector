"""GameMaker strips and multi-sprite atlases.

``export_gamemaker`` relies on GameMaker's own naming rule: importing a PNG called
``name_stripN`` cuts it into N frames. ``pack_atlas`` packs several sprites into one
texture, with JSON in the same hash layout as Aseprite's sprite-sheet export. Both
build their files in Python, so neither raises Aseprite's script-security prompt.
"""

from __future__ import annotations

import json
import math
import os
import re
from statistics import median

from mcp.types import ToolAnnotations

from ..backends import HeadlessBackend
from ..config import load_config
from ..raster import Raster, blit, encode_png, strip
from ._common import ToolError, rails
from .game_export import sprite_name
from .look import frames_of


def gamemaker_strips(stem: str, durations: list[int], tags: list[dict]) -> list[dict]:
    """One strip per tag, or one for the whole sprite. GameMaker gives a sprite a single
    speed, so uneven timing flattens to the middle frame time."""
    spans = [(t["name"], t["from"], t["to"]) for t in tags] or [("", 1, len(durations))]
    out, used = [], set()
    for tag, first, last in spans:
        safe = re.sub(r"\W+", "_", tag).strip("_")
        base = f"{stem}_{safe}" if safe else stem
        n = 2
        while base in used:
            base = f"{stem}_{safe}_{n}"
            n += 1
        used.add(base)
        count = last - first + 1
        times = durations[first - 1 : last]
        out.append(
            {
                "file": f"{base}_strip{count}.png",
                "first": first,
                "last": last,
                "frames": count,
                "fps": round(1000 / median(times), 2),
                "even_timing": len(set(times)) == 1,
            }
        )
    return out


def pack_shelves(sizes: list[tuple[int, int]], padding: int) -> tuple[int, int, list]:
    """Place rectangles in rows, tallest first, aiming for a square. Returns the atlas
    width and height, and each rectangle's (x, y) in the order given."""
    area = sum((w + padding) * (h + padding) for w, h in sizes)
    target = max(max(w for w, _ in sizes), math.ceil(math.sqrt(area)))
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0]))
    places: list[tuple[int, int]] = [(0, 0)] * len(sizes)
    x, y, row, width = 0, 0, 0, 0
    for i in order:
        w, h = sizes[i]
        if x and x + w > target:
            x, y, row = 0, y + row + padding, 0
        places[i] = (x, y)
        width = max(width, x + w)
        row = max(row, h)
        x += w + padding
    return width, y + row, places


def build_atlas(sheets: list[dict], image_name: str, padding: int) -> tuple[Raster, dict]:
    """Pack ``{"name", "frames", "durations", "tags"}`` entries. A frame that repeats
    exactly shares its pixels with the first copy."""
    unique: dict[bytes, int] = {}
    pictures: list[Raster] = []
    rows = []
    for sheet in sheets:
        for n, (frame, ms) in enumerate(zip(sheet["frames"], sheet["durations"], strict=False)):
            key = frame.rgba + bytes((frame.width & 255, frame.height & 255))
            if key not in unique:
                unique[key] = len(pictures)
                pictures.append(frame)
            rows.append((f"{sheet['name']} {n}", unique[key], ms))
    width, height, places = pack_shelves([(p.width, p.height) for p in pictures], padding)
    canvas = bytearray(width * height * 4)
    for picture, (x, y) in zip(pictures, places, strict=False):
        blit(canvas, width, picture, x, y)
    frames = {}
    for key, index, ms in rows:
        p, (x, y) = pictures[index], places[index]
        frames[key] = {
            "frame": {"x": x, "y": y, "w": p.width, "h": p.height},
            "sourceSize": {"w": p.width, "h": p.height},
            "duration": ms,
        }
    tags = [
        {
            "name": f"{s['name']}/{t['name']}",
            "from": t["from"] - 1,
            "to": t["to"] - 1,
            "sprite": s["name"],
        }
        for s in sheets
        for t in s["tags"]
    ]
    meta = {
        "image": image_name,
        "format": "RGBA8888",
        "size": {"w": width, "h": height},
        "scale": "1",
        "frameTags": tags,
    }
    return Raster(width, height, bytes(canvas)), {"frames": frames, "meta": meta}


def read_sprite(sprite: str) -> dict:
    """Frames of a sprite, preferring the open copy so unsaved edits are packed. Live, a
    closed file is read by a batch Aseprite: loading it in the editor would raise the
    script-security prompt. A timeout stays an error, so old pixels never pass for new."""
    cfg = load_config()
    if cfg.backend == "headless":
        return frames_of(file=sprite)
    try:
        return frames_of(pick=sprite)
    except ToolError as e:
        if "no open sprite" not in str(e) or not os.path.isfile(sprite):
            raise
    return frames_of(file=sprite, backend=HeadlessBackend(cfg.aseprite_path, cfg.exec_timeout))


def _refuse_rehearsal(what: str) -> None:
    if rails.capturing:
        raise ToolError(f"{what} writes files, so it can't be batched")
    if rails.dry_run:
        raise ToolError(f"dry run: {what} writes files, so it was not run.")


def register(mcp):
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Export to GameMaker", destructiveHint=False, openWorldHint=True
        )
    )
    def export_gamemaker(output_dir: str, name: str | None = None, file: str | None = None) -> dict:
        """Write sprite strips GameMaker cuts up by itself: one
        ``<name>_<tag>_stripN.png`` per tag, or ``<name>_stripN.png`` with no tags. Drag
        them into GameMaker, or import them in its sprite editor. GameMaker gives a sprite
        one speed, so the result lists each strip's ``fps`` to enter there, and flags
        uneven timing. Headless: pass ``file``."""
        _refuse_rehearsal("export_gamemaker")
        grabbed = frames_of(file=file)
        stem = sprite_name(grabbed["name"], name)
        os.makedirs(output_dir, exist_ok=True)
        strips = gamemaker_strips(stem, grabbed["durations"], grabbed["tags"])
        for item in strips:
            chosen = grabbed["frames"][item["first"] - 1 : item["last"]]
            item["path"] = os.path.join(output_dir, item["file"])
            with open(item["path"], "wb") as f:
                f.write(encode_png(strip(chosen)))
        return {"strips": strips, "frame_size": grabbed["size"]}

    @mcp.tool(
        annotations=ToolAnnotations(title="Pack atlas", destructiveHint=False, openWorldHint=True)
    )
    def pack_atlas(
        sprites: list[str], out_png: str, out_json: str | None = None, padding: int = 1
    ) -> dict:
        """Pack several sprites into one texture, with every frame of each, plus a JSON
        map in the hash layout of Aseprite's sprite-sheet export. Frames that repeat
        exactly share pixels. ``sprites`` are files on disk or, live, the file names of
        open sprites; unsaved sprites can't be named. The JSON goes beside the PNG unless
        ``out_json`` says otherwise, and frames are keyed ``<sprite> <index>``."""
        _refuse_rehearsal("pack_atlas")
        if len(sprites) < 2:
            raise ToolError("sprites needs at least two entries")
        if not 0 <= padding <= 64:
            raise ToolError("padding must be 0..64")
        sheets = []
        seen: dict[str, int] = {}
        for sprite in sprites:
            grabbed = read_sprite(sprite)
            stem = sprite_name(grabbed["name"] or sprite, None)
            seen[stem] = seen.get(stem, 0) + 1
            if seen[stem] > 1:
                raise ToolError(f"two sprites are named '{stem}', so their frames would collide")
            sheets.append(
                {
                    "name": stem,
                    "frames": grabbed["frames"],
                    "durations": grabbed["durations"],
                    "tags": grabbed["tags"],
                }
            )
        atlas, data = build_atlas(sheets, os.path.basename(out_png), padding)
        json_path = out_json or os.path.splitext(out_png)[0] + ".json"
        for path in (out_png, json_path):
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
        with open(out_png, "wb") as f:
            f.write(encode_png(atlas))
        with open(json_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2)
        return {
            "png": out_png,
            "json": json_path,
            "width": atlas.width,
            "height": atlas.height,
            "frames": len(data["frames"]),
        }
