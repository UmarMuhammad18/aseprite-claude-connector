"""Layer tools."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from ..lua import lua_locals
from ._common import ToolError, run

# User-facing blend-mode name -> Aseprite BlendMode enum key.
_BLEND_MODES = {
    "normal": "NORMAL",
    "multiply": "MULTIPLY",
    "screen": "SCREEN",
    "overlay": "OVERLAY",
    "darken": "DARKEN",
    "lighten": "LIGHTEN",
    "color_dodge": "COLOR_DODGE",
    "color_burn": "COLOR_BURN",
    "hard_light": "HARD_LIGHT",
    "soft_light": "SOFT_LIGHT",
    "difference": "DIFFERENCE",
    "exclusion": "EXCLUSION",
    "hue": "HSL_HUE",
    "saturation": "HSL_SATURATION",
    "color": "HSL_COLOR",
    "luminosity": "HSL_LUMINOSITY",
    "addition": "ADDITION",
    "subtract": "SUBTRACT",
    "divide": "DIVIDE",
}

_ADD = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = s:newLayer()
if NAME ~= nil then l.name = NAME end
return J({ name = l.name, layers = #s.layers })
"""

_ADD_GROUP = """
local s = app.activeSprite
if not s then error("no active sprite") end
local g = s:newGroup()
if NAME ~= nil then g.name = NAME end
return J({ name = g.name, group = true })
"""

_MOVE_TO_GROUP = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, NAME)
if not l then error("no layer named '" .. NAME .. "'") end
local g = findLayer(s, GROUP)
if not g then error("no group named '" .. GROUP .. "'") end
if not g.isGroup then error("'" .. GROUP .. "' is a layer, not a group") end
l.parent = g
return J({ layer = NAME, group = GROUP })
"""

_LIST = """
local s = app.activeSprite
if not s then error("no active sprite") end
local function walk(layers, prefix)
  local out = {}
  for i = #layers, 1, -1 do
    local l = layers[i]
    local entry = {
      name = l.name, path = prefix .. l.name,
      visible = l.isVisible, opacity = l.opacity or 255,
    }
    if l.isGroup then
      entry.kind = "group"
      entry.children = walk(l.layers, prefix .. l.name .. "/")
    elseif l.isTilemap then
      entry.kind = "tilemap"
    else
      entry.kind = "image"
    end
    out[#out + 1] = entry
  end
  return out
end
return J({ layers = walk(s.layers, "") })
"""

_DELETE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, NAME)
if not l then error("no layer named '" .. NAME .. "'") end
s:deleteLayer(l)
return J({ deleted = NAME, layers = #s.layers })
"""

_RENAME = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, OLD)
if not l then error("no layer named '" .. OLD .. "'") end
l.name = NEW
return J({ renamed = NEW })
"""

_VISIBILITY = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, NAME)
if not l then error("no layer named '" .. NAME .. "'") end
l.isVisible = VISIBLE
return J({ name = NAME, visible = VISIBLE })
"""

