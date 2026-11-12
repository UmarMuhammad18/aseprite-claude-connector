"""FastMCP server assembly.

Targets the current stable MCP spec (2025-11-25); stdio transport for the local,
single-client case (Aseprite on your machine). The stateless 2026-07-28 revision
is tracked as forward-compat work, not claimed here.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import __version__
from .config import load_config
from .tools import (
    animate,
    artqa,
    atlas,
    atmosphere,
    batch,
    brushes,
    canvas,
    cels,
    character,
    cleanup,
    color,
    docs,
    draw,
    editor,
    export,
    filters,
    finish,
    frames,
    game_export,
    godot_export,
    inspect,
    isometric,
    layers,
    light,
    live,
    look,
    lua_escape,
    motion,
    palette,
    prompts,
    reference,
    resources,
    rig,
    safety,
    scene,
    selection,
    session,
    session_tools,
    shading,
    slices,
    tags,
    tilemaps,
    tiles,
    transform,
    unity_export,
)
from .update_check import start_background_check

_INSTRUCTIONS = """\
Drive Aseprite from an AI agent. Tools operate on the *active sprite*: the live
editor's active document (live backend) or a file you pass via `file` (headless
backend). Live, the sprite you create, open, or pick with `set_active_sprite` or
`pin_sprite` stays your target even if the artist clicks another tab;
`list_sprites` shows which. `save_all_sprites` keeps open work from being lost.
Mutating tools are one undo step each. Start with `status`, then
`get_sprite_info`. Colors are #rrggbb or #rrggbbaa. Use `look` to see the canvas
as an image, and check your work with it rather than editing blind. Use
`describe_sprite` for a one-call summary, `search_api_docs` before writing Lua, and
`edit_batch` to make a multi-step change one undo step. `select_frame` and
`select_layer` choose where edits land.
Use `export_to_game` to put art straight into a Godot or Unity project. When the
artist selects an area and asks you to fix it, use `edit_in_selection`. Use
`check_loop` before calling an animation finished.
To recreate a reference picture, start from `pixelate_reference` rather than
drawing it from memory, then refine by hand and check with `compare_to_reference`
until its worst areas are fixed. `clean_pixel_art` then makes it read as drawn.
To build a scene, `split_into_layers` separates its parts, `extend_scene` widens it
with its own texture, and `ambient_motion` brings it to life as a loop.
To recreate a character sheet, `split_sheet` makes one sprite per pose on one shared
palette. To make a character act, stack keyed tools on its frames: `bob_body`
(breathing, hops), `swing_part` (wings, arms), `draw_eyes` (looks, blinks, moods),
and `lift_symbols` ("!", "?", hearts on their own layer). Expressions are easy to
misread, so show 3-4 options when unsure. Keep a cast consistent with
`check_consistency` and `match_palettes`, and reuse the `style` `draw_eyes` returns.
For characters on part layers, `animate_parts` poses them. For maps, `make_seamless` then
`make_autotiles`. `relight_scene` makes time-of-day versions, `make_normal_map`
readies art for 2D lights, and `export_animation` writes a GIF or animated PNG.
For a landscape, `paint_sky` lays the sky (with `drift`, its clouds move),
`paint_mountains` stands ranges on the horizon, and `reflect_in_water` mirrors it all
into a lake. `add_fire` lights a fire, `add_glow` lights the scene from it, and
`add_rim_light` picks out the edge of a layer that faces a light. Give the sprite its
frames first: these loop over however many it has.
"""

# Tool modules (each exposes register(mcp)).
_TOOL_MODULES = (
    inspect,
    look,
    reference,
    scene,
    character,
    rig,
    light,
    atmosphere,
    tiles,
    finish,
    docs,
    safety,
    session,
    canvas,
    layers,
    frames,
    cels,
    draw,
    palette,
    color,
    shading,
    filters,
    brushes,
    isometric,
    selection,
    transform,
    slices,
    tags,
    tilemaps,
    animate,
    motion,
    export,
    unity_export,
    godot_export,
    game_export,
    atlas,
    artqa,
    cleanup,
    session_tools,
    batch,
    editor,
    live,
    lua_escape,
)

# Resource + prompt modules — the MCP-native integration layer.
_EXTRA_MODULES = (
    resources,
    prompts,
)


def build_server() -> FastMCP:
    mcp = FastMCP(
        "aseprite-claude-connector",
        instructions=_INSTRUCTIONS,
        website_url="https://github.com/UmarMuhammad18/aseprite-claude-connector",
    )
    # FastMCP doesn't forward a version, so serverInfo would report the SDK's —
    # set the lowlevel server's version so clients see the real release.
    mcp._mcp_server.version = __version__
    for module in _TOOL_MODULES + _EXTRA_MODULES:
        module.register(mcp)
    return mcp


def main() -> None:
    # Touch config early so a bad env fails loudly at startup, on stderr.
    config = load_config()
    if config.relay_autostart:
        from .relay import ensure_running

        ensure_running()
    # Fire-and-forget daily update check (never blocks; ASEPRITE_MCP_NO_UPDATE_CHECK=1 disables).
    start_background_check()
    build_server().run(transport="stdio")
