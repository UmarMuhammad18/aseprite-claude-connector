"""FastMCP server assembly.

Targets the current stable MCP spec (2025-11-25); stdio transport for the local,
single-client case (Aseprite on your machine). The stateless 2026-07-28 revision
is tracked as forward-compat work, not claimed here.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .tools import (
    animate,
    artqa,
    batch,
    canvas,
    cels,
    color,
    draw,
    editor,
    export,
    frames,
    inspect,
    isometric,
    layers,
    lua_escape,
    palette,
    prompts,
    resources,
    selection,
    shading,
    slices,
    tags,
    transform,
    unity_export,
)

_INSTRUCTIONS = """\
Drive Aseprite from an AI agent. Tools operate on the *active sprite*: the live
editor's active document (live backend) or a file you pass via `file` (headless
backend). Mutating tools are one undo step each. Start with `status`, then
`get_sprite_info`. Colors are #rrggbb or #rrggbbaa.
"""

# Tool modules (each exposes register(mcp)).
_TOOL_MODULES = (
    inspect,
    canvas,
    layers,
    frames,
    cels,
    draw,
    palette,
    color,
    shading,
    isometric,
    selection,
    transform,
    slices,
    tags,
    animate,
    export,
    unity_export,
    artqa,
    batch,
    editor,
    lua_escape,
)

# Resource + prompt modules — the MCP-native integration layer.
_EXTRA_MODULES = (
    resources,
    prompts,
)


def build_server() -> FastMCP:
    mcp = FastMCP("aseprite-live-mcp", instructions=_INSTRUCTIONS)
    for module in _TOOL_MODULES + _EXTRA_MODULES:
        module.register(mcp)
    return mcp


def main() -> None:
    # Touch config early so a bad env fails loudly at startup, on stderr.
    load_config()
    build_server().run(transport="stdio")
