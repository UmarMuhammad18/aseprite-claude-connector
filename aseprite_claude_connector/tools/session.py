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
from ._common import ToolError, new_pin, run, target

_OPEN = """
local sp = app.open(PATH)
if not sp then error("Aseprite could not open '" .. PATH .. "'") end
if PIN then sp.properties.claude_target = PIN end
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
local was = s.properties.claude_target
s:close()
return J({ closed = name, pin = was })
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
if not hit.properties.claude_target then hit.properties.claude_target = PIN end
return J({ pin = hit.properties.claude_target, active = hit.filename ~= "" and hit.filename or "(unsaved)", matched = how })
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
    pinned = (PIN ~= nil and sp.properties.claude_target == PIN),
    tags = (function()
      local names = {}
      for _, tg in ipairs(sp.tags) do names[#names + 1] = tg.name end
      return names
    end)(),
  }
end
return J({ sprites = out, count = #out })
"""


_PIN = """
local hit
if FILENAME then
  for _, sp in ipairs(app.sprites) do
    if sp.filename == FILENAME or app.fs.fileName(sp.filename) == FILENAME then hit = sp break end
  end
  if not hit then error("no open sprite matches '" .. FILENAME .. "'") end
elseif TAG then
  for _, sp in ipairs(app.sprites) do
    for _, tg in ipairs(sp.tags) do if tg.name == TAG then hit = sp end end
    if hit then break end
  end
  if not hit then error("no open sprite has a tag named '" .. TAG .. "'") end
else
  hit = app.activeSprite
  if not hit then error("no sprite is open") end
end
if not hit.properties.claude_target then hit.properties.claude_target = PIN end
app.activeSprite = hit
return J({ pin = hit.properties.claude_target,
  sprite = hit.filename ~= "" and hit.filename or "(unsaved)",
  width = hit.width, height = hit.height, frames = #hit.frames })
"""

# Untitled sprites are saved into the folder and become those files; sprites that
# already have a file are copied in, leaving their own file untouched.
_SAVE_ALL = """
local out, used = {}, {}
local function unique(name)
  local base, n = name, 1
  while used[name] or app.fs.isFile(app.fs.joinPath(FOLDER, name .. ".aseprite")) do
    n = n + 1
    name = base .. "-" .. n
  end
  used[name] = true
  return name
end
local wanted = nil
if ONLY then
  wanted = {}
  for n in ONLY:gmatch("[^\\n]+") do wanted[n] = true end
end
local function picked(sp)
  if not wanted then return true end
  if wanted[sp.filename] or wanted[app.fs.fileName(sp.filename)] then return true end
  for _, tg in ipairs(sp.tags) do if wanted[tg.name] then return true end end
  return false
end
for _, sp in ipairs(app.sprites) do
  local titled = sp.filename ~= "" and app.fs.fileExtension(sp.filename) ~= ""
  if picked(sp) and (ALL or not titled or sp.isModified) then
    local name
    if titled then name = app.fs.fileTitle(sp.filename)
    elseif #sp.tags > 0 then name = sp.tags[1].name
    else name = "sprite" end
    name = unique((name:gsub("[^%w%-_ ]", "_")))
    local path = app.fs.joinPath(FOLDER, name .. ".aseprite")
    if titled then sp:saveCopyAs(path) else sp:saveAs(path) end
    out[#out + 1] = { file = path, copy = titled }
  end
end
return J({ saved = out, count = #out })
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
        editor and makes it the sprite Claude works on. Headless: each call is a fresh process, so this is a
        "can Aseprite read this file" probe returning the file's info — to
        edit a file headless, pass it as the ``file`` argument of the editing
        tools instead."""
        if not os.path.isfile(path):
            raise ToolError(f"no file at '{path}'")
        pin = new_pin() if get_backend().name == "live" else None
        body = lua_locals(PATH=path, PIN=pin) + _OPEN
        made = run(body, follow_pin=False)
        if pin:
            target.pin = pin
        return made

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
        made = run(body)
        if made.pop("pin", None) == target.pin:
            target.pin = None
        return made

    @mcp.tool(annotations=ToolAnnotations(title="Set active sprite", idempotentHint=True))
    def set_active_sprite(filename: str) -> dict:
        """Live editor only: make one of the open documents active, found by
        exact filename or basename match (e.g. "turret.aseprite"). Returns
        which sprite matched and how. Subsequent tools operate on it, even if the
        artist clicks another tab. Unsaved sprites share a name: pick those with
        ``pin_sprite``."""
        _require_live()
        body = lua_locals(NAME=filename, PIN=new_pin()) + _SET_ACTIVE
        made = run(body, follow_pin=False)
        target.pin = made.pop("pin")
        return made

    @mcp.tool(annotations=ToolAnnotations(title="Pin the sprite to work on", idempotentHint=True))
    def pin_sprite(
        filename: str | None = None, tag: str | None = None, unpin: bool = False
    ) -> dict:
        """Live editor only: choose the sprite Claude's edits go to. Every tool then
        works on it even while the artist looks at another tab. Pick it by
        ``filename`` (full path or basename), by a ``tag`` it has (the way to tell
        unsaved sprites apart), or give neither to pin the sprite the artist has open
        now ("work on this one"). ``unpin`` goes back to following whichever sprite
        is active. Sprites Claude creates or opens are pinned on their own."""
        _require_live()
        if unpin:
            target.pin = None
            return {"pinned": None}
        body = lua_locals(FILENAME=filename, TAG=tag, PIN=new_pin()) + _PIN
        made = run(body, follow_pin=False)
        target.pin = made.pop("pin")
        return {"pinned": made}

    @mcp.tool(annotations=ToolAnnotations(title="Save all open sprites", openWorldHint=True))
    def save_all_sprites(
        folder: str, all_sprites: bool = False, only: list[str] | None = None
    ) -> dict:
        """Live editor only: save open work into ``folder`` as ``.aseprite`` files, so
        nothing is lost when tabs are closed. Unsaved sprites are saved there and
        become those files (named after their first tag); sprites that already have
        a file and unsaved changes are COPIED there, leaving their own file
        untouched. ``all_sprites`` copies unchanged ones too. ``only`` limits it to
        sprites with these filenames or tags. Never overwrites: a taken name gets a
        number."""
        _require_live()
        if not os.path.isdir(folder):
            raise ToolError(f"no folder at {folder}")
        body = (
            lua_locals(
                FOLDER=os.path.abspath(folder),
                ALL=bool(all_sprites),
                ONLY="\n".join(only) if only else None,
            )
            + _SAVE_ALL
        )
        return run(body, follow_pin=False)

    @mcp.tool(annotations=ToolAnnotations(title="List open sprites", readOnlyHint=True))
    def list_sprites() -> dict:
        """Live editor only: list every open document — filename (or
        "(unsaved)"), size, frame/layer counts, tags, unsaved-changes flag, which
        one is active in the editor, and which one Claude's edits go to
        (``pinned``)."""
        _require_live()
        return run(lua_locals(PIN=target.pin) + _LIST, follow_pin=False)
