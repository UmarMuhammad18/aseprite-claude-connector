"""One-action export into a game project.

``export_to_game`` finds the engine from the folder, picks the project's sprites folder,
and writes what that engine needs, so the art is ready to select in the editor. The
folder is remembered, so later exports need no path. ``extension/game-export.lua`` is
the same export behind a button in Aseprite; the smoke test holds the two byte-equal.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from mcp.types import ToolAnnotations

from ..update_check import _cache_path
from . import godot_export, unity_export
from ._common import ToolError, run

# Existing folders to use, best first. The first entry is created if none exist.
_FOLDERS = {
    "godot": ("sprites", "assets/sprites", "art/sprites", "assets", "art"),
    "unity": ("Assets/Sprites", "Assets/Art"),
    "folder": ("sprites", "assets/sprites", "assets"),
}

_NAME_LUA = """
local s = app.activeSprite
if not s then error("no active sprite") end
return J({ filename = s.filename })
"""


def engine_at(folder: str) -> str | None:
    if os.path.isfile(os.path.join(folder, "project.godot")):
        return "godot"
    if os.path.isdir(os.path.join(folder, "Assets")) and os.path.isdir(
        os.path.join(folder, "ProjectSettings")
    ):
        return "unity"
    return None


def locate(game_dir: str) -> tuple[str, str]:
    """The engine and output folder for ``game_dir``. A project root gets its sprites
    folder; a folder picked deeper inside a project, or one already named sprites or
    assets, is used as it is."""
    start = os.path.abspath(game_dir)
    if not os.path.isdir(start):
        raise ToolError(f"game folder not found: {game_dir}")
    root = start
    while not engine_at(root) and os.path.dirname(root) != root:
        root = os.path.dirname(root)
    engine = engine_at(root)
    if engine and root != start:
        return engine, start
    if not engine and os.path.basename(start).lower() in ("sprites", "assets"):
        return "folder", start
    engine = engine or "folder"
    choices = [os.path.normpath(os.path.join(start, c)) for c in _FOLDERS[engine]]
    return engine, next((c for c in choices if os.path.isdir(c)), choices[0])


def sprite_name(filename: str, name: str | None) -> str:
    stem = name or os.path.splitext(re.split(r"[\\/]", filename or "")[-1])[0]
    if not stem:
        raise ToolError("this sprite has never been saved, so pass a name for the export")
    if re.search(r'[\\/:*?"<>|]', stem):
        raise ToolError(f"'{stem}' can't be used as a file name")
    return stem


def _remembered() -> Path:
    return Path(_cache_path()).with_name("game-folder.json")


def _recall() -> str | None:
    try:
        return json.loads(_remembered().read_text(encoding="utf-8"))["game_dir"]
    except (OSError, ValueError, KeyError):
        return None


def _remember(game_dir: str) -> None:
    path = _remembered()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"game_dir": game_dir}), encoding="utf-8")


def _next_step(engine: str, result: dict) -> str:
    if engine == "godot":
        if "tres" in result:
            return (
                "In Godot, add an AnimatedSprite2D and load the .tres as its Sprite Frames. "
                "Set Texture Filter to Nearest for sharp pixels."
            )
        return "In Godot, drag the PNG into the scene. Set Texture Filter to Nearest."
    if engine == "unity":
        return "In Unity, the sprites are already sliced: expand the PNG and drag one in."
    return "The PNG is ready to select in your game engine."


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Export to game", destructiveHint=False))
    def export_to_game(
        game_dir: str | None = None,
        name: str | None = None,
        pixels_per_unit: int = 100,
        file: str | None = None,
    ) -> dict:
        """Export the sprite into a game project in one action, ready to select in the
        engine. ``game_dir`` is the project folder; it's remembered, so leave it out
        after the first time. Godot is detected from ``project.godot``, Unity from
        ``Assets`` plus ``ProjectSettings``, and any other folder gets a plain sheet.
        Art goes in the project's existing sprites or assets folder, or a new
        ``sprites`` (``Assets/Sprites`` in Unity). Godot gets a PNG, plus a
        ``SpriteFrames`` ``.tres`` if animated. Unity gets a PNG and a pre-sliced
        ``.meta``, using ``pixels_per_unit``, and exporting again keeps the references
        to it working. ``name`` defaults to the sprite's file name. Headless: pass
        ``file``."""
        game_dir = game_dir or _recall()
        if not game_dir:
            raise ToolError("no game folder yet: pass game_dir once and it's remembered")
        engine, folder = locate(game_dir)
        info = run(_NAME_LUA, file=file)
        stem = sprite_name(info["filename"] if isinstance(info, dict) else "", name)
        os.makedirs(folder, exist_ok=True)
        png = os.path.join(folder, stem + ".png")
        if engine == "unity":
            result = unity_export.export_sheet(png, pixels_per_unit, file=file)
        else:
            tres = "animated" if engine == "godot" else "never"
            result = godot_export.export(png, file, tres=tres)
        _remember(os.path.abspath(game_dir))
        return {**result, "engine": engine, "next_step": _next_step(engine, result)}
