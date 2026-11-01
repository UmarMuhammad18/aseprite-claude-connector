"""Helpers for composing the Lua that gets executed inside Aseprite.

Two ideas keep the tool code safe and backend-agnostic:

1. ``LUA_PRELUDE`` injects a tiny JSON encoder ``J(value)`` so a tool's Lua can
   ``return J({...})`` and the Python side gets structured data back — in both the
   live and headless backends, over the same string channel.
2. ``build_lua`` wraps a mutating tool body in ``app.transaction(...)`` so each AI
   edit is exactly one undo step on the live editor (the project's core discipline).

Tool bodies never string-format Lua braces; they prepend typed locals with
``lua_locals(...)`` and reference them from a static Lua template.
"""

from __future__ import annotations

# A minimal JSON encoder in Lua (encode-only; handles nil/number/bool/string and
# array-or-object tables). %c in the gsub class covers all control chars.
LUA_PRELUDE = r"""
local function __enc(v)
  local t = type(v)
  if t == "nil" then return "null"
  elseif t == "number" then
    if v ~= v then return "null" end
    return string.format("%.14g", v)
  elseif t == "boolean" then return v and "true" or "false"
  elseif t == "string" then
    local s = v:gsub('[%c"\\]', function(c)
      local map = {['"']='\\"', ['\\']='\\\\', ['\n']='\\n', ['\r']='\\r', ['\t']='\\t'}
      return map[c] or string.format('\\u%04x', string.byte(c))
    end)
    return '"' .. s .. '"'
  elseif t == "table" then
    local n = 0
    for _ in pairs(v) do n = n + 1 end
    local len = #v
    if n == len then
      local parts = {}
      for i = 1, len do parts[i] = __enc(v[i]) end
      return "[" .. table.concat(parts, ",") .. "]"
    else
      local parts = {}
      for k, val in pairs(v) do parts[#parts + 1] = __enc(tostring(k)) .. ":" .. __enc(val) end
      return "{" .. table.concat(parts, ",") .. "}"
    end
  end
  return "null"
end
local function J(v) return __enc(v) end
-- Depth-first layer lookup: exact name first (so a layer literally named
-- "A/B" still resolves), then "Group/Layer" path interpretation.
local function findLayer(s, name)
  local function walk(layers, want)
    for _, l in ipairs(layers) do
      if l.name == want then return l end
      if l.isGroup then
        local hit = walk(l.layers, want)
        if hit then return hit end
      end
    end
    return nil
  end
  local exact = walk(s.layers, name)
  if exact then return exact end
  if name:find("/", 1, true) then
    local node, container = nil, s
    for part in name:gmatch("[^/]+") do
      if node ~= nil and not node.isGroup then return nil end
      node = nil
      for _, l in ipairs(container.layers) do
        if l.name == part then node = l; break end
      end
      if not node then return nil end
      container = node
    end
    return node
  end
  return nil
end
local function findSlice(s, name)
  for _, sl in ipairs(s.slices) do if sl.name == name then return sl end end
  return nil
end
local function activeImageLayer(s)
  local layer = app.activeLayer
  if not layer or not layer.isImage then
    layer = nil
    for i = #s.layers, 1, -1 do
      if s.layers[i].isImage then layer = s.layers[i]; break end
    end
    if not layer then layer = s:newLayer() end
  end
  return layer
end
-- editCel: composite the active layer+frame cel into a sprite-sized image, hand it
-- to fn to draw on, then write it back. Keeps every draw tool consistent.
local function editCel(fn)
  local s = app.activeSprite
  if not s then error("no active sprite") end
  local frame = app.activeFrame or s.frames[1]
  local layer = activeImageLayer(s)
  local existing = layer:cel(frame.frameNumber)
  local img = Image(s.width, s.height, s.colorMode)
  if existing then img:drawImage(existing.image, existing.position) end
  local r = fn(img, s)
  if existing then
    existing.image = img
    existing.position = Point(0, 0)
  else
    s:newCel(layer, frame, img, Point(0, 0))
  end
  return r
end
"""

# Safety rails: compare every cel before and after an edit, hidden layers included.
# Layers have no id in the API, so a cel is keyed by its place in the layer tree; a
# reordered layer therefore counts as changed, which errs on the safe side.
_RAILS_LUA = r"""
local function __snapshot(s)
  local out = {}
  local function walk(layers, prefix)
    for i, l in ipairs(layers) do
      local key = prefix .. i .. "/"
      if l.isGroup then
        walk(l.layers, key)
      else
        for _, c in ipairs(l.cels) do
          out[key .. c.frameNumber] = {
            image = c.image:clone(), x = c.position.x, y = c.position.y,
          }
        end
      end
    end
  end
  walk(s.layers, "")
  return out
end
local function __pixelAt(e, x, y)
  if not e then return 0 end
  local px, py = x - e.x, y - e.y
  if px < 0 or py < 0 or px >= e.image.width or py >= e.image.height then return 0 end
  return e.image:getPixel(px, py)
end
local function __celChanges(a, b, limit)
  if a and b and a.x == b.x and a.y == b.y and a.image.width == b.image.width
    and a.image.height == b.image.height and a.image.colorMode == b.image.colorMode
    and a.image:isEqual(b.image) then
    return 0
  end
  local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
  for _, e in ipairs({ a or b, b or a }) do
    x0, y0 = math.min(x0, e.x), math.min(y0, e.y)
    x1, y1 = math.max(x1, e.x + e.image.width), math.max(y1, e.y + e.image.height)
  end
  local n = 0
  for y = y0, y1 - 1 do
    for x = x0, x1 - 1 do
      if __pixelAt(a, x, y) ~= __pixelAt(b, x, y) then
        n = n + 1
        if n > limit then return n end
      end
    end
  end
  return n
end
local function __countChanges(before, after, limit, touched)
  local n = 0
  for key, a in pairs(before) do
    local c = __celChanges(a, after[key], limit - n)
    if c > 0 then touched[key] = true end
    n = n + c
    if n > limit then return n end
  end
  for key, b in pairs(after) do
    if not before[key] then
      local c = __celChanges(nil, b, limit - n)
      if c > 0 then touched[key] = true end
      n = n + c
      if n > limit then return n end
    end
  end
  return n
end
-- Which frames and layers changed, for the session journal.
local function __touchedReport(s, touched, pixels)
  local frames, layers, fseen, lseen = {}, {}, {}, {}
  for key in pairs(touched) do
    local place, frame = key:match("^(.*/)(%d+)$")
    frame = tonumber(frame)
    if not fseen[frame] then fseen[frame] = true; frames[#frames + 1] = frame end
    local node, container = nil, s
    for i in place:gmatch("(%d+)/") do
      node = container.layers and container.layers[tonumber(i)]
      if not node then break end
      container = node
    end
    if node and not lseen[node.name] then
      lseen[node.name] = true
      layers[#layers + 1] = node.name
    end
  end
  table.sort(frames)
  return J({ frames = frames, layers = layers, pixels = pixels })
end
"""


