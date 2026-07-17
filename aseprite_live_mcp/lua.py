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
-- Depth-first layer lookup: matches top-level layers, then descends into
-- groups. Accepts either a bare name ("Arm") or a group path ("Body/Arm").
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
  if name:find("/", 1, true) then
    local node, container = nil, s
    for part in name:gmatch("[^/]+") do
      node = nil
      for _, l in ipairs(container.layers) do
        if l.name == part then node = l; break end
      end
      if not node then return nil end
      container = node
    end
    return node
  end
  return walk(s.layers, name)
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


def build_lua(body: str, *, mutates: bool = False, undo_label: str = "AI edit") -> str:
    """Wrap a tool body (which must ``return`` a value) into a full Lua chunk.

    Mutating bodies run inside ``app.transaction`` so the edit is one undo step.
    """
    if mutates:
        return (
            LUA_PRELUDE
            + "\nlocal __r\n"
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
