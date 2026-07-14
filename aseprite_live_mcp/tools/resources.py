"""MCP resources — readable live-editor state.

Resources let a client read editor state without spending a tool call, and expose
things uniquely enabled by the live bridge: every open document (including unsaved,
untitled tabs), the active palette, and the last QA / Unity-export result. Across
the Aseprite-MCP field this resource set is essentially unoccupied — the headless
servers have no live state to expose.

Each resource returns a JSON string and never raises: on error it returns
``{"error": ...}`` so the resource is always readable.
"""
from __future__ import annotations

import json

from ._common import run
from . import state

_SPRITE_INFO = """
local s = app.activeSprite
if not s then return J({ error = "no active sprite" }) end
local mode = "indexed"
if s.colorMode == ColorMode.RGB then mode = "rgb"
elseif s.colorMode == ColorMode.GRAY then mode = "gray" end
local tags, layers = {}, {}
for i, t in ipairs(s.tags) do tags[i] = t.name end
for i, l in ipairs(s.layers) do layers[i] = l.name end
return J({ width = s.width, height = s.height, colorMode = mode,
  frames = #s.frames, layers = layers, tags = tags, filename = s.filename })
"""

_PALETTE = """
local s = app.activeSprite
if not s then return J({ error = "no active sprite" }) end
local pal = s.palettes[1]
local out = {}
for i = 0, #pal - 1 do
  local c = pal:getColor(i)
  out[#out + 1] = string.format("#%02x%02x%02x%02x", c.red, c.green, c.blue, c.alpha)
end
return J({ size = #pal, colors = out })
"""

_DOCS = """
local out = {}
for i, sp in ipairs(app.sprites) do
  out[i] = { filename = sp.filename, width = sp.width, height = sp.height,
    frames = #sp.frames, layers = #sp.layers }
end
return J({ documents = out, count = #out })
"""


def _safe(body: str) -> str:
    try:
        return json.dumps(run(body))
    except Exception as e:  # resources must always be readable
        return json.dumps({"error": str(e)})


def _safe_dump(value) -> str:
    try:
        return json.dumps(value)
    except Exception as e:
        return json.dumps({"error": str(e)})


def register(mcp):
    @mcp.resource(
        "aseprite://sprite/active", name="Active sprite",
        description="Size, color mode, and layer/frame/tag names of the active document.",
        mime_type="application/json",
    )
    def active_sprite() -> str:
        return _safe(_SPRITE_INFO)

    @mcp.resource(
        "aseprite://palette/active", name="Active palette",
        description="The active sprite's palette as #rrggbbaa hex colors.",
        mime_type="application/json",
    )
    def active_palette() -> str:
        return _safe(_PALETTE)

    @mcp.resource(
        "aseprite://docs", name="Open documents",
        description="Every document open in the editor, including unsaved/untitled tabs (live backend).",
        mime_type="application/json",
    )
    def open_documents() -> str:
        return _safe(_DOCS)

    @mcp.resource(
        "aseprite://qa/last", name="Last QA report",
        description="The most recent qa_sweep / measure_padding result (null until one runs).",
        mime_type="application/json",
    )
    def last_qa() -> str:
        return _safe_dump(state.get_last("qa"))

    @mcp.resource(
        "aseprite://export/last", name="Last export",
        description="The most recent Unity export result — written files and the .meta sprite manifest (null until one runs).",
        mime_type="application/json",
    )
    def last_export() -> str:
        return _safe_dump(state.get_last("export"))