_OPACITY = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, NAME)
if not l then error("no layer named '" .. NAME .. "'") end
l.opacity = OPACITY
return J({ name = NAME, opacity = OPACITY })
"""

_FLATTEN = """
local s = app.activeSprite
if not s then error("no active sprite") end
s:flatten()
return J({ flattened = true, layers = #s.layers })
"""

_BLEND = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, NAME)
if not l then error("no layer named '" .. NAME .. "'") end
local bm = BlendMode[MODE]
if bm == nil then error("unknown blend mode: " .. MODE) end
l.blendMode = bm
return J({ name = NAME, blendMode = string.lower(MODE) })
"""

_DUP = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, NAME)
if not l then error("no layer named '" .. NAME .. "'") end
app.activeLayer = l
local before = #s.layers
app.command.DuplicateLayer()
return J({ duplicated = NAME, layers = #s.layers, created = #s.layers - before })
"""

_MERGE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, NAME)
if not l then error("no layer named '" .. NAME .. "'") end
if l.stackIndex <= 1 then error("cannot merge '" .. NAME .. "' down (no layer beneath it)") end
app.activeLayer = l
app.command.MergeDownLayer()
return J({ merged = NAME, layers = #s.layers })
"""

_MOVE = """
local s = app.activeSprite
if not s then error("no active sprite") end
local l = findLayer(s, NAME)
if not l then error("no layer named '" .. NAME .. "'") end
local n = #s.layers
local target = l.stackIndex
if DIR == "up" then target = math.min(n, l.stackIndex + 1)
elseif DIR == "down" then target = math.max(1, l.stackIndex - 1)
elseif DIR == "top" then target = n
elseif DIR == "bottom" then target = 1
else error("direction must be up | down | top | bottom") end
l.stackIndex = target
return J({ name = NAME, stackIndex = l.stackIndex, layers = n })
"""

_IMPORT = """
local s = app.activeSprite
if not s then error("no active sprite (create or open one first)") end
local img = Image{ fromFile = PATH }
if not img then error("could not load image: " .. PATH) end
local l = s:newLayer()
if NAME ~= nil then l.name = NAME end
local frame = app.activeFrame or s.frames[1]
s:newCel(l, frame, img, Point(PX, PY))
return J({ layer = l.name, width = img.width, height = img.height, x = PX, y = PY })
"""


def register(mcp):
    @mcp.tool(annotations=ToolAnnotations(title="Add layer"))
    def add_layer(name: str | None = None, file: str | None = None) -> dict:
        """Add a new empty layer (optionally named) at the top of the stack."""
        body = lua_locals(NAME=name) + _ADD
        return run(body, mutates=True, undo_label="Add layer", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Add layer group"))
    def add_group(name: str | None = None, file: str | None = None) -> dict:
        """Add a layer group. Move layers into it with ``move_layer_to_group``;
        reference nested layers anywhere by name or as ``Group/Layer``."""
        body = lua_locals(NAME=name) + _ADD_GROUP
        return run(body, mutates=True, undo_label="Add group", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Move layer into group"))
    def move_layer_to_group(layer: str, group: str, file: str | None = None) -> dict:
        """Move a layer inside a layer group."""
        body = lua_locals(NAME=layer, GROUP=group) + _MOVE_TO_GROUP
        return run(body, mutates=True, undo_label="Move layer to group", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="List layers", readOnlyHint=True))
    def list_layers(file: str | None = None) -> dict:
        """The full layer tree, top of stack first: name, path, kind
        (image/group/tilemap), visibility, and opacity — including layers nested
        in groups (which ``get_sprite_info`` lists only at the top level)."""
        return run(_LIST, file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Delete layer", destructiveHint=True))
    def delete_layer(name: str, file: str | None = None) -> dict:
        """Delete the layer with the given name."""
        body = lua_locals(NAME=name) + _DELETE
        return run(body, mutates=True, undo_label="Delete layer", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Rename layer", idempotentHint=True))
    def rename_layer(old_name: str, new_name: str, file: str | None = None) -> dict:
        """Rename a layer."""
        body = lua_locals(OLD=old_name, NEW=new_name) + _RENAME
        return run(body, mutates=True, undo_label="Rename layer", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set layer visibility", idempotentHint=True))
    def set_layer_visibility(name: str, visible: bool, file: str | None = None) -> dict:
        """Show or hide a layer."""
        body = lua_locals(NAME=name, VISIBLE=visible) + _VISIBILITY
        return run(body, mutates=True, undo_label="Layer visibility", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set layer opacity", idempotentHint=True))
    def set_layer_opacity(name: str, opacity: int, file: str | None = None) -> dict:
        """Set a layer's opacity (0-255)."""
        if not 0 <= opacity <= 255:
            raise ToolError("opacity must be 0-255")
        body = lua_locals(NAME=name, OPACITY=int(opacity)) + _OPACITY
        return run(body, mutates=True, undo_label="Layer opacity", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Flatten sprite", destructiveHint=True))
    def flatten_sprite(file: str | None = None) -> dict:
        """Flatten all layers into a single layer."""
        return run(_FLATTEN, mutates=True, undo_label="Flatten", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Set layer blend mode", idempotentHint=True))
    def set_layer_blend_mode(name: str, mode: str, file: str | None = None) -> dict:
        """Set a layer's blend mode. One of: normal, multiply, screen, overlay, darken,
        lighten, color_dodge, color_burn, hard_light, soft_light, difference,
        exclusion, hue, saturation, color, luminosity, addition, subtract, divide."""
        key = _BLEND_MODES.get(mode.strip().lower())
        if not key:
            raise ToolError(
                f"unknown blend mode '{mode}' (have: {', '.join(sorted(_BLEND_MODES))})"
            )
        body = lua_locals(NAME=name, MODE=key) + _BLEND
        return run(body, mutates=True, undo_label="Layer blend mode", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Duplicate layer"))
    def duplicate_layer(name: str, file: str | None = None) -> dict:
        """Duplicate a layer (with its cels) above the original."""
        body = lua_locals(NAME=name) + _DUP
        return run(body, mutates=True, undo_label="Duplicate layer", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Merge layer down", destructiveHint=True))
    def merge_layer_down(name: str, file: str | None = None) -> dict:
        """Merge a layer into the layer directly beneath it."""
        body = lua_locals(NAME=name) + _MERGE
        return run(body, mutates=True, undo_label="Merge layer down", file=file)

    @mcp.tool(annotations=ToolAnnotations(title="Move layer"))
    def move_layer(name: str, direction: str, file: str | None = None) -> dict:
        """Reorder a layer in the stack. ``direction`` is up | down | top | bottom
        (bottom = stack index 1)."""
        d = direction.strip().lower()
        if d not in ("up", "down", "top", "bottom"):
            raise ToolError("direction must be up | down | top | bottom")
        body = lua_locals(NAME=name, DIR=d) + _MOVE
        # Cels are compared by their place in the stack, so a reorder looks like every
        # pixel changing when none did.
        return run(body, mutates=True, undo_label="Move layer", file=file, capped=False)

    @mcp.tool(annotations=ToolAnnotations(title="Import image as layer"))
    def import_image_as_layer(
        image_path: str,
        layer_name: str | None = None,
        x: int = 0,
        y: int = 0,
        file: str | None = None,
    ) -> dict:
        """Import an external image file (PNG, etc.) into a new layer at (x, y) — a
        reference/trace layer for concept-art intake. One undo step. Headless: pass
        ``file``."""
        body = lua_locals(PATH=image_path, NAME=layer_name, PX=int(x), PY=int(y)) + _IMPORT
        return run(body, mutates=True, undo_label="Import image", file=file)
