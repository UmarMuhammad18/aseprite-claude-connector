"""Live-editor tools — the bridge as a two-way surface, not just a batch target.

Everything here needs the running editor (GUI). Interactive tools are
**two-phase and non-blocking** by design: a `*_start`-style call registers UI or
listeners and returns immediately; a matching poll call fetches the outcome.
Blocking inside a bridge command would stall Aseprite's event loop and the
relay heartbeat — never do it.

State between calls lives in the bridge script's Lua environment under the
``__almcp`` global table (verified to persist across relay execs).
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..backends import get_backend
from ..lua import lua_locals
from ._common import ToolError, run

_LIVE_GUARD = """
if not app.isUIAvailable then error("this tool needs the live editor (GUI)") end
__almcp = __almcp or {}
"""

_EDITOR_STATE = (
    _LIVE_GUARD
    + """
local ed = app.editor
if not ed then error("no active sprite editor") end
local sp = ed.spritePos
return J({
  zoom = ed.zoom, scroll = { x = ed.scroll.x, y = ed.scroll.y },
  sprite_pos = { x = sp.x, y = sp.y },
  sprite = ed.sprite and ed.sprite.filename or nil,
})
"""
)

_SET_VIEW = (
    _LIVE_GUARD
    + """
local ed = app.editor
if not ed then error("no active sprite editor") end
if ZOOM ~= nil then ed.zoom = ZOOM end
if SX ~= nil and SY ~= nil then ed.scroll = { x = SX, y = SY } end
return J({ zoom = ed.zoom, scroll = { x = ed.scroll.x, y = ed.scroll.y } })
"""
)

_SET_SYMMETRY = (
    _LIVE_GUARD
    + """
local s = app.activeSprite
if not s then error("no active sprite") end
local docPref = app.preferences.document(s)
local modes = { none = 0, horizontal = 1, vertical = 2, both = 3 }
docPref.symmetry.mode = modes[MODE]
if XA ~= nil then docPref.symmetry.x_axis = XA end
if YA ~= nil then docPref.symmetry.y_axis = YA end
-- make the symmetry options visible in the context bar so the user sees it
if MODE ~= "none" then app.preferences.symmetry_mode.enabled = true end
app.refresh()
return J({ mode = MODE, x_axis = docPref.symmetry.x_axis, y_axis = docPref.symmetry.y_axis })
"""
)

_ASK_POINT = (
    _LIVE_GUARD
    + """
local ed = app.editor
if not ed then error("no active sprite editor") end
__almcp.point = { done = false }
ed:askPoint{
  title = TITLE,
  onclick = function(ev)
    __almcp.point = { done = true, x = ev.point.x, y = ev.point.y }
  end,
  oncancel = function(ev)
    __almcp.point = { done = true, cancelled = true }
  end,
}
return J({ asking = true, title = TITLE })
"""
)

_POLL_POINT = (
    _LIVE_GUARD
    + """
local p = __almcp.point
if not p then return J({ done = false, note = "no ask_point pending" }) end
return J(p)
"""
)

# Editor:cancel() does NOT fire the askPoint oncancel callback (verified live on
# 1.3.17.2), so this marks the state itself.
_CANCEL_POINT = (
    _LIVE_GUARD
    + """
local ed = app.editor
if ed then pcall(function() ed:cancel() end) end
__almcp.point = { done = true, cancelled = true }
return J({ cancelled = true })
"""
)

_SHOW_DIALOG = (
    _LIVE_GUARD
    + """
if __almcp.dlg then pcall(function() __almcp.dlg:close() end) end
__almcp.dialog = { done = false }
local dlg = Dialog{ title = TITLE }
__almcp.dlg = dlg
dlg:label{ id = "msg", text = MESSAGE }
for _, opt in ipairs(OPTS) do
  dlg:button{ text = opt, onclick = function()
    __almcp.dialog = { done = true, choice = opt }
    dlg:close()
    __almcp.dlg = nil
  end }
end
dlg:show{ wait = false }
return J({ shown = true, options = OPTS })
"""
)

_POLL_DIALOG = (
    _LIVE_GUARD
    + """
local d = __almcp.dialog
if not d then return J({ done = false, note = "no dialog pending" }) end
return J(d)
"""
)

_WATCH_START = (
    _LIVE_GUARD
    + """
local s = app.activeSprite
if not s then error("no active sprite") end
if __almcp.watch and __almcp.watch.sprite and __almcp.watch.code then
  pcall(function() __almcp.watch.sprite.events:off(__almcp.watch.code) end)
end
__almcp.watch = { sprite = s, changes = 0, from_undo = 0 }
__almcp.watch.code = s.events:on("change", function(ev)
  local w = __almcp.watch
  if not w then return end
  w.changes = w.changes + 1
  if ev and ev.fromUndo then w.from_undo = w.from_undo + 1 end
end)
return J({ watching = s.filename ~= "" and s.filename or "(unsaved)" })
"""
)

_WATCH_POLL = (
    _LIVE_GUARD
    + """
local w = __almcp.watch
if not w then return J({ watching = false }) end
local out = { watching = true, changes = w.changes, from_undo = w.from_undo }
if RESET then w.changes = 0; w.from_undo = 0 end
return J(out)
"""
)

_WATCH_STOP = (
    _LIVE_GUARD
    + """
local w = __almcp.watch
if w and w.sprite and w.code then
  pcall(function() w.sprite.events:off(w.code) end)