def lua_str(s: str) -> str:
    """Render a Python string as a safe double-quoted Lua string literal."""
    return (
        '"'
        + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        + '"'
    )


def lua_locals(**kw) -> str:
    """Emit ``local NAME = <literal>`` lines so tool templates stay brace-safe.

    Supports int/float/bool/str/None values.
    """
    lines = []
    for name, value in kw.items():
        if isinstance(value, bool):
            lit = "true" if value else "false"
        elif isinstance(value, (int, float)):
            lit = repr(value)
        elif value is None:
            lit = "nil"
        elif isinstance(value, str):
            lit = lua_str(value)
        else:
            raise ValueError(f"unsupported lua local type for {name}: {type(value)}")
        lines.append(f"local {name} = {lit}")
    return "\n".join(lines) + ("\n" if lines else "")


def _build_railed(body: str, undo_label: str, dry_run: bool, max_pixels: int) -> str:
    """Measure the edit inside its transaction. Raising from there makes Aseprite roll
    the transaction back, so a stopped edit leaves nothing on the undo stack."""
    rails = lua_locals(
        __DRY=dry_run,
        __CAP=max_pixels,
        __LABEL=undo_label,
        __MSG_DRY=_DRY_MSG,
        __MSG_CAP=_CAP_MSG,
        CHANGES_MARK=CHANGES_MARK,
    )
    return (
        LUA_PRELUDE
        + _RAILS_LUA
        + rails
        + """
local __s = app.activeSprite
if not __s then error("no active sprite (headless: pass file=)") end
local __limit = (__DRY or __CAP <= 0) and math.huge or __CAP
local __before = __snapshot(__s)
local __layers, __frames = #__s.layers, #__s.frames
local __r
local __touched, __changes = {}, nil
local __ok, __err = pcall(function()
  app.transaction(__LABEL, function()
    __r = (function()
"""
        + body
        + """
    end)()
    local n = __countChanges(__before, __snapshot(__s), __limit, __touched)
    __changes = __touchedReport(__s, __touched, n)
    if __DRY then
      error(string.format(__MSG_DRY, n, __layers, #__s.layers, __frames, #__s.frames), 0)
    elseif n > __limit then
      error(string.format(__MSG_CAP, __CAP), 0)
    end
  end)
end)
if not __ok then error(__err, 0) end
if __r == nil then return CHANGES_MARK .. __changes .. CHANGES_MARK end
return CHANGES_MARK .. __changes .. CHANGES_MARK .. tostring(__r)
"""
    )


# Fences the journal report off from the tool's own result on the way back to Python.
CHANGES_MARK = "@@changes@@"

_DRY_MSG = (
    "dry run: this edit would change %d pixels (layers %d -> %d, frames %d -> %d). "
    "Nothing was changed."
)
_CAP_MSG = (
    "refused: this edit would change more than %d pixels, so it was rolled back. "
    "Raise the cap with set_safety_rails if the change is intended."
)


def build_lua(
    body: str,
    *,
    mutates: bool = False,
    undo_label: str = "AI edit",
    dry_run: bool = False,
    max_pixels: int = 0,
) -> str:
    """Wrap a tool body (which must ``return`` a value) into a full Lua chunk.

    Mutating bodies run inside ``app.transaction`` so the edit is one undo step.
    ``dry_run`` and ``max_pixels`` (0 for no cap) add the safety rails.
    """
    if mutates and (dry_run or max_pixels > 0):
        return _build_railed(body, undo_label, dry_run, max_pixels)
    if mutates:
        return (
            LUA_PRELUDE
            # Every mutating body targets an existing sprite; failing here (not
            # inside app.transaction) keeps the error message readable.
            + "\nif not app.activeSprite then"
            + ' error("no active sprite (headless: pass file=)") end\n'
            + "local __r\n"
            # Name the transaction so the editor's undo entry reads "Undo <label>"
            # rather than a generic one — the one-edit-one-named-undo discipline.
            + "app.transaction("
            + lua_str(undo_label)
            + ", function()\n"
            + "  __r = (function()\n"
            + body
            + "\n  end)()\n"
            + "end)\n"
            + "return __r\n"
        )
    return LUA_PRELUDE + "\nreturn (function()\n" + body + "\nend)()\n"
