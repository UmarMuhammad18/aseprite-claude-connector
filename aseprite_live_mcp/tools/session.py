"""Multi-document session tools — open, save, close, switch, and list sprites.

The live editor is a multi-document surface: an agent juggling a sprite plus its
reference plus an export target needs to know what's open and steer which
document is active. Aseprite MCP Pro ships session management; no OSS live
server does — these tools close that gap. Headless is a fresh
``aseprite --batch`` process per call, so only ``open_sprite`` (as a file
probe) and ``save_sprite`` (as a copy-under-a-new-path) mean anything there;
``set_active_sprite`` and ``list_sprites`` require the live backend.
"""

from __future__ import annotations

import os

from mcp.types import ToolAnnotations

from ..backends import get_backend
from ..lua import lua_locals
from ._common import ToolError, run

_OPEN = """
local sp = app.open(PATH)
if not sp then error("Aseprite could not open '" .. PATH .. "'") end
return J({
  filename = sp.filename, width = sp.width, height = sp.height,
  frames = #sp.frames, layers = #sp.layers,
})
"""

# Untitled detection: a never-saved sprite's filename is a display name like
# "Sprite" (no extension) — verified on 1.3.17.2 — while any opened/saved
# document carries a real path with an extension.
_SAVE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local target = PATH
if target == nil then
  if s.filename == "" or app.fs.fileExtension(s.filename) == "" then
    error("sprite is untitled (never saved) — pass a path to save it to")
  end
  target = s.filename
end
s:saveAs(target)
return J({ saved = target })
"""

_CLOSE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local name = s.filename ~= "" and s.filename or "(unsaved)"
if s.isModified and not FORCE then
  error("'" .. name .. "' has unsaved changes — save_sprite first, or pass force=true to discard them")
end
s:close()
return J({ closed = name })
"""

_SET_ACTIVE = """
local hit, how = nil, nil
for _, sp in ipairs(app.sprites) do
  if sp.filename == NAME then hit = sp; how = "exact"; break end
end
if not hit then
  for _, sp in ipairs(app.sprites) do
    if app.fs.fileName(sp.filename) == NAME then hit = sp; how = "basename"; break end
  end
end
if not hit then error("no open sprite matches '" .. NAME .. "' (by full path or basename)") end
app.activeSprite = hit
return J({ active = hit.filename ~= "" and hit.filename or "(unsaved)", matched = how })
"""

_LIST = """
local act = app.activeSprite
local out = {}
for i, sp in ipairs(app.sprites) do
  out[i] = {
    filename = sp.filename ~= "" and sp.filename or "(unsaved)",
    width = sp.width, height = sp.height,
    frames = #sp.frames, layers = #sp.layers,
    modified = sp.isModified,
    active = (sp == act),
  }
end
return J({ sprites = out, count = #out })
"""


def _require_live():
    if get_backend().name != "live":
        raise ToolError(
            "this tool needs the live backend (ASEPRITE_MCP_BACKEND=live with the "
            "relay + bridge running) — it works across the editor's open documents"
        )


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Open sprite"))
    def open_sprite(path: str) -> dict:
        """Open a sprite file and make it the active document; returns its
        filename, size, and frame/layer counts. Live: opens a new tab in the
        editor. Headless: each call is a fresh process, so this is a
        "can Aseprite read this file" probe returning the file's info — to
        edit a file headless, pass it as the ``file`` argument of the editing
        tools instead."""
        if not os.path.isfile(path):
            raise ToolError(f"no file at '{path}'")
        body = lua_locals(PATH=path) + _OPEN
        return run(body)

    @mcp.tool(annotations=ToolAnnotations(title="Save sprite", openWorldHint=True))
    def save_sprite(path: str | None = None, file: str | None = None) -> dict:
        """Save the active sprite to disk: to ``path`` if given (save-as; the
        document's filename follows it), else to its own filename — errors if
        the sprite is untitled and no ``path`` is given. Live: persists the
        edits sitting in the open editor. Headless: mutating tools already
        save to ``file`` on their own; use this with both arguments to write a
        copy of ``file`` under a new ``path`` (the source file on disk stays
        untouched)."""
        body = lua_locals(PATH=path) + _SAVE
        return run(body, file=file, save=False)

    @mcp.tool(annotations=ToolAnnotations(title="Close sprite", destructiveHint=True))
    def close_sprite(force: bool = False) -> dict:
        """Close the active sprite. Errors if it has unsaved changes unless
        ``force=true`` — save_sprite first, or force to discard them. Aimed at
        the live editor (frees the tab); headless has no persistent session,
        so there is nothing to close there."""
        body = lua_locals(FORCE=bool(force)) + _CLOSE
        return run(body)

    @mcp.tool(annotations=ToolAnnotations(title="Set active sprite", idempotentHint=True))
    def set_active_sprite(filename: str) -> dict:
        """Live editor only: make one of the open documents active, found by
        exact filename or basename match (e.g. "turret.aseprite"). Returns
        which sprite matched and how. Subsequent tools operate on it."""
        _require_live()
        body = lua_locals(NAME=filename) + _SET_ACTIVE
        return run(body)

    @mcp.tool(annotations=ToolAnnotations(title="List open sprites", readOnlyHint=True))
    def list_sprites() -> dict:
        """Live editor only: list every open document — filename (or
        "(unsaved)"), size, frame/layer counts, unsaved-changes flag, and
        which one is active."""
        _require_live()
        return run(_LIST)