end
__almcp.watch = nil
return J({ watching = false })
"""
)


def _require_live():
    if get_backend().name != "live":
        raise ToolError(
            "this tool needs the live backend (ASEPRITE_MCP_BACKEND=live with the "
            "relay + bridge running) — it drives the open editor's UI"
        )


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Editor view state", readOnlyHint=True))
    def get_editor_state() -> dict:
        """Live editor only: current zoom, scroll, and which sprite pixel the
        mouse is over — lets an agent know what the artist is looking at."""
        _require_live()
        return run(_EDITOR_STATE)

    @mcp.tool(annotations=ToolAnnotations(title="Set editor view", idempotentHint=True))
    def set_editor_view(
        zoom: float | None = None, scroll_x: int | None = None, scroll_y: int | None = None
    ) -> dict:
        """Live editor only: set the viewport zoom (1.0 = 100%) and/or scroll —
        e.g. zoom to the region you're about to edit so the artist can watch."""
        _require_live()
        if zoom is None and (scroll_x is None or scroll_y is None):
            raise ToolError("pass zoom, or both scroll_x and scroll_y")
        body = lua_locals(ZOOM=zoom, SX=scroll_x, SY=scroll_y) + _SET_VIEW
        return run(body)

    @mcp.tool(annotations=ToolAnnotations(title="Set symmetry", idempotentHint=True))
    def set_symmetry(
        mode: str, x_axis: float | None = None, y_axis: float | None = None
    ) -> dict:
        """Live editor only: set mirror-painting symmetry — ``mode`` is ``none``,
        ``horizontal`` (mirror across a vertical axis), ``vertical``, or
        ``both``; optionally place the axis lines. Affects the artist's
        subsequent brush strokes."""
        _require_live()
        if mode not in ("none", "horizontal", "vertical", "both"):
            raise ToolError("mode must be none, horizontal, vertical, or both")
        body = lua_locals(MODE=mode, XA=x_axis, YA=y_axis) + _SET_SYMMETRY
        return run(body)

    @mcp.tool(annotations=ToolAnnotations(title="Ask for a canvas point", openWorldHint=True))
    def ask_point(title: str = "Pick a point") -> dict:
        """Live editor only: ask the ARTIST to click a point on the canvas
        (pivot, anchor, paint origin). Returns immediately; call
        ``get_asked_point`` to collect the click. Human-in-the-loop, in-editor."""
        _require_live()
        body = lua_locals(TITLE=title) + _ASK_POINT
        return run(body)

    @mcp.tool(annotations=ToolAnnotations(title="Get asked point", readOnlyHint=True))
    def get_asked_point() -> dict:
        """Poll the result of ``ask_point``: ``done`` false while waiting, then
        the clicked ``x``/``y`` (or ``cancelled`` if the artist pressed Esc)."""
        _require_live()
        return run(_POLL_POINT)

    @mcp.tool(annotations=ToolAnnotations(title="Cancel point request", idempotentHint=True))
    def cancel_ask_point() -> dict:
        """Withdraw a pending ``ask_point`` request (e.g. the artist stepped
        away and you're moving on)."""
        _require_live()
        return run(_CANCEL_POINT)

    @mcp.tool(annotations=ToolAnnotations(title="Show choice dialog", openWorldHint=True))
    def show_choice_dialog(
        message: str, options: list, title: str = "Claude asks"
    ) -> dict:
        """Live editor only: pop a small dialog IN Aseprite with a message and
        up to 4 option buttons (e.g. approve/redo). Non-blocking — call
        ``get_dialog_choice`` to collect the artist's pick."""
        _require_live()
        if not options or len(options) > 4:
            raise ToolError("options must have 1-4 entries")
        opts = [str(o)[:40] for o in options]
        opts_lua = "local OPTS = {" + ",".join(
            '"' + o.replace("\\", "").replace('"', "'") + '"' for o in opts
        ) + "}\n"
        body = opts_lua + lua_locals(TITLE=title, MESSAGE=message) + _SHOW_DIALOG
        return run(body)

    @mcp.tool(annotations=ToolAnnotations(title="Get dialog choice", readOnlyHint=True))
    def get_dialog_choice() -> dict:
        """Poll the result of ``show_choice_dialog``: ``done`` false while the
        dialog is open, then the chosen button text."""
        _require_live()
        return run(_POLL_DIALOG)

    @mcp.tool(annotations=ToolAnnotations(title="Watch sprite changes"))
    def watch_changes() -> dict:
        """Live editor only: start counting edits the ARTIST makes to the active
        sprite (via ``Sprite.events``). Poll with ``get_watched_changes`` — e.g.
        wait for the artist to finish touching up, then re-run the QA sweep."""
        _require_live()
        return run(_WATCH_START)

    @mcp.tool(annotations=ToolAnnotations(title="Get watched changes", readOnlyHint=True))
    def get_watched_changes(reset: bool = False) -> dict:
        """Poll the change counter started by ``watch_changes`` (``reset=True``
        zeroes it after reading)."""
        _require_live()
        body = lua_locals(RESET=bool(reset)) + _WATCH_POLL
        return run(body)

    @mcp.tool(annotations=ToolAnnotations(title="Stop watching changes", idempotentHint=True))
    def stop_watching_changes() -> dict:
        """Detach the ``watch_changes`` listener."""
        _require_live()
        return run(_WATCH_STOP)
