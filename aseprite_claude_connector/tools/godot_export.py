"""Godot export: a sprite sheet plus a ``SpriteFrames`` resource, in one action.

``export_godot`` writes a horizontal sheet and a ``.tres`` beside it, with one
animation per tag. Aseprite's frame timing maps onto Godot's as ``speed`` (the
fastest frame) plus a ``duration`` multiplier per frame. Targets Godot 4.
"""

from __future__ import annotations

import json
import os

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from . import state
from ._common import ToolError, run

_EXPORT = """
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
local durations = {}
for i, f in ipairs(s.frames) do durations[i] = math.floor(f.duration * 1000 + 0.5) end
local directions = {
  [AniDir.FORWARD] = "forward", [AniDir.REVERSE] = "reverse",
  [AniDir.PING_PONG] = "pingpong", [AniDir.PING_PONG_REVERSE] = "pingpong_reverse",
}
local tags = {}
for i, t in ipairs(s.tags) do
  tags[i] = {
    name = t.name, from = t.fromFrame.frameNumber, to = t.toFrame.frameNumber,
    direction = directions[t.aniDir], repeats = t.repeats,
  }
end
return J({ width = s.width, height = s.height, durations = durations, tags = tags })
"""


def frame_order(first: int, last: int, direction: str) -> list[int]:
    """1-based frame numbers for one pass of a tag, with no doubled frame at the
    turnaround of a ping-pong, which matches how Aseprite plays it."""
    forward = list(range(first, last + 1))
    if direction == "reverse":
        return forward[::-1]
    if direction == "pingpong":
        return forward + forward[-2:0:-1]
    if direction == "pingpong_reverse":
        return forward[::-1] + forward[1:-1]
    return forward


def animations(durations: list[int], tags: list[dict]) -> list[dict]:
    """One animation per tag, or a single looping ``default`` when there are none.
    A tag with a repeat count plays that many passes and then stops."""
    if not tags:
        order = list(range(1, len(durations) + 1))
        return [{"name": "default", "frames": order, "loop": True}]
    out, seen = [], {}
    for tag in tags:
        name = tag["name"] or "tag"
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:  # Godot keys animations by name
            name = f"{name}_{seen[name]}"
        order = frame_order(tag["from"], tag["to"], tag.get("direction") or "forward")
        repeats = int(tag.get("repeats") or 0)
        out.append({"name": name, "frames": order * max(repeats, 1), "loop": repeats == 0})
    return out


def build_tres(res_path: str, width: int, height: int, durations: list[int], anims: list[dict]):
    """The text of a Godot 4 ``SpriteFrames`` resource."""
    used = sorted({n for anim in anims for n in anim["frames"]})
    lines = [
        f'[gd_resource type="SpriteFrames" load_steps={len(used) + 2} format=3]',
        "",
        f'[ext_resource type="Texture2D" path={json.dumps(res_path)} id="1_sheet"]',
        "",
    ]
    for n in used:
        lines += [
            f'[sub_resource type="AtlasTexture" id="frame_{n}"]',
            'atlas = ExtResource("1_sheet")',
            f"region = Rect2({(n - 1) * width}, 0, {width}, {height})",
            "",
        ]
    entries = []
    for anim in anims:
        base = min(durations[n - 1] for n in anim["frames"])
        frames = ", ".join(
            f'{{"duration": {round(durations[n - 1] / base, 3)}, '
            f'"texture": SubResource("frame_{n}")}}'
            for n in anim["frames"]
        )
        entries.append(
            f'{{"frames": [{frames}], "loop": {"true" if anim["loop"] else "false"}, '
            f'"name": &{json.dumps(anim["name"])}, "speed": {round(1000 / base, 3)}}}'
        )
    lines += ["[resource]", f"animations = [{', '.join(entries)}]", ""]
    return "\n".join(lines)


def res_path_for(png_path: str) -> tuple[str, bool]:
    """The sheet's ``res://`` path, from the nearest ``project.godot`` above it.
    Returns the path and whether a project was found."""
    full = os.path.abspath(png_path)
    folder = os.path.dirname(full)
    while True:
        if os.path.isfile(os.path.join(folder, "project.godot")):
            return "res://" + os.path.relpath(full, folder).replace(os.sep, "/"), True
        parent = os.path.dirname(folder)
        if parent == folder:
            return "res://" + os.path.basename(full), False
        folder = parent


def export(png_path: str, file: str | None = None, *, tres: str = "always") -> dict:
    """Write the sheet, and its ``.tres`` when ``tres`` says so: ``always``, ``animated``
    (more than one frame), or ``never``."""
    info = run(lua_locals(OUT=png_path) + _EXPORT, mutates=False, file=file, save=False)
    if not isinstance(info, dict):
        raise ToolError("sprite sheet export failed")
    res_path, found = res_path_for(png_path)
    anims = animations(info["durations"], info.get("tags") or [])
    result = {
        "png": png_path,
        "png_exists": os.path.isfile(png_path),
        "res_path": res_path,
        "project_found": found,
        "frames": len(info["durations"]),
        "frame_size": {"width": info["width"], "height": info["height"]},
        "animations": [a["name"] for a in anims],
    }
    if tres == "always" or (tres == "animated" and len(info["durations"]) > 1):
        text = build_tres(res_path, info["width"], info["height"], info["durations"], anims)
        tres_path = os.path.splitext(png_path)[0] + ".tres"
        with open(tres_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        result["tres"] = tres_path
    state.set_last("export", result)
    return result


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Export to Godot", destructiveHint=False))
    def export_godot(png_path: str, file: str | None = None) -> dict:
        """Export a horizontal sprite sheet AND a Godot 4 ``SpriteFrames`` ``.tres``
        beside it, with one animation per tag, keeping each frame's timing, the tag's
        direction, and its repeat count. No tags gives one looping ``default``
        animation. Export inside a Godot project and the ``res://`` path is worked out
        from ``project.godot``; otherwise ``project_found`` is false and the file must
        sit at the project root. For sharp pixels, set the node's Texture Filter to
        Nearest. Headless: pass ``file``."""
        if not png_path.lower().endswith(".png"):
            raise ToolError("png_path must end in .png")
        return export(png_path, file)
