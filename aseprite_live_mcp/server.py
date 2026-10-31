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
    batch,
    brushes,
    canvas,
    cels,
    color,
    draw,
    editor,
    export,
    filters,
    frames,
    inspect,
    isometric,
    layers,
    live,
    look,
    lua_escape,
    palette,
    prompts,
    resources,
    selection,
    session,
    shading,
    slices,
    tags,
    tilemaps,
    transform,
    unity_export,
)
from .update_check import start_background_check

_INSTRUCTIONS = """\
Drive Aseprite from an AI agent. Tools operate on the *active sprite*: the live
editor's active document (live backend) or a file you pass via `file` (headless
backend). Mutating tools are one undo step each. Start with `status`, then
`get_sprite_info`. Colors are #rrggbb or #rrggbbaa. Use `look` to see the canvas
as an image, and check your work with it rather than editing blind.
"""

# Tool modules (each exposes register(mcp)).
_TOOL_MODULES = (
    inspect,
    look,
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
    export,
    unity_export,
    artqa,
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
        "aseprite-live-mcp",
        instructions=_INSTRUCTIONS,
        website_url="https://github.com/oaktreegames/aseprite-live-mcp",
    )
    # FastMCP doesn't forward a version, so serverInfo would report the SDK's —
    # set the lowlevel server's version so clients see the real release.
    mcp._mcp_server.version = __version__
    for module in _TOOL_MODULES + _EXTRA_MODULES:
        module.register(mcp)
    return mcp


def main() -> None:
    # Touch config early so a bad env fails loudly at startup, on stderr.
    load_config()
    # Fire-and-forget daily update check (never blocks; ASEPRITE_MCP_NO_UPDATE_CHECK=1 disables).
    start_background_check()
    build_server().run(transport="stdio")
